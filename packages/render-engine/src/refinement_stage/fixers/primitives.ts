// Ported from evodesign/agentic_system/refinement_stage/fixers/primitives.py — keep in sync.
//
// Atomic edit op handlers — one function per EditOpName.
//
// Every function takes the full manifest plus the EditOp ``id`` and ``payload``
// fields, then mutates the manifest in place. Some ops intentionally ignore an
// empty payload but keep the shared dispatcher signature. Returns
// ``(applied: bool, error: str | None)``.
//
// These are intentionally tiny so the dispatcher in ``apply_edits.py`` can
// route a single ``EditOp`` with one switch.
//
// Excalidraw conventions used here:
// - Elements live in ``manifest["elements"]`` (a list).
// - Each element has a unique ``id``. Lookup is O(N), which is acceptable for
//   the small edit batches emitted by one refinement iteration.
// - ``boundElements`` is a list of ``{"id": ..., "type": ...}`` dicts.
// - ``startBinding`` / ``endBinding`` on arrows are dicts with ``elementId``,
//   ``focus``, ``gap``.
// - Fractional ``index`` strings (e.g. ``"a00003"``) order rendering bottom→top.

import { copyF, markF } from '../../py/float_marks.ts';
import { set_node_icon, sync_node_icons } from '../../common/node_icons.ts';
import { pyGet } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { pyFloatParse, pyInt } from '../../py/number.ts';
import { pySorted } from '../../py/sort.ts';
import { floatRepr, pyRepr } from '../../py/str.ts';
import { isDict, isList, isStr, pyTypeName, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;
export type OpResult = [boolean, string | null];
export type OpHandler = (manifest: Dict, element_id: string, payload: Dict) => OpResult;

/** ``float(value)`` with Python's TypeError/ValueError. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${pyTypeName(value)}'`);
}

/** ``int(value)`` with Python's TypeError/ValueError. */
function _int(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyInt(value);
  throw new PyTypeError(`int() argument must be a string, a bytes-like object or a real number, not '${pyTypeName(value)}'`);
}

function _isConversionError(error: unknown): boolean {
  return error instanceof PyTypeError || error instanceof ValueError || error instanceof TypeError;
}

function _has(mapping: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(mapping, key);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function _find_element(elements: unknown[], element_id: string): Dict | null {
  for (const elem of elements) {
    if (isDict(elem) && pyEq(pyGet(elem, 'id'), element_id)) {
      return elem;
    }
  }
  return null;
}

export function _elements_list(manifest: Dict): [Dict[] | null, string | null] {
  const elements = pyGet(manifest, 'elements');
  if (!isList(elements)) {
    return [null, 'manifest has no elements list'];
  }
  return [elements as Dict[], null];
}

export function _require_element(
  manifest: Dict,
  element_id: string,
): [Dict[] | null, Dict | null, string | null] {
  const [elements, error] = _elements_list(manifest);
  if (error) {
    return [null, null, error];
  }
  const elem = _find_element(elements!, element_id);
  if (elem === null) {
    return [elements, null, `element ${pyRepr(element_id)} not found`];
  }
  return [elements, elem, null];
}

export function _remove_bound_ref(holder: Dict, bound_id: string): boolean {
  const bound = pyGet(holder, 'boundElements');
  if (!isList(bound)) {
    return false;
  }
  const new_bound = bound.filter((item) => !(isDict(item) && pyEq(pyGet(item, 'id'), bound_id)));
  if (new_bound.length === bound.length) {
    return false;
  }
  holder.boundElements = new_bound;
  _bump_version(holder);
  return true;
}

/**
 * Excalidraw uses ``version`` for change tracking. Bumping is harmless
 * when missing (renderer treats absent as 1).
 */
export function _bump_version(elem: Dict): null {
  try {
    const current = pyGet(elem, 'version', 1);
    elem.version = _int(truthy(current) ? current : 1) + 1;
  } catch (error) {
    if (!_isConversionError(error)) throw error;
    elem.version = 2;
  }
  markF(elem, 'version', false); // int(...) + 1
  return null;
}

export function _num(value: unknown, default_ = 0.0): number {
  try {
    return _float(value);
  } catch (error) {
    if (_isConversionError(error)) return default_;
    throw error;
  }
}

export function _bound_text_elements(elements: unknown[], container: Dict): Dict[] {
  const by_id = new Map<unknown, Dict>();
  for (const elem of elements) {
    if (isDict(elem) && truthy(pyGet(elem, 'id'))) by_id.set(pyGet(elem, 'id'), elem);
  }
  const container_id = pyGet(container, 'id');
  const seen = new Set<unknown>();
  const texts: Dict[] = [];

  const bounds = pyGet(container, 'boundElements');
  for (const bound of (truthy(bounds) ? bounds : []) as unknown[]) {
    if (!isDict(bound) || pyGet(bound, 'type') !== 'text') {
      continue;
    }
    const text_id = pyGet(bound, 'id');
    const text_elem = by_id.get(text_id);
    if (
      isDict(text_elem)
      && pyGet(text_elem, 'type') === 'text'
      && !seen.has(pyGet(text_elem, 'id'))
    ) {
      texts.push(text_elem);
      seen.add(text_elem.id);
    }
  }

  for (const elem of elements) {
    if (
      isDict(elem)
      && pyGet(elem, 'type') === 'text'
      && pyEq(pyGet(elem, 'containerId'), container_id)
      && !seen.has(pyGet(elem, 'id'))
    ) {
      texts.push(elem);
      seen.add(elem.id);
    }
  }

  return texts;
}

export function _move_bound_text(elements: unknown[], container: Dict, dx: number, dy: number): null {
  for (const text_elem of _bound_text_elements(elements, container)) {
    text_elem.x = _num(pyGet(text_elem, 'x')) + dx;
    text_elem.y = _num(pyGet(text_elem, 'y')) + dy;
    markF(text_elem, 'x', true); // _num() -> float
    markF(text_elem, 'y', true);
    _bump_version(text_elem);
  }
  return null;
}

export function _recenter_bound_text(elements: unknown[], container: Dict): null {
  const x = _num(pyGet(container, 'x'));
  const y = _num(pyGet(container, 'y'));
  const width = _num(pyGet(container, 'width'));
  const height = _num(pyGet(container, 'height'));
  for (const text_elem of _bound_text_elements(elements, container)) {
    const text_width = _num(pyGet(text_elem, 'width'));
    const text_height = _num(pyGet(text_elem, 'height'));
    text_elem.x = x + (width - text_width) / 2.0;
    text_elem.y = y + (height - text_height) / 2.0;
    markF(text_elem, 'x', true);
    markF(text_elem, 'y', true);
    _bump_version(text_elem);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Op handlers
// ---------------------------------------------------------------------------

export const _ARROW_GEOMETRY_ERROR = (
  'arrow geometry is not directly editable: an Excalidraw arrow\'s shape is '
  + 'baked into its absolute x/y/points polyline, so translating or resizing it '
  + 'detaches it from the shapes it connects. Arrows follow their endpoints '
  + 'through the arrow re-route pass instead.'
);

/** Parse *value* as a finite float; NaN/Inf would poison every geometry check. */
export function _finite_float(value: unknown, name: string): [number | null, string | null] {
  if (typeof value === 'boolean') {
    return [null, `${name} must be a number, got ${pyRepr(value)}`];
  }
  let number: number;
  try {
    number = _float(value);
  } catch (error) {
    if (_isConversionError(error)) return [null, `${name}: ${(error as Error).message}`];
    throw error;
  }
  if (!Number.isFinite(number)) {
    return [null, `${name} must be finite, got ${pyRepr(value)}`];
  }
  return [number, null];
}

export function op_set_position(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [elements, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  if (pyGet(elem!, 'type') === 'arrow') {
    return [false, _ARROW_GEOMETRY_ERROR];
  }
  if (!_has(payload, 'x') || !_has(payload, 'y')) {
    return [false, 'set_position requires x and y in payload'];
  }
  // Validate both coordinates before mutating so a bad y never leaves a
  // half-applied move behind.
  const [x, x_error] = _finite_float(payload.x, 'x');
  const [y, y_error] = _finite_float(payload.y, 'y');
  if (x_error || y_error) {
    return [false, `invalid x/y: ${x_error || y_error}`];
  }
  const old_x = _num(pyGet(elem!, 'x'));
  const old_y = _num(pyGet(elem!, 'y'));
  elem!.x = x;
  elem!.y = y;
  markF(elem, 'x', true); // _finite_float() -> float
  markF(elem, 'y', true);
  _move_bound_text(elements!, elem!, x! - old_x, y! - old_y);
  sync_node_icons(manifest, element_id);
  _bump_version(elem!);
  return [true, null];
}

export function op_set_size(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [elements, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  if (pyGet(elem!, 'type') === 'arrow') {
    return [false, _ARROW_GEOMETRY_ERROR];
  }
  if (!_has(payload, 'width') || !_has(payload, 'height')) {
    return [false, 'set_size requires width and height in payload'];
  }
  const [w, w_error] = _finite_float(payload.width, 'width');
  const [h, h_error] = _finite_float(payload.height, 'height');
  if (w_error || h_error) {
    return [false, `invalid w/h: ${w_error || h_error}`];
  }
  if (w! <= 0 || h! <= 0) {
    return [false, `non-positive width/height (w=${floatRepr(w!)}, h=${floatRepr(h!)})`];
  }
  elem!.width = w;
  elem!.height = h;
  markF(elem, 'width', true); // _finite_float() -> float
  markF(elem, 'height', true);
  _recenter_bound_text(elements!, elem!);
  sync_node_icons(manifest, element_id);
  _bump_version(elem!);
  return [true, null];
}

const _STYLE_KEYS = new Set([
  'backgroundColor',
  'strokeColor',
  'strokeWidth',
  'strokeStyle',
  'fillStyle',
  'roughness',
  'opacity',
  'fontSize',
  'fontFamily',
  'textAlign',
  'verticalAlign',
]);

export function op_set_style(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }

  // Allow only known style keys to avoid accidental free-form mutation.
  const unknown_keys = pySorted(Object.keys(payload).filter((key) => !_STYLE_KEYS.has(key)));
  if (unknown_keys.length) {
    return [false, `set_style payload has unknown style keys: ${pyRepr(unknown_keys)}`];
  }
  let applied_any = false;
  for (const [key, value] of Object.entries(payload)) {
    elem![key] = value;
    copyF(payload, key, elem, key);
    applied_any = true;
  }
  if (!applied_any) {
    return [false, 'set_style payload had no recognised style keys'];
  }
  const container_id = pyGet(elem!, 'containerId');
  sync_node_icons(manifest, (truthy(container_id) ? container_id : element_id) as string);
  _bump_version(elem!);
  return [true, null];
}

export function op_set_text(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  const text = pyGet(payload, 'text');
  if (!isStr(text)) {
    return [false, 'set_text requires payload.text as a string'];
  }
  if (pyGet(elem!, 'type') !== 'text') {
    return [false, `set_text targets non-text element type=${pyRepr(pyGet(elem!, 'type'))}`];
  }
  elem!.text = text;
  elem!.originalText = text;
  _bump_version(elem!);
  return [true, null];
}

export function op_delete_element(manifest: Dict, element_id: string, _payload: Dict): OpResult {
  const [elements, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }

  // --- Safety checks: refuse to delete connected elements ---
  // Idempotent: already deleted is always safe.
  if (!truthy(pyGet(elem!, 'isDeleted'))) {
    const block_reasons: string[] = [];

    // 1. Bound text/icon inside a container — deleting orphans the label.
    if (truthy(pyGet(elem!, 'containerId'))) {
      block_reasons.push(`element is bound to container ${pyRepr(elem!.containerId)}`);
    }

    // 2. Has bound children (text labels, arrows attached to it).
    const bound = pyGet(elem!, 'boundElements');
    if (isList(bound) && bound.length) {
      const bound_ids = bound.filter((b) => isDict(b)).map((b) => pyGet(b, 'id'));
      block_reasons.push(`element has ${bound_ids.length} bound element(s): ${pyRepr(bound_ids)}`);
    }

    // 3. Arrows whose start/end point to this element.
    for (const other of elements!) {
      if (!isDict(other) || pyGet(other, 'type') !== 'arrow') {
        continue;
      }
      if (truthy(pyGet(other, 'isDeleted'))) {
        continue;
      }
      for (const side of ['start', 'end']) {
        const binding = pyGet(other, `${side}Binding`);
        if (isDict(binding) && pyEq(pyGet(binding, 'elementId'), element_id)) {
          block_reasons.push(`arrow ${pyRepr(pyGet(other, 'id'))} has ${side}Binding pointing to this element`);
        }
      }
    }

    if (block_reasons.length) {
      return [false, `refusing to delete connected element ${pyRepr(element_id)}: ${block_reasons.join('; ')}`];
    }
  }

  if (truthy(pyGet(elem!, 'isDeleted'))) {
    return [false, null];
  }

  // --- Proceed with soft-delete ---
  elem!.isDeleted = true;
  _bump_version(elem!);

  // Remove this id from anyone's boundElements list.
  for (const other of elements!) {
    if (!isDict(other)) {
      continue;
    }
    _remove_bound_ref(other, element_id);
  }

  // Clear startBinding/endBinding on arrows that point to this element.
  for (const other of elements!) {
    if (!isDict(other) || pyGet(other, 'type') !== 'arrow') {
      continue;
    }
    for (const side of ['start', 'end']) {
      const binding = pyGet(other, `${side}Binding`);
      if (isDict(binding) && pyEq(pyGet(binding, 'elementId'), element_id)) {
        other[`${side}Binding`] = null;
        _bump_version(other);
      }
    }
  }

  return [true, null];
}

export function op_clear_arrow_binding(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [elements, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  if (pyGet(elem!, 'type') !== 'arrow') {
    return [false, `clear_arrow_binding targets non-arrow type=${pyRepr(pyGet(elem!, 'type'))}`];
  }
  const side = pyGet(payload, 'side');
  if (side !== 'start' && side !== 'end') {
    return [false, 'clear_arrow_binding requires payload.side ∈ {start, end}'];
  }
  const binding_key = `${side}Binding`;
  if (pyGet(elem!, binding_key) === null) {
    // Already cleared — idempotent no-op.
    return [false, null];
  }
  const current = pyGet(elem!, binding_key);
  const target_id = isDict(current) ? pyGet(truthy(elem![binding_key]) ? elem![binding_key] : {}, 'elementId') : null;
  elem![binding_key] = null;
  _bump_version(elem!);

  // Strip the back-ref on the previously-bound shape, if any.
  if (truthy(target_id)) {
    const target = _find_element(elements!, target_id as string);
    if (target !== null) {
      _remove_bound_ref(target, element_id);
    }
  }
  return [true, null];
}

export function op_clear_container_binding(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [elements, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  if (pyGet(elem!, 'type') !== 'text') {
    return [false, `clear_container_binding targets non-text type=${pyRepr(pyGet(elem!, 'type'))}`];
  }

  const current_container_id = pyGet(elem!, 'containerId');
  if (!truthy(current_container_id)) {
    return [false, null];
  }

  const expected_container_id = pyGet(payload, 'container_id');
  if (expected_container_id !== null && !pyEq(expected_container_id, current_container_id)) {
    return [false, (
      `containerId changed from expected ${pyRepr(expected_container_id)} `
      + `to ${pyRepr(current_container_id)}; refusing stale clear`
    )];
  }

  elem!.containerId = null;
  _bump_version(elem!);

  const target = _find_element(elements!, current_container_id as string);
  if (target !== null) {
    _remove_bound_ref(target, element_id);
  }
  return [true, null];
}

export function op_append_bound_element(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [elements, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  const bound_id = pyGet(payload, 'bound_id');
  const bound_type = pyGet(payload, 'type', 'arrow');
  if (!isStr(bound_id) || !bound_id) {
    return [false, 'append_bound_element requires payload.bound_id (str)'];
  }
  if (bound_type !== 'arrow' && bound_type !== 'text') {
    return [false, "append_bound_element type must be 'arrow' or 'text'"];
  }

  // Verify the referenced element exists; otherwise the back-ref is bogus.
  if (_find_element(elements!, bound_id) === null) {
    return [false, `bound_id ${pyRepr(bound_id)} does not exist; refusing to add dangling ref`];
  }

  let bound = pyGet(elem!, 'boundElements');
  if (!isList(bound)) {
    bound = [];
    elem!.boundElements = bound;
  }

  // Idempotent — skip if already present.
  if ((bound as unknown[]).some((b) => isDict(b) && pyEq(pyGet(b, 'id'), bound_id))) {
    return [false, null];
  }

  (bound as unknown[]).push({ id: bound_id, type: bound_type });
  _bump_version(elem!);
  return [true, null];
}

export function op_remove_bound_element(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  const bound_id = pyGet(payload, 'bound_id');
  if (!isStr(bound_id) || !bound_id) {
    return [false, 'remove_bound_element requires payload.bound_id (str)'];
  }
  if (!isList(pyGet(elem!, 'boundElements'))) {
    return [false, null];
  }
  if (_remove_bound_ref(elem!, bound_id)) {
    return [true, null];
  }
  return [false, null];
}

export function op_set_index(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const [, elem, error] = _require_element(manifest, element_id);
  if (error) {
    return [false, error];
  }
  const new_index = pyGet(payload, 'index');
  if (!isStr(new_index) || !new_index) {
    return [false, 'set_index requires payload.index (str fractional index)'];
  }
  elem!.index = new_index;
  _bump_version(elem!);
  return [true, null];
}

// ---------------------------------------------------------------------------
// Dispatch table — used by apply_edits.py
// ---------------------------------------------------------------------------

export function op_set_icon(manifest: Dict, element_id: string, payload: Dict): OpResult {
  const keys = Object.keys(payload);
  if (!(keys.length === 1 && keys[0] === 'name') || !isStr(pyGet(payload, 'name'))) {
    return [false, 'set_icon requires only payload.name (bundled icon name)'];
  }
  try {
    return [set_node_icon(manifest, element_id, payload.name as string), null];
  } catch (error) {
    if (error instanceof ValueError) return [false, error.message];
    throw error;
  }
}

export const OP_HANDLERS: Record<string, OpHandler> = {
  set_icon: op_set_icon,
  set_position: op_set_position,
  set_size: op_set_size,
  set_style: op_set_style,
  set_text: op_set_text,
  delete_element: op_delete_element,
  clear_arrow_binding: op_clear_arrow_binding,
  clear_container_binding: op_clear_container_binding,
  append_bound_element: op_append_bound_element,
  remove_bound_element: op_remove_bound_element,
  set_index: op_set_index,
};

export const __all__ = [
  'OP_HANDLERS',
  'op_set_position',
  'op_set_size',
  'op_set_style',
  'op_set_text',
  'op_delete_element',
  'op_clear_arrow_binding',
  'op_clear_container_binding',
  'op_append_bound_element',
  'op_remove_bound_element',
  'op_set_index',
];
