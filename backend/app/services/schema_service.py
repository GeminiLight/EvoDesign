import copy
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
    PublicErrorMixin,
)
from app.services.document_commit_service import commit_document, VersionConflictError
from app.models.project import Project
from app.models.snapshot import Snapshot
from app.schemas.schema_contract import (
    DEFAULT_SCHEMA_EDITOR,
    REPLACE_SCHEMA_EDITORS,
    SchemaEditor,
    normalize_schema_editor,
)


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

        assessment_source = base_snapshot or latest_snapshot
        metrics = copy.deepcopy(assessment_source.metrics_scores) if assessment_source else None
        if metrics and next_schema != assessment_source.schema_blob:
            # Both save modes retain provenance without claiming that an edit
            # passed the original generation's verification loop.
            if isinstance(metrics.get("generation"), dict):
                metrics["generation"]["quality_status"] = "edited"
            else:
                metrics = None

        snapshot = await commit_document(
            self.db, project, next_schema, expected_version=version, source="HUMAN",
            checkpoint=create_snapshot, base_snapshot=base_snapshot, metrics=metrics,
            canvas_library=editor if should_replace_schema else None,
            thought_trace=self._build_thought_trace(editor, "create" if create_snapshot else "overwrite"),
        )
        return project, snapshot

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
