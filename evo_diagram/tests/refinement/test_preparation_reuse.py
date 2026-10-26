import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evo_diagram.agentic_system import iterative_workflow as workflow
from evo_diagram.agentic_system.refinement_stage.state import EditOp, IterationLog, VerifierRefinerState


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    manifest = {"elements": [{"id": "n", "type": "rectangle", "x": 10, "y": 10,
                              "width": 100, "height": 50}]}
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(manifest))
    image = tmp_path / "scene.png"
    image.write_bytes(b"input")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"subjective": {"summary": "Keep the corrected spacing", "overall_score": 6}}))
    renders = []

    def render(manifest, output_path, **kwargs):
        renders.append((output_path, kwargs))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"render")
        return SimpleNamespace(ok=True, output_path=output_path)

    monkeypatch.setattr(workflow, "run_all_checks", lambda *a, **k: [])
    monkeypatch.setattr(workflow, "run_all_deterministic_fixers", lambda *a: [
        EditOp(op="set_position", id="n", payload={"x": 30, "y": 10})])
    monkeypatch.setattr(workflow, "render_png_result", render)
    return dict(manifest_path=str(path), image_path=str(image), output_dir=str(tmp_path / "out")), report, renders


def test_preparation_does_not_call_model_and_consumes_completed_critic_once(prepared_inputs):
    inputs, report, renders = prepared_inputs
    seen = []

    class Agent:
        def propose_edits(self, **kwargs):
            seen.append(kwargs)
            assert kwargs["critique"]["summary"] == "Keep the corrected spacing"
            assert kwargs["manifest_summary"][0]["bbox"][0] == 30
            return []

    refiner = workflow.IterativeRefinerWorkflow(llm_agent=Agent())
    prepared = refiner.prepare(**inputs, max_iterations=2)
    assert seen == []
    assert len(renders) == 0  # lazy analysis render after the critic requests work
    result = refiner.run_prepared(prepared, verifier_report_path=str(report))
    assert result.converged
    assert len(seen) == 1
    assert len(result.iteration_logs[0].deterministic_edits) == 1
    assert len(renders) == 2  # analysis once + full-resolution final output
    assert "render_scale" not in renders[-1][1]
    assert json.loads(Path(inputs["manifest_path"]).read_text())["elements"][0]["x"] == 10


def test_prepared_work_rejects_changed_input(prepared_inputs):
    inputs, report, _ = prepared_inputs
    refiner = workflow.IterativeRefinerWorkflow()
    prepared = refiner.prepare(**inputs)
    Path(inputs["manifest_path"]).write_text('{"elements": []}')
    with pytest.raises(ValueError, match="changed after preparation"):
        refiner.run_prepared(prepared, verifier_report_path=str(report))


def test_unchanged_analysis_image_reused_but_geometry_change_invalidates_it(prepared_inputs):
    inputs, _, renders = prepared_inputs
    refiner = workflow.IterativeRefinerWorkflow()
    state = refiner.prepare(**inputs)
    log = IterationLog(iteration=2)
    workflow._refresh_image_for_llm(state, log=log, iteration=2)
    assert len(renders) == 1
    state.manifest["elements"][0]["x"] += 10
    workflow._refresh_image_for_llm(state, log=log, iteration=2)
    assert len(renders) == 2


def test_resolved_minor_work_skips_both_analysis_render_and_refiner_model(prepared_inputs):
    inputs, report, renders = prepared_inputs
    report.write_text(json.dumps({"subjective": {"overall_score": 8.5}}))
    class Agent:
        def propose_edits(self, **kwargs):
            pytest.fail("Resolved work must not call the model")
    refiner = workflow.IterativeRefinerWorkflow(llm_agent=Agent())
    prepared = refiner.prepare(**inputs)
    assert renders == []
    result = refiner.run_prepared(prepared, verifier_report_path=str(report))
    assert result.converged
    assert len(renders) == 1  # full-resolution product only
