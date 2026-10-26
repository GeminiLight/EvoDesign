from __future__ import annotations

import pytest
import json

from evo_diagram.agentic_system.common.spec_utils import (
    build_assistant_content,
    format_specification_for_prompt,
    parse_stage_output,
    unwrap_structure_instantiation,
)


def test_stage_history_keeps_the_same_json_contract_as_the_next_model_response():
    specification = {"intent": "Preserve α → β", "facts": [1, 2]}
    instantiation = {"node": {"label": "Line one\nLine two"}}
    history = build_assistant_content("Structure", specification, instantiation)
    parsed = parse_stage_output(json.loads(history), stage_name="Structure")
    assert parsed.specification == specification
    assert parsed.instantiation == instantiation


def test_parse_stage_output_rejects_unwrapped_legacy_instantiation():
    with pytest.raises(ValueError, match="Styling output missing top-level key"):
        parse_stage_output(
            {"n1": {"type": "rectangle"}},
            stage_name="Styling",
            require_instantiation_dict=True,
        )


def test_parse_stage_output_unwraps_specification_and_flat_instantiation():
    parsed = parse_stage_output(
        {
            "specification": {"visual": {"anchor": "boxes"}},
            "instantiation": {"n1": {"type": "rectangle"}},
        },
        stage_name="Styling",
        require_instantiation_dict=True,
    )

    assert parsed.specification == {"visual": {"anchor": "boxes"}}
    assert parsed.instantiation == {"n1": {"type": "rectangle"}}


def test_format_specification_renders_nested_dicts_uniformly():
    rendered = format_specification_for_prompt(
        "Layout Design Specification",
        {"canvas_use_plan": {"name": "balanced", "description": "Two columns"}},
    )

    assert "- [canvas_use_plan]:" in rendered
    assert "    name: balanced" in rendered
    assert "    description: Two columns" in rendered


def test_parse_stage_output_rejects_categorized_instantiation_when_flat_map_required():
    categorized = {
        "nodes": {"n1": {"type": "rectangle"}},
        "edges": {"edge:n12n2": {"strokeColor": "#111111"}},
        "metadata": {"palette": "slate"},
    }

    with pytest.raises(ValueError, match="flat id-keyed map"):
        parse_stage_output(
            {
                "specification": {"visual": {"anchor": "boxes"}},
                "instantiation": categorized,
            },
            stage_name="Styling",
            require_instantiation_dict=True,
            require_flat_id_map=True,
        )


def test_parse_stage_output_accepts_structure_graph_instantiation():
    parsed = parse_stage_output(
        {
            "specification": {"diagram_paradigm": {"type_budget": "flowchart"}},
            "instantiation": {
                "chart_type": "flowchart",
                "nodes": [{"id": "n1", "label": "Start", "class": "process"}],
                "edges": [],
                "groups": [],
            },
        },
        stage_name="StructureAgent",
        require_instantiation_dict=True,
    )

    assert parsed.specification == {"diagram_paradigm": {"type_budget": "flowchart"}}
    assert parsed.instantiation["nodes"][0]["id"] == "n1"


def test_parse_stage_output_rejects_non_dict_instantiation_when_required():
    with pytest.raises(ValueError, match="Layout output is not a valid dict: list"):
        parse_stage_output(
            {"specification": {}, "instantiation": []},
            stage_name="Layout",
            require_instantiation_dict=True,
        )


def test_parse_stage_output_rejects_error_key_when_requested():
    with pytest.raises(ValueError, match="Styling output missing top-level key"):
        parse_stage_output(
            {"error": "model refused"},
            stage_name="Styling",
            require_instantiation_dict=True,
            reject_error_key=True,
        )


def test_parse_stage_output_rejects_wrapped_error_payload_when_requested():
    with pytest.raises(ValueError, match="Styling output is not a valid dict: dict"):
        parse_stage_output(
            {"specification": {}, "instantiation": {"error": "model refused"}},
            stage_name="Styling",
            require_instantiation_dict=True,
            reject_error_key=True,
        )


def test_parse_stage_output_rejects_non_dict_specification():
    with pytest.raises(ValueError, match="Layout specification must be a JSON object"):
        parse_stage_output(
            {"specification": None, "instantiation": {}},
            stage_name="Layout",
            require_instantiation_dict=True,
        )


def test_unwrap_structure_instantiation_accepts_flat_structure():
    structure = {"nodes": [{"id": "n1"}], "edges": []}

    assert unwrap_structure_instantiation(structure) is structure


def test_unwrap_structure_instantiation_accepts_persisted_wrapper():
    structure = {"nodes": [{"id": "n1"}], "edges": []}

    assert unwrap_structure_instantiation(
        {"structure_instantiation": {"instantiation": structure}}
    ) is structure


def test_unwrap_structure_instantiation_rejects_non_mapping():
    assert unwrap_structure_instantiation(None) == {}
    assert unwrap_structure_instantiation(["not", "a", "structure"]) == {}
