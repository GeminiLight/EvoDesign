import copy
import json
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
    PublicErrorMixin,
)
from app.db.base import utc_now
from app.models.project import Project
from app.models.snapshot import Snapshot
from app.schemas.schema_contract import (
    DEFAULT_SCHEMA_EDITOR,
    REPLACE_SCHEMA_EDITORS,
    SchemaEditor,
    normalize_schema_editor,
)


class VersionConflictError(PublicErrorMixin, Exception):
    """Raised when optimistic lock version doesn't match."""

    default_public_detail = "version conflict"


class SchemaSyncError(PublicErrorMixin, ValueError):
    """Base class for expected schema sync request failures."""

    default_public_detail = "schema sync failed"


class InvalidSchemaPatchError(SchemaSyncError):
    """Raised when the submitted schema patch has the wrong shape."""

    default_public_detail = "schema_patch must be an object"


class InvalidProjectSchemaError(SchemaSyncError):
    """Raised when the stored project schema is not an object."""

    default_public_detail = "project latest_schema is invalid"


class InvalidSchemaEditorError(SchemaSyncError):
    """Raised when schema sync receives an unsupported editor source."""

    default_public_detail = "unsupported editor"


class BaseSnapshotRequiredError(SchemaSyncError):
    """Raised when overwrite mode lacks an explicit base snapshot."""

    default_public_detail = "base snapshot id required for overwrite"


class BaseSnapshotNotFoundError(SchemaSyncError):
    """Raised when a requested base snapshot is not part of the project."""

    default_public_detail = "base snapshot not found"


class ProjectUpdateFailedError(SchemaSyncError):
    """Raised when a project update affects no rows without a version conflict."""

    default_public_detail = "project update failed"


class SchemaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_project(self, user_id: str, project_id: str) -> Project:
        result = await self.db.execute(
            select(Project).where(
                Project.project_id == project_id,
                Project.user_id == user_id,
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            raise ProjectNotFoundException(
                public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            )
        return project

    async def _get_latest_snapshot(self, project_id: str) -> Snapshot | None:
        result = await self.db.execute(
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_base_snapshot(
        self,
        *,
        project_id: str,
        base_snapshot_id: str | None,
    ) -> Snapshot | None:
        if not base_snapshot_id:
            return None

        result = await self.db.execute(
            select(Snapshot).where(
                Snapshot.snapshot_id == base_snapshot_id,
                Snapshot.project_id == project_id,
            )
        )
        snapshot = result.scalar_one_or_none()
        if not snapshot:
            raise BaseSnapshotNotFoundError()
        return snapshot

    async def sync_schema(
        self,
        user_id: str,
        project_id: str,
        schema_patch: dict[str, Any],
        editor: str = DEFAULT_SCHEMA_EDITOR,
        base_snapshot_id: str | None = None,
        create_snapshot: bool = False,
        version: int | None = None,
    ) -> tuple["Project", "Snapshot"]:
        if not isinstance(schema_patch, dict):
            raise InvalidSchemaPatchError()
        editor = self._normalize_editor(editor)

        project = await self._get_project(user_id, project_id)
        latest_snapshot = await self._get_latest_snapshot(project.project_id)
        base_snapshot = await self._get_base_snapshot(
            project_id=project.project_id,
            base_snapshot_id=base_snapshot_id,
        )

        if not create_snapshot and not base_snapshot_id:
            raise BaseSnapshotRequiredError()

        current_schema = project.latest_schema or {}
        if not isinstance(current_schema, dict):
            raise InvalidProjectSchemaError()

        should_replace_schema = self._should_replace_schema(editor=editor)
        if should_replace_schema:
            next_schema = copy.deepcopy(schema_patch)
        else:
            next_schema = self._apply_json_merge_patch(current_schema, schema_patch)

        # Atomic version bump: UPDATE with SQL expression (version = COALESCE(version,1)+1)
        # so concurrent requests each get a unique monotonically-increasing version even
        # when the client sends the same (or no) version hint.
        now = utc_now()
        update_values = {
            "latest_schema": next_schema,
            "updated_at": now,
            "version": func.coalesce(Project.version, 1) + 1,
        }
        if should_replace_schema:
            update_values["canvas_engine"] = editor
        update_where = [
            Project.project_id == project.project_id,
            Project.user_id == user_id,
        ]
        if version is not None:
            update_where.append(Project.version == version)

        result = await self.db.execute(
            update(Project)
            .where(*update_where)
            .values(**update_values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            if version is not None:
                raise VersionConflictError(
                    f"version conflict: expected {version}, current version has changed"
                )
            raise ProjectUpdateFailedError()

        # Refresh the ORM object so callers see the DB-assigned version and timestamps
        # without triggering a second UPDATE on commit.
        await self.db.refresh(project)

        assessment_source = base_snapshot or latest_snapshot
        metrics = copy.deepcopy(assessment_source.metrics_scores) if assessment_source else None
        if metrics and next_schema != assessment_source.schema_blob:
            # Both save modes retain provenance without claiming that an edit
            # passed the original generation's verification loop.
            if isinstance(metrics.get("generation"), dict):
                metrics["generation"]["quality_status"] = "edited"
            else:
                metrics = None

        if create_snapshot:
            snapshot = Snapshot(
                project_id=project.project_id,
                parent_id=base_snapshot_id or (latest_snapshot.snapshot_id if latest_snapshot else None),
                schema_blob=next_schema,
                edit_source="HUMAN",
                thought_trace=self._build_thought_trace(editor=editor, mode="create"),
                metrics_scores=metrics,
            )
            self.db.add(snapshot)
            await self.db.flush()
            return project, snapshot

        target_snapshot: Snapshot | None = base_snapshot
        if target_snapshot is None:
            raise BaseSnapshotNotFoundError()

        target_snapshot.metrics_scores = metrics
        target_snapshot.schema_blob = next_schema
        target_snapshot.edit_source = "HUMAN"
        target_snapshot.thought_trace = self._build_thought_trace(
            editor=editor,
            mode="overwrite",
        )

        return project, target_snapshot

    def _apply_json_merge_patch(
        self,
        source: dict[str, Any],
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        target = copy.deepcopy(source)

        for key, value in patch.items():
            if value is None:
                target.pop(key, None)
                continue

            if isinstance(value, dict) and isinstance(target.get(key), dict):
                target[key] = self._apply_json_merge_patch(target[key], value)
                continue

            target[key] = copy.deepcopy(value)

        return target

    def _normalize_editor(self, editor: str | None) -> SchemaEditor:
        normalized_editor = normalize_schema_editor(editor)
        if normalized_editor is None:
            raise InvalidSchemaEditorError(f"unsupported editor: {editor!r}")
        return normalized_editor

    def _should_replace_schema(self, editor: SchemaEditor) -> bool:
        return editor in REPLACE_SCHEMA_EDITORS

    @staticmethod
    def _build_thought_trace(editor: str, mode: str) -> str:
        return json.dumps(
            {"editor": editor, "action": "schema_sync", "mode": mode},
            ensure_ascii=False,
        )
