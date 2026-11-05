// Ported from evodesign/agentic_system/render_engine/excalidraw/shape_size_fitter.py — keep in sync.
//
// Post-layout shape-size fitter for Excalidraw manifests: expands container
// shapes (center-invariant, never shrinks) so their bound text fits, grows
// standalone text, then resolves / reverts overlaps the expansion caused.
// Run AFTER ``convert`` and BEFORE ``arrows``.

import { copyF, markF } from '../../py/float_marks.ts';
import { pyDeepcopy } from '../../py/float_marks.ts';
import { sync_node_icons } from '../../common/node_icons.ts';
import {
  _ICON_LEFT_PAD,
  _ICON_TEXT_GAP,
  _estimate_text_dimensions,
} from '../../generation_stage/layout/element_shape_estimator.ts';
import {
  BACKGROUND_SUFFIX,
  TITLE_SUFFIX,
  companion_id,
  id_map_from_manifest,
  reverse_id_map,
} from '../../common/semantic_ids.ts';
import { pyGet, pyGetItem, pyItems, pySetdefault } from '../../py/dict.ts';
import { PyTypeError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { ceil } from '../../py/math.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyMaxN, pyMinN, pySort, pySorted } from '../../py/sort.ts';
import { isDict, isNumberOrBool, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

// Per-side padding between text edge and shape boundary (total = 2 × value).
export const _PAD_W = 20.0;
export const _PAD_H = 15.0;

// Shape-type-specific inflate factors.
export const SHAPE_INFLATE: Readonly<Record<string, number>> = {
  rectangle: 1.0,
  diamond: 1.4,
  ellipse: 1.2,
};

// Only these element types can grow to fit bound text.
export const _CONTAINER_TYPES: ReadonlySet<string> = new Set(Object.keys(SHAPE_INFLATE));

function hasKey(obj: unknown, key: unknown): boolean {
  return isDict(obj) && typeof key === 'string' && Object.prototype.hasOwnProperty.call(obj, key);
}

function isContainerType(value: unknown): boolean {
  return typeof value === 'string' && _CONTAINER_TYPES.has(value);
}

/** ``float(value)`` raising TypeError / ValueError like Python. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError('float() argument must be a string or a real number');
}

/** Excalidraw text elements always carry a top-level ``fontSize``; fall back to 16. */
export function _read_font_size(text_elem: Dict): number {
  const fs = pyGet(text_elem, 'fontSize');
  if (isNumberOrBool(fs) && Number(fs) > 0) {
    return Math.trunc(Number(fs));
  }
  return 16;
}

/** Geometry required to hold ``text_elem.text`` at its own ``fontSize``. */
export function _required_text_bbox(text_elem: Dict): { width: number; height: number } {
  const text = pyOr(pyGet(text_elem, 'text'), '') as string;
  const fs = _read_font_size(text_elem);
  return _estimate_text_dimensions(text, fs);
}

/** First ``type=="text"`` entry in ``shape.boundElements``, resolved via ``by_id``. */
export function _find_bound_text(shape: Dict, by_id: Record<string, Dict>): Dict | null {
  for (const b of (pyOr(pyGet(shape, 'boundElements'), []) as unknown[])) {
    if (isDict(b) && pyGet(b, 'type') === 'text') {
      const tid = pyGet(b, 'id');
      if (truthy(tid) && hasKey(by_id, tid)) {
        return by_id[tid as string];
      }
    }
  }
  return null;
}

export function _num(value: unknown, default_ = 0.0): number {
  try {
    return _float(value);
  } catch {
    return default_;
  }
}

export function _element_bbox(elem: Dict): { x: number; y: number; width: number; height: number } {
  return {
    x: _num(pyGet(elem, 'x')),
    y: _num(pyGet(elem, 'y')),
    width: _num(pyGet(elem, 'width')),
    height: _num(pyGet(elem, 'height')),
  };
}

export function _contains_center(container: Dict, child: Dict, tol = 1.0): boolean {
  const cb = _element_bbox(container);
  const ib = _element_bbox(child);
  if (cb.width <= 0 || cb.height <= 0 || ib.width <= 0 || ib.height <= 0) {
    return false;
  }

  const icon_cx = ib.x + ib.width / 2.0;
  const icon_cy = ib.y + ib.height / 2.0;
  return (
    cb.x - tol <= icon_cx && icon_cx <= cb.x + cb.width + tol
    && cb.y - tol <= icon_cy && icon_cy <= cb.y + cb.height + tol
  );
}

/** Infer the node container for each rendered icon image by geometry. */
export function _map_icons_to_containers(elements: Dict[]): Record<string, Dict> {
  const containers = elements.filter(
    (e) => isDict(e) && isContainerType(pyGet(e, 'type')) && truthy(pyGet(e, 'id')),
  );
  const icons = elements.filter(
    (e) => isDict(e) && pyGet(e, 'type') === 'image' && truthy(pyGet(e, 'id')),
  );

  const icon_by_container: Record<string, Dict> = {};
  for (const icon of icons) {
    const candidates = containers.filter((shape) => _contains_center(shape, icon));
    if (!candidates.length) {
      continue;
    }
    pySort(candidates, (s) => _num(pyGet(s, 'width')) * _num(pyGet(s, 'height')));
    const container = candidates[0];
    pySetdefault(icon_by_container, container.id as string, icon);
  }
  return icon_by_container;
}

/**
 * Expand ``shape`` (in place) so its bbox holds the bound text; re-center text.
 * Records original geometry in ``original_dims`` only when the shape resized.
 */
export function _fit_container_to_text(
  shape: Dict,
  text_elem: Dict,
  icon_elem: Dict | null = null,
  original_dims: Record<string, Dict> | null = null,
): null {
  const shape_type = pyGet(shape, 'type');
  const inflate = typeof shape_type === 'string' && hasKey(SHAPE_INFLATE, shape_type) ? SHAPE_INFLATE[shape_type] : 1.0;

  const text_bbox = _required_text_bbox(text_elem);
  const icon_w = icon_elem !== null ? _num(pyGet(icon_elem, 'width')) : 0.0;
  const icon_h = icon_elem !== null ? _num(pyGet(icon_elem, 'height')) : 0.0;
  const icon_extra_w = icon_elem !== null ? (_ICON_LEFT_PAD + icon_w + _ICON_TEXT_GAP) : 0.0;

  const required_w = text_bbox.width * inflate + 2.0 * _PAD_W + icon_extra_w;
  const required_h = text_bbox.height * inflate + 2.0 * _PAD_H;

  const cur_w = _num(pyGet(shape, 'width'));
  const cur_h = _num(pyGet(shape, 'height'));
  const cur_x = _num(pyGet(shape, 'x'));
  const cur_y = _num(pyGet(shape, 'y'));

  const new_w = pyMaxN(cur_w, ceil(required_w));
  const new_h = pyMaxN(cur_h, ceil(required_h));

  const resized = new_w !== cur_w || new_h !== cur_h;

  // Store originals before mutation so we can revert if expansion
  // introduces overlaps with neighbours.
  if (resized && original_dims !== null) {
    const shape_orig: Dict = {
      x: cur_x, y: cur_y,
      width: cur_w, height: cur_h,
    };
    for (const key of ['x', 'y', 'width', 'height']) markF(shape_orig, key, true); // _num() -> float
    original_dims[pyGetItem(shape, 'id') as string] = shape_orig;
    const text_orig: Dict = {
      x: pyGet(text_elem, 'x'),
      y: pyGet(text_elem, 'y'),
      width: pyGet(text_elem, 'width'),
      height: pyGet(text_elem, 'height'),
    };
    for (const key of ['x', 'y', 'width', 'height']) copyF(text_elem, key, text_orig, key);
    original_dims[pyGetItem(text_elem, 'id') as string] = text_orig;
    if (icon_elem !== null) {
      const icon_orig: Dict = {
        x: pyGet(icon_elem, 'x'),
        y: pyGet(icon_elem, 'y'),
        width: pyGet(icon_elem, 'width'),
        height: pyGet(icon_elem, 'height'),
      };
      for (const key of ['x', 'y', 'width', 'height']) copyF(icon_elem, key, icon_orig, key);
      original_dims[pyGetItem(icon_elem, 'id') as string] = icon_orig;
    }
  }

  // Center-invariant growth: shift origin by -Δ/2.
  const dw = new_w - cur_w;
  const dh = new_h - cur_h;
  shape.x = cur_x - dw / 2.0;
  shape.y = cur_y - dh / 2.0;
  shape.width = new_w;
  shape.height = new_h;
  // max(float, math.ceil(...)) keeps the float unless the int is larger.
  markF(shape, 'x', true);
  markF(shape, 'y', true);
  markF(shape, 'width', !(ceil(required_w) > cur_w));
  markF(shape, 'height', !(ceil(required_h) > cur_h));

  if (icon_elem !== null) {
    icon_elem.x = (shape.x as number) + _ICON_LEFT_PAD;
    icon_elem.y = (shape.y as number) + pyMaxN(0.0, ((shape.height as number) - icon_h) / 2.0);
    markF(icon_elem, 'x', true);
    markF(icon_elem, 'y', true);
  }

  // Re-center bound text inside the (possibly enlarged) shape, keeping the
  // text's own required bbox.
  const text_w = ceil(text_bbox.width);
  const text_h = ceil(text_bbox.height);
  let shape_center_x: number;
  const sx = shape.x as number;
  const sy = shape.y as number;
  const sw = shape.width as number;
  const sh = shape.height as number;
  if (icon_elem !== null) {
    const content_left = (icon_elem.x as number) + icon_w + _ICON_TEXT_GAP;
    const content_right = sx + sw - _PAD_W;
    if (content_right > content_left) {
      shape_center_x = content_left + (content_right - content_left) / 2.0;
    } else {
      shape_center_x = sx + sw / 2.0;
    }
  } else {
    shape_center_x = sx + sw / 2.0;
  }
  const shape_center_y = sy + sh / 2.0;
  text_elem.x = shape_center_x - text_w / 2.0;
  text_elem.y = shape_center_y - text_h / 2.0;
  text_elem.width = text_w;
  text_elem.height = text_h;
  markF(text_elem, 'x', true);
  markF(text_elem, 'y', true);
  markF(text_elem, 'width', false); // math.ceil -> int
  markF(text_elem, 'height', false);
  return null;
}

/**
 * Expand a standalone text element's bbox to hold its text, preserving its
 * top-left origin.
 */
export function _fit_standalone_text(text_elem: Dict): null {
  const text_bbox = _required_text_bbox(text_elem);
  const cur_w = _float(pyOr(pyGet(text_elem, 'width', 0), 0));
  const cur_h = _float(pyOr(pyGet(text_elem, 'height', 0), 0));
  const new_w = pyMaxN(cur_w, ceil(text_bbox.width));
  const new_h = pyMaxN(cur_h, ceil(text_bbox.height));
  text_elem.width = new_w;
  text_elem.height = new_h;
  markF(text_elem, 'width', !(ceil(text_bbox.width) > cur_w));
  markF(text_elem, 'height', !(ceil(text_bbox.height) > cur_h));
  return null;
}

/** Return True if the axis-aligned bboxes of two elements intersect. */
export function _bbox_overlap(a: Dict, b: Dict, tol = 2.0): boolean {
  let ax: number, ay: number, aw: number, ah: number, bx: number, by: number, bw: number, bh: number;
  try {
    ax = _float(pyOr(pyGet(a, 'x', 0), 0));
    ay = _float(pyOr(pyGet(a, 'y', 0), 0));
    aw = _float(pyOr(pyGet(a, 'width', 0), 0));
    ah = _float(pyOr(pyGet(a, 'height', 0), 0));
    bx = _float(pyOr(pyGet(b, 'x', 0), 0));
    by = _float(pyOr(pyGet(b, 'y', 0), 0));
    bw = _float(pyOr(pyGet(b, 'width', 0), 0));
    bh = _float(pyOr(pyGet(b, 'height', 0), 0));
  } catch {
    return false;
  }
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

export function _is_group_background(eid: string, semantic_id = ''): boolean {
  const key = pyOr(semantic_id, eid);
  return key.endsWith(BACKGROUND_SUFFIX) || key.startsWith('group_') || key.startsWith('g_');
}

export function _is_group_frame_element(eid: string, semantic_id: string, id_map: Record<string, string>): boolean {
  const key = pyOr(semantic_id, eid);
  return _is_group_background(eid, semantic_id) || (
    truthy(key) && hasKey(id_map, companion_id(key, TITLE_SUFFIX))
  );
}

export function _translate_element(elem: Dict, dx = 0.0, dy = 0.0): null {
  elem.x = _num(pyGet(elem, 'x')) + dx;
  elem.y = _num(pyGet(elem, 'y')) + dy;
  markF(elem, 'x', true);
  markF(elem, 'y', true);
  return null;
}

function _getById(mapping: Record<string, string>, key: unknown): string | null {
  return hasKey(mapping, key) ? mapping[key as string] : null;
}

export function _translate_related(
  shape: Dict,
  dx: number,
  dy: number,
  by_id: Record<string, Dict>,
  shape_to_text: Record<string, string>,
  shape_to_icon: Record<string, string>,
): null {
  _translate_element(shape, dx, dy);
  for (const related_id of [_getById(shape_to_text, pyGet(shape, 'id')), _getById(shape_to_icon, pyGet(shape, 'id'))]) {
    const related = truthy(related_id) ? (pyGet(by_id, related_id) as Dict | null) : null;
    if (related !== null) {
      _translate_element(related, dx, dy);
    }
  }
  return null;
}

export function _horizontal_overlap_amount(a: Dict, b: Dict): number {
  const ax = _num(pyGet(a, 'x'));
  const aw = _num(pyGet(a, 'width'));
  const bx = _num(pyGet(b, 'x'));
  const bw = _num(pyGet(b, 'width'));
  return pyMinN(ax + aw, bx + bw) - pyMaxN(ax, bx);
}

export function _vertical_overlap_amount(a: Dict, b: Dict): number {
  const ay = _num(pyGet(a, 'y'));
  const ah = _num(pyGet(a, 'height'));
  const by = _num(pyGet(b, 'y'));
  const bh = _num(pyGet(b, 'height'));
  return pyMinN(ay + ah, by + bh) - pyMaxN(ay, by);
}

function _origOr(original_dims: Record<string, Dict>, elem: Dict): Dict {
  const id = pyGet(elem, 'id');
  return hasKey(original_dims, id) ? original_dims[id as string] : elem;
}

/**
 * Resolve small container overlaps by shifting related geometry along the
 * axis with the smaller penetration (preferring the original row/column).
 */
export function _resolve_container_overlaps(
  candidates: Dict[],
  original_dims: Record<string, Dict>,
  by_id: Record<string, Dict>,
  shape_to_text: Record<string, string>,
  shape_to_icon: Record<string, string>,
  gap = 8.0,
): null {
  const rounds = pyMaxN(6, 2 * candidates.length);
  for (let round = 0; round < rounds; round += 1) {
    let changed = false;
    for (let i = 0; i < candidates.length; i += 1) {
      const a = candidates[i];
      if (!isContainerType(pyGet(a, 'type'))) {
        continue;
      }
      for (const b of candidates.slice(i + 1)) {
        if (!isContainerType(pyGet(b, 'type'))) {
          continue;
        }
        if (!_bbox_overlap(a, b, 0.0)) {
          continue;
        }

        const overlap_x = _horizontal_overlap_amount(a, b);
        const overlap_y = _vertical_overlap_amount(a, b);
        if (overlap_x <= 0 || overlap_y <= 0) {
          continue;
        }

        const original_a = _origOr(original_dims, a);
        const original_b = _origOr(original_dims, b);
        const same_row = Math.abs(
          _num(pyGet(original_a, 'y')) + _num(pyGet(original_a, 'height')) / 2
          - _num(pyGet(original_b, 'y')) - _num(pyGet(original_b, 'height')) / 2,
        ) < 2.0;
        const same_column = Math.abs(
          _num(pyGet(original_a, 'x')) + _num(pyGet(original_a, 'width')) / 2
          - _num(pyGet(original_b, 'x')) - _num(pyGet(original_b, 'width')) / 2,
        ) < 2.0;
        let a_key: number;
        let b_key: number;
        let move: number;
        let axis: 'x' | 'y';
        // Prefer the original row/column when clear.
        if (same_row || (!same_column && overlap_x <= overlap_y)) {
          a_key = _num(pyGet(original_a, 'x')) + _num(pyGet(original_a, 'width')) / 2.0;
          b_key = _num(pyGet(original_b, 'x')) + _num(pyGet(original_b, 'width')) / 2.0;
          move = overlap_x + gap;
          axis = 'x';
        } else {
          a_key = _num(pyGet(original_a, 'y')) + _num(pyGet(original_a, 'height')) / 2.0;
          b_key = _num(pyGet(original_b, 'y')) + _num(pyGet(original_b, 'height')) / 2.0;
          move = overlap_y + gap;
          axis = 'y';
        }

        const [first, second] = a_key <= b_key ? [a, b] : [b, a];
        if (same_row && axis === 'x') {
          const original_first = _origOr(original_dims, first);
          const original_second = _origOr(original_dims, second);
          const original_gap = _num(pyGet(original_second, 'x')) - (
            _num(pyGet(original_first, 'x')) + _num(pyGet(original_first, 'width'))
          );
          // Preserve the layout's intended connector-label room.
          move = _num(pyGet(first, 'x')) + _num(pyGet(first, 'width')) + pyMaxN(gap, 24.0, original_gap) - _num(pyGet(second, 'x'));
        } else if (same_column && axis === 'y') {
          move = _num(pyGet(first, 'y')) + _num(pyGet(first, 'height')) + gap - _num(pyGet(second, 'y'));
        }
        const forward: [number, number] = axis === 'x' ? [move, 0.0] : [0.0, move];
        const backward: [number, number] = axis === 'x' ? [-move, 0.0] : [0.0, -move];

        if (hasKey(original_dims, pyGet(second, 'id'))) {
          _translate_related(second, ...forward, by_id, shape_to_text, shape_to_icon);
          changed = true;
        } else if (hasKey(original_dims, pyGet(first, 'id'))) {
          _translate_related(first, ...backward, by_id, shape_to_text, shape_to_icon);
          changed = true;
        }
      }
    }
    if (!changed) {
      break;
    }
  }
  return null;
}

/**
 * Enforce shape_width ≥ bound_text_width for every container shape.
 *
 * Returns a deep-copied manifest. After all expansions, overlaps introduced
 * by the fitter are resolved, and remaining ones reverted to the original
 * dimensions.
 */
export function fit_shape_sizes_to_text(manifest: Dict): Dict {
  manifest = pyDeepcopy(manifest);
  const elements = pyOr(pyGet(manifest, 'elements'), []) as Dict[];
  const by_id: Record<string, Dict> = {};
  for (const e of elements) {
    if (isDict(e) && truthy(pyGet(e, 'id'))) by_id[e.id as string] = e;
  }
  const id_map = id_map_from_manifest(manifest);
  const semantic_by_render_id = reverse_id_map(id_map);

  // Track original dimensions so we can revert overlaps.
  const original_dims: Record<string, Dict> = {};
  const icon_by_container = _map_icons_to_containers(elements);
  const shape_to_text: Record<string, string> = {};
  for (const e of elements) {
    if (isDict(e) && truthy(pyGet(e, 'containerId'))) {
      shape_to_text[e.containerId as string] = pyGetItem(e, 'id') as string;
    }
  }
  const shape_to_icon: Record<string, string> = {};
  for (const [shape_id, icon] of pyItems(icon_by_container)) {
    if (isDict(icon) && truthy(pyGet(icon, 'id'))) {
      shape_to_icon[shape_id as string] = icon.id as string;
    }
  }

  for (const e of elements) {
    if (!isDict(e)) {
      continue;
    }
    const etype = pyGet(e, 'type');

    if (isContainerType(etype)) {
      const eid = pyGet(e, 'id', '') as string;
      if (_is_group_frame_element(eid, pyGet(semantic_by_render_id, eid, '') as string, id_map)) {
        continue;
      }
      const text_elem = _find_bound_text(e, by_id);
      if (text_elem !== null) {
        _fit_container_to_text(e, text_elem, (pyGet(icon_by_container, pyGetItem(e, 'id')) as Dict | null), original_dims);
      }
      continue;
    }

    if (etype === 'text') {
      // Text bound to a container was already resized above.
      if (truthy(pyGet(e, 'containerId'))) {
        continue;
      }
      _fit_standalone_text(e);
      continue;
    }

    // arrow / image / line / etc. — untouched.
  }

  // ── Safety valve: revert expansions that introduced overlaps ──
  const candidates: Dict[] = [];
  for (const e of elements) {
    if (!isDict(e)) {
      continue;
    }
    const etype = pyGet(e, 'type');
    if (etype === 'arrow' || etype === 'freedraw' || etype === 'line' || etype === 'image') {
      continue;
    }
    if (etype === 'text' && truthy(pyGet(e, 'containerId'))) {
      continue;
    }
    const eid = pyGet(e, 'id', '') as string;
    if (_is_group_frame_element(eid, pyGet(semantic_by_render_id, eid, '') as string, id_map)) {
      continue;
    }
    candidates.push(e);
  }

  _resolve_container_overlaps(candidates, original_dims, by_id, shape_to_text, shape_to_icon);

  // Find overlaps where at least one element was modified by the fitter.
  // Python iterates this set in hash order; every revert writes values that
  // depend only on its own id, so iteration order does not affect the result.
  const revert_ids = new Set<string>();
  const n = candidates.length;
  for (let i = 0; i < n; i += 1) {
    const a = candidates[i];
    for (let j = i + 1; j < n; j += 1) {
      const b = candidates[j];
      if (!_bbox_overlap(a, b)) {
        continue;
      }
      const a_id = pyGet(a, 'id', '') as string;
      const b_id = pyGet(b, 'id', '') as string;
      const a_modified = hasKey(original_dims, a_id);
      const b_modified = hasKey(original_dims, b_id);
      if (a_modified || b_modified) {
        if (a_modified) {
          revert_ids.add(a_id);
        }
        if (b_modified) {
          revert_ids.add(b_id);
        }
      }
    }
  }

  if (revert_ids.size) {
    const logger = getLogger('evodesign.agentic_system.render_engine.excalidraw.shape_size_fitter');
    logger.warning(
      'shape_size_fitter: %d element(s) reverted to original dims to avoid overlaps: %s',
      revert_ids.size,
      pySorted([...revert_ids]),
    );
    const restore = (target: Dict, orig: Dict) => {
      for (const [key, val] of Object.entries(orig)) {
        if (val !== null && val !== undefined) {
          target[key] = val;
          copyF(orig, key, target, key);
        }
      }
    };
    for (const eid of revert_ids) {
      const elem = hasKey(by_id, eid) ? by_id[eid] : null;
      if (elem === null) {
        continue;
      }
      restore(elem, original_dims[eid]);
      // When a container shape is reverted, also revert its bound text.
      if (hasKey(shape_to_text, eid)) {
        const text_id = shape_to_text[eid];
        const text_elem = hasKey(by_id, text_id) ? by_id[text_id] : null;
        const text_orig = hasKey(original_dims, text_id) ? original_dims[text_id] : null;
        if (text_elem !== null && text_orig !== null) {
          restore(text_elem, text_orig);
        }
      }
      if (hasKey(shape_to_icon, eid)) {
        const icon_id = shape_to_icon[eid];
        const icon_elem = hasKey(by_id, icon_id) ? by_id[icon_id] : null;
        const icon_orig = hasKey(original_dims, icon_id) ? original_dims[icon_id] : null;
        if (icon_elem !== null && icon_orig !== null) {
          restore(icon_elem, icon_orig);
        }
      }
    }
  }

  manifest.elements = elements;
  sync_node_icons(manifest);
  return manifest;
}
