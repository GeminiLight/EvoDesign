// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_routing/detours.py — keep in sync.
//
// Per-edge route repairs: node avoidance and alternative face pairs.

import { reverse_id_map } from '../../../common/semantic_ids.ts';
import { pyGet, type PyMapping } from '../../../py/dict.ts';
import { pyIn } from '../../../py/eq.ts';
import { PyTypeError, ValueError } from '../../../py/errors.ts';
import { copysign } from '../../../py/math.ts';
import { pyFloatParse } from '../../../py/number.ts';
import { pyMax, pyMin } from '../../../py/sort.ts';
import { pyEndswith, pyStr } from '../../../py/str.ts';
import { isDict, pyOr, truthy } from '../../../py/truthy.ts';
import { compute_waypoints, type WayPoint } from '../edge_router.ts';
import {
  PARALLEL_CHANNEL_CLEARANCE,
  type BBox,
  type Box,
  type Point,
  _bbox_center,
  _box_tuple,
  _compress_orthogonal_path,
  _path_bend_count,
  _path_crossing_count,
  _path_is_clear,
  _path_length,
  _path_parallel_channel_penalty,
  _route_is_legal,
  _segment_hits_box,
  _visible_arrows,
  _waypoints,
  _xy,
} from './geometry.ts';
import { ROUTE_BEND_PENALTY, _orthogonal_visibility_route } from './grid_router.ts';

type Dict = Record<string, unknown>;
type PointLike = readonly number[];
type BoxLike = readonly number[];

export const NODE_CLEARANCE = 24.0;
export const _LOCAL_DETOUR_CLEARANCE = 16.0;
export const _MAX_OUTER_ROUTE_LENGTH_RATIO = 1.6;
export const _MAX_CROSSCUTTING_ROUTE_LENGTH_RATIO = 1.8;
export const _MAX_CLEAR_CHANNEL_LENGTH_RATIO = 1.35;
export const _MAX_GENERIC_REROUTE_LENGTH_RATIO = 1.6;
export const _MAX_GENERIC_EXTRA_BENDS = 4;
export const _SIDES = ['left', 'right', 'top', 'bottom'] as const;

export type ObstacleIndex = [unknown, Box][];

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

function _at<T>(items: readonly T[], index: number): T {
  return items[index < 0 ? items.length + index : index];
}

/** Drawable node boxes an edge may not enter, keyed by element id. */
export function _obstacle_index(
  elements: readonly unknown[],
  id_map: PyMapping,
  excluded_ids: Set<string> | null = null,
): ObstacleIndex {
  const reverse_map = reverse_id_map(id_map);
  const index: ObstacleIndex = [];
  const shape_types = new Set(['rectangle', 'ellipse', 'diamond', 'embeddable', 'iframe']);
  for (const element of elements) {
    if (!isDict(element) || truthy(pyGet(element, 'isDeleted'))) continue;
    if (pyIn(pyGet(element, 'id'), pyOr(excluded_ids, new Set()))) continue;
    if (!shape_types.has(pyGet(element, 'type') as string)) continue;
    const semantic_id = pyGet(reverse_map, pyStr(pyGet(element, 'id', '')), '') as string;
    if (pyEndswith(semantic_id, ':background') || pyEndswith(semantic_id, ':title')) continue;
    let bbox: Box;
    try {
      bbox = [
        _float(pyOr(pyGet(element, 'x', 0), 0)),
        _float(pyOr(pyGet(element, 'y', 0), 0)),
        _float(pyOr(pyGet(element, 'width', 0), 0)),
        _float(pyOr(pyGet(element, 'height', 0), 0)),
      ];
    } catch (error) {
      if (error instanceof PyTypeError || error instanceof ValueError) continue;
      throw error;
    }
    if (bbox[2] > 0 && bbox[3] > 0) {
      // A route along an unrelated card's border looks connected to it.
      const visible_border = _float(pyOr(pyGet(element, 'strokeWidth', 1.0), 0.0)) > 0
        && !['transparent', 'none'].includes(pyGet(element, 'strokeColor') as string)
        && _float(pyGet(element, 'opacity', 100)) > 0;
      const padding = visible_border ? 6.0 : 0.0;
      index.push([
        pyGet(element, 'id'),
        [bbox[0] - padding, bbox[1] - padding, bbox[2] + 2.0 * padding, bbox[3] + 2.0 * padding],
      ]);
    }
  }
  return index;
}

/** Obstacles for one edge: every indexed node except its own endpoints. */
export function _edge_obstacles(index: ObstacleIndex, source_id: string, target_id: string): Box[] {
  return index.filter(([element_id]) => element_id !== source_id && element_id !== target_id).map(([, box]) => box);
}

/** The horizontal and vertical face pairs that point the nodes at each other. */
export function _facing_side_pairs(source_bbox: BBox, target_bbox: BBox): [[string, string], [string, string]] {
  const [source_x, source_y] = _bbox_center(source_bbox);
  const [target_x, target_y] = _bbox_center(target_bbox);
  const horizontal: [string, string] = target_x >= source_x ? ['right', 'left'] : ['left', 'right'];
  const vertical: [string, string] = target_y >= source_y ? ['bottom', 'top'] : ['top', 'bottom'];
  return [horizontal, vertical];
}

/** ``endpoint`` moved ``distance`` toward ``adjacent`` along the dominant axis. */
export function _lead_point(endpoint: PointLike, adjacent: PointLike, distance: number): Point {
  const dx = adjacent[0] - endpoint[0];
  const dy = adjacent[1] - endpoint[1];
  if (Math.abs(dx) >= Math.abs(dy) && Math.abs(dx) > 1e-6) return [endpoint[0] + copysign(distance, dx), endpoint[1]];
  if (Math.abs(dy) > 1e-6) return [endpoint[0], endpoint[1] + copysign(distance, dy)];
  return endpoint as Point;
}

/** Route a connector through clear orthogonal channels when needed. */
export function _avoid_node_intersections(
  waypoints: WayPoint[],
  obstacles: readonly BoxLike[],
  clearance = NODE_CLEARANCE,
  existing_arrows: readonly Dict[] | null = null,
  endpoint_boxes: readonly BoxLike[] | null = null,
): WayPoint[] {
  if (waypoints.length < 2) return waypoints;

  const point = (value: PointLike): WayPoint => ({ x: _float(value[0]), y: _float(value[1]) });

  const original = _xy(waypoints);
  const port_normals: [Point, Point] = [
    [original[1][0] - original[0][0], original[1][1] - original[0][1]],
    [_at(original, -2)[0] - _at(original, -1)[0], _at(original, -2)[1] - _at(original, -1)[1]],
  ];

  // A detour must keep the authored entrance and exit directions.
  const preserves_ports = (candidate: readonly PointLike[]): boolean => {
    for (const [endpoint, neighbor] of [[0, 1], [-1, -2]]) {
      const dx = _at(original, neighbor)[0] - _at(original, endpoint)[0];
      const dy = _at(original, neighbor)[1] - _at(original, endpoint)[1];
      const cx = _at(candidate, neighbor)[0] - _at(candidate, endpoint)[0];
      const cy = _at(candidate, neighbor)[1] - _at(candidate, endpoint)[1];
      if (Math.abs(dx * cy - dy * cx) > 1e-6 || dx * cx + dy * cy <= 0) return false;
    }
    return true;
  };

  const routed = (middle: readonly PointLike[]): PointLike[] =>
    _compress_orthogonal_path([original[0], ...middle, _at(original, -1)]);

  const spacing_clearance = 12.0 < clearance / 2.0 ? 12.0 : clearance / 2.0; // min(clearance / 2.0, 12.0)
  const clearance_obstacles: BoxLike[] = obstacles.map(([left, top, width, height]) => [
    left - spacing_clearance,
    top - spacing_clearance,
    width + 2.0 * spacing_clearance,
    height + 2.0 * spacing_clearance,
  ]);
  // Endpoint interiors are obstacles too.
  if (truthy(endpoint_boxes)) {
    obstacles = [...obstacles, ...endpoint_boxes!];
    clearance_obstacles.push(...endpoint_boxes!);
  }
  const original_has_clearance = _path_is_clear(original, clearance_obstacles);
  const visible_arrows = _visible_arrows(existing_arrows);

  if (_path_is_clear(original, obstacles)) {
    // The authored route is legal. Reroute only to remove a crossing,
    // clear a crowded channel, or open a gap beside a passed node.
    const original_crossings = _path_crossing_count(original, visible_arrows);
    const original_parallel_penalty = _path_parallel_channel_penalty(original, visible_arrows);
    const uncontested = original_crossings === 0 && original_parallel_penalty <= 1e-6;
    if (uncontested && original_has_clearance) return waypoints;

    const route_clearance = uncontested ? spacing_clearance : clearance;
    const middle = _orthogonal_visibility_route(
      _lead_point(original[0], original[1], route_clearance),
      _lead_point(_at(original, -1), _at(original, -2), route_clearance),
      obstacles,
      visible_arrows,
      route_clearance,
      port_normals,
    );
    if (!truthy(middle)) return waypoints;

    const candidate = routed(middle!);
    const original_length = Math.max(_path_length(original), 1.0);
    if (
      !_path_is_clear(candidate, obstacles)
      || !preserves_ports(candidate)
      || _path_length(candidate) > original_length * _MAX_GENERIC_REROUTE_LENGTH_RATIO
      || _path_bend_count(candidate) > _path_bend_count(original) + _MAX_GENERIC_EXTRA_BENDS
    ) {
      return waypoints;
    }

    const candidate_crossings = _path_crossing_count(candidate, visible_arrows);
    const candidate_parallel_penalty = _path_parallel_channel_penalty(candidate, visible_arrows);
    const removes_crossing = candidate_crossings < original_crossings;
    const clears_crowded_channel = candidate_crossings === original_crossings
      && original_parallel_penalty > 1e-6
      && candidate_parallel_penalty <= original_parallel_penalty * 0.5;
    const creates_node_clearance = !original_has_clearance && _path_is_clear(candidate, clearance_obstacles);
    if (!(removes_crossing || clears_crowded_channel || creates_node_clearance)) return waypoints;
    return candidate.map(point);
  }

  // The authored route enters a node. First try a local box-shaped detour
  // around each blocking node in turn.
  let local_route: PointLike[] = [...original];
  const local_clearance = clearance < _LOCAL_DETOUR_CLEARANCE ? clearance : _LOCAL_DETOUR_CLEARANCE;
  for (const obstacle of obstacles) {
    let hit_index: number | null = null;
    for (let index = 0; index + 1 < local_route.length; index += 1) {
      if (_segment_hits_box(local_route[index], local_route[index + 1], obstacle)) {
        hit_index = index;
        break;
      }
    }
    if (hit_index === null) continue;

    const detour_start = local_route[hit_index];
    const route_end = _at(local_route, -1);
    const [left, top, width, height] = obstacle;
    const right = left + width;
    const bottom = top + height;
    const detours: PointLike[][] = [
      [detour_start, [detour_start[0], top - local_clearance], [route_end[0], top - local_clearance], route_end],
      [detour_start, [detour_start[0], bottom + local_clearance], [route_end[0], bottom + local_clearance], route_end],
      [detour_start, [left - local_clearance, detour_start[1]], [left - local_clearance, route_end[1]], route_end],
      [detour_start, [right + local_clearance, detour_start[1]], [right + local_clearance, route_end[1]], route_end],
    ];
    const head = local_route.slice(0, hit_index + 1);
    const valid_detours = detours.filter((detour) =>
      _path_is_clear(detour, obstacles)
      && preserves_ports(_compress_orthogonal_path([...head, ...detour.slice(1)])));
    if (!valid_detours.length) continue;
    const chosen = pyMin(valid_detours, (detour) => [_path_crossing_count(detour, existing_arrows), _path_length(detour)]);
    local_route = [...head, ...chosen.slice(1)];
  }

  if (_path_is_clear(local_route, obstacles) && preserves_ports(_compress_orthogonal_path(local_route))) {
    return _compress_orthogonal_path(local_route).map(point);
  }

  // Otherwise search the grid: shortest first, then a crossing-aware
  // alternative when it is only modestly longer.
  const start_lead = _lead_point(original[0], original[1], clearance);
  const end_lead = _lead_point(_at(original, -1), _at(original, -2), clearance);
  const shortest_middle = _orthogonal_visibility_route(start_lead, end_lead, obstacles, null, clearance, port_normals);
  if (!truthy(shortest_middle)) return waypoints;

  const shortest_candidate = routed(shortest_middle!);
  if (!_path_is_clear(shortest_candidate, obstacles) || !preserves_ports(shortest_candidate)) return waypoints;

  let candidate = shortest_candidate;
  if (truthy(existing_arrows)) {
    const crossing_aware_middle = _orthogonal_visibility_route(
      start_lead, end_lead, obstacles, existing_arrows, clearance, port_normals,
    );
    if (truthy(crossing_aware_middle)) {
      const crossing_aware = routed(crossing_aware_middle!);
      const shortest_length = Math.max(_path_length(shortest_candidate), 1.0);
      if (
        _path_is_clear(crossing_aware, obstacles)
        && preserves_ports(crossing_aware)
        && _path_length(crossing_aware) <= shortest_length * _MAX_CLEAR_CHANNEL_LENGTH_RATIO
        && _path_crossing_count(crossing_aware, existing_arrows) < _path_crossing_count(shortest_candidate, existing_arrows)
      ) {
        candidate = crossing_aware;
      }
    }
  }

  const result: WayPoint[] = [];
  for (const value of candidate) {
    const current = point(value);
    const last = result[result.length - 1];
    if (!result.length || current.x !== last.x || current.y !== last.y) result.push(current);
  }
  return result;
}

function _pair_key(pair: readonly [string, string]): string {
  return `${pair[0]}\u0000${pair[1]}`;
}

/** Change ports only when the authored pair necessarily crosses a node. */
export function _prefer_clear_port_pair(
  start_side: string,
  end_side: string,
  source_bbox: BBox,
  target_bbox: BBox,
  obstacles: readonly BoxLike[],
): [string, string] {
  const [authored] = compute_waypoints(
    start_side, end_side, source_bbox, target_bbox,
    undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, 0.0,
  );
  if (_route_is_legal(_xy(authored), obstacles, source_bbox, target_bbox)) return [start_side, end_side];

  // list(dict.fromkeys([...])) keeps the first occurrence of each pair.
  const side_pairs: [string, string][] = [];
  const seen = new Set<string>();
  for (const pair of [[start_side, end_side] as [string, string], ..._facing_side_pairs(source_bbox, target_bbox)]) {
    if (seen.has(_pair_key(pair))) continue;
    seen.add(_pair_key(pair));
    side_pairs.push(pair);
  }
  const primary_pair_count = side_pairs.length;
  for (const start of _SIDES) {
    for (const end of _SIDES) {
      if (seen.has(_pair_key([start, end]))) continue;
      seen.add(_pair_key([start, end]));
      side_pairs.push([start, end]);
    }
  }
  const endpoint_boxes = [_box_tuple(source_bbox), _box_tuple(target_bbox)];
  const candidates: [number, number, string, string][] = [];
  for (let pair_index = 0; pair_index < side_pairs.length; pair_index += 1) {
    const [candidate_start, candidate_end] = side_pairs[pair_index];
    // Try the remaining faces only when the ordinary flow directions have
    // no safe route; preserve the established ports in common cases.
    if (pair_index === primary_pair_count && candidates.length) break;
    const [waypoints] = compute_waypoints(
      candidate_start, candidate_end, source_bbox, target_bbox,
      undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, 0.0,
    );
    const points = _xy(_avoid_node_intersections(waypoints, obstacles, undefined, undefined, endpoint_boxes));
    if (!_route_is_legal(points, obstacles, source_bbox, target_bbox)) continue;
    const bends = Math.max(0, points.length - 2);
    const score = _path_length(points) + bends * ROUTE_BEND_PENALTY;
    candidates.push([score, bends, candidate_start, candidate_end]);
  }

  if (!candidates.length) return [start_side, end_side];
  const [, , best_start, best_end] = pyMin(candidates);
  return [best_start, best_end];
}

/** Use an outer node face when it removes crossings from a long layer edge. */
export function _prefer_architecture_outer_route(
  waypoints: WayPoint[],
  start_side: string,
  end_side: string,
  source_bbox: BBox,
  target_bbox: BBox,
  obstacles: readonly BoxLike[],
  existing_arrows: readonly Dict[] | null,
): [WayPoint[], string, string] {
  const original = _xy(waypoints);
  const original_crossings = _path_crossing_count(original, existing_arrows);
  if (original_crossings === 0) return [waypoints, start_side, end_side];

  const vertical = (side: string) => side === 'top' || side === 'bottom';
  const horizontal = (side: string) => side === 'left' || side === 'right';
  let side_pairs: [string, string][];
  if (vertical(start_side) && vertical(end_side)) side_pairs = [['right', 'right'], ['left', 'left']];
  else if (horizontal(start_side) && horizontal(end_side)) side_pairs = [['bottom', 'bottom'], ['top', 'top']];
  else return [waypoints, start_side, end_side];

  const original_length = Math.max(_path_length(original), 1.0);
  const candidates: [number, number, WayPoint[], string, string][] = [];
  for (const [candidate_start, candidate_end] of side_pairs) {
    let [candidate] = compute_waypoints(candidate_start, candidate_end, source_bbox, target_bbox);
    candidate = _avoid_node_intersections(candidate, obstacles, undefined, existing_arrows);
    const absolute = _xy(candidate);
    const candidate_length = _path_length(absolute);
    if (
      !_route_is_legal(absolute, obstacles, source_bbox, target_bbox)
      || candidate_length > original_length * _MAX_OUTER_ROUTE_LENGTH_RATIO
    ) {
      continue;
    }
    candidates.push([_path_crossing_count(absolute, existing_arrows), candidate_length, candidate, candidate_start, candidate_end]);
  }

  if (!candidates.length) return [waypoints, start_side, end_side];
  const best = pyMin(candidates, (item) => [item[0], item[1]]);
  if (best[0] >= original_crossings) return [waypoints, start_side, end_side];
  return [best[2], best[3], best[4]];
}

/** Move a crossing cross-cutting edge into the clear lower corridor. */
export function _prefer_crosscutting_lower_corridor_route(
  waypoints: WayPoint[],
  start_side: string,
  end_side: string,
  source_bbox: BBox,
  target_bbox: BBox,
  obstacles: readonly BoxLike[],
  existing_arrows: readonly Dict[] | null,
): WayPoint[] {
  const lateral = (side: string) => side === 'left' || side === 'right';
  if (!lateral(start_side) || !lateral(end_side)) return waypoints;
  const source_center_y = source_bbox.y + source_bbox.h / 2.0;
  const target_center_y = target_bbox.y + target_bbox.h / 2.0;
  if (Math.abs(source_center_y - target_center_y) > (pyMax([source_bbox.h, target_bbox.h]) as number) + 24.0) return waypoints;
  const original = _xy(waypoints);
  const original_crossings = _path_crossing_count(original, existing_arrows);
  if (!obstacles.length) return waypoints;

  const lowest_bottom = pyMax(obstacles.map(([, top, , height]) => top + height)) as number;
  const start = original[0];
  const end = _at(original, -1);
  const start_x = start[0] + (start_side === 'right' ? 22.0 : -22.0);
  const end_x = end[0] + (end_side === 'right' ? 22.0 : -22.0);
  const original_penalty = _path_parallel_channel_penalty(original, existing_arrows);
  const original_length = Math.max(_path_length(original), 1.0);
  const candidates: [number, number, number, Point[]][] = [];
  for (let lane_index = 0; lane_index < 6; lane_index += 1) {
    const corridor_y = lowest_bottom + 2.0 + lane_index * PARALLEL_CHANNEL_CLEARANCE;
    const candidate_points: Point[] = [
      start,
      [start_x, start[1]],
      [start_x, corridor_y],
      [end_x, corridor_y],
      [end_x, end[1]],
      end,
    ];
    if (!_route_is_legal(candidate_points, obstacles, source_bbox, target_bbox)) continue;
    const candidate_length = _path_length(candidate_points);
    if (candidate_length > original_length * _MAX_CROSSCUTTING_ROUTE_LENGTH_RATIO) continue;
    candidates.push([
      _path_crossing_count(candidate_points, existing_arrows),
      _path_parallel_channel_penalty(candidate_points, existing_arrows),
      candidate_length,
      candidate_points,
    ]);
  }

  if (!candidates.length) return waypoints;
  const [candidate_crossings, candidate_penalty, , candidate_points] = pyMin(candidates, (item) => [item[0], item[1], item[2]]);
  if (candidate_crossings > original_crossings) return waypoints;
  if (candidate_crossings === original_crossings && candidate_penalty >= original_penalty) return waypoints;
  return _waypoints(candidate_points);
}
