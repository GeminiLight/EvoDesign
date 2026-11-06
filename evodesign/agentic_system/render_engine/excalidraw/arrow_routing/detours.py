"""Per-edge route repairs: node avoidance and alternative face pairs."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

from evodesign.agentic_system.common.semantic_ids import reverse_id_map

from ..edge_router import compute_waypoints
from .geometry import (
    PARALLEL_CHANNEL_CLEARANCE,
    Box,
    Point,
    _bbox_center,
    _box_tuple,
    _compress_orthogonal_path,
    _path_bend_count,
    _path_crossing_count,
    _path_is_clear,
    _path_length,
    _path_parallel_channel_penalty,
    _route_is_legal,
    _visible_arrows,
    _waypoints,
    _xy,
    _segment_hits_box,
)
from .grid_router import ROUTE_BEND_PENALTY, _orthogonal_visibility_route

NODE_CLEARANCE = 24.0
_LOCAL_DETOUR_CLEARANCE = 16.0
_MAX_OUTER_ROUTE_LENGTH_RATIO = 1.6
_MAX_CROSSCUTTING_ROUTE_LENGTH_RATIO = 1.8
_MAX_CLEAR_CHANNEL_LENGTH_RATIO = 1.35
_MAX_GENERIC_REROUTE_LENGTH_RATIO = 1.6
_MAX_GENERIC_EXTRA_BENDS = 4
_SIDES = ("left", "right", "top", "bottom")

ObstacleIndex = List[Tuple[Any, Box]]


def _obstacle_index(
    elements: List[Dict[str, Any]],
    id_map: Dict[str, str],
    excluded_ids: Optional[Set[str]] = None,
) -> ObstacleIndex:
    """Drawable node boxes an edge may not enter, keyed by element id."""
    reverse_map = reverse_id_map(id_map)
    index: ObstacleIndex = []
    shape_types = {"rectangle", "ellipse", "diamond", "embeddable", "iframe"}
    for element in elements:
        if not isinstance(element, dict) or element.get("isDeleted"):
            continue
        if element.get("id") in (excluded_ids or set()):
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
            index.append((
                element.get("id"),
                (bbox[0] - padding, bbox[1] - padding, bbox[2] + 2.0 * padding, bbox[3] + 2.0 * padding),
            ))
    return index


def _edge_obstacles(index: ObstacleIndex, source_id: str, target_id: str) -> List[Box]:
    """Obstacles for one edge: every indexed node except its own endpoints."""
    return [box for element_id, box in index if element_id not in {source_id, target_id}]


def _facing_side_pairs(
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
) -> Tuple[Tuple[str, str], Tuple[str, str]]:
    """The horizontal and vertical face pairs that point the nodes at each other."""
    source_x, source_y = _bbox_center(source_bbox)
    target_x, target_y = _bbox_center(target_bbox)
    horizontal = ("right", "left") if target_x >= source_x else ("left", "right")
    vertical = ("bottom", "top") if target_y >= source_y else ("top", "bottom")
    return horizontal, vertical


def _lead_point(endpoint: Point, adjacent: Point, distance: float) -> Point:
    """``endpoint`` moved ``distance`` toward ``adjacent`` along the dominant axis."""
    dx = adjacent[0] - endpoint[0]
    dy = adjacent[1] - endpoint[1]
    if abs(dx) >= abs(dy) and abs(dx) > 1e-6:
        return endpoint[0] + math.copysign(distance, dx), endpoint[1]
    if abs(dy) > 1e-6:
        return endpoint[0], endpoint[1] + math.copysign(distance, dy)
    return endpoint


def _avoid_node_intersections(
    waypoints: List[Dict[str, float]],
    obstacles: List[Box],
    clearance: float = NODE_CLEARANCE,
    existing_arrows: Optional[List[Dict[str, Any]]] = None,
    endpoint_boxes: Optional[List[Box]] = None,
) -> List[Dict[str, float]]:
    """Route a connector through clear orthogonal channels when needed."""
    if len(waypoints) < 2:
        return waypoints

    def point(value: Point) -> Dict[str, float]:
        return {"x": float(value[0]), "y": float(value[1])}

    original = _xy(waypoints)
    port_normals = (
        (original[1][0] - original[0][0], original[1][1] - original[0][1]),
        (original[-2][0] - original[-1][0], original[-2][1] - original[-1][1]),
    )

    def preserves_ports(candidate: List[Point]) -> bool:
        """A detour must keep the authored entrance and exit directions."""
        for endpoint, neighbor in ((0, 1), (-1, -2)):
            dx = original[neighbor][0] - original[endpoint][0]
            dy = original[neighbor][1] - original[endpoint][1]
            cx = candidate[neighbor][0] - candidate[endpoint][0]
            cy = candidate[neighbor][1] - candidate[endpoint][1]
            if abs(dx * cy - dy * cx) > 1e-6 or dx * cx + dy * cy <= 0:
                return False
        return True

    def routed(middle: List[Point]) -> List[Point]:
        return _compress_orthogonal_path([original[0], *middle, original[-1]])

    spacing_clearance = min(clearance / 2.0, 12.0)
    clearance_obstacles = [
        (left - spacing_clearance, top - spacing_clearance,
         width + 2.0 * spacing_clearance, height + 2.0 * spacing_clearance)
        for left, top, width, height in obstacles
    ]
    # Endpoint interiors are obstacles too: preserving the first/last segment
    # direction alone does not prevent a middle detour from cutting through
    # its own target. Keep their borders unpadded so attachment remains legal.
    if endpoint_boxes:
        obstacles = [*obstacles, *endpoint_boxes]
        clearance_obstacles.extend(endpoint_boxes)
    original_has_clearance = _path_is_clear(original, clearance_obstacles)
    visible_arrows = _visible_arrows(existing_arrows)

    if _path_is_clear(original, obstacles):
        # The authored route is legal. Reroute only to remove a crossing,
        # clear a crowded channel, or open a gap beside a passed node.
        original_crossings = _path_crossing_count(original, visible_arrows)
        original_parallel_penalty = _path_parallel_channel_penalty(original, visible_arrows)
        uncontested = original_crossings == 0 and original_parallel_penalty <= 1e-6
        if uncontested and original_has_clearance:
            return waypoints

        route_clearance = spacing_clearance if uncontested else clearance
        middle = _orthogonal_visibility_route(
            _lead_point(original[0], original[1], route_clearance),
            _lead_point(original[-1], original[-2], route_clearance),
            obstacles,
            visible_arrows,
            route_clearance,
            port_normals=port_normals,
        )
        if not middle:
            return waypoints

        candidate = routed(middle)
        original_length = max(_path_length(original), 1.0)
        if (
            not _path_is_clear(candidate, obstacles)
            or not preserves_ports(candidate)
            or _path_length(candidate) > original_length * _MAX_GENERIC_REROUTE_LENGTH_RATIO
            or _path_bend_count(candidate) > _path_bend_count(original) + _MAX_GENERIC_EXTRA_BENDS
        ):
            return waypoints

        candidate_crossings = _path_crossing_count(candidate, visible_arrows)
        candidate_parallel_penalty = _path_parallel_channel_penalty(candidate, visible_arrows)
        removes_crossing = candidate_crossings < original_crossings
        clears_crowded_channel = (
            candidate_crossings == original_crossings
            and original_parallel_penalty > 1e-6
            and candidate_parallel_penalty <= original_parallel_penalty * 0.5
        )
        creates_node_clearance = (
            not original_has_clearance
            and _path_is_clear(candidate, clearance_obstacles)
        )
        if not (removes_crossing or clears_crowded_channel or creates_node_clearance):
            return waypoints
        return [point(value) for value in candidate]

    # The authored route enters a node. First try a local box-shaped detour
    # around each blocking node in turn.
    local_route = list(original)
    local_clearance = min(clearance, _LOCAL_DETOUR_CLEARANCE)
    for obstacle in obstacles:
        hit_index = next(
            (
                index
                for index, (start, end) in enumerate(zip(local_route, local_route[1:]))
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
            [detour_start, (detour_start[0], top - local_clearance), (route_end[0], top - local_clearance), route_end],
            [detour_start, (detour_start[0], bottom + local_clearance), (route_end[0], bottom + local_clearance), route_end],
            [detour_start, (left - local_clearance, detour_start[1]), (left - local_clearance, route_end[1]), route_end],
            [detour_start, (right + local_clearance, detour_start[1]), (right + local_clearance, route_end[1]), route_end],
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
            key=lambda detour: (_path_crossing_count(detour, existing_arrows), _path_length(detour)),
        )
        local_route = local_route[: hit_index + 1] + chosen[1:]

    if _path_is_clear(local_route, obstacles) and preserves_ports(_compress_orthogonal_path(local_route)):
        return [point(value) for value in _compress_orthogonal_path(local_route)]

    # Otherwise search the grid: shortest first, then a crossing-aware
    # alternative when it is only modestly longer.
    start_lead = _lead_point(original[0], original[1], clearance)
    end_lead = _lead_point(original[-1], original[-2], clearance)
    shortest_middle = _orthogonal_visibility_route(
        start_lead, end_lead, obstacles, None, clearance, port_normals=port_normals,
    )
    if not shortest_middle:
        return waypoints

    shortest_candidate = routed(shortest_middle)
    if not _path_is_clear(shortest_candidate, obstacles) or not preserves_ports(shortest_candidate):
        return waypoints

    candidate = shortest_candidate
    if existing_arrows:
        crossing_aware_middle = _orthogonal_visibility_route(
            start_lead, end_lead, obstacles, existing_arrows, clearance, port_normals=port_normals,
        )
        if crossing_aware_middle:
            crossing_aware = routed(crossing_aware_middle)
            shortest_length = max(_path_length(shortest_candidate), 1.0)
            if (
                _path_is_clear(crossing_aware, obstacles)
                and preserves_ports(crossing_aware)
                and _path_length(crossing_aware) <= shortest_length * _MAX_CLEAR_CHANNEL_LENGTH_RATIO
                and _path_crossing_count(crossing_aware, existing_arrows)
                < _path_crossing_count(shortest_candidate, existing_arrows)
            ):
                candidate = crossing_aware

    result: List[Dict[str, float]] = []
    for value in candidate:
        current = point(value)
        if not result or current != result[-1]:
            result.append(current)
    return result


def _prefer_clear_port_pair(
    start_side: str,
    end_side: str,
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
    obstacles: List[Box],
) -> Tuple[str, str]:
    """Change ports only when the authored pair necessarily crosses a node."""
    authored, _, _ = compute_waypoints(start_side, end_side, source_bbox, target_bbox, port_spacing=0.0)
    if _route_is_legal(_xy(authored), obstacles, source_bbox, target_bbox):
        return start_side, end_side

    side_pairs = list(dict.fromkeys([(start_side, end_side), *_facing_side_pairs(source_bbox, target_bbox)]))
    primary_pair_count = len(side_pairs)
    side_pairs.extend(
        pair for pair in ((start, end) for start in _SIDES for end in _SIDES)
        if pair not in side_pairs
    )
    endpoint_boxes = [_box_tuple(source_bbox), _box_tuple(target_bbox)]
    candidates: List[Tuple[float, int, str, str]] = []
    for pair_index, (candidate_start, candidate_end) in enumerate(side_pairs):
        # Try the remaining faces only when the ordinary flow directions have
        # no safe route; preserve the established ports in common cases.
        if pair_index == primary_pair_count and candidates:
            break
        waypoints, _, _ = compute_waypoints(
            candidate_start, candidate_end, source_bbox, target_bbox, port_spacing=0.0,
        )
        points = _xy(_avoid_node_intersections(waypoints, obstacles, endpoint_boxes=endpoint_boxes))
        if not _route_is_legal(points, obstacles, source_bbox, target_bbox):
            continue
        bends = max(0, len(points) - 2)
        score = _path_length(points) + bends * ROUTE_BEND_PENALTY
        candidates.append((score, bends, candidate_start, candidate_end))

    if not candidates:
        return start_side, end_side
    _, _, best_start, best_end = min(candidates)
    return best_start, best_end


def _prefer_architecture_outer_route(
    waypoints: List[Dict[str, float]],
    start_side: str,
    end_side: str,
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
    obstacles: List[Box],
    existing_arrows: Optional[List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, float]], str, str]:
    """Use an outer node face when it removes crossings from a long layer edge."""
    original = _xy(waypoints)
    original_crossings = _path_crossing_count(original, existing_arrows)
    if original_crossings == 0:
        return waypoints, start_side, end_side

    if start_side in {"top", "bottom"} and end_side in {"top", "bottom"}:
        side_pairs = (("right", "right"), ("left", "left"))
    elif start_side in {"left", "right"} and end_side in {"left", "right"}:
        side_pairs = (("bottom", "bottom"), ("top", "top"))
    else:
        return waypoints, start_side, end_side

    original_length = max(_path_length(original), 1.0)
    candidates: List[Tuple[int, float, List[Dict[str, float]], str, str]] = []
    for candidate_start, candidate_end in side_pairs:
        candidate, _, _ = compute_waypoints(candidate_start, candidate_end, source_bbox, target_bbox)
        candidate = _avoid_node_intersections(candidate, obstacles, existing_arrows=existing_arrows)
        absolute = _xy(candidate)
        candidate_length = _path_length(absolute)
        if (
            not _route_is_legal(absolute, obstacles, source_bbox, target_bbox)
            or candidate_length > original_length * _MAX_OUTER_ROUTE_LENGTH_RATIO
        ):
            continue
        candidates.append((
            _path_crossing_count(absolute, existing_arrows),
            candidate_length,
            candidate,
            candidate_start,
            candidate_end,
        ))

    if not candidates:
        return waypoints, start_side, end_side
    best = min(candidates, key=lambda item: (item[0], item[1]))
    if best[0] >= original_crossings:
        return waypoints, start_side, end_side
    return best[2], best[3], best[4]


def _prefer_crosscutting_lower_corridor_route(
    waypoints: List[Dict[str, float]],
    start_side: str,
    end_side: str,
    source_bbox: Dict[str, float],
    target_bbox: Dict[str, float],
    obstacles: List[Box],
    existing_arrows: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, float]]:
    """Move a crossing cross-cutting edge into the clear lower corridor.

    Cross-cutting nodes commonly sit beside the main architecture layers. A
    left-to-right edge between them should not compete with the data-layer
    horizontals above it. The corridor is derived from the lowest obstacle,
    leaving a small visual gap; the route is accepted when it removes a
    crossing or materially reduces a crowded parallel channel, while staying
    within a bounded length increase.
    """
    if start_side not in {"left", "right"} or end_side not in {"left", "right"}:
        return waypoints
    source_center_y = source_bbox["y"] + source_bbox["h"] / 2.0
    target_center_y = target_bbox["y"] + target_bbox["h"] / 2.0
    if abs(source_center_y - target_center_y) > max(source_bbox["h"], target_bbox["h"]) + 24.0:
        return waypoints
    original = _xy(waypoints)
    original_crossings = _path_crossing_count(original, existing_arrows)
    if not obstacles:
        return waypoints

    lowest_bottom = max(top + height for _, top, _, height in obstacles)
    start = original[0]
    end = original[-1]
    start_x = start[0] + (22.0 if start_side == "right" else -22.0)
    end_x = end[0] + (22.0 if end_side == "right" else -22.0)
    original_penalty = _path_parallel_channel_penalty(original, existing_arrows)
    original_length = max(_path_length(original), 1.0)
    candidates: List[Tuple[int, float, float, List[Point]]] = []
    for lane_index in range(6):
        corridor_y = lowest_bottom + 2.0 + lane_index * PARALLEL_CHANNEL_CLEARANCE
        candidate_points = [
            start,
            (start_x, start[1]),
            (start_x, corridor_y),
            (end_x, corridor_y),
            (end_x, end[1]),
            end,
        ]
        if not _route_is_legal(candidate_points, obstacles, source_bbox, target_bbox):
            continue
        candidate_length = _path_length(candidate_points)
        if candidate_length > original_length * _MAX_CROSSCUTTING_ROUTE_LENGTH_RATIO:
            continue
        candidates.append((
            _path_crossing_count(candidate_points, existing_arrows),
            _path_parallel_channel_penalty(candidate_points, existing_arrows),
            candidate_length,
            candidate_points,
        ))

    if not candidates:
        return waypoints
    candidate_crossings, candidate_penalty, _, candidate_points = min(
        candidates, key=lambda item: (item[0], item[1], item[2]),
    )
    if candidate_crossings > original_crossings:
        return waypoints
    if candidate_crossings == original_crossings and candidate_penalty >= original_penalty:
        return waypoints
    return _waypoints(candidate_points)
