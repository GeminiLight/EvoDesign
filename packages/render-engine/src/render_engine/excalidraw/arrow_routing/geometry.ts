// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_routing/geometry.py — keep in sync.
//
// Path predicates and scores shared by every connector router.
//
// Points are ``[x, y]`` tuples, boxes are ``[left, top, width, height]``
// tuples, and node bboxes are ``{x, y, w, h}`` dicts, matching the callers.

import { markF } from '../../../py/float_marks.ts';
import { pyGet } from '../../../py/dict.ts';
import { PyTypeError, ValueError } from '../../../py/errors.ts';
import { pyFloatParse } from '../../../py/number.ts';
import { pyMin } from '../../../py/sort.ts';
import { isDict, pyOr, truthy } from '../../../py/truthy.ts';
import { count_arrow_crossings } from '../../shared/edge_crossing_detector.ts';
import { to_relative_points, waypoints_bbox } from '../edge_router.ts';

type Dict = Record<string, unknown>;
export type Point = [number, number];
export type Box = [number, number, number, number];
export type BBox = { x: number; y: number; w: number; h: number };
type PointLike = readonly number[];
type BoxLike = readonly number[];

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

/** ``max(a, b)`` for numbers: the first argument unless the second is greater. */
function _max2(a: number, b: number): number {
  return b > a ? b : a;
}

/** ``min(a, b)`` for numbers: the first argument unless the second is smaller. */
function _min2(a: number, b: number): number {
  return b < a ? b : a;
}

/** ``sorted((a, b))`` for two numbers. */
function _sorted2(a: number, b: number): [number, number] {
  return b < a ? [b, a] : [a, b];
}

// Keep adjacent governance lanes visibly distinct without consuming the
// narrow bottom margin of a compact cross-cutting frame.
export const PARALLEL_CHANNEL_CLEARANCE = 16.0;

/** Return whether a segment enters the strict interior of ``bbox``. */
export function _segment_hits_box(start: PointLike, end: PointLike, bbox: BoxLike): boolean {
  let left = bbox[0];
  let top = bbox[1];
  const width = bbox[2];
  const height = bbox[3];
  let right = left + width;
  let bottom = top + height;
  if (width <= 0 || height <= 0) return false;

  // Liang-Barsky clipping.
  const epsilon = 1e-6;
  left += epsilon;
  top += epsilon;
  right -= epsilon;
  bottom -= epsilon;
  if (left >= right || top >= bottom) return false;

  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  let t_enter = 0.0;
  let t_exit = 1.0;
  const ps = [-dx, dx, -dy, dy];
  const qs = [start[0] - left, right - start[0], start[1] - top, bottom - start[1]];
  for (let i = 0; i < 4; i += 1) {
    const p = ps[i];
    const q = qs[i];
    if (Math.abs(p) <= epsilon) {
      if (q < 0) return false;
      continue;
    }
    const ratio = q / p;
    if (p < 0) t_enter = _max2(t_enter, ratio);
    else t_exit = _min2(t_exit, ratio);
    if (t_enter >= t_exit) return false;
  }
  return t_enter < t_exit && t_exit > epsilon && t_enter < 1.0 - epsilon;
}

export function _path_is_clear(points: readonly PointLike[], obstacles: readonly BoxLike[]): boolean {
  for (let i = 0; i + 1 < points.length; i += 1) {
    for (const obstacle of obstacles) {
      if (_segment_hits_box(points[i], points[i + 1], obstacle)) return false;
    }
  }
  return true;
}

/** Reject interior crossings and connectors tangent to endpoint borders. */
export function _path_avoids_endpoint_interiors(points: readonly PointLike[], source_bbox: BBox, target_bbox: BBox): boolean {
  if (points.length < 2) return false;

  const outward = (endpoint: PointLike, adjacent: PointLike, box: BBox): boolean => {
    const [x, y] = endpoint;
    const dx = adjacent[0] - x;
    const dy = adjacent[1] - y;
    const normals: [number, number][] = [];
    if (Math.abs(x - box.x) < 1e-6) normals.push([-1, 0]);
    if (Math.abs(x - box.x - box.w) < 1e-6) normals.push([1, 0]);
    if (Math.abs(y - box.y) < 1e-6) normals.push([0, -1]);
    if (Math.abs(y - box.y - box.h) < 1e-6) normals.push([0, 1]);
    return !normals.length || normals.some(([nx, ny]) => dx * nx + dy * ny > 1e-6);
  };

  if (!outward(points[0], points[1], source_bbox) || !outward(points[points.length - 1], points[points.length - 2], target_bbox)) {
    return false;
  }
  return _path_is_clear(points, [_box_tuple(source_bbox), _box_tuple(target_bbox)]);
}

/** A route may neither enter a foreign node nor cut through its own ends. */
export function _route_is_legal(points: readonly PointLike[], obstacles: readonly BoxLike[], source_bbox: BBox, target_bbox: BBox): boolean {
  return _path_is_clear(points, obstacles) && _path_avoids_endpoint_interiors(points, source_bbox, target_bbox);
}

export function _path_length(points: readonly PointLike[]): number {
  let total = 0;
  for (let i = 0; i + 1 < points.length; i += 1) {
    const start = points[i];
    const end = points[i + 1];
    total += Math.abs(start[0] - end[0]) + Math.abs(start[1] - end[1]);
  }
  return total;
}

/** Count direction changes after ignoring duplicate path vertices. */
export function _path_bend_count(points: readonly PointLike[]): number {
  const directions: string[] = [];
  for (let i = 0; i + 1 < points.length; i += 1) {
    const dx = points[i + 1][0] - points[i][0];
    const dy = points[i + 1][1] - points[i][1];
    if (Math.abs(dx) <= 1e-6 && Math.abs(dy) <= 1e-6) continue;
    let direction: string;
    if (Math.abs(dx) <= 1e-6) direction = 'vertical';
    else if (Math.abs(dy) <= 1e-6) direction = 'horizontal';
    else direction = 'diagonal';
    if (!directions.length || directions[directions.length - 1] !== direction) directions.push(direction);
  }
  return Math.max(0, directions.length - 1);
}

export function _is_orthogonal(points: readonly PointLike[]): boolean {
  for (let i = 0; i + 1 < points.length; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    if (!(Math.abs(a[0] - b[0]) < 1e-6 || Math.abs(a[1] - b[1]) < 1e-6)) return false;
  }
  return true;
}

function _same_point(a: PointLike, b: PointLike): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return false;
  return true;
}

/** Drop duplicate and collinear grid vertices without changing geometry. */
export function _compress_orthogonal_path<P extends PointLike>(points: readonly P[]): P[] {
  const compact: P[] = [];
  for (const point of points) {
    if (compact.length && _same_point(point, compact[compact.length - 1])) continue;
    if (compact.length >= 2) {
      const first = compact[compact.length - 2];
      const second = compact[compact.length - 1];
      if (
        (Math.abs(first[0] - second[0]) <= 1e-6 && Math.abs(second[0] - point[0]) <= 1e-6)
        || (Math.abs(first[1] - second[1]) <= 1e-6 && Math.abs(second[1] - point[1]) <= 1e-6)
      ) {
        compact[compact.length - 1] = point;
        continue;
      }
    }
    compact.push(point);
  }
  return compact;
}

export function _box_tuple(bbox: Dict | BBox): Box {
  const box = bbox as Dict;
  return [box.x as number, box.y as number, box.w as number, box.h as number];
}

export function _bbox_center(bbox: Dict | BBox): Point {
  const box = bbox as Dict;
  return [(box.x as number) + (box.w as number) / 2.0, (box.y as number) + (box.h as number) / 2.0];
}

/** ``{x, y}`` waypoints as float point tuples. */
export function _xy(waypoints: readonly Dict[] | readonly { x: number; y: number }[]): Point[] {
  return (waypoints as readonly Dict[]).map((point) => [_float(point.x), _float(point.y)] as Point);
}

/** Point tuples as the ``{x, y}`` waypoints ``edge_router`` emits. */
export function _waypoints(points: readonly PointLike[]): { x: number; y: number }[] {
  return points.map(([x, y]) => ({ x, y }));
}

/** Return connectors that contribute to the rendered visual surface. */
export function _visible_arrows(arrows: readonly Dict[] | null | undefined): Dict[] {
  const visible: Dict[] = [];
  for (const arrow of (pyOr(arrows, []) as Dict[])) {
    if (pyGet(arrow, 'type') !== 'arrow' || truthy(pyGet(arrow, 'isDeleted'))) continue;
    let opacity: number;
    try {
      opacity = _float(pyOr(pyGet(arrow, 'opacity', 100), 0));
    } catch (error) {
      if (error instanceof PyTypeError || error instanceof ValueError) opacity = 100.0;
      else throw error;
    }
    if (opacity > 0) visible.push(arrow);
  }
  return visible;
}

/** Collect existing route vertices used to seed clear grid channels. */
export function _absolute_arrow_points(arrows: readonly Dict[] | null | undefined): Point[] {
  const points: Point[] = [];
  for (const arrow of _visible_arrows(arrows)) {
    const origin_x = _float(pyOr(pyGet(arrow, 'x', 0.0), 0.0));
    const origin_y = _float(pyOr(pyGet(arrow, 'y', 0.0), 0.0));
    for (const point of (pyOr(pyGet(arrow, 'points'), []) as unknown[])) {
      if (isDict(point)) {
        points.push([_float(pyGet(point, 'x', 0.0)), _float(pyGet(point, 'y', 0.0))]);
      } else if (Array.isArray(point) && point.length >= 2) {
        points.push([origin_x + _float(point[0]), origin_y + _float(point[1])]);
      }
    }
  }
  return points;
}

/** Origin, relative points and bbox size for an arrow on ``waypoints``. */
export function _arrow_path_fields(
  waypoints: readonly Dict[] | readonly { x: number; y: number }[],
  min_size = 1.0,
): { x: number; y: number; width: number; height: number; points: number[][] } {
  const [origin_x, origin_y, relative] = to_relative_points(waypoints as Dict[]);
  const [width, height] = waypoints_bbox(waypoints as Dict[]);
  const fields = {
    x: origin_x,
    y: origin_y,
    width: _max2(min_size, width),
    height: _max2(min_size, height),
    points: relative,
  };
  // to_relative_points / waypoints_bbox use float(); max(1.0, w) is a float.
  // (A caller passing the int ``min_size=1`` re-marks width/height itself.)
  for (const key of ['x', 'y', 'width', 'height']) markF(fields, key, true);
  for (const point of relative) {
    markF(point, 0, true);
    markF(point, 1, true);
  }
  return fields;
}

export function _path_crossing_count(points: readonly PointLike[], existing_arrows: readonly Dict[] | null | undefined): number {
  if (!truthy(existing_arrows)) return 0;
  const origin_x = pyMin(points.map((value) => value[0])) as number;
  const origin_y = pyMin(points.map((value) => value[1])) as number;
  const candidate_arrow = {
    id: '__route_candidate__',
    type: 'arrow',
    x: origin_x,
    y: origin_y,
    points: points.map(([x, y]) => [x - origin_x, y - origin_y]),
  };
  return count_arrow_crossings(candidate_arrow, _visible_arrows(existing_arrows));
}

export function _arrow_segments(arrow: Dict): [Point, Point][] {
  const origin: Point = [_float(pyGet(arrow, 'x', 0.0)), _float(pyGet(arrow, 'y', 0.0))];
  const absolute: Point[] = [];
  for (const point of (pyOr(pyGet(arrow, 'points'), []) as unknown[])) {
    if (isDict(point)) {
      absolute.push([origin[0] + _float(pyGet(point, 'x', 0.0)), origin[1] + _float(pyGet(point, 'y', 0.0))]);
    } else {
      const pair = point as unknown[];
      absolute.push([origin[0] + _float(pair[0]), origin[1] + _float(pair[1])]);
    }
  }
  const segments: [Point, Point][] = [];
  for (let i = 0; i + 1 < absolute.length; i += 1) segments.push([absolute[i], absolute[i + 1]]);
  return segments;
}

/** Score axis-aligned path segments that crowd existing edge channels. */
export function _path_parallel_channel_penalty(
  points: readonly unknown[],
  existing_arrows: readonly Dict[] | null | undefined,
  clearance = PARALLEL_CHANNEL_CLEARANCE,
): number {
  if (!truthy(existing_arrows) || points.length < 2) return 0.0;

  const normalized_points: Point[] = points.map((point) =>
    isDict(point)
      ? [_float(pyGet(point, 'x', 0.0)), _float(pyGet(point, 'y', 0.0))]
      : [_float((point as unknown[])[0]), _float((point as unknown[])[1])]);
  const other_segments: [Point, Point][] = [];
  for (const arrow of _visible_arrows(existing_arrows)) other_segments.push(..._arrow_segments(arrow));

  let penalty = 0.0;
  for (let i = 0; i + 1 < normalized_points.length; i += 1) {
    const start = normalized_points[i];
    const end = normalized_points[i + 1];
    const horizontal = Math.abs(start[1] - end[1]) <= 1e-6;
    const vertical = Math.abs(start[0] - end[0]) <= 1e-6;
    if (!(horizontal || vertical)) continue;
    const [start_axis, end_axis] = horizontal ? [start[0], end[0]] : [start[1], end[1]];
    const [low, high] = _sorted2(start_axis, end_axis);
    if (high - low <= 1e-6) continue;
    const fixed = horizontal ? start[1] : start[0];
    for (const [other_start, other_end] of other_segments) {
      const other_horizontal = Math.abs(other_start[1] - other_end[1]) <= 1e-6;
      const other_vertical = Math.abs(other_start[0] - other_end[0]) <= 1e-6;
      if (horizontal !== other_horizontal || vertical !== other_vertical) continue;
      const other_fixed = horizontal ? other_start[1] : other_start[0];
      const gap = Math.abs(fixed - other_fixed);
      if (gap >= clearance) continue;
      const [other_low, other_high] = horizontal
        ? _sorted2(other_start[0], other_end[0])
        : _sorted2(other_start[1], other_end[1]);
      const overlap = _max2(0.0, _min2(high, other_high) - _max2(low, other_low));
      if (overlap > 0.0) penalty += overlap * (clearance - gap) / clearance;
    }
  }
  return penalty;
}
