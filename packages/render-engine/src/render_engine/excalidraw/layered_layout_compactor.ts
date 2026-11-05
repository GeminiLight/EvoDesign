// Ported from evodesign/agentic_system/render_engine/excalidraw/layered_layout_compactor.py — keep in sync.
//
// Compact architecture layer geometry before connector routing.

import { markF, pyDeepcopy } from '../../py/float_marks.ts';
import { _estimate_text_dimensions } from '../../generation_stage/layout/element_shape_estimator.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import {
  BACKGROUND_SUFFIX,
  ICON_SUFFIX,
  TITLE_SUFFIX,
  group_frame_render_id,
  id_map_from_manifest,
} from '../../common/semantic_ids.ts';
import { pyGet, pyItems, pyValues, type PyMapping } from '../../py/dict.ts';
import { pyEq, pyIn } from '../../py/eq.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { ceil } from '../../py/math.ts';
import { pyFloatParse, pySum } from '../../py/number.ts';
import { pyMax, pyMaxN, pyMin, pyMinN, pySort, pySorted } from '../../py/sort.ts';
import { pyEndswith, pyLower, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isMapping, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;
type ElementsById = PyMapping<Dict>;

export const _ARCHITECTURE_TYPES: ReadonlySet<string> = new Set(['architecture', 'architecture_diagram']);
export const _FRAME_TOP_PADDING = 74.0;
export const _FRAME_BOTTOM_PADDING = 40.0;
export const _ROW_GAP = 68.0;
export const _LAYER_GAP = 48.0;
export const _SIDE_GAP = 56.0;
export const _SIDE_WIDTH = 360.0;
export const _MIN_CONTENT_WIDTH = 980.0;
// Keep the main stack compact while retaining a clear frame margin around the
// widest row.  The minimum content width still prevents narrow diagrams from
// collapsing.
export const _CONTENT_SIDE_PADDING = 60.0;
export const _ROW_TOLERANCE = 100.0;
export const _MIN_ROW_CENTER_GAP = 128.0;
export const _NODE_FONT_SIZE = 18;
export const _NODE_MIN_WIDTH = 180.0;
export const _NODE_MAX_WIDTH = 300.0;
export const _NODE_MIN_HEIGHT = 60.0;
export const _NODE_MAX_HEIGHT = 84.0;
export const _NODE_HORIZONTAL_PADDING = 44.0;
export const _NODE_VERTICAL_PADDING = 26.0;
export const _NODE_SHAPE_INFLATE: Readonly<Record<string, number>> = {
  rectangle: 1.0,
  ellipse: 1.14,
  diamond: 1.28,
};

function _isInflateShape(value: unknown): value is string {
  return isStr(value) && Object.prototype.hasOwnProperty.call(_NODE_SHAPE_INFLATE, value);
}

/** ``mapping.get(key)`` that maps a missing / ``None`` value to ``null``. */
function _lookup(elements_by_id: ElementsById, key: unknown): Dict | null {
  const value = pyGet(elements_by_id, key) as Dict | null | undefined;
  return value === undefined ? null : value;
}

export function _number(value: unknown, default_ = 0.0): number {
  try {
    if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
    throw new PyTypeError('float() argument must be a string or a real number');
  } catch (error) {
    if (error instanceof PyTypeError || error instanceof ValueError) return default_;
    throw error;
  }
}

export function _element_size(element: Dict): [number, number] {
  return [_number(pyGet(element, 'width')), _number(pyGet(element, 'height'))];
}

export function _bound_text_for_shape(elements_by_id: ElementsById, shape: Dict): Dict | null {
  const shape_id = pyStr(pyGet(shape, 'id', ''));
  const bindings = pyOr(pyGet(shape, 'boundElements', []), []) as unknown[];
  for (const binding of bindings) {
    if (!isMapping(binding) || pyGet(binding, 'type') !== 'text') {
      continue;
    }
    const text = _lookup(elements_by_id, pyStr(pyGet(binding, 'id', '')));
    if (text !== null) {
      return text;
    }
  }
  for (const element of pyValues(elements_by_id)) {
    if (pyGet(element, 'type') === 'text' && pyStr(pyGet(element, 'containerId', '')) === shape_id) {
      return element;
    }
  }
  return null;
}

/** Fit architecture components to their labels within a compact size band. */
export function _normalize_member_size(elements_by_id: ElementsById, id_map: PyMapping, semantic_id: string): null {
  const shape = _shape_for_semantic(elements_by_id, id_map, semantic_id);
  if (shape === null || !_isInflateShape(pyGet(shape, 'type'))) {
    return null;
  }
  const text = _bound_text_for_shape(elements_by_id, shape);
  if (text === null) {
    return null;
  }

  const label = pyStr(pyOr(pyOr(pyGet(text, 'originalText'), pyGet(text, 'text')), ''));
  text.fontSize = _NODE_FONT_SIZE;
  text.lineHeight = 1.2;
  markF(text, 'fontSize', false);
  const text_bbox = _estimate_text_dimensions(label, _NODE_FONT_SIZE);
  const inflate = _NODE_SHAPE_INFLATE[pyStr(pyGet(shape, 'type'))];

  const icon = _lookup(elements_by_id, pyGet(id_map, `${semantic_id}${ICON_SUFFIX}`, ''));
  let icon_extra = 0.0;
  if (icon !== null) {
    icon_extra = _number(pyGet(icon, 'width')) + 24.0;
  }

  const target_width = pyMinN(
    _NODE_MAX_WIDTH,
    pyMaxN(
      _NODE_MIN_WIDTH,
      ceil(text_bbox.width * inflate + _NODE_HORIZONTAL_PADDING + icon_extra),
    ),
  );
  const target_height = pyMinN(
    _NODE_MAX_HEIGHT,
    pyMaxN(
      _NODE_MIN_HEIGHT,
      ceil(text_bbox.height * inflate + _NODE_VERTICAL_PADDING),
    ),
  );
  shape.width = target_width;
  shape.height = target_height;
  // min(MAX.0, max(MIN.0, math.ceil(...))): the int ceil survives only strictly between the float bounds.
  const band_f = (c: number, lo: number, hi: number): boolean => !(c > lo && c < hi);
  const target_width_f = band_f(ceil(text_bbox.width * inflate + _NODE_HORIZONTAL_PADDING + icon_extra), _NODE_MIN_WIDTH, _NODE_MAX_WIDTH);
  const target_height_f = band_f(ceil(text_bbox.height * inflate + _NODE_VERTICAL_PADDING), _NODE_MIN_HEIGHT, _NODE_MAX_HEIGHT);
  markF(shape, 'width', target_width_f);
  markF(shape, 'height', target_height_f);

  const text_width = pyMinN(ceil(text_bbox.width), target_width - 32.0);
  const text_height = pyMinN(ceil(text_bbox.height), target_height - 20.0);
  let content_left = _number(pyGet(shape, 'x'));
  if (icon !== null) {
    icon.x = content_left + 16.0;
    icon.y = (
      _number(pyGet(shape, 'y'))
      + (target_height - _number(pyGet(icon, 'height'))) / 2.0
    );
    content_left = (icon.x as number) + _number(pyGet(icon, 'width')) + 12.0;
  }
  const content_right = _number(pyGet(shape, 'x')) + target_width - 16.0;
  const text_center_x = content_left + (content_right - content_left) / 2.0;
  text.x = text_center_x - text_width / 2.0;
  text.y = _number(pyGet(shape, 'y')) + (target_height - text_height) / 2.0;
  text.width = text_width;
  text.height = text_height;
  if (icon !== null) {
    markF(icon, 'x', true);
    markF(icon, 'y', true);
  }
  markF(text, 'x', true);
  markF(text, 'y', true);
  // min(math.ceil(...), target - 32.0): the float wins only when strictly smaller.
  markF(text, 'width', target_width - 32.0 < ceil(text_bbox.width));
  markF(text, 'height', target_height - 20.0 < ceil(text_bbox.height));
  return null;
}

export function _cluster_rows(elements: Dict[]): Dict[][] {
  const rows: Dict[][] = [];
  for (const element of pySorted(elements, (item) => [_number(pyGet(item, 'y')), _number(pyGet(item, 'x'))])) {
    const y = _number(pyGet(element, 'y'));
    const row = rows.find((candidate) => Math.abs(y - _number(pyGet(candidate[0], 'y'))) <= _ROW_TOLERANCE);
    if (row === undefined) {
      rows.push([element]);
    } else {
      row.push(element);
    }
  }
  return rows.map((row) => pySorted(row, (item) => _number(pyGet(item, 'x'))));
}

function _rowCenter(row: Dict[]): number {
  return pySum(row.map((item) => _number(pyGet(item, 'y')) + _number(pyGet(item, 'height')) / 2.0)) / row.length;
}

/** Merge model rows that are too close to leave a usable edge corridor. */
export function _merge_crowded_rows(rows: Dict[][]): Dict[][] {
  const merged: Dict[][] = [];
  for (const row of rows) {
    const current = pySorted(row, (item) => _number(pyGet(item, 'x')));
    if (!merged.length) {
      merged.push(current);
      continue;
    }
    const previous_center = _rowCenter(merged[merged.length - 1]);
    const current_center = _rowCenter(current);
    if (current_center - previous_center < _MIN_ROW_CENTER_GAP) {
      merged[merged.length - 1] = pySorted(
        [...merged[merged.length - 1], ...current],
        (item) => _number(pyGet(item, 'x')),
      );
    } else {
      merged.push(current);
    }
  }
  return merged;
}

export function _shape_for_semantic(elements_by_id: ElementsById, id_map: PyMapping, semantic_id: string): Dict | null {
  const render_id = pyGet(id_map, semantic_id);
  const element = _lookup(elements_by_id, pyOr(render_id, ''));
  if (!truthy(element)) {
    return null;
  }
  const etype = pyGet(element, 'type');
  if (etype === 'text' || etype === 'image' || etype === 'arrow') {
    return null;
  }
  return element;
}

export function _members_for_group(group: Dict, elements_by_id: ElementsById, id_map: PyMapping, nodes: Dict[]): Dict[] {
  const members: Dict[] = [];
  const group_id = pyStr(pyGet(group, 'id', ''));
  let member_ids: unknown[] = (pyOr(pyGet(group, 'members', []), []) as unknown[]).filter((member_id) => isStr(member_id));
  if (!member_ids.length) {
    // Unified sidecars commonly attach membership to nodes instead of
    // duplicating it in ``group.members``.  Accept both representations.
    member_ids = nodes
      .filter((node) => pyStr(pyGet(node, 'group_id', '')) === group_id && truthy(pyGet(node, 'id')))
      .map((node) => pyStr(pyGet(node, 'id')));
  }
  for (const member_id of member_ids) {
    if (!isStr(member_id)) {
      continue;
    }
    const shape = _shape_for_semantic(elements_by_id, id_map, member_id);
    if (shape !== null) {
      members.push(shape);
    }
  }
  return members;
}

export function _move_bound_companions(elements_by_id: ElementsById, shape: Dict, dx: number, dy: number): null {
  const shape_id = pyGet(shape, 'id');
  for (const element of pyValues(elements_by_id)) {
    if (element === shape) {
      continue;
    }
    if (pyEq(pyGet(element, 'containerId'), shape_id)) {
      element.x = _number(pyGet(element, 'x')) + dx;
      element.y = _number(pyGet(element, 'y')) + dy;
      markF(element, 'x', true);
      markF(element, 'y', true);
    }
  }
  return null;
}

export function _move_semantic_element(
  elements_by_id: ElementsById,
  id_map: PyMapping,
  semantic_id: string,
  x: number,
  y: number,
): null {
  const shape = _shape_for_semantic(elements_by_id, id_map, semantic_id);
  if (shape === null) {
    return null;
  }
  const dx = x - _number(pyGet(shape, 'x'));
  const dy = y - _number(pyGet(shape, 'y'));
  shape.x = x;
  shape.y = y;
  markF(shape, 'x', true); // every caller passes a float position
  markF(shape, 'y', true);
  _move_bound_companions(elements_by_id, shape, dx, dy);

  const icon = _lookup(elements_by_id, pyGet(id_map, `${semantic_id}${ICON_SUFFIX}`, ''));
  if (icon !== null) {
    icon.x = _number(pyGet(icon, 'x')) + dx;
    icon.y = _number(pyGet(icon, 'y')) + dy;
    markF(icon, 'x', true);
    markF(icon, 'y', true);
  }
  return null;
}

export function _set_title_position(
  elements_by_id: ElementsById,
  id_map: PyMapping,
  group_id: string,
  x: number,
  y: number,
): null {
  let title = _lookup(elements_by_id, pyGet(id_map, `${group_id}${TITLE_SUFFIX}`, ''));
  if (title === null) {
    // Unified manifests often use the semantic companion ID directly but
    // omit it from id_map because only the group frame is addressable.
    title = _lookup(elements_by_id, `${group_id}${TITLE_SUFFIX}`);
  }
  if (title !== null) {
    title.x = x;
    title.y = y;
    markF(title, 'x', true); // callers pass ``... + 30.0`` / ``... + 20.0``
    markF(title, 'y', true);
  }
  return null;
}

export function _frame_element(elements_by_id: ElementsById, id_map: PyMapping, group_id: string): Dict | null {
  const frame_id = group_frame_render_id(id_map, group_id);
  const frame = _lookup(elements_by_id, pyOr(frame_id, ''));
  if (!truthy(frame) || pyGet(frame, 'type') === 'arrow') {
    return null;
  }
  return frame;
}

export function _semantic_for_render_id(id_map: PyMapping, render_id: string): string {
  for (const [semantic_id, mapped_id] of pyItems(id_map)) {
    if (pyEq(mapped_id, render_id) && !pyEndswith(semantic_id as string, [BACKGROUND_SUFFIX, TITLE_SUFFIX, ICON_SUFFIX])) {
      return semantic_id as string;
    }
  }
  return render_id;
}

/** Order a fan-in row by upstream barycenter, preserving ordinary rows. */
export function _order_row_by_predecessors(
  row: Dict[],
  id_map: PyMapping,
  predecessor_ids: PyMapping<string[]>,
  original_center_x: PyMapping<number>,
  original_center_y: PyMapping<number>,
): Dict[] {
  const ordered = pySorted(row, (element) => _number(pyGet(element, 'x')));
  if (ordered.length < 3) {
    return ordered;
  }
  const semantic_ids = ordered.map((element) => _semantic_for_render_id(id_map, pyStr(pyGet(element, 'id', ''))));
  const upstream_predecessor_count = (semantic_id: string): number => {
    const target_y = pyGet(original_center_y, semantic_id) as number | null;
    if (target_y === null || target_y === undefined) {
      return 0;
    }
    let count = 0;
    for (const source_id of pyGet(predecessor_ids, semantic_id, []) as string[]) {
      if (pyIn(source_id, original_center_y) && (pyGet(original_center_y, source_id) as number) < target_y - 50.0) {
        count += 1;
      }
    }
    return count;
  };

  if ((pyMax(semantic_ids.map((item) => upstream_predecessor_count(item)), undefined, 0) as number) < 2) {
    return ordered;
  }

  const authored_rank = new Map<string, number>();
  ordered.forEach((element, index) => authored_rank.set(pyStr(pyGet(element, 'id', '')), index));

  const upstream_center = (element: Dict): number => {
    const semantic_id = _semantic_for_render_id(id_map, pyStr(pyGet(element, 'id', '')));
    const centers = (pyGet(predecessor_ids, semantic_id, []) as string[])
      .filter((source_id) => pyIn(source_id, original_center_x))
      .map((source_id) => pyGet(original_center_x, source_id) as number);
    if (centers.length) {
      return pySum(centers) / centers.length;
    }
    return pyGet(
      original_center_x,
      semantic_id,
      _number(pyGet(element, 'x')) + _number(pyGet(element, 'width')) / 2.0,
    ) as number;
  };

  return pySorted(
    ordered,
    (element) => [
      upstream_center(element),
      authored_rank.get(pyStr(pyGet(element, 'id', ''))),
    ],
  );
}

function _groupClass(group: Dict): string {
  return pyLower(pyStr(pyGet(group, 'class', ''))).replaceAll('-', '_').replaceAll(' ', '_');
}

/**
 * Pack architecture groups into compact horizontal layers.
 *
 * Node dimensions, left-to-right ordering, membership, bound text, and icon
 * placement are preserved. Only positions and group frame dimensions change.
 */
export function compact_architecture_layout(manifest: Dict, structure_instantiation: Dict | null): Dict {
  if (!isDict(manifest) || !isDict(structure_instantiation)) {
    return manifest;
  }
  const structure = unwrap_structure_instantiation(structure_instantiation);
  if (!_ARCHITECTURE_TYPES.has(pyLower(pyStrip(pyStr(pyGet(structure, 'chart_type', '')))))) {
    return manifest;
  }

  const groups = (pyOr(pyGet(structure, 'groups', []), []) as unknown[]).filter((group): group is Dict => isDict(group));
  const nodes = (pyOr(pyGet(structure, 'nodes', []), []) as unknown[]).filter((node): node is Dict => isDict(node));
  if (!groups.length) {
    return manifest;
  }

  const output = pyDeepcopy(manifest);
  const elements = (pyGet(output, 'elements', []) as unknown[]).filter((element): element is Dict => isDict(element));
  const elements_by_id = new Map<unknown, Dict>();
  for (const element of elements) {
    if (isStr(pyGet(element, 'id'))) {
      elements_by_id.set(element.id, element);
    }
  }
  const id_map = id_map_from_manifest(output);
  // Python builds a set here; its iteration order does not affect the output
  // (each id normalizes its own shape and only feeds lookup dicts).
  const semantic_node_ids = new Set<string>();
  for (const node of nodes) {
    if (isStr(pyGet(node, 'id'))) {
      semantic_node_ids.add(pyStr(pyGet(node, 'id')));
    }
  }
  for (const group of groups) {
    for (const member_id of pyOr(pyGet(group, 'members', []), []) as unknown[]) {
      if (isStr(member_id)) {
        semantic_node_ids.add(member_id);
      }
    }
  }
  for (const semantic_id of semantic_node_ids) {
    _normalize_member_size(elements_by_id, id_map, semantic_id);
  }

  const original_center_x = new Map<unknown, number>();
  for (const semantic_id of semantic_node_ids) {
    const shape = _shape_for_semantic(elements_by_id, id_map, semantic_id);
    if (shape !== null) {
      original_center_x.set(semantic_id, _number(pyGet(shape, 'x')) + _number(pyGet(shape, 'width')) / 2.0);
    }
  }
  const original_center_y = new Map<unknown, number>();
  for (const semantic_id of semantic_node_ids) {
    const shape = _shape_for_semantic(elements_by_id, id_map, semantic_id);
    if (shape !== null) {
      original_center_y.set(semantic_id, _number(pyGet(shape, 'y')) + _number(pyGet(shape, 'height')) / 2.0);
    }
  }

  const predecessor_ids = new Map<unknown, string[]>();
  for (const edge of pyOr(pyGet(structure, 'edges', []), []) as unknown[]) {
    if (!isMapping(edge)) {
      continue;
    }
    const source_id = pyOr(pyGet(edge, 'source'), pyGet(edge, 'from'));
    const target_id = pyOr(pyGet(edge, 'target'), pyGet(edge, 'to'));
    if (isStr(source_id) && isStr(target_id)) {
      if (!predecessor_ids.has(target_id)) predecessor_ids.set(target_id, []);
      predecessor_ids.get(target_id)!.push(source_id);
    }
  }

  const _is_side_group = (group: Dict): boolean => {
    const group_class = _groupClass(group);
    const group_id = pyLower(pyStr(pyGet(group, 'id', '')));
    return (
      group_class.includes('cross')
      || group_id.includes('cross')
      || group_class.includes('governance')
      || group_id.includes('governance')
    );
  };

  // Classify cross-cutting/governance groups before the generic ``group_*``
  // fallback.  Real Structure output commonly uses IDs such as
  // ``group_enterprise_governance`` while carrying the decisive
  // ``cross_cutting_zone`` class; checking the ID alone incorrectly inserts
  // the sidebar into the main vertical layer stack.
  const side_groups = groups.filter((group) => _is_side_group(group));
  const layer_groups = groups.filter((group) =>
    !pyIn(group, side_groups)
    && (
      _groupClass(group).includes('architecture_layer')
      || pyStr(pyGet(group, 'id', '')).startsWith('group_')
      || truthy(pyGet(group, 'members'))
      || nodes.some((node) => pyStr(pyGet(node, 'group_id', '')) === pyStr(pyGet(group, 'id', '')))
    ));

  const records: Dict[] = [];
  for (const group of layer_groups) {
    const group_id = pyStr(pyGet(group, 'id', ''));
    const frame = _frame_element(elements_by_id, id_map, group_id);
    const members = _members_for_group(group, elements_by_id, id_map, nodes);
    if (frame === null || !members.length) {
      continue;
    }
    let rows = _merge_crowded_rows(_cluster_rows(members));
    rows = rows.map((row) => _order_row_by_predecessors(
      row,
      id_map,
      predecessor_ids,
      original_center_x,
      original_center_y,
    ));
    if (rows.length) {
      records.push({
        group,
        frame,
        members,
        rows,
        old_y: _number(pyGet(frame, 'y')),
        old_x: _number(pyGet(frame, 'x')),
      });
    }
  }
  if (!records.length) {
    return manifest;
  }

  type Rec = { group: Dict; frame: Dict; members: Dict[]; rows: Dict[][]; old_y: number; old_x: number; target_y?: number; target_height?: number };
  const recs = records as unknown as Rec[];

  // Distinct side-by-side layers are an authored horizontal architecture,
  // not an oversized vertical stack. Do not rotate that layout into rows.
  const columns = pySorted(recs, (record) => record.old_x);
  if (columns.length > 1 && columns.slice(0, -1).every((left, i) => {
    const right = columns[i + 1];
    return left.old_x + _number(pyGet(left.frame, 'width')) <= right.old_x
      && pyMaxN(left.old_y, right.old_y) < pyMinN(
        left.old_y + _number(pyGet(left.frame, 'height')),
        right.old_y + _number(pyGet(right.frame, 'height')),
      );
  })) {
    return manifest;
  }
  pySort(recs, (record) => [record.old_y, record.old_x]);

  /** Leave visible shafts and arrowheads around same-row edge labels. */
  const row_gap = (row: Dict[]): number => {
    const row_ids = new Set(row.map((item) => _semantic_for_render_id(id_map, pyStr(pyGet(item, 'id', '')))));
    let gap = _ROW_GAP;
    for (const edge of pyOr(pyGet(structure, 'edges', []), []) as unknown[]) {
      if (pyIn(pyGet(edge, 'source'), row_ids) && pyIn(pyGet(edge, 'target'), row_ids)) {
        const label = pyOr(pyGet(edge, 'label'), '');
        if (isStr(label) && label) {
          gap = pyMaxN(gap, _estimate_text_dimensions(label, 13).width + 48.0);
        }
      }
    }
    return gap;
  };

  let max_row_width = 0.0;
  for (const record of recs) {
    for (const row of record.rows) {
      max_row_width = pyMaxN(
        max_row_width,
        pySum(row.map((element) => _element_size(element)[0]))
        + row_gap(row) * Math.max(0, row.length - 1),
      );
    }
  }
  const content_width = pyMaxN(_MIN_CONTENT_WIDTH, max_row_width + 2 * _CONTENT_SIDE_PADDING);
  const main_x = pyMin(recs.map((record) => record.old_x));
  const main_right = main_x + content_width;
  let next_y = pyMin(recs.map((record) => record.old_y));
  const row_centers: [number, number][] = [];

  for (const record of recs) {
    const group = record.group;
    const group_id = pyStr(pyGet(group, 'id', ''));
    const frame = record.frame;
    const rows = record.rows;
    const row_heights = rows.map((row) => pyMax(row.map((element) => _element_size(element)[1])));
    const frame_height = (
      _FRAME_TOP_PADDING
      + pySum(row_heights)
      + _ROW_GAP * Math.max(0, rows.length - 1)
      + _FRAME_BOTTOM_PADDING
    );
    frame.x = main_x;
    frame.y = next_y;
    frame.width = content_width;
    frame.height = frame_height;
    // main_x / next_y come from _number(); content_width = max(980.0, float); paddings are floats.
    for (const key of ['x', 'y', 'width', 'height']) markF(frame, key, true);
    _set_title_position(elements_by_id, id_map, group_id, main_x + 30.0, next_y + 20.0);

    let row_y = next_y + _FRAME_TOP_PADDING;
    for (let i = 0; i < Math.min(rows.length, row_heights.length); i += 1) {
      const row = rows[i];
      const row_height = row_heights[i];
      const gap = row_gap(row);
      const row_width = pySum(row.map((element) => _element_size(element)[0])) + gap * Math.max(0, row.length - 1);
      let cursor = main_x + (content_width - row_width) / 2.0;
      for (const element of row) {
        const render_id = pyStr(pyGet(element, 'id', ''));
        const semantic_id = _semantic_for_render_id(id_map, render_id);
        const [width] = _element_size(element);
        _move_semantic_element(elements_by_id, id_map, semantic_id, cursor, row_y);
        cursor += width + gap;
      }
      row_centers.push([record.old_y, row_y + row_height / 2.0]);
      row_y += row_height + _ROW_GAP;
    }
    record.target_y = next_y;
    record.target_height = frame_height;
    next_y += frame_height + _LAYER_GAP;
  }

  const total_bottom = next_y - _LAYER_GAP;
  for (const group of side_groups) {
    const group_id = pyStr(pyGet(group, 'id', ''));
    const frame = _frame_element(elements_by_id, id_map, group_id);
    const members = _members_for_group(group, elements_by_id, id_map, nodes);
    if (frame === null || !members.length) {
      continue;
    }
    const side_width = pyMaxN(
      _SIDE_WIDTH,
      pyMax(members.map((member) => _element_size(member)[0])) + 2 * 36.0,
    );
    frame.x = main_right + _SIDE_GAP;
    frame.y = pyMin(recs.map((record) => record.target_y as number));
    frame.width = side_width;
    frame.height = total_bottom - (frame.y as number);
    for (const key of ['x', 'y', 'width', 'height']) markF(frame, key, true);
    _set_title_position(elements_by_id, id_map, group_id, (frame.x as number) + 30.0, (frame.y as number) + 20.0);
    const side_center_x = (frame.x as number) + (frame.width as number) / 2.0;
    const single_member_y = (frame.y as number) + (frame.height as number) / 2.0;
    for (const member of members) {
      const render_id = pyStr(pyGet(member, 'id', ''));
      const semantic_id = _semantic_for_render_id(id_map, render_id);
      let nearest_center: number;
      if (members.length === 1) {
        // A single cross-cutting/governance node is a hub, rather than
        // a layer peer.  Centering it in the sidebar shortens the
        // longest fan-in route and keeps the side channel visually
        // balanced across the main stack.
        nearest_center = single_member_y;
      } else {
        const source_centers: number[] = [];
        for (const source_id of predecessor_ids.get(semantic_id) ?? []) {
          const source_shape = _shape_for_semantic(elements_by_id, id_map, source_id);
          if (source_shape !== null) {
            source_centers.push(
              _number(pyGet(source_shape, 'y'))
              + _number(pyGet(source_shape, 'height')) / 2.0,
            );
          }
        }
        if (source_centers.length) {
          const desired_center = pySum(source_centers) / source_centers.length;
          nearest_center = pyMin(
            row_centers.map((pair) => pair[1]),
            (center) => Math.abs(center - desired_center),
          );
        } else {
          nearest_center = pyMin(
            row_centers,
            (pair) => Math.abs(pair[0] - _number(pyGet(member, 'y'))),
          )[1];
        }
      }
      const [width, height] = _element_size(member);
      _move_semantic_element(
        elements_by_id,
        id_map,
        semantic_id,
        side_center_x - width / 2.0,
        nearest_center - height / 2.0,
      );
    }
  }

  output.elements = elements;
  return output;
}

export const __all__ = ['compact_architecture_layout'];
