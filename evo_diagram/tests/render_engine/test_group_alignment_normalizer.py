# -*- coding: utf-8 -*-
"""Tests for preserving layout-stage group alignment intent."""

from __future__ import annotations

from evo_diagram.agentic_system.render_engine.excalidraw.group_alignment_normalizer import (
    preserve_group_alignment_intent,
)


def _rect(elem_id: str, x: float, y: float, w: float, h: float) -> dict:
    return {
        "id": elem_id,
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "boundElements": [],
    }


def _manifest(*elements: dict) -> dict:
    return {
        "type": "excalidraw/clipboard",
        "elements": list(elements),
        "_meta": {
            "id_map": {
                "layer_a:background": "bg_a",
                "layer_a:title": "title_a",
                "layer_b:background": "bg_b",
                "layer_b:title": "title_b",
                "side_zone:background": "bg_side",
                "side_zone:title": "title_side",
            }
        },
    }


def test_equal_width_layout_intent_is_restored_after_one_group_expands():
    layout = {
        "layer_a:background": {"x": 100, "y": 100, "w": 500, "h": 120},
        "layer_a:title": {"type": "text", "x": 120, "y": 115, "w": 120, "h": 24},
        "layer_b:background": {"x": 100, "y": 280, "w": 500, "h": 120},
        "layer_b:title": {"type": "text", "x": 120, "y": 295, "w": 120, "h": 24},
        "side_zone:background": {"x": 760, "y": 100, "w": 180, "h": 300},
        "side_zone:title": {"type": "text", "x": 780, "y": 115, "w": 120, "h": 24},
    }
    manifest = _manifest(
        _rect("bg_a", 100, 100, 560, 120),
        _rect("bg_b", 100, 280, 500, 120),
        _rect("bg_side", 760, 100, 180, 300),
    )

    out = preserve_group_alignment_intent(manifest, layout)
    by_id = {e["id"]: e for e in out["elements"]}

    assert by_id["bg_a"]["width"] == 560
    assert by_id["bg_b"]["width"] == 560
    assert by_id["bg_side"]["width"] == 180


def test_equal_height_layout_intent_is_restored_for_horizontal_row():
    layout = {
        "layer_a:background": {"x": 100, "y": 100, "w": 220, "h": 120},
        "layer_a:title": {"type": "text", "x": 120, "y": 115, "w": 120, "h": 24},
        "layer_b:background": {"x": 380, "y": 100, "w": 240, "h": 120},
        "layer_b:title": {"type": "text", "x": 400, "y": 115, "w": 120, "h": 24},
        "side_zone:background": {"x": 760, "y": 100, "w": 180, "h": 300},
        "side_zone:title": {"type": "text", "x": 780, "y": 115, "w": 120, "h": 24},
    }
    manifest = _manifest(
        _rect("bg_a", 100, 100, 220, 120),
        _rect("bg_b", 380, 100, 240, 150),
        _rect("bg_side", 760, 100, 180, 300),
    )

    out = preserve_group_alignment_intent(manifest, layout)
    by_id = {e["id"]: e for e in out["elements"]}

    assert by_id["bg_a"]["height"] == 150
    assert by_id["bg_b"]["height"] == 150
    assert by_id["bg_side"]["height"] == 300
