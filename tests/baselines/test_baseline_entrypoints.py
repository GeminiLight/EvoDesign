import subprocess
import sys


ENTRYPOINT_MODULES = [
    "baselines.direct_llm.main",
    "baselines.direct_llm.handydirectllmrefiner",
    "baselines.programmic.mermaid.main",
    "baselines.programmic.tlkz.main",
    "baselines.pixel.gemini_image_generator",
    "baselines.pixel.apimart_image_generator",
    "baselines.diagramagent.DiagramAgentEvaluator",
    "baselines.scisketch.src.custom_main",
]


def test_baseline_module_entrypoints_show_help():
    for module in ENTRYPOINT_MODULES:
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, f"{module} failed:\n{result.stderr}"
        assert "usage:" in result.stdout.lower()


def _run_help_import_boundary_check(module, unexpected_modules):
    script = f"""
import runpy
import sys

sys.argv = [{module!r}, "--help"]
try:
    runpy.run_module({module!r}, run_name="__main__")
except SystemExit as exc:
    rc = exc.code
else:
    rc = 0

unexpected_modules = {tuple(unexpected_modules)!r}
loaded = set(name for name in unexpected_modules if name in sys.modules)
if loaded:
    raise SystemExit("unexpected eager imports: " + repr(sorted(loaded)))
raise SystemExit(rc)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_mermaid_help_does_not_load_llm_stack():
    _run_help_import_boundary_check(
        "baselines.programmic.mermaid.main",
        (
            "evo_diagram.core.llm_factory",
            "baselines.programmic.mermaid.mermaid_agent",
        ),
    )


def test_tlkz_help_does_not_load_llm_stack():
    _run_help_import_boundary_check(
        "baselines.programmic.tlkz.main",
        (
            "evo_diagram.core.llm_factory",
            "baselines.programmic.tlkz.tlkz_agent",
        ),
    )
