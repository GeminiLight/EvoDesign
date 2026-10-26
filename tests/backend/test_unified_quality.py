import json
from types import SimpleNamespace

import pytest

from app.services.workflow_runtime.refiner import _should_run_refiner
from app.services.workflow_runtime.quality import quality_regressed
from evo_diagram.agentic_system.quality_policy import quality_status, quality_summary
from evo_diagram.agentic_system.workflow import _refinement_regression_reason
from evo_diagram.agentic_system.verification_stage.critic.critic_agent import _coerce_critique
from evo_diagram.agentic_system.common.design_constraints import build_design_constraints


def state(score, **counts):
    return SimpleNamespace(objective_summary=counts,
                           critique=SimpleNamespace(overall_score=score, constraint_violations=[]))


@pytest.mark.parametrize("before,after,reject", [
    (state(9, minor=1), state(6), True),
    (state(8, major=1), state(8), False),
    (state(8), state(7.5), False),
    (state(8), state(7.49), True),
    (state(8), state(None), True),
    (state(8), state(9, major=1), True),
])
def test_web_and_core_make_identical_adoption_decisions(before, after, reject):
    assert quality_regressed(quality_summary(before), quality_summary(after)) is reject
    assert bool(_refinement_regression_reason(before, after)) is reject


def test_a_clean_draft_does_not_trigger_another_model_call():
    assert not _should_run_refiner(workflow=SimpleNamespace(always_refine=False),
        verifier_state=state(9), severity_cls=None, canvas_library="excalidraw")


def test_low_score_no_op_is_not_reported_as_resolved():
    from evo_diagram.agentic_system.iterative_workflow import _mark_convergence
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState, IterationLog
    candidate = VerifierRefinerState(manifest_path="unused", image_path="unused",
        initial_report={"subjective": {"overall_score": 6}})
    _mark_convergence(candidate, log=IterationLog(iteration=1, findings_before={}),
        findings_after_iter=[], edits_applied=False, iteration=1)
    assert not candidate.converged
    assert quality_status(quality_summary(state(6))) == "needs_attention"
    assert quality_status(quality_summary(state(None))) == "unverified"


def test_constraint_violations_survive_parsing_and_block_adoption():
    critique = _coerce_critique({"overall_score": 9,
        "constraint_violations": ["Publish has an icon although the user explicitly excluded it"]}, None)
    candidate = state(9)
    candidate.critique = critique
    assert _refinement_regression_reason(state(8), candidate)
    assert quality_status(quality_summary(candidate)) == "needs_attention"


def test_refinement_receives_authoritative_partial_icon_coverage_and_dna():
    from evo_diagram.agentic_system.refinement_stage.agent.prompts import build_refiner_user_prompt
    constraints = build_design_constraints(source_text="Keep both feedback loops",
        requirements="No icon on Publish", design_expertise="Use blue and violet",
        use_icons=True, locked_nodes=["n1"])
    prompt = build_refiner_user_prompt("flowchart", [], None, [], design_constraints=constraints)
    for expected in ["Keep both feedback loops", "No icon on Publish", "Use blue and violet", "n1", "Partial coverage"]:
        assert expected in prompt


def test_locked_node_and_bound_text_reject_a_conflicting_edit_batch(monkeypatch):
    from evo_diagram.agentic_system import iterative_workflow as iw
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState, IterationLog, EditOp
    manifest = {"elements": [{"id": "node", "type": "rectangle", "x": 10, "y": 20,
                               "width": 100, "height": 50}], "_meta": {"id_map": {"n1": "node"}}}
    candidate = VerifierRefinerState(manifest_path="unused", image_path="unused", manifest=manifest,
        initial_report={"design_constraints": build_design_constraints(locked_nodes=["n1"])})
    monkeypatch.setattr(iw, "_repair_derived_geometry", lambda *a, **k: None)
    results = iw._apply_edit_batch(candidate,
        [EditOp(op="set_position", id="node", payload={"x": 200, "y": 20})],
        log=IterationLog(iteration=1), target_attr="llm_edits", log_prefix="test")
    assert candidate.manifest["elements"][0]["x"] == 10
    assert results and not results[0].applied


def test_explicit_diagram_type_skips_router_and_keeps_validation():
    from evo_diagram.agentic_system.generation_stage.workflow import PipelineGeneratorWorkflow
    generator = object.__new__(PipelineGeneratorWorkflow)
    generator._router = SimpleNamespace(run=lambda *a: pytest.fail("Known type must not call Router"))
    diagram_type, _ = generator.resolve_generation_context("A to B", "flow", "flow")
    assert diagram_type == "flowchart"
    with pytest.raises(ValueError):
        generator.resolve_generation_context("A to B", "", "unsupported-type")


def test_prepared_geometry_repair_preserves_locked_elements_without_proposals(monkeypatch):
    from evo_diagram.agentic_system import iterative_workflow as iw
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState, IterationLog
    candidate = VerifierRefinerState(manifest_path="unused", image_path="unused",
        manifest={"elements": [{"id": "n", "type": "rectangle", "x": 10}]},
        design_constraints=build_design_constraints(locked_nodes=["n"]))
    def repair(state, **kwargs):
        state.manifest["elements"][0]["x"] = 90
    monkeypatch.setattr(iw, "_repair_derived_geometry", repair)
    iw._apply_edit_batch(candidate, [], log=IterationLog(iteration=1),
                        target_attr="deterministic_edits", log_prefix="test")
    assert candidate.manifest["elements"][0]["x"] == 10


def test_learning_requires_verified_gain_and_accepts_corrected_user_constraints():
    from evo_diagram.agentic_system.quality_policy import verified_learning_gain
    before = {"score": 9, "findings": {}, "constraint_violations": ["wrong colors"]}
    after = {"score": 9, "findings": {}, "constraint_violations": []}
    assert verified_learning_gain(before, after)
    assert not verified_learning_gain(after, after)
    assert not verified_learning_gain(after, before)


def test_incomplete_objective_checks_cannot_be_marked_passed_or_learned():
    from evo_diagram.agentic_system.quality_policy import verified_learning_gain
    broken = state(9)
    broken.has_blocking_errors = True
    summary = quality_summary(broken)
    assert quality_status(summary) == "unverified"
    assert not verified_learning_gain(summary, quality_summary(state(10)))
    assert not verified_learning_gain(quality_summary(state(8)), summary)
