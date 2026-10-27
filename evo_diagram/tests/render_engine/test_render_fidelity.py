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
from copy import deepcopy

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
from evo_diagram.agentic_system.render_engine.shared.edge_crossing_detector import (
    detect_crossings,
)
from evo_diagram.agentic_system.render_engine.tldraw.group_fitter import (
    fit_groups_to_children,
)
from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    _architecture_port_hint,
    _avoid_node_intersections,
    _compress_orthogonal_path,
    _orthogonal_visibility_route,
    _path_avoids_endpoint_interiors,
    _path_crossing_count,
    _path_is_clear,
    _prefer_clear_port_pair,
    _prefer_crosscutting_lower_corridor_route,
    _prefer_architecture_outer_route,
    _normalize_label_payload,
    _merge_semantic_edge_labels,
    _reposition_edge_labels,
    _should_drop_edge_label,
    _segment_hits_box,
    add_excalidraw_arrows_to_manifest,
    rebuild_excalidraw_arrows,
)
from evo_diagram.agentic_system.render_engine.excalidraw.converter import (
    InstantiationToExcalidrawConverter,
)
from evo_diagram.agentic_system.render_engine.excalidraw.group_fitter import (
    fit_excalidraw_groups_to_children,
)
from evo_diagram.agentic_system.render_engine.excalidraw.radial_concept_compactor import (
    _display_relation_label,
    _place_shared_parents_near_external_peers,
    _refresh_edge_ports,
    _stacked_branch_rows,
    compact_concept_map_layout,
)
from evo_diagram.agentic_system.render_engine.tldraw.converter import (
    InstantiationToTldrawConverter,
)
from evo_diagram.agentic_system.render_engine.tldraw.validator import (
    validate_tldraw_manifest,
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


def test_default_typography_has_a_compact_hierarchy():
    layout = _minimal_layout()
    layout["lane:title"].pop("fontSize", None)

    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
    ).convert()
    title = next(
        element
        for element in manifest["elements"]
        if element.get("type") == "text" and element.get("text") == "Marketing"
    )
    node = next(
        element
        for element in manifest["elements"]
        if element.get("type") == "text" and element.get("text") == "Author"
    )

    assert (title["fontSize"], title["fontStyle"], title["lineHeight"]) == (
        18,
        1,
        1.2,
    )
    assert (node["fontSize"], node["fontStyle"], node["lineHeight"]) == (
        18,
        0,
        1.2,
    )
    assert node["strokeColor"] == "#1F2937"


def test_bound_text_honors_top_level_node_typography():
    layout = _minimal_layout()
    layout["a"]["fontSize"] = 16
    layout["a"]["fontFamily"] = 1

    manifest = InstantiationToExcalidrawConverter(layout_instantiation=layout).convert()
    node_id = manifest["_meta"]["id_map"]["a"]
    label = next(
        element
        for element in manifest["elements"]
        if element.get("type") == "text" and element.get("containerId") == node_id
    )

    assert label["fontSize"] == 16
    assert label["fontFamily"] == 1


def test_edge_label_defaults_to_compact_helvetica_and_preserves_overrides():
    assert _normalize_label_payload("depends on") == {
        "text": "depends on",
        "fontSize": 13,
        "fontFamily": 2,
        "strokeColor": "#374151",
        "textAlign": "center",
    }
    explicit = _normalize_label_payload({
        "text": "custom",
        "fontSize": 18,
        "fontFamily": 1,
    })
    assert explicit is not None
    assert explicit["fontSize"] == 18
    assert explicit["fontFamily"] == 1


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


def test_rebuild_excalidraw_arrows_replaces_stale_geometry_and_mapping():
    converter = InstantiationToExcalidrawConverter(layout_instantiation=_minimal_layout())
    manifest = add_excalidraw_arrows_to_manifest(converter.convert(), _minimal_structure())
    original_arrow = next(
        element for element in manifest["elements"] if element["type"] == "arrow"
    )
    original_arrow["strokeColor"] = "#1971c2"
    target_id = manifest["_meta"]["id_map"]["b"]
    target = next(element for element in manifest["elements"] if element["id"] == target_id)
    target["x"] += 240

    rebuilt = rebuild_excalidraw_arrows(manifest, _minimal_structure())

    arrows = [element for element in rebuilt["elements"] if element["type"] == "arrow"]
    assert len(arrows) == 1
    assert arrows[0]["strokeColor"] == "#1971c2"
    assert arrows[0]["points"] != original_arrow["points"]
    assert rebuilt["_meta"]["id_map"]["e1"] == arrows[0]["id"]


def test_architecture_ports_use_layers_and_sidebar_semantics():
    source = {"x": 100, "y": 100, "props": {"w": 300, "h": 80}}
    lower = {"x": 900, "y": 300, "props": {"w": 300, "h": 80}}
    sidebar = {"x": 1600, "y": 300, "props": {"w": 300, "h": 80}}
    group_ids = {"source": "layer_a", "lower": "layer_b", "side": "cross"}

    assert _architecture_port_hint(
        "source", "lower", source, lower, group_ids, {"cross"}
    ) == {"start": "bottom", "end": "top"}
    assert _architecture_port_hint(
        "source", "side", source, sidebar, group_ids, {"cross"}
    ) == {"start": "right", "end": "left"}


def test_visibility_router_avoids_multiple_nodes_in_one_corridor():
    original = [
        {"x": 540.0, "y": 500.0},
        {"x": 346.0, "y": 500.0},
        {"x": 346.0, "y": 1190.0},
    ]
    obstacles = [
        (287.5, 690.0, 285.0, 80.0),
        (178.0, 930.0, 244.0, 60.0),
    ]

    routed = _avoid_node_intersections(original, obstacles)
    routed_points = [(point["x"], point["y"]) for point in routed]

    assert routed != original
    assert _path_is_clear(routed_points, obstacles)
    # The shorter old route reversed the source port. A safe detour needs
    # an extra bend to leave that port before turning around the obstacles.
    assert len(routed) <= 7
    assert routed[1]["x"] < routed[0]["x"]
    assert routed[1]["y"] == routed[0]["y"]
    assert routed[-2]["x"] == routed[-1]["x"]
    assert routed[-2]["y"] < routed[-1]["y"]


def test_visibility_router_keeps_clearance_from_nearby_node():
    original = [
        {"x": 0.0, "y": 55.0},
        {"x": 300.0, "y": 55.0},
    ]
    obstacles = [(80.0, 0.0, 140.0, 52.0)]

    routed = _avoid_node_intersections(original, obstacles)
    routed_points = [(point["x"], point["y"]) for point in routed]
    expanded = [(68.0, -12.0, 164.0, 76.0)]

    assert routed != original
    assert _path_is_clear(routed_points, expanded)
    assert len(routed) <= 6


def test_router_keeps_visible_gap_from_unrelated_card_border():
    from evo_diagram.agentic_system.verification_stage.checks.collision_detection import check_edge_node_clearance

    structure = {
        "chart_type": "flowchart",
        "nodes": [{"id": key, "label": key} for key in ("source", "target", "unrelated")],
        "edges": [{"id": "flow", "source": "source", "target": "target", "label": "supplies"}],
    }
    layout = {
        "source": {"type": "rectangle", "x": 0, "y": 0, "w": 100, "h": 100},
        "target": {"type": "rectangle", "x": 500, "y": 0, "w": 100, "h": 100},
        "unrelated": {"type": "rectangle", "x": 220, "y": 50, "w": 120, "h": 60},
        "flow": {"type": "arrow", "start": {"elementId": "source", "side": "right"},
                 "end": {"elementId": "target", "side": "left"}},
    }
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout, structure_instantiation=structure,
    ).convert()
    rendered = add_excalidraw_arrows_to_manifest(manifest, structure)
    assert not check_edge_node_clearance(rendered)
    arrow = next(element for element in rendered["elements"] if element["type"] == "arrow")
    points = [(arrow["x"] + x, arrow["y"] + y) for x, y in arrow["points"]]
    assert _path_is_clear(points, [(214, 44, 132, 72)])


def test_local_obstacle_detour_preserves_target_approach_direction():
    original = [
        {"x": 240.0, "y": 60.0},
        {"x": 240.0, "y": 160.0},
        {"x": 80.0, "y": 160.0},
        {"x": 80.0, "y": 280.0},
    ]
    obstacles = [(20.0, 120.0, 120.0, 80.0)]
    routed = _avoid_node_intersections(original, obstacles)
    points = [(point["x"], point["y"]) for point in routed]

    assert _path_is_clear(points, obstacles)
    assert points[-2][0] == points[-1][0]
    assert points[-2][1] < points[-1][1]
    assert points[1][0] == points[0][0]
    assert points[1][1] > points[0][1]


def test_port_pair_selection_changes_only_blocked_authored_route():
    source = {"x": 540.0, "y": 470.0, "w": 220.0, "h": 60.0}
    target = {"x": 214.0, "y": 1190.0, "w": 232.0, "h": 60.0}
    obstacles = [
        (287.5, 690.0, 285.0, 80.0),
        (178.0, 930.0, 244.0, 60.0),
        (562.0, 870.0, 196.0, 60.0),
    ]

    assert _prefer_clear_port_pair(
        "left", "top", source, target, obstacles
    ) != ("left", "top")
    assert _prefer_clear_port_pair(
        "bottom", "top", source, target, []
    ) == ("bottom", "top")


def test_port_pair_selection_rejects_route_through_its_endpoints():
    source = {"x": 646.0, "y": 134.0, "w": 184.0, "h": 52.0}
    target = {"x": 646.0, "y": 334.0, "w": 160.0, "h": 52.0}
    invalid = [(646.0, 160.0), (726.0, 160.0), (726.0, 360.0), (806.0, 360.0)]
    tangent = [(738.0, 186.0), (738.0, 334.0), (726.0, 334.0)]
    valid = [(738.0, 186.0), (738.0, 304.0), (726.0, 304.0), (726.0, 334.0)]

    assert not _path_avoids_endpoint_interiors(invalid, source, target)
    assert not _path_avoids_endpoint_interiors(tangent, source, target)
    assert _path_avoids_endpoint_interiors(valid, source, target)
    assert _prefer_clear_port_pair(
        "left", "right", source, target, []
    ) == ("bottom", "top")


def test_visibility_detour_cannot_reverse_final_approach_to_avoid_crossing(monkeypatch):
    import evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder as arrow_module

    original = [
        {"x": 100.0, "y": 0.0}, {"x": 100.0, "y": 50.0},
        {"x": 0.0, "y": 50.0}, {"x": 0.0, "y": 100.0},
    ]
    crossing = {
        "id": "foreign", "type": "arrow", "x": 50.0, "y": 25.0,
        "points": [[0.0, 0.0], [0.0, 50.0]], "opacity": 100,
    }
    # A visibility path may overshoot its end lead. Compressing the collinear
    # lead then approaches the top face from inside the target instead.
    monkeypatch.setattr(
        arrow_module, "_orthogonal_visibility_route",
        lambda *args, **kwargs: [(100.0, 24.0), (100.0, 150.0), (0.0, 150.0), (0.0, 76.0)],
    )
    routed = _avoid_node_intersections(original, [], existing_arrows=[crossing])
    assert routed[-2]["y"] < routed[-1]["y"]
    assert _path_avoids_endpoint_interiors(
        [(point["x"], point["y"]) for point in routed],
        {"x": 60.0, "y": -50.0, "w": 80.0, "h": 50.0},
        {"x": -40.0, "y": 100.0, "w": 80.0, "h": 50.0},
    )


def test_blocked_header_can_route_through_other_faces_without_crossing_children():
    from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import compute_waypoints

    source = {"x": 64.0, "y": 520.0, "w": 182.0, "h": 32.0}
    target = {"x": 180.0, "y": 780.0, "w": 168.0, "h": 52.0}
    obstacles = [(58.0, 558.0, 180.0, 64.0), (290.0, 558.0, 180.0, 64.0), (174.0, 666.0, 180.0, 64.0)]
    start, end = _prefer_clear_port_pair("bottom", "top", source, target, obstacles)
    authored, _, _ = compute_waypoints(start, end, source, target, port_spacing=0.0)
    routed = _avoid_node_intersections(authored, obstacles)
    points = [(point["x"], point["y"]) for point in routed]
    assert _path_is_clear(points, obstacles)
    assert _path_avoids_endpoint_interiors(points, source, target)


def test_concept_map_compactor_scores_candidates_and_preserves_bound_text():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "Artificial Intelligence", "class": "core_concept"},
            {"id": "foundation", "label": "Foundation", "class": "branch_anchor"},
            {"id": "systems", "label": "Systems", "class": "branch_anchor"},
            {"id": "uses", "label": "Uses", "class": "branch_anchor"},
            {"id": "risks", "label": "Risks", "class": "branch_anchor"},
            {"id": "leaf", "label": "Machine Learning", "class": "theory_concept"},
        ],
        "edges": [
            {"id": "e1", "source": "core", "target": "foundation"},
            {"id": "e2", "source": "core", "target": "systems"},
            {"id": "e3", "source": "core", "target": "uses"},
            {"id": "e4", "source": "core", "target": "risks"},
            {"id": "e5", "source": "foundation", "target": "leaf"},
        ],
    }
    layout = {
        "core": {"type": "ellipse", "x": 20, "y": 20, "w": 180, "h": 60, "label": {"text": "Artificial Intelligence"}},
        "foundation": {"type": "ellipse", "x": 260, "y": 20, "w": 140, "h": 50, "label": {"text": "Foundation"}},
        "systems": {"type": "ellipse", "x": 260, "y": 100, "w": 170, "h": 50, "label": {"text": "Systems"}},
        "uses": {"type": "ellipse", "x": 460, "y": 20, "w": 170, "h": 50, "label": {"text": "Uses"}},
        "risks": {"type": "ellipse", "x": 460, "y": 100, "w": 170, "h": 50, "label": {"text": "Risks"}},
        "leaf": {"type": "rectangle", "x": 20, "y": 180, "w": 160, "h": 50, "label": {"text": "Machine Learning"}},
        "e1": {"start": {"elementId": "core", "side": "left"}, "end": {"elementId": "foundation", "side": "right"}},
        "e2": {"start": {"elementId": "core", "side": "left"}, "end": {"elementId": "systems", "side": "right"}},
        "e3": {"start": {"elementId": "core", "side": "right"}, "end": {"elementId": "uses", "side": "left"}},
        "e4": {"start": {"elementId": "core", "side": "right"}, "end": {"elementId": "risks", "side": "left"}},
        "e5": {"start": {"elementId": "foundation", "side": "left"}, "end": {"elementId": "leaf", "side": "right"}},
    }
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    compacted = compact_concept_map_layout(manifest, structure)
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}
    core = elements[id_map["core"]]
    foundation = elements[id_map["foundation"]]
    systems = elements[id_map["systems"]]
    leaf = elements[id_map["leaf"]]

    selection = compacted["_meta"]["concept_layout_selection"]
    assert selection["strategy"] in {"compact_radial", "layered_lanes", "stacked_bands", "panel_grid"}
    assert set(selection["scores"]) == {"compact_radial", "layered_lanes", "stacked_bands", "panel_grid"}
    assert selection["scores"][selection["strategy"]]["node_overlaps"] == 0
    positions = {
        (shape["x"], shape["y"])
        for shape in (core, foundation, systems, leaf)
    }
    assert len(positions) == 4
    assert compacted["_meta"]["edge_data"]["e5"]["routing"] == "elbowed"
    assert all(
        elements[id_map[node_id]]["type"] == "rectangle"
        and elements[id_map[node_id]]["roundness"] == {"type": 3}
        for node_id in ("core", "foundation", "systems", "uses", "risks", "leaf")
    )
    assert core["backgroundColor"] == ("transparent" if selection["strategy"] == "panel_grid" else "#202124")
    assert compacted["_meta"]["edge_data"]["e1"]["opacity"] == 0
    label = next(element for element in compacted["elements"] if element.get("containerId") == leaf["id"])
    assert label["x"] == leaf["x"] + (leaf["width"] - label["width"]) / 2


def test_concept_map_compactor_sizes_cards_for_final_text_not_old_layout():
    labels = {
        "root": "Operating Model",
        "left": "Inputs",
        "right": "Knowledge",
        "short": "Input",
        "wide": "跨语言知识表示与关系推理",
    }
    structure = {
        "chart_type": "concept_map",
        "nodes": [{"id": node_id, "label": label} for node_id, label in labels.items()],
        "edges": [
            {"id": "left_group", "source": "root", "target": "left"},
            {"id": "right_group", "source": "root", "target": "right"},
            {"id": "input", "source": "left", "target": "short"},
            {"id": "knowledge", "source": "right", "target": "wide"},
        ],
    }
    layout = {
        node_id: {
            "type": "rectangle", "x": index * 500, "y": 40,
            "w": 480, "h": 80, "label": {"text": label, "fontSize": 32},
        }
        for index, (node_id, label) in enumerate(labels.items())
    }
    layout.update({
        edge["id"]: {
            "start": {"elementId": edge["source"], "side": "bottom"},
            "end": {"elementId": edge["target"], "side": "top"},
        }
        for edge in structure["edges"]
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout, structure_instantiation=structure,
    ).convert()
    compacted = compact_concept_map_layout(manifest, structure)
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}
    assert elements[id_map["short"]]["width"] <= 176
    for node_id in ("short", "wide"):
        shape = elements[id_map[node_id]]
        label = next(element for element in elements.values() if element.get("containerId") == shape["id"])
        assert label["fontSize"] == 16
        assert shape["width"] >= label["width"] + 24
        assert shape["height"] >= label["height"] + 16


def test_concept_map_compactor_keeps_cross_linked_leaf_in_structural_branch():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "Artificial Intelligence", "class": "core_concept"},
            {"id": "theory", "label": "AI Theory", "class": "branch_anchor"},
            {"id": "infra", "label": "AI Infrastructure", "class": "branch_anchor"},
            {"id": "apps", "label": "AI Applications", "class": "branch_anchor"},
            {"id": "ethics", "label": "Impact and Ethics", "class": "branch_anchor"},
            {"id": "technology", "label": "Technologies"},
            {"id": "concern", "label": "Ethical Concerns"},
            {"id": "privacy", "label": "Privacy"},
        ],
        "edges": [
            {"id": "e1", "source": "core", "target": "theory"},
            {"id": "e2", "source": "core", "target": "infra"},
            {"id": "e3", "source": "core", "target": "apps"},
            {"id": "e4", "source": "core", "target": "ethics"},
            {"id": "e5", "source": "infra", "target": "technology"},
            {"id": "e6", "source": "ethics", "target": "concern"},
            {"id": "e7", "source": "concern", "target": "privacy"},
            {"id": "e8", "source": "technology", "target": "privacy"},
        ],
    }
    layout = {
        node["id"]: {
            "type": "ellipse" if node.get("class") in {"core_concept", "branch_anchor"} else "rectangle",
            "x": 20 + index * 120,
            "y": 20,
            "w": 160,
            "h": 50,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(structure["nodes"])
    }
    layout.update({
        edge["id"]: {
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
        }
        for edge in structure["edges"]
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()

    compacted = compact_concept_map_layout(manifest, structure)
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}
    core = elements[id_map["core"]]
    concern = elements[id_map["concern"]]
    privacy = elements[id_map["privacy"]]

    frame = elements[id_map["ethics:background"]]
    assert frame["x"] <= concern["x"] < concern["x"] + concern["width"] <= frame["x"] + frame["width"]
    assert frame["y"] <= concern["y"] < concern["y"] + concern["height"] <= frame["y"] + frame["height"]
    assert privacy["x"] > concern["x"] or privacy["y"] > concern["y"]
    assert privacy["backgroundColor"] == concern["backgroundColor"]
    assert privacy["strokeColor"] == concern["strokeColor"]


@pytest.mark.parametrize("relation_type,label", [("causal", "improves"), ("association", "is linked to")])
def test_concept_map_compactor_separates_branch_ownership_from_semantic_edges(relation_type, label):
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "Program", "class": "core_concept", "branch_id": None},
            {"id": "design", "label": "Design", "class": "branch_anchor", "branch_id": "design"},
            {"id": "delivery", "label": "Delivery", "class": "branch_anchor", "branch_id": "delivery"},
            {"id": "prototype", "label": "Prototype", "branch_id": "design"},
            {"id": "release", "label": "Release", "branch_id": "delivery"},
            {"id": "adoption", "label": "Adoption", "branch_id": "design"},
        ],
        "edges": [
            {"id": "e1", "source": "core", "target": "design", "relation_type": "hierarchy"},
            {"id": "e2", "source": "core", "target": "delivery", "relation_type": "hierarchy"},
            {"id": "e3", "source": "design", "target": "prototype", "relation_type": "composition"},
            {"id": "e4", "source": "delivery", "target": "release", "relation_type": "composition"},
            {
                "id": "e5",
                "source": "design",
                "target": "adoption",
                "label": label,
                "relation_type": relation_type,
            },
        ],
    }
    layout = {
        node["id"]: {
            "type": "rectangle",
            "x": 20 + index * 120,
            "y": 20,
            "w": 160,
            "h": 50,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(structure["nodes"])
    }
    layout.update({
        edge["id"]: {
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
            **({"label": {"text": edge["label"]}} if edge.get("label") else {}),
        }
        for edge in structure["edges"]
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()

    compacted = compact_concept_map_layout(manifest, structure)
    edge_data = compacted["_meta"]["edge_data"]
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}

    assert edge_data["e3"]["opacity"] < edge_data["e5"]["opacity"]
    assert edge_data["e3"]["_suppressLabel"] is True
    assert edge_data["e5"]["opacity"] > 0
    assert edge_data["e5"]["_suppressLabel"] is False
    assert edge_data["e5"]["label"]["text"] == label
    assert elements[id_map["design"]]["strokeWidth"] > 0
    assert elements[id_map["design"]]["strokeColor"] != "transparent"
    assert elements[id_map["delivery"]]["strokeWidth"] == 0
    assert elements[id_map["adoption"]]["strokeColor"] == elements[id_map["design"]]["meta"]["conceptSectionColor"]
    if relation_type == "causal":
        assert elements[id_map["adoption"]]["y"] > elements[id_map["prototype"]]["y"]


def test_concept_map_compactor_moves_convergent_outcome_to_majority_branch():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "Artificial Intelligence", "class": "core_concept"},
            {"id": "theory", "label": "AI Theory", "class": "branch_anchor"},
            {"id": "infra", "label": "AI Infrastructure", "class": "branch_anchor"},
            {"id": "apps", "label": "AI Applications", "class": "branch_anchor"},
            {"id": "ethics", "label": "Impact and Ethics", "class": "branch_anchor"},
            {"id": "health", "label": "Healthcare", "class": "application_concept"},
            {"id": "finance", "label": "Finance", "class": "application_concept"},
            {"id": "transport", "label": "Transportation", "class": "application_concept"},
            {"id": "outcome", "label": "World", "class": "impact_concept"},
        ],
        "edges": [
            {"id": "e1", "source": "core", "target": "theory"},
            {"id": "e2", "source": "core", "target": "infra"},
            {"id": "e3", "source": "core", "target": "apps"},
            {"id": "e4", "source": "core", "target": "ethics"},
            {"id": "e5", "source": "apps", "target": "health"},
            {"id": "e6", "source": "apps", "target": "finance"},
            {"id": "e7", "source": "apps", "target": "transport"},
            {"id": "e8", "source": "ethics", "target": "outcome"},
            {"id": "e9", "source": "health", "target": "outcome"},
            {"id": "e10", "source": "finance", "target": "outcome"},
            {"id": "e11", "source": "transport", "target": "outcome"},
        ],
    }
    layout = {
        node["id"]: {
            "type": "ellipse" if node.get("class") in {"core_concept", "branch_anchor"} else "rectangle",
            "x": 20 + index * 120,
            "y": 20,
            "w": 160,
            "h": 50,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(structure["nodes"])
    }
    layout.update({
        edge["id"]: {
            "type": "arrow",
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
        }
        for edge in structure["edges"]
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    id_map = manifest["_meta"]["id_map"]
    elements = {element["id"]: element for element in manifest["elements"]}
    elements[id_map["apps"]]["backgroundColor"] = "#d8e6d1"
    elements[id_map["apps"]]["strokeColor"] = "#56765a"
    elements[id_map["ethics"]]["backgroundColor"] = "#f1e4c7"
    elements[id_map["ethics"]]["strokeColor"] = "#8a6a2f"
    elements[id_map["outcome"]]["backgroundColor"] = "#f1e4c7"
    elements[id_map["outcome"]]["strokeColor"] = "#8a6a2f"

    compacted = compact_concept_map_layout(manifest, structure)
    elements = {element["id"]: element for element in compacted["elements"]}
    core = elements[id_map["core"]]
    outcome = elements[id_map["outcome"]]

    assert outcome["backgroundColor"] == elements[id_map["health"]]["backgroundColor"]
    assert outcome["strokeColor"] == elements[id_map["health"]]["strokeColor"]
    assert outcome["strokeColor"] != elements[id_map["ethics"]]["meta"]["conceptSectionColor"]
    edge_data = compacted["_meta"]["edge_data"]
    assert edge_data["e8"]["_layoutCrossBranch"] is True
    assert edge_data["e9"]["_layoutCrossBranch"] is False
    core_color = "transparent" if compacted["_meta"]["concept_layout_selection"]["strategy"] == "panel_grid" else "#202124"
    assert core["backgroundColor"] == core_color
    assert core["strokeColor"] == core_color
    branch_strokes = {
        elements[id_map[node_id]]["meta"]["conceptSectionColor"]
        for node_id in ("theory", "infra", "apps", "ethics")
    }
    assert len(branch_strokes) == 4


@pytest.mark.parametrize("branch_count", [2, 3, 5, 7])
def test_concept_map_compactor_is_topic_agnostic_across_branch_counts(branch_count):
    nodes = [{"id": "root", "label": "Service Delivery System"}]
    edges = []
    for index in range(branch_count):
        branch_id = f"section_{index}"
        leaf_id = f"detail_{index}"
        nodes.extend([
            {"id": branch_id, "label": f"Section {index + 1}"},
            {"id": leaf_id, "label": f"Detail {index + 1}"},
        ])
        edges.extend([
            {"id": f"root_edge_{index}", "source": "root", "target": branch_id},
            {"id": f"detail_edge_{index}", "source": branch_id, "target": leaf_id},
        ])
    structure = {"chart_type": "concept_map", "nodes": nodes, "edges": edges}
    layout = {
        node["id"]: {
            "type": "ellipse",
            "x": 20 + index * 80,
            "y": 20,
            "w": 160,
            "h": 50,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(nodes)
    }
    layout.update({
        edge["id"]: {
            "type": "arrow",
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
        }
        for edge in edges
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()

    compacted = compact_concept_map_layout(manifest, structure)
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}
    root = elements[id_map["root"]]
    def section_color(element):
        return element.get("meta", {}).get(
            "conceptSectionColor",
            element["strokeColor"],
        )
    branch_strokes = [
        section_color(elements[id_map[f"section_{index}"]])
        for index in range(branch_count)
    ]

    assert root["backgroundColor"] == ("transparent" if compacted["_meta"]["concept_layout_selection"]["strategy"] == "panel_grid" else "#202124")
    if compacted["_meta"]["concept_layout_selection"]["strategy"] == "stacked_bands":
        root_text = next(
            element
            for element in compacted["elements"]
            if element.get("containerId") == root["id"]
        )
        assert root["height"] == 52.0
        assert root_text["fontSize"] == 22
    assert all(
        elements[id_map[node["id"]]]["type"] == "rectangle"
        and elements[id_map[node["id"]]]["roundness"] == {"type": 3}
        for node in nodes
    )
    assert len(set(branch_strokes)) == branch_count
    expected_structural_opacity = (
        0
        if compacted["_meta"]["concept_layout_selection"]["strategy"] in {"stacked_bands", "panel_grid"}
        else 58
    )
    assert all(
        compacted["_meta"]["edge_data"][f"root_edge_{index}"]["opacity"]
        == expected_structural_opacity
        for index in range(branch_count)
    )
    for index in range(branch_count):
        assert (
            elements[id_map[f"detail_{index}"]]["strokeColor"]
            == section_color(elements[id_map[f"section_{index}"]])
        )


def test_concept_map_branch_palette_follows_source_order_not_topic_words():
    anchor_ids = ["ethics", "applications", "theory", "infrastructure"]
    nodes = [
        {"id": "root", "label": "Operating Model", "class": "core_concept"},
        *[
            {"id": anchor_id, "label": anchor_id.title(), "class": "branch_anchor"}
            for anchor_id in anchor_ids
        ],
    ]
    edges = [
        {"id": f"e{index}", "source": "root", "target": anchor_id}
        for index, anchor_id in enumerate(anchor_ids)
    ]
    structure = {"chart_type": "concept_map", "nodes": nodes, "edges": edges}
    layout = {
        node["id"]: {
            "type": "ellipse",
            "x": 20 + index * 180,
            "y": 20,
            "w": 160,
            "h": 50,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(nodes)
    }
    layout.update({
        edge["id"]: {
            "type": "arrow",
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
        }
        for edge in edges
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()

    compacted = compact_concept_map_layout(manifest, structure)
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}

    assert [
        elements[id_map[node_id]]["meta"]["conceptSectionColor"]
        for node_id in anchor_ids
    ] == [
        "#9E4F61",
        "#3F7E8C",
        "#56765A",
        "#8A6A2F",
    ]


def test_concept_map_compactor_marks_cross_branch_routes_for_router():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "Artificial Intelligence", "class": "core_concept"},
            {"id": "theory", "label": "AI Theory", "class": "branch_anchor"},
            {"id": "infra", "label": "AI Infrastructure", "class": "branch_anchor"},
            {"id": "apps", "label": "AI Applications", "class": "branch_anchor"},
            {"id": "ethics", "label": "Impact and Ethics", "class": "branch_anchor"},
            {"id": "machine_learning", "label": "Machine Learning"},
            {"id": "technology", "label": "Technologies"},
            {"id": "computers", "label": "Computers"},
            {"id": "data", "label": "Data"},
            {"id": "tasks", "label": "Tasks"},
            {"id": "concern", "label": "Ethical Concerns"},
        ],
        "edges": [
            {"id": "e1", "source": "core", "target": "theory"},
            {"id": "e2", "source": "core", "target": "infra"},
            {"id": "e3", "source": "core", "target": "apps"},
            {"id": "e4", "source": "core", "target": "ethics"},
            {"id": "e5", "source": "theory", "target": "machine_learning"},
            {"id": "e6", "source": "infra", "target": "technology"},
            {"id": "e7", "source": "infra", "target": "computers"},
            {"id": "e8", "source": "infra", "target": "data"},
            {"id": "e9", "source": "infra", "target": "tasks"},
            {"id": "e10", "source": "ethics", "target": "concern"},
            {"id": "e11", "source": "machine_learning", "target": "data", "label": "depends on"},
            {"id": "e12", "source": "technology", "target": "concern", "label": "raises"},
        ],
    }
    layout = {
        node["id"]: {
            "type": "ellipse" if node.get("class") in {"core_concept", "branch_anchor"} else "rectangle",
            "x": 20 + index * 120,
            "y": 20,
            "w": 160,
            "h": 50,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(structure["nodes"])
    }
    layout.update({
        edge["id"]: {
            "type": "arrow",
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
            **(
                {"label": {"text": edge["label"]}}
                if edge.get("label")
                else {}
            ),
        }
        for edge in structure["edges"]
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()

    compacted = compact_concept_map_layout(manifest, structure)
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}
    selection = compacted["_meta"]["concept_layout_selection"]
    assert selection["scores"][selection["strategy"]]["node_overlaps"] == 0
    edge_data = compacted["_meta"]["edge_data"]
    assert edge_data["e6"]["_layoutCrossBranch"] is False
    assert edge_data["e11"]["_layoutCrossBranch"] is True
    assert edge_data["e12"]["_layoutCrossBranch"] is True

    rendered = add_excalidraw_arrows_to_manifest(compacted, structure)
    rendered_elements = {
        element["id"]: element for element in rendered["elements"]
    }
    frames = [
        rendered_elements[render_id]
        for semantic_id, render_id in rendered["_meta"]["id_map"].items()
        if semantic_id.endswith(":background")
    ]
    long_cross_branch = next(
        element
        for element in rendered["elements"]
        if element.get("type") == "arrow"
        and element.get("meta", {}).get("semantic_edge_id") == "e12"
    )
    absolute_xs = [
        float(long_cross_branch["x"]) + float(point[0])
        for point in long_cross_branch["points"]
    ]
    frame_left = min(float(frame["x"]) for frame in frames)
    frame_right = max(
        float(frame["x"]) + float(frame["width"]) for frame in frames
    )

    assert frame_left <= min(absolute_xs) <= max(absolute_xs) <= frame_right
    assert not long_cross_branch.get("boundElements")
    assert rendered["_meta"]["edge_data"]["e12"]["label"]["text"] == "raises"
    assert rendered["_meta"]["edge_data"]["e12"]["_suppressLabel"] is False
    assert any(
        element.get("type") == "text"
        and element.get("meta", {}).get("semantic_arrow_id") == long_cross_branch["id"]
        and element.get("containerId") is None
        and element.get("text") == "raises"
        for element in rendered["elements"]
    )
    adjacent_cross_branch = next(
        element
        for element in rendered["elements"]
        if element.get("type") == "arrow"
        and element.get("meta", {}).get("semantic_edge_id") == "e11"
    )
    assert not adjacent_cross_branch.get("boundElements")


def test_concept_map_explicit_core_fact_does_not_create_an_extra_branch():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "Program", "class": "core_concept", "branch_id": None},
            {"id": "theory", "label": "Theory", "class": "branch_anchor", "branch_id": "theory"},
            {"id": "practice", "label": "Practice", "class": "branch_anchor", "branch_id": "practice"},
            {"id": "model", "label": "Model", "class": "concept", "branch_id": "theory"},
            {"id": "method", "label": "Method", "class": "concept", "branch_id": "theory"},
            {"id": "workshop", "label": "Workshop", "class": "concept", "branch_id": "practice"},
            {"id": "lab", "label": "Lab", "class": "concept", "branch_id": "practice"},
        ],
        "edges": [
            {"id": "edge:core2theory", "source": "core", "target": "theory", "label": "organized into", "relation_type": "hierarchy", "evidence_basis": "structural"},
            {"id": "edge:core2practice", "source": "core", "target": "practice", "label": "organized into", "relation_type": "hierarchy", "evidence_basis": "structural"},
            {"id": "edge:core2model", "source": "core", "target": "model", "label": "has subtype", "relation_type": "hierarchy", "evidence_basis": "explicit", "evidence": "Model is a Program subtype"},
            {"id": "edge:theory2method", "source": "theory", "target": "method", "label": "has example", "relation_type": "exemplification", "evidence_basis": "explicit", "evidence": "Theory includes Method"},
            {"id": "edge:practice2workshop", "source": "practice", "target": "workshop", "label": "has example", "relation_type": "exemplification", "evidence_basis": "explicit", "evidence": "Practice includes Workshop"},
            {"id": "edge:practice2lab", "source": "practice", "target": "lab", "label": "has example", "relation_type": "exemplification", "evidence_basis": "explicit", "evidence": "Practice includes Lab"},
        ],
    }
    layout = {
        node["id"]: {
            "type": "rectangle",
            "x": 40.0 + index * 180.0,
            "y": 40.0,
            "w": 160.0,
            "h": 52.0,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(structure["nodes"])
    }
    layout.update({
        edge["id"]: {
            "type": "arrow",
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
            "label": {"text": edge["label"]},
        }
        for edge in structure["edges"]
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    manifest["_meta"]["edge_data"]["edge:core2model"]["_suppressLabel"] = True

    compacted = compact_concept_map_layout(manifest, structure)
    id_map = compacted["_meta"]["id_map"]
    elements = {element["id"]: element for element in compacted["elements"]}

    assert elements[id_map["model"]]["backgroundColor"] == elements[id_map["method"]]["backgroundColor"]
    assert elements[id_map["model"]]["backgroundColor"] != elements[id_map["theory"]]["backgroundColor"]
    core_fact = compacted["_meta"]["edge_data"]["edge:core2model"]
    assert core_fact["_suppressLabel"] is False
    assert core_fact["label"]["text"] == "has subtype"
    assert "model:background" not in compacted["_meta"]["id_map"]


def test_concept_map_connector_grammar_distinguishes_association_and_dependency():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "System", "class": "core_concept", "branch_id": None},
            {"id": "left", "label": "Left", "class": "branch_anchor", "branch_id": "left"},
            {"id": "right", "label": "Right", "class": "branch_anchor", "branch_id": "right"},
            {"id": "source", "label": "Source", "class": "concept", "branch_id": "left"},
            {"id": "related", "label": "Related", "class": "concept", "branch_id": "right"},
            {"id": "required", "label": "Required", "class": "concept", "branch_id": "right"},
        ],
        "edges": [
            {"id": "edge:core2left", "source": "core", "target": "left", "label": "organized into", "relation_type": "hierarchy", "evidence_basis": "structural", "directionality": "directed"},
            {"id": "edge:core2right", "source": "core", "target": "right", "label": "organized into", "relation_type": "hierarchy", "evidence_basis": "structural", "directionality": "directed"},
            {"id": "edge:source2related", "source": "source", "target": "related", "label": "linked to", "relation_type": "association", "evidence_basis": "explicit", "directionality": "undirected", "evidence": "Source is linked to Related."},
            {"id": "edge:source2required", "source": "source", "target": "required", "label": "depends on", "relation_type": "dependency", "evidence_basis": "explicit", "directionality": "directed", "evidence": "Source depends on Required."},
        ],
    }
    layout = {
        node["id"]: {
            "type": "rectangle",
            "x": 40.0 + index * 180.0,
            "y": 40.0,
            "w": 160.0,
            "h": 52.0,
            "label": {"text": node["label"]},
        }
        for index, node in enumerate(structure["nodes"])
    }
    layout.update({
        edge["id"]: {
            "type": "arrow",
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
            "label": {"text": edge["label"]},
        }
        for edge in structure["edges"]
    })
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()

    compacted = compact_concept_map_layout(manifest, structure)
    rendered = rebuild_excalidraw_arrows(compacted, structure)
    arrows = {
        element.get("meta", {}).get("semantic_edge_id"): element
        for element in rendered["elements"]
        if element.get("type") == "arrow"
    }

    association = arrows["edge:source2related"]
    dependency = arrows["edge:source2required"]
    assert association["strokeStyle"] == "dashed"
    assert association["endArrowhead"] is None
    assert dependency["strokeStyle"] == "dashed"
    assert dependency["endArrowhead"] == "arrow"
    arrow_ids = {arrow["id"] for arrow in arrows.values()}
    assert {
        element["text"]
        for element in rendered["elements"]
        if element.get("type") == "text" and element.get("meta", {}).get("semantic_arrow_id") in arrow_ids
    } == {"linked to", "depends on"}
    assert compacted["_meta"]["edge_data"]["edge:source2required"]["label"]["text"] == "depends on"


def test_stacked_concept_rows_use_causal_edges_not_membership_for_depth():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "core", "label": "System", "class": "core_concept", "branch_id": None},
            {"id": "branch", "label": "Infrastructure", "class": "branch_anchor", "branch_id": "branch"},
            {"id": "technology", "label": "Technology", "class": "concept", "branch_id": "branch"},
            {"id": "metrics", "label": "Metrics", "class": "concept", "branch_id": "branch"},
            {"id": "efficiency", "label": "Efficiency", "class": "concept", "branch_id": "branch"},
        ],
        "edges": [
            {"id": "edge:core2branch", "source": "core", "target": "branch", "label": "organized into", "relation_type": "hierarchy", "evidence_basis": "structural", "directionality": "directed"},
            {"id": "edge:branch2technology", "source": "branch", "target": "technology", "label": "includes", "relation_type": "composition", "evidence_basis": "explicit", "directionality": "directed", "evidence": "Infrastructure includes Technology."},
            {"id": "edge:branch2metrics", "source": "branch", "target": "metrics", "label": "includes", "relation_type": "composition", "evidence_basis": "explicit", "directionality": "directed", "evidence": "Infrastructure includes Metrics."},
            {"id": "edge:metrics2efficiency", "source": "metrics", "target": "efficiency", "label": "are exemplified by", "relation_type": "exemplification", "evidence_basis": "explicit", "directionality": "directed", "evidence": "Metrics such as Efficiency."},
            {"id": "edge:technology2efficiency", "source": "technology", "target": "efficiency", "label": "improves", "relation_type": "causal", "evidence_basis": "explicit", "directionality": "directed", "evidence": "Technology improves Efficiency."},
        ],
    }
    rows = _stacked_branch_rows(
        ["technology", "metrics", "efficiency"],
        structure["edges"],
        anchor_id="branch",
    )

    assert rows == [["technology", "metrics"], ["efficiency"]]
    example_edge = next(
        edge for edge in structure["edges"]
        if edge["id"] == "edge:metrics2efficiency"
    )
    assert _display_relation_label(example_edge, "are exemplified by") == "has example"


def test_concept_ports_require_real_vertical_clearance():
    manifest = {
        "elements": [
            {"id": "source-shape", "type": "rectangle", "x": 40, "y": 100, "width": 220, "height": 48},
            {"id": "overlap-shape", "type": "rectangle", "x": 500, "y": 144, "width": 180, "height": 52},
            {"id": "below-shape", "type": "rectangle", "x": 280, "y": 220, "width": 180, "height": 52},
        ],
        "_meta": {
            "edge_data": {
                "edge:overlap": {},
                "edge:below": {},
            },
        },
    }
    id_map = {
        "source": "source-shape",
        "overlap": "overlap-shape",
        "below": "below-shape",
    }
    edges = [
        {"id": "edge:overlap", "source": "source", "target": "overlap"},
        {"id": "edge:below", "source": "source", "target": "below"},
    ]

    _refresh_edge_ports(
        manifest,
        id_map,
        edges,
        core_id="root",
        ownership={"source": "branch", "overlap": "branch", "below": "branch"},
    )

    edge_data = manifest["_meta"]["edge_data"]
    assert edge_data["edge:overlap"]["start"]["side"] == "right"
    assert edge_data["edge:overlap"]["end"]["side"] == "left"
    assert edge_data["edge:below"]["start"]["side"] == "bottom"
    assert edge_data["edge:below"]["end"]["side"] == "top"


def test_rebuild_arrows_removes_detached_semantic_edge_labels():
    structure = {
        "chart_type": "flowchart",
        "nodes": [
            {"id": "a", "label": "A", "class": "process"},
            {"id": "b", "label": "B", "class": "process"},
        ],
        "edges": [
            {"id": "edge:a2b", "source": "a", "target": "b", "label": "supports"},
        ],
    }
    layout = {
        "a": {"type": "rectangle", "x": 20, "y": 20, "w": 140, "h": 50, "label": {"text": "A"}},
        "b": {"type": "rectangle", "x": 320, "y": 20, "w": 140, "h": 50, "label": {"text": "B"}},
        "edge:a2b": {
            "type": "arrow",
            "start": {"elementId": "a", "side": "right"},
            "end": {"elementId": "b", "side": "left"},
            "label": {"text": "supports"},
        },
    }
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    rendered = add_excalidraw_arrows_to_manifest(manifest, structure)
    rendered["elements"].append({
        "id": "detached-label",
        "type": "text",
        "x": 180,
        "y": 4,
        "width": 70,
        "height": 18,
        "text": "supports",
        "containerId": None,
        "boundElements": [],
        "meta": {"semantic_edge_id": "edge:a2b"},
    })

    rebuilt = rebuild_excalidraw_arrows(rendered, structure)
    semantic_labels = [
        element
        for element in rebuilt["elements"]
        if element.get("type") == "text"
        and element.get("meta", {}).get("semantic_edge_id") == "edge:a2b"
    ]

    assert len(semantic_labels) == 1
    assert semantic_labels[0]["id"] != "detached-label"
    assert semantic_labels[0]["containerId"]
    assert len({element["id"] for element in rebuilt["elements"]}) == len(rebuilt["elements"])


def test_concept_map_independent_sibling_edges_keep_each_predicate():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "a", "label": "Applications"},
            {"id": "b", "label": "Healthcare"},
            {"id": "c", "label": "Finance"},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b", "label": "exemplifies"},
            {"id": "e2", "source": "a", "target": "c", "label": "exemplifies"},
        ],
    }
    layout = {
        "a": {"type": "ellipse", "x": 180, "y": 260, "w": 160, "h": 50, "label": {"text": "Applications"}},
        "b": {"type": "rectangle", "x": 20, "y": 20, "w": 140, "h": 50, "label": {"text": "Healthcare"}},
        "c": {"type": "rectangle", "x": 360, "y": 20, "w": 140, "h": 50, "label": {"text": "Finance"}},
        "e1": {"start": {"elementId": "a", "side": "top"}, "end": {"elementId": "b", "side": "bottom"}, "label": {"text": "exemplifies"}},
        "e2": {"start": {"elementId": "a", "side": "top"}, "end": {"elementId": "c", "side": "bottom"}, "label": {"text": "exemplifies"}},
    }
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    rendered = add_excalidraw_arrows_to_manifest(manifest, structure)
    arrow_ids = {element["id"] for element in rendered["elements"] if element.get("type") == "arrow"}
    labels = [
        element for element in rendered["elements"]
        if element.get("type") == "text" and element.get("meta", {}).get("semantic_arrow_id") in arrow_ids
    ]

    assert [label["text"] for label in labels] == ["exemplifies", "exemplifies"]
    assert {label["meta"]["semantic_arrow_id"] for label in labels} == arrow_ids


def test_concept_map_repeated_core_labels_are_suppressed():
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {
                "id": "core",
                "label": "Artificial Intelligence",
                "class": "core_concept",
            },
            {"id": "theory", "label": "Theory", "class": "branch_anchor"},
            {
                "id": "applications",
                "label": "Applications",
                "class": "branch_anchor",
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "core",
                "target": "theory",
                "label": "organized into",
            },
            {
                "id": "e2",
                "source": "core",
                "target": "applications",
                "label": "organized into",
            },
        ],
    }
    layout = {
        "core": {
            "type": "ellipse",
            "x": 180,
            "y": 20,
            "w": 180,
            "h": 60,
            "label": {"text": "Artificial Intelligence"},
        },
        "theory": {
            "type": "ellipse",
            "x": 20,
            "y": 180,
            "w": 140,
            "h": 50,
            "label": {"text": "Theory"},
        },
        "applications": {
            "type": "ellipse",
            "x": 380,
            "y": 180,
            "w": 160,
            "h": 50,
            "label": {"text": "Applications"},
        },
        "e1": {
            "start": {"elementId": "core", "side": "bottom"},
            "end": {"elementId": "theory", "side": "top"},
            "label": {"text": "organized into"},
        },
        "e2": {
            "start": {"elementId": "core", "side": "bottom"},
            "end": {"elementId": "applications", "side": "top"},
            "label": {"text": "organized into"},
        },
    }
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()

    rendered = add_excalidraw_arrows_to_manifest(manifest, structure)
    arrow_ids = {
        element["id"]
        for element in rendered["elements"]
        if element.get("type") == "arrow"
    }
    labels = [
        element
        for element in rendered["elements"]
        if element.get("type") == "text"
        and element.get("containerId") in arrow_ids
    ]

    assert labels == []


def test_edge_label_repositioner_avoids_node_box():
    nodes = [{"id": "node", "type": "rectangle", "x": 100, "y": 100, "width": 160, "height": 60}]
    generated = [
        {"id": "arrow", "type": "arrow", "x": 0, "y": 0, "points": [[0, 0], [300, 0]]},
        {"id": "label", "type": "text", "containerId": "arrow", "x": 120, "y": 120, "width": 80, "height": 20},
    ]

    _reposition_edge_labels(nodes, generated)

    label = generated[1]
    assert not (
        label["x"] < 264
        and label["x"] + label["width"] > 96
        and label["y"] < 164
        and label["y"] + label["height"] > 96
    )


def test_edge_labels_follow_final_route_inside_group_background():
    nodes = [{"id": "group", "type": "rectangle", "is_group": True,
              "x": 0, "y": 0, "width": 900, "height": 700}]
    generated = [
        {"id": "arrow", "type": "arrow", "elbowed": True,
         "x": 100, "y": 200, "points": [[0, 0], [300, 0]]},
        {"id": "label", "type": "text", "containerId": "arrow", "text": "depends on",
         "fontSize": 13, "x": 700, "y": 550, "width": 80, "height": 20},
    ]
    _reposition_edge_labels(nodes, generated)
    label = generated[1]
    assert abs(label["x"] + label["width"] / 2 - 250) < 1
    assert 160 < label["y"] < 195


def test_edge_label_can_enter_section_but_cannot_straddle_its_border():
    obstacles = [
        {"id": "group", "type": "rectangle", "is_group": True,
         "x": 0, "y": 100, "width": 400, "height": 200, "strokeColor": "#456789"},
        {"id": "title", "type": "rectangle", "x": 0, "y": 20, "width": 320, "height": 68},
    ]
    generated = [
        {"id": "arrow", "type": "arrow", "elbowed": True, "x": 20, "y": 90,
         "points": [[0, 0], [260, 0], [260, 130]]},
        {"id": "label", "type": "text", "containerId": "arrow", "text": "connects",
         "fontSize": 13, "x": 0, "y": 0, "width": 60, "height": 16},
    ]
    _reposition_edge_labels(obstacles, generated)
    label = generated[1]
    assert label["y"] > 104
    assert label["x"] > 280
    assert label["x"] + label["width"] < 396


def test_edge_label_repositioner_avoids_unrelated_arrow_path():
    generated = [
        {"id": "own", "type": "arrow", "x": 0, "y": 0, "points": [[0, 0], [300, 0]]},
        {"id": "other", "type": "arrow", "x": 150, "y": 80, "points": [[0, 0], [0, 100]]},
        {"id": "label", "type": "text", "containerId": "own", "x": 120, "y": 100, "width": 80, "height": 20},
    ]

    _reposition_edge_labels([], generated)

    label = generated[2]
    padded_label = (
        label["x"] - 3,
        label["y"] - 3,
        label["width"] + 6,
        label["height"] + 6,
    )
    assert not _segment_hits_box((150, 80), (150, 180), padded_label)


def test_edge_label_uses_clear_segment_instead_of_distant_empty_space():
    nodes = [{"id": "block", "type": "rectangle", "x": 80, "y": 50, "width": 340, "height": 100}]
    generated = [
        {"id": "own", "type": "arrow", "elbowed": True, "x": 100, "y": 100,
         "points": [[0, 0], [300, 0], [300, 300]]},
        {"id": "label", "type": "text", "containerId": "own", "text": "depends on",
         "fontSize": 13, "x": 200, "y": 75, "width": 80, "height": 16},
    ]
    _reposition_edge_labels(nodes, generated)
    label = generated[-1]
    gap = min(abs(label["x"] - 400), abs(label["x"] + label["width"] - 400))
    assert gap <= 12
    assert 154 <= label["y"] <= 380


def test_long_predicate_wraps_inside_its_corridor_without_losing_words():
    nodes = [{"id": "left", "type": "rectangle", "x": 0, "y": 80, "width": 92, "height": 240}]
    generated = [
        {"id": "own", "type": "arrow", "elbowed": True, "x": 100, "y": 100,
         "points": [[0, 0], [0, 200]]},
        {"id": "foreign", "type": "arrow", "x": 210, "y": 100,
         "points": [[0, 0], [0, 200]]},
        {"id": "predicate", "type": "text", "containerId": "own",
         "text": "can improve outcomes", "fontSize": 14},
    ]
    _reposition_edge_labels(nodes, generated)
    label = generated[-1]
    assert "\n" in label["text"]
    assert label["text"].split() == ["can", "improve", "outcomes"]
    assert label["fontSize"] == 14
    assert label["x"] == pytest.approx(108)
    box = (label["x"] - 3, label["y"] - 3, label["width"] + 6, label["height"] + 6)
    assert not _segment_hits_box((100, 100), (100, 300), box)
    assert not _segment_hits_box((210, 100), (210, 300), box)


def test_visibility_router_prefers_independent_channel_over_crossing():
    original = [
        {"x": 0.0, "y": 50.0},
        {"x": 300.0, "y": 50.0},
    ]
    existing = [
        {
            "id": "vertical",
            "type": "arrow",
            "x": 150.0,
            "y": 30.0,
            "points": [[0.0, 0.0], [0.0, 40.0]],
        },
    ]

    middle = _orthogonal_visibility_route(
        (24.0, 50.0),
        (276.0, 50.0),
        [],
        existing,
        24.0,
    )
    assert middle is not None
    routed_points = _compress_orthogonal_path(
        [(0.0, 50.0), *middle, (300.0, 50.0)]
    )

    assert _path_crossing_count([(0.0, 50.0), (300.0, 50.0)], existing) == 1
    assert _path_crossing_count(routed_points, existing) == 0
    assert len(routed_points) <= 6


def test_generic_router_reroutes_clear_path_that_crosses_existing_arrow():
    original = [
        {"x": 0.0, "y": 50.0},
        {"x": 300.0, "y": 50.0},
    ]
    existing = [
        {
            "id": "vertical",
            "type": "arrow",
            "x": 150.0,
            "y": 30.0,
            "points": [[0.0, 0.0], [0.0, 40.0]],
        },
    ]

    routed = _avoid_node_intersections(
        original,
        [],
        existing_arrows=existing,
    )
    routed_points = [(point["x"], point["y"]) for point in routed]

    assert routed != original
    assert _path_crossing_count(routed_points, existing) == 0
    assert len(routed_points) <= 6


def test_generic_router_ignores_transparent_structural_arrow():
    original = [
        {"x": 0.0, "y": 50.0},
        {"x": 300.0, "y": 50.0},
    ]
    transparent = [
        {
            "id": "hidden-structure",
            "type": "arrow",
            "opacity": 0,
            "x": 150.0,
            "y": 30.0,
            "points": [[0.0, 0.0], [0.0, 40.0]],
        },
    ]

    assert _avoid_node_intersections(
        original,
        [],
        existing_arrows=transparent,
    ) == original
    assert _path_crossing_count(
        [(0.0, 50.0), (300.0, 50.0)],
        transparent,
    ) == 0


def test_architecture_outer_route_avoids_populated_sublayer_crossings():
    source_bbox = {"x": 644.5, "y": 436.0, "w": 217.0, "h": 60.0}
    target_bbox = {"x": 791.5, "y": 788.0, "w": 228.0, "h": 60.0}
    original = [
        {"x": 753.0, "y": 496.0},
        {"x": 753.0, "y": 642.0},
        {"x": 905.5, "y": 642.0},
        {"x": 905.5, "y": 788.0},
    ]
    existing = [
        {
            "id": "upper-horizontal",
            "type": "arrow",
            "x": 487.0,
            "y": 508.0,
            "points": [[0.0, 0.0], [426.0, 0.0]],
        },
        {
            "id": "lower-horizontal",
            "type": "arrow",
            "x": 612.5,
            "y": 707.0,
            "points": [[0.0, 0.0], [300.5, 0.0]],
        },
    ]

    routed, start_side, end_side, _, _ = _prefer_architecture_outer_route(
        original,
        "bottom",
        "top",
        source_bbox,
        target_bbox,
        [],
        existing,
    )
    routed_points = [(point["x"], point["y"]) for point in routed]
    original_points = [(point["x"], point["y"]) for point in original]

    assert _path_crossing_count(original_points, existing) == 2
    assert _path_crossing_count(routed_points, existing) == 0
    assert (start_side, end_side) == ("right", "right")


def test_crosscutting_route_uses_lower_corridor_when_upper_route_is_busy():
    original = [
        {"x": 729.0, "y": 596.0},
        {"x": 729.0, "y": 550.0},
        {"x": 1257.0, "y": 550.0},
        {"x": 1257.0, "y": 596.0},
    ]
    existing = [
        {
            "id": "service-interfaces-to-entities",
            "type": "arrow",
            "x": 487.0,
            "y": 508.0,
            "points": [[0.0, 0.0], [426.0, 0.0], [426.0, 58.0]],
        },
        {
            "id": "service-gateways-to-external",
            "type": "arrow",
            "x": 861.5,
            "y": 466.0,
            "points": [[0.0, 0.0], [188.0, 0.0], [188.0, 352.0], [158.0, 352.0]],
        },
        {
            "id": "entities-to-data-access",
            "type": "arrow",
            "x": 913.0,
            "y": 626.0,
            "points": [[0.0, 0.0], [0.0, 81.0], [-300.5, 81.0], [-300.5, 162.0]],
        },
    ]
    obstacles = [
        (439.5, 788.0, 282.0, 60.0),
        (791.5, 788.0, 228.0, 60.0),
        (1305.5, 788.0, 185.0, 60.0),
    ]

    routed, length = _prefer_crosscutting_lower_corridor_route(
        original,
        "right",
        "left",
        {"x": 479.0, "y": 566.0, "w": 250.0, "h": 60.0},
        {"x": 1257.0, "y": 566.0, "w": 282.0, "h": 60.0},
        obstacles,
        existing,
    )

    routed_points = [(point["x"], point["y"]) for point in routed]
    original_points = [(point["x"], point["y"]) for point in original]
    assert _path_crossing_count(original_points, existing) == 2
    assert _path_crossing_count(routed_points, existing) == 1
    assert routed_points == [
        (729.0, 596.0),
        (751.0, 596.0),
        (751.0, 850.0),
        (1235.0, 850.0),
        (1235.0, 596.0),
        (1257.0, 596.0),
    ]
    assert length == 1036.0


def test_crosscutting_route_separates_parallel_channel_without_new_crossing():
    """A clear but crowded governance edge may move when crossings stay flat."""
    original = [
        {"x": 40.0, "y": 20.0},
        {"x": 40.0, "y": 100.0},
        {"x": 200.0, "y": 100.0},
        {"x": 200.0, "y": 20.0},
    ]
    existing = [
        {
            "id": "parallel-governance-edge",
            "type": "arrow",
            "x": 40.0,
            "y": 94.0,
            "points": [[0.0, 0.0], [160.0, 0.0]],
        },
    ]

    routed, length = _prefer_crosscutting_lower_corridor_route(
        original,
        "right",
        "left",
        {"x": 0.0, "y": 0.0, "w": 40.0, "h": 40.0},
        {"x": 200.0, "y": 0.0, "w": 40.0, "h": 40.0},
        [(80.0, 40.0, 40.0, 20.0)],
        existing,
    )

    assert [(point["x"], point["y"]) for point in routed] == [
        (40.0, 20.0),
        (62.0, 20.0),
        (62.0, 62.0),
        (178.0, 62.0),
        (178.0, 20.0),
        (200.0, 20.0),
    ]
    assert length == 244.0


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


@pytest.mark.parametrize("predicate", [
    "uses", "may depend on availability of resources", "updates result",
])
def test_concept_map_render_keeps_predicate_even_when_prose_filter_would_drop_it(predicate):
    layout = _minimal_layout()
    structure = _minimal_structure()
    structure["chart_type"] = "concept_map"
    structure["nodes"] = [{"id": "a", "label": "Process"}, {"id": "b", "label": "Result"}]
    structure["edges"][0]["label"] = predicate
    layout["a"]["label"] = {"text": "Process"}
    layout["b"]["label"] = {"text": "Result"}
    layout["e1"]["label"] = {"text": predicate}
    manifest = InstantiationToExcalidrawConverter(layout_instantiation=layout).convert()
    rendered = add_excalidraw_arrows_to_manifest(manifest, structure)
    predicates = [element["text"] for element in rendered["elements"]
                  if element.get("type") == "text" and (element.get("meta") or {}).get("semantic_edge_id")]
    assert predicates == [predicate]


def test_excalidraw_arrow_adder_distributes_shared_source_ports():
    layout = _minimal_layout()
    layout["c"] = {
        "type": "rectangle",
        "strokeColor": "#1971c2",
        "backgroundColor": "#a5d8ff",
        "label": {"text": "Review"},
        "x": 500,
        "y": 400,
        "w": 160,
        "h": 60,
    }
    layout["e2"] = {
        "strokeColor": "#e03131",
        "routing": "elbowed",
        "start": {"elementId": "a", "side": "bottom"},
        "end": {"elementId": "c", "side": "top"},
        "endArrowhead": "arrow",
    }
    structure = _minimal_structure()
    structure["nodes"].append({"id": "c", "label": "Review"})
    structure["edges"].append({"id": "e2", "from": "a", "to": "c"})

    manifest = InstantiationToExcalidrawConverter(layout_instantiation=layout).convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, structure)
    arrows = [element for element in manifest["elements"] if element["type"] == "arrow"]

    assert len(arrows) == 2
    starts = sorted((arrow["x"] + arrow["points"][0][0]) for arrow in arrows)
    assert starts[0] < starts[1]


def test_excalidraw_arrow_adder_orders_same_row_fanout_without_crossing():
    layout = {
        "source": {
            "type": "ellipse", "x": 500, "y": 100, "w": 200, "h": 70,
            "label": {"text": "Infrastructure"},
        },
        "far": {
            "type": "rectangle", "x": 20, "y": 400, "w": 140, "h": 60,
            "label": {"text": "Data"},
        },
        "near": {
            "type": "rectangle", "x": 280, "y": 400, "w": 140, "h": 60,
            "label": {"text": "Computers"},
        },
        "e_near": {
            "start": {"elementId": "source", "side": "left"},
            "end": {"elementId": "near", "side": "top"},
        },
        "e_far": {
            "start": {"elementId": "source", "side": "left"},
            "end": {"elementId": "far", "side": "top"},
        },
    }
    structure = {
        "chart_type": "concept_map",
        "nodes": [
            {"id": "source", "label": "Infrastructure"},
            {"id": "far", "label": "Data"},
            {"id": "near", "label": "Computers"},
        ],
        "edges": [
            {"id": "e_near", "source": "source", "target": "near"},
            {"id": "e_far", "source": "source", "target": "far"},
        ],
    }

    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    rendered = add_excalidraw_arrows_to_manifest(manifest, structure)
    arrows = [element for element in rendered["elements"] if element.get("type") == "arrow"]

    assert detect_crossings(arrows) == []


def test_excalidraw_arrow_adder_routes_generic_flowchart_crossing():
    layout = {
        "intake": {
            "type": "rectangle", "x": 20, "y": 220, "w": 160, "h": 60,
            "label": {"text": "Request Intake"},
        },
        "delivery": {
            "type": "rectangle", "x": 820, "y": 220, "w": 160, "h": 60,
            "label": {"text": "Delivery"},
        },
        "review": {
            "type": "rectangle", "x": 320, "y": 120, "w": 160, "h": 60,
            "label": {"text": "Review"},
        },
        "archive": {
            "type": "rectangle", "x": 320, "y": 320, "w": 160, "h": 60,
            "label": {"text": "Archive"},
        },
        "delivery_path": {
            "start": {"elementId": "intake", "side": "right"},
            "end": {"elementId": "delivery", "side": "left"},
        },
        "audit_path": {
            "start": {"elementId": "review", "side": "bottom"},
            "end": {"elementId": "archive", "side": "top"},
        },
    }
    structure = {
        "chart_type": "flowchart",
        "nodes": [
            {"id": "intake", "label": "Request Intake"},
            {"id": "delivery", "label": "Delivery"},
            {"id": "review", "label": "Review"},
            {"id": "archive", "label": "Archive"},
        ],
        "edges": [
            {"id": "delivery_path", "source": "intake", "target": "delivery"},
            {"id": "audit_path", "source": "review", "target": "archive"},
        ],
    }

    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    rendered = add_excalidraw_arrows_to_manifest(manifest, structure)
    arrows = [
        element
        for element in rendered["elements"]
        if element.get("type") == "arrow"
    ]
    shapes = [
        element
        for element in rendered["elements"]
        if element.get("type") == "rectangle"
    ]

    assert detect_crossings(arrows) == []
    assert any(len(arrow.get("points", [])) > 2 for arrow in arrows)
    assert all(shape.get("roundness") == {"type": 3} for shape in shapes)
    assert all(shape.get("roughness") == 0 for shape in shapes)
    assert all(shape.get("backgroundColor") == "#F8FAFC" for shape in shapes)
    assert all(arrow.get("roughness") == 0 for arrow in arrows)

    delivery_arrow = next(
        arrow
        for arrow in arrows
        if arrow.get("meta", {}).get("semantic_edge_id") == "delivery_path"
    )
    points = [
        (
            float(delivery_arrow["x"]) + float(point[0]),
            float(delivery_arrow["y"]) + float(point[1]),
        )
        for point in delivery_arrow["points"]
    ]
    detour_spans = [
        abs(end[0] - start[0])
        for start, end in zip(points, points[1:])
        if abs(start[1] - 250.0) > 1e-6
        and abs(start[1] - end[1]) <= 1e-6
    ]
    assert max(detour_spans) <= 220.0


def test_excalidraw_arrow_adder_routes_around_intermediate_node():
    """An orthogonal edge must not pass through a third node on its route."""
    layout = _minimal_layout()
    layout["b"]["y"] = 520
    layout["c"] = {
        "type": "rectangle",
        "strokeColor": "#1971c2",
        "backgroundColor": "#a5d8ff",
        "label": {"text": "Review"},
        "x": 200,
        "y": 320,
        "w": 160,
        "h": 60,
    }

    manifest = InstantiationToExcalidrawConverter(layout_instantiation=layout).convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, _minimal_structure())
    arrow = next(element for element in manifest["elements"] if element["type"] == "arrow")
    absolute_points = [
        (arrow["x"] + point[0], arrow["y"] + point[1])
        for point in arrow["points"]
    ]
    middle_box = (200.0, 320.0, 160.0, 60.0)

    assert len(absolute_points) > 2
    assert all(
        not _segment_hits_box(start, end, middle_box)
        for start, end in zip(absolute_points, absolute_points[1:])
    )


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


def test_edge_label_filter_keeps_short_branch_labels_swallowed_by_node_labels():
    """"no" is a substring of "Notify user" — decision branches must survive.

    The reverse-direction paraphrase test (node label CONTAINS edge label) used
    a bare substring match, so a diamond routinely lost one of its two branch
    labels. ``_STOP_LABELS`` deliberately does not list yes/no.
    """
    node_labels = {"d_check": "Lamp works?", "n_notify": "Notify user"}
    assert _should_drop_edge_label("no", "d_check", "n_notify", node_labels) is None
    assert (
        _should_drop_edge_label("yes", "d_check", "n_yesterday", {"n_yesterday": "Yesterday report"})
        is None
    )


def test_edge_label_filter_still_drops_substantial_paraphrases():
    """The length floor must not disarm the filter for real paraphrases."""
    assert _should_drop_edge_label(
        "notify", "d_check", "n_notify", {"n_notify": "Notify user"}
    ) == "paraphrases target node 'Notify user'"
    # Forward direction (edge label contains node label) is untouched.
    assert _should_drop_edge_label(
        "submit form", "a", "b", {"a": "Author", "b": "Submit"}
    ) == "paraphrases target node 'Submit'"


# ----------------------------------------------------------------------------
# Arrow / edge-label z-order — index must continue the converter's numbering
# ----------------------------------------------------------------------------


def test_arrow_and_edge_label_indices_sort_above_every_shape():
    """Arrows inherited ``index: "a0"`` from ``_excalidraw_defaults``.

    ``"a0" < "a00000"`` lexicographically, so every arrow and edge label sorted
    BEFORE all shapes and was painted underneath the opaque nodes whenever
    ``render.fix_zorder`` was off.
    """
    layout = deepcopy(_minimal_layout())
    layout["e1"]["label"] = {"text": "batch upload"}   # survives the label filter

    manifest = InstantiationToExcalidrawConverter(layout_instantiation=layout).convert()
    shape_indices = [e["index"] for e in manifest["elements"]]
    manifest = add_excalidraw_arrows_to_manifest(manifest, _minimal_structure())

    arrows = [e for e in manifest["elements"] if e["type"] == "arrow"]
    labels = [
        e for e in manifest["elements"]
        if e["type"] == "text" and e.get("containerId") in {a["id"] for a in arrows}
    ]

    assert len(arrows) == 1
    assert len(labels) == 1
    for elem in arrows + labels:
        assert elem["index"] != "a0"
        assert len(elem["index"]) == len("a00000")
        assert elem["index"] > max(shape_indices), (
            f"{elem['type']} index {elem['index']!r} must sort after every shape"
        )


# ----------------------------------------------------------------------------
# TLDraw converter — standalone text is a text shape, icons read real geometry
# ----------------------------------------------------------------------------


def test_tldraw_standalone_text_renders_as_text_shape_not_stroked_rectangle():
    """``geo_type="text"`` fell through ``normalize_shape`` to "rectangle",
    so every group title was drawn as a box around its own label."""
    layout = {
        "g_lane:background": {"type": "rectangle", "x": 0, "y": 0, "w": 400, "h": 140},
        "g_lane:title": {
            "type": "text",
            "label": {"text": "Ingest Lane"},
            "x": 16, "y": 12, "w": 180, "h": 28,
        },
        "n_a": {"type": "rectangle", "label": {"text": "A"}, "x": 40, "y": 60, "w": 120, "h": 60},
    }

    manifest = InstantiationToTldrawConverter(layout_instantiation=layout).convert()
    store = manifest["document"]["store"]
    title = store["shape:g_lane:title"]

    assert title["type"] == "text"
    assert "geo" not in title["props"]
    assert title["props"]["text"] == "Ingest Lane"
    assert title["props"]["textAlign"] == "middle"
    assert "align" not in title["props"]
    assert title["props"]["w"] == 180
    assert title["props"]["autoSize"] is True
    # Height is not part of the tldraw text schema; group fitting reads it here.
    assert title["meta"]["h"] == 28
    # Real geometry still goes down the geo path.
    assert store["shape:g_lane:background"]["type"] == "geo"
    assert store["shape:g_lane:background"]["props"]["geo"] == "rectangle"
    # The snapshot must stay loadable: tldraw rejects unknown shape props.
    report = validate_tldraw_manifest(manifest_data=manifest)
    assert report["is_valid"], report["errors"]


@pytest.mark.parametrize("alignment,expected", [
    ({"textAlign": "left"}, "start"),
    ({"props": {"textAlign": "end"}}, "end"),
    ({"props": {"align": "start"}}, "start"),
])
def test_tldraw_text_alignment_matches_declared_snapshot_schema(alignment, expected):
    layout = {"title": {"type": "text", "label": {"text": "Title"},
                        "x": 0, "y": 0, "w": 180, "h": 28, **alignment}}
    manifest = InstantiationToTldrawConverter(layout_instantiation=layout).convert()
    props = manifest["document"]["store"]["shape:title"]["props"]
    # Snapshot text v2 already includes the SDK's align -> textAlign migration.
    assert manifest["document"]["schema"]["sequences"]["com.tldraw.shape.text"] == 2
    assert props["textAlign"] == expected
    assert "align" not in props


def test_tldraw_icon_centers_on_top_level_node_height(monkeypatch):
    """``props.get("h", 61.7)`` ignored the top-level geometry contract, so a
    140px-tall node centered its icon against a phantom 61.7px height."""
    monkeypatch.setattr(
        "evo_diagram.agentic_system.render_engine.tldraw.converter.require_icon_svg_path",
        lambda *args, **kwargs: "cloud.svg",
    )
    layout = {
        "n_api": {"type": "rectangle", "label": {"text": "API"}, "x": 0, "y": 0, "w": 300, "h": 140},
        "n_api:icon": {"type": "icon", "props": {"icon": "cloud"}},
    }

    store = InstantiationToTldrawConverter(layout_instantiation=layout).convert()["document"]["store"]
    icon = store["shape:n_api:icon"]

    # icon_dim = clamp(max(48, 140*0.6), 140*0.8) = 84  (was 48 against 61.7)
    assert icon["props"]["w"] == 84
    assert icon["props"]["h"] == 84
    # Vertically centered in the real 140px box (was y=6.85, i.e. glued to top).
    assert icon["y"] == (140 - 84) / 2
    assert icon["x"] == 16


def test_tldraw_arrow_adder_tolerates_relations_without_id_or_dict():
    """``collect_relations`` does not guarantee ``id`` — and the group path can
    even yield plain strings. Hard subscripting raised KeyError / TypeError."""
    manifest = InstantiationToTldrawConverter(
        layout_instantiation=_minimal_layout(),
        structure_instantiation=_minimal_structure(),
    ).convert()
    store = manifest["document"]["store"]
    # Force the structure fallback path (no layout-derived edge_data).
    store["document:document"]["meta"]["edge_data"] = {}

    structure = {
        "chart_type": "flowchart",
        "nodes": [{"id": "a", "label": "Author"}, {"id": "b", "label": "Submit"}],
        "groups": [
            {
                "id": "lane",
                "members": ["a", "b"],
                "relations": ["a->b", {"source": "a", "target": "b"}],
            }
        ],
    }

    new_items = add_arrows(store, structure)
    arrows = [
        item for item in new_items.values()
        if item.get("typeName") == "shape" and item.get("type") == "arrow"
    ]

    assert len(arrows) == 1


def test_excalidraw_group_fitter_accepts_nested_member_objects():
    """Persisted Structure payloads carry ``{"kind": "node", "node": {...}}``
    members; using them as dict keys raised ``unhashable type: 'dict'``."""
    manifest = {
        "type": "excalidraw/clipboard",
        "_meta": {"id_map": {"g_lane": "bg", "n1": "child"}},
        "elements": [
            {"id": "bg", "type": "rectangle", "x": 0, "y": 0, "width": 80, "height": 60},
            {"id": "child", "type": "rectangle", "x": 100, "y": 70, "width": 80, "height": 40},
        ],
    }
    structure = {
        "groups": [
            {"id": "g_lane", "members": [{"kind": "node", "node": {"id": "n1"}}]}
        ]
    }

    fitted = fit_excalidraw_groups_to_children(manifest, structure, padding=10)
    bg = next(elem for elem in fitted["elements"] if elem["id"] == "bg")

    assert bg["x"] == 90
    assert bg["y"] == 60
    assert bg["width"] == 100
    assert bg["height"] == 60


def test_edge_label_filter_keeps_structural_concept_map_relation():
    reason = _should_drop_edge_label(
        "includes",
        "a",
        "b",
        {"a": "Theory", "b": "Machine Learning"},
        preserve_structural_labels=True,
    )
    assert reason is None


def test_layout_relation_recovers_missing_semantic_label():
    relations = [{"id": "edge:a2b", "source": "a", "target": "b"}]
    structure = {
        "chart_type": "concept_map",
        "edges": [{
            "id": "edge:a2b",
            "source": "a",
            "target": "b",
            "label": "includes",
        }],
    }
    merged = _merge_semantic_edge_labels(relations, structure)
    assert merged[0]["label"] == "includes"


@pytest.mark.parametrize("chart_type", ["flowchart", "architecture"])
def test_semantic_predicates_do_not_create_unrequested_display_labels(chart_type):
    relations = [{"id": "edge:a2b", "source": "a", "target": "b"}]
    structure = {"chart_type": chart_type, "edges": [
        {**relations[0], "relation": "followed by"},
    ]}
    assert "label" not in _merge_semantic_edge_labels(relations, structure)[0]
    structure["edges"][0]["label"] = "Yes"
    assert _merge_semantic_edge_labels(relations, structure)[0]["label"] == "Yes"


def test_concept_map_keeps_relation_predicate_as_display_label():
    relations = [{"id": "edge:a2b", "source": "a", "target": "b"}]
    structure = {"chart_type": "concept_map", "edges": [
        {**relations[0], "relation": "supports"},
    ]}
    assert _merge_semantic_edge_labels(relations, structure)[0]["label"] == "supports"


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


def test_audit_manifest_flags_duplicate_element_ids():
    """The converter's id_map can collapse two semantic ids onto one render
    id; Excalidraw then silently keeps a single element. The audit must
    surface that as a targeted, per-element issue (the old dict-key check
    in ``audit_layout_instantiation`` could never fire: dict keys are
    unique by construction)."""
    manifest = {
        "elements": [
            {"type": "arrow", "id": "arrow:e1", "meta": {"semantic_edge_id": "e1"}},
            {"type": "rectangle", "id": "dup", "x": 0, "y": 0, "width": 10, "height": 10},
            {"type": "rectangle", "id": "dup", "x": 50, "y": 0, "width": 10, "height": 10},
        ]
    }

    report = audit_excalidraw_manifest(manifest, _minimal_structure())

    assert any("more than once" in w for w in report.warnings), report.warnings
    dup_issues = [i for i in report.issues if i.category == "duplicate_id"]
    assert [i.element_id for i in dup_issues] == ["dup"]
    assert "2 times" in dup_issues[0].message


def test_audit_manifest_unique_ids_produce_no_duplicate_warning():
    manifest = {
        "elements": [
            {"type": "arrow", "id": "arrow:e1", "meta": {"semantic_edge_id": "e1"}},
            {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 10, "height": 10},
            {"type": "rectangle", "id": "b", "x": 50, "y": 0, "width": 10, "height": 10},
        ]
    }

    report = audit_excalidraw_manifest(manifest, _minimal_structure())

    assert not any(i.category == "duplicate_id" for i in report.issues)
    assert not any("more than once" in w for w in report.warnings)


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


@pytest.mark.parametrize("constraint", [None, "local_parent", "different_children", "larger_slot"])
def test_shared_parent_order_shortens_external_link_without_reversing_facts(constraint):
    from copy import deepcopy

    nodes = {
        "producer": {"id": "producer", "type": "rectangle", "x": 200, "y": 100, "width": 160, "height": 52},
        "category": {"id": "category", "type": "rectangle", "x": 200, "y": 220, "width": 160, "height": 52},
        "result_a": {"id": "result_a", "type": "rectangle", "x": 0, "y": 340, "width": 160, "height": 52},
        "result_b": {"id": "result_b", "type": "rectangle", "x": 400, "y": 340, "width": 160, "height": 52},
        "external": {"id": "external", "type": "rectangle", "x": 200, "y": 580, "width": 160, "height": 52},
    }
    children = {node_id: set() for node_id in nodes if node_id != "external"}
    parents = {node_id: set() for node_id in children}
    edges = []
    for source in ("producer", "category"):
        for target in ("result_a", "result_b"):
            children[source].add(target)
            parents[target].add(source)
            edges.append({"source": source, "target": target, "evidence_basis": "explicit"})
    edges.append({"source": "producer", "target": "external", "relation_type": "association", "evidence_basis": "explicit"})
    if constraint == "local_parent":
        parents["producer"].add("category")
    elif constraint == "different_children":
        children["category"].remove("result_b")
    elif constraint == "larger_slot":
        nodes["category"]["height"] = 76
    before_nodes, before_edges = deepcopy(nodes), deepcopy(edges)
    ownership = {node_id: "local" for node_id in nodes}
    ownership["external"] = "other"
    _place_shared_parents_near_external_peers(
        nodes, {node_id: node_id for node_id in nodes}, children, parents, edges, ownership,
    )
    assert edges == before_edges
    if constraint is not None:
        assert nodes == before_nodes
    else:
        assert nodes["producer"]["y"] == 220
        assert nodes["category"]["y"] == 100
        assert abs(nodes["producer"]["y"] - nodes["external"]["y"]) < abs(before_nodes["producer"]["y"] - nodes["external"]["y"])
        bounds = lambda items: sorted((e["x"], e["y"], e["width"], e["height"]) for e in items.values())
        assert bounds(nodes) == bounds(before_nodes)
        assert nodes["producer"]["y"] + nodes["producer"]["height"] < nodes["result_a"]["y"]


def test_shared_parent_detours_do_not_cross_their_own_target_nodes():
    from evo_diagram.agentic_system.render_engine.excalidraw import arrow_adder

    nodes = {
        "category": (1104, 168), "producer": (1104, 276),
        "first": (824, 384), "second": (1384, 384),
        "peer": (1104, 564), "task": (824, 276),
    }
    pairs = [("category", "first"), ("category", "second"),
             ("producer", "first"), ("producer", "second"), ("producer", "peer")]
    structure = {
        "chart_type": "concept_map",
        "nodes": [{"id": key, "label": key, "class": "concept"} for key in nodes],
        "edges": [{"id": f"edge:{source}2{target}", "source": source, "target": target,
                   "label": "supports", "relation_type": "causal", "evidence_basis": "explicit"}
                  for source, target in pairs],
        "groups": [],
    }
    layout = {key: {"type": "rectangle", "x": x, "y": y, "w": 216, "h": 52}
              for key, (x, y) in nodes.items()}
    for source, target in pairs:
        layout[f"edge:{source}2{target}"] = {
            "type": "arrow", "start": {"elementId": source, "side": "bottom"},
            "end": {"elementId": target, "side": "top"},
        }
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout, structure_instantiation=structure,
    ).convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, structure)
    by_id = {element["id"]: element for element in manifest["elements"]}
    id_map = manifest["_meta"]["id_map"]
    arrows = [element for element in manifest["elements"] if element["type"] == "arrow"]
    assert {element["meta"]["semantic_edge_id"] for element in arrows} == {edge["id"] for edge in structure["edges"]}
    for arrow in arrows:
        source = arrow_adder.shape_bbox(by_id[id_map[arrow["meta"]["source"]]])
        target = arrow_adder.shape_bbox(by_id[id_map[arrow["meta"]["target"]]])
        points = [(arrow["x"] + x, arrow["y"] + y) for x, y in arrow["points"]]
        assert arrow_adder._path_avoids_endpoint_interiors(points, source, target)


def test_short_elbow_label_avoids_incoming_connector():
    nodes = [
        {'id': 'design', 'type': 'rectangle', 'x': 64, 'y': 328, 'width': 160, 'height': 52},
        {'id': 'development', 'type': 'rectangle', 'x': 320, 'y': 328, 'width': 160, 'height': 52},
    ]
    generated = [
        {'id': 'own', 'type': 'arrow', 'elbowed': True, 'x': 224, 'y': 354,
         'points': [[0, 0], [48, 0], [48, 16], [96, 16]]},
        {'id': 'incoming', 'type': 'arrow', 'x': 532, 'y': 220,
         'points': [[0, 0], [0, 78], [-284, 78], [-284, 118], [-308, 118]]},
        {'id': 'predicate', 'type': 'text', 'containerId': 'own', 'text': 'guides', 'fontSize': 14},
    ]
    _reposition_edge_labels(nodes, generated)
    label = generated[-1]
    box = (label['x'] - 3, label['y'] - 3, label['width'] + 6, label['height'] + 6)
    assert not _segment_hits_box((248, 298), (248, 338), box)
    assert label['text'] == 'guides'
    assert label['x'] >= 228
    assert label['x'] + label['width'] <= 316


@pytest.mark.parametrize('invisible_state', [{'opacity': 0}, {'isDeleted': True}])
def test_hidden_arrows_do_not_displace_visible_edge_labels(invisible_state):
    generated = [
        {'id': 'own', 'type': 'arrow', 'x': 100, 'y': 100, 'points': [[0, 0], [300, 0]]},
        {'id': 'hidden', 'type': 'arrow', 'x': 250, 'y': 40, 'points': [[0, 0], [0, 100]], **invisible_state},
        {'id': 'label', 'type': 'text', 'containerId': 'own', 'text': 'guides', 'fontSize': 14},
    ]
    _reposition_edge_labels([], generated)
    label = generated[-1]
    assert label['x'] + label['width'] / 2 == pytest.approx(250)


@pytest.mark.parametrize("chart_type", ["flowchart", "concept_map"])
def test_feedback_cycle_separates_incoming_and_outgoing_ports(chart_type):
    structure = {"chart_type": chart_type, "nodes": [
        {"id": name, "label": name} for name in ("center", "above", "below")
    ], "edges": [
        {"id": "edge:center2above", "source": "center", "target": "above"},
        {"id": "edge:below2center", "source": "below", "target": "center"},
    ]}
    layout = {
        "center": {"type": "rectangle", "x": 20, "y": 200, "w": 140, "h": 100, "label": {"text": "Center"}},
        "above": {"type": "rectangle", "x": 400, "y": 20, "w": 140, "h": 100, "label": {"text": "Above"}},
        "below": {"type": "rectangle", "x": 400, "y": 400, "w": 140, "h": 100, "label": {"text": "Below"}},
        "edge:center2above": {"start": {"elementId": "center", "side": "right"}, "end": {"elementId": "above", "side": "left"}},
        "edge:below2center": {"start": {"elementId": "below", "side": "left"}, "end": {"elementId": "center", "side": "right"}},
    }
    manifest = InstantiationToExcalidrawConverter(layout_instantiation=layout, structure_instantiation=structure).convert()
    out = add_excalidraw_arrows_to_manifest(manifest, structure)
    edges = {e["meta"]["semantic_edge_id"]: e for e in out["elements"] if e.get("type") == "arrow"}
    outgoing, incoming = edges["edge:center2above"], edges["edge:below2center"]
    start_y = outgoing["y"] + outgoing["points"][0][1]
    end_y = incoming["y"] + incoming["points"][-1][1]
    assert abs(start_y - end_y) >= 12
