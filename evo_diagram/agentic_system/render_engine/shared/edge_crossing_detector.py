"""Edge-crossing detector for Excalidraw arrow polylines.

Observational only — reports pairs of arrows whose rendered paths
intersect. Does not modify the manifest. Intended as a warning signal
in the Render workflow's ``arrows`` node so upstream Layout choices
(LLM or dagre) can be diagnosed when visually poor.

Algorithm
---------
Classic line-segment intersection via CCW orientation test
(CLRS §33.1). Two segments ``AB`` and ``CD`` intersect iff::

    orient(A, B, C) != orient(A, B, D)  AND
    orient(C, D, A) != orient(C, D, B)

with a colinear special case handled by bounding-box overlap.

Shared endpoints (one segment ends where the other begins — e.g. two
arrows converging on the same shape face midpoint) are NOT reported,
as these are desired convergence, not crossings.

Each arrow is unfolded into its list of line segments (``len(points)-1``
segments per arrow) and all segment pairs across distinct arrows are
compared.  O(E²) worst-case, which is acceptable for EvoDiagram's
typical ``E ≤ 50`` diagrams.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


# Epsilon for floating-point orientation checks.  At pixel scale,
# collinearity within ~0.01 is indistinguishable from true collinearity.
_ORIENT_EPSILON = 1e-6


def _is_visible_arrow(arrow: Dict[str, Any]) -> bool:
    """Return whether an arrow contributes visible rendered geometry."""
    if arrow.get("type") != "arrow" or arrow.get("isDeleted"):
        return False
    try:
        return float(arrow.get("opacity", 100) or 0) > 0
    except (TypeError, ValueError):
        return True


def _orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> int:
    """Sign of the 2D cross product ``(b-a) x (c-a)``.

    Returns ``+1`` / ``-1`` / ``0`` for counter-clockwise, clockwise, or
    colinear triples respectively.
    """
    v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if v > _ORIENT_EPSILON:
        return 1
    if v < -_ORIENT_EPSILON:
        return -1
    return 0


def _on_segment(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float
) -> bool:
    """True iff colinear point ``C`` lies on segment ``AB`` (inclusive)."""
    return (
        min(ax, bx) - _ORIENT_EPSILON <= cx <= max(ax, bx) + _ORIENT_EPSILON
        and min(ay, by) - _ORIENT_EPSILON <= cy <= max(ay, by) + _ORIENT_EPSILON
    )


def _shares_endpoint(
    a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]
) -> bool:
    """Two segments share an endpoint within epsilon → convergence, not crossing."""
    (ax1, ay1, ax2, ay2) = a
    (bx1, by1, bx2, by2) = b
    for (px, py) in ((ax1, ay1), (ax2, ay2)):
        for (qx, qy) in ((bx1, by1), (bx2, by2)):
            if abs(px - qx) < _ORIENT_EPSILON and abs(py - qy) < _ORIENT_EPSILON:
                return True
    return False


def _segments_intersect(
    a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]
) -> bool:
    """CCW orientation test for proper intersection of segments AB and CD.

    Returns True only for proper crossings; colinear overlap and
    shared-endpoint contact return False (the caller filters shared
    endpoints via ``_shares_endpoint``).
    """
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    o1 = _orient(ax1, ay1, ax2, ay2, bx1, by1)
    o2 = _orient(ax1, ay1, ax2, ay2, bx2, by2)
    o3 = _orient(bx1, by1, bx2, by2, ax1, ay1)
    o4 = _orient(bx1, by1, bx2, by2, ax2, ay2)

    # Proper intersection
    if o1 != o2 and o3 != o4:
        return True

    # Colinear overlap — treat as NON-crossing for warning purposes
    # (avoids spurious warnings on arrows that happen to travel the same
    # grid line briefly).  If one endpoint of one segment lies strictly
    # inside the other, that's still a crossing worth flagging.
    if o1 == 0 and _on_segment(ax1, ay1, ax2, ay2, bx1, by1):
        # Only flag if the collinear point is STRICTLY interior (not an endpoint).
        if not _shares_endpoint(a, b):
            return True
    if o2 == 0 and _on_segment(ax1, ay1, ax2, ay2, bx2, by2):
        if not _shares_endpoint(a, b):
            return True
    if o3 == 0 and _on_segment(bx1, by1, bx2, by2, ax1, ay1):
        if not _shares_endpoint(a, b):
            return True
    if o4 == 0 and _on_segment(bx1, by1, bx2, by2, ax2, ay2):
        if not _shares_endpoint(a, b):
            return True

    return False


def _arrow_segments(arrow: Dict[str, Any]) -> List[Tuple[float, float, float, float]]:
    """Flatten an Excalidraw arrow into its absolute-coord line segments.

    ``arrow.points`` is relative to ``arrow.x``/``arrow.y``.  A 2-point
    arrow produces 1 segment; 3 points produce 2 segments; 4 points
    produce 3 segments.
    """
    pts = arrow.get("points") or []
    if not isinstance(pts, list) or len(pts) < 2:
        return []
    ox = float(arrow.get("x", 0.0) or 0.0)
    oy = float(arrow.get("y", 0.0) or 0.0)
    abs_pts: List[Tuple[float, float]] = []
    for p in pts:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            abs_pts.append((ox + float(p[0]), oy + float(p[1])))
        elif isinstance(p, dict):
            abs_pts.append((float(p.get("x", 0.0)), float(p.get("y", 0.0))))
    segs: List[Tuple[float, float, float, float]] = []
    for i in range(len(abs_pts) - 1):
        x1, y1 = abs_pts[i]
        x2, y2 = abs_pts[i + 1]
        segs.append((x1, y1, x2, y2))
    return segs


def count_segment_crossings(
    segment: Tuple[float, float, float, float],
    arrows: List[Dict[str, Any]],
) -> int:
    """Count existing arrow paths crossed by one candidate segment.

    This is the routing-time counterpart to :func:`detect_crossings`. It keeps
    the same shared-endpoint semantics while avoiding the quadratic work of
    rebuilding a complete candidate manifest for every visibility-graph edge.
    Each existing arrow contributes at most one crossing to the count.
    """
    count = 0
    for arrow in arrows:
        if not _is_visible_arrow(arrow):
            continue
        for existing_segment in _arrow_segments(arrow):
            if _shares_endpoint(segment, existing_segment):
                continue
            if _segments_intersect(segment, existing_segment):
                count += 1
                break
    return count


def detect_crossings(
    arrows: List[Dict[str, Any]],
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Return every pair of arrows whose polylines cross.

    Args:
        arrows: list of Excalidraw arrow elements (``{id, x, y, points, ...}``).

    Returns:
        List of ``(arrow_id_a, arrow_id_b, metadata)``.  ``metadata``
        includes the intersecting segment indices and endpoint count
        for debuggability.  Shared-endpoint convergences are excluded.
        Each arrow pair appears at most once; order within the pair is
        ``(smaller_id, larger_id)`` for stable diff.
    """
    if not arrows:
        return []

    # Pre-compute segments per arrow
    indexed: List[Tuple[str, List[Tuple[float, float, float, float]]]] = []
    for a in arrows:
        if not _is_visible_arrow(a):
            continue
        aid = a.get("id")
        if not aid:
            continue
        segs = _arrow_segments(a)
        if segs:
            indexed.append((aid, segs))

    crossings: List[Tuple[str, str, Dict[str, Any]]] = []

    for i in range(len(indexed)):
        id_i, segs_i = indexed[i]
        for j in range(i + 1, len(indexed)):
            id_j, segs_j = indexed[j]
            first_cross: Tuple[int, int] = (-1, -1)
            for si_idx, si in enumerate(segs_i):
                for sj_idx, sj in enumerate(segs_j):
                    if _shares_endpoint(si, sj):
                        # Two segments that join at a common point (e.g.
                        # two incoming arrows sharing the same target
                        # face midpoint) are convergence, not crossing.
                        continue
                    if _segments_intersect(si, sj):
                        first_cross = (si_idx, sj_idx)
                        break
                if first_cross != (-1, -1):
                    break
            if first_cross != (-1, -1):
                a_id, b_id = sorted((id_i, id_j))
                crossings.append(
                    (
                        a_id,
                        b_id,
                        {
                            "segment_index_a": first_cross[0] if a_id == id_i else first_cross[1],
                            "segment_index_b": first_cross[1] if a_id == id_i else first_cross[0],
                        },
                    )
                )
    return crossings
