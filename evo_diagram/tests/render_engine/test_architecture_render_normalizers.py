from __future__ import annotations

from evo_diagram.agentic_system.render_engine.excalidraw.architecture_style_normalizer import (
    normalize_architecture_style,
)
from evo_diagram.agentic_system.render_engine.excalidraw.layered_layout_compactor import (
    compact_architecture_layout,
)


def test_architecture_style_normalizer_uses_formal_typography_and_connectors():
    manifest = {
        "elements": [
            {"id": "title-layer", "type": "text", "fontFamily": 5},
            {
                "id": "frame-layer",
                "type": "rectangle",
                "backgroundColor": "transparent",
                "strokeStyle": "dashed",
                "strokeWidth": 2,
            },
            {"id": "shape", "type": "rectangle", "roundness": None},
            {"id": "edge", "type": "arrow", "roughness": 1, "label": {"fontFamily": 1}},
        ]
    }
    out = normalize_architecture_style(manifest, {"chart_type": "architecture"})
    assert out is not manifest
    assert out["elements"][0]["fontFamily"] == 2
    assert out["elements"][0]["fontStyle"] == 1
    assert out["elements"][0]["fontSize"] == 18
    assert out["elements"][0]["lineHeight"] == 1.15
    assert out["elements"][1]["backgroundColor"] == "#F8FAFC"
    assert out["elements"][1]["strokeStyle"] == "solid"
    assert out["elements"][1]["strokeWidth"] == 1
    assert out["elements"][1]["roundness"] == {"type": 3}
    assert out["elements"][2]["roundness"] == {"type": 3}
    assert out["elements"][3]["roughness"] == 0
    assert out["elements"][3]["label"]["fontFamily"] == 2
    assert manifest["elements"][0]["fontFamily"] == 5


def test_architecture_style_normalizer_leaves_other_chart_types_unchanged():
    manifest = {"elements": [{"id": "label", "type": "text", "fontFamily": 5}]}
    out = normalize_architecture_style(manifest, {"chart_type": "flowchart"})
    assert out is manifest
    assert out["elements"][0]["fontFamily"] == 5


def test_architecture_style_normalizer_uses_boxes_for_component_nodes():
    manifest = {
        "elements": [
            {"id": "data-source", "type": "ellipse", "roundness": None},
        ],
        "_meta": {"id_map": {"source": "data-source"}},
    }
    structure = {
        "chart_type": "architecture",
        "nodes": [
            {"id": "source", "label": "Data Sources", "class": "persistent store"},
        ],
    }

    out = normalize_architecture_style(manifest, structure)

    assert out["elements"][0]["type"] == "rectangle"
    assert out["elements"][0]["roundness"] == {"type": 3}


def test_compactor_leaves_non_architecture_manifest_unchanged():
    manifest = {"elements": [{"id": "shape", "type": "rectangle", "x": 10, "y": 20}]}
    out = compact_architecture_layout(manifest, {"chart_type": "flowchart", "groups": []})
    assert out is manifest


def test_compactor_keeps_governance_class_group_in_sidebar():
    manifest = {
        "elements": [
            {"id": "main-frame", "type": "rectangle", "x": 0, "y": 0, "width": 800, "height": 160},
            {"id": "main-node", "type": "rectangle", "x": 100, "y": 50, "width": 120, "height": 50},
            {"id": "gov-frame", "type": "rectangle", "x": 0, "y": 0, "width": 240, "height": 160},
            {"id": "gov-node", "type": "rectangle", "x": 120, "y": 50, "width": 120, "height": 50},
        ],
        "_meta": {
            "id_map": {
                "group_main:background": "main-frame",
                "main": "main-node",
                "group_enterprise_governance:background": "gov-frame",
                "governance": "gov-node",
            }
        },
    }
    structure = {
        "chart_type": "architecture",
        "groups": [
            {"id": "group_main", "class": "architecture_layer", "members": ["main"]},
            {
                "id": "group_enterprise_governance",
                "class": "cross_cutting_zone",
                "members": ["governance"],
            },
        ],
    }

    out = compact_architecture_layout(manifest, structure)
    by_id = {element["id"]: element for element in out["elements"]}
    assert by_id["gov-frame"]["x"] > by_id["main-frame"]["x"]
    assert by_id["gov-frame"]["width"] == 360
    assert by_id["gov-frame"]["y"] == by_id["main-frame"]["y"]
    assert by_id["gov-node"]["y"] > by_id["gov-frame"]["y"]


def test_compactor_accepts_space_separated_class_and_node_group_ids():
    manifest = {
        "elements": [
            {"id": "frame", "type": "rectangle", "x": 100, "y": 100, "width": 900, "height": 300},
            {"id": "node-a", "type": "rectangle", "x": 180, "y": 190, "width": 160, "height": 80},
            {"id": "node-b", "type": "rectangle", "x": 700, "y": 190, "width": 160, "height": 80},
        ],
        "_meta": {"id_map": {"g_layer:background": "frame", "n_a": "node-a", "n_b": "node-b"}},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [{"id": "g_layer", "class": "architecture layer"}],
        "nodes": [
            {"id": "n_a", "group_id": "g_layer"},
            {"id": "n_b", "group_id": "g_layer"},
        ],
    }

    out = compact_architecture_layout(manifest, structure)

    by_id = {element["id"]: element for element in out["elements"]}
    assert by_id["frame"]["width"] == 980
    assert by_id["node-b"]["x"] - (
        by_id["node-a"]["x"] + by_id["node-a"]["width"]
    ) == 68


def test_compactor_accepts_colon_group_ids_with_members_and_no_class():
    manifest = {
        "elements": [
            {"id": "group:layer:background", "type": "rectangle", "x": 80, "y": 140, "width": 2200, "height": 300},
            {"id": "n_a", "type": "rectangle", "x": 180, "y": 220, "width": 400, "height": 80},
        ],
        "_meta": {"id_map": {"group:layer": "group:layer:background", "n_a": "n_a"}},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [{"id": "group:layer", "members": ["n_a"]}],
        "nodes": [{"id": "n_a"}],
    }

    out = compact_architecture_layout(manifest, structure)

    frame = next(element for element in out["elements"] if element["id"] == "group:layer:background")
    assert frame["width"] == 980
    assert frame["height"] == 194


def test_style_normalizer_detects_direct_group_frame_and_suffix_title_ids():
    manifest = {
        "elements": [
            {"id": "group:layer:background", "type": "rectangle", "strokeStyle": "dashed"},
            {"id": "group:layer:title", "type": "text", "fontFamily": 5},
        ],
        "_meta": {"id_map": {"group:layer": "group:layer:background"}},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [{"id": "group:layer", "members": []}],
    }

    out = normalize_architecture_style(manifest, structure)

    assert out["elements"][0]["strokeStyle"] == "solid"
    assert out["elements"][0]["backgroundColor"] == "#F8FAFC"
    assert out["elements"][1]["fontFamily"] == 2
    assert out["elements"][1]["fontStyle"] == 1


def test_style_normalizer_uses_role_palette_and_connector_hierarchy():
    manifest = {
        "elements": [
            {"id": "frame-main", "type": "rectangle"},
            {"id": "frame-business", "type": "rectangle"},
            {"id": "frame-gov", "type": "rectangle"},
            {"id": "ui", "type": "rectangle"},
            {"id": "service", "type": "rectangle"},
            {"id": "security", "type": "rectangle"},
            {
                "id": "edge-main",
                "type": "arrow",
                "points": [[0, 0], [0, 80]],
                "meta": {"source": "n_ui", "target": "n_service"},
            },
            {
                "id": "edge-support",
                "type": "arrow",
                "points": [[0, 0], [80, 0], [80, 40]],
                "meta": {"source": "n_ui", "target": "n_security"},
            },
        ],
        "appState": {"viewBackgroundColor": "#FAF8F5"},
        "_meta": {
            "id_map": {
                "group_main:background": "frame-main",
                "group_business:background": "frame-business",
                "group_governance:background": "frame-gov",
                "n_ui": "ui",
                "n_service": "service",
                "n_security": "security",
            }
        },
    }
    structure = {
        "chart_type": "architecture",
        "groups": [
            {"id": "group_main", "label": "Presentation", "members": ["n_ui"]},
            {"id": "group_business", "label": "Business", "members": ["n_service"]},
            {"id": "group_governance", "label": "Governance", "members": ["n_security"]},
        ],
        "nodes": [
            {"id": "n_ui", "class": "presentation component"},
            {"id": "n_service", "class": "business service"},
            {"id": "n_security", "class": "cross-cutting security"},
        ],
    }

    out = normalize_architecture_style(manifest, structure)
    by_id = {element["id"]: element for element in out["elements"]}

    assert out["appState"]["viewBackgroundColor"] == "#FFFFFF"
    assert by_id["frame-main"]["opacity"] == 72
    assert by_id["frame-business"]["opacity"] == 72
    assert by_id["frame-gov"]["opacity"] == 72
    assert (by_id["ui"]["backgroundColor"], by_id["ui"]["strokeColor"]) == (
        "#DAE8FC",
        "#6C8EBF",
    )
    assert by_id["ui"]["strokeWidth"] == 1.5
    assert (by_id["service"]["backgroundColor"], by_id["service"]["strokeColor"]) == (
        "#D5E8D4",
        "#82B366",
    )
    assert by_id["security"]["backgroundColor"] == "#F8CECC"
    assert by_id["edge-main"]["strokeColor"] == "#4B5563"
    assert by_id["edge-main"]["strokeStyle"] == "solid"
    assert by_id["edge-main"]["strokeWidth"] == 1.5
    assert by_id["edge-main"]["endArrowhead"] == "triangle"
    assert by_id["edge-main"]["elbowed"] is False
    assert by_id["edge-support"]["strokeColor"] == "#B85450"
    assert by_id["edge-support"]["strokeStyle"] == "dashed"
    assert by_id["edge-support"]["strokeWidth"] == 1.5
    assert by_id["edge-support"]["opacity"] == 78
    assert by_id["edge-support"]["elbowed"] is True


def test_compactor_shrinks_oversized_nodes_to_drawio_size_band():
    manifest = {
        "elements": [
            {"id": "frame", "type": "rectangle", "x": 0, "y": 0, "width": 1200, "height": 260},
            {
                "id": "node",
                "type": "rectangle",
                "x": 100,
                "y": 100,
                "width": 520,
                "height": 120,
                "boundElements": [{"id": "node-text", "type": "text"}],
            },
            {
                "id": "node-text",
                "type": "text",
                "x": 130,
                "y": 140,
                "width": 460,
                "height": 30,
                "fontSize": 20,
                "text": "Operational Management",
                "originalText": "Operational Management",
                "containerId": "node",
            },
        ],
        "_meta": {"id_map": {"group:main": "frame", "n_ops": "node"}},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [{"id": "group:main", "members": ["n_ops"]}],
        "nodes": [{"id": "n_ops"}],
    }

    out = compact_architecture_layout(manifest, structure)
    by_id = {element["id"]: element for element in out["elements"]}

    assert 180 <= by_id["node"]["width"] <= 300
    assert 60 <= by_id["node"]["height"] <= 84
    assert by_id["node-text"]["fontSize"] == 18
    assert by_id["node-text"]["width"] < by_id["node"]["width"]
    assert by_id["node-text"]["x"] > by_id["node"]["x"]


def test_compactor_repositions_directly_named_group_title():
    manifest = {
        "elements": [
            {"id": "group:main:background", "type": "rectangle", "x": 100, "y": 200, "width": 900, "height": 260},
            {"id": "group:main:title", "type": "text", "x": 1800, "y": 900, "width": 200, "height": 24},
            {"id": "node", "type": "rectangle", "x": 240, "y": 290, "width": 200, "height": 60},
        ],
        "_meta": {"id_map": {"group:main": "group:main:background", "n": "node"}},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [{"id": "group:main", "members": ["n"]}],
        "nodes": [{"id": "n"}],
    }

    out = compact_architecture_layout(manifest, structure)
    by_id = {element["id"]: element for element in out["elements"]}

    assert by_id["group:main:title"]["x"] == by_id["group:main:background"]["x"] + 30
    assert by_id["group:main:title"]["y"] == by_id["group:main:background"]["y"] + 20


def test_compactor_merges_model_rows_without_room_for_connectors():
    manifest = {
        "elements": [
            {"id": "frame", "type": "rectangle", "x": 0, "y": 0, "width": 1200, "height": 400},
            {"id": "n_a", "type": "rectangle", "x": 100, "y": 100, "width": 300, "height": 80},
            {"id": "n_b", "type": "rectangle", "x": 500, "y": 210, "width": 300, "height": 80},
        ],
        "_meta": {"id_map": {"g": "frame", "n_a": "n_a", "n_b": "n_b"}},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [{"id": "g", "members": ["n_a", "n_b"]}],
        "nodes": [{"id": "n_a"}, {"id": "n_b"}],
    }

    out = compact_architecture_layout(manifest, structure)
    by_id = {element["id"]: element for element in out["elements"]}

    assert by_id["n_a"]["y"] == by_id["n_b"]["y"]
    assert by_id["frame"]["height"] == 194


def test_compactor_orders_fan_in_row_by_upstream_centers():
    manifest = {
        "elements": [
            {"id": "upper-frame", "type": "rectangle", "x": 0, "y": 0, "width": 1200, "height": 200},
            {"id": "lower-frame", "type": "rectangle", "x": 0, "y": 300, "width": 1200, "height": 200},
            {"id": "source-left", "type": "rectangle", "x": 100, "y": 70, "width": 200, "height": 60},
            {"id": "source-right", "type": "rectangle", "x": 900, "y": 70, "width": 200, "height": 60},
            {"id": "hub", "type": "rectangle", "x": 100, "y": 370, "width": 200, "height": 60},
            {"id": "target-mid", "type": "rectangle", "x": 500, "y": 370, "width": 200, "height": 60},
            {"id": "target-right", "type": "rectangle", "x": 900, "y": 370, "width": 200, "height": 60},
        ],
        "_meta": {"id_map": {
            "upper": "upper-frame", "lower": "lower-frame",
            "s_left": "source-left", "s_right": "source-right",
            "hub": "hub", "t_mid": "target-mid", "t_right": "target-right",
        }},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [
            {"id": "upper", "members": ["s_left", "s_right"]},
            {"id": "lower", "members": ["hub", "t_mid", "t_right"]},
        ],
        "nodes": [{"id": node_id} for node_id in ("s_left", "s_right", "hub", "t_mid", "t_right")],
        "edges": [
            {"source": "s_right", "target": "hub"},
            {"source": "s_left", "target": "hub"},
            {"source": "hub", "target": "t_mid"},
            {"source": "s_right", "target": "t_right"},
        ],
    }

    out = compact_architecture_layout(manifest, structure)
    by_id = {element["id"]: element for element in out["elements"]}

    assert by_id["target-mid"]["x"] < by_id["hub"]["x"] < by_id["target-right"]["x"]


def test_compactor_preserves_row_order_when_fan_in_is_same_layer():
    manifest = {
        "elements": [
            {"id": "upper-frame", "type": "rectangle", "x": 0, "y": 0, "width": 1000, "height": 180},
            {"id": "lower-frame", "type": "rectangle", "x": 0, "y": 260, "width": 1000, "height": 180},
            {"id": "source", "type": "rectangle", "x": 400, "y": 60, "width": 180, "height": 60},
            {"id": "workflow", "type": "rectangle", "x": 100, "y": 320, "width": 180, "height": 60},
            {"id": "component", "type": "rectangle", "x": 400, "y": 320, "width": 180, "height": 60},
            {"id": "entity", "type": "rectangle", "x": 700, "y": 320, "width": 180, "height": 60},
        ],
        "_meta": {"id_map": {
            "upper": "upper-frame", "lower": "lower-frame", "source": "source",
            "workflow": "workflow", "component": "component", "entity": "entity",
        }},
    }
    structure = {
        "chart_type": "architecture",
        "groups": [
            {"id": "upper", "members": ["source"]},
            {"id": "lower", "members": ["workflow", "component", "entity"]},
        ],
        "nodes": [{"id": node_id} for node_id in ("source", "workflow", "component", "entity")],
        "edges": [
            {"source": "source", "target": "component"},
            {"source": "workflow", "target": "component"},
            {"source": "component", "target": "entity"},
        ],
    }

    out = compact_architecture_layout(manifest, structure)
    by_id = {element["id"]: element for element in out["elements"]}

    assert by_id["workflow"]["x"] < by_id["component"]["x"] < by_id["entity"]["x"]


def test_horizontal_architecture_keeps_authored_columns():
    elements = []
    id_map = {}
    groups = []
    for index in range(3):
        x = index * 350
        group, node = f"group_{index}", f"node_{index}"
        elements.extend([
            {"id": group, "type": "rectangle", "x": x, "y": 40, "width": 300, "height": 200},
            {"id": node, "type": "rectangle", "x": x + 50, "y": 120, "width": 160, "height": 60},
        ])
        id_map[group + ":background"] = group
        id_map[node] = node
        groups.append({"id": group, "members": [node]})
    manifest = {"elements": elements, "_meta": {"id_map": id_map}}
    out = compact_architecture_layout(manifest, {"chart_type": "architecture", "groups": groups})
    assert out == manifest


def test_architecture_preserves_explicit_blue_violet_palette():
    manifest = {"elements": [{"id": "service", "type": "rectangle"}],
                "_meta": {"id_map": {"api": "service"}}}
    palette = {"backgroundColor": "#ede9fe", "strokeColor": "#7c3aed"}
    out = normalize_architecture_style(manifest, {
        "chart_type": "architecture", "nodes": [{"id": "api", "class": "service"}],
    }, layout_instantiation={"api": palette})
    assert all(out["elements"][0][key] == value for key, value in palette.items())
    assert "backgroundColor" not in manifest["elements"][0]


def test_architecture_spacing_reserves_visible_arrow_around_a_long_label():
    manifest = {'elements': [
        {'id': 'frame', 'type': 'rectangle', 'x': 100, 'y': 100, 'width': 800, 'height': 220},
        {'id': 'a', 'type': 'rectangle', 'x': 150, 'y': 180, 'width': 180, 'height': 60},
        {'id': 'b', 'type': 'rectangle', 'x': 500, 'y': 180, 'width': 180, 'height': 60},
    ], '_meta': {'id_map': {'group_layer:background': 'frame', 'a': 'a', 'b': 'b'}}}
    structure = {'chart_type': 'architecture', 'nodes': [{'id': 'a'}, {'id': 'b'}],
                 'groups': [{'id': 'group_layer', 'members': ['a', 'b']}],
                 'edges': [{'source': 'a', 'target': 'b', 'label': 'Validate token'}]}
    result = compact_architecture_layout(manifest, structure)
    elements = {e['id']: e for e in result['elements']}
    gap = elements['b']['x'] - elements['a']['x'] - elements['a']['width']
    assert gap > 120
