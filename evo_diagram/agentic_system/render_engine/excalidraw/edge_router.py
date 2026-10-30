"""Deterministic waypoint computation for Excalidraw arrow polylines.

Replaces Excalidraw's undocumented ``elbowed: true`` flag with explicit
polyline ``points`` arrays. Given a discrete ``(start_side, end_side)``
pair and the source/target bounding boxes, produces a 2-, 3-, or 4-point
path that renders as straight / L-shape / Z-shape / U-shape respectively.

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

    Returns:
        ``(points, focus_start, focus_end)``:
            - ``points``: list of ``{"x", "y"}`` absolute coords, 2–4
              points, including both endpoints.
            - ``focus_start``, ``focus_end``: ``[-1, 1]`` position along
              the respective face. Currently always ``0.0`` (midpoint)
              but reserved for future multi-edge fan-out.
    """
    if start_side not in _VALID_SIDES:
        raise ValueError(f"Invalid start_side: {start_side!r}")
    if end_side not in _VALID_SIDES:
        raise ValueError(f"Invalid end_side: {end_side!r}")

    start = _side_midpoint(src_bbox, start_side)
    end = _side_midpoint(tgt_bbox, end_side)

    start_vertical = start_side in ("top", "bottom")

    # ---------- Aligned pairs: straight or Z-shape ----------
    if (start_side, end_side) in ALIGNED_PAIRS:
        if start_vertical:
            # top↔bottom pair: travel along y axis
            if abs(start["x"] - end["x"]) < alignment_tol:
                return [start, end], 0.0, 0.0
            mid_y = (start["y"] + end["y"]) / 2.0
            mid_y += _stagger_delta(stagger_index, stagger_total, stagger_spacing)
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
        mid_x = (start["x"] + end["x"]) / 2.0
        mid_x += _stagger_delta(stagger_index, stagger_total, stagger_spacing)
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
    # Pivot chosen so first segment extends along start_side's outward normal
    if start_vertical:
        # start = top/bottom  →  first segment vertical, pivot (start.x, end.y)
        return (
            [start, {"x": start["x"], "y": end["y"]}, end],
            0.0,
            0.0,
        )
    # start = left/right  →  first segment horizontal, pivot (end.x, start.y)
    return (
        [start, {"x": end["x"], "y": start["y"]}, end],
        0.0,
        0.0,
    )


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
