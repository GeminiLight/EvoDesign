// Ported from evodesign/agentic_system/render_engine/excalidraw/edge_router.py — keep in sync.
//
// Deterministic waypoint computation for Excalidraw arrow polylines. Given a
// discrete ``(start_side, end_side)`` pair and the source/target bounding
// boxes, produces a 2-, 3-, 4-, or 5-point path (straight / L / Z / U /
// normal-respecting L). See the Python module docstring for the full table.

import { pyGet } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyMaxN, pyMinN } from '../../py/sort.ts';
import { pyRepr } from '../../py/str.ts';

type Dict = Record<string, unknown>;
export type WayPoint = { x: number; y: number };

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

export const ALIGNED_PAIRS: ReadonlySet<readonly [string, string]> = new Set([
  ['top', 'bottom'],
  ['bottom', 'top'],
  ['left', 'right'],
  ['right', 'left'],
] as const);

export const _VALID_SIDES: ReadonlySet<string> = new Set(['top', 'bottom', 'left', 'right']);

// Outward unit normal per face. An arrow must LEAVE the start face along
// +normal and ENTER the end face along -normal.
export const _FACE_NORMALS: Record<string, readonly [number, number]> = {
  top: [0.0, -1.0],
  bottom: [0.0, 1.0],
  left: [-1.0, 0.0],
  right: [1.0, 0.0],
};

function _normal(side: string): readonly [number, number] {
  if (!Object.prototype.hasOwnProperty.call(_FACE_NORMALS, side)) throw new KeyError(pyRepr(side));
  return _FACE_NORMALS[side];
}

/** ``point`` shifted ``offset`` units along ``side``'s outward normal. */
export function _normal_offset_point(point: WayPoint, side: string, offset: number): WayPoint {
  const [nx, ny] = _normal(side);
  return { x: point.x + nx * offset, y: point.y + ny * offset };
}

/** True iff p_from→p_to strictly leaves ``side`` along its outward normal. */
export function _exits_along_normal(p_from: WayPoint, p_to: WayPoint, side: string): boolean {
  const [nx, ny] = _normal(side);
  return (p_to.x - p_from.x) * nx + (p_to.y - p_from.y) * ny > 0;
}

/** True iff p_from→p_to strictly enters ``side`` against its outward normal. */
export function _enters_along_normal(p_from: WayPoint, p_to: WayPoint, side: string): boolean {
  const [nx, ny] = _normal(side);
  return (p_to.x - p_from.x) * nx + (p_to.y - p_from.y) * ny < 0;
}

/** Drop consecutive duplicate points. */
export function _dedupe_consecutive(points: WayPoint[]): WayPoint[] {
  const result: WayPoint[] = [];
  for (const point of points) {
    if (result.length && result[result.length - 1].x === point.x && result[result.length - 1].y === point.y) {
      continue;
    }
    result.push(point);
  }
  return result;
}

/** Absolute coord of the midpoint on one face of ``bbox``. */
export function _side_midpoint(bbox: Dict, side: string): WayPoint {
  const x = _float(pyGet(bbox, 'x', 0.0));
  const y = _float(pyGet(bbox, 'y', 0.0));
  const w = _float(pyGet(bbox, 'w', 0.0));
  const h = _float(pyGet(bbox, 'h', 0.0));
  if (side === 'top') return { x: x + w / 2.0, y };
  if (side === 'bottom') return { x: x + w / 2.0, y: y + h };
  if (side === 'left') return { x, y: y + h / 2.0 };
  if (side === 'right') return { x: x + w, y: y + h / 2.0 };
  throw new ValueError(`Unknown side: ${pyRepr(side)}`);
}

/** Return a signed offset for the i-th edge among ``total`` siblings. */
export function _stagger_delta(index: number, total: number, spacing: number): number {
  if (total <= 1 || spacing === 0.0) return 0.0;
  return (index - (total - 1) / 2.0) * spacing;
}

/** Stagger a corridor without pushing it into either endpoint node. */
export function _bounded_midpoint(
  start: number,
  end: number,
  index: number,
  total: number,
  spacing: number,
  margin = 12.0,
): number {
  const midpoint = (start + end) / 2.0;
  const low = pyMinN(start, end) + margin;
  const high = pyMaxN(start, end) - margin;
  if (low >= high) return midpoint;
  return pyMaxN(low, pyMinN(high, midpoint + _stagger_delta(index, total, spacing)));
}

/** Return a bounded offset for a fan-out port on one shape face. */
export function _face_stagger_delta(
  index: number,
  total: number,
  span: number,
  spacing: number,
  margin = 8.0,
): number {
  const raw = _stagger_delta(index, total, spacing);
  const max_delta = pyMaxN(0.0, (_float(span) - 2.0 * margin) / 2.0);
  return pyMaxN(-max_delta, pyMinN(max_delta, raw));
}

/** Move a face midpoint along its face for deterministic port fan-out. */
export function _offset_face_point(
  point: WayPoint,
  bbox: Dict,
  side: string,
  index: number,
  total: number,
  spacing: number,
): WayPoint {
  const offset = _face_stagger_delta(
    index,
    total,
    (side === 'top' || side === 'bottom' ? pyGet(bbox, 'w', 0.0) : pyGet(bbox, 'h', 0.0)) as number,
    spacing,
  );
  const adjusted = { ...point };
  if (side === 'top' || side === 'bottom') adjusted.x += offset;
  else adjusted.y += offset;
  return adjusted;
}

/** Compute a polyline path between two face midpoints: ``[points, focus_start, focus_end]``. */
export function compute_waypoints(
  start_side: string,
  end_side: string,
  src_bbox: Dict,
  tgt_bbox: Dict,
  alignment_tol = 2.0,
  offset = 30.0,
  stagger_index = 0,
  stagger_total = 1,
  stagger_spacing = 50.0,
  start_port_index = 0,
  start_port_total = 1,
  end_port_index = 0,
  end_port_total = 1,
  port_spacing = 32.0,
): [WayPoint[], number, number] {
  if (!_VALID_SIDES.has(start_side)) throw new ValueError(`Invalid start_side: ${pyRepr(start_side)}`);
  if (!_VALID_SIDES.has(end_side)) throw new ValueError(`Invalid end_side: ${pyRepr(end_side)}`);

  const start = _offset_face_point(
    _side_midpoint(src_bbox, start_side), src_bbox, start_side, start_port_index, start_port_total, port_spacing,
  );
  const end = _offset_face_point(
    _side_midpoint(tgt_bbox, end_side), tgt_bbox, end_side, end_port_index, end_port_total, port_spacing,
  );

  const start_vertical = start_side === 'top' || start_side === 'bottom';

  const at = (along: number, across: number): WayPoint => (start_vertical ? { x: across, y: along } : { x: along, y: across });

  const [travel, cross] = (start_vertical ? ['y', 'x'] : ['x', 'y']) as ['x' | 'y', 'x' | 'y'];

  // ---------- Aligned pairs: straight or Z-shape ----------
  if (pyIn([start_side, end_side], [...ALIGNED_PAIRS])) {
    if (Math.abs(start[cross] - end[cross]) < alignment_tol) return [[start, end], 0.0, 0.0];
    const mid = _bounded_midpoint(start[travel], end[travel], stagger_index, stagger_total, stagger_spacing);
    return [[start, at(mid, start[cross]), at(mid, end[cross]), end], 0.0, 0.0];
  }

  // ---------- Same-face pair: U-shape ----------
  if (start_side === end_side) {
    let detour: number;
    if (start_side === 'top' || start_side === 'left') detour = pyMinN(start[travel], end[travel]) - offset;
    else detour = pyMaxN(start[travel], end[travel]) + offset;
    detour += _stagger_delta(stagger_index, stagger_total, stagger_spacing);
    return [[start, at(detour, start[cross]), at(detour, end[cross]), end], 0.0, 0.0];
  }

  // ---------- Perpendicular pair: L-shape ----------
  let naive_normal_ahead: boolean;
  if (start_vertical) naive_normal_ahead = (end.y - start.y) * _FACE_NORMALS[start_side][1] > 0;
  else naive_normal_ahead = (end.x - start.x) * _FACE_NORMALS[start_side][0] > 0;

  let candidate: WayPoint[];
  if (naive_normal_ahead) {
    if (start_vertical) candidate = [start, { x: start.x, y: end.y }, end];
    else candidate = [start, { x: end.x, y: start.y }, end];
  } else {
    const detour = _normal_offset_point(start, start_side, offset);
    if (start_vertical) candidate = [start, detour, { x: end.x, y: detour.y }, end];
    else candidate = [start, detour, { x: detour.x, y: end.y }, end];
  }

  const ends_legal = _exits_along_normal(candidate[0], candidate[1], start_side)
    && _enters_along_normal(candidate[candidate.length - 2], candidate[candidate.length - 1], end_side);
  if (ends_legal) return [candidate, 0.0, 0.0];

  // 5-point upgrade: offsets along BOTH face normals plus one transition corner.
  const exit_point = _normal_offset_point(start, start_side, offset);
  const approach_point = _normal_offset_point(end, end_side, offset);
  let transition: WayPoint;
  if (start_vertical) transition = { x: approach_point.x, y: exit_point.y };
  else transition = { x: exit_point.x, y: approach_point.y };
  const points = _dedupe_consecutive([start, exit_point, transition, approach_point, end]);
  return [points, 0.0, 0.0];
}

/** Width/height of the axis-aligned bounding box of a points list. */
export function waypoints_bbox(points: Dict[] | WayPoint[]): [number, number] {
  if (!points.length) return [0.0, 0.0];
  const xs = (points as Dict[]).map((p) => _float(p.x));
  const ys = (points as Dict[]).map((p) => _float(p.y));
  return [pyMaxN(...xs) - pyMinN(...xs), pyMaxN(...ys) - pyMinN(...ys)];
}

/** Convert absolute waypoints to Excalidraw arrow-element shape: ``[origin_x, origin_y, relative]``. */
export function to_relative_points(points: Dict[] | WayPoint[]): [number, number, number[][]] {
  if (!points.length) return [0.0, 0.0, []];
  const list = points as Dict[];
  const origin_x = _float(list[0].x);
  const origin_y = _float(list[0].y);
  const rel = list.map((p) => [_float(p.x) - origin_x, _float(p.y) - origin_y]);
  return [origin_x, origin_y, rel];
}
