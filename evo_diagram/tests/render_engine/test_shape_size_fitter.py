# -*- coding: utf-8 -*-
"""Unit tests for ``shape_size_fitter.fit_shape_sizes_to_text``.

Pins the behavior of the render-side size-enforcement pass so future
refactors don't silently regress text overflow protection.  Covers all
three container shapes, CJK handling, center-invariance, bound-text
synchronization, standalone text (group titles), and idempotency.

Run with::

    cd evo_diagram && pytest tests/test_shape_size_fitter.py -v
"""

from __future__ import annotations

import pytest

from evo_diagram.agentic_system.render_engine.excalidraw.shape_size_fitter import (
    SHAPE_INFLATE,
    fit_shape_sizes_to_text,
)
from evo_diagram.agentic_system.generation_stage.layout.element_shape_estimator import (
    _ICON_LEFT_PAD,
    _ICON_TEXT_GAP,
)


def _shape(shape_id: str, stype: str, x: float, y: float, w: float, h: float, text_id: str) -> dict:
    return {
        "id": shape_id,
        "type": stype,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "boundElements": [{"type": "text", "id": text_id}],
    }


def _text(text_id: str, container_id: str, x: float, y: float, w: float, h: float, text: str, fontSize: int = 20) -> dict:
    return {
        "id": text_id,
        "type": "text",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "text": text,
        "fontSize": fontSize,
        "containerId": container_id,
    }


def _icon(icon_id: str, x: float, y: float, size: float = 48) -> dict:
    return {
        "id": icon_id,
        "type": "image",
        "x": x,
        "y": y,
        "width": size,
        "height": size,
    }


def _mani(*elements) -> dict:
    return {"type": "excalidraw", "elements": list(elements)}


def _find(mani: dict, elem_id: str) -> dict:
    return next(e for e in mani["elements"] if e.get("id") == elem_id)


# ---------------------------------------------------------------------------
# Rectangle — no change on short label
# ---------------------------------------------------------------------------

def test_rectangle_short_label_fits_no_change():
    shape = _shape("rect1", "rectangle", x=100, y=100, w=300, h=80, text_id="t1")
    text = _text("t1", "rect1", x=140, y=125, w=60, h=30, text="Hi", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    s = _find(out, "rect1")
    assert s["width"] == 300
    assert s["height"] == 80


# ---------------------------------------------------------------------------
# Rectangle — long label expands width
# ---------------------------------------------------------------------------

def test_rectangle_long_label_expands_width():
    # fontSize=20, 30 chars @ 0.6 char_factor → text.width = 30*20*0.6 = 360
    # rectangle inflate=1.0, + 2*20 pad → required ≥ 400
    shape = _shape("rect2", "rectangle", x=100, y=100, w=200, h=80, text_id="t2")
    text = _text("t2", "rect2", x=100, y=100, w=200, h=80, text="A" * 30, fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    s = _find(out, "rect2")
    assert s["width"] >= 400  # grew
    assert s["height"] == 80  # height unchanged (single line fits)


# ---------------------------------------------------------------------------
# Rectangle — multiline label expands height
# ---------------------------------------------------------------------------

def test_rectangle_multiline_expands_height():
    # 3 lines × fontSize 20 × 1.25 = 75; + 2*15 pad = 105 required h.
    shape = _shape("rect3", "rectangle", x=100, y=100, w=400, h=60, text_id="t3")
    text = _text("t3", "rect3", x=100, y=100, w=400, h=60, text="A\nB\nC", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    s = _find(out, "rect3")
    assert s["height"] >= 105


# ---------------------------------------------------------------------------
# Diamond — 1.4× inflate for decision nodes
# ---------------------------------------------------------------------------

def test_diamond_inflates_1_4x():
    # Text width: 22 chars × 20 × 0.6 = 264.  Diamond needs 264*1.4 + 40 = 409.6 → 410.
    shape = _shape("d1", "diamond", x=100, y=100, w=180, h=120, text_id="td1")
    text = _text("td1", "d1", x=100, y=100, w=180, h=120, text="Is Lamp Plugged In?", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    d = _find(out, "d1")
    # Should grow to roughly text_width * 1.4 + 2*pad.
    assert d["width"] > 180
    # Inflate factor specifically applied (not same as rectangle).
    expected_min = 19 * 20 * 0.6 * SHAPE_INFLATE["diamond"] + 2 * 20
    assert d["width"] >= expected_min - 1  # allow 1px rounding


# ---------------------------------------------------------------------------
# Ellipse — 1.2× inflate for terminators
# ---------------------------------------------------------------------------

def test_ellipse_inflates_1_2x():
    shape = _shape("e1", "ellipse", x=100, y=100, w=100, h=60, text_id="te1")
    text = _text("te1", "e1", x=100, y=100, w=100, h=60, text="Lamp Fails to Operate", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    el = _find(out, "e1")
    expected_min = 21 * 20 * 0.6 * SHAPE_INFLATE["ellipse"] + 2 * 20
    assert el["width"] >= expected_min - 1
    # Ellipse should grow LESS than an equivalent diamond would (1.2 < 1.4)
    diamond_equiv = 21 * 20 * 0.6 * SHAPE_INFLATE["diamond"] + 2 * 20
    assert el["width"] < diamond_equiv + 5   # ellipse is smaller than diamond


# ---------------------------------------------------------------------------
# CJK — char_factor 1.0 rather than 0.6
# ---------------------------------------------------------------------------

def test_cjk_label_uses_full_char_width():
    # 10 Chinese chars at fontSize=20 → char_factor=1.0 → text_w = 200
    shape = _shape("rc", "rectangle", x=0, y=0, w=50, h=30, text_id="tc")
    text = _text("tc", "rc", x=0, y=0, w=50, h=30, text="一二三四五六七八九十", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    s = _find(out, "rc")
    # width = 200 * 1.0 + 40 = 240
    assert s["width"] >= 240


# ---------------------------------------------------------------------------
# Only expand, never shrink
# ---------------------------------------------------------------------------

def test_oversized_shape_not_shrunk():
    # LLM committed 500×300, but text only needs ~80×25.
    shape = _shape("big", "rectangle", x=0, y=0, w=500, h=300, text_id="tb")
    text = _text("tb", "big", x=0, y=0, w=500, h=300, text="OK", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    s = _find(out, "big")
    assert s["width"] == 500
    assert s["height"] == 300


# ---------------------------------------------------------------------------
# Center is preserved when growing
# ---------------------------------------------------------------------------

def test_center_preserved_on_growth():
    # Pre-fit center: (200, 140).  After growth, center must remain (200, 140).
    shape = _shape("c1", "diamond", x=100, y=100, w=200, h=80, text_id="tcc")
    text = _text("tcc", "c1", x=100, y=100, w=200, h=80, text="A very long decision label that definitely overflows", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    s = _find(out, "c1")
    new_cx = s["x"] + s["width"] / 2
    new_cy = s["y"] + s["height"] / 2
    assert abs(new_cx - 200) < 0.5
    assert abs(new_cy - 140) < 0.5


# ---------------------------------------------------------------------------
# Bound text geometry is synced to the enlarged shape
# ---------------------------------------------------------------------------

def test_bound_text_re_centered_after_growth():
    shape = _shape("s1", "diamond", x=100, y=100, w=200, h=80, text_id="ts1")
    text = _text("ts1", "s1", x=100, y=100, w=200, h=80, text="A very long decision label that definitely overflows", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    s = _find(out, "s1")
    t = _find(out, "ts1")
    # Text center must sit at shape center.
    shape_cx = s["x"] + s["width"] / 2
    shape_cy = s["y"] + s["height"] / 2
    text_cx = t["x"] + t["width"] / 2
    text_cy = t["y"] + t["height"] / 2
    assert abs(shape_cx - text_cx) < 1.0
    assert abs(shape_cy - text_cy) < 1.0


def test_icon_node_reserves_left_content_area():
    shape = _shape("icon_node", "rectangle", x=100, y=100, w=140, h=80, text_id="icon_text")
    text = _text(
        "icon_text",
        "icon_node",
        x=100,
        y=100,
        w=140,
        h=25,
        text="Authentication",
        fontSize=20,
    )
    icon = _icon("icon_image", x=116, y=116, size=48)

    out = fit_shape_sizes_to_text(_mani(shape, text, icon))
    s = _find(out, "icon_node")
    t = _find(out, "icon_text")
    i = _find(out, "icon_image")

    # 14 chars * 20 * 0.6 = 168, plus shape padding and left icon budget.
    assert s["width"] >= 168 + 40 + _ICON_LEFT_PAD + 48 + _ICON_TEXT_GAP
    assert i["x"] == s["x"] + _ICON_LEFT_PAD
    assert abs((i["y"] + i["height"] / 2) - (s["y"] + s["height"] / 2)) < 1.0
    assert t["x"] >= i["x"] + i["width"] + _ICON_TEXT_GAP - 1


def test_icon_node_keeps_text_in_right_content_area_when_already_wide():
    shape = _shape("wide_icon_node", "rectangle", x=50, y=50, w=360, h=90, text_id="wide_text")
    text = _text(
        "wide_text",
        "wide_icon_node",
        x=190,
        y=82,
        w=48,
        h=25,
        text="Auth",
        fontSize=20,
    )
    icon = _icon("wide_icon", x=66, y=71, size=48)

    out = fit_shape_sizes_to_text(_mani(shape, text, icon))
    s = _find(out, "wide_icon_node")
    t = _find(out, "wide_text")
    i = _find(out, "wide_icon")

    content_left = i["x"] + i["width"] + _ICON_TEXT_GAP
    content_right = s["x"] + s["width"] - 20
    expected_text_cx = content_left + (content_right - content_left) / 2
    actual_text_cx = t["x"] + t["width"] / 2

    assert s["width"] == 360
    assert abs(actual_text_cx - expected_text_cx) < 1.0


def test_group_frame_containment_does_not_revert_icon_fit():
    group = {
        "id": "group_render_id",
        "type": "rectangle",
        "x": 0,
        "y": 0,
        "width": 500,
        "height": 300,
        "boundElements": [],
    }
    shape = _shape("node_render_id", "rectangle", x=100, y=100, w=140, h=80, text_id="text_render_id")
    text = _text(
        "text_render_id",
        "node_render_id",
        x=100,
        y=100,
        w=140,
        h=25,
        text="Authentication",
        fontSize=20,
    )
    icon = _icon("icon_render_id", x=116, y=116, size=48)
    manifest = _mani(group, shape, text, icon)
    manifest["_meta"] = {
        "id_map": {
            "group_service_layer": "group_render_id",
            "node_auth": "node_render_id",
            "node_auth:icon": "icon_render_id",
        }
    }

    out = fit_shape_sizes_to_text(manifest)
    s = _find(out, "node_render_id")
    t = _find(out, "text_render_id")
    i = _find(out, "icon_render_id")

    assert s["width"] > 140
    assert i["x"] == s["x"] + _ICON_LEFT_PAD
    assert t["x"] >= i["x"] + i["width"] + _ICON_TEXT_GAP - 1


def test_layer_frame_with_title_sibling_is_not_moved_by_overlap_resolver():
    layer = {
        "id": "layer_render_id",
        "type": "rectangle",
        "x": 100,
        "y": 100,
        "width": 500,
        "height": 180,
        "boundElements": [{"type": "text", "id": "layer_bound_text"}],
    }
    layer_text = _text(
        "layer_bound_text",
        "layer_render_id",
        x=210,
        y=177,
        w=280,
        h=25,
        text="Service Boundary Layer",
        fontSize=20,
    )
    title = {
        "id": "layer_title_render_id",
        "type": "text",
        "x": 120,
        "y": 120,
        "width": 280,
        "height": 25,
        "text": "Service Boundary Layer",
        "fontSize": 20,
    }
    node = _shape("node_render_id", "rectangle", x=160, y=160, w=140, h=80, text_id="node_text")
    node_text = _text(
        "node_text",
        "node_render_id",
        x=160,
        y=160,
        w=140,
        h=25,
        text="Authentication",
        fontSize=20,
    )
    icon = _icon("icon_render_id", x=176, y=176, size=48)
    manifest = _mani(layer, layer_text, title, node, node_text, icon)
    manifest["_meta"] = {
        "id_map": {
            "service_layer": "layer_render_id",
            "service_layer:title": "layer_title_render_id",
            "node_auth": "node_render_id",
            "node_auth:icon": "icon_render_id",
        }
    }

    out = fit_shape_sizes_to_text(manifest)
    layer_out = _find(out, "layer_render_id")
    node_out = _find(out, "node_render_id")
    icon_out = _find(out, "icon_render_id")

    assert layer_out["x"] == 100
    assert layer_out["width"] == 500
    assert node_out["width"] > 140
    assert icon_out["x"] == node_out["x"] + _ICON_LEFT_PAD


def test_neighbor_overlap_resolution_keeps_icon_and_text_with_node():
    left = _shape("left_node", "rectangle", x=100, y=100, w=140, h=80, text_id="left_text")
    left_text = _text(
        "left_text",
        "left_node",
        x=100,
        y=100,
        w=140,
        h=25,
        text="Authentication",
        fontSize=20,
    )
    left_icon = _icon("left_icon", x=116, y=116, size=48)
    right = _shape("right_node", "rectangle", x=300, y=100, w=140, h=80, text_id="right_text")
    right_text = _text("right_text", "right_node", x=300, y=100, w=60, h=25, text="Peer", fontSize=20)
    manifest = _mani(left, left_text, left_icon, right, right_text)
    manifest["_meta"] = {
        "id_map": {
            "node_left": "left_node",
            "node_left:icon": "left_icon",
            "node_right": "right_node",
        }
    }

    out = fit_shape_sizes_to_text(manifest)
    left_out = _find(out, "left_node")
    left_text_out = _find(out, "left_text")
    left_icon_out = _find(out, "left_icon")
    right_out = _find(out, "right_node")

    assert left_out["width"] > 140
    assert left_out["x"] + left_out["width"] <= right_out["x"] - 7
    assert left_icon_out["x"] == left_out["x"] + _ICON_LEFT_PAD
    assert left_text_out["x"] >= left_icon_out["x"] + left_icon_out["width"] + _ICON_TEXT_GAP - 1


# ---------------------------------------------------------------------------
# Standalone text (group title) — expanded in place
# ---------------------------------------------------------------------------

def test_standalone_text_grows_width_to_fit():
    # "Service Layer" = 13 chars × fontSize 18 × 0.6 = 140.4 → ceil 141.
    standalone = {
        "id": "title1",
        "type": "text",
        "x": 50,
        "y": 40,
        "width": 80,
        "height": 20,
        "text": "Service Layer",
        "fontSize": 18,
        # no containerId  ← key field
    }
    out = fit_shape_sizes_to_text({"elements": [standalone]})
    t = _find(out, "title1")
    assert t["width"] >= 141   # grew
    # Origin preserved for standalone titles (they're anchored, not centered).
    assert t["x"] == 50
    assert t["y"] == 40


def test_standalone_text_short_no_change():
    standalone = {
        "id": "short",
        "type": "text",
        "x": 0, "y": 0, "width": 500, "height": 100,
        "text": "Hi", "fontSize": 18,
    }
    out = fit_shape_sizes_to_text({"elements": [standalone]})
    t = _find(out, "short")
    assert t["width"] == 500   # already big enough
    assert t["height"] == 100


# ---------------------------------------------------------------------------
# Pass-through cases
# ---------------------------------------------------------------------------

def test_shape_without_bound_text_passes_through():
    shape = {
        "id": "ns",
        "type": "rectangle",
        "x": 100, "y": 100, "width": 50, "height": 30,
        "boundElements": [],
    }
    out = fit_shape_sizes_to_text(_mani(shape))
    s = _find(out, "ns")
    assert s["width"] == 50 and s["height"] == 30


def test_bound_text_reset_to_tight_bbox_by_container_path():
    """Text with containerId gets its bbox RESET to the natural tight
    bbox of its own content (not preserved at LLM's initial value and
    not copied from the shape).  A 300-wide shape with "OK" should have
    a 24-wide text element, not 300."""
    shape = _shape("sc", "rectangle", x=0, y=0, w=300, h=60, text_id="bt")
    # LLM gave text a wildly over-sized bbox of 200×40.
    text = _text("bt", "sc", x=0, y=0, w=200, h=40, text="OK", fontSize=20)
    out = fit_shape_sizes_to_text(_mani(shape, text))
    t = _find(out, "bt")
    s = _find(out, "sc")
    # Text is now at its natural tight size: "OK" @ 20px → 2*20*0.6 = 24.
    assert t["width"] == 24
    # And centered inside the shape.
    assert abs((t["x"] + t["width"]/2) - (s["x"] + s["width"]/2)) < 1.0


def test_arrow_elements_untouched():
    arrow = {
        "id": "a1",
        "type": "arrow",
        "x": 0, "y": 0, "width": 100, "height": 50,
        "points": [[0, 0], [100, 50]],
    }
    out = fit_shape_sizes_to_text(_mani(arrow))
    a = _find(out, "a1")
    assert a == arrow  # unchanged


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_second_pass_is_noop():
    shape = _shape("id1", "diamond", x=100, y=100, w=180, h=120, text_id="tid1")
    text = _text("tid1", "id1", x=100, y=100, w=228, h=25, text="Is Lamp Plugged In?", fontSize=20)
    once = fit_shape_sizes_to_text(_mani(shape, text))
    twice = fit_shape_sizes_to_text(once)
    s1 = _find(once, "id1")
    s2 = _find(twice, "id1")
    assert s1["width"] == s2["width"]
    assert s1["height"] == s2["height"]
    assert s1["x"] == s2["x"]
    assert s1["y"] == s2["y"]


# ---------------------------------------------------------------------------
# Overlap resolver — push axis and "did the fitter cause this?" bookkeeping
# ---------------------------------------------------------------------------

def test_stacked_nodes_separate_vertically_not_out_of_their_column():
    """Column-aligned nodes touching by 1px must not be shoved a full width.

    The resolver used to move along x by the *horizontal* overlap, which for a
    vertically-stacked pair is the whole node width: a 1px vertical touch
    ejected the lower node ~200px out of its column.
    """
    top = _shape("top_node", "rectangle", x=100, y=100, w=140, h=80, text_id="top_text")
    top_text = _text("top_text", "top_node", x=100, y=100, w=140, h=25, text="Authentication", fontSize=20)
    bottom = _shape("bottom_node", "rectangle", x=100, y=179, w=140, h=80, text_id="bottom_text")
    bottom_text = _text("bottom_text", "bottom_node", x=100, y=179, w=140, h=25, text="Authorization", fontSize=20)

    out = fit_shape_sizes_to_text(_mani(top, top_text, bottom, bottom_text))
    top_out = _find(out, "top_node")
    bottom_out = _find(out, "bottom_node")

    # Both grew horizontally (center-invariant) — that part is unchanged.
    assert top_out["width"] > 140 and bottom_out["width"] > 140
    assert top_out["x"] + top_out["width"] / 2 == 170
    assert bottom_out["x"] + bottom_out["width"] / 2 == 170

    # Separation happened on y (overlap 1px) rather than x (overlap ~196px).
    assert bottom_out["y"] >= top_out["y"] + top_out["height"]
    assert bottom_out["y"] - 179 < 20, "vertical push should be overlap + gap, not a node width"


def test_pre_existing_overlap_is_left_alone_when_the_fitter_changed_nothing():
    """The resolver may only clean up overlaps the fitter itself introduced.

    ``_fit_container_to_text`` used to record ``original_dims`` unconditionally,
    so every container with bound text looked "modified" and the resolver
    happily rearranged a layout the fitter had not touched.
    """
    a = _shape("a_node", "rectangle", x=100, y=100, w=300, h=80, text_id="a_text")
    a_text = _text("a_text", "a_node", x=100, y=100, w=60, h=25, text="Hi", fontSize=20)
    b = _shape("b_node", "rectangle", x=350, y=100, w=300, h=80, text_id="b_text")
    b_text = _text("b_text", "b_node", x=350, y=100, w=60, h=25, text="Yo", fontSize=20)

    out = fit_shape_sizes_to_text(_mani(a, a_text, b, b_text))
    a_out = _find(out, "a_node")
    b_out = _find(out, "b_node")

    assert (a_out["x"], a_out["y"], a_out["width"], a_out["height"]) == (100, 100, 300, 80)
    assert (b_out["x"], b_out["y"], b_out["width"], b_out["height"]) == (350, 100, 300, 80)


# ---------------------------------------------------------------------------
# Regression: the exact production scenario from flowchart_20251205_090059_134
# ---------------------------------------------------------------------------

def test_regression_real_decision_diamond_with_overflow():
    """Lifted from results/.../diagram_manifest.json: diamond w=180 with
    bound text w=228 — the #1 observed overflow bug."""
    shape = {
        "id": "diamond_prod",
        "type": "diamond",
        "x": 350, "y": 180, "width": 180, "height": 120,
        "boundElements": [
            {"type": "text", "id": "text_prod"},
            {"type": "arrow", "id": "arrow_dummy_1"},
            {"type": "arrow", "id": "arrow_dummy_2"},
        ],
    }
    text = {
        "id": "text_prod",
        "type": "text",
        "x": 326, "y": 227.5, "width": 228, "height": 25,
        "text": "Is Lamp Plugged In?",
        "fontSize": 20,
        "containerId": "diamond_prod",
    }
    out = fit_shape_sizes_to_text(_mani(shape, text))
    d = _find(out, "diamond_prod")
    # Before fit: diamond w=180 < text w=228.  Expect diamond to now hold
    # the text with diamond-specific inflate (1.4).
    assert d["width"] >= 228  # at minimum wider than the text
    # Re-centered: shape center preserved at (350+90, 180+60) = (440, 240).
    cx = d["x"] + d["width"] / 2
    cy = d["y"] + d["height"] / 2
    assert abs(cx - 440) < 0.5
    assert abs(cy - 240) < 0.5


def test_text_growth_keeps_long_flow_on_its_original_row():
    elements = []
    for index in range(7):
        node_id, text_id = f"node_{index}", f"text_{index}"
        elements.extend([
            _shape(node_id, "diamond" if index == 2 else "rectangle",
                   x=100 + 100 * index, y=100, w=80, h=60, text_id=text_id),
            _text(text_id, node_id, x=100 + 100 * index, y=100,
                  w=80, h=25, text="Validate payment", fontSize=20),
        ])
    out = fit_shape_sizes_to_text(_mani(*elements))
    nodes = [_find(out, f"node_{index}") for index in range(7)]
    assert all(abs(node["y"] + node["height"] / 2 - 130) < 0.1 for node in nodes)
    assert all(a["x"] + a["width"] <= b["x"] for a, b in zip(nodes, nodes[1:]))
    assert all(node["width"] > 80 for node in nodes)


def test_text_growth_preserves_original_room_for_connector_labels():
    elements = []
    for index in range(3):
        node_id, text_id = f"node_{index}", f"text_{index}"
        elements.extend([
            _shape(node_id, "rectangle", x=100 + 140 * index, y=100, w=80, h=60, text_id=text_id),
            _text(text_id, node_id, x=100 + 140 * index, y=100,
                  w=80, h=25, text="Validate payment", fontSize=20),
        ])
    out = fit_shape_sizes_to_text(_mani(*elements))
    nodes = [_find(out, f"node_{index}") for index in range(3)]
    assert all(b["x"] - (a["x"] + a["width"]) >= 60 for a, b in zip(nodes, nodes[1:]))
