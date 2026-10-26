"""Regression tests for generation-stage artifact contracts."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from evo_diagram.agentic_system.generation_stage.workflow import (
    OneShotGeneratorWorkflow,
    PipelineGeneratorWorkflow,
    _save_stage_output,
    create_generator,
)
from evo_diagram.agentic_system.generation_stage.layout.prompts import LAYOUT_TASK_PROMPT
from evo_diagram.agentic_system.generation_stage.styling.prompts import build_styling_task_prompt
from evo_diagram.agentic_system.generation_stage.styling.prompts import STYLING_TASK_PROMPT
from evo_diagram.agentic_system.generation_stage.structure.prompts import STRUCTURE_TASK_PROMPT
from evo_diagram.agentic_system.workflow import (
    GenerationContractError,
    Text2DiagramWorkflow,
    _coerce_generation_artifacts,
)


def _valid_generation_outputs():
    return {
        "structure_instantiation": {
            "chart_type": "flowchart",
            "nodes": [
                {"id": "n_start", "label": "Start", "class": "process"},
                {"id": "n_done", "label": "Done", "class": "process"},
            ],
            "edges": [
                {
                    "id": "edge:n_start2n_done",
                    "source": "n_start",
                    "target": "n_done",
                },
            ],
            "groups": [],
        },
        "structure_specification": {"chart_type": "flowchart"},
        "styling_instantiation": {
            "n_start": {
                "shape": "rectangle",
                "label": {"text": "Start"},
                "strokeColor": "#111111",
                "backgroundColor": "#ffffff",
            },
            "n_done": {
                "shape": "rectangle",
                "label": {"text": "Done"},
                "strokeColor": "#111111",
                "backgroundColor": "#ffffff",
            },
            "edge:n_start2n_done": {"strokeColor": "#111111"},
        },
        "styling_specification": {"palette": "neutral"},
        "layout_instantiation": {
            "n_start": {"x": 0, "y": 0, "w": 120, "h": 60},
            "n_done": {"x": 220, "y": 0, "w": 120, "h": 60},
            "edge:n_start2n_done": {
                "start": {"elementId": "n_start", "side": "right"},
                "end": {"elementId": "n_done", "side": "left"},
            },
        },
        "layout_specification": {"bounds": "ok"},
        "artifact_paths": {},
    }


def test_save_stage_output_writes_canonical_instantiation_and_specification(tmp_path):
    paths = _save_stage_output(
        str(tmp_path),
        "1_structure",
        "structure",
        {"nodes": [{"id": "n1"}]},
        {"chart_type": "flowchart"},
    )

    inst_path = tmp_path / "1_structure" / "structure_instantiation.json"
    spec_path = tmp_path / "1_structure" / "structure_specification.json"

    assert paths == {
        "structure_instantiation_path": str(inst_path),
        "structure_specification_path": str(spec_path),
    }
    assert json.loads(inst_path.read_text(encoding="utf-8")) == {
        "nodes": [{"id": "n1"}],
    }
    assert json.loads(spec_path.read_text(encoding="utf-8")) == {
        "chart_type": "flowchart",
    }


def test_save_stage_output_does_not_embed_specification_inside_instantiation(tmp_path):
    _save_stage_output(
        str(tmp_path),
        "2_styling",
        "styling",
        {"styles": {"n1": {"fill": "#fff"}}},
        {"palette": "neutral"},
    )

    inst_path = tmp_path / "2_styling" / "styling_instantiation.json"
    instantiation = json.loads(inst_path.read_text(encoding="utf-8"))

    assert "specification" not in instantiation


def test_styling_prompt_uses_request_canvas_library_not_global_settings():
    prompt = build_styling_task_prompt(
        palette_key="blush_sage",
        canvas_library="tldraw",
    )

    assert "TLDraw-specific rules" in prompt
    assert '`"type": "geo"` with `props.geo`' in prompt
    assert "Minimum 100x60" not in prompt
    assert "Standard process boxes" not in prompt
    assert "non-empty `props.text`" not in prompt
    assert "non-empty `label.text`" in prompt
    assert "Excalidraw-specific rules" not in prompt


def test_styling_prompt_requires_valid_palette_key():
    with pytest.raises(ValueError, match="Unknown or missing palette_key"):
        build_styling_task_prompt(palette_key="", canvas_library="excalidraw")

    with pytest.raises(ValueError, match="Unknown or missing palette_key"):
        build_styling_task_prompt(palette_key="unknown_palette", canvas_library="excalidraw")


def test_stage_task_prompts_include_runtime_directives_slot():
    prompts = [
        STRUCTURE_TASK_PROMPT,
        STYLING_TASK_PROMPT,
        build_styling_task_prompt(palette_key="blush_sage", canvas_library="excalidraw"),
        LAYOUT_TASK_PROMPT,
    ]

    for prompt in prompts:
        assert "### RUNTIME DIRECTIVES ###" in prompt
        assert "{{runtime_directives}}" in prompt


def test_generation_contract_rejects_missing_pipeline_layout():
    outputs = _valid_generation_outputs()
    outputs.pop("layout_instantiation")

    with pytest.raises(GenerationContractError, match="layout_instantiation"):
        _coerce_generation_artifacts("multiagent", outputs)


def test_generation_contract_requires_oneshot_semantic_sidecar():
    with pytest.raises(GenerationContractError, match="structure_instantiation"):
        _coerce_generation_artifacts(
            "oneshot",
            {
                "diagram_manifest": {
                    "type": "excalidraw/clipboard",
                    "elements": [],
                    "files": {},
                    "appState": {},
                },
            },
        )


def test_generation_contract_rejects_malformed_artifact_paths():
    outputs = _valid_generation_outputs()
    outputs["artifact_paths"] = []
    with pytest.raises(GenerationContractError, match="artifact_paths"):
        _coerce_generation_artifacts("multiagent", outputs)

    outputs = _valid_generation_outputs()
    outputs["artifact_paths"] = {"layout_instantiation_path": 123}
    with pytest.raises(GenerationContractError, match="non-string"):
        _coerce_generation_artifacts("multiagent", outputs)


def test_generation_contract_revalidates_stage_artifacts():
    outputs = _valid_generation_outputs()
    outputs["structure_instantiation"]["edges"][0]["target"] = "n_missing"

    with pytest.raises(GenerationContractError, match="structure_instantiation"):
        _coerce_generation_artifacts("multiagent", outputs)

    outputs = _valid_generation_outputs()
    outputs["styling_instantiation"]["n_ghost"] = {
        "shape": "rectangle",
        "label": {"text": "Ghost"},
        "strokeColor": "#111111",
        "backgroundColor": "#ffffff",
    }

    with pytest.raises(GenerationContractError, match="styling_instantiation"):
        _coerce_generation_artifacts("multiagent", outputs)

    outputs = _valid_generation_outputs()
    outputs["layout_instantiation"]["n_ghost"] = {
        "x": 0,
        "y": 0,
        "w": 120,
        "h": 60,
    }

    with pytest.raises(GenerationContractError, match="layout_instantiation"):
        _coerce_generation_artifacts("multiagent", outputs)


def test_text_workflow_public_design_expertise_api_appends_user_memory():
    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.enable_user_memory = True
    workflow.memory_system = object()
    workflow._retrieve_user_preferences = lambda **_kwargs: "Prefer compact groups."

    assert workflow.build_design_expertise(
        "Use lane layout.",
        diagram_type="flowchart",
        content_area="operations",
    ) == "Use lane layout.\n\nPrefer compact groups."


def test_text_workflow_user_memory_does_not_filter_on_unknown_scope():
    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.enable_user_memory = True

    calls = []

    class FakeMemorySystem:
        def retrieve_preferences(self, **kwargs):
            calls.append(kwargs)
            return [{"content": "Prefer compact groups."}]

        def format_preferences_for_prompt(self, prefs, max_length):
            assert len(prefs) == 3
            assert max_length == 1000
            return "Prefer compact groups."

    workflow.memory_system = FakeMemorySystem()

    assert workflow.build_design_expertise(
        "Use lane layout.",
        diagram_type=None,
        content_area=None,
    ) == "Use lane layout.\n\nPrefer compact groups."
    assert [call["agent_category"] for call in calls] == [
        "Structure",
        "Styling",
        "Layout",
    ]
    assert {call["query"] for call in calls} == {"User diagram preferences"}
    assert all(call["diagram_type"] is None for call in calls)
    assert all(call["content_area"] is None for call in calls)


def _pipeline_workflow_with_fake_stages(canvas_library: str = "tldraw"):
    workflow = PipelineGeneratorWorkflow(MagicMock(), canvas_library=canvas_library)
    workflow.resolve_generation_context = lambda text, query, diagram_type=None: (
        "flowchart",
        "blush_sage",
    )

    seen = {}

    class FakeStructure:
        def run(self, state):
            seen["structure"] = state
            state.structure_instantiation = {"nodes": [{"id": "n1"}]}
            state.structure_specification = {"chart_type": "flowchart"}
            state.conversation_history = [{"role": "assistant", "content": "structure"}]
            return state

    class FakeStyling:
        def run(self, state):
            seen["styling"] = state
            seen["styling_input_history"] = list(state.conversation_history)
            state.styling_instantiation = {"n1": {"fill": "#fff"}}
            state.styling_specification = {"palette": "blush_sage"}
            state.conversation_history = [{"role": "assistant", "content": "styling"}]
            return state

    class FakeLayout:
        def run(self, state):
            seen["layout"] = state
            seen["layout_input_history"] = list(state.conversation_history)
            state.layout_instantiation = {"n1": {"x": 1, "y": 2}}
            state.layout_specification = {"bounds": "ok"}
            return state

    workflow.structure = FakeStructure()
    workflow.styling = FakeStyling()
    workflow.layout = FakeLayout()
    return workflow, seen


def test_pipeline_generator_threads_stage_state_without_real_llm():
    workflow, seen = _pipeline_workflow_with_fake_stages("tldraw")

    outputs = workflow.run(
        text_content="Draw a flow",
        user_query="flowchart",
        design_expertise="use compact spacing",
        runtime_directives="keep node n1 locked",
        content_area="operations",
    )

    assert seen["structure"].canvas_library == "tldraw"
    assert seen["styling"].canvas_library == "tldraw"
    assert seen["layout"].canvas_library == "tldraw"
    assert seen["structure"].content_area == "operations"
    assert seen["styling"].content_area == "operations"
    assert seen["layout"].content_area == "operations"
    assert seen["structure"].diagram_type == "flowchart"
    assert seen["styling"].palette_key == "blush_sage"
    assert seen["styling_input_history"] == [
        {"role": "assistant", "content": "structure"},
    ]
    assert seen["layout_input_history"] == [
        {"role": "assistant", "content": "styling"},
    ]
    assert set(outputs) == {
        "structure_instantiation",
        "structure_specification",
        "styling_instantiation",
        "styling_specification",
        "layout_instantiation",
        "layout_specification",
        "artifact_paths",
    }
    assert outputs["structure_instantiation"] == {"nodes": [{"id": "n1"}]}
    assert outputs["structure_specification"] == {"chart_type": "flowchart"}
    assert outputs["styling_instantiation"] == {"n1": {"fill": "#fff"}}
    assert outputs["styling_specification"] == {"palette": "blush_sage"}
    assert outputs["layout_instantiation"] == {"n1": {"x": 1, "y": 2}}
    assert outputs["layout_specification"] == {"bounds": "ok"}
    assert outputs["artifact_paths"] == {}


def test_pipeline_generator_stage_api_matches_run_output_contract():
    run_workflow, _ = _pipeline_workflow_with_fake_stages()
    run_outputs = run_workflow.run(
        text_content="Draw a flow",
        user_query="flowchart",
        design_expertise="use compact spacing",
        runtime_directives="keep node n1 locked",
    )

    step_workflow, _ = _pipeline_workflow_with_fake_stages()
    run_state = step_workflow.begin_pipeline_run(
        "Draw a flow",
        "flowchart",
        design_expertise="use compact spacing",
        runtime_directives="keep node n1 locked",
    )
    for stage_name in ("structure", "styling", "layout"):
        step_workflow.run_pipeline_stage(run_state, stage_name)

    stage_outputs = step_workflow.pipeline_outputs(run_state)

    assert stage_outputs == run_outputs
    assert stage_outputs["artifact_paths"] == {}
    assert stage_outputs["artifact_paths"] is not run_state.artifact_paths


def test_pipeline_generator_stage_api_rejects_invalid_stage_order():
    workflow, _ = _pipeline_workflow_with_fake_stages()
    run_state = workflow.begin_pipeline_run("Draw a flow", "flowchart")

    with pytest.raises(RuntimeError, match="Structure stage must run before styling"):
        workflow.run_pipeline_stage(run_state, "styling")

    with pytest.raises(RuntimeError, match="Styling stage must run before layout"):
        workflow.run_pipeline_stage(run_state, "layout")

    with pytest.raises(ValueError, match="Unknown pipeline generation stage"):
        workflow.run_pipeline_stage(run_state, "unknown")


def test_pipeline_generator_rejects_failed_stage_even_with_dict_outputs(tmp_path):
    workflow, _ = _pipeline_workflow_with_fake_stages()
    run_state = workflow.begin_pipeline_run("Draw a flow", "flowchart")

    class FailedStructure:
        def run(self, state):
            state.status = "failed"
            state.errors = []
            state.structure_instantiation = {"nodes": [{"id": "n1"}]}
            state.structure_specification = {"chart_type": "flowchart"}
            state.conversation_history = [{"role": "assistant", "content": "structure"}]
            return state

    workflow.structure = FailedStructure()

    with pytest.raises(
        RuntimeError,
        match="Pipeline generation structure stage failed: no error details",
    ):
        workflow.run_pipeline_stage(run_state, "structure", save_dir=str(tmp_path))

    assert run_state.structure_state is None
    assert run_state.structure_instantiation is None
    assert run_state.structure_specification is None
    assert run_state.artifact_paths == {}
    assert not (tmp_path / "1_structure").exists()


def test_pipeline_generator_run_persists_pipeline_artifact_paths(tmp_path):
    workflow, _ = _pipeline_workflow_with_fake_stages()

    outputs = workflow.run(
        text_content="Draw a flow",
        user_query="flowchart",
        save_dir=str(tmp_path),
    )

    expected_paths = {
        "structure_instantiation_path": tmp_path
        / "1_structure"
        / "structure_instantiation.json",
        "structure_specification_path": tmp_path
        / "1_structure"
        / "structure_specification.json",
        "styling_instantiation_path": tmp_path
        / "2_styling"
        / "styling_instantiation.json",
        "styling_specification_path": tmp_path
        / "2_styling"
        / "styling_specification.json",
        "layout_instantiation_path": tmp_path
        / "3_layout"
        / "layout_instantiation.json",
        "layout_specification_path": tmp_path
        / "3_layout"
        / "layout_specification.json",
    }

    assert outputs["artifact_paths"] == {
        key: str(path) for key, path in expected_paths.items()
    }
    assert json.loads(
        expected_paths["structure_instantiation_path"].read_text(encoding="utf-8")
    ) == outputs["structure_instantiation"]
    assert json.loads(
        expected_paths["structure_specification_path"].read_text(encoding="utf-8")
    ) == outputs["structure_specification"]
    assert json.loads(
        expected_paths["styling_instantiation_path"].read_text(encoding="utf-8")
    ) == outputs["styling_instantiation"]
    assert json.loads(
        expected_paths["styling_specification_path"].read_text(encoding="utf-8")
    ) == outputs["styling_specification"]
    assert json.loads(
        expected_paths["layout_instantiation_path"].read_text(encoding="utf-8")
    ) == outputs["layout_instantiation"]
    assert json.loads(
        expected_paths["layout_specification_path"].read_text(encoding="utf-8")
    ) == outputs["layout_specification"]


def test_text_workflow_stepwise_generation_api_delegates_to_generator(tmp_path):
    workflow = Text2DiagramWorkflow.__new__(Text2DiagramWorkflow)
    seen = {}

    class FakeGenerator:
        def begin_pipeline_run(self, *args, **kwargs):
            seen["begin"] = (args, kwargs)
            return {"handle": "run-1"}

        def run_pipeline_stage(self, *args, **kwargs):
            seen["stage"] = (args, kwargs)

    workflow.generator = FakeGenerator()

    run_state = workflow.begin_generation_run(
        "Draw a flow",
        "flowchart",
        design_expertise="compact",
        runtime_directives="lock n1",
        diagram_type="flowchart",
        content_area="ops",
    )
    workflow.run_generation_stage(run_state, "structure", save_dir=str(tmp_path))

    assert run_state == {"handle": "run-1"}
    assert seen["begin"] == (
        ("Draw a flow", "flowchart"),
        {
            "design_expertise": "compact",
            "runtime_directives": "lock n1",
            "diagram_type": "flowchart",
            "content_area": "ops",
        },
    )
    assert seen["stage"] == (
        ({"handle": "run-1"}, "structure"),
        {"save_dir": str(tmp_path)},
    )


def test_text_workflow_stepwise_generation_api_rejects_non_pipeline_generator():
    workflow = Text2DiagramWorkflow.__new__(Text2DiagramWorkflow)
    workflow.generator = object()

    with pytest.raises(RuntimeError, match="pipeline mode only"):
        workflow.begin_generation_run("Draw", "flowchart")


def test_pipeline_generator_uses_structure_chart_type_when_router_is_disabled():
    workflow = PipelineGeneratorWorkflow(MagicMock(), canvas_library="excalidraw")
    workflow.resolve_generation_context = lambda text, query, diagram_type=None: (
        None,
        "blush_sage",
    )

    seen = {}

    class FakeStructure:
        def run(self, state):
            state.structure_instantiation = {
                "chart_type": "timeline",
                "nodes": [{"id": "n1"}],
            }
            state.structure_specification = {"chart_type": "timeline"}
            state.conversation_history = []
            return state

    class FakeStyling:
        def run(self, state):
            seen["styling_diagram_type"] = state.diagram_type
            state.styling_instantiation = {"n1": {"fill": "#fff"}}
            state.styling_specification = {}
            state.conversation_history = []
            return state

    class FakeLayout:
        def run(self, state):
            seen["layout_diagram_type"] = state.diagram_type
            state.layout_instantiation = {"n1": {"x": 0, "y": 0, "w": 100, "h": 60}}
            state.layout_specification = {}
            return state

    workflow.structure = FakeStructure()
    workflow.styling = FakeStyling()
    workflow.layout = FakeLayout()

    workflow.run(text_content="milestones", user_query="make a diagram")

    assert seen == {
        "styling_diagram_type": "timeline",
        "layout_diagram_type": "timeline",
    }


def test_pipeline_generator_rejects_structure_chart_type_mismatch():
    workflow = PipelineGeneratorWorkflow(MagicMock(), canvas_library="excalidraw")
    workflow.resolve_generation_context = lambda text, query, diagram_type=None: (
        "flowchart",
        "blush_sage",
    )

    class FakeStructure:
        def run(self, state):
            state.structure_instantiation = {
                "chart_type": "timeline",
                "nodes": [{"id": "n1"}],
            }
            state.structure_specification = {"chart_type": "timeline"}
            state.conversation_history = []
            return state

    workflow.structure = FakeStructure()

    with pytest.raises(ValueError, match="chart_type conflicts"):
        workflow.run(text_content="milestones", user_query="make a diagram")


def test_pipeline_generator_resolves_diagram_type_aliases_for_downstream_stages():
    assert PipelineGeneratorWorkflow._resolve_downstream_diagram_type(
        "flow",
        {"chart_type": "flowchart"},
    ) == "flowchart"

    assert PipelineGeneratorWorkflow._resolve_downstream_diagram_type(
        None,
        {"chart_type": "state machine"},
    ) == "state_diagram"


def test_create_generator_normalizes_canvas_library_for_direct_callers():
    workflow = create_generator(
        "multiagent",
        MagicMock(),
        canvas_library=" TLDraw ",
    )

    assert workflow.canvas_library == "tldraw"

    with pytest.raises(ValueError, match="Unknown canvas_library"):
        create_generator(
            "multiagent",
            MagicMock(),
            canvas_library="unknown-canvas",
        )


def test_pipeline_generator_uses_explicit_default_palette_when_router_disabled():
    workflow = object.__new__(PipelineGeneratorWorkflow)
    workflow._router = None

    assert workflow.resolve_generation_context(
        text_content="Draw a flow",
        user_query="flowchart",
    ) == (None, "blush_sage")


def test_pipeline_generator_validates_explicit_diagram_type_without_router():
    workflow = object.__new__(PipelineGeneratorWorkflow)
    workflow._router = None

    assert workflow.resolve_generation_context(
        text_content="Draw a flow",
        user_query="flowchart",
        diagram_type="flow",
    ) == ("flowchart", "blush_sage")

    with pytest.raises(ValueError, match="Unsupported diagram_type"):
        workflow.resolve_generation_context(
            text_content="Draw a flow",
            user_query="flowchart",
            diagram_type="unknown",
        )


def test_oneshot_generator_persists_semantic_sidecar(tmp_path):
    from evo_diagram.agentic_system.generation_stage.unified.state import UnifiedWorkflowState

    structure = {
        "chart_type": "flowchart",
        "nodes": [{"id": "n1", "label": "One", "class": "process"}],
        "edges": [],
        "groups": [],
    }
    manifest = {
        "type": "excalidraw/clipboard",
        "elements": [{"id": "shape1", "type": "rectangle"}],
        "files": {},
        "appState": {},
        "_meta": {
            "structure_instantiation": structure,
            "id_map": {"n1": "shape1"},
        },
    }

    class FakeUnified:
        def run(self, state):
            assert isinstance(state, UnifiedWorkflowState)
            state.diagram_manifest = manifest
            state.structure_instantiation = structure
            state.raw_llm_output = "raw"
            return state

    workflow = object.__new__(OneShotGeneratorWorkflow)
    workflow._router = None
    workflow.unified = FakeUnified()

    outputs = workflow.run(
        text_content="One",
        user_query="draw",
        save_dir=str(tmp_path),
    )

    structure_path = tmp_path / "1_unified" / "structure_instantiation.json"
    assert outputs["structure_instantiation"] == structure
    assert json.loads(structure_path.read_text(encoding="utf-8")) == structure
    assert outputs["artifact_paths"]["structure_instantiation_path"] == str(structure_path)


def test_user_memory_retrieval_failure_is_reported_not_silently_empty():
    """A failing memory backend must not look like 'user has no preferences'."""
    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.enable_user_memory = True

    class FailingMemorySystem:
        def retrieve_preferences(self, **_kwargs):
            raise RuntimeError("mem0 search failed")

        def format_preferences_for_prompt(self, prefs, max_length):  # pragma: no cover
            raise AssertionError("formatting must not run after a failed query")

    workflow.memory_system = FailingMemorySystem()

    assert workflow._retrieve_user_preferences(
        diagram_type="flowchart",
        content_area="operations",
    ) is None
    assert workflow.user_memory_degraded is True
    assert any("mem0 search failed" in err for err in workflow.user_memory_errors)
    # Generation still proceeds, but without pretending memory was injected.
    assert workflow.build_design_expertise(
        "Use lane layout.",
        diagram_type="flowchart",
        content_area="operations",
    ) == "Use lane layout."


def test_user_memory_empty_result_is_distinct_from_failure():
    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.enable_user_memory = True

    class EmptyMemorySystem:
        def retrieve_preferences(self, **_kwargs):
            return []

        def format_preferences_for_prompt(self, prefs, max_length):  # pragma: no cover
            raise AssertionError("formatting must not run without preferences")

    workflow.memory_system = EmptyMemorySystem()

    assert workflow._retrieve_user_preferences(
        diagram_type=None,
        content_area=None,
    ) == ""
    assert getattr(workflow, "user_memory_degraded", False) is False


def test_user_memory_partial_category_failure_keeps_other_categories():
    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.enable_user_memory = True

    class PartiallyFailingMemorySystem:
        def retrieve_preferences(self, *, agent_category, **_kwargs):
            if agent_category == "Structure":
                raise RuntimeError("structure index unavailable")
            return [{"content": f"{agent_category} preference"}]

        def format_preferences_for_prompt(self, prefs, max_length):
            return "; ".join(pref["content"] for pref in prefs)

    workflow.memory_system = PartiallyFailingMemorySystem()

    assert workflow._retrieve_user_preferences(
        diagram_type=None,
        content_area=None,
    ) == "Styling preference; Layout preference"
    assert workflow.user_memory_degraded is True
    assert any("Structure" in err for err in workflow.user_memory_errors)
