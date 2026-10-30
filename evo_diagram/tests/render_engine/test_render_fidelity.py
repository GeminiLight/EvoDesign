# -*- coding: utf-8 -*-
"""Regression tests for the three render-fidelity bugs fixed in 2026-04.

These bugs caused rendered PNGs to silently lose content even when the
three-stage LLM pipeline produced well-reasoned structure / styling / layout
JSON. Each test pins down one specific failure mode so future refactors will
fail loudly instead of silently regressing.

Run with::

    cd evo_diagram && pytest tests/test_render_fidelity.py -v
"""

from __future__ import annotations

from collections import Counter

import pytest

from evo_diagram.agentic_system.render_engine.tldraw.arrow_adder import (
    add_arrows,
)
from evo_diagram.agentic_system.common.tldraw_utils import TLDrawIDGenerator, TLDrawUtils
from evo_diagram.agentic_system.render_engine.shared.edge_routing import (
    collect_relations,
    edge_endpoints,
    extract_edge_port_hints,
    find_shape_id,
    is_layout_edge_entry,
)
from evo_diagram.agentic_system.render_engine.tldraw.group_fitter import (
    fit_groups_to_children,
)
from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    _should_drop_edge_label,
    add_excalidraw_arrows_to_manifest,
)
from evo_diagram.agentic_system.render_engine.excalidraw.converter import (
    InstantiationToExcalidrawConverter,
)
from evo_diagram.agentic_system.render_engine.excalidraw.group_fitter import (
    fit_excalidraw_groups_to_children,
)
from evo_diagram.agentic_system.render_engine.tldraw.converter import (
    InstantiationToTldrawConverter,
)
from evo_diagram.agentic_system.render_engine.shared.render_audit import (
    audit_excalidraw_manifest,
    audit_layout_instantiation,
    audit_tldraw_manifest,
)


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


def _minimal_layout() -> dict:
    """Layout dict with one lane, two nodes, one edge — mirrors the swimlane shape."""
    return {
        "lane:background": {
            "type": "rectangle",
            "strokeColor": "#868e96",
            "backgroundColor": "#f8f9fa",
            "strokeStyle": "dashed",
            "x": 100,
            "y": 100,
            "w": 400,
            "h": 600,
        },
        "lane:title": {
            "type": "text",
            "fontFamily": 2,
            "fontSize": 24,
            "label": {"text": "Marketing"},
            "x": 220,
            "y": 120,
            "w": 120,
            "h": 30,
        },
        "a": {
            "type": "rectangle",
            "strokeColor": "#1971c2",
            "backgroundColor": "#a5d8ff",
            "label": {"text": "Author"},
            "x": 200,
            "y": 200,
            "w": 160,
            "h": 60,
        },
        "b": {
            "type": "rectangle",
            "strokeColor": "#1971c2",
            "backgroundColor": "#a5d8ff",
            "label": {"text": "Submit"},
            "x": 200,
            "y": 400,
            "w": 160,
            "h": 60,
        },
        # Bare e1 id — the bug that dropped every arrow.
        "e1": {
            "strokeColor": "#e03131",
            "routing": "straight",
            "start": {"elementId": "a", "side": "bottom"},
            "end": {"elementId": "b", "side": "top"},
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "label": {"text": "next"},
        },
    }


def _minimal_structure() -> dict:
    return {
        "chart_type": "flowchart",
        "nodes": [{"id": "a", "label": "Author"}, {"id": "b", "label": "Submit"}],
        # Uses from/to — the ElementStructure convention that broke arrow_adder.
        "edges": [{"id": "e1", "from": "a", "to": "b", "label": "next"}],
        "groups": [{"id": "lane", "label": "Marketing", "members": ["a", "b"]}],
    }


def _contract_structure() -> dict:
    return {
        "chart_type": "flowchart",
        "nodes": [
            {"id": "n_start", "label": "Start"},
            {"id": "n_done", "label": "Done"},
        ],
        "edges": [
            {"id": "edge:n_start2n_done", "source": "n_start", "target": "n_done"},
        ],
        "groups": [],
    }


def _contract_structure_with_group() -> dict:
    structure = _contract_structure()
    structure["groups"] = [{"id": "g_lane", "label": "Lane", "members": ["n_start", "n_done"]}]
    return structure


def _contract_layout() -> dict:
    return {
        "n_start": {"type": "rectangle", "x": 0, "y": 0, "w": 120, "h": 60},
        "n_done": {"type": "rectangle", "x": 220, "y": 0, "w": 120, "h": 60},
        "edge:n_start2n_done": {
            "start": {"elementId": "n_start", "side": "right"},
            "end": {"elementId": "n_done", "side": "left"},
        },
    }


def _contract_layout_with_group_shell() -> dict:
    layout = _contract_layout()
    layout.update({
        "g_lane": {"type": "rectangle", "label": {"text": "Lane"}},
        "g_lane:background": {"type": "rectangle", "x": -20, "y": -30, "w": 400, "h": 140},
        "g_lane:title": {"type": "text", "x": 0, "y": -20, "w": 120, "h": 24},
    })
    return layout


# ----------------------------------------------------------------------------
# Bug A — standalone text element reads label.text (not top-level text)
# ----------------------------------------------------------------------------


def test_bug_a_standalone_text_reads_label_text():
    converter = InstantiationToExcalidrawConverter(layout_instantiation=_minimal_layout())
    manifest = converter.convert()

    title_elems = [
        e for e in manifest["elements"]
        if e["type"] == "text" and not e.get("containerId")
    ]
    assert title_elems, "expected at least one standalone text element"
    texts = [e.get("text") for e in title_elems]
    assert "Marketing" in texts, f"lane title lost, got {texts!r}"


def test_bug_a_font_family_defaults_to_helvetica():
    """When Styling omits fontFamily we should default to 2 (Helvetica), not 5."""
    layout = _minimal_layout()
    # Strip the explicit fontFamily so we exercise the default path.
    layout["lane:title"].pop("fontFamily", None)

    converter = InstantiationToExcalidrawConverter(layout_instantiation=layout)
    manifest = converter.convert()
    title = next(
        e for e in manifest["elements"]
        if e["type"] == "text" and e.get("text") == "Marketing"
    )
    assert title.get("fontFamily") == 2, title


# ----------------------------------------------------------------------------
# Bug B — edge classifier recognises bare e* keys
# ----------------------------------------------------------------------------


def test_bug_b_layout_edge_entry_accepts_bare_id_with_start_end():
    payload = {
        "strokeColor": "#1e1e1e",
        "start": {"elementId": "a", "side": "bottom"},
        "end": {"elementId": "b", "side": "top"},
    }
    assert is_layout_edge_entry("e1", payload)
    assert is_layout_edge_entry("edge:a2b", payload)
    # Plain node shouldn't be mistaken for an edge.
    assert not is_layout_edge_entry("a", {"type": "rectangle", "x": 0, "y": 0})


def test_bug_b_converter_collects_bare_edge_keys():
    converter = InstantiationToExcalidrawConverter(layout_instantiation=_minimal_layout())
    manifest = converter.convert()
    edge_data = manifest["_meta"]["edge_data"]
    assert "e1" in edge_data, f"bare e1 edge not collected: {list(edge_data)}"
    # Edge styling/routing must be preserved for arrow_adder downstream.
    assert edge_data["e1"]["strokeColor"] == "#e03131"
    assert edge_data["e1"]["routing"] == "straight"


def test_excalidraw_converter_outputs_stable_manifest_for_same_input():
    first = InstantiationToExcalidrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    ).convert()
    second = InstantiationToExcalidrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    ).convert()

    assert first == second
    assert first["elements"][0]["updated"] == 1


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        (
            {**_contract_layout(), "n_ghost": {"type": "rectangle", "x": 500, "y": 0, "w": 120, "h": 60}},
            "Unknown layout id.*n_ghost",
        ),
        (
            {**_contract_layout(), "n_done": {"type": "rectangle", "x": 220, "y": 0, "w": 120}},
            "Missing geometry fields.*n_done.*h",
        ),
        (
            {
                **_contract_layout(),
                "edge:n_start2n_done": {
                    "start": {"elementId": "n_done", "side": "left"},
                    "end": {"elementId": "n_start", "side": "right"},
                },
            },
            "Edge endpoint mismatch.*edge:n_start2n_done",
        ),
        (
            {**_contract_layout(), "n_start_icon": {"type": "icon", "props": {"icon": "label"}}},
            "Unsupported underscore icon layout id.*n_start_icon",
        ),
    ],
)
def test_excalidraw_converter_rejects_layout_contract_violations_before_render(layout, expected):
    with pytest.raises(ValueError, match=expected):
        InstantiationToExcalidrawConverter(
            layout_instantiation=layout,
            structure_instantiation=_contract_structure(),
        ).convert()


def test_tldraw_converter_rejects_layout_contract_violations_before_render():
    layout = {
        **_contract_layout(),
        "edge:n_start2n_done": {
            "start": {"elementId": "n_done", "side": "left"},
            "end": {"elementId": "n_start", "side": "right"},
        },
    }

    with pytest.raises(ValueError, match="Edge endpoint mismatch.*edge:n_start2n_done"):
        InstantiationToTldrawConverter(
            layout_instantiation=layout,
            structure_instantiation=_contract_structure(),
        ).convert()


def test_tldraw_converter_rejects_underscore_icon_layout_key_before_render():
    layout = {
        **_contract_layout(),
        "n_start_icon": {"type": "icon", "props": {"icon": "label"}},
    }

    with pytest.raises(ValueError, match="Unsupported underscore icon layout id.*n_start_icon"):
        InstantiationToTldrawConverter(
            layout_instantiation=layout,
            structure_instantiation=_contract_structure(),
        ).convert()


def test_excalidraw_converter_allows_group_shell_when_background_carries_geometry():
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=_contract_layout_with_group_shell(),
        structure_instantiation=_contract_structure_with_group(),
    ).convert()

    assert manifest["_meta"]["id_map"]["g_lane:background"]


def test_tldraw_converter_preserves_top_level_geometry():
    manifest = InstantiationToTldrawConverter(
        layout_instantiation=_contract_layout(),
        structure_instantiation=_contract_structure(),
    ).convert()
    store = manifest["document"]["store"]

    assert store["shape:n_start"]["x"] == 0
    assert store["shape:n_start"]["y"] == 0
    assert store["shape:n_start"]["props"]["w"] == 120
    assert store["shape:n_start"]["props"]["h"] == 60
    assert store["shape:n_done"]["x"] == 220
    assert store["shape:n_done"]["props"]["w"] == 120


def test_tldraw_converter_skips_group_shell_when_background_carries_geometry():
    manifest = InstantiationToTldrawConverter(
        layout_instantiation=_contract_layout_with_group_shell(),
        structure_instantiation=_contract_structure_with_group(),
    ).convert()
    store = manifest["document"]["store"]

    assert "shape:g_lane" not in store
    assert "shape:g_lane:background" in store
    assert store["shape:g_lane:background"]["props"]["w"] == 400
    assert store["shape:g_lane:background"]["props"]["h"] == 140
    assert "shape:g_lane:title" in store


def test_tldraw_titled_layer_frame_without_group_prefix_skips_bound_text_and_sorts_below_child():
    layout = {
        "service_layer": {
            "type": "rectangle",
            "label": {"text": "Service Boundary Layer"},
            "backgroundColor": "#f8fafc",
            "x": 0, "y": 0, "w": 500, "h": 180,
        },
        "service_layer:title": {
            "type": "text",
            "label": {"text": "Service Boundary Layer"},
            "x": 20, "y": 20, "w": 220, "h": 32,
        },
        "service_api": {
            "type": "rectangle",
            "label": {"text": "Service API"},
            "x": 80, "y": 80, "w": 160, "h": 60,
        },
    }

    manifest = InstantiationToTldrawConverter(layout_instantiation=layout).convert()
    store = manifest["document"]["store"]

    assert store["shape:service_layer"]["props"]["text"] == ""
    assert store["shape:service_layer:title"]["props"]["text"] == "Service Boundary Layer"
    assert store["shape:service_layer"]["index"] < store["shape:service_api"]["index"]


def test_tldraw_converter_places_icons_above_nodes_below_titles(monkeypatch):
    monkeypatch.setattr(
        "evo_diagram.agentic_system.render_engine.tldraw.converter.require_icon_svg_path",
        lambda *args, **kwargs: "cloud.svg",
    )
    layout = {
        "n_api": {
            "type": "rectangle",
            "label": {"text": "API"},
            "x": 80,
            "y": 80,
            "w": 160,
            "h": 60,
        },
        "n_api:icon": {
            "type": "icon",
            "props": {"icon": "cloud"},
        },
        "n_api:title": {
            "type": "text",
            "label": {"text": "Service"},
            "x": 80,
            "y": 40,
            "w": 160,
            "h": 30,
        },
    }

    manifest = InstantiationToTldrawConverter(layout_instantiation=layout).convert()
    store = manifest["document"]["store"]

    assert store["shape:n_api"]["index"] < store["shape:n_api:icon"]["index"]
    assert store["shape:n_api:icon"]["index"] < store["shape:n_api:title"]["index"]
    assert store["shape:n_api:icon"]["index"] != "a99999"


# ----------------------------------------------------------------------------
# Bug C — arrow_adder tolerates from/to AND source/target
# ----------------------------------------------------------------------------


def test_bug_c_edge_endpoints_accepts_either_convention():
    assert edge_endpoints({"from": "a", "to": "b"}) == ("a", "b")
    assert edge_endpoints({"source": "a", "target": "b"}) == ("a", "b")
    # Mixed: explicit from/to wins (newer convention).
    assert edge_endpoints({"from": "a", "to": "b", "source": "x"}) == ("a", "b")


def test_bug_c_collect_relations_enriches_with_source_target():
    rels = collect_relations(_minimal_structure())
    assert len(rels) == 1
    assert rels[0]["source"] == "a"
    assert rels[0]["target"] == "b"
    # Original keys preserved so helpers can still read them.
    assert rels[0]["from"] == "a"
    assert rels[0]["to"] == "b"


def test_bug_c_collect_relations_unwraps_nested_structure_payloads():
    wrapped = {"structure_instantiation": {"instantiation": _minimal_structure()}}

    rels = collect_relations(wrapped)

    assert len(rels) == 1
    assert rels[0]["source"] == "a"
    assert rels[0]["target"] == "b"


def test_bug_c_arrow_adder_produces_arrow_from_from_to_convention():
    converter = InstantiationToExcalidrawConverter(layout_instantiation=_minimal_layout())
    manifest = converter.convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, _minimal_structure())

    types = Counter(e["type"] for e in manifest["elements"])
    assert types.get("arrow", 0) == 1, (
        f"expected 1 arrow, got types={dict(types)}"
    )


def test_bug_c_tldraw_arrow_adder_records_semantic_edge_metadata():
    converter = InstantiationToTldrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    )
    manifest = converter.convert()

    new_items = add_arrows(manifest["document"]["store"], _minimal_structure())
    arrows = [
        item
        for item in new_items.values()
        if item.get("typeName") == "shape" and item.get("type") == "arrow"
    ]

    assert len(arrows) == 1
    assert arrows[0]["meta"]["semantic_edge_id"] == "e1"
    assert arrows[0]["meta"]["source"] == "a"
    assert arrows[0]["meta"]["target"] == "b"


def test_tldraw_arrow_adder_outputs_stable_ids_for_same_input():
    first_manifest = InstantiationToTldrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    ).convert()
    second_manifest = InstantiationToTldrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    ).convert()

    first = add_arrows(first_manifest["document"]["store"], _minimal_structure())
    second = add_arrows(second_manifest["document"]["store"], _minimal_structure())

    assert first == second


def test_tldraw_binding_factory_outputs_stable_ids_for_same_input():
    first = TLDrawUtils.create_binding(
        "shape:arrow",
        "shape:target",
        terminal="start",
        anchor={"x": 0.25, "y": 0.75},
    )
    second = TLDrawUtils.create_binding(
        "shape:arrow",
        "shape:target",
        terminal="start",
        anchor={"y": 0.75, "x": 0.25},
    )

    assert first == second
    assert first["id"].startswith("binding:")


def test_tldraw_id_generator_requires_semantic_seed():
    with pytest.raises(ValueError, match="semantic seed"):
        TLDrawIDGenerator.generate_shape_id("shape")

    with pytest.raises(ValueError, match="semantic seed"):
        TLDrawIDGenerator.generate_stable_index("b")


def test_tldraw_id_generator_outputs_stable_values_from_seed():
    first_shape = TLDrawIDGenerator.generate_shape_id("shape", seed=["edge", "a", "b"])
    second_shape = TLDrawIDGenerator.generate_shape_id("shape", seed=["edge", "a", "b"])
    first_index = TLDrawIDGenerator.generate_stable_index("b", seed=["edge", "a", "b"])
    second_index = TLDrawIDGenerator.generate_stable_index("b", seed=["edge", "a", "b"])

    assert first_shape == second_shape
    assert first_index == second_index
    assert first_shape.startswith("shape:")
    assert first_index.startswith("b")


def test_tldraw_port_hints_use_layout_edge_data():
    converter = InstantiationToTldrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    )
    manifest = converter.convert()

    hints = extract_edge_port_hints(_minimal_structure(), manifest["document"]["store"])

    assert hints["e1"] == {"start": "bottom", "end": "top"}


def test_tldraw_converter_records_layout_edge_data():
    converter = InstantiationToTldrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    )
    manifest = converter.convert()

    meta = manifest["document"]["store"]["document:document"]["meta"]
    assert meta["edge_data"]["e1"]["start"] == {"elementId": "a", "side": "bottom"}
    assert meta["edge_data"]["e1"]["end"] == {"elementId": "b", "side": "top"}
    assert "edge_hints" not in meta


def test_tldraw_arrow_prefers_layout_edge_data_when_structure_ids_drift():
    layout = _minimal_layout()
    layout["n_start"] = layout.pop("a")
    layout["n_start"]["label"] = {"text": "Layout Start"}
    layout["n_end"] = layout.pop("b")
    layout["n_end"]["label"] = {"text": "Layout End"}
    layout["e1"] = {
        **layout["e1"],
        "start": {"elementId": "n_start", "side": "bottom"},
        "end": {"elementId": "n_end", "side": "top"},
    }
    converter = InstantiationToTldrawConverter(layout_instantiation=layout)
    manifest = converter.convert()

    new_items = add_arrows(manifest["document"]["store"], _minimal_structure())
    arrows = [
        item
        for item in new_items.values()
        if item.get("typeName") == "shape" and item.get("type") == "arrow"
    ]

    assert len(arrows) == 1
    assert arrows[0]["meta"]["semantic_edge_id"] == "e1"
    assert arrows[0]["meta"]["source"] == "n_start"
    assert arrows[0]["meta"]["target"] == "n_end"


def test_bug_c_tldraw_arrow_consumes_layout_edge_payload():
    layout = _minimal_layout()
    layout["e1"] = {
        **layout["e1"],
        "props": {"color": "green"},
        "routing": "curved",
        "startArrowhead": "dot",
        "endArrowhead": "triangle",
    }
    converter = InstantiationToTldrawConverter(
        layout_instantiation=layout,
        structure_instantiation=_minimal_structure(),
    )
    manifest = converter.convert()

    new_items = add_arrows(manifest["document"]["store"], _minimal_structure())
    arrow = next(
        item
        for item in new_items.values()
        if item.get("typeName") == "shape" and item.get("type") == "arrow"
    )

    assert arrow["props"]["color"] == "green"
    assert arrow["props"]["labelColor"] == "green"
    assert arrow["props"]["kind"] == "curved"
    assert arrow["props"]["arrowheadStart"] == "dot"
    assert arrow["props"]["arrowheadEnd"] == "triangle"


def test_bug_c_tldraw_arrow_defaults_missing_end_arrowhead_to_arrow():
    layout = _minimal_layout()
    layout["e1"].pop("endArrowhead")
    converter = InstantiationToTldrawConverter(
        layout_instantiation=layout,
        structure_instantiation=_minimal_structure(),
    )
    manifest = converter.convert()

    new_items = add_arrows(manifest["document"]["store"], _minimal_structure())
    arrow = next(
        item
        for item in new_items.values()
        if item.get("typeName") == "shape" and item.get("type") == "arrow"
    )

    assert arrow["props"]["arrowheadStart"] == "none"
    assert arrow["props"]["arrowheadEnd"] == "arrow"


def test_bug_c_tldraw_arrow_maps_hex_stroke_color_to_tldraw_enum():
    converter = InstantiationToTldrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    )
    manifest = converter.convert()

    new_items = add_arrows(manifest["document"]["store"], _minimal_structure())
    arrow = next(
        item
        for item in new_items.values()
        if item.get("typeName") == "shape" and item.get("type") == "arrow"
    )

    assert arrow["props"]["color"] == "red"


def test_bug_c_arrow_inherits_layout_stroke_and_routing():
    """The edge in layout carries strokeColor=#e03131 and routing=straight.

    These should reach the rendered arrow element — confirms Bug B fix wires
    edge_data through to arrow_adder.
    """
    converter = InstantiationToExcalidrawConverter(layout_instantiation=_minimal_layout())
    manifest = converter.convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, _minimal_structure())
    arrow = next(e for e in manifest["elements"] if e["type"] == "arrow")
    assert arrow["strokeColor"] == "#e03131", arrow
    # Straight routing means elbowed=False (the default path kept it false).
    assert arrow.get("elbowed") is False, arrow


def test_bug_c_excalidraw_arrow_records_semantic_edge_metadata():
    converter = InstantiationToExcalidrawConverter(layout_instantiation=_minimal_layout())
    manifest = converter.convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, _minimal_structure())
    arrow = next(e for e in manifest["elements"] if e["type"] == "arrow")

    assert arrow["meta"]["semantic_edge_id"] == "e1"
    assert arrow["meta"]["source"] == "a"
    assert arrow["meta"]["target"] == "b"


def test_edge_label_filter_allows_five_word_informative_label():
    reason = _should_drop_edge_label(
        "publishes real time inventory update",
        "a",
        "b",
        {"a": "Author", "b": "Submit"},
    )
    assert reason is None


def test_edge_label_filter_drops_six_word_description():
    reason = _should_drop_edge_label(
        "publishes real time inventory update event",
        "a",
        "b",
        {"a": "Author", "b": "Submit"},
    )
    assert reason == "too long (6 words)"


# ----------------------------------------------------------------------------
# Audit hooks
# ----------------------------------------------------------------------------


def test_audit_layout_flags_empty_title():
    layout = _minimal_layout()
    layout["lane:title"]["label"] = {}  # strip the title text
    warnings = audit_layout_instantiation(layout, _minimal_structure())
    assert any("empty title text" in w for w in warnings), warnings


def test_audit_layout_clean_sample_has_no_warnings():
    warnings = audit_layout_instantiation(_minimal_layout(), _minimal_structure())
    assert warnings == [], warnings


def test_audit_manifest_flags_low_arrow_coverage():
    # Structure expects 1 edge, manifest has 0 arrows → should warn.
    manifest = {"elements": [{"type": "rectangle", "id": "x"}]}
    report = audit_excalidraw_manifest(manifest, _minimal_structure())
    assert any("rendered arrows=0" in w for w in report.warnings), report.warnings


def test_audit_excalidraw_manifest_unwraps_stage_structure_instantiation():
    manifest = {"elements": [{"type": "rectangle", "id": "x"}]}
    structure = {"instantiation": _minimal_structure()}

    report = audit_excalidraw_manifest(manifest, structure)

    assert any("rendered arrows=0" in w for w in report.warnings), report.warnings
    assert any(issue.category == "arrow_coverage" for issue in report.issues)


def test_audit_manifest_uses_semantic_edge_ids_when_available():
    manifest = {
        "elements": [
            {
                "type": "arrow",
                "id": "arrow:wrong",
                "meta": {"semantic_edge_id": "other"},
            }
        ]
    }

    report = audit_excalidraw_manifest(manifest, _minimal_structure())

    assert any("Missing Structure edge ids: e1" in w for w in report.warnings), report.warnings
    assert any(issue.category == "arrow_coverage" for issue in report.issues)


def test_audit_manifest_reports_named_edge_missing_even_when_threshold_passes():
    structure = {
        "edges": [
            {"id": "e1", "from": "a", "to": "b"},
            {"id": "e2", "from": "b", "to": "c"},
            {"id": "e3", "from": "c", "to": "d"},
            {"id": "e4", "from": "d", "to": "e"},
        ]
    }
    manifest = {
        "elements": [
            {"type": "arrow", "id": "a2", "meta": {"semantic_edge_id": "e2"}},
            {"type": "arrow", "id": "a3", "meta": {"semantic_edge_id": "e3"}},
            {"type": "arrow", "id": "a4", "meta": {"semantic_edge_id": "e4"}},
        ]
    }

    report = audit_excalidraw_manifest(manifest, structure)

    assert any("Missing Structure edge ids: e1" in w for w in report.warnings), report.warnings
    assert any(issue.category == "arrow_coverage" for issue in report.issues)


def test_audit_manifest_falls_back_to_counts_when_some_edges_have_no_id():
    structure = _minimal_structure()
    structure["edges"].append({"from": "b", "to": "a", "label": "return"})
    manifest = {
        "elements": [
            {
                "type": "arrow",
                "id": "arrow:e1",
                "meta": {"semantic_edge_id": "e1"},
            },
            {
                "type": "arrow",
                "id": "arrow:anonymous",
            },
        ]
    }

    report = audit_excalidraw_manifest(manifest, structure)

    assert report.warnings == []
    assert report.issues == []


def test_audit_tldraw_manifest_flags_low_arrow_coverage():
    manifest = {"document": {"store": {}}}

    report = audit_tldraw_manifest(manifest, _minimal_structure())

    assert any("TLDraw rendered arrows=0" in w for w in report.warnings), report.warnings
    assert any(issue.category == "arrow_coverage" for issue in report.issues)


def test_audit_tldraw_manifest_unwraps_stage_structure_instantiation():
    manifest = {"document": {"store": {}}}
    structure = {"instantiation": _minimal_structure()}

    report = audit_tldraw_manifest(manifest, structure)

    assert any("TLDraw rendered arrows=0" in w for w in report.warnings), report.warnings
    assert any(issue.category == "arrow_coverage" for issue in report.issues)


def test_audit_tldraw_manifest_flags_missing_semantic_edge_id():
    manifest = {
        "document": {
            "store": {
                "shape:arrow": {
                    "id": "shape:arrow",
                    "typeName": "shape",
                    "type": "arrow",
                    "meta": {"semantic_edge_id": "other"},
                    "props": {},
                }
            }
        }
    }

    report = audit_tldraw_manifest(manifest, _minimal_structure())

    assert any("Missing Structure edge ids: e1" in w for w in report.warnings), report.warnings


def test_audit_tldraw_manifest_reports_named_edge_missing_when_arrow_count_matches():
    structure = {
        "edges": [
            {"id": "e1", "from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ]
    }
    manifest = {
        "document": {
            "store": {
                "shape:arrow:wrong": {
                    "id": "shape:arrow:wrong",
                    "typeName": "shape",
                    "type": "arrow",
                    "meta": {"semantic_edge_id": "other"},
                    "props": {},
                },
                "shape:arrow:anonymous": {
                    "id": "shape:arrow:anonymous",
                    "typeName": "shape",
                    "type": "arrow",
                    "meta": {},
                    "props": {},
                },
            }
        }
    }

    report = audit_tldraw_manifest(manifest, structure)

    assert any("Missing Structure edge ids: e1" in w for w in report.warnings), report.warnings
    assert any(issue.category == "arrow_coverage" for issue in report.issues)


def test_audit_tldraw_manifest_falls_back_to_counts_when_some_edges_have_no_id():
    structure = _minimal_structure()
    structure["edges"].append({"from": "b", "to": "a", "label": "return"})
    manifest = {
        "document": {
            "store": {
                "shape:arrow:e1": {
                    "id": "shape:arrow:e1",
                    "typeName": "shape",
                    "type": "arrow",
                    "meta": {"semantic_edge_id": "e1"},
                    "props": {},
                },
                "shape:arrow:anonymous": {
                    "id": "shape:arrow:anonymous",
                    "typeName": "shape",
                    "type": "arrow",
                    "meta": {},
                    "props": {},
                },
            }
        }
    }

    report = audit_tldraw_manifest(manifest, structure)

    assert report.warnings == []
    assert report.issues == []


def test_audit_tldraw_manifest_flags_empty_title_text():
    manifest = {
        "document": {
            "store": {
                "shape:lane:title": {
                    "id": "shape:lane:title",
                    "typeName": "shape",
                    "type": "geo",
                    "meta": {},
                    "props": {"text": "   "},
                }
            }
        }
    }

    report = audit_tldraw_manifest(manifest, _minimal_structure())

    assert any("TLDraw title shape" in w and "empty props.text" in w for w in report.warnings)
    assert any(issue.element_id == "shape:lane:title" for issue in report.issues)


def test_audit_excalidraw_group_zorder_resolves_background_suffix():
    structure = {"groups": [{"id": "lane", "members": ["n1"]}]}
    manifest = {
        "_meta": {"id_map": {"lane:background": "bg", "n1": "node"}},
        "elements": [
            {"id": "node", "type": "rectangle", "index": "a00001"},
            {"id": "bg", "type": "rectangle", "index": "a00002"},
        ],
    }

    report = audit_excalidraw_manifest(manifest, structure)

    assert any(issue.category == "zorder" and issue.element_id == "bg" for issue in report.issues)


def test_audit_excalidraw_group_zorder_resolves_direct_group_mapping():
    structure = {"groups": [{"id": "lane", "members": ["n1"]}]}
    manifest = {
        "_meta": {"id_map": {"lane": "bg", "n1": "node"}},
        "elements": [
            {"id": "node", "type": "rectangle", "index": "a00001"},
            {"id": "bg", "type": "rectangle", "index": "a00002"},
        ],
    }

    report = audit_excalidraw_manifest(manifest, structure)

    assert any(issue.category == "zorder" and issue.element_id == "bg" for issue in report.issues)


def test_tldraw_find_shape_id_resolves_group_background_aliases():
    store = {
        "shape:g_lane:background": {
            "id": "shape:g_lane:background",
            "typeName": "shape",
            "type": "geo",
            "props": {"text": ""},
        }
    }

    assert find_shape_id(store, "g_lane") == "shape:g_lane:background"
    assert find_shape_id(store, "group:g_lane") == "shape:g_lane:background"


def test_excalidraw_group_fitter_resolves_direct_group_frame_mapping():
    manifest = {
        "type": "excalidraw/clipboard",
        "_meta": {"id_map": {"g_lane": "bg", "n1": "child"}},
        "elements": [
            {
                "id": "bg",
                "type": "rectangle",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 60,
            },
            {
                "id": "child",
                "type": "rectangle",
                "x": 100,
                "y": 70,
                "width": 80,
                "height": 40,
            },
        ],
    }
    structure = {"groups": [{"id": "g_lane", "members": ["n1"]}]}

    fitted = fit_excalidraw_groups_to_children(manifest, structure, padding=10)
    bg = next(elem for elem in fitted["elements"] if elem["id"] == "bg")

    assert bg["x"] == 90
    assert bg["y"] == 60
    assert bg["width"] == 100
    assert bg["height"] == 60


def test_tldraw_group_fitter_resolves_g_lane_background_and_member_shapes():
    manifest = InstantiationToTldrawConverter(
        layout_instantiation=_contract_layout_with_group_shell(),
        structure_instantiation=_contract_structure_with_group(),
    ).convert()

    fitted = fit_groups_to_children(
        manifest,
        _contract_structure_with_group(),
        padding=20,
    )
    bg = fitted["document"]["store"]["shape:g_lane:background"]

    assert bg["x"] == -20
    assert bg["y"] == -40
    assert bg["props"]["w"] == 380
    assert bg["props"]["h"] == 120


# ----------------------------------------------------------------------------
# Bug D — group frame must paint below its children (z-order)
# ----------------------------------------------------------------------------
#
# The pre-fix converter assigned fractional indices in dict-insertion order,
# so a layout that emitted ``g_empathize`` AFTER its children produced a
# manifest where the opaque group rectangle covered them in the rendered PNG.
# These tests pin the layer-sort behavior so future refactors cannot
# silently regress.


def _index_by_semantic_id(manifest: dict) -> dict:
    id_map = manifest["_meta"]["id_map"]
    eid_to_semantic = {v: k for k, v in id_map.items()}
    return {
        eid_to_semantic[e["id"]]: e["index"]
        for e in manifest["elements"]
        if e["id"] in eid_to_semantic
    }


def test_bug_d_group_frame_painted_below_children():
    """Mirrors the mindmap_20251205_051354_105 failure: children emitted
    FIRST, group frame LAST. Converter must still paint the group behind."""
    layout = {
        # Children first (normal LLM output order)
        "n_a": {
            "type": "rectangle",
            "label": {"text": "A"},
            "backgroundColor": "#d0ebff",
            "x": 0, "y": 0, "w": 100, "h": 50,
        },
        "n_b": {
            "type": "rectangle",
            "label": {"text": "B"},
            "backgroundColor": "#d0ebff",
            "x": 110, "y": 0, "w": 100, "h": 50,
        },
        # Group frame LAST — the bug trigger
        "g_box": {
            "type": "rectangle",
            "label": {"text": "Box"},
            "backgroundColor": "#e7f5ff",
            "x": -10, "y": -10, "w": 230, "h": 70,
        },
    }
    converter = InstantiationToExcalidrawConverter(layout_instantiation=layout)
    manifest = converter.convert()
    idx = _index_by_semantic_id(manifest)

    # Excalidraw paints ascending fractional index first → group rectangle's
    # index must be LESS than each child rectangle's index.
    assert idx["g_box"] < idx["n_a"], (
        f"g_box index {idx['g_box']!r} must come before n_a {idx['n_a']!r}"
    )
    assert idx["g_box"] < idx["n_b"], (
        f"g_box index {idx['g_box']!r} must come before n_b {idx['n_b']!r}"
    )


def test_bug_d_background_key_also_treated_as_group_frame():
    """``lane:background`` is the swimlane convention for a group frame.
    It must be classified at the group-frame layer too."""
    layout = {
        "n_a": {
            "type": "rectangle",
            "label": {"text": "A"},
            "x": 0, "y": 0, "w": 100, "h": 50,
        },
        "lane:background": {
            "type": "rectangle",
            "backgroundColor": "#f8f9fa",
            "x": -20, "y": -20, "w": 300, "h": 200,
        },
    }
    converter = InstantiationToExcalidrawConverter(layout_instantiation=layout)
    manifest = converter.convert()
    idx = _index_by_semantic_id(manifest)
    assert idx["lane:background"] < idx["n_a"]


# ----------------------------------------------------------------------------
# Bug E — group with a ``:title`` sibling must not emit a duplicate bound
# title on the frame itself
# ----------------------------------------------------------------------------


def test_bug_e_titled_group_frame_skips_bound_text():
    """Layout emits both g_X (with label.text) and g_X:title. The converter
    must emit ONE visible title — the standalone :title text — not two."""
    layout = {
        "g_box": {
            "type": "rectangle",
            "label": {"text": "Empathize"},
            "backgroundColor": "#e7f5ff",
            "x": 0, "y": 0, "w": 200, "h": 200,
        },
        "g_box:title": {
            "type": "text",
            "label": {"text": "Empathize"},
            "x": 10, "y": 10,
        },
        "n_child": {
            "type": "rectangle",
            "label": {"text": "Observe"},
            "x": 20, "y": 80, "w": 100, "h": 50,
        },
    }
    converter = InstantiationToExcalidrawConverter(layout_instantiation=layout)
    manifest = converter.convert()

    empathize_texts = [
        e for e in manifest["elements"]
        if e["type"] == "text" and e.get("text") == "Empathize"
    ]
    assert len(empathize_texts) == 1, (
        f"expected exactly one 'Empathize' text element, got {len(empathize_texts)}: "
        f"containerIds={[e.get('containerId') for e in empathize_texts]}"
    )
    # The surviving one must be the standalone title, not a bound center label.
    assert empathize_texts[0].get("containerId") is None

    # And the group frame's boundElements must NOT include a duplicate title ref.
    g_eid = manifest["_meta"]["id_map"]["g_box"]
    g_shape = next(e for e in manifest["elements"] if e["id"] == g_eid)
    assert not g_shape.get("boundElements"), (
        f"group frame should have no bound text when :title sibling exists, "
        f"got boundElements={g_shape.get('boundElements')}"
    )


def test_bug_e_titled_layer_frame_without_group_prefix_skips_bound_text():
    """Layer frames often use ids like ``service_layer`` rather than ``g_*``.
    A standalone ``:title`` sibling is enough to classify them as group frames."""
    layout = {
        "service_layer": {
            "type": "rectangle",
            "label": {"text": "Service Boundary Layer"},
            "backgroundColor": "#f8fafc",
            "x": 0, "y": 0, "w": 500, "h": 180,
        },
        "service_layer:title": {
            "type": "text",
            "label": {"text": "Service Boundary Layer"},
            "x": 20, "y": 20,
        },
        "service_api": {
            "type": "rectangle",
            "label": {"text": "Service API"},
            "x": 80, "y": 80, "w": 160, "h": 60,
        },
    }
    converter = InstantiationToExcalidrawConverter(layout_instantiation=layout)
    manifest = converter.convert()

    titles = [
        e for e in manifest["elements"]
        if e["type"] == "text" and e.get("text") == "Service Boundary Layer"
    ]
    assert len(titles) == 1
    assert titles[0].get("containerId") is None

    idx = _index_by_semantic_id(manifest)
    assert idx["service_layer"] < idx["service_api"]


def test_bug_e_untitled_group_keeps_bound_text_fallback():
    """Negative regression: a group frame WITHOUT a :title sibling should
    still get its label rendered as bound text (so we don't silently lose it
    when Styling skips the :title entry)."""
    layout = {
        "g_box": {
            "type": "rectangle",
            "label": {"text": "Fallback"},
            "x": 0, "y": 0, "w": 200, "h": 100,
        },
    }
    converter = InstantiationToExcalidrawConverter(layout_instantiation=layout)
    manifest = converter.convert()
    fallback = [
        e for e in manifest["elements"]
        if e["type"] == "text" and e.get("text") == "Fallback"
    ]
    assert len(fallback) == 1, fallback


# ----------------------------------------------------------------------------
# Explicit zIndex override — escape hatch for LLM / post-processors that
# need non-default stacking (decorative frames, callouts).
# ----------------------------------------------------------------------------


def test_explicit_zindex_overrides_layer_heuristic():
    layout = {
        # Normally a group frame (layer 100). Force it ABOVE the node via zIndex.
        "g_decoration": {
            "type": "rectangle",
            "zIndex": 250,
            "backgroundColor": "#ffec99",
            "x": 0, "y": 0, "w": 100, "h": 100,
        },
        "n_under": {
            "type": "rectangle",
            "label": {"text": "under"},
            "x": 10, "y": 10, "w": 80, "h": 30,
        },
    }
    converter = InstantiationToExcalidrawConverter(layout_instantiation=layout)
    manifest = converter.convert()
    idx = _index_by_semantic_id(manifest)
    assert idx["g_decoration"] > idx["n_under"], (
        f"explicit zIndex=250 should paint g_decoration ABOVE n_under (layer 200); "
        f"got g_decoration={idx['g_decoration']!r}, n_under={idx['n_under']!r}"
    )
