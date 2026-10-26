from __future__ import annotations

import json

import pytest

from evo_diagram.agentic_system.common import icon_assets
from evo_diagram.agentic_system.generation_stage.styling.icon_colors import (
    ICON_COLOR_NAMES,
    hex_to_icon_color_name,
)
from evo_diagram.agentic_system.generation_stage.styling.schemas import (
    StylingValidationError,
    validate_styling_instantiation,
)
from evo_diagram.agentic_system.generation_stage.styling.state import WorkflowState
from evo_diagram.agentic_system.generation_stage.styling.styling_agent import StylingAgent
from evo_diagram.core.base_agent import BaseAgent


def _structure(edge_id: str = "edge:n_start2n_done") -> dict:
    return {
        "chart_type": "flowchart",
        "nodes": [
            {"id": "n_start", "label": "Start", "class": "process"},
            {"id": "n_done", "label": "Done", "class": "process"},
        ],
        "edges": [
            {"id": edge_id, "source": "n_start", "target": "n_done"},
        ],
        "groups": [
            {"id": "g_lane", "label": "Lane", "members": ["n_start", "n_done"]},
        ],
    }


def _valid_excalidraw_styling(edge_id: str = "edge:n_start2n_done") -> dict:
    return {
        "n_start": {
            "shape": "rectangle",
            "label": {"text": "Start"},
            "strokeColor": "#111111",
            "backgroundColor": "#FFFFFF",
        },
        "n_done": {
            "shape": "rectangle",
            "label": {"text": "Done"},
            "strokeColor": "#111111",
            "backgroundColor": "#FFFFFF",
        },
        edge_id: {"strokeColor": "#111111"},
        "g_lane:background": {
            "shape": "rectangle",
            "strokeColor": "#111111",
            "backgroundColor": "transparent",
        },
        "g_lane:title": {
            "shape": "text",
            "label": {"text": "Lane", "strokeColor": "#111111"},
        },
        "n_start:icon": {
            "type": "icon",
            "props": {"icon": "label", "color": "#111111"},
        },
    }


def test_styling_agent_constructor_uses_default_palette_prompt(monkeypatch):
    captured = {}

    def fake_base_init(self, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(BaseAgent, "__init__", fake_base_init)

    StylingAgent(model=object())

    assert "{{selected_palette}}" not in captured["task_prompt"]
    assert "### SELECTED PALETTE ###" in captured["task_prompt"]


@pytest.mark.parametrize("enabled", [False, True])
def test_request_icon_option_is_enforced_on_model_output(enabled):
    agent = object.__new__(StylingAgent)
    agent.use_icons = enabled
    agent._system_prompt = "system"
    agent.invoke_with_history = lambda messages: {"specification": {}, "instantiation": _valid_excalidraw_styling()}
    state = agent.run(WorkflowState(structure_instantiation=_structure(), text_content="Start then Done"))
    assert ("n_start:icon" in state.styling_instantiation) is enabled


def test_styling_uses_validated_structure_not_obsolete_history():
    agent = object.__new__(StylingAgent)
    agent.use_icons = True
    agent._system_prompt = "system"
    captured = []
    def invoke(messages):
        captured.extend(messages)
        return {"specification": {}, "instantiation": _valid_excalidraw_styling()}
    agent.invoke_with_history = invoke
    state = WorkflowState(structure_instantiation=_structure(),
        structure_specification={"fact_ledger": [{"predicate": "must remain"}]},
        text_content="Original facts", user_query="Icons only on Start",
        runtime_directives="Locked node stays blue",
        conversation_history=[{"role": "assistant", "content": "OBSOLETE_FAILED_OUTPUT"}])
    agent.run(state)
    upstream = json.loads(captured[2]["content"])
    assert upstream["instantiation"] == _structure()
    assert upstream["specification"] == state.structure_specification
    prompt = captured[-1]["content"]
    assert all(value in prompt for value in ("Original facts", "Icons only on Start", "Locked node stays blue"))
    assert "OBSOLETE_FAILED_OUTPUT" not in str(captured)


def test_explicit_icon_coverage_is_not_silently_capped_at_half_the_nodes():
    agent = object.__new__(StylingAgent)
    agent.use_icons = True
    agent._system_prompt = "system"
    styling = _valid_excalidraw_styling()
    styling["n_done:icon"] = {"type": "icon", "props": {"icon": "check_circle"}}
    agent.invoke_with_history = lambda messages: {"specification": {}, "instantiation": styling}
    state = agent.run(WorkflowState(structure_instantiation=_structure(),
        user_query="Put icons on both Start and Done", text_content="Start then Done"))
    assert {key for key in state.styling_instantiation if key.endswith(":icon")} == {"n_start:icon", "n_done:icon"}


def test_requested_terminal_icon_preserves_ellipse_semantics():
    agent = object.__new__(StylingAgent)
    agent.use_icons = True
    agent._system_prompt = "system"
    styling = _valid_excalidraw_styling()
    styling['n_start']['shape'] = 'ellipse'
    agent.invoke_with_history = lambda messages: {'specification': {}, 'instantiation': styling}
    state = agent.run(WorkflowState(structure_instantiation=_structure(), text_content='Start then Done'))
    assert state.styling_instantiation['n_start']['shape'] == 'ellipse'
    assert 'n_start:icon' in state.styling_instantiation


def test_sequence_participant_lane_does_not_require_duplicate_title():
    styling = _valid_excalidraw_styling()
    del styling['g_lane:title']
    structure = _structure()
    structure['chart_type'] = 'sequence_diagram'
    structure['groups'][0]['members'] = ['n_start']
    assert validate_styling_instantiation(styling, structure) is styling
    structure['groups'][0]['members'].append('n_done')
    with pytest.raises(StylingValidationError, match='Missing title'):
        validate_styling_instantiation(styling, structure)


@pytest.mark.parametrize('chart_type', ['flowchart', 'sequence_diagram'])
def test_group_surface_without_companion_suffix_is_not_a_labelled_node(chart_type):
    styling = _valid_excalidraw_styling()
    styling['g_lane'] = styling.pop('g_lane:background')
    structure = _structure()
    structure['chart_type'] = chart_type
    if chart_type == 'sequence_diagram':
        structure['groups'][0]['members'] = ['n_start']
        del styling['g_lane:title']
    assert validate_styling_instantiation(styling, structure) is styling


def test_styling_contract_helper_requires_explicit_valid_canvas(monkeypatch):
    from evo_diagram.agentic_system.generation_stage.styling.contracts import (
        get_styling_contract,
    )

    monkeypatch.setenv("CANVAS_LIBRARY", "tldraw")

    with pytest.raises(TypeError):
        get_styling_contract()
    with pytest.raises(ValueError, match="Unknown canvas_library"):
        get_styling_contract("future-canvas")

    assert "Excalidraw" in get_styling_contract("excalidraw")
    assert "tldraw" in get_styling_contract("tldraw").lower()


def test_styling_contract_accepts_valid_excalidraw_group_title_and_icon():
    styling = _valid_excalidraw_styling()

    validated = validate_styling_instantiation(styling, _structure())

    assert validated is styling


def test_styling_contract_normalizes_logical_group_shell_with_valid_surface():
    styling = _valid_excalidraw_styling()
    styling["g_lane"] = {"members": ["n_start", "n_done"]}
    validated = validate_styling_instantiation(styling, _structure())
    assert "g_lane" not in validated
    assert validated["g_lane:background"] == styling["g_lane:background"]
    assert "g_lane" in styling  # Do not mutate the model's source output.


@pytest.mark.parametrize("invalid", ["missing_surface", "invalid_surface", "node", "geometry"])
def test_group_shell_normalization_does_not_hide_invalid_styles(invalid):
    styling = _valid_excalidraw_styling()
    styling["g_lane"] = {}
    if invalid == "missing_surface":
        del styling["g_lane:background"]
    elif invalid == "invalid_surface":
        styling["g_lane:background"] = {}
    elif invalid == "node":
        styling["n_start"] = {}
    else:
        styling["g_lane"]["x"] = 10
    with pytest.raises(StylingValidationError):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_unwraps_stage_structure_wrapper():
    styling = _valid_excalidraw_styling()
    structure = {"structure_instantiation": {"instantiation": _structure()}}

    assert validate_styling_instantiation(styling, structure) is styling


def test_styling_agent_leaves_underscore_icon_key_for_contract_rejection():
    agent = object.__new__(StylingAgent)
    styling = {
        "n_start": {
            "shape": "rectangle",
            "label": {"text": "Start"},
            "strokeColor": "#111111",
            "backgroundColor": "#FFFFFF",
        },
        "n_start_icon": {
            "type": "icon",
            "props": {"icon": "label", "color": "black"},
        },
    }

    processed = agent._postprocess_styling_json(styling)

    assert "n_start_icon" in processed
    assert "n_start:icon" not in processed
    with pytest.raises(StylingValidationError, match="Unknown styling id 'n_start_icon'"):
        validate_styling_instantiation(processed, _structure())


def test_styling_agent_extracts_inline_icon_to_canonical_companion_entry():
    agent = object.__new__(StylingAgent)
    styling = {
        "n_start": {
            "shape": "rectangle",
            "label": {"text": "Start"},
            "strokeColor": "#111111",
            "backgroundColor": "#FFFFFF",
            "props": {"icon": "label"},
        },
    }

    processed = agent._postprocess_styling_json(styling)

    assert "icon" not in processed["n_start"]["props"]
    assert processed["n_start:icon"]["type"] == "icon"
    assert processed["n_start:icon"]["props"]["icon"] == "label"


def test_styling_agent_validates_icon_name_against_manifest(monkeypatch, tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "colors": {
                    "black": {
                        "icons": [
                            {"name": "settings"},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(icon_assets, "icon_manifest_path", lambda: manifest_path)
    icon_assets.manifest_icon_names.cache_clear()
    agent = object.__new__(StylingAgent)

    try:
        assert agent._normalize_icon_name("settings") == "settings"
        assert agent._normalize_icon_name("unknown_icon") == "label"
    finally:
        icon_assets.manifest_icon_names.cache_clear()


def test_styling_contract_rejects_underscore_icon_key():
    styling = _valid_excalidraw_styling()
    styling["n_start_icon"] = styling.pop("n_start:icon")

    with pytest.raises(StylingValidationError, match="Unknown styling id 'n_start_icon'"):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_rejects_unknown_node_id():
    styling = _valid_excalidraw_styling()
    styling["n_ghost"] = {
        "shape": "rectangle",
        "label": {"text": "Ghost"},
        "strokeColor": "#111111",
        "backgroundColor": "#FFFFFF",
    }

    with pytest.raises(StylingValidationError, match="Unknown styling id 'n_ghost'"):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_rejects_missing_node_coverage():
    styling = _valid_excalidraw_styling()
    styling.pop("n_done")

    with pytest.raises(StylingValidationError, match="Missing styling entries.*n_done"):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_reuses_structure_edge_id_verbatim_even_when_bare():
    structure = _structure(edge_id="e1")
    styling = _valid_excalidraw_styling(edge_id="edge:n_start2n_done")

    with pytest.raises(StylingValidationError, match="Unknown styling id 'edge:n_start2n_done'"):
        validate_styling_instantiation(styling, structure)


def test_styling_contract_rejects_edge_with_layout_fields():
    styling = _valid_excalidraw_styling()
    styling["edge:n_start2n_done"] = {
        "strokeColor": "#111111",
        "start": {"elementId": "n_start", "side": "right"},
        "end": {"elementId": "n_done", "side": "left"},
        "label": {"text": "layout owns this"},
    }

    with pytest.raises(StylingValidationError, match="must be color-only.*end.*label.*start"):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_rejects_excalidraw_geometry_fields():
    styling = _valid_excalidraw_styling()
    styling["n_start"]["x"] = 100
    styling["n_start"]["width"] = 160

    with pytest.raises(StylingValidationError, match="layout-owned fields.*width.*x"):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_rejects_tldraw_props_geometry_fields():
    styling = {
        "n_start": {
            "type": "geo",
            "props": {"geo": "rectangle", "color": "blue", "fill": "semi", "text": "Start", "w": 160},
        },
        "n_done": {
            "type": "geo",
            "props": {"geo": "ellipse", "color": "green", "fill": "solid", "text": "Done"},
        },
        "edge:n_start2n_done": {"props": {"color": "black"}},
        "g_lane:background": {
            "type": "geo",
            "props": {"geo": "rectangle", "color": "grey", "fill": "none"},
        },
        "g_lane:title": {
            "type": "text",
            "props": {"text": "Lane", "color": "black"},
        },
    }

    with pytest.raises(StylingValidationError, match="props must not include layout-owned fields.*w"):
        validate_styling_instantiation(styling, _structure(), canvas_library="tldraw")


def test_styling_contract_rejects_excalidraw_unsupported_shape():
    styling = _valid_excalidraw_styling()
    styling["n_start"] = {
        **styling["n_start"],
        "shape": "hexagon",
    }

    with pytest.raises(StylingValidationError, match="unsupported shape/type 'hexagon'"):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_rejects_empty_group_title():
    styling = _valid_excalidraw_styling()
    styling["g_lane:title"] = {
        "shape": "text",
        "label": {"text": "   ", "strokeColor": "#111111"},
    }

    with pytest.raises(StylingValidationError, match="Title styling 'g_lane:title'.*non-empty text"):
        validate_styling_instantiation(styling, _structure())


def test_styling_contract_accepts_valid_tldraw_entries():
    edge_id = "e1"
    styling = {
        "n_start": {
            "type": "geo",
            "props": {"geo": "rectangle", "color": "blue", "fill": "semi", "text": "Start"},
        },
        "n_done": {
            "type": "geo",
            "props": {"geo": "ellipse", "color": "green", "fill": "solid", "text": "Done"},
        },
        edge_id: {"props": {"color": "black"}},
        "g_lane:background": {
            "type": "geo",
            "props": {"geo": "rectangle", "color": "grey", "fill": "none"},
        },
        "g_lane:title": {
            "type": "text",
            "props": {"text": "Lane", "color": "black"},
        },
    }

    assert validate_styling_instantiation(styling, _structure(edge_id=edge_id), canvas_library="tldraw") is styling


def test_styling_agent_sanitizes_bare_edge_ids_from_structure():
    agent = object.__new__(StylingAgent)
    styling = {
        "e1": {
            "strokeColor": "#111111",
            "start": {"elementId": "n_start"},
            "end": {"elementId": "n_done"},
            "label": {"text": "Layout owns this"},
        }
    }

    sanitized = agent._sanitize_edge_styling(
        styling,
        canvas_library="excalidraw",
        structure_instantiation=_structure(edge_id="e1"),
    )

    assert sanitized == {"e1": {"strokeColor": "#111111"}}


def test_styling_agent_injects_group_label_for_shape_text_title():
    agent = object.__new__(StylingAgent)
    styling = {
        "g_lane:title": {
            "shape": "text",
            "label": {"strokeColor": "#111111"},
        }
    }

    injected = agent._inject_labels_from_structure(styling, _structure())

    assert injected["g_lane:title"]["label"]["text"] == "Lane"


def test_styling_agent_validation_error_does_not_require_error_hook():
    agent = object.__new__(StylingAgent)
    agent.use_icons = False
    agent._system_prompt = "system"
    agent.invoke_with_history = lambda messages: ["not", "a", "dict"]
    state = WorkflowState(
        structure_instantiation=_structure(),
        text_content="Start then Done",
        user_query="flowchart",
    )

    with pytest.raises(StylingValidationError, match="Styling output must be a JSON object"):
        agent.run(state)


def test_styling_agent_rejects_categorized_instantiation_without_flattening():
    agent = object.__new__(StylingAgent)
    agent.use_icons = False
    agent._system_prompt = "system"
    agent.invoke_with_history = lambda messages: {
        "specification": {"visual_paradigm": {"recognition_anchor": "process boxes"}},
        "instantiation": {
            "nodes": {
                "n_start": {"shape": "rectangle", "strokeColor": "#111111"},
                "n_done": {"shape": "rectangle", "strokeColor": "#111111"},
            },
            "edges": {
                "edge:n_start2n_done": {"strokeColor": "#111111"},
            },
        },
    }
    state = WorkflowState(
        structure_instantiation=_structure(),
        text_content="Start then Done",
        user_query="flowchart",
    )

    with pytest.raises(StylingValidationError, match="flat id-keyed map"):
        agent.run(state)


def test_styling_agent_records_formatted_assistant_history():
    agent = object.__new__(StylingAgent)
    agent.use_icons = False
    agent._system_prompt = "system"
    styling = _valid_excalidraw_styling()
    styling.pop("n_start:icon")
    agent.invoke_with_history = lambda messages: {
        "specification": {"visual_paradigm": {"recognition_anchor": "process boxes"}},
        "instantiation": styling,
    }
    state = WorkflowState(
        structure_instantiation=_structure(),
        text_content="Start then Done",
        user_query="flowchart",
    )

    result = agent.run(state)

    assistant_content = result.conversation_history[-1]["content"]
    assert isinstance(json.loads(assistant_content)["specification"], dict)
    assert json.loads(assistant_content)["specification"]["visual_paradigm"]["recognition_anchor"] == "process boxes"
    assert isinstance(json.loads(assistant_content)["instantiation"], dict)
    assert '"edge:n_start2n_done"' in assistant_content


# ---------------------------------------------------------------------------
# Icon colour → icon asset directory
# ---------------------------------------------------------------------------
# ``<id>:icon`` entries carry ``props.color``, and every consumer resolves it
# through ``icon_assets.color_to_icon_folder`` to pick a pre-tinted SVG
# directory. It must therefore always be a colour NAME. Writing an Excalidraw
# hex through made ``color_to_icon_folder`` fall back to ``black`` for every
# icon on an Excalidraw canvas.


@pytest.mark.parametrize(
    ("hex_color", "expected"),
    [
        ("#1E40AF", "blue"),
        # Dark navy: nearest colour in plain RGB space is black, which is why the
        # match runs in HLS instead.
        ("#003366", "blue"),
        ("#92400E", "orange"),
        ("#B91C1C", "red"),
        ("#065F46", "green"),
        ("#6D28D9", "violet"),
        ("#1E1E1E", "black"),
        ("#6B7280", "grey"),
        ("#DBEAFE", "light-blue"),
    ],
)
def test_hex_maps_to_an_existing_icon_directory(hex_color, expected):
    assert hex_to_icon_color_name(hex_color) == expected
    assert expected in ICON_COLOR_NAMES
    # The mapped name must survive the renderer's own normalization step.
    assert icon_assets.color_to_icon_folder(expected) == expected.replace("-", "_")


def test_excalidraw_icon_color_uses_host_stroke_family_not_black():
    agent = object.__new__(StylingAgent)
    styling = {
        "n_start": {
            "shape": "rectangle",
            "label": {"text": "Start"},
            "strokeColor": "#1E40AF",
            "backgroundColor": "#DBEAFE",
        },
        # The LLM commonly emits the generic default here.
        "n_start:icon": {"type": "icon", "props": {"icon": "label", "color": "black"}},
    }

    processed = agent._postprocess_styling_json(styling)
    icon_color = processed["n_start:icon"]["props"]["color"]

    assert icon_color == "blue"
    assert not icon_color.startswith("#")
    assert icon_assets.color_to_icon_folder(icon_color) == "blue"


def test_excalidraw_icon_color_honours_llm_hex_when_supplied():
    agent = object.__new__(StylingAgent)
    styling = {
        "n_alert": {
            "shape": "rectangle",
            "label": {"text": "Alert"},
            "strokeColor": "#1E1E1E",
            "backgroundColor": "#FFFFFF",
        },
        "n_alert:icon": {"type": "icon", "props": {"icon": "label", "color": "#B91C1C"}},
    }

    processed = agent._postprocess_styling_json(styling)

    assert processed["n_alert:icon"]["props"]["color"] == "red"


def test_tldraw_icon_color_still_passes_colour_names_through():
    agent = object.__new__(StylingAgent)
    styling = {
        "n_start": {
            "type": "geo",
            "label": {"text": "Start"},
            "props": {"geo": "rectangle", "color": "green", "fill": "none"},
        },
        "n_start:icon": {"type": "icon", "props": {"icon": "label", "color": "black"}},
    }

    processed = agent._postprocess_styling_json(styling)

    assert processed["n_start:icon"]["props"]["color"] == "green"


def test_styling_no_longer_injects_edge_labels():
    """Edge labels belong to Layout; injecting them here was dead code.

    ``_sanitize_edge_styling`` strips every non-colour edge field in the same
    ``run()``, so a label written here never survived. The fallback now lives in
    ``LayoutAgent._merge_layout_with_styling``.
    """
    agent = object.__new__(StylingAgent)
    structure = _structure()
    structure["edges"][0]["label"] = "<18"
    styling = {"edge:n_start2n_done": {"strokeColor": "#111111"}}

    injected = agent._inject_labels_from_structure(styling, structure)

    assert "label" not in injected["edge:n_start2n_done"]


def test_styling_still_injects_node_and_group_labels():
    agent = object.__new__(StylingAgent)
    styling = {
        "n_start": {"shape": "rectangle", "strokeColor": "#111111"},
        "g_lane:title": {"shape": "text"},
    }

    injected = agent._inject_labels_from_structure(styling, _structure())

    assert injected["n_start"]["label"]["text"] == "Start"
    assert injected["g_lane:title"]["label"]["text"] == "Lane"
