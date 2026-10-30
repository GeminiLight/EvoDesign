from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import DnaRule, OAuthCode, Project, Snapshot, Subscription, User  # noqa: F401
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListItem,
    ProjectListResponse,
    ProjectUpdateRequest,
    ProjectUpdateResponse,
)
from app.services.project_service import ProjectService


async def _create_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory()


def _project(project_id: str, user_id: str, *, updated_at: datetime) -> Project:
    return Project(
        project_id=project_id,
        user_id=user_id,
        title=f"Project {project_id}",
        diagram_type="flow",
        canvas_engine="excalidraw",
        source_text="A to B",
        version=1,
        latest_schema={"elements": []},
        created_at=updated_at,
        updated_at=updated_at,
    )


def _snapshot(snapshot_id: str, project_id: str, *, timestamp: datetime) -> Snapshot:
    return Snapshot(
        snapshot_id=snapshot_id,
        project_id=project_id,
        schema_blob={"elements": [{"id": snapshot_id}]},
        edit_source="AI_GEN",
        timestamp=timestamp,
    )


@pytest.mark.asyncio
async def test_list_projects_returns_typed_records_with_stable_latest_snapshot():
    engine, session = await _create_session()
    try:
        project = _project(
            "project-1",
            "user-1",
            updated_at=datetime(2026, 1, 2, 12, 0, 0),
        )
        other_user_project = _project(
            "project-other",
            "user-2",
            updated_at=datetime(2026, 1, 3, 12, 0, 0),
        )
        same_timestamp = datetime(2026, 1, 4, 12, 0, 0)
        session.add_all(
            [
                project,
                other_user_project,
                _snapshot("snapshot-a", "project-1", timestamp=same_timestamp),
                _snapshot("snapshot-b", "project-1", timestamp=same_timestamp),
                _snapshot("snapshot-other", "project-other", timestamp=same_timestamp),
            ]
        )
        await session.flush()

        records, total = await ProjectService(session).list_projects(
            user_id="user-1",
            limit=20,
            offset=0,
        )

        assert total == 1
        assert len(records) == 1
        assert records[0].project_id == "project-1"
        assert records[0].snapshot_count == 2
        assert records[0].latest_snapshot_id == "snapshot-b"
        assert records[0].version == 1
        snapshots, snapshot_total, revision = await ProjectService(session).get_snapshots("user-1", "project-1")
        assert snapshot_total == 2 and revision == 1 and len(snapshots) == 2

        response_item = ProjectListItem.model_validate(records[0])
        assert response_item.latest_snapshot_id == "snapshot-b"
        assert response_item.snapshot_count == 2
        assert response_item.canvas_engine == "excalidraw"
        assert response_item.model_dump()["canvas_library"] == "excalidraw"

        response = ProjectListResponse(projects=[response_item], total=1).model_dump()
        assert response["projects"][0]["canvas_library"] == "excalidraw"
    finally:
        await session.close()
        await engine.dispose()


def test_project_responses_expose_canvas_library_alias():
    updated_at = datetime(2026, 1, 2, 12, 0, 0)
    project = _project("project-1", "user-1", updated_at=updated_at)
    project.canvas_engine = "tldraw"

    detail = ProjectDetailResponse.model_validate(project).model_dump()
    update = ProjectUpdateResponse.model_validate(project).model_dump()

    assert detail["canvas_engine"] == "tldraw"
    assert detail["canvas_library"] == "tldraw"
    assert update["canvas_engine"] == "tldraw"
    assert update["canvas_library"] == "tldraw"


def test_project_requests_accept_canvas_library_alias():
    create = ProjectCreateRequest(canvas_library=" TLDraw ")
    update = ProjectUpdateRequest(canvas_library=" Excalidraw ")

    assert create.canvas_engine == "tldraw"
    assert create.model_dump()["canvas_engine"] == "tldraw"
    assert update.canvas_engine == "excalidraw"
    assert update.model_dump()["canvas_engine"] == "excalidraw"


def test_project_requests_reject_dual_canvas_aliases():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectCreateRequest(
            canvas_engine="excalidraw",
            canvas_library="tldraw",
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectUpdateRequest(
            canvas_engine="tldraw",
            canvas_library="excalidraw",
        )


@pytest.mark.asyncio
async def test_project_service_persists_canvas_library_alias_on_create_and_update():
    engine, session = await _create_session()
    try:
        service = ProjectService(session)

        project = await service.create_project(
            "user-1",
            ProjectCreateRequest(title="Alias project", canvas_library="tldraw"),
        )

        assert project.canvas_engine == "tldraw"

        updated = await service.update_project(
            "user-1",
            project.project_id,
            ProjectUpdateRequest(canvas_library="excalidraw", version=project.version),
        )

        assert updated.canvas_engine == "excalidraw"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_projects_respects_limit_offset_and_total_count():
    engine, session = await _create_session()
    try:
        session.add_all(
            [
                _project(
                    "project-1",
                    "user-1",
                    updated_at=datetime(2026, 1, 1, 12, 0, 0),
                ),
                _project(
                    "project-2",
                    "user-1",
                    updated_at=datetime(2026, 1, 2, 12, 0, 0),
                ),
                _project(
                    "project-3",
                    "user-1",
                    updated_at=datetime(2026, 1, 3, 12, 0, 0),
                ),
            ]
        )
        await session.flush()

        records, total = await ProjectService(session).list_projects(
            user_id="user-1",
            limit=1,
            offset=1,
        )

        assert total == 3
        assert [record.project_id for record in records] == ["project-2"]
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_project_removes_project_scoped_snapshots_and_dna_rules():
    """SQLite ignores ON DELETE CASCADE, so children are deleted explicitly."""
    engine, session = await _create_session()
    try:
        session.add(User(user_id="user-1", email="user-1@example.com"))
        session.add(_project("project-1", "user-1", updated_at=datetime(2026, 1, 1)))
        session.add(_snapshot("snap-1", "project-1", timestamp=datetime(2026, 1, 1)))
        session.add(
            DnaRule(
                rule_id="rule-1",
                user_id="user-1",
                project_id="project-1",
                cabin_id="structure",
                title="Scoped rule",
                preview="Only for this project.",
                source="manual",
            )
        )
        session.add(
            DnaRule(
                rule_id="rule-global",
                user_id="user-1",
                project_id=None,
                cabin_id="structure",
                title="Global rule",
                preview="Survives project deletion.",
                source="manual",
            )
        )
        await session.flush()

        await ProjectService(session).delete_project("user-1", "project-1")

        remaining_rules = (await session.execute(select(DnaRule))).scalars().all()
        remaining_snapshots = (await session.execute(select(Snapshot))).scalars().all()
        remaining_projects = (await session.execute(select(Project))).scalars().all()

        assert [row.rule_id for row in remaining_rules] == ["rule-global"]
        assert remaining_snapshots == []
        assert remaining_projects == []
    finally:
        await session.close()
        await engine.dispose()
