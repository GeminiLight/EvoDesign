# -*- coding: utf-8 -*-
"""Unit tests for ``edge_crossing_detector.detect_crossings``.

The detector is observational (warn-only); these tests pin its
classification behavior so future refactors of Render won't silently
change the set of reported crossings.

Run with::

    cd evo_diagram && pytest tests/test_crossing_detector.py -v
"""

from __future__ import annotations

import pytest

from evo_diagram.agentic_system.render_engine.shared.edge_crossing_detector import (
    detect_crossings,
)


def _arrow(arrow_id: str, *abs_points: tuple) -> dict:
    """Build an Excalidraw-shaped arrow element from absolute coord pairs.

    ``abs_points`` are ``(x, y)`` tuples in absolute canvas coords.  We
    set ``arrow.x`` / ``arrow.y`` to the first point and store the rest
    relative.
    """
    if not abs_points:
        return {"id": arrow_id, "type": "arrow", "x": 0.0, "y": 0.0, "points": []}
    ox, oy = abs_points[0]
    rel = [[float(px - ox), float(py - oy)] for (px, py) in abs_points]
    return {
        "id": arrow_id,
        "type": "arrow",
        "x": float(ox),
        "y": float(oy),
        "points": rel,
    }


# ---------------------------------------------------------------------------
# Positive cases — true crossings
# ---------------------------------------------------------------------------

def test_x_cross_two_straight_arrows_intersect():
    """Two diagonal lines forming an X → detected."""
    a = _arrow("e1", (0, 0), (100, 100))
    b = _arrow("e2", (0, 100), (100, 0))
    result = detect_crossings([a, b])
    assert len(result) == 1
    assert set(result[0][:2]) == {"e1", "e2"}


def test_l_shape_crossing_straight_line():
    """L-shaped arrow crossing a straight arrow → detected on the crossed segment."""
    l_arrow = _arrow("e1", (0, 0), (100, 0), (100, 100))  # horizontal then vertical
    straight = _arrow("e2", (50, -50), (50, 50))         # vertical passing through horizontal leg
    result = detect_crossings([l_arrow, straight])
    assert len(result) == 1


def test_two_zshapes_crossing_at_middle_segment():
    """Z-shape middle horizontal segments crossing → detected."""
    z1 = _arrow("e1", (0, 0), (0, 100), (200, 100), (200, 200))
    z2 = _arrow("e2", (50, 150), (50, 80), (150, 80), (150, 20))
    result = detect_crossings([z1, z2])
    assert len(result) >= 1


# ---------------------------------------------------------------------------
# Negative cases — NOT crossings
# ---------------------------------------------------------------------------

def test_parallel_lines_no_intersection():
    a = _arrow("e1", (0, 0), (100, 0))
    b = _arrow("e2", (0, 20), (100, 20))
    assert detect_crossings([a, b]) == []


def test_shared_endpoint_convergence_not_a_crossing():
    """Two arrows ending at the same point (convergence on a target face) — excluded."""
    a = _arrow("e1", (0, 0), (100, 100))
    b = _arrow("e2", (200, 0), (100, 100))
    assert detect_crossings([a, b]) == []


def test_shared_start_divergence_not_a_crossing():
    """Two arrows leaving the same source face midpoint — excluded."""
    a = _arrow("e1", (100, 100), (200, 50))
    b = _arrow("e2", (100, 100), (200, 150))
    assert detect_crossings([a, b]) == []


def test_t_junction_segments_touching_at_endpoint():
    """One arrow's endpoint lies on the other arrow's interior — treated as crossing."""
    # Because shared-endpoint filter only matches endpoint-to-endpoint, if
    # endpoint-of-A lies on INTERIOR-of-B (T-junction), that IS a crossing.
    a = _arrow("e1", (0, 50), (100, 50))
    b = _arrow("e2", (50, 50), (50, 200))  # b starts on a's interior
    result = detect_crossings([a, b])
    assert len(result) == 1


def test_collinear_overlap_is_a_crossing():
    """Two arrows sharing a run of the same line overlap visually.

    Pins the docstring/code agreement: a collinear endpoint strictly
    inside the other segment (any real overlap) IS reported — one line is
    drawn on top of the other, which is the defect this warn-only detector
    exists to surface.
    """
    a = _arrow("e1", (0, 0), (100, 0))
    b = _arrow("e2", (20, 0), (50, 0))    # fully contained in a's span
    assert len(detect_crossings([a, b])) == 1

    c = _arrow("e3", (0, 0), (100, 0))
    d = _arrow("e4", (50, 0), (150, 0))   # partial overlap, no shared endpoint
    assert len(detect_crossings([c, d])) == 1


def test_collinear_disjoint_spans_are_not_a_crossing():
    """Same infinite line, spans never touch → no contact, no warning."""
    a = _arrow("e1", (0, 0), (10, 0))
    b = _arrow("e2", (20, 0), (30, 0))
    assert detect_crossings([a, b]) == []


def test_collinear_spans_touching_only_at_endpoints_are_convergence():
    """Head-to-tail continuation on the same line shares an endpoint →
    convergence, not a crossing."""
    a = _arrow("e1", (0, 0), (10, 0))
    b = _arrow("e2", (10, 0), (30, 0))
    assert detect_crossings([a, b]) == []


def test_disjoint_arrows_far_apart():
    a = _arrow("e1", (0, 0), (10, 10))
    b = _arrow("e2", (500, 500), (600, 600))
    assert detect_crossings([a, b]) == []


def test_reverse_direction_same_path_no_crossing():
    """Same polyline traversed in opposite directions — share endpoints both ends."""
    a = _arrow("e1", (0, 0), (100, 100))
    b = _arrow("e2", (100, 100), (0, 0))
    assert detect_crossings([a, b]) == []


# ---------------------------------------------------------------------------
# Degenerate / boundary inputs
# ---------------------------------------------------------------------------

def test_empty_arrow_list():
    assert detect_crossings([]) == []


def test_transparent_arrow_is_not_a_visible_crossing():
    visible = _arrow("visible", (0, 50), (100, 50))
    transparent = _arrow("transparent", (50, 0), (50, 100))
    transparent["opacity"] = 0

    assert detect_crossings([visible, transparent]) == []


def test_single_arrow_cannot_cross_itself():
    a = _arrow("e1", (0, 0), (100, 0), (100, 100))
    assert detect_crossings([a]) == []


def test_arrow_with_fewer_than_2_points_skipped():
    """Malformed arrow (1 point or no points) silently skipped, not raised."""
    a = _arrow("e_bad", (50, 50))          # only 1 point → no segments
    b = _arrow("e_good", (0, 0), (100, 100))
    # No error, no crossings
    assert detect_crossings([a, b]) == []


def test_arrow_without_id_skipped():
    """Arrow missing ``id`` field is tolerated (skipped, not raised)."""
    a = {"type": "arrow", "x": 0, "y": 0, "points": [[0, 0], [100, 100]]}
    b = _arrow("e1", (0, 100), (100, 0))
    # a has no id → excluded from pair enumeration
    assert detect_crossings([a, b]) == []


def test_pair_id_ordering_is_stable():
    """Returned pair is ordered as (smaller_id, larger_id) for stable diff."""
    a = _arrow("edge_z", (0, 0), (100, 100))
    b = _arrow("edge_a", (0, 100), (100, 0))
    result = detect_crossings([a, b])
    assert result[0][0] == "edge_a"
    assert result[0][1] == "edge_z"


def test_multiple_crossings_all_reported():
    """Three arrows each pair-wise crossing → 3 crossings (3 choose 2)."""
    a = _arrow("e1", (0, 50), (100, 50))      # horizontal mid
    b = _arrow("e2", (50, 0), (50, 100))      # vertical mid
    c = _arrow("e3", (0, 0), (100, 100))      # diagonal
    result = detect_crossings([a, b, c])
    # a∩b crosses; a∩c crosses (at (50,50) which is interior of a, endpoint of c) — T-junction
    # Note: c.endpoints are (0,0) and (100,100); neither is on a's interior. c passes THROUGH a at (50,50).
    # So a∩c is a proper crossing.
    # b∩c similarly crosses at (50,50)
    assert len(result) == 3
