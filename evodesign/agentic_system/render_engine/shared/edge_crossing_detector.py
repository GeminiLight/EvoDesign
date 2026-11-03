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

with a collinear special case: when an endpoint of one segment lies on
the interior of the other (a T-junction, or two arrows overlapping along
the same line) the pair IS reported — visually one line is drawn on top
of the other, which is exactly the defect this warn-only detector exists
to surface. Collinear segments that never touch, and touches at shared
endpoints, are NOT reported.

Shared endpoints (one segment ends where the other begins — e.g. two
arrows converging on the same shape face midpoint) are NOT reported,
as these are desired convergence, not crossings.

Each arrow is unfolded into its list of line segments (``len(points)-1``
segments per arrow) and all segment pairs across distinct arrows are
compared.  O(E²) worst-case, which is acceptable for EvoDesign's
typical ``E ≤ 50`` diagrams.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


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
    """Orientation test for intersection of segments AB and CD.

    Returns True for proper crossings AND for collinear contacts where an
    endpoint of one segment lies on the interior of the other — a
    T-junction or two arrows sharing a run of the same line. Both render
    as one line drawn over the other, a real visual defect worth warning
    about (the caller is warn-only, so recall beats precision here).

    Returns False for shared-endpoint contact (convergence on a face
    midpoint; the caller also filters those up front via
    ``_shares_endpoint``) and for collinear segments whose spans never
    touch.
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

    # Collinear contact: an endpoint of one segment lying on the OTHER
    # segment is a T-junction or a same-line overlap — flagged, unless the
    # contact is at shared endpoints (convergence, filtered here and in
    # detect_crossings alike).
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
    return count_prepared_crossings(segment, prepare_crossing_segments(arrows))


# Exact early rejection for axis-aligned pairs. When both segments are
# exactly horizontal/vertical, every cross product in _segments_intersect is
# one product ``length * offset``, so an orientation of 0 means an offset of at
# most _ORIENT_EPSILON / length, and _on_segment allows _ORIENT_EPSILON. With
# lengths of at least _AXIS_MIN_LENGTH that slack is <= 0.1 px, so boxes more
# than _AXIS_GAP apart can never intersect. Diagonal or tiny segments always
# take the exact predicate, so results are identical.
_AXIS_MIN_LENGTH = 1e-5
_AXIS_GAP = 1.0

_PreparedSegment = Tuple[Tuple[float, float, float, float], Optional[Tuple[float, float, float, float]]]


def _axis_box(segment: Tuple[float, float, float, float]) -> Optional[Tuple[float, float, float, float]]:
    """Bounding box of an exactly axis-aligned, non-tiny segment, else None."""
    x1, y1, x2, y2 = segment
    if y1 == y2:
        length = abs(x2 - x1)
    elif x1 == x2:
        length = abs(y2 - y1)
    else:
        return None
    if not (length >= _AXIS_MIN_LENGTH and all(map(math.isfinite, segment))):
        return None
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def _boxes_apart(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    return (a[2] + _AXIS_GAP < b[0] or b[2] + _AXIS_GAP < a[0]
            or a[3] + _AXIS_GAP < b[1] or b[3] + _AXIS_GAP < a[1])


def _prepare(segments: List[Tuple[float, float, float, float]]) -> List[_PreparedSegment]:
    return [(segment, _axis_box(segment)) for segment in segments]


def _union_box(prepared: List[_PreparedSegment]) -> Optional[Tuple[float, float, float, float]]:
    """Box around an arrow whose segments all have axis boxes, else None.

    Each segment box lies inside it, so a candidate apart from this box is
    apart from every segment and the whole arrow can be skipped.
    """
    boxes = [box for _, box in prepared]
    if not boxes or any(box is None for box in boxes):
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


_PreparedArrow = Tuple[List[_PreparedSegment], Optional[Tuple[float, float, float, float]]]


def prepare_crossing_segments(arrows: List[Dict[str, Any]]) -> List[_PreparedArrow]:
    """Flatten the visible arrows once for repeated crossing counts."""
    prepared = []
    for arrow in arrows:
        if _is_visible_arrow(arrow):
            segments = _prepare(_arrow_segments(arrow))
            prepared.append((segments, _union_box(segments)))
    return prepared


def count_prepared_crossings(
    segment: Tuple[float, float, float, float],
    prepared: List[_PreparedArrow],
) -> int:
    """:func:`count_segment_crossings` over :func:`prepare_crossing_segments` output."""
    box = _axis_box(segment)
    count = 0
    for segments, arrow_box in prepared:
        if box is not None and arrow_box is not None and _boxes_apart(box, arrow_box):
            continue
        for existing_segment, existing_box in segments:
            if box is not None and existing_box is not None and _boxes_apart(box, existing_box):
                continue
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
    indexed: List[Tuple[str, List[_PreparedSegment], Optional[Tuple[float, float, float, float]]]] = []
    for a in arrows:
        if not _is_visible_arrow(a):
            continue
        aid = a.get("id")
        if not aid:
            continue
        segs = _arrow_segments(a)
        if segs:
            prepared = _prepare(segs)
            indexed.append((aid, prepared, _union_box(prepared)))

    crossings: List[Tuple[str, str, Dict[str, Any]]] = []

    for i in range(len(indexed)):
        id_i, segs_i, box_i_all = indexed[i]
        for j in range(i + 1, len(indexed)):
            id_j, segs_j, box_j_all = indexed[j]
            if box_i_all is not None and box_j_all is not None and _boxes_apart(box_i_all, box_j_all):
                continue
            first_cross: Tuple[int, int] = (-1, -1)
            for si_idx, (si, box_i) in enumerate(segs_i):
                for sj_idx, (sj, box_j) in enumerate(segs_j):
                    if box_i is not None and box_j is not None and _boxes_apart(box_i, box_j):
                        continue
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
