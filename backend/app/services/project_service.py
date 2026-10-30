from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dna_rule import DnaRule
from app.models.project import Project
from app.models.snapshot import Snapshot
from app.models.agent import AgentConnection, AgentProposal
from app.core.exceptions import AppException
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest
from app.core.exceptions import ProjectNotFoundException


@dataclass(frozen=True)
class ProjectListRecord:
    """Project list data enriched with snapshot summary fields."""

    project_id: str
    title: str | None
    diagram_type: str | None
    canvas_engine: str
    source_text: str | None
    latest_schema: dict[str, Any] | None
    thumbnail_url: str | None
    created_at: datetime
    updated_at: datetime
    snapshot_count: int
    latest_snapshot_id: str | None
    version: int


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_snapshots(
        self,
        user_id: str,
        project_id: str,
        with_trace: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Snapshot], int, int]:
        project_result = await self.db.execute(
            select(Project).where(
                Project.project_id == project_id,
                Project.user_id == user_id,
            )
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise ProjectNotFoundException()

        offset = (page - 1) * page_size

        total_result = await self.db.execute(
            select(func.count(Snapshot.snapshot_id)).where(Snapshot.project_id == project_id)
        )
        total = total_result.scalar() or 0

        snapshots_result = await self.db.execute(
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.timestamp.desc())
            .offset(offset)
            .limit(page_size)
        )
        snapshots = list(snapshots_result.scalars().all())

        return snapshots, int(total), project.version

    async def list_projects(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ProjectListRecord], int]:
        """Return a list of projects with snapshot_count and latest_snapshot_id."""
        total_result = await self.db.execute(
            select(func.count(Project.project_id)).where(Project.user_id == user_id)
        )
        total = total_result.scalar() or 0

        snap_count_sq = (
            select(
                Snapshot.project_id,
                func.count(Snapshot.snapshot_id).label("snapshot_count"),
            )
            .group_by(Snapshot.project_id)
            .subquery()
        )

        latest_snapshot_id_sq = (
            select(Snapshot.snapshot_id)
            .where(Snapshot.project_id == Project.project_id)
            .order_by(Snapshot.timestamp.desc(), Snapshot.snapshot_id.desc())
            .limit(1)
            .correlate(Project)
            .scalar_subquery()
        )

        stmt = (
            select(
                Project,
                func.coalesce(snap_count_sq.c.snapshot_count, 0).label("snapshot_count"),
                func.coalesce(Project.current_snapshot_id, latest_snapshot_id_sq).label("latest_snapshot_id"),
            )
            .outerjoin(snap_count_sq, Project.project_id == snap_count_sq.c.project_id)
            .where(Project.user_id == user_id)
            .order_by(Project.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        projects: list[ProjectListRecord] = []
        for row in rows:
            project = row[0]
            snapshot_count = row[1]
            latest_snapshot_id = row[2]
            projects.append(
                ProjectListRecord(
                    project_id=project.project_id,
                    title=project.title,
                    diagram_type=project.diagram_type,
                    canvas_engine=project.canvas_engine,
                    source_text=project.source_text,
                    latest_schema=project.latest_schema,
                    thumbnail_url=project.thumbnail_url,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                    snapshot_count=int(snapshot_count),
                    latest_snapshot_id=latest_snapshot_id,
                    version=project.version,
                )
            )

        return projects, int(total)

    async def create_project(self, user_id: str, data: ProjectCreateRequest) -> Project:
        project = Project(
            user_id=user_id,
            title=data.title,
            diagram_type=data.diagram_type,
            canvas_engine=data.canvas_engine,
            source_text=data.source_text,
        )
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def get_project(self, user_id: str, project_id: str) -> Project:
        result = await self.db.execute(
            select(Project).where(
                Project.project_id == project_id,
                Project.user_id == user_id,
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            raise ProjectNotFoundException()
        return project

    async def update_project(
        self,
        user_id: str,
        project_id: str,
        data: ProjectUpdateRequest,
    ) -> Project:
        project = await self.get_project(user_id, project_id)

        changes_design = ((data.diagram_type is not None and data.diagram_type != project.diagram_type)
                          or (data.canvas_engine is not None and data.canvas_engine != project.canvas_engine))
        if changes_design:
            if data.canvas_engine and data.canvas_engine != project.canvas_engine and project.latest_schema:
                raise AppException('Create a new project to change the canvas engine', 422,
                                   public_detail='Cannot change the engine of a nonempty project')
            if data.version is None:
                raise AppException('Expected project version is required', 409,
                                   public_detail='Reload the project before changing its design settings')
            written = await self.db.execute(update(Project).where(Project.project_id == project_id,
                Project.user_id == user_id, Project.version == data.version).values(version=Project.version+1)
                .execution_options(synchronize_session=False))
            if written.rowcount != 1:
                raise AppException('Project version conflict', 409, public_detail='Project version conflict')
            await self.db.refresh(project)
        if data.title is not None:
            project.title = data.title
        if data.diagram_type is not None:
            project.diagram_type = data.diagram_type
        if data.canvas_engine is not None:
            project.canvas_engine = data.canvas_engine

        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def delete_project(self, user_id: str, project_id: str) -> None:
        project = await self.get_project(user_id, project_id)
        await self.db.execute(delete(AgentProposal).where(AgentProposal.project_id == project_id))
        await self.db.execute(delete(AgentConnection).where(AgentConnection.project_id == project_id))
        # SQLite does not enforce ON DELETE CASCADE by default, so project-scoped
        # children are removed explicitly and behave the same on both backends.
        await self.db.execute(
            delete(Snapshot).where(Snapshot.project_id == project.project_id)
        )
        await self.db.execute(
            delete(DnaRule).where(DnaRule.project_id == project.project_id)
        )
        await self.db.delete(project)
        await self.db.flush()
