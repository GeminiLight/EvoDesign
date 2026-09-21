"""Top-level workflow contracts for adopting refiner outputs."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _generator_outputs() -> dict:
    return {
        "structure_instantiation": {
            "chart_type": "flowchart",
            "nodes": [{"id": "n1", "label": "A", "class": "process"}],
            "edges": [],
            "groups": [],
        },
        "structure_specification": {"chart_type": "flowchart"},
        "styling_instantiation": {
            "n1": {
                "shape": "rectangle",
                "label": {"text": "A"},
                "strokeColor": "#111111",
                "backgroundColor": "#ffffff",
            }
        },
        "styling_specification": {"palette": "neutral"},
        "layout_instantiation": {"n1": {"x": 10, "y": 20, "w": 120, "h": 60}},
        "layout_specification": {"bounds": "ok"},
        "artifact_paths": {
            "structure_instantiation_path": "/tmp/structure.json",
            "layout_instantiation_path": "/tmp/layout.json",
        },
    }


def test_refiner_findings_summary_handles_supported_shapes():
    from evo_diagram.agentic_system.workflow import _refiner_findings_summary

    class PydanticLikeFinding:
        def model_dump(self):
            return {"severity": "minor", "message": "model dump"}

    assert _refiner_findings_summary(None) is None
    assert _refiner_findings_summary(SimpleNamespace(latest_findings="bad")) is None
    assert _refiner_findings_summary(
        SimpleNamespace(
            latest_findings=[
                {"severity": "major", "message": "dict"},
                PydanticLikeFinding(),
                "plain",
            ],
        )
    ) == [
        {"severity": "major", "message": "dict"},
        {"severity": "minor", "message": "model dump"},
        {"message": "plain"},
    ]


def test_workflow_refiner_runs_after_nonblocking_verification_error(
    tmp_path,
    monkeypatch,
):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import (
        _GenerationArtifacts,
        _VerificationPhaseResult,
        Text2DiagramWorkflow,
    )
    from evo_diagram.canvas_environment import RenderResult

    manifest_path = tmp_path / "4_render" / "diagram_manifest.json"
    image_path = tmp_path / "4_render" / "diagram_manifest.png"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text('{"elements": [{"id": "base"}]}', encoding="utf-8")
    image_path.write_bytes(b"base-png")

    refined_manifest_path = tmp_path / "7_refiner" / "refined_manifest.json"
    refined_image_path = tmp_path / "7_refiner" / "refined_diagram.png"
    refined_manifest_path.parent.mkdir(parents=True)
    refined_manifest_path.write_text(
        '{"elements": [{"id": "refined"}]}',
        encoding="utf-8",
    )
    refined_image_path.write_bytes(b"refined-png")

    refiner = MagicMock()
    refiner_state = MagicMock()
    refiner_state.status = "reported"
    refiner_state.current_iteration = 1
    refiner_state.converged = True
    refiner_state.termination_reason = "resolved"
    refiner_state.refined_manifest_path = str(refined_manifest_path)
    refiner_state.refined_image_path = str(refined_image_path)
    refiner_state.candidate_manifest_path = None
    refiner_state.candidate_image_path = None
    refiner_state.refiner_report_path = None
    refiner_state.errors = []
    refiner_state.latest_findings = []
    refiner.run.return_value = refiner_state
    monkeypatch.setattr(workflow_module, "IterativeRefinerWorkflow", lambda: refiner)

    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.mode = "multiagent"
    workflow.enable_refiner = True
    workflow.verification_only = False
    workflow.canvas_library = "excalidraw"
    workflow.refiner_max_iterations = 2

    verification_state = SimpleNamespace(
        has_errors=True,
        has_blocking_errors=False,
        errors=["subjective critic failed: model unavailable"],
        blocking_errors=[],
        report_path=None,
    )
    generation = _GenerationArtifacts(
        structure_instantiation={},
        structure_specification=None,
        styling_instantiation={},
        styling_specification=None,
        layout_instantiation={},
        layout_specification=None,
        diagram_manifest=None,
        artifact_paths={},
    )

    result = workflow._run_refinement_phase(
        render_result=RenderResult(
            manifest={"elements": [{"id": "base"}]},
            manifest_path=str(manifest_path),
            png_path=str(image_path),
        ),
        generation=generation,
        verification=_VerificationPhaseResult(
            state=verification_state,
            output_dir=str(tmp_path / "6_verification"),
        ),
        save_dir=str(tmp_path),
    )

    assert refiner.run.called is True
    assert result.manifest == {"elements": [{"id": "refined"}]}
    assert result.png_path == str(refined_image_path)


def test_workflow_refiner_skips_after_blocking_verification_error(
    tmp_path,
    monkeypatch,
):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import (
        _GenerationArtifacts,
        _VerificationPhaseResult,
        Text2DiagramWorkflow,
    )
    from evo_diagram.canvas_environment import RenderResult

    manifest_path = tmp_path / "4_render" / "diagram_manifest.json"
    image_path = tmp_path / "4_render" / "diagram_manifest.png"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text('{"elements": [{"id": "base"}]}', encoding="utf-8")
    image_path.write_bytes(b"base-png")

    refiner = MagicMock()
    monkeypatch.setattr(workflow_module, "IterativeRefinerWorkflow", lambda: refiner)

    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.mode = "multiagent"
    workflow.enable_refiner = True
    workflow.verification_only = False
    workflow.canvas_library = "excalidraw"
    workflow.refiner_max_iterations = 2

    generation = _GenerationArtifacts(
        structure_instantiation={},
        structure_specification=None,
        styling_instantiation={},
        styling_specification=None,
        layout_instantiation={},
        layout_specification=None,
        diagram_manifest=None,
        artifact_paths={},
    )

    result = workflow._run_refinement_phase(
        render_result=RenderResult(
            manifest={"elements": [{"id": "base"}]},
            manifest_path=str(manifest_path),
            png_path=str(image_path),
        ),
        generation=generation,
        verification=_VerificationPhaseResult(
            state=SimpleNamespace(
                has_errors=True,
                has_blocking_errors=True,
                errors=["objective checks failed"],
                blocking_errors=["objective checks failed"],
            ),
            output_dir=str(tmp_path / "6_verification"),
        ),
        save_dir=str(tmp_path),
    )

    assert refiner.run.called is False
    assert result.manifest is None
    assert result.png_path is None
    assert result.state is None


def test_workflow_keeps_original_render_when_refiner_does_not_converge(
    tmp_path,
    monkeypatch,
):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
    from evo_diagram.canvas_environment import RenderResult

    original_manifest = {
        "type": "excalidraw",
        "version": 2,
        "elements": [{"id": "original"}],
        "appState": {},
        "files": {},
    }
    refined_manifest = {
        "type": "excalidraw",
        "version": 2,
        "elements": [{"id": "refined"}],
        "appState": {},
        "files": {},
    }

    generator = MagicMock()
    generator.run.return_value = _generator_outputs()

    def fake_render_manifest(*, output_dir, **_kwargs):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        manifest_path = out / "diagram_manifest.json"
        png_path = out / "diagram_manifest.png"
        manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
        png_path.write_bytes(b"original-png")
        return RenderResult(
            manifest=original_manifest,
            manifest_path=str(manifest_path),
            png_path=str(png_path),
        )

    verifier = MagicMock()
    verifier_state = MagicMock()
    verifier_report_path = tmp_path / "custom_verifier_report.json"
    verifier_report_path.write_text("{}", encoding="utf-8")
    verifier_state.report_path = str(verifier_report_path)
    verifier_state.objective_findings = []
    verifier.run.return_value = verifier_state

    refiner_dir = tmp_path / "7_refiner"
    refined_manifest_path = refiner_dir / "refined_manifest.json"
    refined_png_path = refiner_dir / "refined_diagram.png"
    refiner_report_path = refiner_dir / "refiner_report.json"
    refiner_dir.mkdir()
    refined_manifest_path.write_text(json.dumps(refined_manifest), encoding="utf-8")
    refined_png_path.write_bytes(b"refined-png")
    refiner_report_path.write_text("{}", encoding="utf-8")

    refiner = MagicMock()
    refiner_state = MagicMock()
    refiner_state.status = "reported"
    refiner_state.current_iteration = 2
    refiner_state.converged = False
    refiner_state.termination_reason = "max_iterations_exhausted"
    refiner_state.refined_manifest_path = str(refined_manifest_path)
    refiner_state.refined_image_path = str(refined_png_path)
    refiner_state.candidate_manifest_path = None
    refiner_state.candidate_image_path = None
    refiner_state.refiner_report_path = str(refiner_report_path)
    refiner_state.errors = []
    refiner_state.latest_findings = [{"severity": "major", "message": "still misaligned"}]
    refiner.run.return_value = refiner_state

    monkeypatch.setattr(
        workflow_module,
        "create_generator",
        lambda *args, **kwargs: generator,
    )
    monkeypatch.setattr(workflow_module, "render_manifest", fake_render_manifest)
    monkeypatch.setattr(workflow_module, "VerifierWorkflow", lambda: verifier)
    monkeypatch.setattr(workflow_module, "IterativeRefinerWorkflow", lambda: refiner)

    workflow = Text2DiagramWorkflow(
        object(),
        enable_refiner=True,
        enable_critic=False,
    )
    state = workflow.run(
        text_content="A flows to B",
        user_query="draw a flowchart",
        save_dir=str(tmp_path),
    )

    assert state.diagram_manifest == original_manifest
    assert state.refined_diagram_manifest is None
    assert state.final_diagram_manifest == original_manifest
    assert json.loads(Path(state.final_manifest_path).read_text(encoding="utf-8")) == original_manifest
    assert Path(state.final_png_path).read_bytes() == b"original-png"
    assert state.refiner_status == "reported"
    assert state.refiner_converged is False
    assert state.refiner_termination_reason == "max_iterations_exhausted"
    assert state.refiner_degraded is False
    assert state.refiner_report_path == str(refiner_report_path)
    assert state.refiner_candidate_manifest_path is None
    assert state.refiner_candidate_png_path is None
    assert state.refiner_latest_findings_summary == [
        {"severity": "major", "message": "still misaligned"},
    ]
    assert refiner.run.call_args.kwargs["verifier_report_path"] == str(verifier_report_path)
    assert state.artifact_paths["verification_report_path"] == str(verifier_report_path)
    assert "refined_manifest_path" not in state.artifact_paths
    assert "refined_png_path" not in state.artifact_paths
    assert "refiner_status" not in state.artifact_paths
    assert "refiner_termination_reason" not in state.artifact_paths


def test_workflow_records_non_converged_candidate_artifacts(tmp_path, monkeypatch):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
    from evo_diagram.canvas_environment import RenderResult

    original_manifest = {
        "type": "excalidraw",
        "version": 2,
        "elements": [{"id": "original"}],
        "appState": {},
        "files": {},
    }
    generator = MagicMock()
    generator.run.return_value = _generator_outputs()

    def fake_render_manifest(*, output_dir, **_kwargs):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        manifest_path = out / "diagram_manifest.json"
        png_path = out / "diagram_manifest.png"
        manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
        png_path.write_bytes(b"original-png")
        return RenderResult(
            manifest=original_manifest,
            manifest_path=str(manifest_path),
            png_path=str(png_path),
        )

    verifier = MagicMock()
    verifier_state = MagicMock()
    verifier_state.status = "reported"
    verifier_state.quality_passed = True
    verifier_state.cli_exit_code = 0
    verifier_state.objective_summary = {}
    verifier_state.errors = []
    verifier_state.report_path = None
    verifier_state.objective_findings = []
    verifier.run.return_value = verifier_state

    candidate_manifest_path = tmp_path / "7_refiner" / "candidate_manifest.json"
    candidate_png_path = tmp_path / "7_refiner" / "candidate_diagram.png"
    candidate_manifest_path.parent.mkdir()
    candidate_manifest_path.write_text('{"elements":[{"id":"candidate"}]}', encoding="utf-8")
    candidate_png_path.write_bytes(b"candidate-png")

    refiner = MagicMock()
    refiner_state = MagicMock()
    refiner_state.status = "reported_degraded"
    refiner_state.current_iteration = 1
    refiner_state.converged = False
    refiner_state.termination_reason = "fixed_point_unresolved"
    refiner_state.refined_manifest_path = None
    refiner_state.refined_image_path = None
    refiner_state.candidate_manifest_path = str(candidate_manifest_path)
    refiner_state.candidate_image_path = str(candidate_png_path)
    refiner_state.refiner_report_path = None
    refiner_state.errors = ["LLM exhausted"]
    refiner_state.latest_findings = []
    refiner.run.return_value = refiner_state

    monkeypatch.setattr(workflow_module, "create_generator", lambda *args, **kwargs: generator)
    monkeypatch.setattr(workflow_module, "render_manifest", fake_render_manifest)
    monkeypatch.setattr(workflow_module, "VerifierWorkflow", lambda: verifier)
    monkeypatch.setattr(workflow_module, "IterativeRefinerWorkflow", lambda: refiner)

    workflow = Text2DiagramWorkflow(
        object(),
        enable_refiner=True,
        enable_critic=False,
    )
    state = workflow.run(
        text_content="A flows to B",
        user_query="draw a flowchart",
        save_dir=str(tmp_path),
    )

    assert state.refined_diagram_manifest is None
    assert state.final_diagram_manifest == original_manifest
    assert state.refiner_status == "reported_degraded"
    assert state.refiner_degraded is True
    assert state.refiner_errors == ["LLM exhausted"]
    assert state.refiner_candidate_manifest_path == str(candidate_manifest_path)
    assert state.refiner_candidate_png_path == str(candidate_png_path)
    assert state.artifact_paths["refiner_candidate_manifest_path"] == str(candidate_manifest_path)
    assert state.artifact_paths["refiner_candidate_png_path"] == str(candidate_png_path)


@pytest.mark.parametrize("initial_counts,candidate_counts,candidate_score,adopt,comparison_winner", [
    ({}, {}, 8.5, True, None),
    ({}, {"critical": 1}, 8.8, False, None),
    ({}, {}, 7.5, False, None),
    ({}, {}, None, False, None),
    ({"major": 1}, {}, 7.5, True, None),
    ({}, {}, 8.5, True, "candidate"),
    ({}, {}, 8.5, False, "original"),
    ({}, {}, 8.5, False, "tie"),
    ({}, {}, 7.5, True, "candidate"),
    ({}, {}, 8.9, False, "original"),
])
def test_workflow_verifies_refinement_before_promoting_artifacts(
    tmp_path, monkeypatch, initial_counts, candidate_counts, candidate_score, adopt, comparison_winner,
):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
    from evo_diagram.canvas_environment import RenderResult

    original_manifest = {
        "type": "excalidraw",
        "version": 2,
        "elements": [{"id": "original"}],
        "appState": {},
        "files": {},
    }
    refined_manifest = {
        "type": "excalidraw",
        "version": 2,
        "elements": [{"id": "refined"}],
        "appState": {},
        "files": {},
    }

    generator = MagicMock()
    generator.run.return_value = _generator_outputs()

    def fake_render_manifest(*, output_dir, **_kwargs):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        manifest_path = out / "diagram_manifest.json"
        png_path = out / "diagram_manifest.png"
        manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
        png_path.write_bytes(b"original-png")
        return RenderResult(
            manifest=original_manifest,
            manifest_path=str(manifest_path),
            png_path=str(png_path),
        )

    pre_report_path = tmp_path / "6_verification" / "verification_report.md"
    final_report_path = tmp_path / "8_final_verification" / "verification_report.md"

    pre_verifier_state = MagicMock()
    pre_verifier_state.status = "reported"
    pre_verifier_state.quality_passed = not bool(initial_counts)
    pre_verifier_state.cli_exit_code = int(bool(initial_counts))
    pre_verifier_state.objective_summary = initial_counts
    pre_verifier_state.critique = SimpleNamespace(overall_score=8.4)
    pre_verifier_state.errors = []
    pre_verifier_state.objective_findings = []
    pre_verifier_state.report_path = str(pre_report_path)

    final_verifier_state = MagicMock()
    final_verifier_state.status = "reported"
    final_verifier_state.quality_passed = not bool(candidate_counts)
    final_verifier_state.cli_exit_code = int(bool(candidate_counts))
    final_verifier_state.objective_summary = candidate_counts
    final_verifier_state.critique = SimpleNamespace(overall_score=candidate_score)
    final_verifier_state.errors = []
    final_verifier_state.objective_findings = ["final artifact issue"]
    final_verifier_state.report_path = str(final_report_path)

    verifier = MagicMock()
    verifier.run.side_effect = [pre_verifier_state, final_verifier_state]

    refiner_dir = tmp_path / "7_refiner"
    refined_manifest_path = refiner_dir / "refined_manifest.json"
    refined_png_path = refiner_dir / "refined_diagram.png"
    refiner_dir.mkdir()
    refined_manifest_path.write_text(json.dumps(refined_manifest), encoding="utf-8")
    refined_png_path.write_bytes(b"refined-png")

    refiner = MagicMock()
    refiner_state = MagicMock()
    refiner_state.status = "reported"
    refiner_state.current_iteration = 1
    refiner_state.converged = True
    refiner_state.termination_reason = "converged"
    refiner_state.refined_manifest_path = str(refined_manifest_path)
    refiner_state.refined_image_path = str(refined_png_path)
    refiner_state.candidate_manifest_path = None
    refiner_state.candidate_image_path = None
    refiner_state.refiner_report_path = None
    refiner_state.errors = []
    refiner_state.latest_findings = []
    refiner.run.return_value = refiner_state

    monkeypatch.setattr(workflow_module, "create_generator", lambda *args, **kwargs: generator)
    monkeypatch.setattr(workflow_module, "render_manifest", fake_render_manifest)
    monkeypatch.setattr(workflow_module, "VerifierWorkflow", lambda: verifier)
    monkeypatch.setattr(workflow_module, "IterativeRefinerWorkflow", lambda: refiner)

    from evo_diagram.agentic_system.verification_stage.critic import comparison
    monkeypatch.setattr(comparison, "compare_rendered_diagrams", lambda *args: {
        "winner": comparison_winner, "reason": "The displayed group margins are more balanced.",
    })
    workflow = Text2DiagramWorkflow(
        object(),
        enable_refiner=True,
        enable_critic=comparison_winner is not None,
    )
    state = workflow.run(
        text_content="A flows to B",
        user_query="draw a flowchart",
        save_dir=str(tmp_path),
    )

    assert verifier.run.call_count == 2
    assert refiner.run.call_args.kwargs["verifier_report_path"] == str(pre_report_path)
    assert verifier.run.call_args_list[1].kwargs["manifest_path"] == str(refined_manifest_path)
    assert verifier.run.call_args_list[1].kwargs["image_path"] == str(refined_png_path)
    assert state.final_diagram_manifest == (refined_manifest if adopt else original_manifest)
    assert Path(state.final_png_path).read_bytes() == (b"refined-png" if adopt else b"original-png")
    assert json.loads(Path(state.final_manifest_path).read_text()) == state.final_diagram_manifest
    selected_verification = final_verifier_state if adopt else pre_verifier_state
    assert state.verification_quality_passed is selected_verification.quality_passed
    assert state.verification_cli_exit_code == selected_verification.cli_exit_code
    assert state.verification_objective_summary == (candidate_counts if adopt else initial_counts)
    selected_report = str(final_report_path if adopt else pre_report_path)
    assert state.verification_report_path == selected_report
    assert state.artifact_paths["pre_refine_verification_report_path"] == str(pre_report_path)
    assert state.artifact_paths["verification_report_path"] == selected_report
    if comparison_winner is not None:
        comparison_path = Path(state.artifact_paths["refiner_comparison_report_path"])
        assert json.loads(comparison_path.read_text())["winner"] == comparison_winner
    if adopt:
        assert state.artifact_paths["final_verification_report_path"] == str(final_report_path)
    else:
        assert state.artifact_paths["refiner_candidate_verification_report_path"] == str(final_report_path)
        assert state.refiner_candidate_manifest_path == str(refined_manifest_path)
        assert state.refiner_candidate_png_path == str(refined_png_path)
        assert Path(refined_png_path).read_bytes() == b"refined-png"


def test_oneshot_verification_receives_semantic_structure_path(tmp_path, monkeypatch):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import (
        _GenerationArtifacts,
        Text2DiagramWorkflow,
    )
    from evo_diagram.canvas_environment import RenderResult

    structure_path = tmp_path / "1_unified" / "structure_instantiation.json"
    layout_path = tmp_path / "3_layout" / "layout_instantiation.json"
    structure_path.parent.mkdir(parents=True)
    layout_path.parent.mkdir(parents=True)
    structure_path.write_text("{}", encoding="utf-8")
    layout_path.write_text("{}", encoding="utf-8")
    png_path = tmp_path / "diagram.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest_path = tmp_path / "diagram_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    verifier = MagicMock()
    verifier_state = MagicMock()
    verifier_state.status = "reported"
    verifier_state.quality_passed = True
    verifier_state.cli_exit_code = 0
    verifier_state.objective_summary = {}
    verifier_state.errors = []
    verifier_state.objective_findings = []
    verifier_state.report_path = None
    verifier.run.return_value = verifier_state
    monkeypatch.setattr(workflow_module, "VerifierWorkflow", lambda: verifier)

    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.mode = "oneshot"
    workflow.enable_verifier = True
    workflow.enable_critic = False
    workflow.canvas_library = "excalidraw"

    generation = _GenerationArtifacts(
        structure_instantiation={},
        structure_specification=None,
        styling_instantiation=None,
        styling_specification=None,
        layout_instantiation=None,
        layout_specification=None,
        diagram_manifest={},
        artifact_paths={
            "structure_instantiation_path": str(structure_path),
            "layout_instantiation_path": str(layout_path),
        },
    )
    render_result = RenderResult(
        manifest={},
        manifest_path=str(manifest_path),
        png_path=str(png_path),
    )

    workflow._run_verification_phase(
        render_result=render_result,
        generation=generation,
        text_content="source",
        save_dir=str(tmp_path),
    )

    assert verifier.run.call_args.kwargs["structure_path"] == str(structure_path)
    assert verifier.run.call_args.kwargs["layout_path"] is None
