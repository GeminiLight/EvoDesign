// Ported from evodesign/agentic_system/render_engine/shared/normalization.py — keep in sync.
//
// Shared normalization logic for diagram manifests: z-order layering,
// group-frame detection, title deduplication and zero-padded index
// assignment.

import { sequential_index } from './order_keys.ts';
import {
  BACKGROUND_SUFFIX,
  GROUP_TITLE_SUFFIXES,
  ICON_SUFFIX,
  TITLE_SUFFIX,
  group_frame_render_id,
  semantic_id_base,
} from '../../common/semantic_ids.ts';
import { pyGet, pyItems, pyKeys } from '../../py/dict.ts';
import { PyTypeError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pyFloatParse, pyInt } from '../../py/number.ts';
import { pySort, pySorted } from '../../py/sort.ts';
import { pyEndswith, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isInt, isMapping, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;
type BBox = [number, number, number, number];

const logger = getLogger('evodesign.agentic_system.render_engine.shared.normalization');

/** ``float(value)`` with Python's TypeError / ValueError behaviour. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

/** ``set(value or [])`` for a list-ish value. */
function _set(value: unknown): Set<unknown> {
  const items = pyOr(value, []);
  if (Array.isArray(items)) return new Set(items);
  if (typeof items === 'string') return new Set([...items]);
  if (items instanceof Set || items instanceof Map) return new Set(items.keys());
  if (isDict(items)) return new Set(Object.keys(items));
  throw new PyTypeError(`'${typeof items}' object is not iterable`);
}

function _intersects(a: Set<unknown>, b: Set<unknown>): boolean {
  for (const item of a) if (b.has(item)) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Z-order layer constants (smaller value = painted first = visually behind).
// ---------------------------------------------------------------------------

export const LAYER_GROUP_FRAME = 100; // group / container backdrops (g_*, <name>:background)
export const LAYER_NODE = 200; // ordinary shape nodes
export const LAYER_ICON = 220; // icons sit above nodes and below connectors/text
export const LAYER_ARROW = 240; // connectors sit above nodes, below labels
export const LAYER_TEXT = 300; // standalone text: group titles, annotations

export const _SHAPE_TYPES: ReadonlySet<string> = new Set(['rectangle', 'ellipse', 'diamond', 'triangle']);

function _isShapeType(value: unknown): boolean {
  return typeof value === 'string' && _SHAPE_TYPES.has(value);
}

/** Return the node id of a group member, whatever shape it arrives in. */
export function normalize_member_ref(member: unknown): string {
  if (isStr(member)) {
    return member;
  }
  if (isDict(member)) {
    const node = pyGet(member, 'node');
    if (isDict(node)) {
      return pyStr(pyOr(pyOr(pyGet(node, 'id'), pyGet(node, 'node_id')), ''));
    }
    return pyStr(pyOr(pyOr(pyGet(member, 'id'), pyGet(member, 'node_id')), ''));
  }
  return '';
}

/** True when an element carries an intentional integer zIndex override. */
export function _has_explicit_zindex(element_data: unknown): boolean {
  if (!isDict(element_data)) {
    return false;
  }
  const z = pyGet(element_data, 'zIndex');
  return isInt(z);
}

// ---------------------------------------------------------------------------
// Naming-convention helpers (shared by both converters)
// ---------------------------------------------------------------------------

/** Return the z-layer for a ``layout_instantiation`` entry. */
export function layer_for(element_id: unknown, element_data: unknown): number {
  if (_has_explicit_zindex(element_data)) {
    return pyInt((element_data as Dict).zIndex as number);
  }

  if (isStr(element_id)) {
    if (element_id.endsWith(TITLE_SUFFIX)) {
      return LAYER_TEXT;
    }
    if (element_id.endsWith(BACKGROUND_SUFFIX)) {
      return LAYER_GROUP_FRAME;
    }
    if (element_id.startsWith('g_')) {
      return LAYER_GROUP_FRAME;
    }
  }

  if (isDict(element_data)) {
    if (pyGet(element_data, 'is_group') === true) {
      return LAYER_GROUP_FRAME;
    }
    if (pyGet(element_data, 'type') === 'text' || pyGet(element_data, 'shape') === 'text') {
      return LAYER_TEXT;
    }
  }

  return LAYER_NODE;
}

/** Strip title/background suffixes so companion entries share the same base id. */
export function base_id(element_id: string): string {
  if (!isStr(element_id)) {
    return element_id;
  }
  for (const suffix of [TITLE_SUFFIX, BACKGROUND_SUFFIX]) {
    if (element_id.endsWith(suffix)) {
      return element_id.slice(0, -suffix.length);
    }
  }
  return element_id;
}

/** True if this layout_instantiation entry is a group frame. */
export function is_group_frame(element_id: unknown, element_data: unknown): boolean {
  return layer_for(element_id, element_data) === LAYER_GROUP_FRAME;
}

// ---------------------------------------------------------------------------
// Manifest-level helpers (used by normalizer for unified-mode manifests)
// ---------------------------------------------------------------------------

/** Return ``(x, y, right, bottom)`` for an Excalidraw element. */
export function _bbox(elem: Dict): BBox {
  const x = _float(pyOr(pyGet(elem, 'x', 0), 0));
  const y = _float(pyOr(pyGet(elem, 'y', 0), 0));
  let w = pyGet(elem, 'width') !== null ? pyGet(elem, 'width') : pyGet(elem, 'w', 0);
  let h = pyGet(elem, 'height') !== null ? pyGet(elem, 'height') : pyGet(elem, 'h', 0);
  w = _float(pyOr(w, 0));
  h = _float(pyOr(h, 0));
  return [x, y, x + (w as number), y + (h as number)];
}

export function _bbox_contains(outer: readonly number[], inner: readonly number[], tol = 1.0): boolean {
  const [ox, oy, or_, ob] = outer;
  const [ix, iy, ir, ib] = inner;
  return (
    ox - tol <= ix
    && oy - tol <= iy
    && or_ + tol >= ir
    && ob + tol >= ib
  );
}

export function _elem_id(elem: Dict): string | null {
  const eid = pyGet(elem, 'id');
  return isStr(eid) ? eid : null;
}

/** True when the element is unambiguously a group frame by naming / flag. */
export function _explicit_frame_signal(elem: Dict): boolean {
  if (pyGet(elem, 'is_group') === true) {
    return true;
  }
  const eid = _elem_id(elem);
  if (eid === null) {
    return false;
  }
  if (eid.endsWith(TITLE_SUFFIX)) {
    return false;
  }
  if (eid.endsWith(BACKGROUND_SUFFIX)) {
    return true;
  }
  if (eid.startsWith('g_')) {
    return true;
  }
  return false;
}

export function _frame_ids_from_id_map(id_map: unknown): Set<string> {
  const frame_ids = new Set<string>();
  if (!isMapping(id_map)) {
    return frame_ids;
  }

  const non_frame_suffixes = [...GROUP_TITLE_SUFFIXES, ICON_SUFFIX];
  for (const [semantic_id, render_id] of pyItems(id_map)) {
    if (!isStr(semantic_id) || !isStr(render_id)) {
      continue;
    }
    if (semantic_id.endsWith(BACKGROUND_SUFFIX)) {
      frame_ids.add(render_id);
      continue;
    }
    if (semantic_id.startsWith('g_') && !pyEndswith(semantic_id, non_frame_suffixes)) {
      frame_ids.add(render_id);
    }
  }

  return frame_ids;
}

export function _title_marked_frame_candidates(elements: Dict[], id_map: unknown): Set<string> {
  const candidate_ids = new Set<string>();
  const titled_bases = new Set<string>();
  if (isMapping(id_map)) {
    for (const semantic_id of pyKeys(id_map)) {
      if (isStr(semantic_id) && pyEndswith(semantic_id, GROUP_TITLE_SUFFIXES)) {
        const base = semantic_id_base(semantic_id);
        if (truthy(base)) {
          titled_bases.add(base!);
        }
      }
    }
  }

  for (const base of titled_bases) {
    const frame_id = group_frame_render_id(id_map as Dict, base);
    if (truthy(frame_id)) {
      candidate_ids.add(frame_id!);
    }
  }

  const element_ids = new Set<string>();
  for (const elem of elements) {
    if (isDict(elem) && isStr(pyGet(elem, 'id'))) {
      element_ids.add(pyGet(elem, 'id') as string);
    }
  }
  for (const elem_id of element_ids) {
    if (!isStr(elem_id)) {
      continue;
    }
    if (GROUP_TITLE_SUFFIXES.some((suffix) => element_ids.has(`${elem_id}${suffix}`))) {
      candidate_ids.add(elem_id);
    }
  }

  return candidate_ids;
}

export function _is_structural_frame_candidate(candidate_id: string, elements: Dict[]): boolean {
  let candidate: Dict | null = null;
  for (const elem of elements) {
    if (_elem_id(elem) === candidate_id) {
      candidate = elem;
      break;
    }
  }
  if (!truthy(candidate) || !_isShapeType(pyGet(candidate, 'type'))) {
    return false;
  }

  const candidate_bbox = _bbox(candidate!);
  let contained = 0;
  for (const elem of elements) {
    if (elem === candidate || truthy(pyGet(elem, 'isDeleted'))) {
      continue;
    }
    const child_id = _elem_id(elem);
    if (!truthy(child_id)) {
      continue;
    }
    if (GROUP_TITLE_SUFFIXES.some((suffix) => child_id === `${candidate_id}${suffix}`)) {
      continue;
    }
    if (pyGet(elem, 'type') === 'arrow') {
      continue;
    }
    if (pyGet(elem, 'type') === 'text' && pyGet(elem, 'containerId') === candidate_id) {
      continue;
    }
    if (_bbox_contains(candidate_bbox, _bbox(elem))) {
      contained += 1;
      if (contained >= 2) {
        return true;
      }
    }
  }

  return false;
}

/** Return element IDs classified as group frames. */
export function detect_group_frame_ids(elements: Dict[], structural = false, id_map: unknown = null): Set<string> {
  const frame_ids = _frame_ids_from_id_map(id_map);
  if (!truthy(elements)) {
    return frame_ids;
  }

  // Pass 1: naming convention + explicit flags.
  for (const elem of elements) {
    if (!_isShapeType(pyGet(elem, 'type'))) {
      continue;
    }
    if (_explicit_frame_signal(elem)) {
      const eid = _elem_id(elem);
      if (truthy(eid)) {
        frame_ids.add(eid!);
      }
    }
  }

  if (!structural) {
    return frame_ids;
  }

  for (const candidate_id of _title_marked_frame_candidates(elements, id_map)) {
    if (!frame_ids.has(candidate_id) && _is_structural_frame_candidate(candidate_id, elements)) {
      frame_ids.add(candidate_id);
    }
  }

  // Pass 2: containment heuristic for unified-mode manifests.
  for (const elem of elements) {
    if (!_isShapeType(pyGet(elem, 'type'))) {
      continue;
    }
    const eid = _elem_id(elem);
    if (!truthy(eid) || frame_ids.has(eid!)) {
      continue;
    }

    const e_groups = _set(pyGet(elem, 'groupIds'));
    if (!e_groups.size) {
      continue;
    }

    const e_bb = _bbox(elem);
    let contained = 0;
    for (const other of elements) {
      if (other === elem) {
        continue;
      }
      const oid = _elem_id(other);
      if (oid === eid) {
        continue;
      }
      if (pyGet(other, 'type') === 'arrow') {
        continue;
      }
      if (pyGet(other, 'type') === 'text' && pyGet(other, 'containerId') === eid) {
        continue;
      }

      const other_groups = _set(pyGet(other, 'groupIds'));
      if (!_intersects(e_groups, other_groups)) {
        continue;
      }
      if (_bbox_contains(e_bb, _bbox(other))) {
        contained += 1;
        if (contained >= 2) {
          frame_ids.add(eid!);
          break;
        }
      }
    }
  }

  return frame_ids;
}

/**
 * Remove bound-text titles that duplicate a standalone title. Returns a
 * filtered element list and strips dangling ``boundElements`` references.
 */
export function deduplicate_group_titles(elements: Dict[], frame_ids: Iterable<string>): Dict[] {
  if (!truthy(frame_ids) || !truthy(elements)) {
    return elements;
  }

  const by_id = new Map<string, Dict>();
  for (const elem of elements) {
    const eid = _elem_id(elem);
    if (truthy(eid)) {
      by_id.set(eid!, elem);
    }
  }

  const to_remove = new Set<string | null>();

  for (const frame_id of frame_ids) {
    const frame = by_id.get(frame_id) ?? null;
    if (!truthy(frame)) {
      continue;
    }

    const frame_bbox = _bbox(frame!);
    const frame_groups = _set(pyGet(frame!, 'groupIds'));

    const bound_on_frame = elements.filter((e) =>
      pyGet(e, 'type') === 'text'
      && pyGet(e, 'containerId') === frame_id
      && _elem_id(e) !== null);
    if (!bound_on_frame.length) {
      continue;
    }

    for (const bt of bound_on_frame) {
      const bt_text = pyStrip(pyStr(pyOr(pyGet(bt, 'text'), '')));
      if (!bt_text) {
        continue;
      }

      const bt_id = _elem_id(bt);
      for (const other of elements) {
        if (other === bt) {
          continue;
        }
        if (pyGet(other, 'type') !== 'text') {
          continue;
        }
        if (truthy(pyGet(other, 'containerId'))) {
          continue;
        }
        if (pyStrip(pyStr(pyOr(pyGet(other, 'text'), ''))) !== bt_text) {
          continue;
        }

        const other_groups = _set(pyGet(other, 'groupIds'));
        const shares_group = _intersects(frame_groups, other_groups);
        const inside_frame = _bbox_contains(frame_bbox, _bbox(other));
        if (shares_group || inside_frame) {
          to_remove.add(bt_id);
          break;
        }
      }
    }
  }

  if (!to_remove.size) {
    return elements;
  }

  const filtered = elements.filter((e) => !to_remove.has(_elem_id(e)));

  // Strip dangling boundElements references.
  for (const elem of filtered) {
    const bound = pyGet(elem, 'boundElements');
    if (Array.isArray(bound) && bound.length) {
      elem.boundElements = bound.filter((b) => !(isDict(b) && to_remove.has(pyGet(b, 'id') as string)));
    }
  }

  logger.info(
    '[normalization] removed %d duplicate bound-text title(s): %s',
    to_remove.size,
    pySorted(to_remove),
  );
  return filtered;
}

/**
 * Stable-sort elements by z-layer and assign zero-padded indices.
 * Returns ``[sorted_elements, next_counter]``; each element's ``index`` is
 * mutated in place.
 */
export function sort_and_reindex(elements: Dict[], index_counter = 0): [Dict[], number] {
  const decorated: [number, number, Dict][] = elements.map((elem, orig_idx) => [layer_for(pyGet(elem, 'id'), elem), orig_idx, elem]);
  pySort(decorated, (t) => [t[0], t[1]]);

  const ordered = decorated.map((t) => t[2]);
  let counter = index_counter;
  for (const elem of ordered) {
    elem.index = sequential_index(counter);
    counter += 1;
  }

  return [ordered, counter];
}
