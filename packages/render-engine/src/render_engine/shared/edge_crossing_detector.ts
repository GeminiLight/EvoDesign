// Ported from evodesign/agentic_system/render_engine/shared/edge_crossing_detector.py — keep in sync.
//
// Edge-crossing detector for Excalidraw arrow polylines. Observational only —
// reports pairs of arrows whose rendered paths intersect (CCW orientation
// test, CLRS §33.1). Shared endpoints are convergence, not crossings; a
// collinear endpoint lying on the other segment's interior IS reported.

import { pyGet } from '../../py/dict.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { isfinite } from '../../py/math.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyMaxN, pyMinN, pySorted } from '../../py/sort.ts';
import { isDict, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;
export type Segment = [number, number, number, number];
type Box = [number, number, number, number];

/** ``float(value)`` with Python's TypeError / ValueError behaviour. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

// Epsilon for floating-point orientation checks.
export const _ORIENT_EPSILON = 1e-6;

/** Return whether an arrow contributes visible rendered geometry. */
export function _is_visible_arrow(arrow: Dict): boolean {
  if (pyGet(arrow, 'type') !== 'arrow' || truthy(pyGet(arrow, 'isDeleted'))) {
    return false;
  }
  try {
    return _float(pyOr(pyGet(arrow, 'opacity', 100), 0)) > 0;
  } catch (error) {
    if (error instanceof PyTypeError || error instanceof ValueError) {
      return true;
    }
    throw error;
  }
}

/** Sign of the 2D cross product ``(b-a) x (c-a)``. */
export function _orient(ax: number, ay: number, bx: number, by: number, cx: number, cy: number): number {
  const v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
  if (v > _ORIENT_EPSILON) {
    return 1;
  }
  if (v < -_ORIENT_EPSILON) {
    return -1;
  }
  return 0;
}

/** True iff colinear point ``C`` lies on segment ``AB`` (inclusive). */
export function _on_segment(ax: number, ay: number, bx: number, by: number, cx: number, cy: number): boolean {
  const loX = pyMinN(ax, bx) - _ORIENT_EPSILON;
  if (!(loX <= cx)) return false;
  if (!(cx <= pyMaxN(ax, bx) + _ORIENT_EPSILON)) return false;
  const loY = pyMinN(ay, by) - _ORIENT_EPSILON;
  if (!(loY <= cy)) return false;
  return cy <= pyMaxN(ay, by) + _ORIENT_EPSILON;
}

/** Two segments share an endpoint within epsilon → convergence, not crossing. */
export function _shares_endpoint(a: readonly number[], b: readonly number[]): boolean {
  const [ax1, ay1, ax2, ay2] = a;
  const [bx1, by1, bx2, by2] = b;
  for (const [px, py] of [[ax1, ay1], [ax2, ay2]]) {
    for (const [qx, qy] of [[bx1, by1], [bx2, by2]]) {
      if (Math.abs(px - qx) < _ORIENT_EPSILON && Math.abs(py - qy) < _ORIENT_EPSILON) {
        return true;
      }
    }
  }
  return false;
}

/** Orientation test for intersection of segments AB and CD. */
export function _segments_intersect(a: readonly number[], b: readonly number[]): boolean {
  const [ax1, ay1, ax2, ay2] = a;
  const [bx1, by1, bx2, by2] = b;

  const o1 = _orient(ax1, ay1, ax2, ay2, bx1, by1);
  const o2 = _orient(ax1, ay1, ax2, ay2, bx2, by2);
  const o3 = _orient(bx1, by1, bx2, by2, ax1, ay1);
  const o4 = _orient(bx1, by1, bx2, by2, ax2, ay2);

  // Proper intersection
  if (o1 !== o2 && o3 !== o4) {
    return true;
  }

  // Collinear contact (T-junction or same-line overlap), unless at shared endpoints.
  if (o1 === 0 && _on_segment(ax1, ay1, ax2, ay2, bx1, by1)) {
    if (!_shares_endpoint(a, b)) {
      return true;
    }
  }
  if (o2 === 0 && _on_segment(ax1, ay1, ax2, ay2, bx2, by2)) {
    if (!_shares_endpoint(a, b)) {
      return true;
    }
  }
  if (o3 === 0 && _on_segment(bx1, by1, bx2, by2, ax1, ay1)) {
    if (!_shares_endpoint(a, b)) {
      return true;
    }
  }
  if (o4 === 0 && _on_segment(bx1, by1, bx2, by2, ax2, ay2)) {
    if (!_shares_endpoint(a, b)) {
      return true;
    }
  }

  return false;
}

/** Flatten an Excalidraw arrow into its absolute-coord line segments. */
export function _arrow_segments(arrow: Dict): Segment[] {
  const pts = pyOr(pyGet(arrow, 'points'), []);
  if (!Array.isArray(pts) || pts.length < 2) {
    return [];
  }
  const ox = _float(pyOr(pyGet(arrow, 'x', 0.0), 0.0));
  const oy = _float(pyOr(pyGet(arrow, 'y', 0.0), 0.0));
  const abs_pts: [number, number][] = [];
  for (const p of pts) {
    if (Array.isArray(p) && p.length >= 2) {
      abs_pts.push([ox + _float(p[0]), oy + _float(p[1])]);
    } else if (isDict(p)) {
      abs_pts.push([_float(pyGet(p, 'x', 0.0)), _float(pyGet(p, 'y', 0.0))]);
    }
  }
  const segs: Segment[] = [];
  for (let i = 0; i < abs_pts.length - 1; i += 1) {
    const [x1, y1] = abs_pts[i];
    const [x2, y2] = abs_pts[i + 1];
    segs.push([x1, y1, x2, y2]);
  }
  return segs;
}

/** Count existing arrow paths crossed by one candidate segment. */
export function count_segment_crossings(segment: readonly number[], arrows: Dict[]): number {
  return count_prepared_crossings(segment, prepare_crossing_segments(arrows));
}

// Exact early rejection for axis-aligned pairs (see the Python module).
export const _AXIS_MIN_LENGTH = 1e-5;
export const _AXIS_GAP = 1.0;

export type _PreparedSegment = [Segment, Box | null];

/** Bounding box of an exactly axis-aligned, non-tiny segment, else None. */
export function _axis_box(segment: readonly number[]): Box | null {
  const [x1, y1, x2, y2] = segment;
  let length: number;
  if (y1 === y2) {
    length = Math.abs(x2 - x1);
  } else if (x1 === x2) {
    length = Math.abs(y2 - y1);
  } else {
    return null;
  }
  if (!(length >= _AXIS_MIN_LENGTH && segment.every((value) => isfinite(value)))) {
    return null;
  }
  return [pyMinN(x1, x2), pyMinN(y1, y2), pyMaxN(x1, x2), pyMaxN(y1, y2)];
}

export function _boxes_apart(a: readonly number[], b: readonly number[]): boolean {
  return (a[2] + _AXIS_GAP < b[0] || b[2] + _AXIS_GAP < a[0]
    || a[3] + _AXIS_GAP < b[1] || b[3] + _AXIS_GAP < a[1]);
}

export function _prepare(segments: Segment[]): _PreparedSegment[] {
  return segments.map((segment) => [segment, _axis_box(segment)]);
}

/** Box around an arrow whose segments all have axis boxes, else None. */
export function _union_box(prepared: _PreparedSegment[]): Box | null {
  const boxes = prepared.map(([, box]) => box);
  if (!boxes.length || boxes.some((box) => box === null)) {
    return null;
  }
  const full = boxes as Box[];
  return [
    pyMinN(...full.map((b) => b[0])),
    pyMinN(...full.map((b) => b[1])),
    pyMaxN(...full.map((b) => b[2])),
    pyMaxN(...full.map((b) => b[3])),
  ];
}

export type _PreparedArrow = [_PreparedSegment[], Box | null];

/** Flatten the visible arrows once for repeated crossing counts. */
export function prepare_crossing_segments(arrows: Dict[]): _PreparedArrow[] {
  const prepared: _PreparedArrow[] = [];
  for (const arrow of arrows) {
    if (_is_visible_arrow(arrow)) {
      const segments = _prepare(_arrow_segments(arrow));
      prepared.push([segments, _union_box(segments)]);
    }
  }
  return prepared;
}

/** :func:`count_segment_crossings` over :func:`prepare_crossing_segments` output. */
export function count_prepared_crossings(segment: readonly number[], prepared: _PreparedArrow[]): number {
  const box = _axis_box(segment);
  let count = 0;
  for (const [segments, arrow_box] of prepared) {
    if (box !== null && arrow_box !== null && _boxes_apart(box, arrow_box)) {
      continue;
    }
    for (const [existing_segment, existing_box] of segments) {
      if (box !== null && existing_box !== null && _boxes_apart(box, existing_box)) {
        continue;
      }
      if (_shares_endpoint(segment, existing_segment)) {
        continue;
      }
      if (_segments_intersect(segment, existing_segment)) {
        count += 1;
        break;
      }
    }
  }
  return count;
}

export type _IndexedArrow = [unknown, _PreparedSegment[], Box | null];

/** Prepared segments of a visible, identified arrow with a drawable path. */
export function _index_arrow(arrow: Dict): _IndexedArrow | null {
  if (!_is_visible_arrow(arrow)) {
    return null;
  }
  const aid = pyGet(arrow, 'id');
  if (!truthy(aid)) {
    return null;
  }
  const segs = _arrow_segments(arrow);
  if (!segs.length) {
    return null;
  }
  const prepared = _prepare(segs);
  return [aid, prepared, _union_box(prepared)];
}

/** Segment indices of the first crossing between two arrows, if any. */
export function _first_crossing(first: _IndexedArrow, second: _IndexedArrow): [number, number] | null {
  const [, segs_i, box_i_all] = first;
  const [, segs_j, box_j_all] = second;
  if (box_i_all !== null && box_j_all !== null && _boxes_apart(box_i_all, box_j_all)) {
    return null;
  }
  for (let si_idx = 0; si_idx < segs_i.length; si_idx += 1) {
    const [si, box_i] = segs_i[si_idx];
    for (let sj_idx = 0; sj_idx < segs_j.length; sj_idx += 1) {
      const [sj, box_j] = segs_j[sj_idx];
      if (box_i !== null && box_j !== null && _boxes_apart(box_i, box_j)) {
        continue;
      }
      if (_shares_endpoint(si, sj)) {
        // Convergence on a common point, not a crossing.
        continue;
      }
      if (_segments_intersect(si, sj)) {
        return [si_idx, sj_idx];
      }
    }
  }
  return null;
}

/** Return every pair of arrows whose polylines cross, as ``(smaller_id, larger_id, metadata)``. */
export function detect_crossings(arrows: Dict[] | null): [string, string, Dict][] {
  const indexed = (pyOr(arrows, []) as Dict[]).map(_index_arrow).filter((entry): entry is _IndexedArrow => entry !== null);
  const crossings: [string, string, Dict][] = [];
  for (let i = 0; i < indexed.length; i += 1) {
    for (let j = i + 1; j < indexed.length; j += 1) {
      const first_cross = _first_crossing(indexed[i], indexed[j]);
      if (first_cross === null) {
        continue;
      }
      const id_i = indexed[i][0];
      const id_j = indexed[j][0];
      const [a_id, b_id] = pySorted([id_i, id_j]);
      crossings.push([
        a_id as string,
        b_id as string,
        {
          segment_index_a: a_id === id_i ? first_cross[0] : first_cross[1],
          segment_index_b: a_id === id_i ? first_cross[1] : first_cross[0],
        },
      ]);
    }
  }
  return crossings;
}

/** Number of pairs :func:`detect_crossings` would report between ``arrow`` and ``others``. */
export function count_arrow_crossings(arrow: Dict, others: Dict[]): number {
  const indexed = _index_arrow(arrow);
  if (indexed === null) {
    return 0;
  }
  let total = 0;
  for (const other_arrow of others) {
    const other = _index_arrow(other_arrow);
    if (other !== null && _first_crossing(indexed, other) !== null) {
      total += 1;
    }
  }
  return total;
}
