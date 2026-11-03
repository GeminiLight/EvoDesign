"""Package import hygiene tests."""

import os
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _package_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(_REPO_ROOT)
    return env


def test_evodesign_package_import_has_no_legacy_alias_side_effects():
    for alias in ("agentic_system", "canvas_environment", "config", "core", "utils"):
        sys.modules.pop(alias, None)

    import evodesign  # noqa: F401

    for alias in ("agentic_system", "canvas_environment", "config", "core", "utils"):
        assert alias not in sys.modules


def test_config_imports_do_not_install_top_level_aliases():
    for alias in ("config.settings", "config.model_loader"):
        sys.modules.pop(alias, None)

    import evodesign.config.model_loader  # noqa: F401
    import evodesign.config.settings  # noqa: F401

    assert "config.settings" not in sys.modules
    assert "config.model_loader" not in sys.modules


def test_knowledge_evolution_module_cli_imports_in_package_mode():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "evodesign.knowledge_evolution",
            "--help",
        ],
        cwd=_REPO_ROOT,
        env=_package_env(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DiagramKnowledgeEvolver" in result.stdout
    assert "--output-dir" in result.stdout
    assert "--max-iters" in result.stdout
    assert "--design-memory-mode" in result.stdout
    assert "--generation-role" in result.stdout
    assert "--distillation-role" in result.stdout
    assert "--judge-role" in result.stdout
    assert "--role" not in result.stdout
    assert "--skip-retrieval" not in result.stdout
    assert "--output_dir" not in result.stdout
    assert "--max_iters" not in result.stdout


def test_user_memory_imports_in_package_mode():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import evodesign.user_memory; print('ok')",
        ],
        cwd=_REPO_ROOT,
        env=_package_env(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_user_memory_package_import_is_lightweight():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import evodesign.user_memory; "
                "blocked = [name for name in ("
                "'evodesign.user_memory.main', "
                "'evodesign.user_memory.storage.mem0_storage', "
                "'evodesign.user_memory.extractors.llm_preference_agent', "
                "'evodesign.user_memory.extractors.vlm_observer'"
                ") if name in sys.modules]; "
                "print(blocked)"
            ),
        ],
        cwd=_REPO_ROOT,
        env=_package_env(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_user_memory_main_import_is_lightweight():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import evodesign.user_memory.main; "
                "blocked = [name for name in ("
                "'evodesign.core.llm_factory', "
                "'evodesign.user_memory.storage.mem0_storage', "
                "'evodesign.user_memory.extractors.llm_preference_agent', "
                "'evodesign.user_memory.extractors.vlm_observer'"
                ") if name in sys.modules]; "
                "print(blocked)"
            ),
        ],
        cwd=_REPO_ROOT,
        env=_package_env(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_user_memory_diff_extractor_import_does_not_load_llm_extractors():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import evodesign.user_memory.extractors.diff_extractor; "
                "blocked = [name for name in ("
                "'evodesign.user_memory.extractors.llm_preference_agent', "
                "'evodesign.user_memory.extractors.vlm_observer'"
                ") if name in sys.modules]; "
                "print(blocked)"
            ),
        ],
        cwd=_REPO_ROOT,
        env=_package_env(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_render_engine_imports_do_not_load_canvas_environment_facade():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                "[importlib.import_module(name) for name in ("
                "'evodesign.agentic_system.render_engine.workflow', "
                "'evodesign.agentic_system.render_engine.canvas_render', "
                "'evodesign.agentic_system.render_engine.service'"
                ")]; "
                "blocked = [name for name in ("
                "'evodesign.canvas_environment', "
                "'canvas_environment'"
                ") if name in sys.modules]; "
                "print(blocked)"
            ),
        ],
        cwd=_REPO_ROOT,
        env=_package_env(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_canvas_runtime_owns_render_result_contract():
    from evodesign.canvas_runtime import RenderResult, normalize_canvas_library
    from evodesign.canvas_environment import RenderResult as FacadeRenderResult
    from evodesign.agentic_system.render_engine.service import (
        RenderResult as LegacyRenderResult,
    )

    assert FacadeRenderResult is RenderResult
    assert LegacyRenderResult is RenderResult
    assert normalize_canvas_library(" TLDraw ") == "tldraw"
