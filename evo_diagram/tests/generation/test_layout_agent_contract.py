from __future__ import annotations

import pytest
import json

from evo_diagram.agentic_system.common.layout_contract import (
    LayoutValidationError,
    validate_layout_instantiation,
)
from evo_diagram.core.base_agent import BaseAgent
from evo_diagram.agentic_system.generation_stage.layout.layout_agent import LayoutAgent
from evo_diagram.agentic_system.generation_stage.layout.viewport_profile import (
    choose_layout_viewport,
)


def _structure():
    return {
        "chart_type": "flowchart",
        "nodes": [
            {"id": "n_start", "label": "Start", "class": "process"},
            {"id": "n_done", "label": "Done", "class": "process"},
        ],
        "edges": [
            {"id": "edge:n_start2n_done", "source": "n_start", "target": "n_done"},
        ],
        "groups": [],
    }


def _structure_with_group():
    structure = _structure()
    structure["groups"] = [{"id": "g_lane", "label": "Lane", "members": ["n_start", "n_done"]}]
    return structure


def _styling():
    return {
        "n_start": {"type": "rectangle", "label": {"text": "Start"}, "strokeColor": "#111111"},
        "n_done": {"type": "rectangle", "label": {"text": "Done"}, "strokeColor": "#111111"},
        "edge:n_start2n_done": {"strokeColor": "#111111"},
    }


def _styling_with_group_shell():
    styling = _styling()
    styling.update({
        "g_lane": {"type": "rectangle", "label": {"text": "Lane"}, "strokeColor": "#111111"},
        "g_lane:background": {"type": "rectangle", "strokeColor": "#111111"},
        "g_lane:title": {"type": "text", "label": {"text": "Lane"}, "strokeColor": "#111111"},
    })
    return styling


def _valid_layout():
    return {
        "n_start": {"x": 0, "y": 0, "w": 120, "h": 60},
        "n_done": {"x": 220, "y": 0, "w": 120, "h": 60},
        "edge:n_start2n_done": {
            "start": {"elementId": "n_start", "side": "right"},
            "end": {"elementId": "n_done", "side": "left"},
        },
    }


def _valid_layout_with_group_shell():
    layout = _valid_layout()
    layout.update({
        "g_lane:background": {"x": -20, "y": -30, "w": 400, "h": 140},
        "g_lane:title": {"x": 0, "y": -20, "w": 120, "h": 24},
    })
    return layout


def test_layout_agent_constructor_pops_base_agent_kwargs(monkeypatch):
    captured = {}

    def fake_base_init(self, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(BaseAgent, "__init__", fake_base_init)

    LayoutAgent(
        model=object(),
        exclude_think=True,
        json_retry_attempts=2,
        response_format={"type": "json_object"},
    )

    assert captured["exclude_think"] is True
    assert captured["json_retry_attempts"] == 2
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["strict_json_output"] is True


def test_layout_agent_prompt_includes_estimated_size_hints():
    from evo_diagram.agentic_system.generation_stage.layout.state import WorkflowState

    agent = object.__new__(LayoutAgent)
    agent._system_prompt = "system"
    captured = {}

    def fake_invoke(messages):
        captured["messages"] = messages
        return {
            "specification": {"canvas_use_plan": "left to right"},
            "instantiation": _valid_layout(),
        }

    agent.invoke_with_history = fake_invoke

    state = WorkflowState(
        text_content="Start then done",
        user_query="flowchart",
        structure_instantiation=_structure(),
        styling_instantiation={
            "n_start": {
                "type": "rectangle",
                "label": {"text": "Start"},
                "strokeColor": "#111111",
                "min_width": 96,
                "min_height": 24,
            },
            "n_done": {
                "type": "rectangle",
                "label": {"text": "Done"},
                "strokeColor": "#111111",
                "min_width": 72,
                "min_height": 24,
            },
            "edge:n_start2n_done": {"strokeColor": "#111111"},
        },
    )

    agent.run(state)

    prompt = captured["messages"][-2]["content"]
    # Both canonical and discrete-cell prompts retain the measured payload;
    # its section heading is presentation, not the geometry contract.
    assert '"n_start": {"min_height": 24, "min_width": 96}' in prompt
    assert '"edge:n_start2n_done"' not in prompt
    assert "Program-selected profile: compact" in prompt
    assert "Preferred logical viewport: 1200 x 800" in prompt
    assistant_content = state.conversation_history[-1]["content"]
    assert isinstance(json.loads(assistant_content)["specification"], dict)
    assert isinstance(json.loads(assistant_content)["instantiation"], dict)


def test_layout_retains_complete_canonical_inputs_without_prior_task_prompts():
    from evo_diagram.agentic_system.generation_stage.layout.state import WorkflowState
    agent = object.__new__(LayoutAgent)
    agent._system_prompt = "system"
    captured = []
    def invoke(messages):
        captured.extend(messages)
        return {"specification": {}, "instantiation": _valid_layout()}
    agent.invoke_with_history = invoke
    styling = _styling()
    styling["n_start:icon"] = {"type": "icon", "props": {"icon": "label"}}
    state = WorkflowState(structure_instantiation=_structure(), styling_instantiation=styling,
        structure_specification={"facts": ["Do not remove return edges"]},
        styling_specification={"palette": "custom blue"}, user_query="Keep all arrows",
        conversation_history=[{"role": "user", "content": "OBSOLETE_STRUCTURE_TASK"}])
    agent.run(state)
    assert json.loads(captured[2]["content"]) == {"specification": state.structure_specification,
                                                "instantiation": _structure()}
    assert json.loads(captured[4]["content"]) == {"specification": state.styling_specification,
                                                "instantiation": styling}
    assert "Keep all arrows" in captured[-1]["content"]
    assert "OBSOLETE_STRUCTURE_TASK" not in str(captured)


def test_layout_viewport_profile_scales_with_semantic_load():
    compact = choose_layout_viewport(_structure())
    assert (compact.profile, compact.width, compact.height) == (
        "compact",
        1200,
        800,
    )

    dense_concept_map = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": f"n_{index}", "label": f"Concept {index}"}
            for index in range(22)
        ],
        "edges": [
            {
                "id": f"edge:{index}",
                "source": "n_0",
                "target": f"n_{index + 1}",
                "label": "relates to",
            }
            for index in range(21)
        ],
        "groups": [],
    }

    large = choose_layout_viewport(dense_concept_map)
    assert (large.profile, large.width, large.height) == (
        "large",
        2400,
        1600,
    )


def test_layout_agent_rejects_categorized_instantiation_without_flattening():
    from evo_diagram.agentic_system.generation_stage.layout.state import WorkflowState

    agent = object.__new__(LayoutAgent)
    agent._system_prompt = "system"
    agent.invoke_with_history = lambda messages: {
        "specification": {"canvas_use_plan": "left to right"},
        "instantiation": {
            "nodes": {
                "n_start": {"x": 0, "y": 0, "w": 120, "h": 60},
                "n_done": {"x": 220, "y": 0, "w": 120, "h": 60},
            },
            "edges": {
                "edge:n_start2n_done": {
                    "start": {"elementId": "n_start", "side": "right"},
                    "end": {"elementId": "n_done", "side": "left"},
                },
            },
        },
    }
    state = WorkflowState(
        text_content="Start then done",
        user_query="flowchart",
        structure_instantiation=_structure(),
        styling_instantiation=_styling(),
    )

    with pytest.raises(ValueError, match="flat id-keyed map"):
        agent.run(state)


def test_layout_merge_rejects_non_object_layout_output():
    agent = object.__new__(LayoutAgent)

    with pytest.raises(ValueError, match="layout instantiation to be a JSON object"):
        agent._merge_layout_with_styling(
            ["not", "an", "object"],
            {"n1": {"fill": "#fff"}},
        )


def test_layout_merge_preserves_styling_and_applies_geometry():
    agent = object.__new__(LayoutAgent)

    merged = agent._merge_layout_with_styling(
        {"n1": {"x": 10, "y": 20, "w": 120, "h": 80, "text": "ignored"}},
        {"n1": {"fill": "#fff", "text": "Keep me"}},
        canvas_library="excalidraw",
    )

    assert merged["n1"] == {
        "fill": "#fff",
        "text": "Keep me",
        "x": 10,
        "y": 20,
        "w": 120,
        "h": 80,
    }


def test_layout_merge_strips_transient_size_hints_from_output():
    agent = object.__new__(LayoutAgent)

    merged = agent._merge_layout_with_styling(
        {"n1": {"x": 10, "y": 20, "w": 120, "h": 80}},
        {
            "n1": {
                "fill": "#fff",
                "min_width": 96,
                "min_height": 24,
                "width": 999,
                "height": 999,
            }
        },
        canvas_library="excalidraw",
    )

    assert merged["n1"] == {
        "fill": "#fff",
        "x": 10,
        "y": 20,
        "w": 120,
        "h": 80,
    }


def test_layout_merge_ignores_unowned_node_fields():
    agent = object.__new__(LayoutAgent)

    merged = agent._merge_layout_with_styling(
        {
            "n1": {
                "x": 10,
                "y": 20,
                "w": 120,
                "h": 80,
                "boundElements": [{"id": "edge-1", "type": "arrow"}],
                "containerId": "frame-1",
                "customData": {"renderer": "override"},
                "strokeColor": "#f00",
            }
        },
        {"n1": {"fill": "#fff"}},
        canvas_library="excalidraw",
    )

    assert merged["n1"] == {
        "fill": "#fff",
        "x": 10,
        "y": 20,
        "w": 120,
        "h": 80,
    }


def test_tldraw_layout_merge_does_not_overwrite_styling_props():
    agent = object.__new__(LayoutAgent)

    merged = agent._merge_layout_with_styling(
        {
            "n1": {
                "x": 10,
                "y": 20,
                "w": 120,
                "h": 80,
                "props": {
                    "w": 130,
                    "h": 90,
                    "color": "red",
                    "fill": "solid",
                    "text": "Layout must not win",
                },
            },
        },
        {
            "n1": {
                "type": "geo",
                "props": {
                    "color": "black",
                    "fill": "none",
                    "text": "Styling wins",
                },
            }
        },
        canvas_library="tldraw",
    )

    assert merged["n1"]["x"] == 10
    assert merged["n1"]["y"] == 20
    assert merged["n1"]["props"] == {
        "color": "black",
        "fill": "none",
        "text": "Styling wins",
        "w": 130,
        "h": 90,
    }


@pytest.mark.parametrize(
    ("unknown_id", "payload"),
    [
        ("n_ghost", {"x": 500, "y": 0, "w": 120, "h": 60}),
        (
            "edge:n_start2n_ghost",
            {
                "start": {"elementId": "n_start", "side": "right"},
                "end": {"elementId": "n_ghost", "side": "left"},
            },
        ),
    ],
)
def test_layout_merge_rejects_unknown_semantic_node_or_edge_id(unknown_id, payload):
    agent = object.__new__(LayoutAgent)
    layout = {**_valid_layout(), unknown_id: payload}

    with pytest.raises(LayoutValidationError, match=f"Unknown layout id.*{unknown_id}"):
        agent._merge_layout_with_styling(
            layout,
            _styling(),
            structure_instantiation=_structure(),
        )


def test_layout_merge_rejects_missing_geometry_entry_for_styled_shape():
    agent = object.__new__(LayoutAgent)
    layout = _valid_layout()
    layout.pop("n_done")

    with pytest.raises(LayoutValidationError, match="Missing layout geometry.*n_done"):
        agent._merge_layout_with_styling(
            layout,
            _styling(),
            structure_instantiation=_structure(),
        )


@pytest.mark.parametrize("missing_field", ["x", "y", "w", "h"])
def test_layout_merge_rejects_partial_geometry_fields(missing_field):
    agent = object.__new__(LayoutAgent)
    layout = _valid_layout()
    layout["n_done"] = dict(layout["n_done"])
    layout["n_done"].pop(missing_field)

    with pytest.raises(LayoutValidationError, match=f"Missing geometry fields.*n_done.*{missing_field}"):
        agent._merge_layout_with_styling(
            layout,
            _styling(),
            structure_instantiation=_structure(),
        )


def test_layout_agent_rejects_edge_endpoint_mismatch_with_structure():
    agent = object.__new__(LayoutAgent)
    layout = _valid_layout()
    layout["edge:n_start2n_done"] = {
        "start": {"elementId": "n_done", "side": "left"},
        "end": {"elementId": "n_start", "side": "right"},
    }

    with pytest.raises(
        LayoutValidationError,
        match="Edge endpoint mismatch.*edge:n_start2n_done.*n_start.*n_done",
    ):
        agent._merge_layout_with_styling(
            layout,
            _styling(),
            structure_instantiation=_structure(),
        )


def test_layout_contract_unwraps_stage_structure_wrapper():
    structure = {"structure_instantiation": {"instantiation": _structure()}}

    assert validate_layout_instantiation(
        _valid_layout(),
        structure_instantiation=structure,
        styling_instantiation=_styling(),
    ) == _valid_layout()


def test_layout_contract_empty_styling_still_rejects_unknown_layout_ids():
    layout = {**_valid_layout(), "n_ghost": {"x": 0, "y": 0, "w": 80, "h": 40}}

    with pytest.raises(LayoutValidationError, match="Unknown layout id.*n_ghost"):
        validate_layout_instantiation(
            layout,
            structure_instantiation=_structure(),
            styling_instantiation={},
            require_complete_styling_geometry=False,
        )


@pytest.mark.parametrize(
    ("port_key", "bad_side"),
    [("start", "middle"), ("end", "center")],
)
def test_layout_contract_rejects_invalid_edge_sides(port_key, bad_side):
    layout = _valid_layout()
    layout["edge:n_start2n_done"] = {
        "start": {"elementId": "n_start", "side": "right"},
        "end": {"elementId": "n_done", "side": "left"},
    }
    layout["edge:n_start2n_done"][port_key]["side"] = bad_side

    with pytest.raises(LayoutValidationError, match=f"{port_key}\\.side.*{bad_side}"):
        validate_layout_instantiation(
            layout,
            structure_instantiation=_structure(),
            styling_instantiation=_styling(),
        )


def test_layout_contract_rejects_llm_waypoints():
    layout = _valid_layout()
    layout["edge:n_start2n_done"] = {
        **layout["edge:n_start2n_done"],
        "waypoints": [{"x": 100, "y": 200}],
    }

    with pytest.raises(LayoutValidationError, match="must not include waypoints"):
        validate_layout_instantiation(
            layout,
            structure_instantiation=_structure(),
            styling_instantiation=_styling(),
        )


def test_layout_contract_rejects_underscore_icon_key_even_when_styled():
    layout = {
        **_valid_layout(),
        "n_start_icon": {"x": 12, "y": 12, "w": 48, "h": 48},
    }
    styling = {
        **_styling(),
        "n_start_icon": {"type": "icon", "props": {"icon": "label"}},
    }

    with pytest.raises(LayoutValidationError, match="Unsupported underscore icon layout id 'n_start_icon'"):
        validate_layout_instantiation(
            layout,
            structure_instantiation=_structure(),
            styling_instantiation=styling,
        )


def test_layout_contract_allows_canonical_icon_and_rejects_underscore_icon():
    canonical_layout = {
        **_valid_layout(),
        "n_start:icon": {"type": "icon", "props": {"icon": "label"}},
    }

    assert validate_layout_instantiation(
        canonical_layout,
        structure_instantiation=_structure(),
        require_complete_styling_geometry=False,
    ) is canonical_layout

    underscore_icon_layout = {
        **_valid_layout(),
        "n_start_icon": {"type": "icon", "props": {"icon": "label"}},
    }
    with pytest.raises(LayoutValidationError, match="Unsupported underscore icon layout id 'n_start_icon'"):
        validate_layout_instantiation(
            underscore_icon_layout,
            structure_instantiation=_structure(),
            require_complete_styling_geometry=False,
        )


def test_layout_merge_allows_group_shell_when_background_carries_geometry():
    agent = object.__new__(LayoutAgent)

    merged = agent._merge_layout_with_styling(
        _valid_layout_with_group_shell(),
        _styling_with_group_shell(),
        structure_instantiation=_structure_with_group(),
    )

    assert "x" not in merged["g_lane"]
    assert merged["g_lane:background"]["x"] == -20


@pytest.mark.parametrize('has_background', [False, True])
def test_layout_resolves_exact_logical_group_alias_without_inventing_geometry(has_background):
    styling = _styling_with_group_shell()
    del styling['g_lane']
    layout = _valid_layout_with_group_shell()
    layout['g_lane'] = layout['g_lane:background'].copy()
    if not has_background:
        del layout['g_lane:background']
    merged = object.__new__(LayoutAgent)._merge_layout_with_styling(
        layout, styling, structure_instantiation=_structure_with_group())
    assert 'g_lane' not in merged
    assert merged['g_lane:background']['x'] == -20
    assert 'g_lane' in layout
    layout['g_unknown'] = layout['g_lane'].copy()
    with pytest.raises(LayoutValidationError, match='Unknown layout id'):
        object.__new__(LayoutAgent)._merge_layout_with_styling(
            layout, styling, structure_instantiation=_structure_with_group())


def _structure_with_edge_label(label: str = "<18"):
    structure = _structure()
    structure["edges"][0]["label"] = label
    return structure


# ---------------------------------------------------------------------------
# Unknown-id checking with an empty allowed set
# ---------------------------------------------------------------------------


def test_layout_contract_rejects_all_ids_when_upstream_has_no_ids():
    """An empty allowed-id set means *every* layout id is unknown.

    ``_validate_known_id`` used to short-circuit on a falsy set, so a Structure
    stage that emitted no nodes let Layout invent arbitrary ids and geometry
    with zero errors anywhere in the chain.
    """
    empty_structure = {"chart_type": "flowchart", "nodes": [], "edges": [], "groups": []}

    with pytest.raises(LayoutValidationError, match="Unknown layout id 'n_ghost'"):
        validate_layout_instantiation(
            {"n_ghost": {"x": 0, "y": 0, "w": 80, "h": 40}},
            structure_instantiation=empty_structure,
            styling_instantiation={},
            require_complete_styling_geometry=False,
        )


def test_layout_contract_rejects_icon_ids_when_upstream_has_no_ids():
    empty_structure = {"chart_type": "flowchart", "nodes": [], "edges": [], "groups": []}

    with pytest.raises(LayoutValidationError, match="Unknown layout id 'n_ghost:icon'"):
        validate_layout_instantiation(
            {"n_ghost:icon": {"type": "icon", "props": {"icon": "label"}}},
            structure_instantiation=empty_structure,
            styling_instantiation={},
            require_complete_styling_geometry=False,
        )


def test_layout_contract_still_accepts_known_ids_from_non_empty_structure():
    assert validate_layout_instantiation(
        _valid_layout(),
        structure_instantiation=_structure(),
        styling_instantiation=_styling(),
    ) == _valid_layout()


# ---------------------------------------------------------------------------
# Structure edge labels reach the render through the layout entry
# ---------------------------------------------------------------------------


def test_layout_merge_backfills_structure_edge_label_when_layout_omits_it():
    """Structure's edge label must survive when the Layout LLM forgets it.

    The renderer reads edge labels off the layout entry only, and Styling edge
    entries are colour-only by contract, so without this backfill a dropped
    ``label`` silently erases decision-branch conditions such as ``<18``.
    """
    agent = object.__new__(LayoutAgent)

    merged = agent._merge_layout_with_styling(
        _valid_layout(),
        _styling(),
        structure_instantiation=_structure_with_edge_label("<18"),
    )

    assert merged["edge:n_start2n_done"]["label"] == {"text": "<18"}
    # The colour Styling owns must still come through.
    assert merged["edge:n_start2n_done"]["strokeColor"] == "#111111"


def test_layout_merge_keeps_explicit_layout_edge_label():
    agent = object.__new__(LayoutAgent)
    layout = _valid_layout()
    layout["edge:n_start2n_done"]["label"] = {"text": ">=18"}

    merged = agent._merge_layout_with_styling(
        layout,
        _styling(),
        structure_instantiation=_structure_with_edge_label("<18"),
    )

    assert merged["edge:n_start2n_done"]["label"] == {"text": ">=18"}


def test_layout_merge_replaces_blank_layout_edge_label():
    agent = object.__new__(LayoutAgent)
    layout = _valid_layout()
    layout["edge:n_start2n_done"]["label"] = {"text": "   "}

    merged = agent._merge_layout_with_styling(
        layout,
        _styling(),
        structure_instantiation=_structure_with_edge_label("<18"),
    )

    assert merged["edge:n_start2n_done"]["label"] == {"text": "<18"}


def test_layout_merge_does_not_invent_labels_structure_omitted():
    """"Edge labels are forbidden by default" — never synthesize one."""
    agent = object.__new__(LayoutAgent)

    merged = agent._merge_layout_with_styling(
        _valid_layout(),
        _styling(),
        structure_instantiation=_structure(),
    )

    assert "label" not in merged["edge:n_start2n_done"]


def test_layout_merge_backfills_edge_label_on_tldraw_canvas():
    agent = object.__new__(LayoutAgent)
    styling = {
        "n_start": {"type": "geo", "props": {"geo": "rectangle", "color": "blue"}},
        "n_done": {"type": "geo", "props": {"geo": "rectangle", "color": "blue"}},
        "edge:n_start2n_done": {"props": {"color": "blue"}},
    }

    merged = agent._merge_layout_with_styling(
        _valid_layout(),
        styling,
        canvas_library="tldraw",
        structure_instantiation=_structure_with_edge_label("approves"),
    )

    assert merged["edge:n_start2n_done"]["label"] == {"text": "approves"}


def test_layout_merge_backfills_edge_label_through_structure_wrapper():
    agent = object.__new__(LayoutAgent)
    wrapped = {"structure_instantiation": {"instantiation": _structure_with_edge_label("<18")}}

    merged = agent._merge_layout_with_styling(
        _valid_layout(),
        _styling(),
        structure_instantiation=wrapped,
    )

    assert merged["edge:n_start2n_done"]["label"] == {"text": "<18"}
