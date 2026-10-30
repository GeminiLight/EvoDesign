from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
)
from app.db.base import Base
from app.models import DnaRule, OAuthCode, Project, Snapshot, Subscription, User  # noqa: F401
from app.services.diagram_persistence_service import (
    DiagramPersistenceInput,
    DiagramPersistenceService,
    build_diagram_persistence_input,
)
from app.services.thumbnail_service import ThumbnailGenerationError


async def _create_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory()


def _payload(**overrides) -> DiagramPersistenceInput:
    data = {
        "user_id": "user-1",
        "base_version": 1,
        "context": "A flows to B",
        "requirements": "Draw a flow",
        "project_id": None,
        "canvas_library": "excalidraw",
        "workflow_result": {
            "schema_blob": {"elements": [{"id": "n1"}], "edges": []},
            "thought_trace": {"step": "generated"},
            "metrics_scores": {"node_count": 1, "edge_count": 0},
        },
    }
    data.update(overrides)
    return DiagramPersistenceInput(**data)


def test_project_not_found_exception_keeps_internal_message_private():
    exc = ProjectNotFoundException(
        "project secret-project-id not found for user-1",
        public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    )

    assert str(exc) == "project secret-project-id not found for user-1"
    assert exc.public_detail == LOWERCASE_PROJECT_NOT_FOUND_DETAIL
    assert "secret-project-id" not in exc.public_detail
    assert "user-1" not in exc.public_detail


def test_build_diagram_persistence_input_preserves_generation_request_fields():
    workflow_result = {"schema_blob": {"elements": []}, "summary": "Generated"}
    request = SimpleNamespace(
        context="A flows to B",
        requirements="Draw a flow",
        project_id="project-1",
        canvas_library="tldraw",
    )

    payload = build_diagram_persistence_input(
        user_id="user-1",
        request=request,
        workflow_result=workflow_result,
    )

    assert payload.user_id == "user-1"
    assert payload.context == "A flows to B"
    assert payload.requirements == "Draw a flow"
    assert payload.project_id == "project-1"
    assert payload.canvas_library == "tldraw"
    assert payload.workflow_result == workflow_result


@pytest.mark.asyncio
async def test_persist_generation_result_creates_project_snapshot_and_thumbnail():
    engine, session = await _create_session()
    try:
        service = DiagramPersistenceService(
            session,
            thumbnail_generator=lambda schema, canvas: f"thumbnail:{canvas}:{len(schema)}",
        )

        result = await service.persist_generation_result(_payload())

        assert result.project_id
        assert result.snapshot_id
        assert result.thumbnail_url == "thumbnail:excalidraw:2"

        project = await session.get(Project, result.project_id)
        snapshot = await session.get(Snapshot, result.snapshot_id)

        assert project is not None
        assert project.title == "A flows to B"
        assert project.canvas_engine == "excalidraw"
        assert project.latest_schema == {"elements": [{"id": "n1"}], "edges": []}
        assert project.thumbnail_url == "thumbnail:excalidraw:2"
        assert snapshot is not None
        assert snapshot.project_id == project.project_id
        assert snapshot.parent_id is None
        assert snapshot.metrics_scores == {"node_count": 1, "edge_count": 0}
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_persist_generation_result_appends_snapshot_to_existing_project():
    engine, session = await _create_session()
    try:
        project = Project(
            user_id="user-1",
            title="Existing",
            diagram_type="automated",
            canvas_engine="excalidraw",
            source_text="Existing context",
            latest_schema={"elements": []},
        )
        session.add(project)
        await session.flush()

        first_snapshot = Snapshot(
            project_id=project.project_id,
            schema_blob={"elements": []},
            edit_source="AI_GEN",
            thought_trace="{}",
            metrics_scores={},
        )
        session.add(first_snapshot)
        await session.flush()

        service = DiagramPersistenceService(session, thumbnail_generator=lambda *_: None)
        result = await service.persist_generation_result(
            _payload(project_id=project.project_id, canvas_library="tldraw")
        )

        assert result.project_id == project.project_id
        assert result.snapshot_id != first_snapshot.snapshot_id

        new_snapshot = await session.get(Snapshot, result.snapshot_id)

        assert new_snapshot is not None
        assert new_snapshot.parent_id == first_snapshot.snapshot_id
        assert project.version == 2
        assert result.version == project.version
        from app.services.schema_service import SchemaService, VersionConflictError
        with pytest.raises(VersionConflictError):
            await SchemaService(session).sync_schema(
                "user-1", project.project_id, {"elements": [{"id": "stale"}]},
                editor="excalidraw", base_snapshot_id=first_snapshot.snapshot_id, version=1,
            )
        await session.refresh(project)
        assert project.latest_schema == {"elements": [{"id": "n1"}], "edges": []}
        assert project.canvas_engine == "tldraw"
        assert project.latest_schema == {"elements": [{"id": "n1"}], "edges": []}
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_persist_generation_result_degrades_when_thumbnail_generation_fails():
    engine, session = await _create_session()
    try:
        def fail_thumbnail(schema, canvas):
            raise ThumbnailGenerationError("thumbnail render failed")

        service = DiagramPersistenceService(
            session,
            thumbnail_generator=fail_thumbnail,
        )

        result = await service.persist_generation_result(_payload())

        assert result.project_id
        assert result.snapshot_id
        assert result.thumbnail_url is None

        project = await session.get(Project, result.project_id)
        snapshot = await session.get(Snapshot, result.snapshot_id)

        assert project is not None
        assert project.latest_schema == {"elements": [{"id": "n1"}], "edges": []}
        assert project.thumbnail_url is None
        assert snapshot is not None
        assert snapshot.project_id == project.project_id
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_persist_generation_result_rejects_project_owned_by_another_user():
    engine, session = await _create_session()
    try:
        project = Project(
            user_id="other-user",
            title="Existing",
            diagram_type="automated",
            canvas_engine="excalidraw",
            source_text="Existing context",
        )
        session.add(project)
        await session.flush()

        service = DiagramPersistenceService(session)
        with pytest.raises(
            ProjectNotFoundException,
            match=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
        ):
            await service.persist_generation_result(
                _payload(project_id=project.project_id)
            )
    finally:
        await session.close()
        await engine.dispose()
