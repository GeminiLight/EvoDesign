// Ported from evodesign/agentic_system/render_engine/excalidraw/group_fitter.py — keep in sync.
//
// Excalidraw Group Fitter - Ensure group background elements contain their children.
//
// Counterpart of group_fitter.py for the Excalidraw canvas library.

import { copyF, isF, markF, pyDeepcopy } from '../../py/float_marks.ts';
import { normalize_diagram_type } from '../../common/diagram_types.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import {
  BACKGROUND_SUFFIX,
  GROUP_TITLE_SUFFIXES,
  companion_id,
  group_frame_render_id,
  id_map_from_manifest,
} from '../../common/semantic_ids.ts';
import { normalize_member_ref } from '../shared/normalization.ts';
import { pyGet, pyGetItem, type PyMapping } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { PyTypeError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyMinN, pyMaxN, pySorted } from '../../py/sort.ts';
import { pyRepr, pyStr } from '../../py/str.ts';
import { pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

const logger = getLogger('evodesign.agentic_system.render_engine.excalidraw.group_fitter');

// Types whose frames are the figure itself (equal quadrants, columns and
// bands): shrinking them to their children breaks the geometry.
export const _FIXED_FRAME_TYPES: ReadonlySet<string> = new Set(['quadrant', 'layer_stack', 'user_journey', 'kanban', 'story_map']);
// Containment types: each scope is sized from its contents, innermost first,
// with a title band on top. Frames drawn larger than their contents would
// otherwise stay large and leave the figure sparse.
export const _CONTAINMENT_TYPES: ReadonlySet<string> = new Set(['nested', 'deployment']);
export const _SCOPE_SIDE_PADDING = 24.0;
export const _SCOPE_TITLE_GAP = 12.0;

/** Python ``a + b`` for numbers (bool counts as int) and strings; anything else raises TypeError. */
function _add(a: unknown, b: unknown): unknown {
  const an = typeof a === 'number' || typeof a === 'boolean';
  const bn = typeof b === 'number' || typeof b === 'boolean';
  if (an && bn) return Number(a) + Number(b);
  if (typeof a === 'string' && typeof b === 'string') return a + b;
  throw new PyTypeError('unsupported operand type(s) for +');
}

/** ``float(value)`` with Python's TypeError / ValueError behaviour. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError('float() argument must be a string or a real number');
}

/** ``for x in value`` over a list-like value (``None`` raises like Python). */
function _iter(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (value instanceof Set || value instanceof Map) return [...value.keys()];
  if (value !== null && typeof value === 'object') return Object.keys(value);
  throw new PyTypeError(`'${value === null || value === undefined ? 'NoneType' : typeof value}' object is not iterable`);
}

/** Get the bounding box of an Excalidraw element. */
export function _get_element_bounds(elem: Dict): Dict {
  const x = pyGet(elem, 'x', 0);
  const y = pyGet(elem, 'y', 0);
  const w = pyGet(elem, 'width', 0);
  const h = pyGet(elem, 'height', 0);
  const bounds: Dict = {
    x,
    y,
    w,
    h,
    right: _add(x, w),
    bottom: _add(y, h),
  };
  copyF(elem, 'x', bounds, 'x');
  copyF(elem, 'y', bounds, 'y');
  copyF(elem, 'width', bounds, 'w');
  copyF(elem, 'height', bounds, 'h');
  markF(bounds, 'right', isF(elem, 'x') || isF(elem, 'width'));
  markF(bounds, 'bottom', isF(elem, 'y') || isF(elem, 'height'));
  return bounds;
}

/** Calculate the bounding box that contains all elements. */
export function _calculate_bounding_box(elements: Dict[]): Dict | null {
  if (!truthy(elements)) {
    return null;
  }

  let min_x = Infinity;
  let min_y = Infinity;
  let max_x = -Infinity;
  let max_y = -Infinity;
  // float("inf") starts as a float; min()/max() keep the first operand unless the other wins.
  let min_x_f = true;
  let min_y_f = true;
  let max_x_f = true;
  let max_y_f = true;

  for (const elem of elements) {
    const bounds = _get_element_bounds(elem);
    if ((bounds.x as number) < min_x) min_x_f = isF(bounds, 'x');
    if ((bounds.y as number) < min_y) min_y_f = isF(bounds, 'y');
    if ((bounds.right as number) > max_x) max_x_f = isF(bounds, 'right');
    if ((bounds.bottom as number) > max_y) max_y_f = isF(bounds, 'bottom');
    min_x = pyMinN(min_x, bounds.x as number);
    min_y = pyMinN(min_y, bounds.y as number);
    max_x = pyMaxN(max_x, bounds.right as number);
    max_y = pyMaxN(max_y, bounds.bottom as number);
  }

  const bbox: Dict = {
    min_x,
    min_y,
    max_x,
    max_y,
  };
  markF(bbox, 'min_x', min_x_f);
  markF(bbox, 'min_y', min_y_f);
  markF(bbox, 'max_x', max_x_f);
  markF(bbox, 'max_y', max_y_f);
  return bbox;
}

/** Return the sides of *bounds* that a sibling frame abuts or overlaps. */
export function _shared_edges(bounds: Dict, others: Dict[], tolerance = 24.0): Set<string> {
  const blocked = new Set<string>();
  const b = bounds as Record<string, number>;
  for (const other of others) {
    const o = _get_element_bounds(other) as Record<string, number>;
    const overlap_y = pyMinN(b.bottom, o.bottom) - pyMaxN(b.y, o.y) > 0;
    const overlap_x = pyMinN(b.right, o.right) - pyMaxN(b.x, o.x) > 0;
    if (overlap_y && Math.abs(o.x - b.right) <= tolerance) {
      blocked.add('right');
    }
    if (overlap_y && Math.abs(o.right - b.x) <= tolerance) {
      blocked.add('left');
    }
    if (overlap_x && Math.abs(o.y - b.bottom) <= tolerance) {
      blocked.add('bottom');
    }
    if (overlap_x && Math.abs(o.bottom - b.y) <= tolerance) {
      blocked.add('top');
    }
  }
  return blocked;
}

export function _group_title(elem_by_eid: PyMapping<Dict>, id_map: PyMapping, group_id: string): Dict | null {
  for (const suffix of GROUP_TITLE_SUFFIXES) {
    const title = pyGet(elem_by_eid, pyStr(pyOr(pyGet(id_map, companion_id(group_id, suffix)), ''))) as Dict | null;
    if (title !== null && title !== undefined && pyGet(title, 'type') === 'text') {
      return title;
    }
  }
  return null;
}

/**
 * Wrap a containment scope tightly around its contents, title band on top.
 *
 * The title keeps its inset from the frame corner (clamped to a sane range)
 * and moves with the frame, so a shrunken scope does not leave its title
 * floating where the old frame edge used to be.
 */
export function _fit_scope(frame: Dict, bbox: Dict, title: Dict | null): null {
  const side = _SCOPE_SIDE_PADDING;
  let inset_x = 0.0;
  let inset_y = 0.0;
  let title_w = 0.0;
  let title_h = 0.0;
  if (title !== null && title !== undefined) {
    const bounds = _get_element_bounds(frame);
    inset_x = pyMinN(pyMaxN(_float(pyGet(title, 'x', 0)) - (bounds.x as number), 8.0), side);
    inset_y = pyMinN(pyMaxN(_float(pyGet(title, 'y', 0)) - (bounds.y as number), 8.0), 16.0);
    title_w = _float(pyOr(pyGet(title, 'width'), 0));
    title_h = _float(pyOr(pyGet(title, 'height'), 0));
  }
  const hasTitle = title !== null && title !== undefined;
  const top = hasTitle ? inset_y + title_h + _SCOPE_TITLE_GAP : side;
  const box = bbox as Record<string, number>;
  const x = box.min_x - side;
  const y = box.min_y - top;
  const right = pyMaxN(box.max_x + side, x + inset_x + title_w + side);
  const bottom = box.max_y + side;
  Object.assign(frame, { x, y, width: right - x, height: bottom - y });
  // ``side`` / insets are floats, so every coordinate written here is a float.
  for (const key of ['x', 'y', 'width', 'height']) markF(frame, key, true);
  if (hasTitle) {
    Object.assign(title!, { x: x + inset_x, y: y + inset_y });
    markF(title, 'x', true);
    markF(title, 'y', true);
  }
  return null;
}

/**
 * Expand group background elements in the Excalidraw manifest as needed to contain all children.
 * Preserve the layout stage's intended group footprint when it is already large enough.
 *
 * @param manifest Excalidraw manifest with elements, files, _meta
 * @param structure_instantiation Semantic graph with group-member relationships
 * @param padding Padding around children in pixels
 * @returns Updated manifest with resized group backgrounds
 */
export function fit_excalidraw_groups_to_children(
  manifest: Dict,
  structure_instantiation: Dict,
  padding = 20,
): Dict {
  manifest = pyDeepcopy(manifest);
  const elements = pyGet(manifest, 'elements', []) as Dict[];
  const id_map = id_map_from_manifest(manifest);

  // Build element lookup: excalidraw_id -> element reference
  const elem_by_eid = new Map<unknown, Dict>();
  for (const elem of elements) {
    elem_by_eid.set(pyGet(elem, 'id', ''), elem);
  }

  const data = unwrap_structure_instantiation(structure_instantiation);

  const chart_type = normalize_diagram_type(pyStr(pyOr(pyGet(data, 'chart_type'), '')));
  const fixed_frames = _FIXED_FRAME_TYPES.has(chart_type);
  const containment = _CONTAINMENT_TYPES.has(chart_type);
  const groups = pyGet(data, 'groups', []) as Dict[];
  if (!truthy(groups)) {
    logger.info('[ExcalidrawGroupFitter] No groups found in structure_instantiation');
    return manifest;
  }

  // Fit inner scopes first so each parent wraps its child frames as fitted.
  // A scope may name its parent with ``parent_group_id`` or be listed among
  // the parent's members; the structure validator accepts both.
  const group_ids = new Set<unknown>();
  for (const g of groups) {
    if (truthy(pyGet(g, 'id'))) group_ids.add(pyGet(g, 'id'));
  }
  const parent_of = new Map<unknown, unknown>();
  for (const g of groups) {
    if (group_ids.has(pyGet(g, 'parent_group_id'))) {
      parent_of.set(pyGetItem(g, 'id'), pyGetItem(g, 'parent_group_id'));
    }
    for (const member of _iter(pyOr(pyGet(g, 'members', []), []))) {
      const member_id = normalize_member_ref(member);
      if (group_ids.has(member_id) && !pyEq(member_id, pyGet(g, 'id'))) {
        if (!parent_of.has(member_id)) parent_of.set(member_id, pyGetItem(g, 'id'));
      }
    }
  }
  const children_of = new Map<unknown, unknown[]>();
  for (const [child, parent] of parent_of) {
    if (!children_of.has(parent)) children_of.set(parent, []);
    children_of.get(parent)!.push(child);
  }

  const depth = (group_id: unknown): number => {
    const seen = new Set<unknown>();
    while (parent_of.has(group_id) && !seen.has(group_id)) {
      seen.add(group_id);
      group_id = parent_of.get(group_id);
    }
    return seen.size;
  };

  const frame_of = (group_id: unknown): Dict | null => {
    const found = elem_by_eid.get(pyOr(group_frame_render_id(id_map, group_id), ''));
    return found === undefined ? null : found;
  };

  for (const group of pySorted(groups, (g) => -depth(pyGet(g, 'id', '')))) {
    const group_semantic_id = pyGet(group, 'id', '') as string;
    const members = pyGet(group, 'members', []);
    const child_scopes = children_of.get(group_semantic_id) ?? [];

    if (!truthy(members) && !truthy(child_scopes)) {
      logger.debug(`[ExcalidrawGroupFitter] Group ${pyStr(group_semantic_id)} has no members, skipping`);
      continue;
    }

    // Find group background element
    const bg_excalidraw_id = group_frame_render_id(id_map, group_semantic_id);
    if (!truthy(bg_excalidraw_id)) {
      logger.debug(`[ExcalidrawGroupFitter] Background ID not found for ${pyStr(group_semantic_id)}`);
      continue;
    }
    // A parent scope keeps the footprint the layout gave it (title room
    // included) and only grows to hold its child frames.
    const uses_companion_frame = fixed_frames || truthy(child_scopes) || (
      pyEq(pyGet(id_map, companion_id(group_semantic_id, BACKGROUND_SUFFIX)), bg_excalidraw_id)
    );

    const bg_lookup = elem_by_eid.get(bg_excalidraw_id);
    const bg_elem = bg_lookup === undefined ? null : bg_lookup;
    if (!truthy(bg_elem)) {
      logger.warning(`[ExcalidrawGroupFitter] Background element not found: ${pyStr(bg_excalidraw_id)}`);
      continue;
    }

    // Collect shapes to wrap: member nodes only (NOT title).
    // Title is a label that sits on/above the group frame — it must not
    // drive the group background expansion, otherwise the frame creeps
    // upward to engulf the title.
    const shapes_to_wrap: Dict[] = [];

    for (const member of _iter(members)) {
      const member_id = normalize_member_ref(member);
      if (!member_id || group_ids.has(member_id)) {
        if (!member_id) {
          logger.debug(`[ExcalidrawGroupFitter] Unrecognized member entry ${pyRepr(member)}`);
        }
        continue;
      }
      const member_excalidraw_id = pyGet(id_map, member_id);
      if (truthy(member_excalidraw_id)) {
        const found = elem_by_eid.get(member_excalidraw_id);
        const member_elem = found === undefined ? null : found;
        if (truthy(member_elem) && pyGet(member_elem, 'type') !== 'text') {
          shapes_to_wrap.push(member_elem!);
        } else {
          logger.debug(`[ExcalidrawGroupFitter] Member ${member_id} -> ${pyStr(member_excalidraw_id)} not found or is text`);
        }
      } else {
        logger.debug(`[ExcalidrawGroupFitter] Member ${member_id} not in id_map`);
      }
    }

    for (const child_id of child_scopes) {
      const child_frame = frame_of(child_id);
      if (child_frame !== null && child_frame !== bg_elem) {
        shapes_to_wrap.push(child_frame);
      }
    }

    if (!shapes_to_wrap.length) {
      logger.warning(`[ExcalidrawGroupFitter] No valid shapes to wrap for group ${pyStr(group_semantic_id)}`);
      continue;
    }

    const bbox = _calculate_bounding_box(shapes_to_wrap);
    if (!truthy(bbox)) {
      continue;
    }
    const box = bbox as Record<string, number>;

    if (containment) {
      _fit_scope(bg_elem!, bbox!, _group_title(elem_by_eid as PyMapping<Dict>, id_map, group_semantic_id));
      continue;
    }

    let new_x: number;
    let new_y: number;
    let new_right: number;
    let new_bottom: number;
    let new_x_f: boolean;
    let new_y_f: boolean;
    let new_right_f: boolean;
    let new_bottom_f: boolean;
    const pad_f = !Number.isInteger(padding);
    if (uses_companion_frame) {
      // Preserve the layout stage's intended organizer footprint and only
      // expand when children/title would otherwise overflow it. Padding is
      // added only where overflow occurs, so a title placed 16 px from a
      // lane's left edge does not cause the lane to creep leftward and
      // overlap its neighbour.
      const bg_bounds = _get_element_bounds(bg_elem!);
      const bb = bg_bounds as Record<string, number>;
      let needs_left = box.min_x < bb.x;
      let needs_top = box.min_y < bb.y;
      let needs_right = box.max_x > bb.right;
      let needs_bottom = box.max_y > bb.bottom;
      if (fixed_frames) {
        // Equal cells, columns and bands share edges with their
        // siblings; growing across a shared edge would overlap the
        // neighbour, so only the figure's outer edges may grow.
        const own_parent = parent_of.has(group_semantic_id) ? parent_of.get(group_semantic_id) : null;
        const siblings = groups
          .filter((g) => !pyEq(pyGet(g, 'id'), group_semantic_id)
            && pyEq(parent_of.has(pyGet(g, 'id')) ? parent_of.get(pyGet(g, 'id')) : null, own_parent))
          .map((g) => frame_of(pyGet(g, 'id')));
        const blocked = _shared_edges(bg_bounds, siblings.filter((f): f is Dict => f !== null && f !== bg_elem));
        needs_left = needs_left && !blocked.has('left');
        needs_top = needs_top && !blocked.has('top');
        needs_right = needs_right && !blocked.has('right');
        needs_bottom = needs_bottom && !blocked.has('bottom');
      }

      new_x = needs_left ? pyMinN(bb.x, box.min_x - padding) : bb.x;
      new_y = needs_top ? pyMinN(bb.y, box.min_y - padding) : bb.y;
      new_right = needs_right ? pyMaxN(bb.right, box.max_x + padding) : bb.right;
      new_bottom = needs_bottom ? pyMaxN(bb.bottom, box.max_y + padding) : bb.bottom;
      // min(a, b) / max(a, b) return ``a`` unless ``b`` is strictly better.
      const pick = (needs: boolean, key: string, other: number, other_f: boolean, smaller: boolean): boolean => {
        if (!needs) return isF(bg_bounds, key);
        const wins = smaller ? other < bb[key] : other > bb[key];
        return wins ? other_f : isF(bg_bounds, key);
      };
      new_x_f = pick(needs_left, 'x', box.min_x - padding, isF(bbox, 'min_x') || pad_f, true);
      new_y_f = pick(needs_top, 'y', box.min_y - padding, isF(bbox, 'min_y') || pad_f, true);
      new_right_f = pick(needs_right, 'right', box.max_x + padding, isF(bbox, 'max_x') || pad_f, false);
      new_bottom_f = pick(needs_bottom, 'bottom', box.max_y + padding, isF(bbox, 'max_y') || pad_f, false);
    } else {
      // Direct group-id mappings do not have a separate companion frame
      // contract, so fit the frame tightly to its children.
      new_x = box.min_x - padding;
      new_y = box.min_y - padding;
      new_right = box.max_x + padding;
      new_bottom = box.max_y + padding;
      new_x_f = isF(bbox, 'min_x') || pad_f;
      new_y_f = isF(bbox, 'min_y') || pad_f;
      new_right_f = isF(bbox, 'max_x') || pad_f;
      new_bottom_f = isF(bbox, 'max_y') || pad_f;
    }

    const new_w = new_right - new_x;
    const new_h = new_bottom - new_y;

    bg_elem!.x = new_x;
    bg_elem!.y = new_y;
    bg_elem!.width = new_w;
    bg_elem!.height = new_h;
    markF(bg_elem, 'x', new_x_f);
    markF(bg_elem, 'y', new_y_f);
    markF(bg_elem, 'width', new_right_f || new_x_f);
    markF(bg_elem, 'height', new_bottom_f || new_y_f);

    logger.info(
      `[ExcalidrawGroupFitter] Fitted group ${pyStr(group_semantic_id)}: `
      + `x=${pyStr(new_x)}, y=${pyStr(new_y)}, w=${pyStr(new_w)}, h=${pyStr(new_h)} `
      + `(wrapped ${shapes_to_wrap.length} shapes)`,
    );
  }

  manifest.elements = elements;
  return manifest;
}
