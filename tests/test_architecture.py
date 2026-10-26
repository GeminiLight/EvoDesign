"""Architecture validation: directory structure + import integrity.

Run:  python -m pytest tests/test_architecture.py -v
"""
import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

EVO_DIAGRAM_DIR = Path(__file__).resolve().parent.parent / "evo_diagram"
AGENTIC_DIR = EVO_DIAGRAM_DIR / "agentic_system"

# ── Directory structure ──────────────────────────────────────────────────────

EXPECTED_DIRS = [
    "../canvas_environment",
    "generation_stage",
    "generation_stage/structure",
    "generation_stage/styling",
    "generation_stage/layout",
    "generation_stage/unified",
    "verification_stage",
    "refinement_stage",
    "render_engine",
    "common",
]

OLD_DIRS_SHOULD_NOT_EXIST = [
    "structure_workflow",
    "styling_workflow",
    "layout_workflow",
    "unified_workflow",
    "verifier_workflow",
    "refiner_workflow",
    "render_workflow",
    "_legacy/vlm_refiner",
    "generation_stage/layout/tools/legacy",
    "system_prompt/legacy",
]


@pytest.mark.parametrize("rel_path", EXPECTED_DIRS)
def test_expected_dir_exists(rel_path):
    assert (AGENTIC_DIR / rel_path).is_dir(), f"Missing: {AGENTIC_DIR / rel_path}"


@pytest.mark.parametrize("rel_path", OLD_DIRS_SHOULD_NOT_EXIST)
def test_old_dir_removed(rel_path):
    assert not (AGENTIC_DIR / rel_path).exists(), f"Should not exist: {AGENTIC_DIR / rel_path}"


# ── No stale imports ─────────────────────────────────────────────────────────

IMPORT_RE = re.compile(
    r"(?:from|import)\s+(?:evo_diagram\.)?agentic_system\."
    r"(structure_workflow|styling_workflow|layout_workflow"
    r"|unified_workflow|verifier_workflow|refiner_workflow|render_workflow)"
)
STALE_AGENTIC_NAME_RE = re.compile(
    r"\b(structure_workflow|styling_workflow|layout_workflow"
    r"|unified_workflow|verifier_workflow|refiner_workflow|render_workflow)\b"
)

SKIP_DIRS = {"_legacy", "__pycache__", "node_modules"}
FORBIDDEN_TOP_LEVEL_ENGINE_ROOTS = {
    "agentic_system",
    "canvas_environment",
    "config",
    "core",
    "design_memory",
    "knowledge_evolution",
    "user_memory",
    "utils",
}
ACTIVE_SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"}


def test_no_stale_absolute_imports():
    violations = []
    for py_file in AGENTIC_DIR.rglob("*.py"):
        parts = set(py_file.relative_to(AGENTIC_DIR).parts)
        if parts & SKIP_DIRS:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if IMPORT_RE.search(line):
                violations.append(f"{py_file.relative_to(AGENTIC_DIR)}:{i}: {line.strip()}")
    assert not violations, "Stale imports found:\n" + "\n".join(violations)


def test_active_agentic_docs_do_not_reference_legacy_module_names():
    """Current package docs and comments should use the post-reorg names."""
    violations = []
    for file_path in AGENTIC_DIR.rglob("*"):
        if not file_path.is_file() or file_path.suffix not in {".py", ".md"}:
            continue
        parts = set(file_path.relative_to(AGENTIC_DIR).parts)
        if parts & SKIP_DIRS:
            continue
        text = file_path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if STALE_AGENTIC_NAME_RE.search(line):
                violations.append(
                    f"{file_path.relative_to(AGENTIC_DIR)}:{i}: {line.strip()}"
                )

    assert not violations, "Stale module names found:\n" + "\n".join(violations)


def test_evo_diagram_uses_package_qualified_internal_imports():
    """Internal package imports should not depend on legacy top-level aliases."""
    violations = []
    for py_file in EVO_DIAGRAM_DIR.rglob("*.py"):
        parts = set(py_file.relative_to(EVO_DIAGRAM_DIR).parts)
        if parts & SKIP_DIRS:
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            pytest.fail(f"Cannot parse {py_file.relative_to(EVO_DIAGRAM_DIR)}: {exc}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in FORBIDDEN_TOP_LEVEL_ENGINE_ROOTS:
                        violations.append(
                            f"{py_file.relative_to(EVO_DIAGRAM_DIR)}:{node.lineno}: "
                            f"import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                root = node.module.split(".", 1)[0]
                if root in FORBIDDEN_TOP_LEVEL_ENGINE_ROOTS:
                    violations.append(
                        f"{py_file.relative_to(EVO_DIAGRAM_DIR)}:{node.lineno}: "
                        f"from {node.module} import ..."
                    )

    assert not violations, (
        "Use evo_diagram.* or relative imports inside the package:\n"
        + "\n".join(violations)
    )


def test_canvas_environment_import_does_not_load_render_engine_internals():
    """The canvas facade should keep legacy render-engine imports lazy."""
    code = "\n".join(
        [
            "import sys",
            "import evo_diagram.canvas_environment",
            "loaded = sorted(",
            "    name for name in sys.modules",
            "    if name.startswith('evo_diagram.agentic_system.render_engine')",
            ")",
            "assert not loaded, loaded",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=EVO_DIAGRAM_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_canvas_runtime_import_does_not_load_canvas_facade_or_render_engine():
    """The low-level canvas runtime contract must stay below the facade."""
    code = "\n".join(
        [
            "import sys",
            "import evo_diagram.canvas_runtime as runtime",
            "assert runtime.normalize_canvas_library(' Excalidraw ') == 'excalidraw'",
            "for name in (",
            "    'evo_diagram.canvas_environment',",
            "    'evo_diagram.agentic_system.render_engine.service',",
            "    'evo_diagram.agentic_system.render_engine.workflow',",
            "):",
            "    assert name not in sys.modules, name",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=EVO_DIAGRAM_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_canvas_capabilities_import_does_not_load_agentic_system():
    """Canvas capability checks belong below agentic workflow orchestration."""
    code = "\n".join(
        [
            "import sys",
            "from evo_diagram.canvas_environment.capabilities import (",
            "    get_canvas_capabilities,",
            ")",
            "assert get_canvas_capabilities(' Excalidraw ').supports_refiner is True",
            "loaded = sorted(",
            "    name for name in sys.modules",
            "    if name.startswith('evo_diagram.agentic_system')",
            ")",
            "assert not loaded, loaded",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=EVO_DIAGRAM_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_knowledge_evolution_does_not_depend_on_agentic_capability_facade():
    """Non-agentic modules should use the canvas capability boundary directly."""
    knowledge_dir = EVO_DIAGRAM_DIR / "knowledge_evolution"
    violations = []

    for py_file in knowledge_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "evo_diagram.agentic_system.capabilities":
                        violations.append(
                            f"{py_file.relative_to(EVO_DIAGRAM_DIR)}:{node.lineno}: "
                            f"import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "evo_diagram.agentic_system.capabilities":
                    violations.append(
                        f"{py_file.relative_to(EVO_DIAGRAM_DIR)}:{node.lineno}: "
                        f"from {node.module} import ..."
                    )

    assert not violations, (
        "Use evo_diagram.canvas_environment.capabilities from knowledge_evolution:\n"
        + "\n".join(violations)
    )


def test_knowledge_evolution_uses_design_retriever_public_api():
    """Knowledge evolution should not reach into retriever private internals."""
    knowledge_dir = EVO_DIAGRAM_DIR / "knowledge_evolution"
    violations = []

    for py_file in knowledge_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not node.func.attr.startswith("_"):
                continue
            target = node.func.value
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "_retriever"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                violations.append(
                    f"{py_file.relative_to(EVO_DIAGRAM_DIR)}:{node.lineno}: "
                    f"self._retriever.{node.func.attr}(...)"
                )

    assert not violations, (
        "Route design-memory retrieval through DiagramDesignRetriever public APIs:\n"
        + "\n".join(violations)
    )


def test_canvas_environment_render_engine_imports_stay_in_private_adapter():
    """Only the private adapter may bridge to the legacy render engine."""
    canvas_dir = EVO_DIAGRAM_DIR / "canvas_environment"
    allowed = canvas_dir / "_render_engine_adapter.py"
    violations = []

    for py_file in canvas_dir.rglob("*.py"):
        if py_file == allowed:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("evo_diagram.agentic_system.render_engine"):
                        violations.append(
                            f"{py_file.relative_to(EVO_DIAGRAM_DIR)}:{node.lineno}: "
                            f"import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("evo_diagram.agentic_system.render_engine"):
                    violations.append(
                        f"{py_file.relative_to(EVO_DIAGRAM_DIR)}:{node.lineno}: "
                        f"from {node.module} import ..."
                    )

    assert not violations, (
        "Route canvas render-engine delegation through "
        "canvas_environment._render_engine_adapter:\n"
        + "\n".join(violations)
    )


def test_material_icon_legacy_routes_stay_in_icon_asset_boundary():
    """Legacy icon paths should not leak back into active source files."""
    allowed_files = {
        AGENTIC_DIR / "common" / "icon_assets.py",
    }
    forbidden_terms = ("public/material-icons", "/material-icons/")
    skip_dirs = SKIP_DIRS | {".next", "out"}
    violations = []

    for file_path in AGENTIC_DIR.rglob("*"):
        if not file_path.is_file() or file_path.suffix not in ACTIVE_SOURCE_SUFFIXES:
            continue
        if file_path in allowed_files:
            continue
        parts = set(file_path.relative_to(AGENTIC_DIR).parts)
        if parts & skip_dirs:
            continue
        text = file_path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if any(term in line for term in forbidden_terms):
                violations.append(
                    f"{file_path.relative_to(AGENTIC_DIR)}:{i}: {line.strip()}"
                )

    assert not violations, (
        "Use common.icon_assets for legacy Material icon route compatibility:\n"
        + "\n".join(violations)
    )


def test_canvas_renderer_packages_do_not_import_each_other():
    """Canvas-specific renderers should share code through render_engine.shared."""
    renderer_pairs = (
        ("excalidraw", "tldraw"),
        ("tldraw", "excalidraw"),
    )
    violations = []

    for renderer, forbidden in renderer_pairs:
        renderer_dir = AGENTIC_DIR / "render_engine" / renderer
        for py_file in renderer_dir.rglob("*.py"):
            parts = set(py_file.relative_to(AGENTIC_DIR).parts)
            if parts & SKIP_DIRS:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(
                            f"evo_diagram.agentic_system.render_engine.{forbidden}"
                        ):
                            violations.append(
                                f"{py_file.relative_to(AGENTIC_DIR)}:{node.lineno}: "
                                f"import {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    absolute_forbidden = (
                        f"evo_diagram.agentic_system.render_engine.{forbidden}"
                    )
                    relative_forbidden = (
                        node.level > 0 and node.module.startswith(forbidden)
                    )
                    if (
                        node.module.startswith(absolute_forbidden)
                        or relative_forbidden
                    ):
                        violations.append(
                            f"{py_file.relative_to(AGENTIC_DIR)}:{node.lineno}: "
                            f"from {'.' * node.level}{node.module} import ..."
                        )

    assert not violations, (
        "Move shared renderer logic to render_engine.shared:\n"
        + "\n".join(violations)
    )


# ── Module importability ─────────────────────────────────────────────────────

NEW_MODULES = [
    "evo_diagram.canvas_environment",
    "evo_diagram.canvas_environment.capabilities",
    "evo_diagram.canvas_environment.environment",
    "evo_diagram.canvas_environment.rendering",
    "evo_diagram.canvas_environment.validation",
    "evo_diagram.agentic_system.generation_stage.structure.workflow",
    "evo_diagram.agentic_system.generation_stage.styling.workflow",
    "evo_diagram.agentic_system.generation_stage.layout.workflow",
    "evo_diagram.agentic_system.generation_stage.unified.workflow",
    "evo_diagram.agentic_system.generation_stage.unified.sidecar",
    "evo_diagram.agentic_system.verification_stage.workflow",
    "evo_diagram.agentic_system.verification_stage.checks.finding",
    "evo_diagram.agentic_system.iterative_workflow",
    "evo_diagram.agentic_system.refinement_stage.fixers",
    "evo_diagram.agentic_system.render_engine.workflow",
    "evo_diagram.agentic_system.render_engine.service",
    "evo_diagram.agentic_system.render_engine.canvas_render",
    "evo_diagram.agentic_system.render_engine.shared.edge_routing",
    "evo_diagram.agentic_system.common",
    "evo_diagram.agentic_system.workflow",
    "evo_diagram.agentic_system.main",
]

OLD_MODULES = [
    "evo_diagram.agentic_system.capabilities",
    "evo_diagram.agentic_system.structure_workflow",
    "evo_diagram.agentic_system.styling_workflow",
    "evo_diagram.agentic_system.layout_workflow",
    "evo_diagram.agentic_system.unified_workflow",
    "evo_diagram.agentic_system.verifier_workflow",
    "evo_diagram.agentic_system.refiner_workflow",
    "evo_diagram.agentic_system.render_workflow",
    "evo_diagram.agentic_system._legacy.vlm_refiner",
    "evo_diagram.agentic_system.generation_stage.layout.tools.legacy.baseline_validator",
    "evo_diagram.agentic_system.generation_stage.layout.tools.legacy.dagre_client",
    "evo_diagram.agentic_system.render_engine.excalidraw.render",
    "evo_diagram.agentic_system.render_engine.tldraw.render",
    "evo_diagram.agentic_system.render_engine.shared.canvas",
    "evo_diagram.agentic_system.common.arrow_utils",
]


@pytest.mark.parametrize("module_path", NEW_MODULES)
def test_new_module_importable(module_path):
    try:
        importlib.import_module(module_path)
    except ImportError as e:
        pytest.fail(f"Cannot import {module_path}: {e}")


@pytest.mark.parametrize("module_path", OLD_MODULES)
def test_old_module_not_importable(module_path):
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module(module_path)


# ── Key symbols ──────────────────────────────────────────────────────────────

KEY_SYMBOLS = [
    ("evo_diagram.canvas_environment", "CanvasEnvironment"),
    ("evo_diagram.canvas_environment", "render_manifest"),
    ("evo_diagram.canvas_environment", "render_png_result"),
    ("evo_diagram.canvas_environment", "validate_manifest"),
    ("evo_diagram.agentic_system.workflow", "Text2DiagramWorkflow"),
    ("evo_diagram.agentic_system.workflow", "WorkflowState"),
    ("evo_diagram.agentic_system.generation_stage.structure.workflow", "StructureWorkflow"),
    ("evo_diagram.agentic_system.generation_stage.styling.workflow", "StylingWorkflow"),
    ("evo_diagram.agentic_system.generation_stage.layout.workflow", "LayoutWorkflow"),
    ("evo_diagram.agentic_system.generation_stage.unified.workflow", "UnifiedGeneratorWorkflow"),
    ("evo_diagram.agentic_system.generation_stage.unified.sidecar", "validate_semantic_sidecar"),
    ("evo_diagram.agentic_system.verification_stage.workflow", "VerifierWorkflow"),
    ("evo_diagram.agentic_system.iterative_workflow", "IterativeRefinerWorkflow"),
    ("evo_diagram.agentic_system.render_engine.workflow", "RenderWorkflow"),
    ("evo_diagram.agentic_system.render_engine", "render_png_result"),
    ("evo_diagram.agentic_system.render_engine.service", "render_manifest"),
    ("evo_diagram.agentic_system.render_engine.service", "render_png_result"),
    ("evo_diagram.agentic_system.render_engine.service", "RenderPngResult"),
    ("evo_diagram.agentic_system.render_engine.service", "RenderResult"),
    ("evo_diagram.agentic_system.verification_stage.checks.finding", "Finding"),
    ("evo_diagram.agentic_system.verification_stage.checks.finding", "Severity"),
]

LIBRARY_ONLY_WORKFLOWS = [
    "generation_stage/structure/workflow.py",
    "generation_stage/styling/workflow.py",
    "generation_stage/layout/workflow.py",
    "render_engine/workflow.py",
]


def test_agentic_system_canvas_calls_go_through_facade():
    """Agentic orchestration should not import render_engine internals directly."""
    violations = []
    allowed_parts = {
        "render_engine",
        "_legacy",
    }
    for py_file in AGENTIC_DIR.rglob("*.py"):
        rel_parts = set(py_file.relative_to(AGENTIC_DIR).parts)
        if rel_parts & allowed_parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "evo_diagram.agentic_system.render_engine" in stripped or "from ...render_engine" in stripped:
                violations.append(f"{py_file.relative_to(AGENTIC_DIR)}:{i}: {stripped}")
    assert not violations, "Canvas runtime imports should use canvas_environment:\n" + "\n".join(violations)


@pytest.mark.parametrize("rel_path", LIBRARY_ONLY_WORKFLOWS)
def test_library_workflows_do_not_define_debug_cli_blocks(rel_path):
    """The supported user CLI is agentic_system.main, not stage-local debug scripts."""
    py_file = AGENTIC_DIR / rel_path
    tree = ast.parse(py_file.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        comparison = ast.dump(node.test)
        assert "__main__" not in comparison, (
            f"{rel_path} should stay import-only; use "
            "evo_diagram.agentic_system.main for runnable CLI behavior."
        )


def _parent_map(tree):
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _ancestors(node, parents):
    current = parents.get(node)
    while current is not None:
        yield current
        current = parents.get(current)


def _is_cli_print(node, parents):
    for ancestor in _ancestors(node, parents):
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ancestor.name == "main":
                return True
        if isinstance(ancestor, ast.If) and "__main__" in ast.dump(ancestor.test):
            return True
    return False


def test_agentic_system_library_code_does_not_print_to_stdout():
    """Library paths should log diagnostics; stdout is reserved for CLI entrypoints."""
    violations = []

    for py_file in AGENTIC_DIR.rglob("*.py"):
        parts = set(py_file.relative_to(AGENTIC_DIR).parts)
        if parts & SKIP_DIRS:
            continue

        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        parents = _parent_map(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "print":
                continue
            if _is_cli_print(node, parents):
                continue
            violations.append(
                f"{py_file.relative_to(AGENTIC_DIR)}:{node.lineno}: print(...)"
            )

    assert not violations, (
        "Use module loggers outside main() or __main__ CLI guards:\n"
        + "\n".join(violations)
    )


def test_refiner_public_controls_do_not_expose_transitional_knobs():
    """Refiner convergence is fixed by serious-finding resolution, not ad hoc knobs."""
    forbidden_terms = (
        "skip_" + "llm",
        "convergence_" + "threshold",
        "--no-" + "llm",
        "--convergence-" + "threshold",
    )
    files = [
        AGENTIC_DIR / "iterative_workflow.py",
        AGENTIC_DIR / "refinement_stage" / "state.py",
        AGENTIC_DIR / "refinement_stage" / "__main__.py",
        AGENTIC_DIR / "refinement_stage" / "reports" / "refiner_report.py",
        Path(__file__).resolve().parent.parent
        / "backend"
        / "app"
        / "services"
        / "workflow_runtime"
        / "refiner.py",
    ]
    violations = []
    for file_path in files:
        text = file_path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            if term in text:
                violations.append(f"{file_path.relative_to(EVO_DIAGRAM_DIR.parent)}: {term}")

    assert not violations, "Transitional refiner controls found:\n" + "\n".join(violations)


def test_knowledge_evolution_dataset_schema_does_not_normalize_legacy_fields():
    """Knowledge evolution datasets should use the current content/content_area/query contract."""
    schemas_file = EVO_DIAGRAM_DIR / "knowledge_evolution" / "schemas.py"
    text = schemas_file.read_text(encoding="utf-8")
    forbidden_terms = (
        "model_validator",
        "\"text\"",
        "\"domain\"",
        "Legacy KS",
    )
    violations = [term for term in forbidden_terms if term in text]

    assert not violations, "Legacy dataset adapter terms found: " + ", ".join(violations)


@pytest.mark.parametrize("module_path,attr_name", KEY_SYMBOLS)
def test_key_symbols_exported(module_path, attr_name):
    mod = importlib.import_module(module_path)
    assert hasattr(mod, attr_name), f"{module_path} does not export {attr_name}"
