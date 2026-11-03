"""Deterministic waypoint computation for Excalidraw arrow polylines.

Replaces Excalidraw's undocumented ``elbowed: true`` flag with explicit
polyline ``points`` arrays. Given a discrete ``(start_side, end_side)``
pair and the source/target bounding boxes, produces a 2-, 3-, 4-, or
5-point path that renders as straight / L-shape / Z-shape / U-shape /
normal-respecting L respectively.

Shape selection (16 combinations, 4×4 lookup):

    Aligned faces on the same axis:
        (bottom, top), (top, bottom): vertical axis
            - collinear (|dx| < alignment_tol): 2-point straight
            - offset:                            4-point Z via mid-y
        (right, left), (left, right): horizontal axis
            - collinear (|dy| < alignment_tol): 2-point straight
            - offset:                            4-point Z via mid-x

    Perpendicular faces:
        start vertical (top/bottom) + end horizontal (left/right):
            3-point L, pivot at (start.x, end.y)
        start horizontal (left/right) + end vertical (top/bottom):
            3-point L, pivot at (end.x, start.y)
        ...unless either end segment would violate its face normal — the
        first segment doubling back through the source shape, or the last
        segment entering the target face sideways / from behind (under the
        axis-aligned constraint a 4-point path cannot satisfy both face
        normals at once). Then the route upgrades to 5 points: ``offset``
        along the start face's outward normal → transition corner →
        ``offset`` back along the end face's outward normal → target point,
        so the arrow exits and enters perpendicular to both faces.

    Same face (loop-back, e.g. both nodes attach on top):
        4-point U with ``offset`` detour along the outward normal

The caller is responsible for converting absolute points to
arrow-origin-relative ones (Excalidraw stores ``points`` relative to
``arrow.x``/``arrow.y``) and for setting
``arrow.width``/``arrow.height`` to match the bounding box of the
points.
"""
from __future__ import annotations

from typing import Dict, List, Tuple


ALIGNED_PAIRS = frozenset({
    ("top", "bottom"),
    ("bottom", "top"),
    ("left", "right"),
    ("right", "left"),
})

_VALID_SIDES = frozenset({"top", "bottom", "left", "right"})

# Outward unit normal per face. An arrow must LEAVE the start face along
# +normal and ENTER the end face along -normal; anything else (doubling
# back, sideways incidence, zero-length end segment) is a conflict.
_FACE_NORMALS: Dict[str, Tuple[float, float]] = {
    "top": (0.0, -1.0),
    "bottom": (0.0, 1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}


def _normal_offset_point(
    point: Dict[str, float],
    side: str,
    offset: float,
) -> Dict[str, float]:
    """``point`` shifted ``offset`` units along ``side``'s outward normal."""
    nx, ny = _FACE_NORMALS[side]
    return {"x": point["x"] + nx * offset, "y": point["y"] + ny * offset}


def _exits_along_normal(
    p_from: Dict[str, float],
    p_to: Dict[str, float],
    side: str,
) -> bool:
    """True iff p_from→p_to strictly leaves ``side`` along its outward normal.

    Sideways (dot == 0), backward (dot < 0), and zero-length segments all
    count as conflicts.
    """
    nx, ny = _FACE_NORMALS[side]
    return ((p_to["x"] - p_from["x"]) * nx + (p_to["y"] - p_from["y"]) * ny) > 0


def _enters_along_normal(
    p_from: Dict[str, float],
    p_to: Dict[str, float],
    side: str,
) -> bool:
    """True iff p_from→p_to strictly enters ``side`` against its outward normal.

    An arrow reaching a face must approach it head-on from the outside, so
    the final direction must be anti-parallel to the face normal; sideways
    entry (dot == 0) and entry from behind the face (dot > 0) are conflicts.
    """
    nx, ny = _FACE_NORMALS[side]
    return ((p_to["x"] - p_from["x"]) * nx + (p_to["y"] - p_from["y"]) * ny) < 0


def _dedupe_consecutive(
    points: List[Dict[str, float]],
) -> List[Dict[str, float]]:
    """Drop consecutive duplicate points (possible when ``offset`` is 0 or a
    transition corner collapses onto its neighbour). Legality of the end
    segments is unaffected: the surviving neighbours keep their direction."""
    result: List[Dict[str, float]] = []
    for point in points:
        if result and result[-1]["x"] == point["x"] and result[-1]["y"] == point["y"]:
            continue
        result.append(point)
    return result


def _side_midpoint(bbox: Dict[str, float], side: str) -> Dict[str, float]:
    """Absolute coord of the midpoint on one face of ``bbox``.

    ``bbox`` keys: ``x``, ``y``, ``w``, ``h`` (top-left origin, w/h positive).
    """
    x = float(bbox.get("x", 0.0))
    y = float(bbox.get("y", 0.0))
    w = float(bbox.get("w", 0.0))
    h = float(bbox.get("h", 0.0))
    if side == "top":
        return {"x": x + w / 2.0, "y": y}
    if side == "bottom":
        return {"x": x + w / 2.0, "y": y + h}
    if side == "left":
        return {"x": x, "y": y + h / 2.0}
    if side == "right":
        return {"x": x + w, "y": y + h / 2.0}
    raise ValueError(f"Unknown side: {side!r}")


def _stagger_delta(index: int, total: int, spacing: float) -> float:
    """Return a signed offset for the i-th edge among ``total`` siblings.

    Distributes edges symmetrically around 0:
        total=1 → [0]
        total=2 → [-spacing/2, +spacing/2]
        total=3 → [-spacing, 0, +spacing]
        total=4 → [-1.5*spacing, -0.5*spacing, +0.5*spacing, +1.5*spacing]
    """
    if total <= 1 or spacing == 0.0:
        return 0.0
    return (index - (total - 1) / 2.0) * spacing


def _bounded_midpoint(
    start: float,
    end: float,
    index: int,
    total: int,
    spacing: float,
    margin: float = 12.0,
) -> float:
    """Stagger a corridor without pushing it into either endpoint node."""
    midpoint = (start + end) / 2.0
    low = min(start, end) + margin
    high = max(start, end) - margin
    if low >= high:
        return midpoint
    return max(low, min(high, midpoint + _stagger_delta(index, total, spacing)))


def _face_stagger_delta(
    index: int,
    total: int,
    span: float,
    spacing: float,
    margin: float = 8.0,
) -> float:
    """Return a bounded offset for a fan-out port on one shape face.

    A fixed spacing is useful for readable paths, but it must not push a port
    past a node corner.  Clamping the symmetric offset keeps the endpoint on
    the face even when a compact node has many incoming or outgoing edges.
    """
    raw = _stagger_delta(index, total, spacing)
    max_delta = max(0.0, (float(span) - 2.0 * margin) / 2.0)
    return max(-max_delta, min(max_delta, raw))


def _offset_face_point(
    point: Dict[str, float],
    bbox: Dict[str, float],
    side: str,
    index: int,
    total: int,
    spacing: float,
) -> Dict[str, float]:
    """Move a face midpoint along its face for deterministic port fan-out."""
    offset = _face_stagger_delta(
        index,
        total,
        bbox.get("w", 0.0) if side in ("top", "bottom") else bbox.get("h", 0.0),
        spacing,
    )
    adjusted = dict(point)
    if side in ("top", "bottom"):
        adjusted["x"] += offset
    else:
        adjusted["y"] += offset
    return adjusted


def compute_waypoints(
    start_side: str,
    end_side: str,
    src_bbox: Dict[str, float],
    tgt_bbox: Dict[str, float],
    alignment_tol: float = 2.0,
    offset: float = 30.0,
    stagger_index: int = 0,
    stagger_total: int = 1,
    stagger_spacing: float = 50.0,
    start_port_index: int = 0,
    start_port_total: int = 1,
    end_port_index: int = 0,
    end_port_total: int = 1,
    port_spacing: float = 32.0,
) -> Tuple[List[Dict[str, float]], float, float]:
    """Compute a polyline path between two face midpoints.

    Args:
        start_side: one of ``top|bottom|left|right`` (source face).
        end_side:   one of ``top|bottom|left|right`` (target face).
        src_bbox:   ``{x, y, w, h}`` of source shape.
        tgt_bbox:   ``{x, y, w, h}`` of target shape.
        alignment_tol: pixels within which two face midpoints are treated
            as collinear (emits a 2-point straight line). Default ``2.0``.
        offset: detour distance for U-shapes (same-face pairs). Default
            ``30.0``.
        stagger_index: 0-based position among same-source edges sharing
            the same (start_side, end_side) orientation. Default ``0``.
        stagger_total: total count of such sibling edges. Default ``1``.
        stagger_spacing: pixel gap between staggered segments. Default
            ``50.0``.
        start_port_index: 0-based position among all edges leaving the same
            source face. Default ``0``.
        start_port_total: total count of edges leaving that source face.
        end_port_index: 0-based position among all edges entering the same
            target face. Default ``0``.
        end_port_total: total count of edges entering that target face.
        port_spacing: desired pixel gap between adjacent face ports. The
            actual offset is bounded by the node face. Default ``32.0``.

    Returns:
        ``(points, focus_start, focus_end)``:
            - ``points``: list of ``{"x", "y"}`` absolute coords, 2–5
              points, including both endpoints.
            - ``focus_start``, ``focus_end``: ``[-1, 1]`` position along
              the respective face. Currently always ``0.0`` (midpoint)
              but reserved for future multi-edge fan-out.
    """
    if start_side not in _VALID_SIDES:
        raise ValueError(f"Invalid start_side: {start_side!r}")
    if end_side not in _VALID_SIDES:
        raise ValueError(f"Invalid end_side: {end_side!r}")

    start = _offset_face_point(
        _side_midpoint(src_bbox, start_side),
        src_bbox,
        start_side,
        start_port_index,
        start_port_total,
        port_spacing,
    )
    end = _offset_face_point(
        _side_midpoint(tgt_bbox, end_side),
        tgt_bbox,
        end_side,
        end_port_index,
        end_port_total,
        port_spacing,
    )

    start_vertical = start_side in ("top", "bottom")

    # ---------- Aligned pairs: straight or Z-shape ----------
    if (start_side, end_side) in ALIGNED_PAIRS:
        if start_vertical:
            # top↔bottom pair: travel along y axis
            if abs(start["x"] - end["x"]) < alignment_tol:
                return [start, end], 0.0, 0.0
            mid_y = _bounded_midpoint(
                start["y"], end["y"], stagger_index, stagger_total, stagger_spacing
            )
            return (
                [
                    start,
                    {"x": start["x"], "y": mid_y},
                    {"x": end["x"], "y": mid_y},
                    end,
                ],
                0.0,
                0.0,
            )
        # left↔right pair: travel along x axis
        if abs(start["y"] - end["y"]) < alignment_tol:
            return [start, end], 0.0, 0.0
        mid_x = _bounded_midpoint(
            start["x"], end["x"], stagger_index, stagger_total, stagger_spacing
        )
        return (
            [
                start,
                {"x": mid_x, "y": start["y"]},
                {"x": mid_x, "y": end["y"]},
                end,
            ],
            0.0,
            0.0,
        )

    # ---------- Same-face pair: U-shape ----------
    if start_side == end_side:
        if start_side == "top":
            detour_y = min(start["y"], end["y"]) - offset
            detour_y += _stagger_delta(stagger_index, stagger_total, stagger_spacing)
            return (
                [
                    start,
                    {"x": start["x"], "y": detour_y},
                    {"x": end["x"], "y": detour_y},
                    end,
                ],
                0.0,
                0.0,
            )
        if start_side == "bottom":
            detour_y = max(start["y"], end["y"]) + offset
            detour_y += _stagger_delta(stagger_index, stagger_total, stagger_spacing)
            return (
                [
                    start,
                    {"x": start["x"], "y": detour_y},
                    {"x": end["x"], "y": detour_y},
                    end,
                ],
                0.0,
                0.0,
            )
        if start_side == "left":
            detour_x = min(start["x"], end["x"]) - offset
            detour_x += _stagger_delta(stagger_index, stagger_total, stagger_spacing)
            return (
                [
                    start,
                    {"x": detour_x, "y": start["y"]},
                    {"x": detour_x, "y": end["y"]},
                    end,
                ],
                0.0,
                0.0,
            )
        # start_side == "right"
        detour_x = max(start["x"], end["x"]) + offset
        detour_x += _stagger_delta(stagger_index, stagger_total, stagger_spacing)
        return (
            [
                start,
                {"x": detour_x, "y": start["y"]},
                {"x": detour_x, "y": end["y"]},
                end,
            ],
            0.0,
            0.0,
        )

    # ---------- Perpendicular pair: L-shape ----------
    # Build the cheapest candidate (3-point pivot, or 4-point detour when
    # the pivot sits behind the start face), then check BOTH end segments
    # against their face normals. The first segment must leave the start
    # face along its outward normal; the last segment must enter the end
    # face against its outward normal (head-on, from outside). Under the
    # axis-aligned constraint a 4-point path can only ever satisfy one of
    # the two — its last segment runs parallel to the START normal's axis
    # and therefore enters the (perpendicular) end face sideways — and a
    # 3-point pivot whose corner overshoots the end face enters it from
    # behind. Either conflict upgrades the route to 5 points:
    #     start → start+normal*offset → transition corner
    #           → end+normal*offset   → end
    # so both end segments respect their face normals.
    if start_vertical:
        naive_normal_ahead = (end["y"] - start["y"]) * _FACE_NORMALS[start_side][1] > 0
    else:
        naive_normal_ahead = (end["x"] - start["x"]) * _FACE_NORMALS[start_side][0] > 0

    if naive_normal_ahead:
        # 3-point L, pivot at (start.x, end.y) / (end.x, start.y).
        if start_vertical:
            candidate = [start, {"x": start["x"], "y": end["y"]}, end]
        else:
            candidate = [start, {"x": end["x"], "y": start["y"]}, end]
    else:
        # 4-point detour: step ``offset`` along the start normal first,
        # travel at the detour level, then drop onto the end point.
        detour = _normal_offset_point(start, start_side, offset)
        if start_vertical:
            candidate = [start, detour, {"x": end["x"], "y": detour["y"]}, end]
        else:
            candidate = [start, detour, {"x": detour["x"], "y": end["y"]}, end]

    ends_legal = _exits_along_normal(
        candidate[0], candidate[1], start_side
    ) and _enters_along_normal(candidate[-2], candidate[-1], end_side)
    if ends_legal:
        return candidate, 0.0, 0.0

    # 5-point upgrade: offsets along BOTH face normals plus one transition
    # corner. The corner continues perpendicular to the start normal first
    # (travelling at the start detour level), mirroring the 4-point detour
    # it replaces, so the route stays as close to the shapes' free space as
    # the simpler paths did.
    exit_point = _normal_offset_point(start, start_side, offset)
    approach_point = _normal_offset_point(end, end_side, offset)
    if start_vertical:
        transition = {"x": approach_point["x"], "y": exit_point["y"]}
    else:
        transition = {"x": exit_point["x"], "y": approach_point["y"]}
    points = _dedupe_consecutive([start, exit_point, transition, approach_point, end])
    return points, 0.0, 0.0


def waypoints_bbox(points: List[Dict[str, float]]) -> Tuple[float, float]:
    """Width/height of the axis-aligned bounding box of a points list.

    Excalidraw requires ``arrow.width`` and ``arrow.height`` to match the
    bounding box of its ``points`` array. Empty lists return ``(0.0, 0.0)``.
    """
    if not points:
        return 0.0, 0.0
    xs = [float(p["x"]) for p in points]
    ys = [float(p["y"]) for p in points]
    return max(xs) - min(xs), max(ys) - min(ys)


def to_relative_points(
    points: List[Dict[str, float]],
) -> Tuple[float, float, List[List[float]]]:
    """Convert absolute waypoints to Excalidraw arrow-element shape.

    Excalidraw stores ``points`` as ``[[dx, dy], ...]`` relative to the
    arrow element's ``x``/``y`` origin. The origin is conventionally the
    first point's absolute position.

    Returns ``(origin_x, origin_y, relative_points)`` suitable for:

        arrow_elem["x"] = origin_x
        arrow_elem["y"] = origin_y
        arrow_elem["points"] = relative_points
    """
    if not points:
        return 0.0, 0.0, []
    origin_x = float(points[0]["x"])
    origin_y = float(points[0]["y"])
    rel = [[float(p["x"]) - origin_x, float(p["y"]) - origin_y] for p in points]
    return origin_x, origin_y, rel
