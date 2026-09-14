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
    assert by_id["gov-frame"]["y"] == by_id["main-frame"]["y"]
    assert by_id["gov-node"]["y"] > by_id["gov-frame"]["y"]
