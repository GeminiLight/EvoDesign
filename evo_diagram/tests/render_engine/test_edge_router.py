# -*- coding: utf-8 -*-
"""Unit tests for ``excalidraw_edge_router.compute_waypoints``.

Covers all 16 ``(start_side, end_side)`` combinations plus boundary
cases (coincident shapes, collinear alignment, offset = 0, zero-bbox).

Run with::

    cd evo_diagram && pytest tests/test_edge_router.py -v
"""

from __future__ import annotations

import pytest

from evo_diagram.agentic_system.render_engine.excalidraw.edge_router import (
    compute_waypoints,
    to_relative_points,
    waypoints_bbox,
)
from evo_diagram.agentic_system.render_engine.shared.edge_routing import (
    audit_sides,
    derive_routing_from_sides,
    pick_sides_from_geometry,
)


# ---------------------------------------------------------------------------
# Fixtures — canonical two-shape arrangements
# ---------------------------------------------------------------------------

# Source at (100,100) 100x60; target at various positions to exercise sides.
SRC = {"x": 100.0, "y": 100.0, "w": 100.0, "h": 60.0}
# source midpoints: top=(150,100), bottom=(150,160), left=(100,130), right=(200,130)

# Target DIRECTLY BELOW source (same x center)
TGT_BELOW_ALIGNED = {"x": 100.0, "y": 300.0, "w": 100.0, "h": 60.0}
# target midpoints: top=(150,300), bottom=(150,360), left=(100,330), right=(200,330)

# Target BELOW source but OFFSET in x (Z-shape territory)
TGT_BELOW_OFFSET = {"x": 400.0, "y": 300.0, "w": 100.0, "h": 60.0}
# target midpoints: top=(450,300), left=(400,330)

# Target DIRECTLY RIGHT of source (same y center)
TGT_RIGHT_ALIGNED = {"x": 400.0, "y": 100.0, "w": 100.0, "h": 60.0}
# target midpoints: left=(400,130), top=(450,100), right=(500,130)

# Target RIGHT of source but y-offset (Z-shape along x)
TGT_RIGHT_OFFSET = {"x": 400.0, "y": 300.0, "w": 100.0, "h": 60.0}
# target midpoints: left=(400,330), top=(450,300)

# Target directly ABOVE source (for reverse-direction aligned tests)
TGT_ABOVE_ALIGNED = {"x": 100.0, "y": 0.0, "w": 100.0, "h": 60.0}  # bottom=(150,60)

# Target directly LEFT of source
TGT_LEFT_ALIGNED = {"x": 0.0, "y": 100.0, "w": 60.0, "h": 60.0}  # right=(60,130)


# ---------------------------------------------------------------------------
# Aligned pairs — 4 cases × (collinear | offset)
# ---------------------------------------------------------------------------

def test_bottom_top_collinear_straight():
    """Source directly above target, exits bottom, enters top → 2-point straight."""
    pts, fs, fe = compute_waypoints("bottom", "top", SRC, TGT_BELOW_ALIGNED)
    assert len(pts) == 2
    assert pts[0] == {"x": 150.0, "y": 160.0}
    assert pts[1] == {"x": 150.0, "y": 300.0}
    assert fs == 0.0 and fe == 0.0


def test_bottom_top_offset_zshape():
    """Source above + offset in x; bottom→top emits a 4-point Z via mid-y."""
    pts, _, _ = compute_waypoints("bottom", "top", SRC, TGT_BELOW_OFFSET)
    assert len(pts) == 4
    assert pts[0] == {"x": 150.0, "y": 160.0}   # src.bottom mid
    assert pts[3] == {"x": 450.0, "y": 300.0}   # tgt.top mid
    mid_y = (160.0 + 300.0) / 2
    assert pts[1]["y"] == mid_y and pts[2]["y"] == mid_y
    assert pts[1]["x"] == 150.0 and pts[2]["x"] == 450.0


def test_top_bottom_reverse_direction_straight():
    """Source directly below target, exits top, enters bottom → 2-point straight."""
    pts, _, _ = compute_waypoints("top", "bottom", SRC, TGT_ABOVE_ALIGNED)
    assert len(pts) == 2
    assert pts[0] == {"x": 150.0, "y": 100.0}   # src.top
    assert pts[1] == {"x": 150.0, "y": 60.0}    # tgt.bottom


def test_right_left_collinear_straight():
    """Source directly left of target → 2-point straight."""
    pts, _, _ = compute_waypoints("right", "left", SRC, TGT_RIGHT_ALIGNED)
    assert len(pts) == 2
    assert pts[0] == {"x": 200.0, "y": 130.0}
    assert pts[1] == {"x": 400.0, "y": 130.0}


def test_right_left_offset_zshape():
    """Source left + y-offset → 4-point Z via mid-x."""
    pts, _, _ = compute_waypoints("right", "left", SRC, TGT_RIGHT_OFFSET)
    assert len(pts) == 4
    assert pts[0] == {"x": 200.0, "y": 130.0}
    assert pts[3] == {"x": 400.0, "y": 330.0}
    mid_x = (200.0 + 400.0) / 2
    assert pts[1]["x"] == mid_x and pts[2]["x"] == mid_x
    assert pts[1]["y"] == 130.0 and pts[2]["y"] == 330.0


def test_left_right_reverse_straight():
    """Source right of target → 2-point straight via left/right pair."""
    pts, _, _ = compute_waypoints("left", "right", SRC, TGT_LEFT_ALIGNED)
    assert len(pts) == 2
    assert pts[0] == {"x": 100.0, "y": 130.0}
    assert pts[1] == {"x": 60.0, "y": 130.0}


# ---------------------------------------------------------------------------
# Perpendicular pairs — 8 cases (4 with start vertical, 4 with start horizontal)
# ---------------------------------------------------------------------------

def test_bottom_left_lshape_pivot_at_start_x_end_y():
    pts, _, _ = compute_waypoints("bottom", "left", SRC, TGT_BELOW_OFFSET)
    assert len(pts) == 3
    assert pts[0] == {"x": 150.0, "y": 160.0}   # src.bottom
    assert pts[1] == {"x": 150.0, "y": 330.0}   # pivot (start.x, end.y)
    assert pts[2] == {"x": 400.0, "y": 330.0}   # tgt.left


def test_bottom_right_lshape():
    """bottom→right: the 3-point pivot overshoots the right face — the last
    segment would travel +x INTO the face from inside the target (entering
    from behind). The normal conflict upgrades the route to 5 points."""
    pts, _, _ = compute_waypoints("bottom", "right", SRC, TGT_BELOW_OFFSET, offset=30.0)
    assert len(pts) == 5
    assert pts[0] == {"x": 150.0, "y": 160.0}   # src.bottom
    assert pts[1] == {"x": 150.0, "y": 190.0}   # 30px along the bottom normal
    assert pts[2] == {"x": 530.0, "y": 190.0}   # transition corner
    assert pts[3] == {"x": 530.0, "y": 330.0}   # 30px outside tgt.right
    assert pts[4] == {"x": 500.0, "y": 330.0}   # tgt.right, entered along -x


def test_top_left_detours_outward_instead_of_doubling_back():
    """Target is BELOW a top-face exit → the pivot must not dive back down.

    Old behaviour: 3-point L pivoting at (150, 330) — the first segment left
    the top face and immediately travelled down through the source body.
    The 4-point detour that fixed the tail still entered tgt.left sideways
    (vertically); the 5-point upgrade respects BOTH face normals.
    """
    pts, _, _ = compute_waypoints("top", "left", SRC, TGT_BELOW_OFFSET, offset=30.0)
    assert len(pts) == 5
    assert pts[0] == {"x": 150.0, "y": 100.0}   # src.top
    assert pts[1] == {"x": 150.0, "y": 70.0}    # 30px along the top normal
    assert pts[2] == {"x": 370.0, "y": 70.0}    # transition corner
    assert pts[3] == {"x": 370.0, "y": 330.0}   # 30px outside tgt.left
    assert pts[4] == {"x": 400.0, "y": 330.0}   # tgt.left, entered along +x


def test_top_right_detours_outward_instead_of_doubling_back():
    pts, _, _ = compute_waypoints("top", "right", SRC, TGT_BELOW_OFFSET, offset=30.0)
    assert len(pts) == 5
    assert pts[0] == {"x": 150.0, "y": 100.0}
    assert pts[1] == {"x": 150.0, "y": 70.0}
    assert pts[2] == {"x": 530.0, "y": 70.0}
    assert pts[3] == {"x": 530.0, "y": 330.0}
    assert pts[4] == {"x": 500.0, "y": 330.0}


def test_right_top_lshape_pivot_at_end_x_start_y():
    pts, _, _ = compute_waypoints("right", "top", SRC, TGT_RIGHT_OFFSET)
    assert len(pts) == 3
    assert pts[0] == {"x": 200.0, "y": 130.0}   # src.right
    assert pts[1] == {"x": 450.0, "y": 130.0}   # pivot (end.x, start.y)
    assert pts[2] == {"x": 450.0, "y": 300.0}   # tgt.top


def test_right_bottom_lshape():
    """right→bottom: the 3-point pivot sits ABOVE the bottom face, so the
    last segment would descend through the target body and enter its bottom
    face from behind (+y instead of the required -y). Upgraded to 5 points."""
    pts, _, _ = compute_waypoints("right", "bottom", SRC, TGT_RIGHT_OFFSET, offset=30.0)
    assert len(pts) == 5
    assert pts[0] == {"x": 200.0, "y": 130.0}   # src.right
    assert pts[1] == {"x": 230.0, "y": 130.0}   # 30px along the right normal
    assert pts[2] == {"x": 230.0, "y": 390.0}   # transition corner
    assert pts[3] == {"x": 450.0, "y": 390.0}   # 30px outside tgt.bottom
    assert pts[4] == {"x": 450.0, "y": 360.0}   # tgt.bottom, entered along -y


def test_left_top_detours_outward_instead_of_doubling_back():
    """Target is RIGHT of a left-face exit → the pivot must not cut back right.

    Old behaviour: 3-point L pivoting at (450, 130) — the first segment left
    the left face heading right, straight through the source body.
    """
    pts, _, _ = compute_waypoints("left", "top", SRC, TGT_RIGHT_OFFSET, offset=30.0)
    assert len(pts) == 5
    assert pts[0] == {"x": 100.0, "y": 130.0}   # src.left
    assert pts[1] == {"x": 70.0, "y": 130.0}    # 30px along the left normal
    assert pts[2] == {"x": 70.0, "y": 270.0}    # transition corner
    assert pts[3] == {"x": 450.0, "y": 270.0}   # 30px outside tgt.top
    assert pts[4] == {"x": 450.0, "y": 300.0}   # tgt.top, entered along +y


def test_left_bottom_detours_outward_instead_of_doubling_back():
    pts, _, _ = compute_waypoints("left", "bottom", SRC, TGT_RIGHT_OFFSET, offset=30.0)
    assert len(pts) == 5
    assert pts[0] == {"x": 100.0, "y": 130.0}
    assert pts[1] == {"x": 70.0, "y": 130.0}
    assert pts[2] == {"x": 70.0, "y": 390.0}
    assert pts[3] == {"x": 450.0, "y": 390.0}
    assert pts[4] == {"x": 450.0, "y": 360.0}


def test_perpendicular_first_segment_never_re_enters_the_source_box():
    """Arrow tails must leave the source, whatever face pair is requested."""
    src = {"x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0}
    tgt = {"x": 400.0, "y": 30.0, "w": 200.0, "h": 60.0}

    # bottom → left: the naive pivot is (100, 60), i.e. 40px back INSIDE src.
    pts, _, _ = compute_waypoints("bottom", "left", src, tgt, offset=30.0)
    assert len(pts) == 5
    assert pts[0] == {"x": 100.0, "y": 100.0}   # src.bottom
    assert pts[1] == {"x": 100.0, "y": 130.0}   # steps DOWN, away from src
    assert pts[2] == {"x": 370.0, "y": 130.0}
    assert pts[3] == {"x": 370.0, "y": 60.0}    # 30px outside tgt.left
    assert pts[4] == {"x": 400.0, "y": 60.0}    # tgt.left
    assert all(
        not (0.0 < p["x"] < 200.0 and 0.0 < p["y"] < 100.0) for p in pts[1:]
    ), "no waypoint may sit inside the source box"


# ---------------------------------------------------------------------------
# 5-point upgrade contract — end segments follow their face normals
# ---------------------------------------------------------------------------

_NORMALS = {
    "top": (0.0, -1.0),
    "bottom": (0.0, 1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}

# Perpendicular combos whose naive 3-/4-point route violates a face normal.
_CONFLICTING_COMBOS = [
    ("top", "left", SRC, TGT_BELOW_OFFSET),
    ("top", "right", SRC, TGT_BELOW_OFFSET),
    ("bottom", "right", SRC, TGT_BELOW_OFFSET),
    ("left", "top", SRC, TGT_RIGHT_OFFSET),
    ("left", "bottom", SRC, TGT_RIGHT_OFFSET),
    ("right", "bottom", SRC, TGT_RIGHT_OFFSET),
]


@pytest.mark.parametrize("start_side,end_side,src,tgt", _CONFLICTING_COMBOS)
def test_five_point_route_end_segments_follow_face_normals(
    start_side, end_side, src, tgt
):
    """The whole point of the upgrade: the first segment leaves the start
    face along its outward normal and the last segment enters the end face
    against its outward normal (head-on from outside)."""
    pts, _, _ = compute_waypoints(start_side, end_side, src, tgt, offset=30.0)
    assert len(pts) == 5

    first = (pts[1]["x"] - pts[0]["x"], pts[1]["y"] - pts[0]["y"])
    last = (pts[-1]["x"] - pts[-2]["x"], pts[-1]["y"] - pts[-2]["y"])
    n_start = _NORMALS[start_side]
    n_end = _NORMALS[end_side]

    # First segment points along the start face's outward normal.
    assert first[0] * n_start[0] + first[1] * n_start[1] > 0
    # Last segment points INTO the end face, i.e. against its outward normal.
    assert last[0] * n_end[0] + last[1] * n_end[1] < 0

    # Both offsets reuse the caller's ``offset`` distance (default 30.0).
    assert (first[0] ** 2 + first[1] ** 2) ** 0.5 == pytest.approx(30.0)
    assert (last[0] ** 2 + last[1] ** 2) ** 0.5 == pytest.approx(30.0)

    # Every segment stays axis-aligned.
    for a, b in zip(pts, pts[1:]):
        assert a["x"] == b["x"] or a["y"] == b["y"]


@pytest.mark.parametrize(
    "start_side,end_side,src,tgt",
    [
        ("bottom", "left", SRC, TGT_BELOW_OFFSET),
        ("right", "top", SRC, TGT_RIGHT_OFFSET),
    ],
)
def test_legal_three_point_lshape_is_not_upgraded(start_side, end_side, src, tgt):
    """Both end segments already follow their normals → keep the 3-point L."""
    pts, _, _ = compute_waypoints(start_side, end_side, src, tgt, offset=30.0)
    assert len(pts) == 3


# ---------------------------------------------------------------------------
# Same-face pairs — 4 cases (U-shape)
# ---------------------------------------------------------------------------

def test_top_top_ushape_detours_above():
    pts, _, _ = compute_waypoints("top", "top", SRC, TGT_RIGHT_OFFSET, offset=30.0)
    assert len(pts) == 4
    assert pts[0] == {"x": 150.0, "y": 100.0}   # src.top
    assert pts[3] == {"x": 450.0, "y": 300.0}   # tgt.top
    # detour_y = min(100, 300) - 30 = 70
    assert pts[1] == {"x": 150.0, "y": 70.0}
    assert pts[2] == {"x": 450.0, "y": 70.0}


def test_bottom_bottom_ushape_detours_below():
    pts, _, _ = compute_waypoints("bottom", "bottom", SRC, TGT_RIGHT_OFFSET, offset=30.0)
    assert len(pts) == 4
    # detour_y = max(160, 360) + 30 = 390
    assert pts[1]["y"] == 390.0 and pts[2]["y"] == 390.0
    assert pts[0] == {"x": 150.0, "y": 160.0}
    assert pts[3] == {"x": 450.0, "y": 360.0}


def test_left_left_ushape_detours_left():
    pts, _, _ = compute_waypoints("left", "left", SRC, TGT_RIGHT_OFFSET, offset=30.0)
    assert len(pts) == 4
    # detour_x = min(100, 400) - 30 = 70
    assert pts[1]["x"] == 70.0 and pts[2]["x"] == 70.0
    assert pts[0] == {"x": 100.0, "y": 130.0}
    assert pts[3] == {"x": 400.0, "y": 330.0}


def test_right_right_ushape_detours_right():
    pts, _, _ = compute_waypoints("right", "right", SRC, TGT_RIGHT_OFFSET, offset=30.0)
    assert len(pts) == 4
    # detour_x = max(200, 500) + 30 = 530
    assert pts[1]["x"] == 530.0 and pts[2]["x"] == 530.0


def test_port_stagger_distributes_start_face_endpoints():
    first, _, _ = compute_waypoints(
        "bottom", "top", SRC, TGT_BELOW_ALIGNED,
        start_port_index=0, start_port_total=2,
    )
    second, _, _ = compute_waypoints(
        "bottom", "top", SRC, TGT_BELOW_ALIGNED,
        start_port_index=1, start_port_total=2,
    )

    assert first[0]["x"] < SRC["x"] + SRC["w"] / 2 < second[0]["x"]
    assert first[0]["y"] == second[0]["y"] == SRC["y"] + SRC["h"]
    assert first[-1] == second[-1]


def test_port_stagger_is_bounded_inside_compact_face():
    compact = {"x": 100.0, "y": 100.0, "w": 30.0, "h": 30.0}
    points, _, _ = compute_waypoints(
        "bottom", "top", compact, TGT_BELOW_ALIGNED,
        start_port_index=0, start_port_total=8,
    )

    assert compact["x"] < points[0]["x"] < compact["x"] + compact["w"]


def test_corridor_stagger_stays_between_close_vertical_nodes():
    target = {"x": 400.0, "y": 230.0, "w": 100.0, "h": 60.0}
    points, _, _ = compute_waypoints(
        "bottom",
        "top",
        SRC,
        target,
        stagger_index=2,
        stagger_total=3,
        stagger_spacing=50.0,
    )

    assert SRC["y"] + SRC["h"] < points[1]["y"] < target["y"]
    assert points[1]["y"] == points[2]["y"]


def test_side_selection_uses_dominant_axis_for_far_sidebar_target():
    source = _shape_from_bbox(SRC)
    target = _shape_from_bbox({"x": 1000.0, "y": 300.0, "w": 100.0, "h": 60.0})

    assert pick_sides_from_geometry(source, target) == ("right", "left")


# ---------------------------------------------------------------------------
# Boundary cases
# ---------------------------------------------------------------------------

def test_alignment_tol_boundary_strict_less_than():
    """Exactly at alignment_tol → still counts as offset (strict <). Safe default."""
    # Two shapes 2px apart; default alignment_tol=2.0 → |dx|=2.0 not < 2.0 → Z-shape
    tgt = {"x": 102.0, "y": 300.0, "w": 100.0, "h": 60.0}  # tgt.top midpoint = (152, 300)
    pts, _, _ = compute_waypoints("bottom", "top", SRC, tgt, alignment_tol=2.0)
    assert len(pts) == 4   # Z-shape, not straight


def test_alignment_tol_sub_boundary_straight():
    """|dx| < alignment_tol → straight 2-point."""
    tgt = {"x": 101.0, "y": 300.0, "w": 100.0, "h": 60.0}  # offset by 1 < tol
    pts, _, _ = compute_waypoints("bottom", "top", SRC, tgt, alignment_tol=2.0)
    assert len(pts) == 2


def test_offset_zero_ushape_degenerate():
    """offset=0 means U-shape detour collapses onto the face → 4 points but pivots at face y."""
    pts, _, _ = compute_waypoints("top", "top", SRC, TGT_BELOW_OFFSET, offset=0.0)
    assert len(pts) == 4
    # detour_y = min(100, 300) - 0 = 100 (same as src.top y)
    assert pts[1]["y"] == 100.0 and pts[2]["y"] == 100.0


def test_zero_bbox_degenerate():
    """Zero-sized shapes degenerate to points; waypoints still well-defined."""
    zero_src = {"x": 50.0, "y": 50.0, "w": 0.0, "h": 0.0}
    pts, _, _ = compute_waypoints("right", "left", zero_src, TGT_RIGHT_ALIGNED)
    # src face midpoints all collapse to (50, 50); tgt.left = (400, 100)
    # |sy - ty| = |50 - 130| = 80 → Z-shape
    assert len(pts) == 4
    assert pts[0] == {"x": 50.0, "y": 50.0}


# ---------------------------------------------------------------------------
# Side audit — protects the renderer contract before compute_waypoints runs
# ---------------------------------------------------------------------------

def _shape_from_bbox(bbox: dict) -> dict:
    return {
        "x": bbox["x"],
        "y": bbox["y"],
        "props": {"w": bbox["w"], "h": bbox["h"]},
    }


def test_audit_sides_rejects_target_side_in_wrong_vertical_half_plane():
    """Source above target: target.bottom faces away and must be corrected.

    The hint pair has to *differ* to exercise the per-side audit — a same-face
    pair is a loop-back request and is honoured verbatim (see
    ``test_audit_sides_honours_same_face_loop_back_hint``).
    """
    source = _shape_from_bbox(SRC)
    target = _shape_from_bbox(TGT_BELOW_ALIGNED)

    assert audit_sides(
        {"start": "left", "end": "bottom"},
        source,
        target,
    ) == ("bottom", "top")


def test_audit_sides_rejects_target_side_in_wrong_horizontal_half_plane():
    """Source left of target: target.right faces away and must be corrected."""
    source = _shape_from_bbox(SRC)
    target = _shape_from_bbox(TGT_RIGHT_ALIGNED)

    assert audit_sides(
        {"start": "top", "end": "right"},
        source,
        target,
    ) == ("right", "left")


def test_audit_sides_honours_same_face_loop_back_hint():
    """Same-face hints express a loop-back detour, not a mis-typed side.

    ``is_side_plausible`` applies mutually exclusive half-plane tests to the
    two roles, so a same-face pair could never survive the per-side audit: it
    always lost at least one side to the geometric forward route.
    """
    source = _shape_from_bbox(SRC)
    target = _shape_from_bbox(TGT_BELOW_ALIGNED)

    assert audit_sides({"start": "right", "end": "right"}, source, target) == (
        "right",
        "right",
    )
    assert audit_sides({"start": "top", "end": "top"}, source, target) == ("top", "top")


def test_same_column_back_edge_bows_out_instead_of_overlapping_forward_edge():
    """State-diagram back edge: A→B down the column, B→A must route around.

    Before the audit fix both same-face hints were rejected, the back edge fell
    back to the geometric ("top", "bottom") pair, and rendered as a straight
    line pixel-identical to the forward edge.
    """
    source = _shape_from_bbox(SRC)
    target = _shape_from_bbox(TGT_BELOW_ALIGNED)

    fwd_start, fwd_end = audit_sides({"start": "bottom", "end": "top"}, source, target)
    fwd_pts, _, _ = compute_waypoints(fwd_start, fwd_end, SRC, TGT_BELOW_ALIGNED)
    assert fwd_pts == [{"x": 150.0, "y": 160.0}, {"x": 150.0, "y": 300.0}]

    back_start, back_end = audit_sides({"start": "right", "end": "right"}, target, source)
    assert (back_start, back_end) == ("right", "right")
    assert derive_routing_from_sides(back_start, back_end) == "curved"

    back_pts, _, _ = compute_waypoints(
        back_start, back_end, TGT_BELOW_ALIGNED, SRC, offset=30.0
    )
    assert back_pts == [
        {"x": 200.0, "y": 330.0},   # B.right
        {"x": 230.0, "y": 330.0},   # detour_x = max(200, 200) + 30
        {"x": 230.0, "y": 130.0},
        {"x": 200.0, "y": 130.0},   # A.right
    ]
    assert back_pts != list(reversed(fwd_pts))


def test_pick_sides_uses_horizontal_faces_for_a_long_horizontal_hop():
    """Two boxes side by side with a small vertical offset connect right→left.

    The dropped ``or abs(dy) > 30`` disjunct made any vertical offset past
    30px force ("bottom", "top"), producing a down / 700px across / up Z.
    """
    a_bbox = {"x": 0.0, "y": 0.0, "w": 200.0, "h": 60.0}
    b_bbox = {"x": 700.0, "y": 90.0, "w": 200.0, "h": 60.0}

    assert audit_sides(None, _shape_from_bbox(a_bbox), _shape_from_bbox(b_bbox)) == (
        "right",
        "left",
    )

    pts, _, _ = compute_waypoints("right", "left", a_bbox, b_bbox)
    assert pts == [
        {"x": 200.0, "y": 30.0},
        {"x": 450.0, "y": 30.0},
        {"x": 450.0, "y": 120.0},
        {"x": 700.0, "y": 120.0},
    ]
    # Old route was [(100,60), (100,105), (800,105), (800,150)] — it left the
    # 200..700 corridor at both ends.
    assert all(200.0 <= p["x"] <= 700.0 for p in pts)


def test_pick_sides_still_uses_vertical_faces_for_a_stacked_pair():
    """Guard against over-correcting: a tall hop stays bottom→top."""
    a_bbox = {"x": 0.0, "y": 0.0, "w": 200.0, "h": 60.0}
    b_bbox = {"x": 60.0, "y": 400.0, "w": 200.0, "h": 60.0}

    assert audit_sides(None, _shape_from_bbox(a_bbox), _shape_from_bbox(b_bbox)) == (
        "bottom",
        "top",
    )


def test_audit_sides_preserves_correct_target_side():
    source = _shape_from_bbox(SRC)
    target = _shape_from_bbox(TGT_BELOW_ALIGNED)

    assert audit_sides(
        {"start": "bottom", "end": "top"},
        source,
        target,
    ) == ("bottom", "top")


def test_coincident_shapes_ushape_well_formed():
    """Same bbox on both ends, same-face pair → U still renders."""
    pts, _, _ = compute_waypoints("top", "top", SRC, SRC, offset=30.0)
    assert len(pts) == 4
    # src.top = tgt.top = (150, 100); detour_y = 100 - 30 = 70
    assert pts[0] == pts[3] == {"x": 150.0, "y": 100.0}
    assert pts[1] == pts[2] == {"x": 150.0, "y": 70.0}


def test_invalid_side_raises():
    with pytest.raises(ValueError):
        compute_waypoints("middle", "top", SRC, TGT_BELOW_ALIGNED)
    with pytest.raises(ValueError):
        compute_waypoints("top", "", SRC, TGT_BELOW_ALIGNED)


# ---------------------------------------------------------------------------
# waypoints_bbox & to_relative_points
# ---------------------------------------------------------------------------

def test_waypoints_bbox_matches_polyline_extent():
    pts = [
        {"x": 150.0, "y": 160.0},
        {"x": 150.0, "y": 230.0},
        {"x": 450.0, "y": 230.0},
        {"x": 450.0, "y": 300.0},
    ]
    w, h = waypoints_bbox(pts)
    assert w == 300.0  # 450 - 150
    assert h == 140.0  # 300 - 160


def test_waypoints_bbox_empty():
    assert waypoints_bbox([]) == (0.0, 0.0)


def test_waypoints_bbox_straight_zero_dimension():
    """Straight horizontal line has h=0."""
    pts = [{"x": 100.0, "y": 50.0}, {"x": 300.0, "y": 50.0}]
    w, h = waypoints_bbox(pts)
    assert w == 200.0 and h == 0.0


def test_to_relative_points_origin_at_first_point():
    abs_pts = [
        {"x": 150.0, "y": 160.0},
        {"x": 150.0, "y": 230.0},
        {"x": 450.0, "y": 230.0},
    ]
    ox, oy, rel = to_relative_points(abs_pts)
    assert ox == 150.0 and oy == 160.0
    assert rel == [[0.0, 0.0], [0.0, 70.0], [300.0, 70.0]]


def test_to_relative_points_empty():
    ox, oy, rel = to_relative_points([])
    assert ox == 0.0 and oy == 0.0
    assert rel == []


# ---------------------------------------------------------------------------
# Bbox contract: waypoints_bbox output MUST match arrow.width/height spec
# ---------------------------------------------------------------------------

def test_every_combo_produces_non_negative_bbox():
    """Regression guard: arrow.width/height must be >= 0 for every side combo."""
    sides = ["top", "bottom", "left", "right"]
    for s_side in sides:
        for e_side in sides:
            pts, _, _ = compute_waypoints(s_side, e_side, SRC, TGT_RIGHT_OFFSET)
            w, h = waypoints_bbox(pts)
            assert w >= 0 and h >= 0, f"negative bbox for ({s_side},{e_side})"
            # At least 2 points always
            assert len(pts) >= 2
