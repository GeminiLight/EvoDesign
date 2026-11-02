"""Single optimistic-write boundary shared by editors, generation and agents."""

import asyncio
import copy
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.models.project import Project
from app.models.snapshot import Snapshot
from app.core.exceptions import PublicErrorMixin
from app.services.diagram_schema_inspection import (
    CONNECTOR_COLLECTION_KEYS,
    NODE_COLLECTION_KEYS,
    first_schema_collection,
)
from app.services.thumbnail_service import ThumbnailGenerationError, generate_svg_thumbnail

ThumbnailGenerator = Callable[[dict[str, Any], str], str | None]
# Small scenes render in well under a millisecond; larger ones go to a thread.
THUMBNAIL_INLINE_MAX_ITEMS = 200


class VersionConflictError(PublicErrorMixin, Exception):
    default_public_detail = 'version conflict'


class MissingVersionError(PublicErrorMixin, ValueError):
    default_public_detail = 'Expected project version is required'


class CanvasEngineChangeError(PublicErrorMixin, ValueError):
    default_public_detail = 'Cannot change the engine of a nonempty project'


def _live_items(schema: Any) -> list[Any]:
    return [
        item
        for keys in (NODE_COLLECTION_KEYS, CONNECTOR_COLLECTION_KEYS)
        for item in first_schema_collection(schema, keys)
        if not (isinstance(item, dict) and item.get('isDeleted'))
    ]


def has_live_content(schema: Any) -> bool:
    """Return whether a saved scene still shows any node or connector."""
    return bool(_live_items(schema))


async def _render_thumbnail(schema: dict[str, Any], engine: str,
                            generator: ThumbnailGenerator) -> str | None:
    try:
        if len(_live_items(schema)) > THUMBNAIL_INLINE_MAX_ITEMS:
            return await asyncio.to_thread(generator, schema, engine)
        return generator(schema, engine)
    except ThumbnailGenerationError:
        return None


async def commit_document(
    db: AsyncSession, project: Project, schema: dict[str, Any], *,
    expected_version: int | None, source: str, checkpoint: bool = False,
    base_snapshot: Snapshot | None = None, metrics: dict[str, Any] | None = None,
    thought_trace: str | None = None, canvas_library: str | None = None,
    thumbnail_generator: ThumbnailGenerator = generate_svg_thumbnail,
) -> Snapshot:
    if expected_version is None:
        raise MissingVersionError()
    # Same rule as ProjectService.update_project: the engine of a scene with
    # content is fixed, whichever write path (sync, generation, agent) tries.
    # A stale writer still gets the version conflict from the fenced UPDATE.
    if (canvas_library and canvas_library != project.canvas_engine
            and project.version == expected_version and has_live_content(project.latest_schema)):
        raise CanvasEngineChangeError(
            f'cannot change canvas engine {project.canvas_engine!r} -> {canvas_library!r} of a nonempty project'
        )
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
    if (checkpoint or target is None or target.is_checkpoint
        or (current is not None and target.snapshot_id != current.snapshot_id)):
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
    project.thumbnail_url = await _render_thumbnail(schema, project.canvas_engine, thumbnail_generator)
    await db.flush()
    return target
