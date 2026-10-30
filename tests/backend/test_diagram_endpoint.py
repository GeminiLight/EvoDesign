from __future__ import annotations

import ast
import inspect
import textwrap
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import diagram
from app.api.v1.endpoints.diagram import (
    _get_user_tier,
    edit_diagram_local,
    generate_diagram,
    generate_diagram_stream,
)
from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
)
from app.core.sse import parse_sse_event
from app.schemas.diagram_generate import DiagramGenerateRequest, DiagramLocalEditRequest
from app.services.diagram_generation_contract import GenerationInputValidationError
from app.services.llm_client import BackendLLMConfigurationError
from app.services.local_edit_service import (
    LocalEditResponseError,
    LocalEditResult,
    LocalEditValidationError,
)
from app.services.workflow_runtime.stream_errors import (
    STREAM_GENERATION_ERROR_DETAIL,
    STREAM_INIT_ERROR_DETAIL,
    STREAM_REWRITE_ERROR_DETAIL,
)


async def _stream_response_body(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return "".join(chunks)


def _stream_events(body: str):
    events = []
    for chunk in body.split("\n\n"):
        if not chunk.strip():
            continue
        event = parse_sse_event(f"{chunk}\n\n")
        if event is not None:
            events.append(event)
    return events


def _assert_stream_error(
    body: str,
    *,
    stage: str = "init",
    message: str = "Diagram generation failed",
    detail: str = STREAM_INIT_ERROR_DETAIL,
) -> None:
    events = _stream_events(body)
    assert events
    event = events[-1]
    assert event.event == "error"
    assert event.data == {
        "stage": stage,
        "message": message,
        "detail": detail,
    }


def _assert_stream_init_error(
    body: str,
    *,
    message: str = "Diagram generation failed",
    detail: str = STREAM_INIT_ERROR_DETAIL,
) -> None:
    _assert_stream_error(body, message=message, detail=detail)


def _direct_service_constructions(endpoint) -> list[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint.__wrapped__)))
    forbidden = {
        "WorkflowGenerateService",
        "DiagramStreamService",
        "LocalEditService",
        "DiagramPersistenceService",
    }
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in forbidden:
                calls.append(f"{node.func.id}()")
    return calls


def test_diagram_endpoints_use_dependency_providers_for_services():
    constructions = {
        endpoint.__name__: _direct_service_constructions(endpoint)
        for endpoint in (
            generate_diagram,
            generate_diagram_stream,
            edit_diagram_local,
        )
    }

    assert constructions == {
        "generate_diagram": [],
        "generate_diagram_stream": [],
        "edit_diagram_local": [],
    }


def _user_with_subscription(status: str | None, price_id: str | None = None):
    subscription = (
        SimpleNamespace(status=status, price_id=price_id)
        if status is not None
        else None
    )
    return SimpleNamespace(user_id="user-1", subscription=subscription)


class _RecordingDiagramLogger:
    def __init__(self):
        self.warning_calls: list[tuple[str, tuple[object, ...]]] = []
        self.exception_calls: list[str] = []

    def warning(self, message: str, *args):
        self.warning_calls.append((message, args))

    def exception(self, message: str):
        self.exception_calls.append(message)


class _UnusedDiagramPersistenceService:
    async def persist_generation_result(self, payload):
        raise AssertionError("persistence service should not be used")


class _PassThroughDiagramStreamService:
    async def rewrite_chunk(self, *, chunk, user_id, request):
        return chunk


async def _call_generate_diagram(
    *,
    body: DiagramGenerateRequest,
    workflow_service,
    current_user=None,
    request=object(),
    persistence_service=None,
):
    return await generate_diagram.__wrapped__(
        request=request,
        body=body,
        current_user=current_user,
        workflow_service=workflow_service,
        persistence_service=persistence_service or _UnusedDiagramPersistenceService(),
    )


async def _call_edit_diagram_local(
    *,
    body: DiagramLocalEditRequest,
    service,
    current_user=None,
    request=object(),
):
    return await edit_diagram_local.__wrapped__(
        request=request,
        body=body,
        current_user=current_user,
        service=service,
    )


async def _call_generate_diagram_stream(
    *,
    body: DiagramGenerateRequest,
    workflow_service,
    current_user=None,
    request=object(),
    stream_service=None,
):
    return await generate_diagram_stream.__wrapped__(
        request=request,
        body=body,
        current_user=current_user,
        workflow_service=workflow_service,
        stream_service=stream_service or _PassThroughDiagramStreamService(),
    )


@pytest.mark.parametrize(
    ("user", "expected_tier"),
    [
        (None, None),
        (_user_with_subscription(None), None),
        (_user_with_subscription("free"), None),
        (_user_with_subscription("canceled"), None),
        (_user_with_subscription("trialing"), None),
        (_user_with_subscription("active"), "pro"),
        (_user_with_subscription("active", price_id="enterprise-price"), "pro"),
    ],
)
def test_get_user_tier_matches_current_billing_contract(user, expected_tier):
    assert _get_user_tier(user) == expected_tier


@pytest.mark.parametrize(
    (
        "exc",
        "policy",
        "log_mappings",
        "fallback_log_message",
        "expected_status",
        "expected_detail",
        "expected_warnings",
        "expected_exceptions",
    ),
    [
        (
            GenerationInputValidationError(
                "Unsupported canvas library: secret-canvas",
                public_detail="Unsupported canvas library",
            ),
            diagram.DIAGRAM_GENERATION_ERROR_POLICY,
            diagram.DIAGRAM_GENERATION_ERROR_LOGS,
            "Diagram generation failed",
            400,
            "Unsupported canvas library",
            "Diagram generation input rejected: {}",
            None,
        ),
        (
            ValueError("internal parser secret-token"),
            diagram.DIAGRAM_GENERATION_ERROR_POLICY,
            diagram.DIAGRAM_GENERATION_ERROR_LOGS,
            "Diagram generation failed",
            500,
            "Diagram generation failed",
            None,
            "Diagram generation failed with internal validation error",
        ),
        (
            ProjectNotFoundException(
                "project secret-project-id not found for user-1",
                public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            ),
            diagram.DIAGRAM_PERSISTENCE_ERROR_POLICY,
            diagram.DIAGRAM_PERSISTENCE_ERROR_LOGS,
            "Diagram generation result persistence failed",
            404,
            LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            "Diagram generation persistence rejected: {}",
            None,
        ),
        (
            LocalEditValidationError(
                "No nodes found with IDs: ['node-1']",
                public_detail="Selected nodes were not found",
            ),
            diagram.LOCAL_EDIT_ERROR_POLICY,
            diagram.LOCAL_EDIT_ERROR_LOGS,
            "Local edit failed",
            400,
            "Selected nodes were not found",
            "Local edit validation error: {}",
            None,
        ),
        (
            LocalEditResponseError("provider response included secret-token"),
            diagram.LOCAL_EDIT_ERROR_POLICY,
            diagram.LOCAL_EDIT_ERROR_LOGS,
            "Local edit failed",
            500,
            "Local edit failed",
            None,
            "Local edit LLM response was invalid",
        ),
        (
            RuntimeError("database password leaked"),
            diagram.DIAGRAM_PERSISTENCE_ERROR_POLICY,
            diagram.DIAGRAM_PERSISTENCE_ERROR_LOGS,
            "Diagram generation result persistence failed",
            500,
            "Diagram generation failed",
            None,
            "Diagram generation result persistence failed",
        ),
    ],
)
def test_raise_diagram_api_error_preserves_public_policy_and_logging(
    monkeypatch,
    exc,
    policy,
    log_mappings,
    fallback_log_message,
    expected_status,
    expected_detail,
    expected_warnings,
    expected_exceptions,
):
    logger = _RecordingDiagramLogger()
    monkeypatch.setattr(diagram, "logger", logger)

    with pytest.raises(HTTPException) as exc_info:
        diagram._raise_diagram_api_error(
            exc,
            policy=policy,
            log_mappings=log_mappings,
            fallback_log_message=fallback_log_message,
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert exc_info.value.__cause__ is exc
    assert "secret" not in str(exc_info.value.detail)
    if expected_warnings is None:
        assert logger.warning_calls == []
    else:
        assert logger.warning_calls == [(expected_warnings, (exc,))]
    if expected_exceptions is None:
        assert logger.exception_calls == []
    else:
        assert logger.exception_calls == [expected_exceptions]


@pytest.mark.asyncio
async def test_generate_diagram_hides_unexpected_exception_details(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            raise RuntimeError("database password leaked in traceback")

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
            current_user=None,
            workflow_service=FakeWorkflowGenerateService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Diagram generation failed"
    assert "password" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_diagram_hides_backend_llm_configuration_errors(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            raise BackendLLMConfigurationError("LLM API key is missing: secret")

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
            current_user=None,
            workflow_service=FakeWorkflowGenerateService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Diagram generation failed"
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_diagram_returns_validation_errors_as_bad_request(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            raise GenerationInputValidationError(
                "Unsupported canvas library: unknown",
                public_detail="Unsupported canvas library",
            )

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
            current_user=None,
            workflow_service=FakeWorkflowGenerateService(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Unsupported canvas library"


@pytest.mark.asyncio
async def test_generate_diagram_does_not_publish_plain_value_error_prefixes(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            raise ValueError("Unsupported canvas library: secret-canvas")

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
            current_user=None,
            workflow_service=FakeWorkflowGenerateService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Diagram generation failed"
    assert "secret-canvas" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_diagram_hides_unexpected_value_error_details(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            raise ValueError("internal parser secret-token")

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
            current_user=None,
            workflow_service=FakeWorkflowGenerateService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Diagram generation failed"
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_diagram_persists_request_fields(monkeypatch):
    workflow_result = {
        "request_id": "req_1",
        "schema_blob": {"elements": []},
        "summary": "Generated",
    }

    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            assert kwargs["context"] == "A to B"
            assert kwargs["requirements"] == "Draw a flow"
            # DNA scope: the engine needs the acting user and target project.
            assert kwargs["user_id"] == "user-1"
            assert kwargs["project_id"] == "project-1"
            assert kwargs["canvas_library"] == "tldraw"
            assert kwargs["user_tier"] == "pro"
            return workflow_result

    class FakeDiagramPersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            assert payload.user_id == "user-1"
            assert payload.context == "A to B"
            assert payload.requirements == "Draw a flow"
            assert payload.project_id == "project-1"
            assert payload.canvas_library == "tldraw"
            assert payload.workflow_result == workflow_result
            return SimpleNamespace(
                project_id="project-1",
                snapshot_id="snapshot-1",
                thumbnail_url="thumbnail",
                version=2,
            )

    response = await _call_generate_diagram(
        body=DiagramGenerateRequest(base_version=1,
            context="A to B",
            requirements="Draw a flow",
            project_id="project-1",
            canvas_library="tldraw",
        ),
        current_user=_user_with_subscription("active"),
        workflow_service=FakeWorkflowGenerateService(),
        persistence_service=FakeDiagramPersistenceService(object()),
    )

    assert response.project_id == "project-1"
    assert response.snapshot_id == "snapshot-1"
    assert response.schema_blob == {"elements": []}
    assert response.summary == "Generated"
    assert response.thumbnail_url == "thumbnail"


@pytest.mark.asyncio
async def test_generate_diagram_stream_scopes_dna_to_user_and_project():
    seen = {}

    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            seen.update(kwargs)
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1,
            context="A to B",
            project_id="project-1",
            canvas_library="excalidraw",
        ),
        current_user=_user_with_subscription("active"),
        workflow_service=FakeWorkflowGenerateService(),
    )
    await _stream_response_body(response)

    assert seen["user_id"] == "user-1"
    assert seen["project_id"] == "project-1"


@pytest.mark.asyncio
async def test_generate_diagram_passes_guest_scope_without_dna_identity():
    seen = {}
    workflow_result = {
        "request_id": "req_1",
        "schema_blob": {"elements": []},
        "summary": "Generated",
    }

    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            seen.update(kwargs)
            return workflow_result

    response = await _call_generate_diagram(
        body=DiagramGenerateRequest(base_version=1,
            context="A to B",
            project_id="",
            canvas_library="excalidraw",
        ),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
    )

    assert response.project_id is None
    # Guests carry no user identity, and an empty project scope normalizes to
    # the global (None) DNA scope.
    assert seen["user_id"] is None
    assert seen["project_id"] is None


@pytest.mark.asyncio
async def test_generate_diagram_returns_not_found_for_missing_project_without_private_detail(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            return {
                "request_id": "req_1",
                "schema_blob": {"elements": []},
            }

    class FakeDiagramPersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            raise ProjectNotFoundException(
                "project secret-project-id not found for user-1",
                public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            )

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw", project_id="project-1"),
            current_user=_user_with_subscription("active"),
            workflow_service=FakeWorkflowGenerateService(),
            persistence_service=FakeDiagramPersistenceService(object()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == LOWERCASE_PROJECT_NOT_FOUND_DETAIL
    assert "secret-project-id" not in exc_info.value.detail
    assert "user-1" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_diagram_uses_project_not_found_public_detail(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            return {
                "request_id": "req_1",
                "schema_blob": {"elements": []},
            }

    class FakeDiagramPersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            raise ProjectNotFoundException(
                "project secret-project-id not found for user-1",
                public_detail="Project is unavailable",
            )

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw", project_id="project-1"),
            current_user=_user_with_subscription("active"),
            workflow_service=FakeWorkflowGenerateService(),
            persistence_service=FakeDiagramPersistenceService(object()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Project is unavailable"
    assert "secret-project-id" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_diagram_hides_persistence_exception_details(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render(self, **kwargs):
            return {
                "request_id": "req_1",
                "schema_blob": {"elements": []},
            }

    class FakeDiagramPersistenceService:
        def __init__(self, db):
            self.db = db

        async def persist_generation_result(self, payload):
            raise RuntimeError("database password leaked")

    with pytest.raises(HTTPException) as exc_info:
        await _call_generate_diagram(
            body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw", project_id="project-1"),
            current_user=_user_with_subscription("active"),
            workflow_service=FakeWorkflowGenerateService(),
            persistence_service=FakeDiagramPersistenceService(object()),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Diagram generation failed"
    assert "password" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_diagram_local_builds_response_from_typed_service_result(monkeypatch):
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            assert kwargs["current_schema"] == {"elements": [{"id": "node-1"}]}
            assert kwargs["selected_node_ids"] == ["node-1"]
            assert kwargs["instruction"] == "Make it larger"
            assert kwargs["canvas_library"] == "excalidraw"
            return LocalEditResult(
                modified_nodes={"elements": [{"id": "node-1", "width": 120}]},
                operation_type="update",
                summary="Made node-1 larger",
            )

    response = await _call_edit_diagram_local(
        body=DiagramLocalEditRequest(
            current_schema={"elements": [{"id": "node-1"}]},
            selected_node_ids=["node-1"],
            instruction="Make it larger",
            canvas_library="excalidraw",
        ),
        current_user=None,
        service=FakeLocalEditService(),
    )

    assert response.request_id.startswith("edit_")
    assert response.modified_nodes == {
        "elements": [{"id": "node-1", "width": 120}]
    }
    assert response.operation_type == "update"
    assert response.summary == "Made node-1 larger"


@pytest.mark.asyncio
async def test_edit_diagram_local_hides_unexpected_exception_details(monkeypatch):
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            raise RuntimeError("provider API key leaked in traceback")

    with pytest.raises(HTTPException) as exc_info:
        await _call_edit_diagram_local(
            body=DiagramLocalEditRequest(
                current_schema={"elements": []},
                selected_node_ids=["node-1"],
                instruction="Make it larger",
                canvas_library="excalidraw",
            ),
            current_user=None,
            service=FakeLocalEditService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Local edit failed"
    assert "API key" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_diagram_local_hides_backend_llm_configuration_errors(monkeypatch):
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            raise BackendLLMConfigurationError("LLM API key is missing: secret")

    with pytest.raises(HTTPException) as exc_info:
        await _call_edit_diagram_local(
            body=DiagramLocalEditRequest(
                current_schema={"elements": []},
                selected_node_ids=["node-1"],
                instruction="Make it larger",
                canvas_library="excalidraw",
            ),
            current_user=None,
            service=FakeLocalEditService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Local edit failed"
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_diagram_local_returns_validation_errors_as_bad_request(monkeypatch):
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            raise LocalEditValidationError(
                "No nodes found with IDs: ['node-1']",
                public_detail="Selected nodes were not found",
            )

    with pytest.raises(HTTPException) as exc_info:
        await _call_edit_diagram_local(
            body=DiagramLocalEditRequest(
                current_schema={"elements": []},
                selected_node_ids=["node-1"],
                instruction="Make it larger",
                canvas_library="excalidraw",
            ),
            current_user=None,
            service=FakeLocalEditService(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Selected nodes were not found"
    assert "node-1" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_diagram_local_hides_validation_error_details(monkeypatch):
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            raise LocalEditValidationError("internal node secret-token")

    with pytest.raises(HTTPException) as exc_info:
        await _call_edit_diagram_local(
            body=DiagramLocalEditRequest(
                current_schema={"elements": []},
                selected_node_ids=["node-1"],
                instruction="Make it larger",
                canvas_library="excalidraw",
            ),
            current_user=None,
            service=FakeLocalEditService(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Local edit request is invalid"
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_diagram_local_hides_invalid_llm_response_details(monkeypatch):
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            raise LocalEditResponseError("provider response included secret-token")

    with pytest.raises(HTTPException) as exc_info:
        await _call_edit_diagram_local(
            body=DiagramLocalEditRequest(
                current_schema={"elements": []},
                selected_node_ids=["node-1"],
                instruction="Make it larger",
                canvas_library="excalidraw",
            ),
            current_user=None,
            service=FakeLocalEditService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Local edit failed"
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_diagram_local_hides_unexpected_plain_value_errors(monkeypatch):
    class FakeLocalEditService:
        async def edit_local(self, **kwargs):
            raise ValueError("internal parser secret-token")

    with pytest.raises(HTTPException) as exc_info:
        await _call_edit_diagram_local(
            body=DiagramLocalEditRequest(
                current_schema={"elements": []},
                selected_node_ids=["node-1"],
                instruction="Make it larger",
                canvas_library="excalidraw",
            ),
            current_user=None,
            service=FakeLocalEditService(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Local edit failed"
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_diagram_stream_passes_through_normal_chunks(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            assert user_id is None
            assert request.context == "A to B"
            return chunk

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert await _stream_response_body(response) == (
        'event: stage_start\ndata: {"stage": "structure"}\n\n'
    )


@pytest.mark.asyncio
async def test_generate_diagram_stream_stops_when_client_disconnected_before_start(
    monkeypatch,
):
    calls = {"workflow": 0, "rewrite": 0}

    class FakeRequest:
        async def is_disconnected(self):
            return True

    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            calls["workflow"] += 1
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            calls["rewrite"] += 1
            return chunk

    response = await _call_generate_diagram_stream(
        request=FakeRequest(),
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )

    assert await _stream_response_body(response) == ""
    assert calls == {"workflow": 0, "rewrite": 0}


@pytest.mark.asyncio
async def test_generate_diagram_stream_stops_before_rewrite_after_disconnect(
    monkeypatch,
):
    calls = {"workflow": 0, "rewrite": 0}

    class FakeRequest:
        def __init__(self):
            self._checks = iter((False, True))

        async def is_disconnected(self):
            return next(self._checks)

    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            calls["workflow"] += 1
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            calls["rewrite"] += 1
            return chunk

    response = await _call_generate_diagram_stream(
        request=FakeRequest(),
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )

    assert await _stream_response_body(response) == ""
    assert calls == {"workflow": 1, "rewrite": 0}


@pytest.mark.asyncio
async def test_generate_diagram_stream_passes_active_subscription_as_pro_tier(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            assert kwargs["user_tier"] == "pro"
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            assert user_id == "user-1"
            return chunk

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=_user_with_subscription("active"),
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )

    assert await _stream_response_body(response) == (
        'event: stage_start\ndata: {"stage": "structure"}\n\n'
    )


@pytest.mark.asyncio
async def test_generate_diagram_stream_hides_unexpected_init_exception(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            raise RuntimeError("provider secret leaked in stack")
            yield

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_init_error(body)
    assert "secret" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_marks_post_start_generation_failures(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'
            raise RuntimeError("provider secret leaked after first chunk")

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            return chunk

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    events = _stream_events(body)
    assert events[0].event == "stage_start"
    _assert_stream_error(
        body,
        stage="generation",
        detail=STREAM_GENERATION_ERROR_DETAIL,
    )
    assert "secret" not in body


@pytest.mark.parametrize(
    ("exc_factory", "private_text"),
    [
        (
            lambda: BackendLLMConfigurationError("LLM API key is missing: secret"),
            "secret",
        ),
        (
            lambda: ValueError("internal parser secret-token"),
            "secret-token",
        ),
    ],
    ids=("backend-llm-config", "value-error"),
)
@pytest.mark.asyncio
async def test_generate_diagram_stream_marks_post_start_internal_errors_as_generation_sse(
    monkeypatch,
    exc_factory,
    private_text,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'
            raise exc_factory()

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            return chunk

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    events = _stream_events(body)
    assert events[0].event == "stage_start"
    _assert_stream_error(
        body,
        stage="generation",
        detail=STREAM_GENERATION_ERROR_DETAIL,
    )
    assert private_text not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_marks_post_start_validation_errors_as_generation_sse(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'
            raise GenerationInputValidationError(
                "Unsupported canvas library: secret",
                public_detail="Unsupported canvas library",
            )

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            return chunk

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    events = _stream_events(body)
    assert events[0].event == "stage_start"
    _assert_stream_error(
        body,
        stage="generation",
        message="Unsupported canvas library",
        detail="Unsupported canvas library",
    )
    assert "secret" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_passes_through_workflow_error_chunks(monkeypatch):
    workflow_error = (
        'event: error\n'
        'data: {"stage": "render", "message": "Diagram generation failed", '
        '"detail": "The diagram generation stage failed."}\n\n'
    )

    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield workflow_error

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            return chunk

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )

    assert await _stream_response_body(response) == workflow_error


@pytest.mark.asyncio
async def test_generate_diagram_stream_hides_unexpected_rewrite_exception(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: result\ndata: {"schema_blob": {}}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            raise RuntimeError("persistence secret leaked in stack")

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_error(
        body,
        stage="rewrite",
        detail=STREAM_REWRITE_ERROR_DETAIL,
    )
    assert "secret" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_returns_rewrite_public_validation_errors_as_sse(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: result\ndata: {"schema_blob": {}}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            raise GenerationInputValidationError(
                "Unsupported canvas library: secret",
                public_detail="Unsupported canvas library",
            )

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_error(
        body,
        stage="rewrite",
        message="Unsupported canvas library",
        detail="Unsupported canvas library",
    )
    assert "secret" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_hides_rewrite_backend_llm_configuration_errors(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: result\ndata: {"schema_blob": {}}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            raise BackendLLMConfigurationError("LLM API key is missing: secret")

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_error(
        body,
        stage="rewrite",
        detail=STREAM_REWRITE_ERROR_DETAIL,
    )
    assert "secret" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_hides_unexpected_rewrite_value_error_details(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: result\ndata: {"schema_blob": {}}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            raise ValueError("internal parser secret-token")

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_error(
        body,
        stage="rewrite",
        detail=STREAM_REWRITE_ERROR_DETAIL,
    )
    assert "secret-token" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_hides_escaped_project_not_found_details(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            yield 'event: result\ndata: {"schema_blob": {}}\n\n'

    class FakeDiagramStreamService:
        async def rewrite_chunk(self, *, chunk, user_id, request):
            raise ProjectNotFoundException(
                "project secret-id not found",
                public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            )

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
        stream_service=FakeDiagramStreamService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_error(
        body,
        stage="rewrite",
        detail=STREAM_REWRITE_ERROR_DETAIL,
    )
    assert "secret-id" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_hides_backend_llm_configuration_errors(monkeypatch):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            raise BackendLLMConfigurationError("LLM API key is missing: secret")
            yield

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_init_error(body)
    assert "secret" not in body


@pytest.mark.asyncio
async def test_generate_diagram_stream_returns_public_validation_errors_as_sse(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            raise GenerationInputValidationError(
                "Unsupported canvas library: unknown",
                public_detail="Unsupported canvas library",
            )
            yield

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_init_error(
        body,
        message="Unsupported canvas library",
        detail="Unsupported canvas library",
    )


@pytest.mark.asyncio
async def test_generate_diagram_stream_hides_unexpected_init_value_error_details(
    monkeypatch,
):
    class FakeWorkflowGenerateService:
        async def generate_without_render_streaming(self, **kwargs):
            raise ValueError("internal parser secret-token")
            yield

    response = await _call_generate_diagram_stream(
        body=DiagramGenerateRequest(base_version=1, context="A to B", canvas_library="excalidraw"),
        current_user=None,
        workflow_service=FakeWorkflowGenerateService(),
    )
    body = await _stream_response_body(response)

    _assert_stream_init_error(body)
    assert "secret-token" not in body
