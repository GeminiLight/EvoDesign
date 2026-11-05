// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_routing/grid_router.py — keep in sync.
//
// Orthogonal visibility-grid router (draw.io style) with a per-pass memo.

import { pyGet } from '../../../py/dict.ts';
import { PyTypeError } from '../../../py/errors.ts';
import { pyFloatParse } from '../../../py/number.ts';
import { floatRepr, pyRepr } from '../../../py/str.ts';
import { count_prepared_crossings, prepare_crossing_segments } from '../../shared/edge_crossing_detector.ts';
import {
  type Box,
  type Point,
  _absolute_arrow_points,
  _compress_orthogonal_path,
  _path_is_clear,
  _visible_arrows,
} from './geometry.ts';

type Dict = Record<string, unknown>;
type PointLike = readonly number[];
type BoxLike = readonly number[];

export const ROUTE_BEND_PENALTY = 36.0;
export const _ROUTE_CROSSING_PENALTY = 1800.0;
export const _ROUTE_DEVIATION_PENALTY = 0.01;
export const _SPAN_MARGIN = 1.0; // well beyond the 1e-6 interior epsilon of _segment_hits_box

export type PortNormals = readonly [PointLike, PointLike];

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

/** Obstacles whose span on ``axis`` (0 = x, 1 = y) reaches ``value``. */
export function _obstacles_spanning<B extends BoxLike>(obstacles: readonly B[], value: number, axis: number): B[] {
  return obstacles.filter((obstacle) =>
    obstacle[axis] - _SPAN_MARGIN <= value && value <= obstacle[axis] + obstacle[axis + 2] + _SPAN_MARGIN);
}

/** Obstacles whose span on ``axis`` overlaps ``[low, high]`` (with margin). */
export function _obstacles_overlapping<B extends BoxLike>(obstacles: readonly B[], low: number, high: number, axis: number): B[] {
  return obstacles.filter((obstacle) =>
    obstacle[axis] - _SPAN_MARGIN <= high && low <= obstacle[axis] + obstacle[axis + 2] + _SPAN_MARGIN);
}

/**
 * Minimal ``contextvars.ContextVar`` stand-in. The engine is synchronous, so
 * a module-level slot with token-based reset gives the same scoping.
 */
export class ContextVar<T> {
  #value: T;
  constructor(readonly name: string, defaultValue: T) {
    this.#value = defaultValue;
  }

  get(): T {
    return this.#value;
  }

  set(value: T): { previous: T } {
    const token = { previous: this.#value };
    this.#value = value;
    return token;
  }

  reset(token: { previous: T }): void {
    this.#value = token.previous;
  }
}

// Routes are pure functions of their geometric input, and one render asks for
// the same route many times. The memo lives for one top-level arrow pass only
// (owned by ``add_excalidraw_arrows_to_manifest``).
export const _ROUTE_MEMO = new ContextVar<Map<string, Point[] | null> | null>('_ROUTE_MEMO', null);

function _num_repr(value: unknown): string {
  return typeof value === 'number' ? floatRepr(value) : pyRepr(value);
}

function _tuple_repr(items: readonly string[]): string {
  return items.length === 1 ? `(${items[0]},)` : `(${items.join(', ')})`;
}

function _float_seq_repr(value: unknown, tuple: boolean): string {
  if (!Array.isArray(value)) return pyRepr(value);
  const items = value.map(_num_repr);
  return tuple ? _tuple_repr(items) : `[${items.join(', ')}]`;
}

/**
 * ``repr((start, end, obstacles, arrows, clearance, port_normals))``.
 *
 * TS numbers carry no int/float distinction, so geometric values (always
 * floats on the Python side) are printed as float reprs; ``type``,
 * ``isDeleted`` and ``opacity`` use the generic ``pyRepr``. Arrow ``points``
 * print as lists of lists, the shape ``_arrow_path_fields`` produces. The
 * key only needs to be injective for the memo; parity with Python's repr is
 * a bonus that holds for every recorded vector.
 */
export function _route_memo_key(
  start: PointLike,
  end: PointLike,
  obstacles: readonly BoxLike[],
  existing_arrows: readonly Dict[] | null | undefined,
  clearance: number,
  port_normals: PortNormals | null | undefined,
): string {
  const arrows = (existing_arrows ?? []).map((arrow) => {
    const points = pyGet(arrow, 'points');
    const points_repr = Array.isArray(points)
      ? `[${points.map((point) => (Array.isArray(point) ? _float_seq_repr(point, false) : pyRepr(point))).join(', ')}]`
      : pyRepr(points);
    return _tuple_repr([
      pyRepr(pyGet(arrow, 'type')),
      pyRepr(pyGet(arrow, 'isDeleted')),
      pyRepr(pyGet(arrow, 'opacity', 100)),
      _num_repr(pyGet(arrow, 'x')),
      _num_repr(pyGet(arrow, 'y')),
      points_repr,
    ]);
  });
  const normals_repr = port_normals === null || port_normals === undefined
    ? 'None'
    : _tuple_repr(port_normals.map((normal) => _float_seq_repr(normal, true)));
  return _tuple_repr([
    _float_seq_repr(start, true),
    _float_seq_repr(end, true),
    `[${obstacles.map((obstacle) => _float_seq_repr(obstacle, true)).join(', ')}]`,
    `[${arrows.join(', ')}]`,
    _num_repr(clearance),
    normals_repr,
  ]);
}

function _copy_route(route: Point[] | null): Point[] | null {
  return route === null ? null : route.map((point) => [point[0], point[1]] as Point);
}

/** Memoized :func:`_find_orthogonal_visibility_route` within one arrow pass. */
export function _orthogonal_visibility_route(
  start: PointLike,
  end: PointLike,
  obstacles: readonly BoxLike[],
  existing_arrows: readonly Dict[] | null | undefined,
  clearance: number,
  port_normals: PortNormals | null = null,
): Point[] | null {
  const memo = _ROUTE_MEMO.get();
  if (memo === null) {
    return _find_orthogonal_visibility_route(start, end, obstacles, existing_arrows, clearance, port_normals);
  }
  const key = _route_memo_key(start, end, obstacles, existing_arrows, clearance, port_normals);
  if (!memo.has(key)) {
    memo.set(key, _find_orthogonal_visibility_route(start, end, obstacles, existing_arrows, clearance, port_normals));
  }
  // Hits return copies: TS tuples are mutable arrays.
  return _copy_route(memo.get(key)!);
}

type HeapItem = [number, number, Point, string];

/** Binary min-heap on ``(cost, serial)``; serials are unique, so pop order equals ``heapq``'s. */
class _Heap {
  private items: HeapItem[] = [];

  get size(): number {
    return this.items.length;
  }

  private static less(a: HeapItem, b: HeapItem): boolean {
    return a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);
  }

  push(item: HeapItem): void {
    const items = this.items;
    items.push(item);
    let index = items.length - 1;
    while (index > 0) {
      const parent = (index - 1) >> 1;
      if (!_Heap.less(items[index], items[parent])) break;
      [items[index], items[parent]] = [items[parent], items[index]];
      index = parent;
    }
  }

  pop(): HeapItem {
    const items = this.items;
    const top = items[0];
    const last = items.pop()!;
    if (items.length) {
      items[0] = last;
      let index = 0;
      for (;;) {
        const left = 2 * index + 1;
        const right = left + 1;
        let smallest = index;
        if (left < items.length && _Heap.less(items[left], items[smallest])) smallest = left;
        if (right < items.length && _Heap.less(items[right], items[smallest])) smallest = right;
        if (smallest === index) break;
        [items[index], items[smallest]] = [items[smallest], items[index]];
        index = smallest;
      }
    }
    return top;
  }
}

function _key(x: number, y: number): string {
  // String(-0) === '0', matching Python's hash/equality of 0.0 and -0.0.
  return `${x},${y}`;
}

/** Find a draw.io-style orthogonal route through a visibility grid. */
export function _find_orthogonal_visibility_route(
  start: PointLike,
  end: PointLike,
  obstacles: readonly BoxLike[],
  existing_arrows: readonly Dict[] | null | undefined,
  clearance: number,
  port_normals: PortNormals | null = null,
): Point[] | null {
  const visible_arrows = _visible_arrows(existing_arrows);
  const expanded: Box[] = obstacles.map(([left, top, width, height]) =>
    [left - clearance, top - clearance, width + 2.0 * clearance, height + 2.0 * clearance]);

  const x_values = new Set<number>([_float(start[0]), _float(end[0])]);
  const y_values = new Set<number>([_float(start[1]), _float(end[1])]);
  for (const [left, top, width, height] of expanded) {
    x_values.add(left);
    x_values.add(left + width);
    y_values.add(top);
    y_values.add(top + height);
  }
  for (const [x, y] of _absolute_arrow_points(visible_arrows)) {
    x_values.add(x - clearance);
    x_values.add(x + clearance);
    y_values.add(y - clearance);
    y_values.add(y + clearance);
  }

  const xs = [...x_values].sort((a, b) => a - b);
  const ys = [...y_values].sort((a, b) => a - b);

  // A grid point is unavailable only inside an obstacle's strict interior.
  const points = new Map<string, Point>();
  for (const x of xs) {
    const column_obstacles = _obstacles_spanning(expanded, x, 0);
    for (const y of ys) {
      let blocked = false;
      for (const [left, top, width, height] of column_obstacles) {
        if (left + 1e-6 < x && x < left + width - 1e-6 && top + 1e-6 < y && y < top + height - 1e-6) {
          blocked = true;
          break;
        }
      }
      if (!blocked) points.set(_key(x, y), [x, y]);
    }
  }
  const start_key = _key(start[0], start[1]);
  const end_key = _key(end[0], end[1]);
  if (!points.has(start_key) || !points.has(end_key)) return null;

  // Python groups the point set by row/column and sorts each group by the
  // other coordinate; walking the sorted axes yields the same ordered lists.
  const rows = new Map<number, Point[]>();
  const columns = new Map<number, Point[]>();
  for (const x of xs) {
    for (const y of ys) {
      const point = points.get(_key(x, y));
      if (!point) continue;
      if (!rows.has(y)) rows.set(y, []);
      rows.get(y)!.push(point);
      if (!columns.has(x)) columns.set(x, []);
      columns.get(x)!.push(point);
    }
  }

  const neighbors = new Map<string, [Point, string][]>();
  for (const key of points.keys()) neighbors.set(key, []);
  for (const y of ys) {
    const row = rows.get(y) ?? [];
    const row_obstacles = _obstacles_spanning(expanded, y, 1);
    for (let i = 0; i + 1 < row.length; i += 1) {
      const left_point = row[i];
      const right_point = row[i + 1];
      const blockers = _obstacles_overlapping(row_obstacles, left_point[0], right_point[0], 0);
      if (_path_is_clear([left_point, right_point], blockers)) {
        neighbors.get(_key(left_point[0], left_point[1]))!.push([right_point, 'horizontal']);
        neighbors.get(_key(right_point[0], right_point[1]))!.push([left_point, 'horizontal']);
      }
    }
  }
  for (const x of xs) {
    const column = columns.get(x) ?? [];
    const column_obstacles = _obstacles_spanning(expanded, x, 0);
    for (let i = 0; i + 1 < column.length; i += 1) {
      const top_point = column[i];
      const bottom_point = column[i + 1];
      const blockers = _obstacles_overlapping(column_obstacles, top_point[1], bottom_point[1], 1);
      if (_path_is_clear([top_point, bottom_point], blockers)) {
        neighbors.get(_key(top_point[0], top_point[1]))!.push([bottom_point, 'vertical']);
        neighbors.get(_key(bottom_point[0], bottom_point[1]))!.push([top_point, 'vertical']);
      }
    }
  }

  const prepared_arrows = prepare_crossing_segments(visible_arrows);
  const edge_crossings = new Map<string, number>();
  const start_point: Point = [start[0], start[1]];
  const start_state_key = `${start_key}|`;
  const primary_axis = Math.abs(start[1] - end[1]) <= 1e-6
    ? 'horizontal'
    : Math.abs(start[0] - end[0]) <= 1e-6
      ? 'vertical'
      : '';
  const distances = new Map<string, number>([[start_state_key, 0.0]]);
  const previous = new Map<string, [Point, string]>();
  const queue = new _Heap();
  let serial = 0;
  queue.push([0.0, serial, start_point, '']);
  let final_state: [Point, string] | null = null;

  while (queue.size) {
    const [cost, , point, direction] = queue.pop();
    const point_key = _key(point[0], point[1]);
    const state_key = `${point_key}|${direction}`;
    if (cost > (distances.get(state_key) ?? Infinity) + 1e-6) continue;
    if (point[0] === end[0] && point[1] === end[1]) {
      final_state = [point, direction];
      break;
    }
    for (const [next_point, next_direction] of neighbors.get(point_key)!) {
      if (port_normals !== null && port_normals !== undefined) {
        const dx = next_point[0] - point[0];
        const dy = next_point[1] - point[1];
        const [start_normal, end_normal] = port_normals;
        // The first/last grid steps must not fold back over the fixed
        // endpoint stubs. Perpendicular turns at a lead remain valid.
        if (point[0] === start[0] && point[1] === start[1] && dx * start_normal[0] + dy * start_normal[1] < -1e-6) continue;
        if (next_point[0] === end[0] && next_point[1] === end[1] && dx * end_normal[0] + dy * end_normal[1] > 1e-6) continue;
      }
      const distance = Math.abs(next_point[0] - point[0]) + Math.abs(next_point[1] - point[1]);
      const bend_cost = direction && direction !== next_direction ? ROUTE_BEND_PENALTY : 0.0;
      const next_key = _key(next_point[0], next_point[1]);
      const edge_key = `${point_key}>${next_key}`;
      let crossing_count = edge_crossings.get(edge_key);
      if (crossing_count === undefined) {
        crossing_count = count_prepared_crossings([point[0], point[1], next_point[0], next_point[1]], prepared_arrows);
        edge_crossings.set(edge_key, crossing_count);
      }
      let deviation_cost = 0.0;
      if (primary_axis === 'horizontal' && next_direction === 'horizontal') {
        deviation_cost = distance * Math.abs(point[1] - start[1]) * _ROUTE_DEVIATION_PENALTY;
      } else if (primary_axis === 'vertical' && next_direction === 'vertical') {
        deviation_cost = distance * Math.abs(point[0] - start[0]) * _ROUTE_DEVIATION_PENALTY;
      }
      const next_cost = cost + distance + bend_cost + deviation_cost + crossing_count * _ROUTE_CROSSING_PENALTY;
      const next_state_key = `${next_key}|${next_direction}`;
      if (next_cost + 1e-6 >= (distances.get(next_state_key) ?? Infinity)) continue;
      distances.set(next_state_key, next_cost);
      previous.set(next_state_key, [point, direction]);
      serial += 1;
      queue.push([next_cost, serial, next_point, next_direction]);
    }
  }

  if (final_state === null) return null;

  const route: Point[] = [final_state[0]];
  let state = final_state;
  let state_key = `${_key(state[0][0], state[0][1])}|${state[1]}`;
  while (state_key !== start_state_key) {
    state = previous.get(state_key)!;
    state_key = `${_key(state[0][0], state[0][1])}|${state[1]}`;
    route.push(state[0]);
  }
  route.reverse();
  return _compress_orthogonal_path(route);
}
