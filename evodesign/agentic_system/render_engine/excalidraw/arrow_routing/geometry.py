"""Path predicates and scores shared by every connector router.

Points are ``(x, y)`` tuples, boxes are ``(left, top, width, height)`` tuples,
and node bboxes are ``{"x", "y", "w", "h"}`` dicts, matching the callers.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ...shared.edge_crossing_detector import count_arrow_crossings
from ..edge_router import to_relative_points, waypoints_bbox

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]

# Keep adjacent governance lanes visibly distinct without consuming the
# narrow bottom margin of a compact cross-cutting frame.
PARALLEL_CHANNEL_CLEARANCE = 16.0


def _segment_hits_box(start: Point, end: Point, bbox: Box) -> bool:
    """Return whether a segment enters the strict interior of ``bbox``."""
    left, top, width, height = bbox
    right = left + width
    bottom = top + height
    if width <= 0 or height <= 0:
        return False

    # Liang-Barsky clipping keeps this check exact for horizontal, vertical,
    # and zero-length segments without introducing a geometry dependency.
    epsilon = 1e-6
    left += epsilon
    top += epsilon
    right -= epsilon
    bottom -= epsilon
    if left >= right or top >= bottom:
        return False

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    t_enter, t_exit = 0.0, 1.0
    for p, q in (
        (-dx, start[0] - left),
        (dx, right - start[0]),
        (-dy, start[1] - top),
        (dy, bottom - start[1]),
    ):
        if abs(p) <= epsilon:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            t_enter = max(t_enter, ratio)
        else:
            t_exit = min(t_exit, ratio)
        if t_enter >= t_exit:
            return False
    return t_enter < t_exit and t_exit > epsilon and t_enter < 1.0 - epsilon


def _path_is_clear(points: List[Point], obstacles: List[Box]) -> bool:
    return all(
        not _segment_hits_box(start, end, obstacle)
        for start, end in zip(points, points[1:])
        for obstacle in obstacles
    )


def _path_avoids_endpoint_interiors(
    points: List[Point],
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
) -> bool:
    """Reject interior crossings and connectors tangent to endpoint borders."""
    if len(points) < 2:
        return False

    def outward(endpoint, adjacent, box):
        x, y = endpoint
        dx, dy = adjacent[0] - x, adjacent[1] - y
        normals = []
        if abs(x - box["x"]) < 1e-6:
            normals.append((-1, 0))
        if abs(x - box["x"] - box["w"]) < 1e-6:
            normals.append((1, 0))
        if abs(y - box["y"]) < 1e-6:
            normals.append((0, -1))
        if abs(y - box["y"] - box["h"]) < 1e-6:
            normals.append((0, 1))
        return not normals or any(dx * nx + dy * ny > 1e-6 for nx, ny in normals)

    if not outward(points[0], points[1], source_bbox) or not outward(points[-1], points[-2], target_bbox):
        return False
    return _path_is_clear(points, [_box_tuple(source_bbox), _box_tuple(target_bbox)])


def _route_is_legal(
    points: List[Point],
    obstacles: List[Box],
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
) -> bool:
    """A route may neither enter a foreign node nor cut through its own ends."""
    return _path_is_clear(points, obstacles) and _path_avoids_endpoint_interiors(
        points, source_bbox, target_bbox
    )


def _path_length(points: List[Point]) -> float:
    return sum(
        abs(start[0] - end[0]) + abs(start[1] - end[1])
        for start, end in zip(points, points[1:])
    )


def _path_bend_count(points: List[Point]) -> int:
    """Count direction changes after ignoring duplicate path vertices."""
    directions: List[str] = []
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if abs(dx) <= 1e-6 and abs(dy) <= 1e-6:
            continue
        if abs(dx) <= 1e-6:
            direction = "vertical"
        elif abs(dy) <= 1e-6:
            direction = "horizontal"
        else:
            direction = "diagonal"
        if not directions or directions[-1] != direction:
            directions.append(direction)
    return max(0, len(directions) - 1)


def _is_orthogonal(points: List[Point]) -> bool:
    return all(
        abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6
        for a, b in zip(points, points[1:])
    )


def _compress_orthogonal_path(points: List[Point]) -> List[Point]:
    """Drop duplicate and collinear grid vertices without changing geometry."""
    compact: List[Point] = []
    for point in points:
        if compact and point == compact[-1]:
            continue
        if len(compact) >= 2:
            first, second = compact[-2], compact[-1]
            if (
                abs(first[0] - second[0]) <= 1e-6
                and abs(second[0] - point[0]) <= 1e-6
            ) or (
                abs(first[1] - second[1]) <= 1e-6
                and abs(second[1] - point[1]) <= 1e-6
            ):
                compact[-1] = point
                continue
        compact.append(point)
    return compact


def _box_tuple(bbox: Dict[str, float]) -> Box:
    return bbox["x"], bbox["y"], bbox["w"], bbox["h"]


def _bbox_center(bbox: Dict[str, float]) -> Point:
    return bbox["x"] + bbox["w"] / 2.0, bbox["y"] + bbox["h"] / 2.0


def _xy(waypoints: List[Dict[str, float]]) -> List[Point]:
    """``{"x", "y"}`` waypoints as float point tuples."""
    return [(float(point["x"]), float(point["y"])) for point in waypoints]


def _waypoints(points: List[Point]) -> List[Dict[str, float]]:
    """Point tuples as the ``{"x", "y"}`` waypoints ``edge_router`` emits."""
    return [{"x": x, "y": y} for x, y in points]


def _visible_arrows(arrows: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Return connectors that contribute to the rendered visual surface."""
    visible: List[Dict[str, Any]] = []
    for arrow in arrows or []:
        if arrow.get("type") != "arrow" or arrow.get("isDeleted"):
            continue
        try:
            opacity = float(arrow.get("opacity", 100) or 0)
        except (TypeError, ValueError):
            opacity = 100.0
        if opacity > 0:
            visible.append(arrow)
    return visible


def _absolute_arrow_points(arrows: Optional[List[Dict[str, Any]]]) -> List[Point]:
    """Collect existing route vertices used to seed clear grid channels."""
    points: List[Point] = []
    for arrow in _visible_arrows(arrows):
        origin_x = float(arrow.get("x", 0.0) or 0.0)
        origin_y = float(arrow.get("y", 0.0) or 0.0)
        for point in arrow.get("points") or []:
            if isinstance(point, dict):
                points.append((float(point.get("x", 0.0)), float(point.get("y", 0.0))))
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append((origin_x + float(point[0]), origin_y + float(point[1])))
    return points


def _arrow_path_fields(waypoints: List[Dict[str, float]], min_size: float = 1.0) -> Dict[str, Any]:
    """Origin, relative points and bbox size for an arrow on ``waypoints``."""
    origin_x, origin_y, relative = to_relative_points(waypoints)
    width, height = waypoints_bbox(waypoints)
    return {
        "x": origin_x,
        "y": origin_y,
        "width": max(min_size, width),
        "height": max(min_size, height),
        "points": relative,
    }


def _path_crossing_count(
    points: List[Point],
    existing_arrows: Optional[List[Dict[str, Any]]],
) -> int:
    if not existing_arrows:
        return 0
    origin_x = min(value[0] for value in points)
    origin_y = min(value[1] for value in points)
    candidate_arrow = {
        "id": "__route_candidate__",
        "type": "arrow",
        "x": origin_x,
        "y": origin_y,
        "points": [[x - origin_x, y - origin_y] for x, y in points],
    }
    return count_arrow_crossings(candidate_arrow, _visible_arrows(existing_arrows))


def _arrow_segments(arrow: Dict[str, Any]) -> List[Tuple[Point, Point]]:
    origin = (float(arrow.get("x", 0.0)), float(arrow.get("y", 0.0)))
    absolute: List[Point] = []
    for point in arrow.get("points") or []:
        if isinstance(point, dict):
            absolute.append((origin[0] + float(point.get("x", 0.0)), origin[1] + float(point.get("y", 0.0))))
        else:
            absolute.append((origin[0] + float(point[0]), origin[1] + float(point[1])))
    return list(zip(absolute, absolute[1:]))


def _path_parallel_channel_penalty(
    points: List[Any],
    existing_arrows: Optional[List[Dict[str, Any]]],
    clearance: float = PARALLEL_CHANNEL_CLEARANCE,
) -> float:
    """Score axis-aligned path segments that crowd existing edge channels.

    A small gap between two long, collinear segments is technically valid but
    renders like a single heavy line.  The penalty is proportional to the
    overlapping span and fades to zero at ``clearance`` pixels.  This metric
    is deliberately local to route selection and does not change crossing
    detection semantics.
    """
    if not existing_arrows or len(points) < 2:
        return 0.0

    normalized_points = [
        (float(point.get("x", 0.0)), float(point.get("y", 0.0)))
        if isinstance(point, dict)
        else (float(point[0]), float(point[1]))
        for point in points
    ]
    other_segments = [
        segment
        for arrow in _visible_arrows(existing_arrows)
        for segment in _arrow_segments(arrow)
    ]

    penalty = 0.0
    for start, end in zip(normalized_points, normalized_points[1:]):
        horizontal = abs(start[1] - end[1]) <= 1e-6
        vertical = abs(start[0] - end[0]) <= 1e-6
        if not (horizontal or vertical):
            continue
        start_axis, end_axis = (start[0], end[0]) if horizontal else (start[1], end[1])
        low, high = sorted((start_axis, end_axis))
        if high - low <= 1e-6:
            continue
        fixed = start[1] if horizontal else start[0]
        for other_start, other_end in other_segments:
            other_horizontal = abs(other_start[1] - other_end[1]) <= 1e-6
            other_vertical = abs(other_start[0] - other_end[0]) <= 1e-6
            if horizontal != other_horizontal or vertical != other_vertical:
                continue
            other_fixed = other_start[1] if horizontal else other_start[0]
            gap = abs(fixed - other_fixed)
            if gap >= clearance:
                continue
            other_low, other_high = sorted(
                (other_start[0], other_end[0]) if horizontal else (other_start[1], other_end[1])
            )
            overlap = max(0.0, min(high, other_high) - max(low, other_low))
            if overlap > 0.0:
                penalty += overlap * (clearance - gap) / clearance
    return penalty
