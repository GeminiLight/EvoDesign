from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = REPO_ROOT / "backend" / "app"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
FRONTEND_SOURCE_SUFFIXES = {".ts", ".tsx"}


def _python_string_tuple(path: Path, name: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            target_matches = any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
        elif isinstance(node, ast.AnnAssign):
            target_matches = isinstance(node.target, ast.Name) and node.target.id == name
        else:
            continue

        if not target_matches or not isinstance(node.value, ast.Tuple):
            continue

        values: list[str] = []
        for item in node.value.elts:
            if isinstance(item, ast.Starred) and isinstance(item.value, ast.Name):
                values.extend(_python_string_tuple(path, item.value.id))
            elif isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
        return tuple(values)
    raise AssertionError(f"{name} tuple not found in {path}")


def _ts_const_string_array(path: Path, name: str) -> tuple[str, ...]:
    source = path.read_text(encoding="utf-8")
    match = re.search(
        rf"{name}\s*=\s*\[(?P<values>.*?)\]\s+as const",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, f"{name} constant not found in {path}"
    return tuple(re.findall(r"'([^']+)'", match.group("values")))


def _ts_interface_field_names(path: Path, name: str) -> tuple[str, ...]:
    source = path.read_text(encoding="utf-8")
    match = re.search(
        rf"interface\s+{name}\s*\{{(?P<body>.*?)\n\}}",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, f"{name} interface not found in {path}"
    fields = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??:", match.group("body"), re.MULTILINE)
    return tuple(fields)


def _pydantic_model_field_names(path: Path, class_name: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue

        fields: list[str] = []
        for stmt in node.body:
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id != "model_config"
            ):
                fields.append(stmt.target.id)
        return tuple(fields)
    raise AssertionError(f"{class_name} model not found in {path}")


def _frontend_source_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in FRONTEND_SRC.rglob("*")
            if path.is_file() and path.suffix in FRONTEND_SOURCE_SUFFIXES
        )
    )


def test_frontend_diagram_service_does_not_advertise_mock_backend_capabilities():
    """Frontend API adapters should not return successful mocks for absent backend APIs."""
    service_source = (FRONTEND_SRC / "services" / "apiDiagramService.ts").read_text(
        encoding="utf-8"
    )
    api_types_source = (FRONTEND_SRC / "types" / "api.ts").read_text(
        encoding="utf-8"
    )
    forbidden_terms = (
        "optimizeArrows",
        "measureDifficulty",
        "ArrowOptimization",
        "DifficultyMeasure",
        "return mock",
        "Not implemented in backend yet",
    )

    for term in forbidden_terms:
        assert term not in service_source
        assert term not in api_types_source


def test_frontend_generate_payload_does_not_send_removed_edit_mode():
    """Diagram generation requests should match the backend public request schema."""
    service_source = (FRONTEND_SRC / "services" / "apiDiagramService.ts").read_text(
        encoding="utf-8"
    )
    workspace_source = (FRONTEND_SRC / "pages" / "WorkspacePage.tsx").read_text(
        encoding="utf-8"
    )

    assert "edit_mode" not in service_source
    assert "edit_mode" not in workspace_source


def test_frontend_sources_do_not_reintroduce_generation_edit_mode_flag():
    """The endpoint path, not a request flag, is the generation/local-edit boundary."""
    forbidden_terms = ("edit_mode", "editMode")
    offenders: list[str] = []

    for path in _frontend_source_files():
        source = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            if term in source:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {term}")

    assert offenders == []


def test_frontend_generate_payload_matches_backend_request_schema():
    """Generated generation DTO fields should match the backend envelope."""
    service_source = (FRONTEND_SRC / "services" / "apiDiagramService.ts").read_text(
        encoding="utf-8"
    )

    assert set(
        _ts_interface_field_names(
            FRONTEND_SRC / "contracts" / "backendApi.generated.ts",
            "BackendDiagramGenerateRequest",
        )
    ) == set(
        _pydantic_model_field_names(
            BACKEND_APP / "schemas" / "diagram_generate.py",
            "DiagramGenerateRequest",
        )
    )
    assert "BackendDiagramGenerateRequest" in service_source
    assert "buildGenerateDiagramPayload(" in service_source


def test_frontend_local_edit_payload_matches_backend_request_schema():
    """Generated local edit DTO should match the backend envelope."""
    api_types_source = (FRONTEND_SRC / "types" / "api.ts").read_text(encoding="utf-8")

    assert set(
        _ts_interface_field_names(
            FRONTEND_SRC / "contracts" / "backendApi.generated.ts",
            "BackendDiagramLocalEditRequest",
        )
    ) == set(
        _pydantic_model_field_names(
            BACKEND_APP / "schemas" / "diagram_generate.py",
            "DiagramLocalEditRequest",
        )
    )
    assert "export type DiagramLocalEditRequest = BackendDiagramLocalEditRequest" in api_types_source
    assert "edit_mode" not in api_types_source


def test_frontend_backend_api_uses_generated_project_and_dna_contracts():
    """Frontend backend adapter DTOs should come from generated OpenAPI types."""
    service_source = (FRONTEND_SRC / "services" / "backendApi.ts").read_text(
        encoding="utf-8"
    )
    api_types_source = (FRONTEND_SRC / "types" / "api.ts").read_text(encoding="utf-8")

    required_generated_types = (
        "BackendProjectListItem",
        "BackendProjectListResponse",
        "BackendProjectCreateRequest",
        "BackendProjectCreateResponse",
        "BackendDnaAnalyzeResponse",
        "BackendDnaRulesPayload",
        "BackendDnaRuleSchema",
    )
    for type_name in required_generated_types:
        assert type_name in service_source
        assert type_name in api_types_source

    forbidden_handwritten_dtos = (
        "type BackendProject =",
        "type BackendRule =",
        "Array<{ temp_id: number; cabin_id: string; title: string; preview: string }>",
        "data: { structure?: unknown[]; style?: unknown[]; layout?: unknown[] }",
    )
    for dto in forbidden_handwritten_dtos:
        assert dto not in service_source

    assert "normalizeBackendDiagramType(p.diagram_type)" in service_source
    assert "diagram_type: p.diagram_type || 'automated'" not in service_source


def test_frontend_stream_parser_validates_sse_payloads_before_dispatch():
    """SSE payloads should pass runtime guards before reaching UI callbacks."""
    service_source = (FRONTEND_SRC / "services" / "apiDiagramService.ts").read_text(
        encoding="utf-8"
    )
    guard_source = (FRONTEND_SRC / "services" / "streamEventGuards.ts").read_text(
        encoding="utf-8"
    )

    required_guards = (
        "export function isStreamStageStartEvent",
        "export function isStreamStageCompleteEvent",
        "export function isStreamRefineCompleteEvent",
        "export function isStreamRefineErrorEvent",
        "export function isRefinerSkippedEvent",
        "export function isStreamResultEvent",
        "export function isStreamErrorEvent",
        "export function assertStreamPayload",
    )
    forbidden_casts = (
        "parsed as StreamStageEvent",
        "parsed as StreamRefineCompleteEvent",
        "parsed as StreamRefineErrorEvent",
        "parsed as StreamResultEvent",
        "parsed as StreamErrorEvent",
    )

    assert "from './streamEventGuards'" in service_source
    for guard in required_guards:
        assert guard in guard_source
    for cast in forbidden_casts:
        assert cast not in service_source


def test_frontend_stream_event_contract_matches_backend_sse_contract():
    """Frontend stream literal unions should not drift from backend public SSE models."""
    backend_contract = BACKEND_APP / "services" / "workflow_runtime" / "event_payloads.py"
    frontend_contract = FRONTEND_SRC / "contracts" / "streamEvents.ts"
    frontend_source = frontend_contract.read_text(encoding="utf-8")

    assert "Generated by scripts/generate_frontend_api_contract.py" in frontend_source

    assert _ts_const_string_array(frontend_contract, "STREAM_STAGES") == _python_string_tuple(
        backend_contract,
        "STREAM_STAGE_VALUES",
    )
    assert _ts_const_string_array(frontend_contract, "STREAM_ERROR_STAGES") == _python_string_tuple(
        backend_contract,
        "STREAM_ERROR_STAGE_VALUES",
    )
    assert _ts_const_string_array(frontend_contract, "STREAM_REFINE_STATUSES") == _python_string_tuple(
        backend_contract,
        "REFINE_COMPLETE_STATUSES",
    )
    assert _ts_const_string_array(frontend_contract, "STREAM_EVENT_TYPES") == _python_string_tuple(
        backend_contract,
        "STREAM_EVENT_TYPES",
    )


def test_frontend_stage_complete_guard_requires_duration_ms():
    """Backend stage_complete payloads require duration_ms; the frontend guard should too."""
    guard_source = (FRONTEND_SRC / "services" / "streamEventGuards.ts").read_text(
        encoding="utf-8"
    )
    service_source = (FRONTEND_SRC / "services" / "apiDiagramService.ts").read_text(
        encoding="utf-8"
    )

    assert "export function isStreamStageStartEvent" in guard_source
    assert "export function isStreamStageCompleteEvent" in guard_source
    assert "isFiniteNumber((value as unknown as Record<string, unknown>).duration_ms)" in guard_source
    assert "isStreamStageStartEvent(value) || isStreamStageCompleteEvent(value)" in guard_source
    assert "assertStreamPayload(parsed, isStreamStageStartEvent, eventType)" in service_source
    assert "assertStreamPayload(parsed, isStreamStageCompleteEvent, eventType)" in service_source


def _backend_canvas_libraries() -> tuple[str, ...]:
    return _python_string_tuple(BACKEND_APP / "core" / "canvas.py", "SUPPORTED_CANVAS_LIBRARIES")


def _frontend_canvas_libraries() -> tuple[str, ...]:
    return _ts_const_string_array(FRONTEND_SRC / "contracts" / "canvas.ts", "CANVAS_LIBRARIES")


def test_frontend_canvas_contract_matches_backend_canvas_contract():
    """Frontend canvas identifiers should not drift from the backend API schema."""
    assert _frontend_canvas_libraries() == _backend_canvas_libraries()


def test_frontend_canvas_validation_uses_shared_contract():
    """Canvas parsing in frontend services should use the shared canvas contract."""
    contract_source = (FRONTEND_SRC / "contracts" / "canvas.ts").read_text(
        encoding="utf-8"
    )
    assert "export function isCanvasLibrary" in contract_source
    assert "export function normalizeCanvasLibraryOrNull" in contract_source
    assert "export function normalizeCanvasLibraryOrDefault" in contract_source

    service_files = (
        "services/apiDiagramService.ts",
        "services/backendApi.ts",
        "services/guestImportService.ts",
        "services/guestStorage.ts",
        "services/startupGenerationDraft.ts",
        "services/workspacePreflightDraft.ts",
        "services/workspaceRecoveryDraft.ts",
        "services/workspaceRouteHandoff.ts",
    )
    forbidden_local_guards = (
        "value === 'excalidraw' || value === 'tldraw'",
        "value === 'tldraw' || value === 'excalidraw'",
        "function normalizeRequestCanvasLibrary",
        "function normalizeCanvasLibrary(value",
        "const isCanvasMode =",
    )

    for rel_path in service_files:
        source = (FRONTEND_SRC / rel_path).read_text(encoding="utf-8")
        assert "../contracts/canvas" in source
        for guard in forbidden_local_guards:
            assert guard not in source


def test_workspace_route_handoff_logic_stays_out_of_page_component():
    """Workspace route/preflight parsing should live outside the route component."""
    page_source = (FRONTEND_SRC / "pages" / "WorkspacePage.tsx").read_text(
        encoding="utf-8"
    )
    handoff_source = (FRONTEND_SRC / "services" / "workspaceRouteHandoff.ts").read_text(
        encoding="utf-8"
    )

    assert "from '../services/workspaceRouteHandoff'" in page_source
    for exported_name in (
        "export const buildCreateHandoff",
        "export const getInitialPreflightGeneration",
        "export const getInitialStartupGenerationDraft",
        "export const isWorkspaceDiagramType",
    ):
        assert exported_name in handoff_source

    for local_helper in (
        "const getRoutePreflightGeneration",
        "const getRouteStartupGenerationDraft",
        "const normalizeStartupDraftForWorkspace",
        "const normalizePreflightForWorkspace",
    ):
        assert local_helper not in page_source
