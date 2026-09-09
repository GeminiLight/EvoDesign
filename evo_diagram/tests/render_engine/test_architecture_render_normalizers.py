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
            {"id": "label", "type": "text", "fontFamily": 5},
            {"id": "edge", "type": "arrow", "roughness": 1, "label": {"fontFamily": 1}},
        ]
    }
    out = normalize_architecture_style(manifest, {"chart_type": "architecture"})
    assert out is not manifest
    assert out["elements"][0]["fontFamily"] == 2
    assert out["elements"][1]["roughness"] == 0
    assert out["elements"][1]["label"]["fontFamily"] == 2
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
