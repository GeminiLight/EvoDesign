# -*- coding: utf-8 -*-
"""
Excalidraw Arrow Adder - Add directional arrows to an Excalidraw manifest.
"""

import logging
import math
from copy import deepcopy
from heapq import heappop, heappush
from typing import Any, Dict, List, Optional, Tuple

from evo_diagram.agentic_system.common.semantic_ids import (
    group_frame_render_id,
    id_map_from_manifest,
    reverse_id_map,
)
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from ..shared.edge_crossing_detector import count_segment_crossings, detect_crossings
from ..shared.label_geometry import disjoint_segment_box_distance
from ..shared.edge_routing import (
    audit_sides,
    collect_relations,
    derive_routing_from_sides,
    extract_edge_port_hints,
    extract_side_from_port,
    find_shape_id,
    normalize_port,
    normalize_routing,
    relations_from_edge_data,
    resolve_edge_payload,
    shape_bbox,
)
from .converter import (
    _estimate_text_dimensions,
    _excalidraw_defaults,
    _generate_excalidraw_id,
)
from .edge_router import (
    compute_waypoints,
    to_relative_points,
    waypoints_bbox,
)

logger = logging.getLogger(__name__)

DEFAULT_STAGGER_SPACING = 50.0
DEFAULT_PORT_SPACING = 32.0
NODE_CLEARANCE = 24.0
_LOCAL_DETOUR_CLEARANCE = 16.0
MAX_EDGE_LABEL_WORDS = 5
_ARCHITECTURE_TYPES = {"architecture", "architecture_diagram"}
_MAX_OUTER_ROUTE_LENGTH_RATIO = 1.6
_MAX_CROSSCUTTING_ROUTE_LENGTH_RATIO = 1.8
# Keep adjacent governance lanes visibly distinct without consuming the
# narrow bottom margin of a compact cross-cutting frame.
_PARALLEL_CHANNEL_CLEARANCE = 16.0
_ROUTE_BEND_PENALTY = 36.0
_ROUTE_CROSSING_PENALTY = 1800.0
_ROUTE_DEVIATION_PENALTY = 0.01
_MAX_CLEAR_CHANNEL_LENGTH_RATIO = 1.35
_MAX_GENERIC_REROUTE_LENGTH_RATIO = 1.6
_MAX_GENERIC_EXTRA_BENDS = 4


def _segment_hits_box(
    start: Tuple[float, float],
    end: Tuple[float, float],
    bbox: Tuple[float, float, float, float],
) -> bool:
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


def _shape_obstacles(
    elements: List[Dict[str, Any]],
    id_map: Dict[str, str],
    source_id: str,
    target_id: str,
    excluded_ids: Optional[set[str]] = None,
) -> List[Tuple[float, float, float, float]]:
    """Collect drawable node boxes that an edge is not allowed to enter."""
    reverse_map = reverse_id_map(id_map)
    obstacles: List[Tuple[float, float, float, float]] = []
    shape_types = {"rectangle", "ellipse", "diamond", "embeddable", "iframe"}
    for element in elements:
        if not isinstance(element, dict) or element.get("isDeleted"):
            continue
        if element.get("id") in {source_id, target_id} | (excluded_ids or set()):
            continue
        if element.get("type") not in shape_types:
            continue
        semantic_id = reverse_map.get(str(element.get("id", "")), "")
        if semantic_id.endswith(":background") or semantic_id.endswith(":title"):
            continue
        try:
            bbox = (
                float(element.get("x", 0) or 0),
                float(element.get("y", 0) or 0),
                float(element.get("width", 0) or 0),
                float(element.get("height", 0) or 0),
            )
        except (TypeError, ValueError):
            continue
        if bbox[2] > 0 and bbox[3] > 0:
            # A route along an unrelated card's border looks connected to it,
            # even when it never enters the strict interior. Reserve a small
            # visible gap in every route candidate, including later port swaps.
            visible_border = (
                float(element.get("strokeWidth", 1.0) or 0.0) > 0
                and element.get("strokeColor") not in {"transparent", "none"}
                and float(element.get("opacity", 100)) > 0
            )
            padding = 6.0 if visible_border else 0.0
            obstacles.append((
                bbox[0] - padding, bbox[1] - padding,
                bbox[2] + 2.0 * padding, bbox[3] + 2.0 * padding,
            ))
    return obstacles


def _path_is_clear(
    points: List[Tuple[float, float]],
    obstacles: List[Tuple[float, float, float, float]],
) -> bool:
    return all(
        not _segment_hits_box(start, end, obstacle)
        for start, end in zip(points, points[1:])
        for obstacle in obstacles
    )


def _path_avoids_endpoint_interiors(
    points: List[Tuple[float, float]],
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
    endpoint_boxes = [
        (source_bbox["x"], source_bbox["y"], source_bbox["w"], source_bbox["h"]),
        (target_bbox["x"], target_bbox["y"], target_bbox["w"], target_bbox["h"]),
    ]
    return _path_is_clear(points, endpoint_boxes)


def _path_length(points: List[Tuple[float, float]]) -> float:
    return sum(
        abs(start[0] - end[0]) + abs(start[1] - end[1])
        for start, end in zip(points, points[1:])
    )


def _visible_arrows(
    arrows: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
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


def _path_bend_count(points: List[Tuple[float, float]]) -> int:
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


def _path_crossing_count(
    points: List[Tuple[float, float]],
    existing_arrows: Optional[List[Dict[str, Any]]],
) -> int:
    if not existing_arrows:
        return 0
    origin_x = min(value[0] for value in points)
    origin_y = min(value[1] for value in points)
    candidate_id = "__route_candidate__"
    candidate_arrow = {
        "id": candidate_id,
        "type": "arrow",
        "x": origin_x,
        "y": origin_y,
        "points": [[x - origin_x, y - origin_y] for x, y in points],
    }
    arrows = _visible_arrows(existing_arrows)
    return sum(
        1
        for first_id, second_id, _ in detect_crossings(arrows + [candidate_arrow])
        if candidate_id in {first_id, second_id}
    )


def _path_parallel_channel_penalty(
    points: List[Any],
    existing_arrows: Optional[List[Dict[str, Any]]],
    clearance: float = _PARALLEL_CHANNEL_CLEARANCE,
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

    normalized_points: List[Tuple[float, float]] = []
    for point in points:
        if isinstance(point, dict):
            normalized_points.append((float(point.get("x", 0.0)), float(point.get("y", 0.0))))
        else:
            normalized_points.append((float(point[0]), float(point[1])))

    def segments_for_arrow(arrow: Dict[str, Any]) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        origin = (float(arrow.get("x", 0.0)), float(arrow.get("y", 0.0)))
        raw_points = arrow.get("points") or []
        absolute: List[Tuple[float, float]] = []
        for point in raw_points:
            if isinstance(point, dict):
                absolute.append((origin[0] + float(point.get("x", 0.0)), origin[1] + float(point.get("y", 0.0))))
            else:
                absolute.append((origin[0] + float(point[0]), origin[1] + float(point[1])))
        return list(zip(absolute, absolute[1:]))

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
        for arrow in _visible_arrows(existing_arrows):
            for other_start, other_end in segments_for_arrow(arrow):
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


def _absolute_arrow_points(
    arrows: Optional[List[Dict[str, Any]]],
) -> List[Tuple[float, float]]:
    """Collect existing route vertices used to seed clear grid channels."""
    points: List[Tuple[float, float]] = []
    for arrow in _visible_arrows(arrows):
        origin_x = float(arrow.get("x", 0.0) or 0.0)
        origin_y = float(arrow.get("y", 0.0) or 0.0)
        for point in arrow.get("points") or []:
            if isinstance(point, dict):
                points.append(
                    (
                        float(point.get("x", 0.0)),
                        float(point.get("y", 0.0)),
                    )
                )
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append(
                    (
                        origin_x + float(point[0]),
                        origin_y + float(point[1]),
                    )
                )
    return points


def _compress_orthogonal_path(
    points: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    """Drop duplicate and collinear grid vertices without changing geometry."""
    compact: List[Tuple[float, float]] = []
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


def _orthogonal_visibility_route(
    start: Tuple[float, float],
    end: Tuple[float, float],
    obstacles: List[Tuple[float, float, float, float]],
    existing_arrows: Optional[List[Dict[str, Any]]],
    clearance: float,
    port_normals: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None,
) -> Optional[List[Tuple[float, float]]]:
    """Find a draw.io-style orthogonal route through a visibility grid.

    Nodes sit at candidate channel intersections derived from obstacle margins
    and existing connector vertices. Dijkstra state includes travel direction,
    allowing the scorer to prefer fewer bends and independent edge channels in
    addition to short paths.
    """
    visible_arrows = _visible_arrows(existing_arrows)
    expanded = [
        (
            left - clearance,
            top - clearance,
            width + 2.0 * clearance,
            height + 2.0 * clearance,
        )
        for left, top, width, height in obstacles
    ]

    x_values = {float(start[0]), float(end[0])}
    y_values = {float(start[1]), float(end[1])}
    for left, top, width, height in expanded:
        x_values.update((left, left + width))
        y_values.update((top, top + height))
    for x, y in _absolute_arrow_points(visible_arrows):
        x_values.update((x - clearance, x + clearance))
        y_values.update((y - clearance, y + clearance))

    xs = sorted(x_values)
    ys = sorted(y_values)

    def available(point: Tuple[float, float]) -> bool:
        return not any(
            left + 1e-6 < point[0] < left + width - 1e-6
            and top + 1e-6 < point[1] < top + height - 1e-6
            for left, top, width, height in expanded
        )

    points = {
        (x, y)
        for x in xs
        for y in ys
        if available((x, y))
    }
    if start not in points or end not in points:
        return None

    neighbors: Dict[Tuple[float, float], List[Tuple[Tuple[float, float], str]]] = {
        point: [] for point in points
    }
    for y in ys:
        row = sorted((point for point in points if point[1] == y), key=lambda item: item[0])
        for left_point, right_point in zip(row, row[1:]):
            if _path_is_clear([left_point, right_point], expanded):
                neighbors[left_point].append((right_point, "horizontal"))
                neighbors[right_point].append((left_point, "horizontal"))
    for x in xs:
        column = sorted((point for point in points if point[0] == x), key=lambda item: item[1])
        for top_point, bottom_point in zip(column, column[1:]):
            if _path_is_clear([top_point, bottom_point], expanded):
                neighbors[top_point].append((bottom_point, "vertical"))
                neighbors[bottom_point].append((top_point, "vertical"))

    start_state = (start, "")
    primary_axis = (
        "horizontal"
        if abs(start[1] - end[1]) <= 1e-6
        else "vertical"
        if abs(start[0] - end[0]) <= 1e-6
        else ""
    )
    distances = {start_state: 0.0}
    previous: Dict[
        Tuple[Tuple[float, float], str],
        Tuple[Tuple[float, float], str],
    ] = {}
    queue: List[Tuple[float, int, Tuple[float, float], str]] = []
    serial = 0
    heappush(queue, (0.0, serial, start, ""))
    final_state: Optional[Tuple[Tuple[float, float], str]] = None

    while queue:
        cost, _, point, direction = heappop(queue)
        state = (point, direction)
        if cost > distances.get(state, math.inf) + 1e-6:
            continue
        if point == end:
            final_state = state
            break
        for next_point, next_direction in neighbors[point]:
            if port_normals is not None:
                dx, dy = next_point[0] - point[0], next_point[1] - point[1]
                start_normal, end_normal = port_normals
                # The first/last grid steps must not fold back over the fixed
                # endpoint stubs. Perpendicular turns at a lead remain valid.
                if point == start and dx * start_normal[0] + dy * start_normal[1] < -1e-6:
                    continue
                if next_point == end and dx * end_normal[0] + dy * end_normal[1] > 1e-6:
                    continue
            distance = abs(next_point[0] - point[0]) + abs(next_point[1] - point[1])
            bend_cost = (
                _ROUTE_BEND_PENALTY
                if direction and direction != next_direction
                else 0.0
            )
            crossing_count = count_segment_crossings(
                (point[0], point[1], next_point[0], next_point[1]),
                visible_arrows,
            )
            deviation_cost = 0.0
            if primary_axis == "horizontal" and next_direction == "horizontal":
                deviation_cost = (
                    distance
                    * abs(point[1] - start[1])
                    * _ROUTE_DEVIATION_PENALTY
                )
            elif primary_axis == "vertical" and next_direction == "vertical":
                deviation_cost = (
                    distance
                    * abs(point[0] - start[0])
                    * _ROUTE_DEVIATION_PENALTY
                )
            next_cost = (
                cost
                + distance
                + bend_cost
                + deviation_cost
                + crossing_count * _ROUTE_CROSSING_PENALTY
            )
            next_state = (next_point, next_direction)
            if next_cost + 1e-6 >= distances.get(next_state, math.inf):
                continue
            distances[next_state] = next_cost
            previous[next_state] = state
            serial += 1
            heappush(queue, (next_cost, serial, next_point, next_direction))

    if final_state is None:
        return None

    route = [final_state[0]]
    state = final_state
    while state != start_state:
        state = previous[state]
        route.append(state[0])
    route.reverse()
    return _compress_orthogonal_path(route)


def _prefer_architecture_outer_route(
    waypoints: List[Dict[str, float]],
    start_side: str,
    end_side: str,
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
    obstacles: List[Tuple[float, float, float, float]],
    existing_arrows: Optional[List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, float]], str, str, float, float]:
    """Use an outer node face when it removes crossings from a long layer edge."""
    original = [
        (float(point["x"]), float(point["y"]))
        for point in waypoints
    ]
    original_crossings = _path_crossing_count(original, existing_arrows)
    if original_crossings == 0:
        return waypoints, start_side, end_side, 0.0, 0.0

    if start_side in {"top", "bottom"} and end_side in {"top", "bottom"}:
        side_pairs = (("right", "right"), ("left", "left"))
    elif start_side in {"left", "right"} and end_side in {"left", "right"}:
        side_pairs = (("bottom", "bottom"), ("top", "top"))
    else:
        return waypoints, start_side, end_side, 0.0, 0.0

    original_length = max(_path_length(original), 1.0)
    candidates: List[
        Tuple[int, float, List[Dict[str, float]], str, str, float, float]
    ] = []
    for candidate_start, candidate_end in side_pairs:
        candidate, focus_start, focus_end = compute_waypoints(
            candidate_start,
            candidate_end,
            source_bbox,
            target_bbox,
        )
        candidate = _avoid_node_intersections(
            candidate,
            obstacles,
            existing_arrows=existing_arrows,
        )
        absolute = [
            (float(point["x"]), float(point["y"]))
            for point in candidate
        ]
        candidate_length = _path_length(absolute)
        if (
            not _path_is_clear(absolute, obstacles)
            or not _path_avoids_endpoint_interiors(
                absolute,
                source_bbox,
                target_bbox,
            )
            or candidate_length > original_length * _MAX_OUTER_ROUTE_LENGTH_RATIO
        ):
            continue
        candidates.append(
            (
                _path_crossing_count(absolute, existing_arrows),
                candidate_length,
                candidate,
                candidate_start,
                candidate_end,
                focus_start,
                focus_end,
            )
        )

    if not candidates:
        return waypoints, start_side, end_side, 0.0, 0.0
    best = min(candidates, key=lambda item: (item[0], item[1]))
    if best[0] >= original_crossings:
        return waypoints, start_side, end_side, 0.0, 0.0
    return best[2], best[3], best[4], best[5], best[6]


def _prefer_crosscutting_lower_corridor_route(
    waypoints: List[Dict[str, float]],
    start_side: str,
    end_side: str,
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
    obstacles: List[Tuple[float, float, float, float]],
    existing_arrows: Optional[List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, float]], float]:
    """Move a crossing cross-cutting edge into the clear lower corridor.

    Cross-cutting nodes commonly sit beside the main architecture layers. A
    left-to-right edge between them should not compete with the data-layer
    horizontals above it. The corridor is derived from the lowest obstacle,
    leaving a small visual gap; the route is accepted when it removes a
    crossing or materially reduces a crowded parallel channel, while staying
    within a bounded length increase.
    """
    if start_side not in {"left", "right"} or end_side not in {"left", "right"}:
        return waypoints, 0.0
    source_center_y = source_bbox["y"] + source_bbox["h"] / 2.0
    target_center_y = target_bbox["y"] + target_bbox["h"] / 2.0
    if abs(source_center_y - target_center_y) > max(source_bbox["h"], target_bbox["h"]) + 24.0:
        return waypoints, 0.0
    original = [(float(point["x"]), float(point["y"])) for point in waypoints]
    original_crossings = _path_crossing_count(original, existing_arrows)
    if not obstacles:
        return waypoints, 0.0

    lowest_bottom = max(top + height for _, top, _, height in obstacles)
    start = original[0]
    end = original[-1]
    original_penalty = _path_parallel_channel_penalty(original, existing_arrows)
    original_length = max(_path_length(original), 1.0)
    candidates: List[Tuple[int, float, float, List[Tuple[float, float]]]] = []
    for lane_index in range(6):
        corridor_y = lowest_bottom + 2.0 + lane_index * _PARALLEL_CHANNEL_CLEARANCE
        candidate_points = [
            start,
            (start[0] + (22.0 if start_side == "right" else -22.0), start[1]),
            (start[0] + (22.0 if start_side == "right" else -22.0), corridor_y),
            (end[0] + (22.0 if end_side == "right" else -22.0), corridor_y),
            (end[0] + (22.0 if end_side == "right" else -22.0), end[1]),
            end,
        ]
        if (
            not _path_is_clear(candidate_points, obstacles)
            or not _path_avoids_endpoint_interiors(
                candidate_points,
                source_bbox,
                target_bbox,
            )
        ):
            continue
        candidate_length = _path_length(candidate_points)
        if candidate_length > original_length * _MAX_CROSSCUTTING_ROUTE_LENGTH_RATIO:
            continue
        candidates.append(
            (
                _path_crossing_count(candidate_points, existing_arrows),
                _path_parallel_channel_penalty(candidate_points, existing_arrows),
                candidate_length,
                candidate_points,
            )
        )

    if not candidates:
        return waypoints, 0.0
    candidate_crossings, candidate_penalty, candidate_length, candidate_points = min(
        candidates,
        key=lambda item: (item[0], item[1], item[2]),
    )
    if candidate_crossings > original_crossings:
        return waypoints, 0.0
    if candidate_crossings == original_crossings and candidate_penalty >= original_penalty:
        return waypoints, 0.0
    return (
        [{"x": x, "y": y} for x, y in candidate_points],
        candidate_length,
    )


def _avoid_node_intersections(
    waypoints: List[Dict[str, float]],
    obstacles: List[Tuple[float, float, float, float]],
    clearance: float = NODE_CLEARANCE,
    existing_arrows: Optional[List[Dict[str, Any]]] = None,
    endpoint_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
) -> List[Dict[str, float]]:
    """Route a connector through clear orthogonal channels when needed."""
    if len(waypoints) < 2:
        return waypoints

    def point(value: Tuple[float, float]) -> Dict[str, float]:
        return {"x": float(value[0]), "y": float(value[1])}

    def lead_point(
        endpoint: Tuple[float, float],
        adjacent: Tuple[float, float],
        distance: float,
    ) -> Tuple[float, float]:
        dx = adjacent[0] - endpoint[0]
        dy = adjacent[1] - endpoint[1]
        if abs(dx) >= abs(dy) and abs(dx) > 1e-6:
            return endpoint[0] + math.copysign(distance, dx), endpoint[1]
        if abs(dy) > 1e-6:
            return endpoint[0], endpoint[1] + math.copysign(distance, dy)
        return endpoint

    original = [(float(item["x"]), float(item["y"])) for item in waypoints]
    port_normals = (
        (original[1][0] - original[0][0], original[1][1] - original[0][1]),
        (original[-2][0] - original[-1][0], original[-2][1] - original[-1][1]),
    )

    def preserves_ports(candidate: List[Tuple[float, float]]) -> bool:
        """A detour must keep the authored entrance and exit directions."""
        for endpoint, neighbor in ((0, 1), (-1, -2)):
            dx = original[neighbor][0] - original[endpoint][0]
            dy = original[neighbor][1] - original[endpoint][1]
            cx = candidate[neighbor][0] - candidate[endpoint][0]
            cy = candidate[neighbor][1] - candidate[endpoint][1]
            if abs(dx * cy - dy * cx) > 1e-6 or dx * cx + dy * cy <= 0:
                return False
        return True

    spacing_clearance = min(clearance / 2.0, 12.0)
    clearance_obstacles = [
        (
            left - spacing_clearance,
            top - spacing_clearance,
            width + 2.0 * spacing_clearance,
            height + 2.0 * spacing_clearance,
        )
        for left, top, width, height in obstacles
    ]
    # Endpoint interiors are obstacles too: preserving the first/last segment
    # direction alone does not prevent a middle detour from cutting through
    # its own target. Keep their borders unpadded so attachment remains legal.
    if endpoint_boxes:
        obstacles = [*obstacles, *endpoint_boxes]
        clearance_obstacles.extend(endpoint_boxes)
    original_clear = _path_is_clear(original, obstacles)
    original_has_clearance = _path_is_clear(original, clearance_obstacles)
    visible_arrows = _visible_arrows(existing_arrows)
    if original_clear:
        original_crossings = _path_crossing_count(original, visible_arrows)
        original_parallel_penalty = _path_parallel_channel_penalty(
            original,
            visible_arrows,
        )
        if (
            original_crossings == 0
            and original_parallel_penalty <= 1e-6
            and original_has_clearance
        ):
            return waypoints

        start = original[0]
        end = original[-1]
        route_clearance = (
            spacing_clearance
            if original_crossings == 0 and original_parallel_penalty <= 1e-6
            else clearance
        )
        start_lead = lead_point(start, original[1], route_clearance)
        end_lead = lead_point(end, original[-2], route_clearance)
        crossing_aware_middle = _orthogonal_visibility_route(
            start_lead,
            end_lead,
            obstacles,
            visible_arrows,
            route_clearance,
            port_normals=port_normals,
        )
        if not crossing_aware_middle:
            return waypoints

        candidate = _compress_orthogonal_path(
            [start, *crossing_aware_middle, end]
        )
        original_length = max(_path_length(original), 1.0)
        candidate_length = _path_length(candidate)
        if (
            not _path_is_clear(candidate, obstacles)
            or not preserves_ports(candidate)
            or candidate_length
            > original_length * _MAX_GENERIC_REROUTE_LENGTH_RATIO
            or _path_bend_count(candidate)
            > _path_bend_count(original) + _MAX_GENERIC_EXTRA_BENDS
        ):
            return waypoints

        candidate_crossings = _path_crossing_count(candidate, visible_arrows)
        candidate_parallel_penalty = _path_parallel_channel_penalty(
            candidate,
            visible_arrows,
        )
        removes_crossing = candidate_crossings < original_crossings
        clears_crowded_channel = (
            candidate_crossings == original_crossings
            and original_parallel_penalty > 1e-6
            and candidate_parallel_penalty
            <= original_parallel_penalty * 0.5
        )
        creates_node_clearance = (
            not original_has_clearance
            and _path_is_clear(candidate, clearance_obstacles)
        )
        if not (removes_crossing or clears_crowded_channel or creates_node_clearance):
            return waypoints
        return [point(value) for value in candidate]

    local_route = list(original)
    local_clearance = min(clearance, _LOCAL_DETOUR_CLEARANCE)
    for obstacle in obstacles:
        hit_index = next(
            (
                index
                for index, (start, end) in enumerate(
                    zip(local_route, local_route[1:])
                )
                if _segment_hits_box(start, end, obstacle)
            ),
            None,
        )
        if hit_index is None:
            continue

        detour_start = local_route[hit_index]
        route_end = local_route[-1]
        left, top, width, height = obstacle
        right, bottom = left + width, top + height
        detours = [
            [
                detour_start,
                (detour_start[0], top - local_clearance),
                (route_end[0], top - local_clearance),
                route_end,
            ],
            [
                detour_start,
                (detour_start[0], bottom + local_clearance),
                (route_end[0], bottom + local_clearance),
                route_end,
            ],
            [
                detour_start,
                (left - local_clearance, detour_start[1]),
                (left - local_clearance, route_end[1]),
                route_end,
            ],
            [
                detour_start,
                (right + local_clearance, detour_start[1]),
                (right + local_clearance, route_end[1]),
                route_end,
            ],
        ]
        valid_detours = [
            detour for detour in detours
            if _path_is_clear(detour, obstacles)
            and preserves_ports(_compress_orthogonal_path(local_route[: hit_index + 1] + detour[1:]))
        ]
        if not valid_detours:
            continue
        chosen = min(
            valid_detours,
            key=lambda detour: (
                _path_crossing_count(detour, existing_arrows),
                _path_length(detour),
            ),
        )
        local_route = local_route[: hit_index + 1] + chosen[1:]

    if _path_is_clear(local_route, obstacles) and preserves_ports(_compress_orthogonal_path(local_route)):
        original = _compress_orthogonal_path(local_route)
        return [point(value) for value in original]

    start = original[0]
    end = original[-1]
    start_lead = lead_point(start, original[1], clearance)
    end_lead = lead_point(end, original[-2], clearance)
    shortest_middle = _orthogonal_visibility_route(
        start_lead,
        end_lead,
        obstacles,
        None,
        clearance,
        port_normals=port_normals,
    )
    if not shortest_middle:
        return waypoints

    shortest_candidate = _compress_orthogonal_path([start, *shortest_middle, end])
    if not _path_is_clear(shortest_candidate, obstacles) or not preserves_ports(shortest_candidate):
        return waypoints

    candidate = shortest_candidate
    if existing_arrows:
        crossing_aware_middle = _orthogonal_visibility_route(
            start_lead,
            end_lead,
            obstacles,
            existing_arrows,
            clearance,
            port_normals=port_normals,
        )
        if crossing_aware_middle:
            crossing_aware = _compress_orthogonal_path(
                [start, *crossing_aware_middle, end]
            )
            shortest_length = max(_path_length(shortest_candidate), 1.0)
            if (
                _path_is_clear(crossing_aware, obstacles)
                and preserves_ports(crossing_aware)
                and _path_length(crossing_aware)
                <= shortest_length * _MAX_CLEAR_CHANNEL_LENGTH_RATIO
                and _path_crossing_count(crossing_aware, existing_arrows)
                < _path_crossing_count(shortest_candidate, existing_arrows)
            ):
                candidate = crossing_aware

    original = candidate

    result: List[Dict[str, float]] = []
    for value in original:
        current = point(value)
        if not result or current != result[-1]:
            result.append(current)
    return result


def _prefer_clear_port_pair(
    start_side: str,
    end_side: str,
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
    obstacles: List[Tuple[float, float, float, float]],
) -> Tuple[str, str]:
    """Change ports only when the authored pair necessarily crosses a node."""
    authored, _, _ = compute_waypoints(
        start_side,
        end_side,
        source_bbox,
        target_bbox,
        port_spacing=0.0,
    )
    authored_points = [
        (float(point["x"]), float(point["y"])) for point in authored
    ]
    if (
        _path_is_clear(authored_points, obstacles)
        and _path_avoids_endpoint_interiors(
            authored_points,
            source_bbox,
            target_bbox,
        )
    ):
        return start_side, end_side

    source_x = source_bbox["x"] + source_bbox["w"] / 2.0
    source_y = source_bbox["y"] + source_bbox["h"] / 2.0
    target_x = target_bbox["x"] + target_bbox["w"] / 2.0
    target_y = target_bbox["y"] + target_bbox["h"] / 2.0
    horizontal_pair = (
        ("right", "left") if target_x >= source_x else ("left", "right")
    )
    vertical_pair = (
        ("bottom", "top") if target_y >= source_y else ("top", "bottom")
    )

    side_pairs = list(
        dict.fromkeys(
            [
                (start_side, end_side),
                horizontal_pair,
                vertical_pair,
            ]
        )
    )
    candidates: List[Tuple[float, int, str, str]] = []
    primary_pair_count = len(side_pairs)
    side_pairs.extend(
        pair for pair in (
            (start, end)
            for start in ("left", "right", "top", "bottom")
            for end in ("left", "right", "top", "bottom")
        ) if pair not in side_pairs
    )
    for pair_index, (candidate_start, candidate_end) in enumerate(side_pairs):
        # Try the remaining faces only when the ordinary flow directions have
        # no safe route; preserve the established ports in common cases.
        if pair_index == primary_pair_count and candidates:
            break
        waypoints, _, _ = compute_waypoints(
            candidate_start,
            candidate_end,
            source_bbox,
            target_bbox,
            port_spacing=0.0,
        )
        routed = _avoid_node_intersections(
            waypoints, obstacles,
            endpoint_boxes=[tuple(box[key] for key in ("x", "y", "w", "h")) for box in (source_bbox, target_bbox)],
        )
        points = [(float(point["x"]), float(point["y"])) for point in routed]
        if (
            not _path_is_clear(points, obstacles)
            or not _path_avoids_endpoint_interiors(
                points,
                source_bbox,
                target_bbox,
            )
        ):
            continue
        bends = max(0, len(points) - 2)
        score = _path_length(points) + bends * _ROUTE_BEND_PENALTY
        candidates.append(
            (score, bends, candidate_start, candidate_end)
        )

    if not candidates:
        return start_side, end_side
    _, _, best_start, best_end = min(candidates)
    return best_start, best_end


def _build_fixed_segments(points: List[List[float]]) -> Optional[List[Dict[str, Any]]]:
    """Lock middle elbow segments so explicit turns survive render/import."""
    if len(points) < 4:
        return None

    fixed_segments: List[Dict[str, Any]] = []
    for i in range(1, len(points) - 2):
        fixed_segments.append(
            {
                "start": points[i],
                "end": points[i + 1],
                "index": i + 1,
            }
        )
    return fixed_segments or None


def _normalize_label_payload(label_payload: Any) -> Optional[Dict[str, Any]]:
    """Normalize edge label payload into text styling fields."""
    if isinstance(label_payload, str):
        text = label_payload.strip()
        if not text:
            return None
        return {
            "text": text,
            "fontSize": 13,
            "fontFamily": 2,
            "strokeColor": "#374151",
            "textAlign": "center",
        }

    if not isinstance(label_payload, dict):
        return None

    text = label_payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    normalized: Dict[str, Any] = {
        "text": text,
        "fontSize": label_payload.get("fontSize", 13),
        "fontFamily": label_payload.get("fontFamily", 2),
        "strokeColor": label_payload.get("strokeColor", "#374151"),
        "textAlign": label_payload.get("textAlign", "center"),
    }

    if label_payload.get("verticalAlign") in {"top", "middle", "bottom"}:
        normalized["verticalAlign"] = label_payload["verticalAlign"]

    return normalized


# ---------------------------------------------------------------------------
# Edge-label sanity filter (2026-04-25 — user complaint about edge-text clutter).
#
# Acts as the deterministic backstop to the prompt-level "non-essential edge
# labels are forbidden" rule in STRUCTURE_TASK_PROMPT. Even when the LLM
# slips and emits a stop-verb / over-long / target-paraphrasing label, this
# filter drops it before it lands on the canvas.
# ---------------------------------------------------------------------------

# Generic direction-verbs and connectors that the arrow itself already
# encodes. Comparison is case-insensitive after stripping.
_STOP_LABELS: frozenset = frozenset({
    "next", "then", "after", "before", "follows", "follow",
    "leads to", "leads_to", "lead to",
    "goes to", "goes_to", "go to",
    "flows to", "flows_to", "flow to",
    "passes to", "passes_to", "pass to",
    "sent to", "sent_to", "sends to",
    "is part of", "part of", "part_of",
    "contains", "containing", "includes", "including",
    "has", "have", "is a", "is_a", "is an",
    "uses", "use", "using", "calls", "call",
    "to", "from", "and", "or",
    "→", "->", "=>", "⇒", ">",
})


def _node_label_lookup(structure_instantiation: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Build a {node_id -> node.label} map from structure_instantiation
    so we can detect when an edge label paraphrases its target node.

    Tolerates both ``{instantiation: {nodes: [...]}}`` and flat shapes.
    """
    inst = unwrap_structure_instantiation(structure_instantiation)
    nodes = inst.get("nodes") or []
    out: Dict[str, str] = {}
    for n in nodes:
        if isinstance(n, dict):
            nid = n.get("id")
            label = n.get("label")
            if isinstance(nid, str) and isinstance(label, str):
                out[nid] = label
    return out


def _merge_semantic_edge_labels(
    relations: List[Dict[str, Any]],
    structure_instantiation: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Restore semantic labels omitted by a layout response.

    Layout owns ports and routing, but it must not be able to erase a
    relationship label that Structure already validated. Keep layout endpoint
    records authoritative and fill only missing labels from the semantic edge
    with the same stable id.
    """
    structure = unwrap_structure_instantiation(structure_instantiation)
    semantic_by_id: Dict[str, Dict[str, Any]] = {
        str(edge.get("id")): edge
        for edge in structure.get("edges", []) or []
        if isinstance(edge, dict) and isinstance(edge.get("id"), str)
    }
    merged: List[Dict[str, Any]] = []
    for relation in relations:
        enriched = dict(relation)
        if not enriched.get("label"):
            semantic = semantic_by_id.get(str(enriched.get("id")))
            if semantic:
                label = semantic.get("label") or semantic.get("relation")
                if label:
                    enriched["label"] = label
        merged.append(enriched)
    return merged


def _should_drop_edge_label(
    label_text: str,
    source_ref: Any,
    target_ref: Any,
    node_labels: Dict[str, str],
    *,
    preserve_structural_labels: bool = False,
) -> Optional[str]:
    """Return a reason string (for logging) if the label should be dropped,
    or ``None`` to keep it. Three rules, in order:

    1. **stop-verb match** — generic direction-verbs the arrow already
       encodes (next / then / leads to / contains / has / uses / "→" / ...).
    2. **too long** — more than ``MAX_EDGE_LABEL_WORDS`` words is a description,
       not a relation. Mirrors the ``≤5 words`` rule in STRUCTURE_TASK_PROMPT.
    3. **paraphrases an endpoint** — when the source or target node's
       label appears as a substring inside the edge label, the edge text
       is just repeating what the destination shape already says.
    """
    if not isinstance(label_text, str):
        return None
    text = label_text.strip()
    if not text:
        return None  # already empty, nothing to drop
    if preserve_structural_labels:
        # Concept-map arrows alone do not express a predicate. Containment
        # suppression is handled explicitly before this filter; a long fact,
        # a modal qualifier, or "uses" must not silently lose its meaning.
        return None

    low = text.lower()

    if low in _STOP_LABELS:
        return f"stop-verb '{text}'"

    word_count = len(text.split())
    if word_count > MAX_EDGE_LABEL_WORDS:
        return f"too long ({word_count} words)"

    for ref in (target_ref, source_ref):
        ref_label = (node_labels.get(str(ref)) or "").strip().lower()
        if not ref_label:
            continue
        # Substring match either direction: edge label contains node label,
        # or node label contains edge label (handles abbreviations / partials).
        if ref_label in low or low in ref_label:
            role = "target" if ref is target_ref else "source"
            return f"paraphrases {role} node '{node_labels[str(ref)]}'"

    return None


def _build_label_path_points(
    ax: float,
    ay: float,
    dx: float,
    dy: float,
    arrow_elem: Dict[str, Any],
) -> List[List[float]]:
    """Build an absolute path polyline for label placement."""
    rel_points = arrow_elem.get("points")
    if isinstance(rel_points, list) and len(rel_points) >= 2:
        abs_points: List[List[float]] = []
        for point in rel_points:
            if not (
                isinstance(point, (list, tuple))
                and len(point) == 2
                and isinstance(point[0], (int, float))
                and isinstance(point[1], (int, float))
            ):
                abs_points = []
                break
            abs_points.append([float(ax + point[0]), float(ay + point[1])])
        if len(abs_points) >= 2:
            return abs_points

    return [[float(ax), float(ay)], [float(ax + dx), float(ay + dy)]]


def _segment_orientation(dx: float, dy: float) -> str:
    if abs(dy) < 1e-6:
        return "horizontal"
    if abs(dx) < 1e-6:
        return "vertical"
    return "diagonal"


def _choose_label_segment(path_points: List[List[float]], routing: str) -> Optional[Dict[str, float]]:
    """Choose the most readable path segment for a label."""
    segments: List[Dict[str, float]] = []
    for start, end in zip(path_points, path_points[1:]):
        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        orientation = _segment_orientation(dx, dy)
        length = abs(dx) if orientation == "horizontal" else abs(dy) if orientation == "vertical" else math.hypot(dx, dy)
        if length < 1:
            continue
        segments.append(
            {
                "start_x": float(start[0]),
                "start_y": float(start[1]),
                "end_x": float(end[0]),
                "end_y": float(end[1]),
                "mid_x": float((start[0] + end[0]) / 2),
                "mid_y": float((start[1] + end[1]) / 2),
                "dx": dx,
                "dy": dy,
                "length": float(length),
                "orientation": orientation,
            }
        )

    if not segments:
        return None

    if routing == "elbowed":
        horizontal = [segment for segment in segments if segment["orientation"] == "horizontal"]
        if horizontal:
            return max(horizontal, key=lambda segment: segment["length"])
        vertical = [segment for segment in segments if segment["orientation"] == "vertical"]
        if vertical:
            return max(vertical, key=lambda segment: segment["length"])

    if routing == "curved":
        non_diagonal = [segment for segment in segments if segment["orientation"] != "diagonal"]
        if non_diagonal:
            return max(non_diagonal, key=lambda segment: segment["length"])

    return max(segments, key=lambda segment: segment["length"])


def _compute_label_geometry(
    ax: float,
    ay: float,
    dx: float,
    dy: float,
    arrow_elem: Dict[str, Any],
    normalized_label: Dict[str, Any],
) -> Dict[str, float]:
    """Compute text box geometry from the arrow path instead of the raw endpoint midpoint."""
    dims = _estimate_text_dimensions(
        normalized_label["text"],
        int(normalized_label["fontSize"]),
    )
    width = float(dims["width"])
    height = float(dims["height"])

    if arrow_elem.get("elbowed"):
        routing = "elbowed"
    elif isinstance(arrow_elem.get("roundness"), dict):
        routing = "curved"
    else:
        routing = "straight"

    path_points = _build_label_path_points(ax, ay, dx, dy, arrow_elem)
    segment = _choose_label_segment(path_points, routing)
    if segment and segment["orientation"] == "horizontal" and segment["length"] < width + 16.0:
        vertical_segments = [
            _choose_label_segment([start, end], "straight")
            for start, end in zip(path_points, path_points[1:])
            if abs(start[0] - end[0]) < 1.0 and abs(start[1] - end[1]) >= height + 16.0
        ]
        if vertical_segments:
            segment = max(vertical_segments, key=lambda item: item["length"])

    if segment is None:
        mid_x = float(ax + dx / 2)
        mid_y = float(ay + dy / 2)
        return {
            "x": max(0.0, mid_x - width / 2),
            "y": max(0.0, mid_y - height / 2),
            "width": width,
            "height": height,
        }

    if segment["orientation"] == "horizontal":
        x = segment["mid_x"] - width / 2
        y = segment["mid_y"] - height - 8
    elif segment["orientation"] == "vertical":
        x = segment["mid_x"] + 8
        y = segment["mid_y"] - height / 2
    else:
        segment_length = max(segment["length"], 1.0)
        normal_x = -segment["dy"] / segment_length
        normal_y = segment["dx"] / segment_length
        offset = 14.0
        x = segment["mid_x"] + normal_x * offset - width / 2
        y = segment["mid_y"] + normal_y * offset - height / 2

    return {
        "x": max(0.0, x),
        "y": max(0.0, y),
        "width": width,
        "height": height,
    }


def _separate_final_channels(
    arrows: List[Dict[str, Any]],
    route_contexts: Dict[str, Dict[str, Any]],
) -> None:
    """Separate crowded dogleg channels without changing either endpoint."""
    for _ in range(2):
        changed = False
        for arrow in _visible_arrows(arrows):
            context = route_contexts.get(str(arrow.get("id", "")))
            points = _absolute_arrow_points([arrow])
            if context is None or len(points) != 4:
                continue
            middle = (points[1], points[2])
            vertical = abs(middle[0][0] - middle[1][0]) < 1e-6
            horizontal = abs(middle[0][1] - middle[1][1]) < 1e-6
            if vertical == horizontal or _path_length(list(middle)) < 24.0:
                continue
            axis = 0 if vertical else 1
            other_arrows = [item for item in arrows if item is not arrow]
            penalty = _path_parallel_channel_penalty(points, other_arrows)
            if penalty <= 1e-6:
                continue
            crossings = _path_crossing_count(points, other_arrows)
            length = _path_length(points)
            best = None
            for delta in (-16.0, -8.0, 8.0, 16.0):
                candidate = [list(point) for point in points]
                candidate[1][axis] += delta
                candidate[2][axis] += delta
                candidate_points = [tuple(point) for point in candidate]
                candidate_length = _path_length(candidate_points)
                if (
                    candidate_length > length + 32.0
                    or not all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6
                               for a, b in zip(candidate_points, candidate_points[1:]))
                    or not _path_is_clear(candidate_points, context["obstacles"])
                    or not _path_avoids_endpoint_interiors(
                        candidate_points, context["source_bbox"], context["target_bbox"]
                    )
                    or _path_crossing_count(candidate_points, other_arrows) > crossings
                ):
                    continue
                candidate_penalty = _path_parallel_channel_penalty(candidate_points, other_arrows)
                if candidate_penalty >= penalty - 1e-6:
                    continue
                score = (candidate_penalty, candidate_length, abs(delta))
                if best is None or score < best[0]:
                    best = (score, candidate_points)
            if best is None:
                continue
            candidate = [{"x": x, "y": y} for x, y in best[1]]
            ox, oy, relative = to_relative_points(candidate)
            width, height = waypoints_bbox(candidate)
            arrow.update({"x": ox, "y": oy, "points": relative,
                          "width": max(1.0, width), "height": max(1.0, height)})
            changed = True
        if not changed:
            break


def _spread_final_target_ports(
    arrows: List[Dict[str, Any]],
    route_contexts: Dict[str, Dict[str, Any]],
    spacing: float,
) -> None:
    """Separate incoming ports after route optimization has changed faces."""
    if spacing <= 0:
        return
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for arrow in _visible_arrows(arrows):
        context = route_contexts.get(str(arrow.get("id", "")))
        if context:
            groups.setdefault((context["target_ref"], context["end_side"]), []).append(arrow)

    for (_, side), siblings in groups.items():
        if len(siblings) < 2:
            continue
        axis = 0 if side in {"top", "bottom"} else 1
        box = route_contexts[str(siblings[0]["id"])]["target_bbox"]
        span = box["w"] if axis == 0 else box["h"]
        step = min(spacing, max(0.0, span - 16.0) / (len(siblings) - 1))
        if step <= 0:
            continue
        paths = {str(arrow["id"]): _absolute_arrow_points([arrow]) for arrow in siblings}
        # Preserve simple direct connections; changing their end would also
        # move their source or make a formerly orthogonal line diagonal.
        if any(len(points) < 3 for points in paths.values()):
            continue
        ordered = sorted(siblings, key=lambda arrow: (
            paths[str(arrow["id"])][-1][axis],
            paths[str(arrow["id"])][0][axis],
            str(arrow["id"]),
        ))
        positions = [paths[str(arrow["id"])][-1][axis] for arrow in ordered]
        if min(b - a for a, b in zip(positions, positions[1:])) >= step - 1e-6:
            continue
        center = box["x" if axis == 0 else "y"] + span / 2.0
        boundary = box["y" if axis == 0 else "x"]
        if side == "bottom":
            boundary += box["h"]
        elif side == "right":
            boundary += box["w"]
        replacements: Dict[str, Dict[str, Any]] = {}
        for rank, arrow in enumerate(ordered):
            arrow_id = str(arrow["id"])
            points = [list(point) for point in paths[arrow_id]]
            # The final segment must enter this actual face normally. Context
            # left over from a custom route must not shift a different face.
            if (
                abs(points[-1][1 - axis] - boundary) > 1e-6
                or abs(points[-2][axis] - points[-1][axis]) > 1e-6
            ):
                break
            coordinate = center + (rank - (len(ordered) - 1) / 2.0) * step
            points[-1][axis] = coordinate
            points[-2][axis] = coordinate
            candidate_points = [tuple(point) for point in points]
            context = route_contexts[arrow_id]
            if not (
                all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6
                    for a, b in zip(candidate_points, candidate_points[1:]))
                and _path_is_clear(candidate_points, context["obstacles"])
                and _path_avoids_endpoint_interiors(
                    candidate_points, context["source_bbox"], context["target_bbox"]
                )
            ):
                break
            candidate = [{"x": x, "y": y} for x, y in candidate_points]
            ox, oy, relative = to_relative_points(candidate)
            width, height = waypoints_bbox(candidate)
            replacements[arrow_id] = {
                **arrow, "x": ox, "y": oy, "points": relative,
                "width": max(1.0, width), "height": max(1.0, height),
            }
        if len(replacements) != len(siblings):
            continue
        trial = [replacements.get(str(arrow["id"]), arrow) for arrow in arrows]
        if len(detect_crossings(trial)) > len(detect_crossings(arrows)):
            continue
        for arrow in siblings:
            arrow.update(replacements[str(arrow["id"])])


def _reposition_edge_labels(
    elements: List[Dict[str, Any]],
    generated_elements: List[Dict[str, Any]],
) -> None:
    """Move edge labels to the nearest node- and foreign-edge-free position."""
    arrows = {
        str(element.get("id")): element
        for element in generated_elements
        if element.get("type") == "arrow" and element.get("id")
    }
    node_boxes = [
        (
            float(element.get("x", 0.0) or 0.0),
            float(element.get("y", 0.0) or 0.0),
            float(element.get("width", 0.0) or 0.0),
            float(element.get("height", 0.0) or 0.0),
        )
        for element in elements
        if element.get("type") not in {"arrow", "text", "image"}
        and not element.get("isDeleted")
        and not element.get("is_group")
    ]
    for element in elements:
        if not element.get("is_group") or element.get("isDeleted"):
            continue
        if float(element.get("opacity", 100)) <= 0 or element.get("strokeColor") in {"transparent", "none"}:
            continue
        left = float(element.get("x", 0.0) or 0.0)
        top = float(element.get("y", 0.0) or 0.0)
        width = float(element.get("width", 0.0) or 0.0)
        height = float(element.get("height", 0.0) or 0.0)
        # Labels may live inside a section, but must not straddle its outline.
        node_boxes.extend([
            (left, top, width, 0.0), (left, top + height, width, 0.0),
            (left, top, 0.0, height), (left + width, top, 0.0, height),
        ])
    placed: List[Tuple[float, float, float, float]] = []
    arrow_segments = {
        arrow_id: [
            (points[index], points[index + 1])
            for index in range(len(points) - 1)
            if points[index] != points[index + 1]
        ]
        for arrow_id, arrow in arrows.items()
        if len(points := _absolute_arrow_points([arrow])) >= 2
    }

    def overlaps(box: Tuple[float, float, float, float], obstacle: Tuple[float, float, float, float]) -> bool:
        x, y, width, height = box
        ox, oy, obstacle_width, obstacle_height = obstacle
        padding = 4.0
        return (
            x < ox + obstacle_width + padding
            and x + width > ox - padding
            and y < oy + obstacle_height + padding
            and y + height > oy - padding
        )

    def placement_candidates(geometry, own_segments):
        base_x, base_y = geometry["x"], geometry["y"]
        width, height = geometry["width"], geometry["height"]
        candidates = [(base_x, base_y)]
        for start, end in sorted(own_segments, key=lambda segment: -math.dist(*segment)):
            if abs(start[1] - end[1]) < 1e-6:
                available = abs(end[0] - start[0]) - width - 16.0
                if available < 0:
                    continue
                for fraction in (0.5, 0.0, 1.0, 0.25, 0.75):
                    x = min(start[0], end[0]) + 8.0 + fraction * available
                    candidates.extend([(x, start[1] - height - 8.0), (x, start[1] + 8.0)])
            elif abs(start[0] - end[0]) < 1e-6:
                available = abs(end[1] - start[1]) - height - 16.0
                if available < 0:
                    continue
                for fraction in (0.5, 0.0, 1.0, 0.25, 0.75):
                    y = min(start[1], end[1]) + 8.0 + fraction * available
                    candidates.extend([(start[0] + 8.0, y), (start[0] - width - 8.0, y)])
        candidates.extend((base_x + dx, base_y + dy) for dx, dy in (
            (0.0, -24.0), (0.0, 24.0), (-24.0, 0.0), (24.0, 0.0),
        ))
        return [(max(0.0, x), max(0.0, y), width, height) for x, y in candidates]

    def clear(candidate):
        if any(overlaps(candidate, obstacle) for obstacle in [*node_boxes, *placed]):
            return False
        padded = (candidate[0] - 3.0, candidate[1] - 3.0, candidate[2] + 6.0, candidate[3] + 6.0)
        return not any(
            _segment_hits_box(start, end, padded)
            for segments in arrow_segments.values() for start, end in segments
        )

    for label in generated_elements:
        if label.get("type") != "text" or str(label.get("containerId", "")) not in arrows:
            continue
        own_arrow = arrows[str(label["containerId"])]
        own_segments = arrow_segments.get(str(label["containerId"]), [])
        original_text = label.get("text", "")
        font_size = float(label.get("fontSize", 13))
        variants = [original_text]
        words = original_text.split()
        # Preserve every word. Only try a two-line label when the authored
        # form has no clear nearby placement; balanced breaks come first.
        breaks = sorted(range(1, len(words)), key=lambda index: abs(
            len(" ".join(words[:index])) - len(" ".join(words[index:]))
        ))[:6]
        variants.extend(" ".join(words[:index]) + "\n" + " ".join(words[index:]) for index in breaks)
        chosen = None
        nearest_clear = None
        default = None
        for variant_index, text in enumerate(variants):
            geometry = {key: float(label.get(key, 0.0) or 0.0) for key in ("x", "y", "width", "height")}
            if text:
                geometry = _compute_label_geometry(
                    ax=float(own_arrow.get("x", 0.0)), ay=float(own_arrow.get("y", 0.0)),
                    dx=float(own_arrow.get("width", 0.0)), dy=float(own_arrow.get("height", 0.0)),
                    arrow_elem=own_arrow, normalized_label={"text": text, "fontSize": font_size},
                )
            if default is None:
                default = (text, tuple(geometry[key] for key in ("x", "y", "width", "height")))
            for candidate in placement_candidates(geometry, own_segments):
                if not clear(candidate):
                    continue
                distance = min((disjoint_segment_box_distance(start, end, candidate)
                                for start, end in own_segments), default=0.0)
                if distance <= max(24.0, 1.5 * font_size):
                    chosen = (text, candidate)
                    break
                score = (distance, variant_index)
                if nearest_clear is None or score < nearest_clear[0]:
                    nearest_clear = (score, text, candidate)
            if chosen is not None:
                break
        if chosen is None:
            chosen = (nearest_clear[1], nearest_clear[2]) if nearest_clear else default
        text, box = chosen
        label.update(dict(zip(("x", "y", "width", "height"), box)))
        if text != original_text:
            label["text"] = text
            label["originalText"] = text
        placed.append(box)


def _find_element_by_excalidraw_id(elements: List[Dict[str, Any]], eid: str) -> Optional[Dict[str, Any]]:
    """Find an element in the elements list by its Excalidraw ID."""
    for elem in elements:
        if elem.get("id") == eid:
            return elem
    return None


def _build_lookup_store(elements: List[Dict[str, Any]], id_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Build a shape lookup store from Excalidraw elements for shared edge routing.

    The store maps `shape:{semantic_id}` to shape-like entries accepted by
    shared edge routing helpers.
    """
    store: Dict[str, Any] = {}
    # Build reverse map: excalidraw_id -> semantic_id
    reverse_map = reverse_id_map(id_map)

    for elem in elements:
        eid = elem.get("id", "")
        semantic_id = reverse_map.get(eid)
        if not semantic_id:
            continue
        # Create a shape-like entry for the shared lookup/geometry helpers.
        shape_key = f"shape:{semantic_id}"
        store[shape_key] = {
            "x": elem.get("x", 0),
            "y": elem.get("y", 0),
            "type": elem.get("type", "rectangle"),
            "props": {
                "w": elem.get("width", 100),
                "h": elem.get("height", 100),
            },
            "parentId": "page:page",
            "_excalidraw_id": eid,
        }
    return store


def _architecture_port_hint(
    source_ref: str,
    target_ref: str,
    source_shape: Dict[str, Any],
    target_shape: Dict[str, Any],
    node_group_ids: Dict[str, str],
    side_group_ids: set[str],
) -> Optional[Dict[str, str]]:
    """Choose architecture ports from layer semantics before raw geometry."""
    source_group = node_group_ids.get(source_ref, "")
    target_group = node_group_ids.get(target_ref, "")
    source_bbox = shape_bbox(source_shape)
    target_bbox = shape_bbox(target_shape)
    source_x = source_bbox["x"] + source_bbox["w"] / 2.0
    source_y = source_bbox["y"] + source_bbox["h"] / 2.0
    target_x = target_bbox["x"] + target_bbox["w"] / 2.0
    target_y = target_bbox["y"] + target_bbox["h"] / 2.0

    if target_group in side_group_ids or source_group in side_group_ids:
        return (
            {"start": "right", "end": "left"}
            if source_x <= target_x
            else {"start": "left", "end": "right"}
        )

    inter_layer = source_group and target_group and source_group != target_group
    row_separation = abs(target_y - source_y)
    min_vertical_gap = max(source_bbox["h"], target_bbox["h"]) + 24.0
    if inter_layer or row_separation >= min_vertical_gap:
        return (
            {"start": "bottom", "end": "top"}
            if source_y <= target_y
            else {"start": "top", "end": "bottom"}
        )
    return None


def add_excalidraw_arrows_to_manifest(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    *,
    port_spacing: Optional[float] = None,
    _adaptive_ports: bool = True,
    _report_crossings: bool = True,
) -> Dict[str, Any]:
    """
    Add arrow elements to an Excalidraw manifest based on structure_instantiation edges.

    Args:
        manifest: Excalidraw manifest with elements, files, _meta
        structure_instantiation: Semantic graph with edges

    Returns:
        Updated manifest with arrow elements added
    """
    if port_spacing is None:
        port_spacing = DEFAULT_PORT_SPACING
    if port_spacing < 0:
        raise ValueError("port_spacing must be non-negative")
    manifest = deepcopy(manifest)
    elements = manifest.get("elements", [])
    id_map = id_map_from_manifest(manifest)
    meta = manifest.get("_meta")
    edge_data = meta.get("edge_data", {}) if isinstance(meta, dict) else {}
    if not isinstance(edge_data, dict):
        edge_data = {}

    # Build a store for shared edge lookup and routing helpers.
    store = _build_lookup_store(elements, id_map)

    # Pick the authoritative edge source.
    #
    # Layout-derived ``edge_data`` is keyed by the same ID space as ``id_map``.
    # Prefer it over structure edges so arrows bind to the shapes that were
    # actually rendered, even when an upstream layout payload has diverged from
    # the original semantic ids.
    #
    # Falls back to structure edges when ``edge_data`` is missing (older
    # converter, unified mode, or hand-built manifests in tests).
    layout_relations = (
        relations_from_edge_data(edge_data, valid_element_ids=set(id_map))
        if edge_data
        else []
    )
    if layout_relations:
        relations = layout_relations
        logger.info(
            "[ArrowAdder] Using %d edges from manifest._meta.edge_data",
            len(relations),
        )
    else:
        relations = collect_relations(structure_instantiation)
        logger.info(
            "[ArrowAdder] edge_data empty - falling back to structure.edges (%d edges)",
            len(relations),
        )
    port_hints = extract_edge_port_hints(structure_instantiation)
    structure = unwrap_structure_instantiation(structure_instantiation)
    relations = _merge_semantic_edge_labels(relations, structure)
    chart_type_key = str(structure.get("chart_type", "")).lower()
    node_group_ids: Dict[str, str] = {
        str(node.get("id")): str(node.get("group_id"))
        for node in structure.get("nodes", []) or []
        if isinstance(node, dict) and node.get("id") and node.get("group_id")
    }
    core_node_ids = {
        str(node.get("id"))
        for node in structure.get("nodes", []) or []
        if isinstance(node, dict)
        and node.get("id")
        and str(node.get("class", "")).lower() in {"core", "core_concept"}
    }
    side_group_ids: set[str] = set()
    for group in structure.get("groups", []) or []:
        if not isinstance(group, dict) or not group.get("id"):
            continue
        group_id = str(group["id"])
        token = " ".join(
            str(group.get(key, "")).lower()
            for key in ("id", "class", "label")
        )
        if "cross" in token or "governance" in token:
            side_group_ids.add(group_id)
        for member_id in group.get("members", []) or []:
            if isinstance(member_id, str):
                node_group_ids.setdefault(member_id, group_id)
    group_frame_ids = {
        render_id
        for group in structure.get("groups", []) or []
        if isinstance(group, dict)
        for render_id in [group_frame_render_id(id_map, group.get("id"))]
        if render_id
    }
    concept_frames: List[Tuple[str, Dict[str, float]]] = []
    if chart_type_key in {"concept_map", "concept map", "conceptmap"}:
        rendered_frames = {
            render_id
            for semantic_id, render_id in id_map.items()
            if semantic_id.endswith(":background")
        }
        for element in elements:
            if not isinstance(element, dict) or element.get("id") not in rendered_frames:
                continue
            concept_frames.append((
                str(element["id"]),
                {
                    "x": float(element.get("x", 0.0) or 0.0),
                    "y": float(element.get("y", 0.0) or 0.0),
                    "w": float(element.get("width", 0.0) or 0.0),
                    "h": float(element.get("height", 0.0) or 0.0),
                },
            ))
        concept_frames.sort(key=lambda item: (item[1]["y"], item[1]["x"]))

    # Cached for the deterministic edge-label sanity filter further down. Maps
    # node id -> node.label so we can detect when an edge label simply
    # paraphrases the destination node (a common over-labeling pattern in
    # dense relation diagrams).
    node_label_map = _node_label_lookup(structure_instantiation)
    dropped_label_count = 0

    # ------------------------------------------------------------------
    # Fan-out stagger pre-computation (2026-05-06 AB test)
    # ------------------------------------------------------------------
    from collections import defaultdict

    _relation_sides: List[Dict[str, Any]] = []
    for rel in relations:
        source_ref = rel.get("source", "")
        target_ref = rel.get("target", "")
        edge_id = rel.get("id", "")
        edge_payload = resolve_edge_payload(edge_data, edge_id)

        source_shape_key = find_shape_id(store, source_ref, structure_instantiation)
        target_shape_key = find_shape_id(store, target_ref, structure_instantiation)
        if not (source_shape_key and target_shape_key):
            logger.warning(
                f"Could not find shapes for relation source='{source_ref}' -> target='{target_ref}'"
            )
            continue

        source_shape = store[source_shape_key]
        target_shape = store[target_shape_key]

        hinted = port_hints.get(edge_id) if isinstance(edge_id, str) else None
        if not hinted and isinstance(rel, dict):
            start_hint = normalize_port(rel.get("start"))
            end_hint = normalize_port(rel.get("end"))
            if start_hint and end_hint:
                hinted = {"start": start_hint, "end": end_hint}

        if not hinted and edge_payload:
            start_hint = extract_side_from_port(edge_payload.get("start"))
            end_hint = extract_side_from_port(edge_payload.get("end"))
            if start_hint or end_hint:
                hinted = {"start": start_hint, "end": end_hint}

        if str(structure.get("chart_type", "")).lower() in _ARCHITECTURE_TYPES:
            architecture_hint = _architecture_port_hint(
                str(source_ref),
                str(target_ref),
                source_shape,
                target_shape,
                node_group_ids,
                side_group_ids,
            )
            if architecture_hint:
                hinted = architecture_hint

        start_edge, end_edge = audit_sides(hinted, source_shape, target_shape)
        source_excalidraw_id = source_shape["_excalidraw_id"]
        target_excalidraw_id = target_shape["_excalidraw_id"]
        obstacles = _shape_obstacles(
            elements,
            id_map,
            source_excalidraw_id,
            target_excalidraw_id,
            excluded_ids=group_frame_ids,
        )
        start_edge, end_edge = _prefer_clear_port_pair(
            start_edge,
            end_edge,
            shape_bbox(source_shape),
            shape_bbox(target_shape),
            obstacles,
        )
        _relation_sides.append({
            "rel": rel,
            "source_shape_key": source_shape_key,
            "target_shape_key": target_shape_key,
            "source_shape": source_shape,
            "target_shape": target_shape,
            "source_excalidraw_id": source_excalidraw_id,
            "target_excalidraw_id": target_excalidraw_id,
            "start_edge": start_edge,
            "end_edge": end_edge,
            "edge_payload": edge_payload,
        })

    # Count how many edges share the same (source, start_side, end_side)
    _fanout_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)
    for rs in _relation_sides:
        key = (rs["rel"].get("source", ""), rs["start_edge"], rs["end_edge"])
        _fanout_counts[key] += 1

    # Port fan-out is independent of the target orientation: two edges leaving
    # the same face should not collapse onto the same midpoint merely because
    # they eventually use different target faces.  The target side is grouped
    # separately for fan-in at a shared destination face.
    _source_port_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    _target_port_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    _source_degrees: Dict[str, int] = defaultdict(int)
    _target_degrees: Dict[str, int] = defaultdict(int)
    for rs in _relation_sides:
        source_ref = rs["rel"].get("source", "")
        target_ref = rs["rel"].get("target", "")
        _source_port_counts[(source_ref, rs["start_edge"])] += 1
        _target_port_counts[(target_ref, rs["end_edge"])] += 1
        _source_degrees[source_ref] += 1
        _target_degrees[target_ref] += 1

    # Port order and corridor order solve different problems. Ports follow the
    # opposite endpoint's visual order, while bend corridors put the farthest
    # branch closest to the source. Keeping them separate prevents a wide
    # fan-out from cutting across its own nearer branches.
    _source_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    _target_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    _corridor_groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for rs in _relation_sides:
        rel = rs["rel"]
        _source_groups[(rel.get("source", ""), rs["start_edge"])].append(rs)
        _target_groups[(rel.get("target", ""), rs["end_edge"])].append(rs)
        _corridor_groups[(rel.get("source", ""), rs["start_edge"], rs["end_edge"])].append(rs)

    def _shape_center(shape: Dict[str, Any]) -> Tuple[float, float]:
        bbox = shape_bbox(shape)
        return bbox["x"] + bbox["w"] / 2.0, bbox["y"] + bbox["h"] / 2.0

    def _port_order_key(item: Dict[str, Any], shape_key: str, side: str) -> Tuple[float, float, str]:
        center_x, center_y = _shape_center(item[shape_key])
        if side == "left":
            primary, secondary = center_y, center_x
        elif side == "right":
            primary, secondary = center_y, -center_x
        elif side == "top":
            primary, secondary = center_x, center_y
        else:
            primary, secondary = center_x, -center_y
        return primary, secondary, str(item["rel"].get("id", ""))

    for siblings in _source_groups.values():
        side = siblings[0]["start_edge"]
        ordered = sorted(
            siblings,
            key=lambda item: _port_order_key(item, "target_shape", side),
        )
        for rank, item in enumerate(ordered):
            item["source_port_index"] = rank

    for siblings in _target_groups.values():
        side = siblings[0]["end_edge"]
        ordered = sorted(
            siblings,
            key=lambda item: _port_order_key(item, "source_shape", side),
        )
        for rank, item in enumerate(ordered):
            item["target_port_index"] = rank

    for siblings in _corridor_groups.values():
        if len(siblings) <= 1:
            siblings[0]["stagger_index"] = 0
            continue
        start_side = siblings[0]["start_edge"]
        cross_axis = 0 if start_side in {"top", "bottom"} else 1
        travel_axis = 1 - cross_axis

        def _cross_distance(item: Dict[str, Any]) -> float:
            source_center = _shape_center(item["source_shape"])
            target_center = _shape_center(item["target_shape"])
            return abs(target_center[cross_axis] - source_center[cross_axis])

        ordered = sorted(siblings, key=_cross_distance, reverse=True)
        source_axis = _shape_center(siblings[0]["source_shape"])[travel_axis]
        average_target_axis = sum(
            _shape_center(item["target_shape"])[travel_axis] for item in siblings
        ) / len(siblings)
        ranks = range(len(ordered)) if average_target_axis >= source_axis else reversed(range(len(ordered)))
        for rank, item in zip(ranks, ordered):
            item["stagger_index"] = rank

    _all_source_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    _all_target_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rs in _relation_sides:
        _all_source_groups[rs["rel"].get("source", "")].append(rs)
        _all_target_groups[rs["rel"].get("target", "")].append(rs)
    for siblings in _all_source_groups.values():
        for axis, key in ((0, "source_x_index"), (1, "source_y_index")):
            for rank, item in enumerate(sorted(siblings, key=lambda value: _shape_center(value["target_shape"])[axis])):
                item[key] = rank
    for siblings in _all_target_groups.values():
        for axis, key in ((0, "target_x_index"), (1, "target_y_index")):
            for rank, item in enumerate(sorted(siblings, key=lambda value: _shape_center(value["source_shape"])[axis])):
                item[key] = rank

    if chart_type_key in {"concept_map", "concept map", "conceptmap"}:
        repeated_groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        for rs in _relation_sides:
            rel = rs["rel"]
            label_payload = rel.get("label", "")
            if not label_payload and rs.get("edge_payload"):
                label_payload = rs["edge_payload"].get("label", "")
            normalized = _normalize_label_payload(label_payload)
            if not normalized:
                continue
            label_key = " ".join(normalized["text"].lower().split())
            repeated_groups[("source", str(rel.get("source", "")), label_key)].append(rs)
            repeated_groups[("target", str(rel.get("target", "")), label_key)].append(rs)
        for (role, _, label_key), siblings in repeated_groups.items():
            if len(siblings) < 2:
                continue
            if (
                role == "source"
                and str(siblings[0]["rel"].get("source", "")) in core_node_ids
                and (
                    label_key == "organized into"
                    or all(item["rel"].get("evidence_basis") == "structural" for item in siblings)
                )
            ):
                for item in siblings:
                    item["suppress_repeated_label"] = True
                continue
            # Independently routed edges need independently readable
            # predicates, even when they share a source and wording. A single
            # label is valid only for an actual shared branching trunk.

    # ------------------------------------------------------------------
    # Second pass: render arrows with stagger
    # ------------------------------------------------------------------
    new_arrows: List[Dict[str, Any]] = []
    route_contexts: Dict[str, Dict[str, Any]] = {}
    for rs in _relation_sides:
        rel = rs["rel"]
        source_ref = rel.get("source", "")
        target_ref = rel.get("target", "")
        edge_id = rel.get("id", "")
        edge_payload = rs["edge_payload"]
        source_shape = rs["source_shape"]
        target_shape = rs["target_shape"]
        source_excalidraw_id = rs["source_excalidraw_id"]
        target_excalidraw_id = rs["target_excalidraw_id"]
        start_edge = rs["start_edge"]
        end_edge = rs["end_edge"]

        # Compute stagger index for this edge
        fanout_key = (source_ref, start_edge, end_edge)
        stagger_index = int(rs.get("stagger_index", 0))
        stagger_total = _fanout_counts[fanout_key]

        source_port_key = (source_ref, start_edge)
        target_port_key = (target_ref, end_edge)
        source_port_index = int(rs.get("source_port_index", 0))
        target_port_index = int(rs.get("target_port_index", 0))

        # Compute an explicit polyline path for the arrow.
        src_bbox = shape_bbox(source_shape)
        tgt_bbox = shape_bbox(target_shape)
        abs_waypoints, focus_s, focus_e = compute_waypoints(
            start_edge, end_edge, src_bbox, tgt_bbox,
            stagger_index=stagger_index,
            stagger_total=stagger_total,
            stagger_spacing=DEFAULT_STAGGER_SPACING,
            start_port_index=source_port_index,
            start_port_total=_source_port_counts[source_port_key],
            end_port_index=target_port_index,
            end_port_total=_target_port_counts[target_port_key],
            port_spacing=port_spacing,
        )
        obstacles = _shape_obstacles(
            elements,
            id_map,
            source_excalidraw_id,
            target_excalidraw_id,
            excluded_ids=group_frame_ids,
        )
        abs_waypoints = _avoid_node_intersections(
            abs_waypoints,
            obstacles,
            existing_arrows=new_arrows,
            endpoint_boxes=[tuple(box[key] for key in ("x", "y", "w", "h")) for box in (src_bbox, tgt_bbox)],
        )
        ox, oy, rel_points = to_relative_points(abs_waypoints)
        bbox_w, bbox_h = waypoints_bbox(abs_waypoints)

        # Label-geometry helpers below still expect a straight-line
        # (ax, ay)→(ax+dx, ay+dy) summary.  Derive that from the polyline
        # endpoints so existing label placement keeps working.
        ax = abs_waypoints[0]["x"]
        ay = abs_waypoints[0]["y"]
        dx = abs_waypoints[-1]["x"] - ax
        dy = abs_waypoints[-1]["y"] - ay
        start_center = {"x": ax, "y": ay}
        end_center = {"x": abs_waypoints[-1]["x"], "y": abs_waypoints[-1]["y"]}

        edge_seed = [
            "edge",
            edge_id or f"{source_ref}->{target_ref}",
            source_ref,
            target_ref,
            stagger_index,
            start_edge,
            end_edge,
        ]
        arrow_id = _generate_excalidraw_id(edge_seed)
        arrow_elem = {
            **_excalidraw_defaults(["arrow", edge_seed]),
            "id": arrow_id,
            "type": "arrow",
            "strokeColor": "#64748B",
            "strokeWidth": 1.5,
            "roughness": 0,
            "meta": {
                "semantic_edge_id": edge_id,
                "source": source_ref,
                "target": target_ref,
            },
            "x": ox,
            "y": oy,
            "width": max(1.0, bbox_w),
            "height": max(1.0, bbox_h),
            "points": rel_points,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "lastCommittedPoint": None,
        }
        route_contexts[arrow_id] = {
            "source_ref": source_ref,
            "target_ref": target_ref,
            "source_group": node_group_ids.get(source_ref, ""),
            "target_group": node_group_ids.get(target_ref, ""),
            "source_bbox": src_bbox,
            "target_bbox": tgt_bbox,
            "obstacles": obstacles,
            "start_side": start_edge,
            "end_side": end_edge,
            "source_x_index": int(rs.get("source_x_index", 0)),
            "source_y_index": int(rs.get("source_y_index", 0)),
            "target_x_index": int(rs.get("target_x_index", 0)),
            "target_y_index": int(rs.get("target_y_index", 0)),
            "source_degree": _source_degrees[source_ref],
            "target_degree": _target_degrees[target_ref],
            "cross_branch": bool(
                edge_payload and edge_payload.get("_layoutCrossBranch")
            ),
        }

        # Apply edge routing mode.
        #
        # routing 同时控制 ``elbowed`` 和 ``roundness``，让 LLM 的三选一真正生效：
        #
        #   routing=straight → elbowed=False, roundness=None  (普通直线)
        #   routing=elbowed  → elbowed=True,  roundness=None  (带弯折的尖锐线)
        #   routing=curved   → elbowed=True,  roundness={"type": 2} (带弯折的平滑曲线)
        routing_hint: Optional[str] = (
            normalize_routing(edge_payload.get("routing")) if edge_payload else None
        )

        if routing_hint is None:
            routing_hint = normalize_routing(rel.get("routing"))

        if routing_hint is None:
            # Diagram-type-aware fallback — preserves identity signals (e.g.
            # mindmap radial branches must be curved, not elbowed).
            chart_type = unwrap_structure_instantiation(structure_instantiation).get("chart_type")
            routing_hint = derive_routing_from_sides(start_edge, end_edge, chart_type)

        if routing_hint == "straight":
            arrow_elem["elbowed"] = False
            arrow_elem["roundness"] = None
        elif routing_hint == "curved":
            arrow_elem["elbowed"] = True
            arrow_elem["roundness"] = {"type": 2}
        elif routing_hint == "elbowed":
            # Elbowed: explicit polyline with corner routing (no binding).
            # Distinct from straight — has intermediate turns.
            arrow_elem["elbowed"] = True
            arrow_elem["roundness"] = None
        else:
            # Unknown / None — treat as straight polyline.
            arrow_elem["elbowed"] = False
            arrow_elem["roundness"] = None

        if edge_payload:
            if "startArrowhead" in edge_payload:
                arrow_elem["startArrowhead"] = edge_payload["startArrowhead"]
            if "endArrowhead" in edge_payload:
                arrow_elem["endArrowhead"] = edge_payload["endArrowhead"]

        # Apply edge styling from edge_data if available
        if edge_payload:
            if "strokeColor" in edge_payload:
                arrow_elem["strokeColor"] = edge_payload["strokeColor"]
            if "strokeWidth" in edge_payload:
                arrow_elem["strokeWidth"] = edge_payload["strokeWidth"]
            if "strokeStyle" in edge_payload:
                arrow_elem["strokeStyle"] = edge_payload["strokeStyle"]
            if "opacity" in edge_payload:
                arrow_elem["opacity"] = edge_payload["opacity"]
            if "roughness" in edge_payload:
                arrow_elem["roughness"] = edge_payload["roughness"]
            props = edge_payload.get("props", {})
            if isinstance(props, dict):
                if "color" in props:
                    arrow_elem["strokeColor"] = props["color"]

            # Note: LLM-supplied ``waypoints`` are no longer honored.  The
            # 2026-04-22 schema removed the field; ``compute_waypoints``
            # above produces the authoritative polyline from the audited
            # (start_side, end_side) pair.

        new_arrows.append(arrow_elem)

        # Handle edge labels
        label_payload: Any = rel.get("label", "")
        if (not label_payload) and edge_payload:
            label_payload = edge_payload.get("label", "")

        normalized_label = _normalize_label_payload(label_payload)
        if normalized_label and edge_payload and edge_payload.get("_suppressLabel"):
            normalized_label = None
            dropped_label_count += 1
        if normalized_label and rs.get("suppress_repeated_label"):
            normalized_label = None
            dropped_label_count += 1

        # Deterministic stop-label filter (2026-04-25 — backstop for the
        # "non-essential edge labels are forbidden" prompt rule). Drops
        # generic direction-verbs, over-long descriptions, and labels that
        # paraphrase their target node. Logs each drop at INFO; aggregate
        # WARNING after the loop if anything was dropped.
        if normalized_label:
            drop_reason = _should_drop_edge_label(
                normalized_label.get("text", ""),
                source_ref,
                target_ref,
                node_label_map,
                preserve_structural_labels=chart_type_key
                in {"concept_map", "concept map", "conceptmap"},
            )
            if drop_reason:
                logger.info(
                    "[ArrowAdder] dropping edge label edge=%s text=%r reason=%s",
                    edge_id,
                    normalized_label.get("text", ""),
                    drop_reason,
                )
                normalized_label = None
                dropped_label_count += 1

        if normalized_label:
            label_geometry = _compute_label_geometry(
                ax=ax,
                ay=ay,
                dx=dx,
                dy=dy,
                arrow_elem=arrow_elem,
                normalized_label=normalized_label,
            )
            text_seed = [
                "edge_label",
                edge_id or arrow_id,
                normalized_label["text"],
            ]
            text_id = _generate_excalidraw_id(text_seed)
            text_elem = {
                **_excalidraw_defaults(["edge_label", text_seed]),
                "id": text_id,
                "type": "text",
                "x": label_geometry["x"],
                "y": label_geometry["y"],
                "width": label_geometry["width"],
                "height": label_geometry["height"],
                "text": normalized_label["text"],
                "fontSize": normalized_label["fontSize"],
                "fontFamily": normalized_label["fontFamily"],
                "strokeColor": normalized_label["strokeColor"],
                "textAlign": normalized_label["textAlign"],
                "verticalAlign": normalized_label.get("verticalAlign", "middle"),
                "containerId": arrow_id,
                "originalText": normalized_label["text"],
                "autoResize": True,
                "lineHeight": 1.15,
                "meta": {"semantic_edge_id": edge_id},
            }
            arrow_elem["boundElements"] = [{"type": "text", "id": text_id}]
            new_arrows.append(text_elem)

    # Fan-out is a local readability improvement, but it must not trade away
    # global route clarity.  Compare against the same scene with midpoint
    # ports and keep the lower-crossing candidate.  This makes the feature
    # deterministic and naturally falls back on dense layouts where moving a
    # shared source face would introduce extra crossings.
    arrow_elems = [
        element
        for element in new_arrows
        if element.get("type") == "arrow"
        and float(element.get("opacity", 100) or 0) > 0
    ]
    if arrow_elems:
        # Draw.io-style global port reconsideration is a geometry primitive,
        # not a chart-type feature. The layout model supplies the first route,
        # then a deterministic coordinate-descent pass tries the two facing
        # axes and their L-shaped combinations. A candidate is committed only
        # when it lowers the complete scene's crossing count.
        for _ in range(8):
            crossing_pairs = detect_crossings(arrow_elems)
            current_crossings = len(crossing_pairs)
            if current_crossings == 0:
                break
            crossing_arrow_ids = {
                arrow_id
                for first_id, second_id, _ in crossing_pairs
                for arrow_id in (first_id, second_id)
            }
            crossing_neighbors: Dict[str, set[str]] = {
                arrow_id: set() for arrow_id in crossing_arrow_ids
            }
            for first_id, second_id, _ in crossing_pairs:
                crossing_neighbors[first_id].add(second_id)
                crossing_neighbors[second_id].add(first_id)
            best_update: Optional[
                Tuple[int, float, Dict[str, Any], List[Dict[str, float]], str, str]
            ] = None
            for arrow in arrow_elems:
                if str(arrow.get("id", "")) not in crossing_arrow_ids:
                    continue
                context = route_contexts.get(str(arrow.get("id", "")))
                if not context:
                    continue
                source_bbox = context["source_bbox"]
                target_bbox = context["target_bbox"]
                source_center = (
                    source_bbox["x"] + source_bbox["w"] / 2.0,
                    source_bbox["y"] + source_bbox["h"] / 2.0,
                )
                target_center = (
                    target_bbox["x"] + target_bbox["w"] / 2.0,
                    target_bbox["y"] + target_bbox["h"] / 2.0,
                )
                horizontal = (
                    ("right", "left")
                    if target_center[0] >= source_center[0]
                    else ("left", "right")
                )
                vertical = (
                    ("bottom", "top")
                    if target_center[1] >= source_center[1]
                    else ("top", "bottom")
                )
                side_pairs = list(dict.fromkeys([
                    (context["start_side"], context["end_side"]),
                    horizontal,
                    vertical,
                    (horizontal[0], vertical[1]),
                    (vertical[0], horizontal[1]),
                ]))
                current_points = _absolute_arrow_points([arrow])
                current_length = max(_path_length(current_points), 1.0)
                other_arrows = [item for item in arrow_elems if item is not arrow]
                conflicting_ids = crossing_neighbors.get(str(arrow.get("id", "")), set())
                conflicting_arrows = [
                    item
                    for item in other_arrows
                    if str(item.get("id", "")) in conflicting_ids
                ]
                for start_side, end_side in side_pairs:
                    candidate, _, _ = compute_waypoints(
                        start_side,
                        end_side,
                        source_bbox,
                        target_bbox,
                        start_port_index=(
                            context["source_x_index"]
                            if start_side in {"top", "bottom"}
                            else context["source_y_index"]
                        ),
                        start_port_total=context["source_degree"],
                        end_port_index=(
                            context["target_x_index"]
                            if end_side in {"top", "bottom"}
                            else context["target_y_index"]
                        ),
                        end_port_total=context["target_degree"],
                        port_spacing=port_spacing,
                    )
                    candidate = _avoid_node_intersections(
                        candidate,
                        context["obstacles"],
                        # Seed the visibility grid only with the routes that
                        # currently conflict with this edge. The complete
                        # scene is still scored below before committing.
                        existing_arrows=conflicting_arrows,
                    )
                    points = [(float(point["x"]), float(point["y"])) for point in candidate]
                    candidate_length = _path_length(points)
                    if (
                        not _path_is_clear(points, context["obstacles"])
                        or not _path_avoids_endpoint_interiors(
                            points,
                            source_bbox,
                            target_bbox,
                        )
                        or candidate_length > current_length * 1.6
                    ):
                        continue
                    candidate_arrow = deepcopy(arrow)
                    ox, oy, rel_points = to_relative_points(candidate)
                    bbox_w, bbox_h = waypoints_bbox(candidate)
                    candidate_arrow.update({
                        "x": ox,
                        "y": oy,
                        "width": max(1.0, bbox_w),
                        "height": max(1.0, bbox_h),
                        "points": rel_points,
                    })
                    trial = [candidate_arrow if item is arrow else item for item in arrow_elems]
                    trial_crossings = len(detect_crossings(trial))
                    if trial_crossings >= current_crossings:
                        continue
                    update = (
                        trial_crossings,
                        candidate_length,
                        arrow,
                        candidate,
                        start_side,
                        end_side,
                    )
                    if best_update is None or update[:2] < best_update[:2]:
                        best_update = update
            if best_update is None:
                break
            _, _, arrow, candidate, start_side, end_side = best_update
            ox, oy, rel_points = to_relative_points(candidate)
            bbox_w, bbox_h = waypoints_bbox(candidate)
            arrow.update({
                "x": ox,
                "y": oy,
                "width": max(1.0, bbox_w),
                "height": max(1.0, bbox_h),
                "points": rel_points,
            })
            context = route_contexts[str(arrow["id"])]
            context["start_side"] = start_side
            context["end_side"] = end_side
            for binding in arrow.get("boundElements", []) or []:
                if binding.get("type") != "text":
                    continue
                label = next(
                    (item for item in new_arrows if item.get("id") == binding.get("id")),
                    None,
                )
                if label is None:
                    continue
                endpoints = _absolute_arrow_points([arrow])
                geometry = _compute_label_geometry(
                    endpoints[0][0],
                    endpoints[0][1],
                    endpoints[-1][0] - endpoints[0][0],
                    endpoints[-1][1] - endpoints[0][1],
                    arrow,
                    label,
                )
                label.update(geometry)

        # Long concept-map cross-section relations belong on an outside
        # corridor. The
        # regular router intentionally ignores group backgrounds as obstacles,
        # so without this composition-aware pass a dependency can run straight
        # through an unrelated band even though it avoids every node.
        if len(concept_frames) >= 3:
            frame_index = {
                frame_id: index
                for index, (frame_id, _) in enumerate(concept_frames)
            }

            def containing_frame(box: Dict[str, float]) -> Optional[str]:
                center_x = box["x"] + box["w"] / 2.0
                center_y = box["y"] + box["h"] / 2.0
                for frame_id, frame in concept_frames:
                    if (
                        frame["x"] <= center_x <= frame["x"] + frame["w"]
                        and frame["y"] <= center_y <= frame["y"] + frame["h"]
                    ):
                        return frame_id
                return None

            frame_by_id = dict(concept_frames)
            min_left = min(frame["x"] for _, frame in concept_frames)
            max_right = max(frame["x"] + frame["w"] for _, frame in concept_frames)
            corridor_margin = 28.0
            band_clearance = 14.0
            for arrow in arrow_elems:
                context = route_contexts.get(str(arrow.get("id", "")))
                if not context or not context.get("cross_branch"):
                    continue
                source_frame_id = containing_frame(context["source_bbox"])
                target_frame_id = containing_frame(context["target_bbox"])
                if not source_frame_id or not target_frame_id:
                    continue
                source_frame_index = frame_index[source_frame_id]
                target_frame_index = frame_index[target_frame_id]
                if abs(target_frame_index - source_frame_index) < 2:
                    continue

                source_box = context["source_bbox"]
                target_box = context["target_bbox"]
                source_frame = frame_by_id[source_frame_id]
                target_frame = frame_by_id[target_frame_id]
                downward = target_frame_index > source_frame_index
                source_x = source_box["x"] + source_box["w"] / 2.0
                target_x = target_box["x"] + target_box["w"] / 2.0
                source_y = (
                    source_box["y"] + source_box["h"]
                    if downward
                    else source_box["y"]
                )
                target_y = target_box["y"] if downward else target_box["y"] + target_box["h"]
                source_gap_y = (
                    source_frame["y"] + source_frame["h"] + band_clearance
                    if downward
                    else source_frame["y"] - band_clearance
                )
                target_gap_y = (
                    target_frame["y"] - band_clearance
                    if downward
                    else target_frame["y"] + target_frame["h"] + band_clearance
                )
                route_candidates: List[
                    Tuple[int, float, List[Dict[str, float]], str]
                ] = []
                other_arrows = [item for item in arrow_elems if item is not arrow]

                # First consider clear rails inside the band composition. A
                # draw.io-style router derives these channels from obstacle
                # boundaries instead of sending every long relation around
                # the page perimeter. Candidate rails stay in the whitespace
                # immediately beside nodes and are accepted only after full
                # obstacle and crossing checks below.
                interior_corridors = {source_x, target_x}
                for left, _, width, _ in context["obstacles"]:
                    interior_corridors.update((
                        left - band_clearance,
                        left + width + band_clearance,
                    ))
                source_ports = {source_x}
                source_margin = 8.0
                for offset_index in range(1, int(context["source_degree"]) + 2):
                    offset = float(offset_index) * float(port_spacing)
                    for candidate_x in (source_x - offset, source_x + offset):
                        if (
                            source_box["x"] + source_margin
                            <= candidate_x
                            <= source_box["x"] + source_box["w"] - source_margin
                        ):
                            source_ports.add(candidate_x)

                for source_port_x in sorted(source_ports):
                    for corridor_x in sorted(interior_corridors):
                        if not (
                            min_left + band_clearance
                            < corridor_x
                            < max_right - band_clearance
                        ):
                            continue
                        raw_candidate = [
                            (source_port_x, source_y),
                            (source_port_x, source_gap_y),
                            (corridor_x, source_gap_y),
                            (corridor_x, target_gap_y),
                            (target_x, target_gap_y),
                            (target_x, target_y),
                        ]
                        compressed = _compress_orthogonal_path(raw_candidate)
                        if (
                            not _path_is_clear(compressed, context["obstacles"])
                            or not _path_avoids_endpoint_interiors(
                                compressed,
                                source_box,
                                target_box,
                            )
                        ):
                            continue
                        route_candidates.append((
                            _path_crossing_count(compressed, other_arrows),
                            _path_length(compressed),
                            [{"x": x, "y": y} for x, y in compressed],
                            "bottom" if downward else "top",
                        ))

                # The exterior rails remain a robust fallback when every
                # internal channel is blocked by a populated intermediate
                # band. Scoring crossings first preserves readability; length
                # then naturally favors a clear internal rail when available.
                for corridor_x, side in (
                    (min_left - corridor_margin, "left"),
                    (max_right + corridor_margin, "right"),
                ):
                    side_source_x = (
                        source_box["x"]
                        if side == "left"
                        else source_box["x"] + source_box["w"]
                    )
                    side_source_y = source_box["y"] + source_box["h"] / 2.0
                    raw_candidates = [
                        [
                            (source_x, source_y),
                            (source_x, source_gap_y),
                            (corridor_x, source_gap_y),
                            (corridor_x, target_gap_y),
                            (target_x, target_gap_y),
                            (target_x, target_y),
                        ],
                        [
                            (side_source_x, side_source_y),
                            (corridor_x, side_source_y),
                            (corridor_x, target_gap_y),
                            (target_x, target_gap_y),
                            (target_x, target_y),
                        ],
                        # Escape above a downward source (or below an upward
                        # one) before entering an exterior rail. A source in
                        # the middle of a populated row cannot reach the rail
                        # through its row peers, and dropping through its
                        # local fan-out can cross several meaningful edges.
                        [
                            (source_x, source_box["y"] if downward else source_box["y"] + source_box["h"]),
                            (source_x, source_box["y"] - 24.0 if downward else source_box["y"] + source_box["h"] + 24.0),
                            (corridor_x, source_box["y"] - 24.0 if downward else source_box["y"] + source_box["h"] + 24.0),
                            (corridor_x, target_gap_y),
                            (target_x, target_gap_y),
                            (target_x, target_y),
                        ],
                    ]
                    for candidate_index, raw_candidate in enumerate(raw_candidates):
                        compressed = _compress_orthogonal_path(raw_candidate)
                        if (
                            not _path_is_clear(compressed, context["obstacles"])
                            or not _path_avoids_endpoint_interiors(
                                compressed,
                                source_box,
                                target_box,
                            )
                        ):
                            continue
                        route_candidates.append((
                            _path_crossing_count(compressed, other_arrows),
                            _path_length(compressed),
                            [{"x": x, "y": y} for x, y in compressed],
                            (
                                ("top" if downward else "bottom") if candidate_index == 2
                                else "bottom" if raw_candidate[0][0] == source_x and downward
                                else "top" if raw_candidate[0][0] == source_x
                                else side
                            ),
                        ))
                if not route_candidates:
                    continue
                _, _, candidate, candidate_start_side = min(
                    route_candidates,
                    key=lambda item: (item[0], item[1]),
                )
                ox, oy, rel_points = to_relative_points(candidate)
                bbox_w, bbox_h = waypoints_bbox(candidate)
                arrow.update({
                    "x": ox,
                    "y": oy,
                    "width": max(1.0, bbox_w),
                    "height": max(1.0, bbox_h),
                    "points": rel_points,
                })
                context["start_side"] = candidate_start_side
                context["end_side"] = "top" if downward else "bottom"
                # A path-length midpoint would put the predicate beside the
                # outer canvas edge. Keep the semantic label, but attach it to
                # the final horizontal approach where readers naturally
                # reconnect the perimeter route with its target section.
                retained_bindings: List[Dict[str, Any]] = []
                for binding in arrow.get("boundElements", []) or []:
                    if binding.get("type") != "text" or not binding.get("id"):
                        retained_bindings.append(binding)
                        continue
                    label = next(
                        (
                            element
                            for element in new_arrows
                            if str(element.get("id", "")) == str(binding["id"])
                        ),
                        None,
                    )
                    if label is None:
                        continue
                    label_width = float(label.get("width", 0.0) or 0.0)
                    label_height = float(label.get("height", 0.0) or 0.0)
                    approach_x = float(candidate[-2]["x"])
                    if approach_x < target_x:
                        label_x = target_x - label_width - 18.0
                    else:
                        label_x = target_x + 18.0
                    label_y = (
                        target_gap_y - label_height - 8.0
                        if downward
                        else target_gap_y + 8.0
                    )
                    label.update({
                        "x": max(0.0, label_x),
                        "y": max(0.0, label_y),
                        "containerId": None,
                        "meta": {
                            "semantic_edge_id": arrow.get("meta", {}).get(
                                "semantic_edge_id"
                            ),
                        },
                    })
                if retained_bindings:
                    arrow["boundElements"] = retained_bindings
                else:
                    arrow.pop("boundElements", None)

    if str(structure.get("chart_type", "")).lower() in _ARCHITECTURE_TYPES:
        while True:
            current_crossings = len(detect_crossings(arrow_elems))
            best_update: Optional[
                Tuple[int, float, Dict[str, Any], List[Dict[str, float]], str, str]
            ] = None
            for arrow in arrow_elems:
                context = route_contexts.get(str(arrow.get("id", "")))
                if not context or arrow.get("boundElements"):
                    continue
                source_ref = context["source_ref"]
                target_ref = context["target_ref"]
                is_crosscutting = (
                    context.get("source_group") in side_group_ids
                    or context.get("target_group") in side_group_ids
                )
                if (
                    not is_crosscutting
                    and (
                        _source_degrees[source_ref] != 1
                        or _target_degrees[target_ref] != 1
                    )
                ):
                    continue
                current_points = [
                    {
                        "x": float(arrow.get("x", 0.0)) + float(point[0]),
                        "y": float(arrow.get("y", 0.0)) + float(point[1]),
                    }
                    for point in arrow.get("points", [])
                ]
                other_arrows = [item for item in arrow_elems if item is not arrow]
                crosscutting_candidate = None
                if is_crosscutting:
                    crosscutting_candidate, _ = _prefer_crosscutting_lower_corridor_route(
                        current_points,
                        context["start_side"],
                        context["end_side"],
                        context["source_bbox"],
                        context["target_bbox"],
                        context["obstacles"],
                        other_arrows,
                )
                candidate, start_side, end_side, _, _ = _prefer_architecture_outer_route(
                    current_points,
                    context["start_side"],
                    context["end_side"],
                    context["source_bbox"],
                    context["target_bbox"],
                    context["obstacles"],
                    other_arrows,
                )
                used_crosscutting_candidate = False
                if crosscutting_candidate and crosscutting_candidate != current_points:
                    candidate = crosscutting_candidate
                    start_side = context["start_side"]
                    end_side = context["end_side"]
                    used_crosscutting_candidate = True
                if candidate == current_points:
                    continue
                candidate_points = [
                    (float(point["x"]), float(point["y"]))
                    for point in candidate
                ]
                if not _path_avoids_endpoint_interiors(
                    candidate_points,
                    context["source_bbox"],
                    context["target_bbox"],
                ):
                    continue
                candidate_arrow = deepcopy(arrow)
                ox, oy, rel_points = to_relative_points(candidate)
                bbox_w, bbox_h = waypoints_bbox(candidate)
                candidate_arrow.update({
                    "x": ox,
                    "y": oy,
                    "width": max(1.0, bbox_w),
                    "height": max(1.0, bbox_h),
                    "points": rel_points,
                })
                trial_arrows = [
                    candidate_arrow if item is arrow else item
                    for item in arrow_elems
                ]
                trial_crossings = len(detect_crossings(trial_arrows))
                if trial_crossings > current_crossings:
                    continue
                if trial_crossings == current_crossings and not (
                    used_crosscutting_candidate
                    and _path_parallel_channel_penalty(candidate, other_arrows)
                    < _path_parallel_channel_penalty(current_points, other_arrows)
                ):
                    continue
                candidate_length = _path_length([
                    (float(point["x"]), float(point["y"]))
                    for point in candidate
                ])
                update = (
                    trial_crossings,
                    candidate_length,
                    arrow,
                    candidate,
                    start_side,
                    end_side,
                )
                if best_update is None or update[:2] < best_update[:2]:
                    best_update = update
            if best_update is None:
                break
            _, _, arrow, candidate, start_side, end_side = best_update
            ox, oy, rel_points = to_relative_points(candidate)
            bbox_w, bbox_h = waypoints_bbox(candidate)
            arrow.update({
                "x": ox,
                "y": oy,
                "width": max(1.0, bbox_w),
                "height": max(1.0, bbox_h),
                "points": rel_points,
            })
            context = route_contexts[str(arrow["id"])]
            context["start_side"] = start_side
            context["end_side"] = end_side

    _spread_final_target_ports(arrow_elems, route_contexts, port_spacing)
    _separate_final_channels(arrow_elems, route_contexts)
    _reposition_edge_labels(elements, new_arrows)

    if chart_type_key in {"concept_map", "concept map", "conceptmap"}:
        # Excalidraw ignores authored x/y for text bound to an arrow when
        # exporting, and places it back on the path. Concept predicates need
        # the obstacle-free positions computed above. Keep semantic ownership
        # and an editor group while exporting them as independent text.
        arrows_by_id = {element["id"]: element for element in new_arrows if element.get("type") == "arrow"}
        arrows_by_semantic_id = {
            (arrow.get("meta") or {}).get("semantic_edge_id"): arrow_id
            for arrow_id, arrow in arrows_by_id.items()
        }
        for label in new_arrows:
            arrow_id = label.get("containerId") or arrows_by_semantic_id.get(
                (label.get("meta") or {}).get("semantic_edge_id")
            )
            if label.get("type") != "text" or arrow_id not in arrows_by_id:
                continue
            arrow = arrows_by_id[arrow_id]
            group_id = f"relation:{arrow_id}"
            label["containerId"] = None
            label.setdefault("meta", {})["semantic_arrow_id"] = arrow_id
            label["groupIds"] = [group_id]
            arrow["groupIds"] = [group_id]
            arrow["boundElements"] = [binding for binding in arrow.get("boundElements", []) if binding.get("id") != label["id"]]

    if _adaptive_ports and port_spacing > 0:
        midpoint_manifest = add_excalidraw_arrows_to_manifest(
            manifest,
            structure_instantiation,
            port_spacing=0.0,
            _adaptive_ports=False,
            _report_crossings=False,
        )
        midpoint_arrows = [
            element
            for element in midpoint_manifest.get("elements", [])
            if element.get("type") == "arrow"
        ]
        fanout_crossings = len(detect_crossings(arrow_elems))
        midpoint_crossings = len(detect_crossings(midpoint_arrows))
        if midpoint_crossings < fanout_crossings:
            logger.info(
                "[ArrowAdder] midpoint ports selected (%d crossings vs %d with fan-out)",
                midpoint_crossings,
                fanout_crossings,
            )
            return midpoint_manifest

    elements.extend(new_arrows)
    manifest["elements"] = elements

    # Observational crossing check — warn-only, no manifest changes.
    # Reports arrows whose polylines intersect (shared-endpoint
    # convergences are excluded).  The warning signal is intended for
    # future Layout-side iteration; we never modify already-committed
    # geometry here.
    crossings = detect_crossings(arrow_elems)
    if crossings and _report_crossings:
        for a_id, b_id, meta in crossings:
            logger.warning(
                "[CrossingDetector] Arrow %s crosses %s (segment a=%s, b=%s)",
                a_id,
                b_id,
                meta.get("segment_index_a"),
                meta.get("segment_index_b"),
            )
        logger.warning(
            "[CrossingDetector] %d edge crossing pair(s) detected in manifest",
            len(crossings),
        )

    if dropped_label_count and _report_crossings:
        logger.warning(
            "[ArrowAdder] suppressed %d non-informative or repeated edge label(s)",
            dropped_label_count,
        )

    return manifest


def rebuild_excalidraw_arrows(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    """Recompute arrow geometry after a deterministic node layout pass.

    Unified scenes already contain LLM-authored arrows. When a post-processor
    moves their endpoint shapes, those coordinates become stale. Remove the
    old arrows and their bound labels, clear reverse bindings, then delegate
    geometry to the same router used by pipeline mode. Semantic mappings and
    authored connector styling are restored on the rebuilt elements.
    """
    source = deepcopy(manifest)
    elements = [
        element
        for element in source.get("elements", [])
        if isinstance(element, dict)
    ]
    old_arrows = {
        str(element.get("id")): element
        for element in elements
        if element.get("type") == "arrow" and element.get("id")
    }
    if not old_arrows:
        return add_excalidraw_arrows_to_manifest(source, structure_instantiation)

    old_styles: Dict[str, Dict[str, Any]] = {}
    old_semantic_edge_ids: set[str] = set()
    for arrow in old_arrows.values():
        meta = arrow.get("meta")
        edge_id = str(meta.get("semantic_edge_id", "")) if isinstance(meta, dict) else ""
        if edge_id:
            old_semantic_edge_ids.add(edge_id)
            old_styles[edge_id] = {
                key: arrow[key]
                for key in (
                    "strokeColor",
                    "strokeWidth",
                    "strokeStyle",
                    "opacity",
                    "startArrowhead",
                    "endArrowhead",
                )
                if key in arrow
            }

    old_arrow_ids = set(old_arrows)
    old_label_ids = {
        str(element.get("id"))
        for element in elements
        if element.get("type") == "text"
        and (
            str(element.get("containerId", "")) in old_arrow_ids
            or (
                isinstance(element.get("meta"), dict)
                and str(element["meta"].get("semantic_edge_id", ""))
                in old_semantic_edge_ids
            )
        )
        and element.get("id")
    }
    edge_data = (source.get("_meta") or {}).get("edge_data")
    if isinstance(edge_data, dict):
        for element in elements:
            if str(element.get("id")) not in old_label_ids:
                continue
            edge_id = (element.get("meta") or {}).get("semantic_edge_id")
            if not edge_id:
                owner = old_arrows.get(str(element.get("containerId")), {})
                edge_id = (owner.get("meta") or {}).get("semantic_edge_id")
            payload = edge_data.get(edge_id)
            if not isinstance(payload, dict):
                continue
            label = _normalize_label_payload(payload.get("label"))
            if label is None:
                label = _normalize_label_payload(element.get("text"))
            if label is None:
                continue
            # Feed edited typography into routing before measuring/repositioning
            # labels. Restoring it only afterward would leave stale text boxes.
            label.update({
                key: element[key]
                for key in ("fontSize", "fontFamily", "strokeColor", "textAlign", "verticalAlign")
                if key in element
            })
            payload["label"] = label
    removed_ids = old_arrow_ids | old_label_ids
    retained: List[Dict[str, Any]] = []
    for element in elements:
        if str(element.get("id", "")) in removed_ids:
            continue
        bound_elements = element.get("boundElements")
        if isinstance(bound_elements, list):
            element["boundElements"] = [
                binding
                for binding in bound_elements
                if not (
                    isinstance(binding, dict)
                    and str(binding.get("id", "")) in removed_ids
                )
            ]
        retained.append(element)
    source["elements"] = retained

    rebuilt = add_excalidraw_arrows_to_manifest(source, structure_instantiation)
    id_map = {key: value for key, value in id_map_from_manifest(rebuilt).items() if value not in removed_ids}
    semantic_edge_ids = {
        str(edge.get("id"))
        for edge in unwrap_structure_instantiation(structure_instantiation).get("edges", []) or []
        if isinstance(edge, dict) and edge.get("id")
    }
    for edge_id in semantic_edge_ids:
        id_map.pop(edge_id, None)
    for element in rebuilt.get("elements", []):
        if not isinstance(element, dict):
            continue
        meta = element.get("meta")
        edge_id = str(meta.get("semantic_edge_id", "")) if isinstance(meta, dict) else ""
        if not edge_id:
            continue
        if element.get("type") == "text":
            id_map[f"{edge_id}:label"] = str(element.get("id", ""))
            continue
        if element.get("type") != "arrow":
            continue
        element.update(old_styles.get(edge_id, {}))
        id_map[edge_id] = str(element.get("id", ""))

    meta = rebuilt.setdefault("_meta", {})
    if isinstance(meta, dict):
        meta["id_map"] = id_map
    return rebuilt
