from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
)
from app.core.sse import parse_sse_event
from app.schemas.diagram_generate import DiagramGenerateRequest
from app.services.diagram_stream_service import (
    GENERIC_PERSISTENCE_ERROR_MESSAGE,
    DiagramStreamService,
)


def _request(**overrides) -> DiagramGenerateRequest:
    data = {
        "context": "A flows to B",
        "requirements": "Draw a flow",
        "canvas_library": "excalidraw",
    }
    data.update(overrides)
    return DiagramGenerateRequest(**data)


class FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_rewrite_chunk_preserves_non_result_events():
    service = DiagramStreamService()
    chunk = 'event: stage_start\ndata: {"stage": "structure"}\n\n'

    rewritten = await service.rewrite_chunk(
        chunk=chunk,
        user_id="user-1",
        request=_request(),
    )

    assert rewritten == chunk


@pytest.mark.asyncio
async def test_rewrite_chunk_preserves_guest_result_events():
    async def fail_if_called(**kwargs):
        raise AssertionError("guest results must not be persisted")

    service = DiagramStreamService()
    service.persist_stream_result = fail_if_called
    chunk = 'event: result\ndata: {"request_id": "req_1", "schema_blob": {}}\n\n'

    rewritten = await service.rewrite_chunk(
        chunk=chunk,
        user_id=None,
        request=_request(),
    )

    assert rewritten == chunk


@pytest.mark.asyncio
async def test_rewrite_chunk_preserves_unparseable_result_events():
    async def fail_if_called(**kwargs):
        raise AssertionError("unparseable results must not be persisted")

    service = DiagramStreamService()
    service.persist_stream_result = fail_if_called
    chunk = "event: result\ndata: not-json\n\n"

    rewritten = await service.rewrite_chunk(
        chunk=chunk,
        user_id="user-1",
        request=_request(),
    )

    assert rewritten == chunk


@pytest.mark.asyncio
async def test_rewrite_chunk_injects_persistence_metadata():
    async def fake_persist_stream_result(*, user_id, request, result_data):
        assert user_id == "user-1"
        assert request.context == "A flows to B"
        return {
            **result_data,
            "project_id": "project-1",
            "snapshot_id": "snapshot-1",
            "thumbnail_url": "data:image/svg+xml;base64,test",
        }

    service = DiagramStreamService()
    service.persist_stream_result = fake_persist_stream_result

    rewritten = await service.rewrite_chunk(
        chunk='event: result\ndata: {"request_id": "req_1", "schema_blob": {}}\n\n',
        user_id="user-1",
        request=_request(),
    )
    event = parse_sse_event(rewritten)

    assert event is not None
    assert event.event == "result"
    assert event.data["project_id"] == "project-1"
    assert event.data["snapshot_id"] == "snapshot-1"
    assert event.data["thumbnail_url"] == "data:image/svg+xml;base64,test"


@pytest.mark.asyncio
async def test_persist_stream_result_adds_persistence_metadata():
    class FakePersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            assert payload.user_id == "user-1"
            assert payload.context == "A flows to B"
            assert payload.requirements == "Draw a flow"
            assert payload.project_id == "existing-project"
            assert payload.canvas_library == "tldraw"
            assert payload.workflow_result == {"request_id": "req_1", "schema_blob": {}}
            return SimpleNamespace(
                project_id="project-1",
                snapshot_id="snapshot-1",
                thumbnail_url="thumbnail",
                version=2,
            )

    session = FakeSession()
    service = DiagramStreamService(
        session_factory=lambda: session,
        persistence_service_factory=FakePersistenceService,
    )

    result = await service.persist_stream_result(
        user_id="user-1",
        request=_request(project_id="existing-project", canvas_library="tldraw"),
        result_data={"request_id": "req_1", "schema_blob": {}},
    )

    assert session.committed is True
    assert session.rolled_back is False
    assert result["project_id"] == "project-1"
    assert result["snapshot_id"] == "snapshot-1"
    assert result["thumbnail_url"] == "thumbnail"


@pytest.mark.asyncio
async def test_persist_stream_result_marks_project_not_found():
    class FakePersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            raise ProjectNotFoundException(
                "project secret-project-id not found for user-1",
                public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            )

    session = FakeSession()
    service = DiagramStreamService(
        session_factory=lambda: session,
        persistence_service_factory=FakePersistenceService,
    )

    result = await service.persist_stream_result(
        user_id="user-1",
        request=_request(),
        result_data={"request_id": "req_1", "schema_blob": {}},
    )

    assert session.committed is False
    assert session.rolled_back is True
    assert result["persist_error"] is True
    assert result["persist_error_message"] == LOWERCASE_PROJECT_NOT_FOUND_DETAIL
    assert "secret-project-id" not in result["persist_error_message"]
    assert "user-1" not in result["persist_error_message"]


@pytest.mark.asyncio
async def test_persist_stream_result_uses_project_error_public_detail():
    class FakePersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            raise ProjectNotFoundException(
                "project secret-project-id not found for user-1",
                public_detail="Project is unavailable",
            )

    session = FakeSession()
    service = DiagramStreamService(
        session_factory=lambda: session,
        persistence_service_factory=FakePersistenceService,
    )

    result = await service.persist_stream_result(
        user_id="user-1",
        request=_request(),
        result_data={"request_id": "req_1", "schema_blob": {}},
    )

    assert session.committed is False
    assert session.rolled_back is True
    assert result["persist_error"] is True
    assert result["persist_error_message"] == "Project is unavailable"
    assert "secret-project-id" not in result["persist_error_message"]


@pytest.mark.asyncio
async def test_persist_stream_result_marks_database_persistence_errors():
    class FakePersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            raise SQLAlchemyError("database unavailable")

    session = FakeSession()
    service = DiagramStreamService(
        session_factory=lambda: session,
        persistence_service_factory=FakePersistenceService,
    )

    result = await service.persist_stream_result(
        user_id="user-1",
        request=_request(),
        result_data={"request_id": "req_1", "schema_blob": {}},
    )

    assert session.committed is False
    assert session.rolled_back is True
    assert result["persist_error"] is True
    assert result["persist_error_message"] == GENERIC_PERSISTENCE_ERROR_MESSAGE


@pytest.mark.asyncio
async def test_persist_stream_result_reraises_result_contract_errors():
    class FakePersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            raise KeyError("schema_blob")

    session = FakeSession()
    service = DiagramStreamService(
        session_factory=lambda: session,
        persistence_service_factory=FakePersistenceService,
    )

    with pytest.raises(KeyError, match="schema_blob"):
        await service.persist_stream_result(
            user_id="user-1",
            request=_request(),
            result_data={"request_id": "req_1"},
        )

    assert session.committed is False
    assert session.rolled_back is True
