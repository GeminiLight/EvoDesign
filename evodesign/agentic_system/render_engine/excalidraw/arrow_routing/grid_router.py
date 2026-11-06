"""Orthogonal visibility-grid router (draw.io style) with a per-pass memo."""
from __future__ import annotations

import math
from contextvars import ContextVar
from heapq import heappop, heappush
from typing import Any, Dict, List, Optional, Tuple

from ...shared.edge_crossing_detector import (
    count_prepared_crossings,
    prepare_crossing_segments,
)
from .geometry import (
    Box,
    Point,
    _absolute_arrow_points,
    _compress_orthogonal_path,
    _path_is_clear,
    _visible_arrows,
)

ROUTE_BEND_PENALTY = 36.0
_ROUTE_CROSSING_PENALTY = 1800.0
_ROUTE_DEVIATION_PENALTY = 0.01
_SPAN_MARGIN = 1.0  # well beyond the 1e-6 interior epsilon of _segment_hits_box

PortNormals = Tuple[Tuple[float, float], Tuple[float, float]]


def _obstacles_spanning(obstacles: List[Box], value: float, *, axis: int) -> List[Box]:
    """Obstacles whose span on ``axis`` (0 = x, 1 = y) reaches ``value``."""
    return [
        obstacle for obstacle in obstacles
        if obstacle[axis] - _SPAN_MARGIN <= value <= obstacle[axis] + obstacle[axis + 2] + _SPAN_MARGIN
    ]


def _obstacles_overlapping(obstacles: List[Box], low: float, high: float, *, axis: int) -> List[Box]:
    """Obstacles whose span on ``axis`` overlaps ``[low, high]`` (with margin)."""
    return [
        obstacle for obstacle in obstacles
        if obstacle[axis] - _SPAN_MARGIN <= high and low <= obstacle[axis] + obstacle[axis + 2] + _SPAN_MARGIN
    ]


# Routes are pure functions of their geometric input, and one render asks for
# the same route many times (crossing-reduction retries and the midpoint-port
# comparison pass). The memo lives for one top-level arrow pass only.
_ROUTE_MEMO: ContextVar[Optional[Dict[Any, Any]]] = ContextVar("_ROUTE_MEMO", default=None)


def _route_memo_key(start, end, obstacles, existing_arrows, clearance, port_normals) -> str:
    # repr keeps every float exactly (including -0.0), so a hit returns
    # byte-identical geometry. Only the fields the router reads are keyed.
    arrows = [
        (
            arrow.get("type"),
            arrow.get("isDeleted"),
            arrow.get("opacity", 100),
            arrow.get("x"),
            arrow.get("y"),
            arrow.get("points"),
        )
        for arrow in existing_arrows or []
    ]
    return repr((start, end, obstacles, arrows, clearance, port_normals))


def _orthogonal_visibility_route(
    start: Point,
    end: Point,
    obstacles: List[Box],
    existing_arrows: Optional[List[Dict[str, Any]]],
    clearance: float,
    port_normals: Optional[PortNormals] = None,
) -> Optional[List[Point]]:
    """Memoized :func:`_find_orthogonal_visibility_route` within one arrow pass."""
    memo = _ROUTE_MEMO.get()
    if memo is None:
        return _find_orthogonal_visibility_route(
            start, end, obstacles, existing_arrows, clearance, port_normals
        )
    key = _route_memo_key(start, end, obstacles, existing_arrows, clearance, port_normals)
    if key not in memo:
        memo[key] = _find_orthogonal_visibility_route(
            start, end, obstacles, existing_arrows, clearance, port_normals
        )
    route = memo[key]
    return list(route) if route is not None else None


def _find_orthogonal_visibility_route(
    start: Point,
    end: Point,
    obstacles: List[Box],
    existing_arrows: Optional[List[Dict[str, Any]]],
    clearance: float,
    port_normals: Optional[PortNormals] = None,
) -> Optional[List[Point]]:
    """Find a draw.io-style orthogonal route through a visibility grid.

    Nodes sit at candidate channel intersections derived from obstacle margins
    and existing connector vertices. Dijkstra state includes travel direction,
    allowing the scorer to prefer fewer bends and independent edge channels in
    addition to short paths.
    """
    visible_arrows = _visible_arrows(existing_arrows)
    expanded = [
        (left - clearance, top - clearance, width + 2.0 * clearance, height + 2.0 * clearance)
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

    # A grid point is unavailable only inside an obstacle's strict interior,
    # so each column needs only the obstacles whose x span reaches it.
    points = set()
    for x in xs:
        column_obstacles = _obstacles_spanning(expanded, x, axis=0)
        for y in ys:
            if not any(
                left + 1e-6 < x < left + width - 1e-6
                and top + 1e-6 < y < top + height - 1e-6
                for left, top, width, height in column_obstacles
            ):
                points.add((x, y))
    if start not in points or end not in points:
        return None

    rows: Dict[float, List[Point]] = {}
    columns: Dict[float, List[Point]] = {}
    for point in points:
        rows.setdefault(point[1], []).append(point)
        columns.setdefault(point[0], []).append(point)

    neighbors: Dict[Point, List[Tuple[Point, str]]] = {point: [] for point in points}
    # A grid edge can only enter obstacles whose span covers its row/column
    # and overlaps its extent; _segment_hits_box tests the strict interior.
    for y in ys:
        row = sorted(rows.get(y, ()), key=lambda item: item[0])
        row_obstacles = _obstacles_spanning(expanded, y, axis=1)
        for left_point, right_point in zip(row, row[1:]):
            blockers = _obstacles_overlapping(row_obstacles, left_point[0], right_point[0], axis=0)
            if _path_is_clear([left_point, right_point], blockers):
                neighbors[left_point].append((right_point, "horizontal"))
                neighbors[right_point].append((left_point, "horizontal"))
    for x in xs:
        column = sorted(columns.get(x, ()), key=lambda item: item[1])
        column_obstacles = _obstacles_spanning(expanded, x, axis=0)
        for top_point, bottom_point in zip(column, column[1:]):
            blockers = _obstacles_overlapping(column_obstacles, top_point[1], bottom_point[1], axis=1)
            if _path_is_clear([top_point, bottom_point], blockers):
                neighbors[top_point].append((bottom_point, "vertical"))
                neighbors[bottom_point].append((top_point, "vertical"))

    # Existing arrows are fixed during the search, and Dijkstra relaxes the
    # same grid edge from up to three travel directions.
    prepared_arrows = prepare_crossing_segments(visible_arrows)
    edge_crossings: Dict[Tuple[Point, Point], int] = {}
    start_state = (start, "")
    primary_axis = (
        "horizontal"
        if abs(start[1] - end[1]) <= 1e-6
        else "vertical"
        if abs(start[0] - end[0]) <= 1e-6
        else ""
    )
    distances = {start_state: 0.0}
    previous: Dict[Tuple[Point, str], Tuple[Point, str]] = {}
    queue: List[Tuple[float, int, Point, str]] = []
    serial = 0
    heappush(queue, (0.0, serial, start, ""))
    final_state: Optional[Tuple[Point, str]] = None

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
            bend_cost = ROUTE_BEND_PENALTY if direction and direction != next_direction else 0.0
            crossing_count = edge_crossings.get((point, next_point))
            if crossing_count is None:
                crossing_count = count_prepared_crossings(
                    (point[0], point[1], next_point[0], next_point[1]),
                    prepared_arrows,
                )
                edge_crossings[(point, next_point)] = crossing_count
            deviation_cost = 0.0
            if primary_axis == "horizontal" and next_direction == "horizontal":
                deviation_cost = distance * abs(point[1] - start[1]) * _ROUTE_DEVIATION_PENALTY
            elif primary_axis == "vertical" and next_direction == "vertical":
                deviation_cost = distance * abs(point[0] - start[0]) * _ROUTE_DEVIATION_PENALTY
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
