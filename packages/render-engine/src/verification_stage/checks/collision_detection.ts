// Ported from evodesign/agentic_system/verification_stage/checks/collision_detection.py — keep in sync.
//
// Geometric collision detection: node overlap and edge path defects.
//
// These two checks are pure pixel-math: they don't depend on chart_type or any
// LLM output, and complement the structural checks in render_validation /
// binding_consistency.
//
// **Node overlap** — two non-arrow shapes whose bboxes intersect, EXCLUDING:
// - group ⊃ child (legitimate containment)
// - text ⊂ shape (bound label inside its container)
// - shape inside its own group background
//
// **Edge crossings** — pairs of arrow segments that cross. Reported only as
// INFO unless the count exceeds a threshold (then MINOR), since some crossings
// are unavoidable.
//
// **Edge-node intersections** — an arrow path entering a non-endpoint node is a
// MAJOR visual defect. The source and target shapes are excluded because the
// path intentionally terminates on their faces.
//
// Out-of-canvas: shape bbox outside the configured safe area
// `[CANVAS_MARGIN, MAX_CANVAS-CANVAS_MARGIN]`. Reported as MINOR.

import { CANVAS_MARGIN, CANVAS_MAX_X, CANVAS_MAX_Y } from '../../canvas_environment/constants.ts';
import { detect_group_frame_ids } from '../../canvas_environment/validation.ts';
import { DECORATION_KEY, JUNCTION_KEY } from '../../common/node_icons.ts';
import { id_map_from_manifest } from '../../common/semantic_ids.ts';
import { pyGet, pyGetItem, pyItems } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { IndexError, PyTypeError, ValueError } from '../../py/errors.ts';
import { PY_FLOAT_MARKS } from '../../py/json_decoder.ts';
import { pyFloatParse } from '../../py/number.ts';
import { numberStr, pyFormatFixed, pyRepr, pyStr } from '../../py/str.ts';
import { isDict, isList, truthy } from '../../py/truthy.ts';
import { Finding, Severity } from './finding.ts';

type Dict = Record<string, any>;
type BBox = [number, number, number, number];
type Point = [number, number];
type Segment = [Point, Point];

export const _OVERLAP_TOLERANCE_PX = 2; // ignore touching edges
export const _EDGE_CROSSING_INFO_THRESHOLD = 0; // 0..N crossings → INFO
export const _EDGE_CROSSING_MINOR_THRESHOLD = 4; // >N crossings → MINOR

/** Python ``float(value)``. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError('float() argument must be a string or a real number');
}

function _isConversionError(error: unknown): boolean {
  return error instanceof PyTypeError || error instanceof ValueError || error instanceof TypeError;
}

/** ``value or 0`` */
function _or0(value: unknown): unknown {
  return truthy(value) ? value : 0;
}

/** Return whether an element is intentionally absent from the visual surface. */
export function _is_fully_transparent(elem: Dict): boolean {
  try {
    return _float(pyGet(elem, 'opacity', 100)) <= 0;
  } catch (error) {
    if (_isConversionError(error)) return false;
    throw error;
  }
}

/** Junction dots, zone backgrounds and titles are design decoration, not nodes. */
export function _is_decoration(elem: Dict): boolean {
  const custom = pyGet(elem, 'customData');
  return isDict(custom) && truthy(truthy(pyGet(custom, JUNCTION_KEY)) ? pyGet(custom, JUNCTION_KEY) : pyGet(custom, DECORATION_KEY));
}

export function _bbox(elem: Dict): BBox | null {
  let x: number;
  let y: number;
  let w: number;
  let h: number;
  try {
    x = _float(_or0(pyGet(elem, 'x', 0)));
    y = _float(_or0(pyGet(elem, 'y', 0)));
    w = _float(_or0(pyGet(elem, 'width', 0)));
    h = _float(_or0(pyGet(elem, 'height', 0)));
  } catch (error) {
    if (_isConversionError(error)) return null;
    throw error;
  }
  return [x, y, w, h];
}

export function _bboxes_overlap(a: readonly number[], b: readonly number[], tol: number = _OVERLAP_TOLERANCE_PX): boolean {
  const [ax, ay, aw, ah] = a;
  const [bx, by, bw, bh] = b;
  if (aw <= 0 || ah <= 0 || bw <= 0 || bh <= 0) {
    return false;
  }
  return !(
    ax + aw <= bx + tol
    || bx + bw <= ax + tol
    || ay + ah <= by + tol
    || by + bh <= ay + tol
  );
}

/** Standard 2D segment-segment intersection test (proper crossings only). */
export function _segments_intersect(
  p1: readonly number[],
  p2: readonly number[],
  p3: readonly number[],
  p4: readonly number[],
): boolean {
  const cross = (o: readonly number[], a: readonly number[], b: readonly number[]): number =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

  const d1 = cross(p3, p4, p1);
  const d2 = cross(p3, p4, p2);
  const d3 = cross(p1, p2, p3);
  const d4 = cross(p1, p2, p4);
  if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {
    return true;
  }
  return false;
}

/** ``p[i]`` with Python's TypeError / IndexError (KeyError for dicts propagates). */
function _index(p: unknown, i: number): unknown {
  if (Array.isArray(p)) {
    if (i >= p.length) throw new IndexError('list index out of range');
    return p[i];
  }
  if (typeof p === 'string') {
    const chars = [...p];
    if (i >= chars.length) throw new IndexError('string index out of range');
    return chars[i];
  }
  if (isDict(p)) return pyGetItem(p, i);
  throw new PyTypeError('object is not subscriptable');
}

/**
 * All consecutive waypoint segments of an Excalidraw arrow in screen space.
 *
 * Excalidraw arrows are multi-segment polylines (orthogonal routing).
 * Treating an arrow as just ``points[0] → points[-1]`` produces both false
 * positives and false negatives.
 */
export function _arrow_segments(elem: Dict): Segment[] {
  let x0: number;
  let y0: number;
  try {
    x0 = _float(_or0(pyGet(elem, 'x', 0)));
    y0 = _float(_or0(pyGet(elem, 'y', 0)));
  } catch (error) {
    if (_isConversionError(error)) return [];
    throw error;
  }

  const points = pyGet(elem, 'points');
  if (!isList(points) || points.length < 2) {
    return [];
  }

  const abs_pts: Point[] = [];
  for (const p of points) {
    try {
      abs_pts.push([x0 + _float(_index(p, 0)), y0 + _float(_index(p, 1))]);
    } catch (error) {
      if (_isConversionError(error) || error instanceof IndexError) return [];
      throw error;
    }
  }

  const segments: Segment[] = [];
  for (let i = 0; i < abs_pts.length - 1; i += 1) {
    const [a, b] = [abs_pts[i], abs_pts[i + 1]];
    if (pyEq(a, b)) {
      continue; // zero-length segment, ignore
    }
    segments.push([a, b]);
  }
  return segments;
}

/** Return whether a segment enters the strict interior of a rectangle. */
export function _segment_intersects_rect_interior(
  start: readonly number[],
  end: readonly number[],
  bbox: readonly number[],
  epsilon = 1e-6,
): boolean {
  const [x, y, width, height] = bbox;
  if (width <= 0 || height <= 0) {
    return false;
  }

  // Liang-Barsky clipping against a slightly inset rectangle.  Insetting
  // avoids treating a path that merely touches a node border as an overlap.
  const left = x + epsilon;
  const right = x + width - epsilon;
  const top = y + epsilon;
  const bottom = y + height - epsilon;
  if (left >= right || top >= bottom) {
    return false;
  }

  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  let t_enter = 0.0;
  let t_exit = 1.0;
  for (const [p, q] of [
    [-dx, start[0] - left],
    [dx, right - start[0]],
    [-dy, start[1] - top],
    [dy, bottom - start[1]],
  ]) {
    if (Math.abs(p) <= epsilon) {
      if (q < 0) {
        return false;
      }
      continue;
    }
    const ratio = q / p;
    if (p < 0) {
      t_enter = Math.max(t_enter, ratio);
    } else {
      t_exit = Math.min(t_exit, ratio);
    }
    if (t_enter >= t_exit) {
      return false;
    }
  }
  return t_enter < t_exit && t_exit > epsilon && t_enter < 1.0 - epsilon;
}

/** Resolve semantic or direct endpoint references by endpoint role. */
export function _arrow_endpoint_ids(arrow: Dict, id_map: Record<string, string>): Record<'source' | 'target', Set<string>> {
  const endpoint_ids: Record<'source' | 'target', Set<string>> = { source: new Set(), target: new Set() };
  for (const [binding_key, role] of [['startBinding', 'source'], ['endBinding', 'target']] as const) {
    const binding = pyGet(arrow, binding_key);
    if (isDict(binding) && truthy(pyGet(binding, 'elementId'))) {
      endpoint_ids[role].add(pyStr(pyGetItem(binding, 'elementId')));
    }
  }

  let metadata = pyGet(arrow, 'meta');
  if (!isDict(metadata)) {
    metadata = pyGet(arrow, '_meta');
  }
  if (isDict(metadata)) {
    for (const key of ['source', 'target'] as const) {
      let ref = pyGet(metadata, key);
      if (ref !== null && ref !== undefined) {
        ref = pyStr(ref);
        endpoint_ids[key].add(pyStr(pyGet(id_map, ref, ref)));
      }
    }
  }
  return endpoint_ids;
}

/** Detect a visible parallel run along an unrelated node border. */
export function _segment_tracks_border(
  start: readonly number[],
  end: readonly number[],
  bbox: readonly number[],
  clearance: number,
): boolean {
  const [x, y, width, height] = bbox;
  let overlap: number;
  let distance: number;
  if (Math.abs(start[1] - end[1]) <= 1e-6) {
    overlap = Math.min(Math.max(start[0], end[0]), x + width) - Math.max(Math.min(start[0], end[0]), x);
    distance = Math.min(Math.abs(start[1] - y), Math.abs(start[1] - y - height));
  } else if (Math.abs(start[0] - end[0]) <= 1e-6) {
    overlap = Math.min(Math.max(start[1], end[1]), y + height) - Math.max(Math.min(start[1], end[1]), y);
    distance = Math.min(Math.abs(start[0] - x), Math.abs(start[0] - x - width));
  } else {
    return false;
  }
  return overlap >= 12.0 && distance < clearance;
}

/** ``f"{value:g}"`` for the clearance values used here. */
function _formatG(value: number): string {
  if (Number.isInteger(value) && Math.abs(value) < 1e16) return numberStr(value);
  // General format with 6 significant digits, trailing zeros stripped.
  const text = value.toPrecision(6);
  if (text.includes('e')) {
    const [mantissa, exponent] = text.split('e');
    const m = mantissa.includes('.') ? mantissa.replace(/\.?0+$/, '') : mantissa;
    const e = Number(exponent);
    return `${m}e${e < 0 ? '-' : '+'}${String(Math.abs(e)).padStart(2, '0')}`;
  }
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text;
}

/** Report node crossings and optionally ambiguous parallel border runs. */
export function check_edge_node_intersections(manifest: Dict, node_clearance = 0.0): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }
  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return findings;
  }

  let id_map: Record<string, string> = {};
  const meta = pyGet(manifest, '_meta');
  if (isDict(meta) && isDict(pyGet(meta, 'id_map'))) {
    id_map = Object.create(null);
    for (const [key, value] of pyItems(pyGet(meta, 'id_map') as Dict)) id_map[pyStr(key)] = pyStr(value);
  }
  const background_ids = detect_group_frame_ids(
    elements.filter((elem) => isDict(elem)) as Dict[],
    true,
    id_map,
  );
  const candidates: [string, BBox][] = [];
  for (const elem of elements) {
    if (!isDict(elem) || truthy(pyGet(elem, 'isDeleted'))) {
      continue;
    }
    const etype = pyGet(elem, 'type');
    if (['arrow', 'text', 'image', 'line', 'freedraw'].includes(etype as string) || _is_decoration(elem)) {
      continue;
    }
    const element_id = pyGet(elem, 'id');
    if (!truthy(element_id) || background_ids.has(element_id as string)) {
      continue;
    }
    const bbox = _bbox(elem);
    if (bbox !== null) {
      candidates.push([pyStr(element_id), bbox]);
    }
  }

  for (const arrow of elements) {
    if (!isDict(arrow) || truthy(pyGet(arrow, 'isDeleted')) || pyGet(arrow, 'type') !== 'arrow') {
      continue;
    }
    if (_is_fully_transparent(arrow)) {
      continue;
    }
    const arrow_id = pyStr(pyGet(arrow, 'id', '<no-id>'));
    const endpoint_ids = _arrow_endpoint_ids(arrow, id_map);
    const segments = _arrow_segments(arrow);
    for (const [node_id, bbox] of candidates) {
      let indexes = segments.map((_, index) => index);
      if (endpoint_ids.source.has(node_id)) {
        indexes = indexes.filter((index) => index !== 0);
      }
      if (endpoint_ids.target.has(node_id)) {
        indexes = indexes.filter((index) => index !== segments.length - 1);
      }
      const hit = indexes.find((index) => _segment_intersects_rect_interior(segments[index][0], segments[index][1], bbox));
      const hit_segment = hit === undefined ? null : hit;
      if (hit_segment === null) {
        if (node_clearance > 0 && !endpoint_ids.source.has(node_id) && !endpoint_ids.target.has(node_id)) {
          const found = segments.findIndex(([start, end]) => _segment_tracks_border(start, end, bbox, node_clearance));
          const border_segment = found < 0 ? null : found;
          if (border_segment !== null) {
            findings.push(new Finding({
              category: 'collision/edge_node_clearance',
              severity: Severity.MAJOR,
              message:
                `arrow ${pyRepr(arrow_id)} runs along unrelated node ${pyRepr(node_id)} `
                + `on segment ${border_segment}; leave at least ${_formatG(node_clearance)}px `
                + 'so the line does not imply an extra connection.',
              element_id: arrow_id,
              location: { node_id, segment_index: border_segment, bbox: _float_list(bbox) },
            }));
          }
        }
        continue;
      }
      findings.push(
        new Finding({
          category: 'collision/edge_node_intersection',
          severity: Severity.MAJOR,
          message:
            `arrow ${pyRepr(arrow_id)} enters node ${pyRepr(node_id)} on segment `
            + `${hit_segment}; only the first source segment and final `
            + 'target segment may touch endpoint nodes.',
          element_id: arrow_id,
          location: { node_id, segment_index: hit_segment, bbox: _float_list(bbox) },
        }),
      );
    }
  }
  return findings;
}

/** Report sustained near-border routes that imply unrelated connections. */
export function check_edge_node_clearance(manifest: Dict): Finding[] {
  return check_edge_node_intersections(manifest, 4.0).filter(
    (finding) => finding.category === 'collision/edge_node_clearance',
  );
}

/** Pairs of shape bboxes that overlap when neither contains the other. */
export function check_node_overlap(manifest: Dict): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }

  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return findings;
  }

  // Identify group/frame background containers & bound text containers —
  // they are allowed to enclose other shapes legitimately.
  const idm = id_map_from_manifest(manifest);
  const background_ids = detect_group_frame_ids(
    elements.filter((elem) => isDict(elem)) as Dict[],
    true,
    idm,
  );

  const candidates: [string, BBox, Dict][] = [];
  for (const elem of elements) {
    if (!isDict(elem)) {
      continue;
    }
    if (truthy(pyGet(elem, 'isDeleted')) || _is_fully_transparent(elem) || _is_decoration(elem)) {
      continue;
    }
    const etype = pyGet(elem, 'type');
    if (['arrow', 'freedraw', 'line', 'image'].includes(etype as string)) {
      continue;
    }
    if (etype === 'text' && truthy(pyGet(elem, 'containerId'))) {
      continue;
    }
    const eid = pyGet(elem, 'id');
    if (!truthy(eid)) {
      continue;
    }
    if (background_ids.has(eid as string)) {
      continue;
    }
    const bbox = _bbox(elem);
    if (bbox === null) {
      continue;
    }
    candidates.push([eid as string, bbox, elem]);
  }

  const n = candidates.length;
  for (let i = 0; i < n; i += 1) {
    const [eid_a, bbox_a, elem_a] = candidates[i];
    for (let j = i + 1; j < n; j += 1) {
      const [eid_b, bbox_b, elem_b] = candidates[j];

      if (!_bboxes_overlap(bbox_a, bbox_b)) {
        continue;
      }
      // A card's registered subtitle is content, not a second node.
      // Keep reporting a subtitle that escapes its card or overlaps others.
      let contained_part = false;
      for (const [part, host, part_box, host_box] of [
        [elem_a, elem_b, bbox_a, bbox_b], [elem_b, elem_a, bbox_b, bbox_a],
      ] as const) {
        const owner = _orEmpty(pyGet(_orEmpty(pyGet(part, 'customData')), 'evoDesignCardPart'));
        const card = _orEmpty(pyGet(_orEmpty(pyGet(host, 'customData')), 'evoDesignCard'));
        if (isDict(owner) && isDict(card)
            && pyEq(pyGet(owner, 'hostId'), pyGet(host, 'id'))
            && pyEq(pyGet(card, 'sublabelId'), pyGet(part, 'id'))) {
          const [px, py, pw, ph] = part_box;
          const [hx, hy, hw, hh] = host_box;
          contained_part = hx <= px && hy <= py && px + pw <= hx + hw && py + ph <= hy + hh;
        }
      }
      if (contained_part) {
        continue;
      }

      findings.push(
        new Finding({
          category: 'collision/node_overlap',
          severity: Severity.MAJOR,
          message:
            `shapes ${pyRepr(eid_a)} and ${pyRepr(eid_b)} overlap. `
            + `a=(${pyFormatFixed(bbox_a[0], 0)},${pyFormatFixed(bbox_a[1], 0)},`
            + `${pyFormatFixed(bbox_a[2], 0)}x${pyFormatFixed(bbox_a[3], 0)}); `
            + `b=(${pyFormatFixed(bbox_b[0], 0)},${pyFormatFixed(bbox_b[1], 0)},`
            + `${pyFormatFixed(bbox_b[2], 0)}x${pyFormatFixed(bbox_b[3], 0)}).`,
          element_id: eid_a,
          location: { a: [...bbox_a], b: [...bbox_b], other_id: eid_b },
        }),
      );
    }
  }

  return findings;
}

/** ``value or {}`` */
function _orEmpty(value: unknown): any {
  return truthy(value) ? value : {};
}

/**
 * Pairwise arrow crossings — segment-aware over the full polyline path.
 *
 * Counts each ARROW PAIR at most once, regardless of how many of its
 * segments intersect. Skips arrow pairs that share an endpoint.
 *
 * - 0 crossings → no finding
 * - 1..N crossings → INFO
 * - >N crossings → MINOR
 */
export function check_edge_crossings(manifest: Dict): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }
  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return findings;
  }

  const arrows: [unknown, Segment[]][] = [];
  for (const elem of elements) {
    if (!isDict(elem) || truthy(pyGet(elem, 'isDeleted')) || pyGet(elem, 'type') !== 'arrow') {
      continue;
    }
    if (_is_fully_transparent(elem)) {
      continue;
    }
    const eid = pyGet(elem, 'id', '');
    const segs = _arrow_segments(elem);
    if (!segs.length) {
      continue;
    }
    arrows.push([eid, segs]);
  }

  const crossing_pairs: [unknown, unknown][] = [];
  const n = arrows.length;
  for (let i = 0; i < n; i += 1) {
    const [id_a, segs_a] = arrows[i];
    const a_first = segs_a[0][0];
    const a_last = segs_a[segs_a.length - 1][1];
    for (let j = i + 1; j < n; j += 1) {
      const [id_b, segs_b] = arrows[j];
      const b_first = segs_b[0][0];
      const b_last = segs_b[segs_b.length - 1][1];

      // Skip arrows that share an endpoint (legit branch / merge fan).
      if (pyEq(a_first, b_first) || pyEq(a_first, b_last) || pyEq(a_last, b_first) || pyEq(a_last, b_last)) {
        continue;
      }

      // Look for any segment-vs-segment intersection across the two
      // polylines. Stop at the first hit — one finding per pair.
      let crossed = false;
      for (const [sa, ea] of segs_a) {
        for (const [sb, eb] of segs_b) {
          if (_segments_intersect(sa, ea, sb, eb)) {
            crossed = true;
            break;
          }
        }
        if (crossed) {
          break;
        }
      }
      if (crossed) {
        crossing_pairs.push([id_a, id_b]);
      }
    }
  }

  const count = crossing_pairs.length;
  if (count <= _EDGE_CROSSING_INFO_THRESHOLD) {
    return findings; // nothing worth reporting
  }

  const severity = count > _EDGE_CROSSING_MINOR_THRESHOLD ? Severity.MINOR : Severity.INFO;
  const sample = crossing_pairs.slice(0, 3).map(([a, b]) => `${pyRepr(a)}×${pyRepr(b)}`).join(', ');
  findings.push(
    new Finding({
      category: 'collision/edge_crossing',
      severity,
      message: `${count} arrow crossing pair(s) detected. Sample: ${sample}.`,
      location: { count, pairs: crossing_pairs.slice(0, 20) },
    }),
  );
  return findings;
}

/** Shapes whose bbox violates the canvas safe area. */
export function check_out_of_canvas(manifest: Dict): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }
  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return findings;
  }

  const arrow_ids = new Set<string>();
  for (const elem of elements) {
    if (isDict(elem) && pyGet(elem, 'type') === 'arrow' && truthy(pyGet(elem, 'id'))) {
      arrow_ids.add(pyStr(pyGet(elem, 'id')));
    }
  }
  for (const elem of elements) {
    if (!isDict(elem)) {
      continue;
    }
    if (truthy(pyGet(elem, 'isDeleted'))) {
      continue;
    }
    if (['arrow', 'freedraw', 'line'].includes(pyGet(elem, 'type') as string)) {
      continue;
    }
    // Excalidraw positions text bound to an arrow from the arrow geometry.
    // Its serialized x/y can remain a placeholder outside the canvas even
    // though the rendered label is correctly located on the connector.
    if (pyGet(elem, 'type') === 'text' && arrow_ids.has(pyStr(pyGet(elem, 'containerId')))) {
      continue;
    }
    const bbox = _bbox(elem);
    if (bbox === null) {
      continue;
    }
    const [x, y, w, h] = bbox;
    if (
      x < CANVAS_MARGIN
      || y < CANVAS_MARGIN
      || x + w > CANVAS_MAX_X - CANVAS_MARGIN
      || y + h > CANVAS_MAX_Y - CANVAS_MARGIN
    ) {
      findings.push(
        new Finding({
          category: 'collision/out_of_canvas',
          severity: Severity.MINOR,
          message:
            `element ${pyRepr(pyGet(elem, 'id', '?'))} bbox=(${pyFormatFixed(x, 0)},`
            + `${pyFormatFixed(y, 0)},${pyFormatFixed(w, 0)}x${pyFormatFixed(h, 0)}) violates canvas safe `
            + `area [${pyStr(_pyFloatValue(CANVAS_MARGIN))},${pyStr(_pyFloatValue(CANVAS_MAX_X - CANVAS_MARGIN))}]`
            + `x[${pyStr(_pyFloatValue(CANVAS_MARGIN))},${pyStr(_pyFloatValue(CANVAS_MAX_Y - CANVAS_MARGIN))}].`,
          element_id: pyGet(elem, 'id') as string | null,
          location: { x, y, w, h },
        }),
      );
    }
  }
  return findings;
}

/** The canvas constants are Python floats (``16.0``): format them as floats. */
function _pyFloatValue(value: number): string {
  return Number.isInteger(value) ? `${value}.0` : pyStr(value);
}

export const __all__ = [
  'check_node_overlap',
  'check_edge_crossings',
  'check_edge_node_intersections',
  'check_out_of_canvas',
];

/**
 * ``list(bbox)`` of the ``_bbox`` floats. The values are Python floats, so the
 * copy is marked in ``PY_FLOAT_MARKS``: ``json.dumps(location)`` in the refiner
 * prompt prints ``190.0`` (see migration/notes/ISSUES.md WP22-1).
 */
function _float_list(bbox: readonly number[]): number[] {
  const out = [...bbox];
  PY_FLOAT_MARKS.set(out, new Set(out.map((_, i) => String(i))));
  return out;
}
