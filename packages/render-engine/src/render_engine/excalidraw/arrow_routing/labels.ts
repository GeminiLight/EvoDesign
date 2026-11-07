// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_routing/labels.py — keep in sync.
//
// Edge labels: filtering, measurement and obstacle-free placement.

import { markF, pyUpdate } from '../../../py/float_marks.ts';

/** Mark x/y/width/height as Python floats (label geometry is built from ``float(...)`` values). */
function _float_geometry<T extends object>(geometry: T): T {
  for (const key of ['x', 'y', 'width', 'height']) markF(geometry, key, true);
  return geometry;
}
import { pyDeepcopy } from '../../../py/float_marks.ts';
import { unwrap_structure_instantiation } from '../../../common/spec_utils.ts';
import { pyGet, pyItems, pySetdefault } from '../../../py/dict.ts';
import { pyIn } from '../../../py/eq.ts';
import { PyTypeError } from '../../../py/errors.ts';
import * as logging from '../../../py/logging.ts';
import { dist, hypot } from '../../../py/math.ts';
import { floorDiv, pyFloatParse, pyInt } from '../../../py/number.ts';
import { pyMax, pyMin, pySorted } from '../../../py/sort.ts';
import { cpLen, pyLower, pySplit, pyStr, pyStrip } from '../../../py/str.ts';
import { isBool, isDict, isStr, pyOr, truthy } from '../../../py/truthy.ts';
import { detect_crossings } from '../../shared/edge_crossing_detector.ts';
import { disjoint_segment_box_distance } from '../../shared/label_geometry.ts';
import { _estimate_text_dimensions } from '../converter.ts';
import {
  type BBox,
  type Box,
  type Point,
  _absolute_arrow_points,
  _arrow_path_fields,
  _path_length,
  _path_parallel_channel_penalty,
  _route_is_legal,
  _segment_hits_box,
  _visible_arrows,
  _waypoints,
} from './geometry.ts';

type Dict = Record<string, unknown>;
type PointLike = readonly number[];

const logger = logging.getLogger('evodesign.agentic_system.render_engine.excalidraw.arrow_routing.labels');
void logger;

export const MAX_EDGE_LABEL_WORDS = 5;
// Reverse-containment guard for the edge-label paraphrase filter.
export const MIN_REVERSE_PARAPHRASE_CHARS = 4;

// Generic direction-verbs and connectors that the arrow itself already
// encodes. Comparison is case-insensitive after stripping.
export const _STOP_LABELS: ReadonlySet<string> = new Set([
  'next', 'then', 'after', 'before', 'follows', 'follow',
  'leads to', 'leads_to', 'lead to',
  'goes to', 'goes_to', 'go to',
  'flows to', 'flows_to', 'flow to',
  'passes to', 'passes_to', 'pass to',
  'sent to', 'sent_to', 'sends to',
  'is part of', 'part of', 'part_of',
  'contains', 'containing', 'includes', 'including',
  'has', 'have', 'is a', 'is_a', 'is an',
  'uses', 'use', 'using', 'calls', 'call',
  'to', 'from', 'and', 'or',
  '→', '->', '=>', '⇒', '>',
]);

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

/** ``max(0.0, x)`` */
function _nonneg(x: number): number {
  return x > 0.0 ? x : 0.0;
}

function _list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : truthy(value) ? [...(value as Iterable<unknown>)] : [];
}

function _at<T>(items: readonly T[], index: number): T {
  return items[index < 0 ? items.length + index : index];
}

/** Normalize edge label payload into text styling fields. */
export function _normalize_label_payload(label_payload: unknown): Dict | null {
  if (isStr(label_payload)) {
    const text = pyStrip(label_payload);
    if (!text) return null;
    return { text, fontSize: 13, fontFamily: 2, strokeColor: '#374151', textAlign: 'center' };
  }

  if (!isDict(label_payload)) return null;

  const text = pyGet(label_payload, 'text');
  if (!isStr(text) || !pyStrip(text)) return null;

  const normalized: Dict = {
    text,
    fontSize: pyGet(label_payload, 'fontSize', 13),
    fontFamily: pyGet(label_payload, 'fontFamily', 2),
    strokeColor: pyGet(label_payload, 'strokeColor', '#374151'),
    textAlign: pyGet(label_payload, 'textAlign', 'center'),
  };

  if (['top', 'middle', 'bottom'].includes(pyGet(label_payload, 'verticalAlign') as string)) {
    normalized.verticalAlign = label_payload.verticalAlign;
  }

  return normalized;
}

/** The relation's own label, else the layout edge's label. */
export function _edge_label_payload(relation: Dict, edge_payload: Dict | null): unknown {
  let label_payload = pyGet(relation, 'label', '');
  if (!truthy(label_payload) && truthy(edge_payload)) label_payload = pyGet(edge_payload!, 'label', '');
  return label_payload;
}

/** Build a {node_id -> node.label} map from structure_instantiation. */
export function _node_label_lookup(structure_instantiation: Dict | null): Record<string, string> {
  const inst = unwrap_structure_instantiation(structure_instantiation);
  const out: Record<string, string> = Object.create(null);
  for (const n of _list(pyOr(pyGet(inst, 'nodes'), []))) {
    if (isDict(n)) {
      const nid = pyGet(n, 'id');
      const label = pyGet(n, 'label');
      if (isStr(nid) && isStr(label)) out[nid] = label;
    }
  }
  return out;
}

/** Restore semantic labels omitted by a layout response. */
export function _merge_semantic_edge_labels(relations: Dict[], structure_instantiation: Dict | null): Dict[] {
  const structure = unwrap_structure_instantiation(structure_instantiation);
  const semantic_by_id = new Map<string, Dict>();
  for (const edge of _list(pyOr(pyGet(structure, 'edges', []), []))) {
    if (isDict(edge) && isStr(pyGet(edge, 'id'))) semantic_by_id.set(pyStr(edge.id), edge);
  }
  const merged: Dict[] = [];
  for (const relation of relations) {
    const enriched: Dict = { ...relation };
    if (!truthy(pyGet(enriched, 'label'))) {
      const semantic = semantic_by_id.get(pyStr(pyGet(enriched, 'id')));
      if (truthy(semantic)) {
        // A semantic predicate is not necessarily visible text.
        let label = pyGet(semantic!, 'label');
        if (!truthy(label) && pyGet(structure, 'chart_type') === 'concept_map') label = pyGet(semantic!, 'relation');
        if (truthy(label)) enriched.label = label;
      }
    }
    merged.push(enriched);
  }
  return merged;
}

/** Return a reason string if the label should be dropped, or ``null`` to keep it. */
export function _should_drop_edge_label(
  label_text: unknown,
  source_ref: unknown,
  target_ref: unknown,
  node_labels: Record<string, string>,
  preserve_structural_labels = false,
): string | null {
  if (!isStr(label_text)) return null;
  const text = pyStrip(label_text);
  if (!text) return null; // already empty, nothing to drop
  if (preserve_structural_labels) return null;

  const low = pyLower(text);

  if (_STOP_LABELS.has(low)) return `stop-verb '${text}'`;

  const word_count = pySplit(text).length;
  if (word_count > MAX_EDGE_LABEL_WORDS) return `too long (${word_count} words)`;

  const refs = [target_ref, source_ref];
  for (let index = 0; index < refs.length; index += 1) {
    const ref = refs[index];
    const ref_label = pyLower(pyStrip(pyOr(pyGet(node_labels, pyStr(ref)), '') as string));
    if (!ref_label) continue;
    // Forward direction: the edge label spells out the node label.
    let matched = low.includes(ref_label);
    // Reverse direction requires a substantial edge label.
    if (!matched && ref_label.includes(low)) {
      matched = cpLen(low) >= MIN_REVERSE_PARAPHRASE_CHARS || pySplit(low).length >= 2;
    }
    if (matched) {
      // ``ref is target_ref``: the first iteration is target_ref itself; the
      // second can only match when source and target labels differ.
      const role = index === 0 || ref === target_ref ? 'target' : 'source';
      return `paraphrases ${role} node '${node_labels[pyStr(ref)]}'`;
    }
  }

  return null;
}

/** Build an absolute path polyline for label placement. */
export function _build_label_path_points(ax: number, ay: number, dx: number, dy: number, arrow_elem: Dict): number[][] {
  const rel_points = pyGet(arrow_elem, 'points');
  if (Array.isArray(rel_points) && rel_points.length >= 2) {
    let abs_points: number[][] = [];
    for (const point of rel_points) {
      const numeric = (value: unknown) => typeof value === 'number' || isBool(value);
      if (!(Array.isArray(point) && point.length === 2 && numeric(point[0]) && numeric(point[1]))) {
        abs_points = [];
        break;
      }
      abs_points.push([_float(ax + Number(point[0])), _float(ay + Number(point[1]))]);
    }
    if (abs_points.length >= 2) return abs_points;
  }

  return [[_float(ax), _float(ay)], [_float(ax + dx), _float(ay + dy)]];
}

export function _segment_orientation(dx: number, dy: number): string {
  if (Math.abs(dy) < 1e-6) return 'horizontal';
  if (Math.abs(dx) < 1e-6) return 'vertical';
  return 'diagonal';
}

type LabelSegment = {
  start_x: number;
  start_y: number;
  end_x: number;
  end_y: number;
  mid_x: number;
  mid_y: number;
  dx: number;
  dy: number;
  length: number;
  orientation: string;
};

/** Choose the most readable path segment for a label. */
export function _choose_label_segment(path_points: readonly PointLike[], routing: string): LabelSegment | null {
  const segments: LabelSegment[] = [];
  for (let i = 0; i + 1 < path_points.length; i += 1) {
    const start = path_points[i];
    const end = path_points[i + 1];
    const dx = _float(end[0] - start[0]);
    const dy = _float(end[1] - start[1]);
    const orientation = _segment_orientation(dx, dy);
    const length = orientation === 'horizontal' ? Math.abs(dx) : orientation === 'vertical' ? Math.abs(dy) : hypot(dx, dy);
    if (length < 1) continue;
    segments.push({
      start_x: _float(start[0]),
      start_y: _float(start[1]),
      end_x: _float(end[0]),
      end_y: _float(end[1]),
      mid_x: _float((start[0] + end[0]) / 2),
      mid_y: _float((start[1] + end[1]) / 2),
      dx,
      dy,
      length: _float(length),
      orientation,
    });
  }

  if (!segments.length) return null;

  const longest = (orientation_filter: (o: string) => boolean): LabelSegment | null => {
    const matching = segments.filter((segment) => orientation_filter(segment.orientation));
    return matching.length ? pyMax(matching, (segment) => segment.length) : null;
  };

  let preferred: LabelSegment | null = null;
  if (routing === 'elbowed') preferred = longest((o) => o === 'horizontal') ?? longest((o) => o === 'vertical');
  else if (routing === 'curved') preferred = longest((o) => o !== 'diagonal');
  return preferred ?? longest(() => true);
}

export function _arrow_routing(arrow_elem: Dict): string {
  if (truthy(pyGet(arrow_elem, 'elbowed'))) return 'elbowed';
  if (isDict(pyGet(arrow_elem, 'roundness'))) return 'curved';
  return 'straight';
}

/** Compute text box geometry from the arrow path instead of the raw endpoint midpoint. */
export function _compute_label_geometry(
  ax: number,
  ay: number,
  dx: number,
  dy: number,
  arrow_elem: Dict,
  normalized_label: Dict,
): { x: number; y: number; width: number; height: number } {
  const dims = _estimate_text_dimensions(normalized_label.text as string, pyInt(normalized_label.fontSize as number));
  const width = _float(dims.width);
  const height = _float(dims.height);

  const path_points = _build_label_path_points(ax, ay, dx, dy, arrow_elem);
  let segment = _choose_label_segment(path_points, _arrow_routing(arrow_elem));
  if (segment && segment.orientation === 'horizontal' && segment.length < width + 16.0) {
    const vertical_segments: LabelSegment[] = [];
    for (let i = 0; i + 1 < path_points.length; i += 1) {
      const start = path_points[i];
      const end = path_points[i + 1];
      if (Math.abs(start[0] - end[0]) < 1.0 && Math.abs(start[1] - end[1]) >= height + 16.0) {
        vertical_segments.push(_choose_label_segment([start, end], 'straight')!);
      }
    }
    if (vertical_segments.length) segment = pyMax(vertical_segments, (item) => item.length);
  }

  if (segment === null) {
    const mid_x = _float(ax + dx / 2);
    const mid_y = _float(ay + dy / 2);
    return _float_geometry({ x: _nonneg(mid_x - width / 2), y: _nonneg(mid_y - height / 2), width, height });
  }

  let x: number;
  let y: number;
  if (segment.orientation === 'horizontal') {
    x = segment.mid_x - width / 2;
    y = segment.mid_y - height - 8;
  } else if (segment.orientation === 'vertical') {
    x = segment.mid_x + 8;
    y = segment.mid_y - height / 2;
  } else {
    const segment_length = segment.length > 1.0 ? segment.length : 1.0;
    const normal_x = -segment.dy / segment_length;
    const normal_y = segment.dx / segment_length;
    const offset = 14.0;
    x = segment.mid_x + normal_x * offset - width / 2;
    y = segment.mid_y + normal_y * offset - height / 2;
  }

  return _float_geometry({ x: _nonneg(x), y: _nonneg(y), width, height });
}

/** Re-place the text bound to ``arrow`` on its current path. */
export function _refresh_bound_labels(arrow: Dict, elements_by_id: Record<string, Dict> | Map<unknown, Dict>): null {
  for (const binding of _list(pyOr(pyGet(arrow, 'boundElements', []), [])) as Dict[]) {
    if (pyGet(binding, 'type') !== 'text') continue;
    const label = pyGet(elements_by_id, pyStr(pyGet(binding, 'id'))) as Dict | null;
    if (label === null) continue;
    const endpoints = _absolute_arrow_points([arrow]);
    pyUpdate(label, _compute_label_geometry(
      endpoints[0][0],
      endpoints[0][1],
      _at(endpoints, -1)[0] - endpoints[0][0],
      _at(endpoints, -1)[1] - endpoints[0][1],
      arrow,
      label,
    ));
  }
  return null;
}

function _same_point(a: PointLike, b: PointLike): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

/** Move edge labels to the nearest node- and foreign-edge-free position. */
export function _reposition_edge_labels(elements: Dict[], generated_elements: Dict[]): null {
  const arrows = new Map<string, Dict>();
  for (const element of _visible_arrows(generated_elements)) {
    if (truthy(pyGet(element, 'id'))) arrows.set(pyStr(element.id), element);
  }
  const node_boxes: Box[] = [];
  for (const element of elements) {
    if (
      !['arrow', 'text', 'image'].includes(pyGet(element, 'type') as string)
      && !truthy(pyGet(element, 'isDeleted'))
      && !truthy(pyGet(element, 'is_group'))
    ) {
      node_boxes.push([
        _float(pyOr(pyGet(element, 'x', 0.0), 0.0)),
        _float(pyOr(pyGet(element, 'y', 0.0), 0.0)),
        _float(pyOr(pyGet(element, 'width', 0.0), 0.0)),
        _float(pyOr(pyGet(element, 'height', 0.0), 0.0)),
      ]);
    }
  }
  for (const element of elements) {
    if (!truthy(pyGet(element, 'is_group')) || truthy(pyGet(element, 'isDeleted'))) continue;
    if (_float(pyGet(element, 'opacity', 100)) <= 0 || ['transparent', 'none'].includes(pyGet(element, 'strokeColor') as string)) continue;
    const left = _float(pyOr(pyGet(element, 'x', 0.0), 0.0));
    const top = _float(pyOr(pyGet(element, 'y', 0.0), 0.0));
    const width = _float(pyOr(pyGet(element, 'width', 0.0), 0.0));
    const height = _float(pyOr(pyGet(element, 'height', 0.0), 0.0));
    // Labels may live inside a section, but must not straddle its outline.
    node_boxes.push(
      [left, top, width, 0.0], [left, top + height, width, 0.0],
      [left, top, 0.0, height], [left + width, top, 0.0, height],
    );
  }
  const placed: Box[] = [];
  const arrow_segments = new Map<string, [Point, Point][]>();
  for (const [arrow_id, arrow] of arrows) {
    const points = _absolute_arrow_points([arrow]);
    if (points.length >= 2) {
      const segments: [Point, Point][] = [];
      for (let index = 0; index < points.length - 1; index += 1) {
        if (!_same_point(points[index], points[index + 1])) segments.push([points[index], points[index + 1]]);
      }
      arrow_segments.set(arrow_id, segments);
    }
  }
  const all_segments: [Point, Point][] = [];
  for (const segments of arrow_segments.values()) all_segments.push(...segments);

  const overlaps = (box: Box, obstacle: Box): boolean => {
    const [x, y, width, height] = box;
    const [ox, oy, obstacle_width, obstacle_height] = obstacle;
    const padding = 4.0;
    return x < ox + obstacle_width + padding
      && x + width > ox - padding
      && y < oy + obstacle_height + padding
      && y + height > oy - padding;
  };

  const placement_candidates = (geometry: { x: number; y: number; width: number; height: number }, own_segments: [Point, Point][]): Box[] => {
    const base_x = geometry.x;
    const base_y = geometry.y;
    const width = geometry.width;
    const height = geometry.height;
    const candidates: [number, number][] = [[base_x, base_y]];
    for (const [start, end] of pySorted(own_segments, (segment) => -dist(segment[0], segment[1]))) {
      if (Math.abs(start[1] - end[1]) < 1e-6) {
        const available = Math.abs(end[0] - start[0]) - width - 16.0;
        if (available < 0) continue;
        for (const fraction of [0.5, 0.0, 1.0, 0.25, 0.75]) {
          const x = (end[0] < start[0] ? end[0] : start[0]) + 8.0 + fraction * available;
          candidates.push([x, start[1] - height - 8.0], [x, start[1] + 8.0]);
        }
      } else if (Math.abs(start[0] - end[0]) < 1e-6) {
        const available = Math.abs(end[1] - start[1]) - height - 16.0;
        if (available < 0) continue;
        for (const fraction of [0.5, 0.0, 1.0, 0.25, 0.75]) {
          const y = (end[1] < start[1] ? end[1] : start[1]) + 8.0 + fraction * available;
          candidates.push([start[0] + 8.0, y], [start[0] - width - 8.0, y]);
        }
      }
    }
    // A short elbow can still have room for its label beside the bend.
    for (const offset of [8.0, 16.0, 24.0, 32.0, 48.0]) {
      for (const [dx, dy] of [[0.0, -offset], [0.0, offset], [-offset, 0.0], [offset, 0.0]]) {
        candidates.push([base_x + dx, base_y + dy]);
      }
    }
    return candidates.map(([x, y]) => [_nonneg(x), _nonneg(y), width, height] as Box);
  };

  const clear = (candidate: Box): boolean => {
    for (const obstacle of [...node_boxes, ...placed]) if (overlaps(candidate, obstacle)) return false;
    const padded: Box = [candidate[0] - 3.0, candidate[1] - 3.0, candidate[2] + 6.0, candidate[3] + 6.0];
    return !all_segments.some(([start, end]) => _segment_hits_box(start, end, padded));
  };

  for (const label of generated_elements) {
    if (pyGet(label, 'type') !== 'text' || !arrows.has(pyStr(pyGet(label, 'containerId', '')))) continue;
    const own_arrow = arrows.get(pyStr(label.containerId))!;
    const own_segments = arrow_segments.get(pyStr(label.containerId)) ?? [];
    const original_text = pyGet(label, 'text', '') as string;
    const font_size = _float(pyGet(label, 'fontSize', 13));
    const variants = [original_text];
    const words = pySplit(original_text);
    // Preserve every word. Balanced two-line breaks come first.
    const indices: number[] = [];
    for (let index = 1; index < words.length; index += 1) indices.push(index);
    const breaks = pySorted(indices, (index) =>
      Math.abs(cpLen(words.slice(0, index).join(' ')) - cpLen(words.slice(index).join(' ')))).slice(0, 6);
    for (const index of breaks) variants.push(`${words.slice(0, index).join(' ')}\n${words.slice(index).join(' ')}`);
    let chosen: [string, Box] | null = null;
    let nearest_clear: [[number, number], string, Box] | null = null;
    let fallback: [string, Box] | null = null;
    for (let variant_index = 0; variant_index < variants.length; variant_index += 1) {
      const text = variants[variant_index];
      let geometry = {
        x: _float(pyOr(pyGet(label, 'x', 0.0), 0.0)),
        y: _float(pyOr(pyGet(label, 'y', 0.0), 0.0)),
        width: _float(pyOr(pyGet(label, 'width', 0.0), 0.0)),
        height: _float(pyOr(pyGet(label, 'height', 0.0), 0.0)),
      };
      if (truthy(text)) {
        geometry = _compute_label_geometry(
          _float(pyGet(own_arrow, 'x', 0.0)),
          _float(pyGet(own_arrow, 'y', 0.0)),
          _float(pyGet(own_arrow, 'width', 0.0)),
          _float(pyGet(own_arrow, 'height', 0.0)),
          own_arrow,
          { text, fontSize: font_size },
        );
      }
      if (fallback === null) fallback = [text, [geometry.x, geometry.y, geometry.width, geometry.height]];
      for (const candidate of placement_candidates(geometry, own_segments)) {
        if (!clear(candidate)) continue;
        const distance = pyMin(own_segments.map(([start, end]) => disjoint_segment_box_distance(start, end, candidate)), null, 0.0) as number;
        if (distance <= (1.5 * font_size > 24.0 ? 1.5 * font_size : 24.0)) {
          chosen = [text, candidate];
          break;
        }
        const score: [number, number] = [distance, variant_index];
        if (
          nearest_clear === null
          || score[0] < nearest_clear[0][0]
          || (score[0] === nearest_clear[0][0] && score[1] < nearest_clear[0][1])
        ) {
          nearest_clear = [score, text, candidate];
        }
      }
      if (chosen !== null) break;
    }
    if (chosen === null) chosen = nearest_clear ? [nearest_clear[1], nearest_clear[2]] : fallback;
    const [text, box] = chosen!;
    Object.assign(label, { x: box[0], y: box[1], width: box[2], height: box[3] });
    _float_geometry(label); // candidate boxes are built from float() geometry
    if (text !== original_text) {
      label.text = text;
      label.originalText = text;
    }
    placed.push(box);
  }
  return null;
}

type RouteContext = Dict & { obstacles: Box[]; source_bbox: BBox; target_bbox: BBox };

/** Clear native bound-label midpoints by moving dogleg channels, not text. */
export function _position_architecture_bound_labels(
  elements: Dict[],
  generated_elements: Dict[],
  route_contexts: Record<string, Dict> | Map<unknown, Dict>,
  group_frame_ids: Set<string> | null = null,
): null {
  const arrows = new Map<string, Dict>();
  for (const item of _visible_arrows(generated_elements)) arrows.set(pyStr(item.id), item);
  const labels = new Map<string, Dict>();
  for (const item of generated_elements) {
    if (pyGet(item, 'type') === 'text' && arrows.has(pyStr(pyGet(item, 'containerId')))) {
      labels.set(pyStr(pyGet(item, 'containerId')), item);
    }
  }
  if (!labels.size) return null;
  const obstacles: Box[] = [];
  for (const item of elements) {
    if (truthy(pyGet(item, 'isDeleted')) || ['text', 'image', 'arrow'].includes(pyGet(item, 'type') as string)) continue;
    const [x, y, w, h] = ['x', 'y', 'width', 'height'].map((key) => _float(pyOr(pyGet(item, key, 0), 0)));
    if (truthy(pyGet(item, 'is_group')) || pyIn(pyGet(item, 'id'), pyOr(group_frame_ids, new Set()))) {
      if ((pyGet(item, 'opacity', 100) as number) > 0 && !['transparent', 'none'].includes(pyGet(item, 'strokeColor') as string)) {
        obstacles.push([x, y, w, 0], [x, y + h, w, 0], [x, y, 0, h], [x + w, y, 0, h]);
      }
    } else {
      obstacles.push([x, y, w, h]);
    }
  }

  const native_box = (points: readonly PointLike[], label: Dict): Box => {
    const middle = floorDiv(points.length, 2);
    let [cx, cy] = points[middle];
    if (points.length % 2 === 0) {
      cx = (points[middle - 1][0] + points[middle][0]) / 2;
      cy = (points[middle - 1][1] + points[middle][1]) / 2;
    }
    const w = _float(label.width);
    const h = _float(label.height);
    return [cx - w / 2, cy - h / 2, w, h];
  };

  const overlap = (a: Box, b: Box): boolean =>
    a[0] < b[0] + b[2] + 6 && a[0] + a[2] > b[0] - 6 && a[1] < b[1] + b[3] + 6 && a[1] + a[3] > b[1] - 6;

  const penalty = (paths: Map<string, PointLike[]>): number => {
    const boxes = new Map<string, Box>();
    for (const [key, label] of labels) {
      if (paths.get(key)!.length >= 2) boxes.set(key, native_box(paths.get(key)!, label));
    }
    let count = 0;
    for (const [key, box] of boxes) {
      for (const obstacle of obstacles) if (overlap(box, obstacle)) count += 1;
      for (const [other_key, other] of boxes) if (other_key !== key && overlap(box, other)) count += 1;
      const padded: Box = [box[0] - 6, box[1] - 6, box[2] + 12, box[3] + 12];
      for (const [other_key, points] of paths) {
        if (other_key === key) continue;
        for (let i = 0; i + 1 < points.length; i += 1) if (_segment_hits_box(points[i], points[i + 1], padded)) count += 1;
      }
    }
    return count;
  };

  const creates_crossing = (candidate: readonly PointLike[], original: readonly PointLike[], others: Dict[]): boolean => {
    // Reject new intersection locations, not a relabeling of a shared corner.
    for (const other of others) {
      const foreign = _absolute_arrow_points([other]);
      for (let i = 0; i + 1 < candidate.length; i += 1) {
        const a = candidate[i];
        const b = candidate[i + 1];
        const rx = b[0] - a[0];
        const ry = b[1] - a[1];
        for (let j = 0; j + 1 < foreign.length; j += 1) {
          const c = foreign[j];
          const d = foreign[j + 1];
          const sx = d[0] - c[0];
          const sy = d[1] - c[1];
          const denominator = rx * sy - ry * sx;
          if (Math.abs(denominator) < 1e-9) continue;
          const qx = c[0] - a[0];
          const qy = c[1] - a[1];
          const t = (qx * sy - qy * sx) / denominator;
          const u = (qx * ry - qy * rx) / denominator;
          if (!(t >= 0 && t <= 1 && u >= 0 && u <= 1)) continue;
          const point = [a[0] + t * rx, a[1] + t * ry, 0, 0];
          let all_far = true;
          for (let k = 0; k + 1 < original.length; k += 1) {
            if (!(disjoint_segment_box_distance(original[k], original[k + 1], point) > 1e-6)) {
              all_far = false;
              break;
            }
          }
          if (all_far) return true;
        }
      }
    }
    return false;
  };

  const context_of = (key: string): RouteContext | null => pyGet(route_contexts, key) as RouteContext | null;
  const legal = (points: readonly PointLike[], context: RouteContext): boolean =>
    _route_is_legal(points, context.obstacles, context.source_bbox, context.target_bbox);

  const paths = new Map<string, PointLike[]>();
  for (const [key, arrow] of arrows) paths.set(key, _absolute_arrow_points([arrow]));
  const originals = new Map<string, Dict>();
  for (const [key, arrow] of arrows) originals.set(key, pyDeepcopy(arrow));
  const original_score = penalty(paths);

  const set_path = (key: string, points: PointLike[]): void => {
    const fields = _arrow_path_fields(_waypoints(points), 1);
    // ``min_size=1`` is an int here: max(1, w) keeps the int unless w > 1.
    markF(fields, 'width', fields.width > 1);
    markF(fields, 'height', fields.height > 1);
    pyUpdate(arrows.get(key)!, fields);
    if (points.length > 2) arrows.get(key)!.elbowed = true;
    paths.set(key, points);
  };

  // Earlier route optimization can collapse an incoming and outgoing port
  // back onto the same face center. Reserve room for their actual labels.
  const faces = new Map<string, [[unknown, string], [string, string][]]>();
  for (const [raw_key, context] of pyItems(route_contexts)) {
    const key = raw_key as string;
    if (!paths.has(key) || paths.get(key)!.length < 2) continue;
    for (const [role, ref_key, side_key] of [['source', 'source_ref', 'start_side'], ['target', 'target_ref', 'end_side']]) {
      if (pyIn(ref_key, context)) {
        const face: [unknown, string] = [context[ref_key], context[side_key] as string];
        const face_key = JSON.stringify(face);
        if (!faces.has(face_key)) faces.set(face_key, [face, []]);
        faces.get(face_key)![1].push([key, role]);
      }
    }
  }
  for (const [[, side], endpoints] of faces.values()) {
    const roles = new Set(endpoints.map(([, role]) => role));
    if (!(roles.size === 2 && roles.has('source') && roles.has('target'))) continue;
    const axis = side === 'top' || side === 'bottom' ? 0 : 1;
    const positions = endpoints
      .map(([key, role]) => _at(paths.get(key)!, role === 'source' ? 0 : -1)[axis])
      .sort((a, b) => a - b);
    const gaps: number[] = [];
    for (let i = 0; i + 1 < positions.length; i += 1) gaps.push(positions[i + 1] - positions[i]);
    if ((pyMin(gaps) as number) >= 8) continue;
    const [first_key, first_role] = endpoints[0];
    const box = context_of(first_key)![`${first_role}_bbox`] as BBox;
    const span = axis === 0 ? box.w : box.h;
    const center = (axis === 0 ? box.x : box.y) + span / 2;
    let spacing = pyMax([32.0, ...endpoints
      .filter(([key]) => labels.has(key))
      .map(([key]) => _float(labels.get(key)![axis === 0 ? 'width' : 'height']) + 20)]) as number;
    const limit = (span - 24 > 0 ? span - 24 : 0) / (endpoints.length - 1);
    spacing = limit < spacing ? limit : spacing;
    const ordered = pySorted(endpoints, (item) => [_at(paths.get(item[0])!, item[1] === 'source' ? -1 : 0)[axis], item[0]]);
    const trial = new Map<string, PointLike[]>();
    for (const [key, points] of paths) trial.set(key, points.map((point) => [...point]));
    let valid = true;
    for (let rank = 0; rank < ordered.length; rank += 1) {
      const [key, role] = ordered[rank];
      let points = trial.get(key)!.map((point) => [...point]);
      if (points.length === 2) {
        // A near-vertical single segment can share the exact same face as
        // an outgoing dogleg. Give it a middle channel first.
        const midpoint = (points[0][1 - axis] + _at(points, -1)[1 - axis]) / 2;
        const first = [...points[0]];
        const last = [..._at(points, -1)];
        first[1 - axis] = midpoint;
        last[1 - axis] = midpoint;
        points = [points[0], first, last, _at(points, -1)];
      }
      const [i, j] = role === 'source' ? [0, 1] : [points.length - 1, points.length - 2];
      const boundary = (axis === 0 ? box.y : box.x) + (side === 'bottom' ? box.h : side === 'right' ? box.w : 0);
      if (Math.abs(points[i][1 - axis] - boundary) > 1e-6 || Math.abs(points[i][axis] - points[j][axis]) > 1e-6) {
        valid = false;
        break;
      }
      const coordinate = center + (rank - (ordered.length - 1) / 2) * spacing;
      points[i][axis] = coordinate;
      points[j][axis] = coordinate;
      trial.set(key, points.map((point) => [...point]));
      if (!legal(trial.get(key)!, context_of(key)!)) {
        valid = false;
        break;
      }
    }
    if (valid) {
      for (const [key] of endpoints) set_path(key, trial.get(key)!);
    }
  }

  let score = penalty(paths);
  for (let round = 0; round < 2; round += 1) {
    let changed = false;
    for (const key of labels.keys()) {
      const arrow = arrows.get(key)!;
      const points = paths.get(key)!;
      const context = context_of(key);
      if (!truthy(context) || points.length !== 4 || !truthy(pyGet(arrow, 'elbowed'))) continue;
      const vertical = Math.abs(points[1][0] - points[2][0]) < 1e-6;
      const horizontal = Math.abs(points[1][1] - points[2][1]) < 1e-6;
      if (vertical === horizontal) continue;
      const axis = vertical ? 0 : 1;
      const others = [...arrows].filter(([other_key]) => other_key !== key).map(([, item]) => item);
      const channel_penalty = _path_parallel_channel_penalty(points, others);
      let best: [[number, number], PointLike[]] | null = null;
      for (const offset of [-16, 16, -32, 32, -48, 48, -64, 64]) {
        const moved = points.map((point) => [...point]);
        moved[1][axis] += offset;
        moved[2][axis] += offset;
        const candidate: PointLike[] = moved;
        if (
          (pyMin(candidate.map((point) => pyMin(point) as number)) as number) < 0
          || _path_length(candidate) > _path_length(points) + 64
          || !legal(candidate, context!)
          || _path_parallel_channel_penalty(candidate, others) > channel_penalty + 1e-6
          || creates_crossing(candidate, points, others)
        ) {
          continue;
        }
        const next_paths = new Map(paths);
        next_paths.set(key, candidate);
        const next_score = penalty(next_paths);
        const rank: [number, number] = [next_score, Math.abs(offset)];
        if (next_score < score && (best === null || rank[0] < best[0][0] || (rank[0] === best[0][0] && rank[1] < best[0][1]))) {
          best = [rank, candidate];
        }
      }
      if (best === null) continue;
      score = best[0][0];
      paths.set(key, best[1]);
      set_path(key, paths.get(key)!);
      changed = true;
    }
    if (!changed || score === 0) break;
  }
  if (score >= original_score || detect_crossings([...arrows.values()]).length > detect_crossings([...originals.values()]).length) {
    for (const [key, original] of originals) {
      pyUpdate(arrows.get(key)!, original);
      paths.set(key, _absolute_arrow_points([original]));
    }
  }
  for (const [key, label] of labels) {
    if (paths.get(key)!.length >= 2) {
      const [x, y, width, height] = native_box(paths.get(key)!, label);
      Object.assign(label, { x, y, width, height });
      _float_geometry(label); // native_box: float path points, float(label[...])
    }
  }
  return null;
}

/** Export concept predicates as grouped free text at their computed spots. */
export function _detach_concept_labels(generated_elements: Dict[]): null {
  const arrows_by_id = new Map<unknown, Dict>();
  for (const element of generated_elements) {
    if (pyGet(element, 'type') === 'arrow') arrows_by_id.set(element.id, element);
  }
  const arrows_by_semantic_id = new Map<unknown, unknown>();
  for (const [arrow_id, arrow] of arrows_by_id) {
    arrows_by_semantic_id.set(pyGet(pyOr(pyGet(arrow, 'meta'), {}), 'semantic_edge_id'), arrow_id);
  }
  for (const label of generated_elements) {
    const semantic = arrows_by_semantic_id.get(pyGet(pyOr(pyGet(label, 'meta'), {}), 'semantic_edge_id'));
    const arrow_id = pyOr(pyGet(label, 'containerId'), semantic === undefined ? null : semantic);
    if (pyGet(label, 'type') !== 'text' || !arrows_by_id.has(arrow_id)) continue;
    const arrow = arrows_by_id.get(arrow_id)!;
    const group_id = `relation:${pyStr(arrow_id)}`;
    label.containerId = null;
    (pySetdefault<unknown>(label, 'meta', {}) as Dict).semantic_arrow_id = arrow_id;
    label.groupIds = [group_id];
    arrow.groupIds = [group_id];
    arrow.boundElements = (pyGet(arrow, 'boundElements', []) as Dict[]).filter((binding) => pyGet(binding, 'id') !== label.id);
  }
  return null;
}
