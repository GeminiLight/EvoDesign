from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_or_guest
from app.application import create_app
from app.db.session import get_db
from app.api.v1.endpoints import diagram
from app.services.local_edit_service import LocalEditResult


def _settings():
    return SimpleNamespace(
        app_name="Test EvoDiagram API",
        app_version="test",
        debug=False,
        cors_origins_list=["http://localhost:5175"],
    )


async def _guest_user():
    return None


async def _db_session():
    yield object()


class _ForbiddenWorkflowGenerateService:
    async def generate_without_render(self, **_kwargs):
        raise AssertionError("generation service should not run for invalid request bodies")

    async def generate_without_render_streaming(self, **_kwargs):
        raise AssertionError("streaming service should not run for invalid request bodies")
        yield ""  # pragma: no cover


class _ForbiddenLocalEditService:
    async def edit_local(self, **_kwargs):
        raise AssertionError("local edit service should not run for invalid request bodies")


class _PassThroughDiagramStreamService:
    async def rewrite_chunk(self, *, chunk, user_id, request):
        return chunk


def _client() -> TestClient:
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    app.dependency_overrides[get_current_user_or_guest] = _guest_user
    app.dependency_overrides[get_db] = _db_session
    app.dependency_overrides[diagram.get_workflow_generate_service] = (
        lambda: _ForbiddenWorkflowGenerateService()
    )
    app.dependency_overrides[diagram.get_local_edit_service] = (
        lambda: _ForbiddenLocalEditService()
    )
    app.dependency_overrides[diagram.get_diagram_stream_service] = (
        lambda: _PassThroughDiagramStreamService()
    )
    return TestClient(app)


def _app_with_common_overrides():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    app.dependency_overrides[get_current_user_or_guest] = _guest_user
    app.dependency_overrides[get_db] = _db_session
    return app


def _validation_locations(response_json: dict[str, Any]) -> set[tuple[str, ...]]:
    return {
        tuple(str(part) for part in item.get("loc", ()))
        for item in response_json.get("detail", [])
        if isinstance(item, dict)
    }


def _assert_rejected_field(response_json: dict[str, Any], field: str) -> None:
    assert ("body", field) in _validation_locations(response_json)


def test_generate_http_uses_dependency_overridden_workflow_service():
    seen: dict[str, Any] = {}

    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            seen.update(kwargs)
            return {
                "request_id": "req_http",
                "schema_blob": {"elements": []},
                "summary": "Generated through override",
            }

    app = _app_with_common_overrides()
    app.dependency_overrides[diagram.get_workflow_generate_service] = (
        lambda: FakeWorkflowGenerateService()
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagram/generate",
        json={
            "context": "A to B",
            "requirements": "Draw a simple flow",
            "use_icons": True,
            "canvas_library": "excalidraw",
        },
    )

    assert response.status_code == 201
    assert response.json()["summary"] == "Generated through override"
    assert seen["use_icons"] is True
    assert seen["context"] == "A to B"
    assert seen["canvas_library"] == "excalidraw"


def test_generate_stream_http_uses_dependency_overridden_services():
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            assert kwargs["use_icons"] is True
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            assert user_id is None
            assert request.context == "A to B"
            return chunk

    app = _app_with_common_overrides()
    app.dependency_overrides[diagram.get_workflow_generate_service] = (
        lambda: FakeWorkflowGenerateService()
    )
    app.dependency_overrides[diagram.get_diagram_stream_service] = (
        lambda: FakeDiagramStreamService()
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagram/generate/stream",
        json={
            "context": "A to B",
            "use_icons": True,
            "canvas_library": "excalidraw",
        },
    )

    assert response.status_code == 200
    assert response.text == 'event: stage_start\ndata: {"stage": "structure"}\n\n'


def test_local_edit_http_uses_dependency_overridden_service():
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            assert kwargs["selected_node_ids"] == ["node-1"]
            return LocalEditResult(
                modified_nodes={"elements": [{"id": "node-1", "width": 120}]},
                operation_type="update",
                summary="Made node-1 larger",
            )

    app = _app_with_common_overrides()
    app.dependency_overrides[diagram.get_local_edit_service] = (
        lambda: FakeLocalEditService()
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagram/edit-local",
        json={
            "current_schema": {"elements": [{"id": "node-1"}]},
            "selected_node_ids": ["node-1"],
            "instruction": "Make it larger",
            "canvas_library": "excalidraw",
        },
    )

    assert response.status_code == 200
    assert response.json()["modified_nodes"] == {
        "elements": [{"id": "node-1", "width": 120}]
    }


def test_generate_http_rejects_removed_edit_mode_field():
    client = _client()

    response = client.post(
        "/api/v1/diagram/generate",
        json={
            "context": "A to B",
            "requirements": "Draw a simple flow",
            "edit_mode": "local",
        },
    )

    assert response.status_code == 422
    _assert_rejected_field(response.json(), "edit_mode")


def test_generate_stream_http_rejects_removed_edit_mode_field():
    client = _client()

    response = client.post(
        "/api/v1/diagram/generate/stream",
        json={
            "context": "A to B",
            "requirements": "Draw a simple flow",
            "edit_mode": "local",
        },
    )

    assert response.status_code == 422
    _assert_rejected_field(response.json(), "edit_mode")


def test_local_edit_http_rejects_generation_only_payload_fields():
    client = _client()

    response = client.post(
        "/api/v1/diagram/edit-local",
        json={
            "current_schema": {"elements": [{"id": "node-1"}]},
            "selected_node_ids": ["node-1"],
            "instruction": "Make it blue",
            "context": "A to B",
            "requirements": "Draw a simple flow",
        },
    )

    assert response.status_code == 422
    assert {
        ("body", "context"),
        ("body", "requirements"),
    } <= _validation_locations(response.json())


def test_diagram_http_rejects_unknown_canvas_library_before_services():
    client = _client()

    response = client.post(
        "/api/v1/diagram/generate",
        json={
            "context": "A to B",
            "canvas_library": "secret-canvas",
        },
    )

    assert response.status_code == 422
    _assert_rejected_field(response.json(), "canvas_library")


def test_generate_http_requires_canvas_library_before_services():
    client = _client()

    response = client.post(
        "/api/v1/diagram/generate",
        json={
            "context": "A to B",
            "requirements": "Draw a simple flow",
        },
    )

    assert response.status_code == 422
    _assert_rejected_field(response.json(), "canvas_library")


def test_generate_stream_http_requires_canvas_library_before_services():
    client = _client()

    response = client.post(
        "/api/v1/diagram/generate/stream",
        json={
            "context": "A to B",
            "requirements": "Draw a simple flow",
        },
    )

    assert response.status_code == 422
    _assert_rejected_field(response.json(), "canvas_library")


def test_local_edit_http_rejects_unknown_canvas_library_before_services():
    client = _client()

    response = client.post(
        "/api/v1/diagram/edit-local",
        json={
            "current_schema": {"elements": [{"id": "node-1"}]},
            "selected_node_ids": ["node-1"],
            "instruction": "Make it blue",
            "canvas_library": "secret-canvas",
        },
    )

    assert response.status_code == 422
    _assert_rejected_field(response.json(), "canvas_library")


def test_local_edit_http_requires_canvas_library_before_services():
    client = _client()

    response = client.post(
        "/api/v1/diagram/edit-local",
        json={
            "current_schema": {"elements": [{"id": "node-1"}]},
            "selected_node_ids": ["node-1"],
            "instruction": "Make it blue",
        },
    )

    assert response.status_code == 422
    _assert_rejected_field(response.json(), "canvas_library")
