"""Unexpected refiner exceptions degrade to status=failed, never crash the run."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_iteration_exception_marks_refiner_failed_and_skips_refined_output(tmp_path, monkeypatch):
    import evodesign.agentic_system.iterative_workflow as iterative_workflow
    from evodesign.agentic_system.iterative_workflow import IterativeRefinerWorkflow

    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    manifest_path.write_text('{"elements": []}', encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    def explode(*_args, **_kwargs):
        raise ZeroDivisionError("degenerate bbox")

    monkeypatch.setattr(iterative_workflow, "_run_one_iteration", explode)
    monkeypatch.setattr(
        iterative_workflow, "render_png_result",
        lambda *a, **k: pytest.fail("a failed refiner must not render a refined output"),
    )

    state = IterativeRefinerWorkflow(llm_agent=SimpleNamespace()).run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(tmp_path / "refiner"),
        max_iterations=2,
    )

    assert state.status == "failed"
    assert state.refined_manifest_path is None
    assert any("ZeroDivisionError" in error for error in state.errors)


def test_max_iterations_is_capped_and_sets_a_matching_recursion_limit():
    from evodesign.agentic_system.refinement_stage.state import (
        MAX_REFINER_ITERATIONS,
        VerifierRefinerState,
        refiner_recursion_limit,
    )

    with pytest.raises(ValueError):
        VerifierRefinerState(manifest_path="m", image_path="i", max_iterations=MAX_REFINER_ITERATIONS + 1)
    # load_inputs + N iterations + finalize must fit in the recursion limit.
    assert refiner_recursion_limit(MAX_REFINER_ITERATIONS) >= MAX_REFINER_ITERATIONS + 2


def test_cli_rejects_out_of_range_refiner_iterations():
    from evodesign.agentic_system import main as cli_main
    from evodesign.agentic_system.config import AgenticSystemConfig

    args = SimpleNamespace(example=1, start=None, end=None, ids=None, all=False)
    with pytest.raises(ValueError, match="refiner-iterations"):
        cli_main.validate_config(AgenticSystemConfig(refiner_iterations=1000), args)


def test_workflow_keeps_verified_render_when_refiner_raises(tmp_path, monkeypatch):
    import evodesign.agentic_system.workflow as workflow_module
    import evodesign.agentic_system.quality_policy as quality_policy

    class ExplodingRefiner:
        def run(self, **_kwargs):
            raise RuntimeError("geometry helper blew up")

    monkeypatch.setattr(workflow_module, "IterativeRefinerWorkflow", ExplodingRefiner)
    monkeypatch.setattr(quality_policy, "should_refine", lambda *_a, **_k: True)

    workflow = object.__new__(workflow_module.Text2DiagramWorkflow)
    workflow.verification_only = False
    workflow.enable_refiner = True
    workflow.always_refine = False
    workflow.canvas_library = "excalidraw"
    workflow.refiner_max_iterations = 2
    workflow.mode = "multiagent"
    workflow.design_constraints = ""

    generation = SimpleNamespace(artifact_paths={})
    result = workflow._run_refinement_phase(
        render_result=SimpleNamespace(manifest_path="m.json", png_path="m.png"),
        generation=generation,
        verification=SimpleNamespace(state=SimpleNamespace(has_blocking_errors=False, report_path=None)),
        save_dir=str(tmp_path),
    )

    assert result.manifest is None and result.png_path is None
    assert result.state.status == "failed"
    assert "geometry helper blew up" in result.state.errors[0]
    assert "refined_manifest_path" not in generation.artifact_paths


@pytest.mark.parametrize("directives,expected", [
    ('=== RUNTIME DIRECTIVES (HIGHEST PRIORITY) ===\n{"locked_nodes": ["a", "b"]}\n\n', ["a", "b"]),
    ('{"locked_nodes": ["a"]}', ["a"]),
    ("", []),
])
def test_locked_nodes_are_recovered_from_runtime_directives(directives, expected):
    from evodesign.agentic_system.workflow import _locked_nodes_from_runtime_directives

    assert _locked_nodes_from_runtime_directives(directives) == expected


def test_unparsable_runtime_directives_are_logged(caplog):
    from evodesign.agentic_system.workflow import _locked_nodes_from_runtime_directives

    with caplog.at_level("WARNING"):
        assert _locked_nodes_from_runtime_directives("lock node a please") == []
    assert "locked nodes" in caplog.text


def test_explicit_locked_nodes_take_precedence_over_directives(monkeypatch):
    import evodesign.agentic_system.workflow as workflow_module
    import evodesign.agentic_system.common.design_constraints as constraints_module

    captured = {}

    def fake_constraints(**kwargs):
        captured.update(kwargs)
        return "constraints"

    monkeypatch.setattr(constraints_module, "build_design_constraints", fake_constraints)
    workflow = object.__new__(workflow_module.Text2DiagramWorkflow)
    workflow.build_design_expertise = lambda *a, **k: ""
    class _Stop(Exception):
        pass

    def stop(**_kwargs):
        raise _Stop

    workflow.generator = SimpleNamespace(run=stop)

    with pytest.raises(_Stop):
        workflow._run_generation_phase(
            text_content="t", user_query="q", design_expertise="",
            runtime_directives='{"locked_nodes": ["from-directives"]}',
            diagram_type=None, content_area=None, save_dir="/unused",
            locked_nodes=["explicit"],
        )
    assert captured["locked_nodes"] == ["explicit"]
