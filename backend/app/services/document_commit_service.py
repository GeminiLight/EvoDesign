"""Single optimistic-write boundary shared by editors, generation and agents."""

import copy
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.models.project import Project
from app.models.snapshot import Snapshot
from app.core.exceptions import PublicErrorMixin


class VersionConflictError(PublicErrorMixin, Exception):
    default_public_detail = 'version conflict'


class MissingVersionError(PublicErrorMixin, ValueError):
    default_public_detail = 'Expected project version is required'


async def commit_document(
    db: AsyncSession, project: Project, schema: dict[str, Any], *,
    expected_version: int | None, source: str, checkpoint: bool = False,
    base_snapshot: Snapshot | None = None, metrics: dict[str, Any] | None = None,
    thought_trace: str | None = None, canvas_library: str | None = None,
) -> Snapshot:
    if expected_version is None:
        raise MissingVersionError()
    previous = copy.deepcopy(project.latest_schema or {})
    if source in {'AI_GEN', 'AGENT'} and (canvas_library or project.canvas_engine) == 'excalidraw':
        from evo_diagram.canvas_environment import assert_preserves_locks
        assert_preserves_locks(previous, schema)
    result = await db.execute(update(Project).where(
        Project.project_id == project.project_id, Project.user_id == project.user_id,
        Project.version == expected_version,
    ).values(latest_schema=copy.deepcopy(schema), version=Project.version + 1,
             updated_at=utc_now(), canvas_engine=canvas_library or project.canvas_engine)
      .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise VersionConflictError(f'version conflict: expected {expected_version}, current version has changed')
    # The conditional UPDATE serializes all remaining writes in this transaction.
    current = await db.get(Snapshot, project.current_snapshot_id) if project.current_snapshot_id else None
    if current is None:
        current = (await db.execute(select(Snapshot).where(Snapshot.project_id == project.project_id)
                                   .order_by(Snapshot.timestamp.desc(), Snapshot.snapshot_id.desc()).limit(1))).scalar_one_or_none()
    if checkpoint and previous and (current is None or current.schema_blob != previous):
        current = Snapshot(project_id=project.project_id, schema_blob=previous,
                           edit_source='HUMAN', is_checkpoint=True)
        db.add(current)
        await db.flush()
    elif checkpoint and current:
        current.is_checkpoint = True
    target = base_snapshot
    if checkpoint or target is None or target.is_checkpoint:
        target = Snapshot(project_id=project.project_id, parent_id=(base_snapshot or current).snapshot_id if (base_snapshot or current) else None,
                          schema_blob=copy.deepcopy(schema), edit_source=source, is_checkpoint=checkpoint,
                          metrics_scores=metrics, thought_trace=thought_trace)
        db.add(target)
    else:
        target.schema_blob = copy.deepcopy(schema)
        target.edit_source = source
        target.metrics_scores = metrics
        target.thought_trace = thought_trace
    await db.flush()
    await db.refresh(project)
    project.current_snapshot_id = target.snapshot_id
    from app.services.thumbnail_service import generate_svg_thumbnail, ThumbnailGenerationError
    try:
        project.thumbnail_url = generate_svg_thumbnail(schema, project.canvas_engine)
    except ThumbnailGenerationError:
        project.thumbnail_url = None
    await db.flush()
    return target
