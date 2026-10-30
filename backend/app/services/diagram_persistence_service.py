"""Diagram generation persistence service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from evo_diagram.canvas_environment import EditError

from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
)
from app.services.document_commit_service import commit_document, VersionConflictError, MissingVersionError
from app.services.document_service import effective_constraints, digest
from app.models.agent import AgentProposal
import copy
import time
from uuid import uuid4
from app.models.project import Project
from app.models.snapshot import Snapshot
from app.services.thumbnail_service import ThumbnailGenerationError, generate_svg_thumbnail


@dataclass(frozen=True)
class DiagramPersistenceInput:
    """Input required to persist a generated diagram result."""

    user_id: str
    context: str
    requirements: str | None
    project_id: str | None
    canvas_library: str
    workflow_result: Mapping[str, Any]
    base_version: int | None = None
    base_schema: dict[str, Any] | None = None


class DiagramPersistenceRequest(Protocol):
    """Request fields needed to persist a diagram generation result."""

    context: str
    requirements: str | None
    project_id: str | None
    canvas_library: str


@dataclass(frozen=True)
class PersistedDiagramResult:
    """Database identifiers created or updated for a generated diagram."""

    project_id: str
    snapshot_id: str | None
    thumbnail_url: str | None
    version: int | None = None
    proposal_id: str | None = None


ThumbnailGenerator = Callable[[dict[str, Any], str], str | None]


def build_diagram_persistence_input(
    *,
    user_id: str,
    request: DiagramPersistenceRequest,
    workflow_result: Mapping[str, Any],
) -> DiagramPersistenceInput:
    """Build the persistence contract shared by sync and streaming generation."""
    return DiagramPersistenceInput(
        user_id=user_id,
        context=request.context,
        requirements=request.requirements,
        project_id=request.project_id,
        canvas_library=request.canvas_library,
        workflow_result=workflow_result,
        base_version=getattr(request, "base_version", None),
        base_schema=getattr(request, "current_schema", None),
    )


class DiagramPersistenceService:
    """Persist generated diagram results into Project and Snapshot records."""

    def __init__(
        self,
        db: AsyncSession,
        thumbnail_generator: ThumbnailGenerator = generate_svg_thumbnail,
    ):
        self.db = db
        self.thumbnail_generator = thumbnail_generator

    async def persist_generation_result(
        self,
        payload: DiagramPersistenceInput,
    ) -> PersistedDiagramResult:
        """Persist a workflow result and return project/snapshot identifiers."""
        project = await self._resolve_project(payload)
        schema_blob = payload.workflow_result["schema_blob"]
        if payload.project_id and payload.base_version is None:
            raise MissingVersionError()
        try:
            snapshot = await commit_document(
                self.db, project, schema_blob,
                expected_version=payload.base_version if payload.project_id else project.version,
                source="AI_GEN", checkpoint=True,
                metrics=payload.workflow_result.get("metrics_scores"), canvas_library=payload.canvas_library,
                thought_trace=json.dumps(payload.workflow_result.get("thought_trace") or {}, ensure_ascii=False),
            )
        except (VersionConflictError, EditError):
            constraints = await effective_constraints(self.db, project)
            request_id = payload.workflow_result.get("request_id") or str(uuid4())
            proposal = AgentProposal(
                project_id=project.project_id, user_id=payload.user_id, author_kind="AI_GEN",
                operation_id="generation:" + str(request_id), request_hash=digest(schema_blob),
                base_version=payload.base_version, base_schema=copy.deepcopy(payload.base_schema or {}),
                candidate_schema=copy.deepcopy(schema_blob), constraints_hash=constraints["constraints_hash"],
                expires_at=time.time()+7*86400,
            )
            self.db.add(proposal)
            await self.db.flush()
            await self.db.refresh(project)
            return PersistedDiagramResult(project.project_id, None, project.thumbnail_url,
                                          project.version, proposal.proposal_id)
        self._update_thumbnail(project, schema_blob, payload.canvas_library)

        return PersistedDiagramResult(
            project_id=project.project_id,
            snapshot_id=snapshot.snapshot_id,
            thumbnail_url=project.thumbnail_url,
            version=project.version,
        )

    async def _resolve_project(self, payload: DiagramPersistenceInput) -> Project:
        if payload.project_id:
            result = await self.db.execute(
                select(Project).where(
                    Project.project_id == payload.project_id,
                    Project.user_id == payload.user_id,
                )
            )
            project = result.scalar_one_or_none()
            if not project:
                raise ProjectNotFoundException(
                    public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
                )
            return project

        project = Project(
            user_id=payload.user_id,
            # Requirements can include internal canvas instructions and DNA.
            # Name the project from the user's actual content instead.
            title=" ".join(payload.context.split())[:60] or "Untitled diagram",
            diagram_type="automated",
            canvas_engine=payload.canvas_library,
            source_text=payload.context,
        )
        self.db.add(project)
        await self.db.flush()
        return project

    async def _get_latest_snapshot(self, project_id: str) -> Snapshot | None:
        result = await self.db.execute(
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _update_thumbnail(
        self,
        project: Project,
        schema_blob: dict[str, Any],
        canvas_library: str,
    ) -> None:
        try:
            thumbnail = self.thumbnail_generator(schema_blob, canvas_library)
        except ThumbnailGenerationError as exc:
            project.thumbnail_url = None
            logger.warning("Thumbnail generation failed: {}", exc)
            return

        if thumbnail:
            project.thumbnail_url = thumbnail
