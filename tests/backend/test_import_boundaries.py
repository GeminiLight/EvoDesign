from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import evo_imports
from app.core.security import create_access_token, verify_token

ROOT = Path(__file__).resolve().parents[2]


def _run_import_probe(
    code: str,
    *,
    pythonpath: str,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("JWT_SECRET", None)
    env.pop("SESSION_SECRET", None)
    env["PYTHONPATH"] = pythonpath

    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd or os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_backend_boundary_modules_import_without_runtime_secrets():
    code = "\n".join(
        [
            "import app.core.security",
            "import app.db.session",
            "import app.application",
            "import app.services.auth_service",
            "import app.services.auth_token_service",
            "import app.services.diagram_persistence_service",
            "import app.services.diagram_stream_service",
            "import app.services.dna_analysis_service",
            "import app.services.dna_rule_service",
            "import app.services.oauth_profile_service",
            "import app.services.oauth_session_service",
            "import app.services.workflow_engine_adapter",
            "import app.services.workflow_engine_port",
            "import app.services.workflow_generate_service",
            "import app.api.v1.endpoints.auth",
            "import app.api.v1.endpoints.dna",
        ]
    )
    result = _run_import_probe(code, pythonpath="backend:evo_diagram:.")

    assert result.returncode == 0, result.stderr


def test_backend_service_imports_do_not_mutate_sys_path():
    code = "\n".join(
        [
            "import sys",
            "before = list(sys.path)",
            "import app.services.llm_client",
            "import app.services.workflow_engine_adapter",
            "import app.services.dna_analysis_service",
            "after = list(sys.path)",
            "assert after == before, (before, after)",
        ]
    )
    result = _run_import_probe(code, pythonpath="backend:.")

    assert result.returncode == 0, result.stderr


def test_workflow_engine_adapter_init_does_not_import_engine_internals():
    code = "\n".join(
        [
            "import sys",
            "before = list(sys.path)",
            "import app.services.workflow_engine_adapter as adapter",
            "adapter.WorkflowEngineAdapter(results_dir='/tmp/evodiagram-test')",
            "after = list(sys.path)",
            "assert after == before, (before, after)",
            "for name in (",
            "    'evo_diagram.agentic_system.workflow',",
            "    'evo_diagram.agentic_system.generation_stage.structure.state',",
            "    'evo_diagram.agentic_system.generation_stage.styling.state',",
            "    'evo_diagram.agentic_system.generation_stage.layout.state',",
            "    'evo_diagram.agentic_system.verification_stage.workflow',",
            "    'evo_diagram.agentic_system.iterative_workflow',",
            "    'evo_diagram.canvas_environment',",
            "):",
            "    assert name not in sys.modules, name",
        ]
    )
    result = _run_import_probe(code, pythonpath="backend:.")

    assert result.returncode == 0, result.stderr


def test_workflow_engine_port_init_does_not_import_engine_internals():
    code = "\n".join(
        [
            "import sys",
            "before = list(sys.path)",
            "from app.services.workflow_engine_port import EvoDiagramWorkflowEnginePort",
            "EvoDiagramWorkflowEnginePort()",
            "after = list(sys.path)",
            "assert after == before, (before, after)",
            "for name in (",
            "    'evo_diagram.agentic_system.workflow',",
            "    'evo_diagram.agentic_system.generation_stage.structure.state',",
            "    'evo_diagram.agentic_system.generation_stage.styling.state',",
            "    'evo_diagram.agentic_system.generation_stage.layout.state',",
            "    'evo_diagram.agentic_system.verification_stage.workflow',",
            "    'evo_diagram.agentic_system.iterative_workflow',",
            "    'evo_diagram.canvas_environment',",
            "):",
            "    assert name not in sys.modules, name",
        ]
    )
    result = _run_import_probe(code, pythonpath="backend:.")

    assert result.returncode == 0, result.stderr


def test_workflow_engine_adapter_keeps_engine_imports_in_port_module():
    adapter_path = ROOT / "backend" / "app" / "services" / "workflow_engine_adapter.py"
    adapter_source = adapter_path.read_text(encoding="utf-8")
    port_source = (
        ROOT / "backend" / "app" / "services" / "workflow_engine_port.py"
    ).read_text(encoding="utf-8")

    assert "evo_diagram.agentic_system" not in adapter_source
    assert "from evo_diagram.canvas_environment" not in adapter_source
    assert "evo_diagram.agentic_system.workflow" in port_source
    assert "from evo_diagram.canvas_environment" in port_source


def test_backend_canvas_capabilities_match_engine_contract():
    code = "\n".join(
        [
            "from app.core.canvas import (",
            "    SUPPORTED_CANVAS_LIBRARIES,",
            "    SUPPORTED_REFINER_CANVAS_LIBRARIES,",
            "    canvas_library_supports_refiner,",
            ")",
            "from evo_diagram.canvas_environment.capabilities import (",
            "    get_canvas_capabilities,",
            ")",
            "engine_libraries = tuple(SUPPORTED_CANVAS_LIBRARIES)",
            "engine_refiner_libraries = tuple(",
            "    name",
            "    for name in engine_libraries",
            "    if get_canvas_capabilities(name).supports_refiner",
            ")",
            "assert SUPPORTED_CANVAS_LIBRARIES == ('excalidraw', 'tldraw')",
            "assert SUPPORTED_REFINER_CANVAS_LIBRARIES == engine_refiner_libraries",
            "for name in engine_libraries:",
            "    assert canvas_library_supports_refiner(name) is (name in engine_refiner_libraries)",
        ]
    )
    result = _run_import_probe(code, pythonpath="backend:.")

    assert result.returncode == 0, result.stderr or result.stdout


def test_workflow_engine_adapter_uses_public_engine_api_methods():
    adapter_path = ROOT / "backend" / "app" / "services" / "workflow_engine_adapter.py"
    tree = ast.parse(adapter_path.read_text(encoding="utf-8"))
    engine_object_names = {"workflow", "generator"}
    violations = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not node.func.attr.startswith("_"):
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id not in engine_object_names:
            continue
        violations.append(
            f"{adapter_path.relative_to(ROOT)}:{node.lineno}: "
            f"{node.func.value.id}.{node.func.attr}(...)"
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr != "generator":
            continue
        if not isinstance(node.value, ast.Name):
            continue
        if node.value.id == "workflow":
            violations.append(
                f"{adapter_path.relative_to(ROOT)}:{node.lineno}: "
                "workflow.generator"
            )

    assert not violations, (
        "Backend workflow adapters should use public workflow APIs:\n"
        + "\n".join(violations)
    )


def test_evodiagram_import_helper_prefers_package_imports_before_path_fallback():
    code = "\n".join(
        [
            "import sys",
            "from app.core.evo_imports import REPO_ROOT, ensure_evo_diagram_importable",
            "before = list(sys.path)",
            "ensure_evo_diagram_importable()",
            "after = list(sys.path)",
            "assert str(REPO_ROOT / 'evo_diagram') not in after[:2], after",
            "assert after == before, (before, after)",
            "import evo_diagram.agentic_system.workflow",
            "import evo_diagram.canvas_environment",
            "import evo_diagram.core.llm_factory",
        ]
    )
    result = _run_import_probe(code, pythonpath="backend:.")

    assert result.returncode == 0, result.stderr


def test_evodiagram_import_helper_uses_checkout_package_root_when_package_missing():
    code = "\n".join(
        [
            "import sys",
            "from app.core.evo_imports import REPO_ROOT, ensure_evo_diagram_importable",
            "ensure_evo_diagram_importable()",
            "assert str(REPO_ROOT) in sys.path[:2], sys.path[:4]",
            "assert str(REPO_ROOT / 'evo_diagram') not in sys.path[:4], sys.path[:4]",
            "import evo_diagram.agentic_system.workflow",
            "import evo_diagram.canvas_environment",
            "import evo_diagram.core.llm_factory",
        ]
    )
    result = _run_import_probe(code, pythonpath=".", cwd=os.path.join(os.getcwd(), "backend"))

    assert result.returncode == 0, result.stderr


def test_evodiagram_import_helper_reports_all_failed_resolution_stages(
    monkeypatch,
    tmp_path,
):
    before_path = list(sys.path)
    calls: list[str] = []

    def fail_engine_modules():
        calls.append("engine")
        raise ModuleNotFoundError("missing evo_diagram package", name="evo_diagram")

    monkeypatch.setattr(evo_imports, "_import_engine_modules", fail_engine_modules)
    monkeypatch.setattr(evo_imports, "REPO_ROOT", tmp_path / "repo")

    try:
        with pytest.raises(evo_imports.EvoDiagramImportError) as exc_info:
            evo_imports.ensure_evo_diagram_importable()
    finally:
        sys.path[:] = before_path

    assert calls == ["engine", "engine"]
    assert [attempt.stage for attempt in exc_info.value.attempts] == [
        "evo_diagram package",
        "source checkout package path",
    ]
    assert [attempt.error.name for attempt in exc_info.value.attempts] == [
        "evo_diagram",
        "evo_diagram",
    ]
    assert exc_info.value.__cause__ is exc_info.value.attempts[-1].error
    assert "missing evo_diagram package" in str(exc_info.value)


def test_evodiagram_import_helper_reports_source_checkout_verification_failures(
    monkeypatch,
    tmp_path,
):
    before_path = list(sys.path)
    calls: list[str] = []
    failures = iter(
        [
            ModuleNotFoundError("missing installed package", name="evo_diagram"),
            ModuleNotFoundError("missing checkout module", name="evo_diagram.canvas_environment"),
        ]
    )

    def fail_engine_modules():
        calls.append("engine")
        raise next(failures)

    monkeypatch.setattr(evo_imports, "_import_engine_modules", fail_engine_modules)
    monkeypatch.setattr(evo_imports, "REPO_ROOT", tmp_path / "repo")

    try:
        with pytest.raises(evo_imports.EvoDiagramImportError) as exc_info:
            evo_imports.ensure_evo_diagram_importable()
    finally:
        sys.path[:] = before_path

    assert calls == ["engine", "engine"]
    assert [attempt.stage for attempt in exc_info.value.attempts] == [
        "evo_diagram package",
        "source checkout package path",
    ]
    assert [attempt.error.name for attempt in exc_info.value.attempts] == [
        "evo_diagram",
        "evo_diagram.canvas_environment",
    ]


def test_evodiagram_import_helper_stops_on_non_engine_dependency_failures(
    monkeypatch,
    tmp_path,
):
    before_path = list(sys.path)
    calls: list[str] = []

    def fail_engine_modules():
        calls.append("engine")
        raise ModuleNotFoundError(
            "missing transitive dependency",
            name="missing_dependency",
        )

    def unexpected_import(module_name: str):
        raise AssertionError(f"unexpected fallback import: {module_name}")

    monkeypatch.setattr(evo_imports, "_import_engine_modules", fail_engine_modules)
    monkeypatch.setattr(evo_imports.importlib, "import_module", unexpected_import)
    monkeypatch.setattr(evo_imports, "REPO_ROOT", tmp_path / "repo")

    try:
        with pytest.raises(evo_imports.EvoDiagramImportError) as exc_info:
            evo_imports.ensure_evo_diagram_importable()
    finally:
        sys.path[:] = before_path

    assert calls == ["engine"]
    assert [attempt.stage for attempt in exc_info.value.attempts] == ["evo_diagram package"]
    assert exc_info.value.attempts[0].error.name == "missing_dependency"
    assert str(tmp_path / "repo") not in sys.path


def test_import_engine_modules_annotates_required_module_failures(monkeypatch):
    def fail_import(module_name: str):
        assert module_name == evo_imports.REQUIRED_ENGINE_MODULES[0]
        raise ModuleNotFoundError(
            "missing transitive dependency",
            name="missing_dependency",
        )

    monkeypatch.setattr(evo_imports.importlib, "import_module", fail_import)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        evo_imports._import_engine_modules()

    assert exc_info.value.name == "missing_dependency"
    assert "evo_diagram.agentic_system.workflow" in str(exc_info.value)
    assert exc_info.value.__cause__.name == "missing_dependency"


def test_security_helpers_accept_injected_settings():
    settings = SimpleNamespace(
        jwt_secret="test-jwt-secret",
        jwt_algorithm="HS256",
        jwt_expires_in=60,
    )

    token = create_access_token({"user_id": "u_1"}, settings=settings)
    payload = verify_token(token, settings=settings)

    assert payload is not None
    assert payload["user_id"] == "u_1"
