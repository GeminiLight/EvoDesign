// Ported from evodesign/agentic_system/generation_stage/styling/schemas.py — keep in sync.
// Styling-stage output contract validation.
//
// Python sets become ``Set<string>``; wherever their order reaches output
// (error messages) Python sorts first, and so does this port.

import {
  BACKGROUND_SUFFIX,
  ICON_SUFFIX,
  TITLE_SUFFIX,
  companion_base_id,
  companion_id,
  drop_canvas_decorations,
} from '../../common/semantic_ids.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { TLDrawColorValidator, TLDrawFillValidator, TLDrawShapeValidator } from '../../common/tldraw_utils.ts';
import { normalize_canvas_library } from '../../canvas_runtime.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pySorted } from '../../py/sort.ts';
import { pyRepr, pyStrip } from '../../py/str.ts';
import { isDict, pyOr, pyTypeName, truthy } from '../../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.styling.schemas');

/** Raised when Styling output violates the Structure-to-Styling contract. */
export class StylingValidationError extends ValueError {}

export const _HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;
export const _EXCALIDRAW_NATIVE_SHAPES: ReadonlySet<string> = new Set(['rectangle', 'ellipse', 'diamond', 'triangle']);
export const _TLDRAW_TEXT_TYPES: ReadonlySet<string> = new Set(['text']);
export const _TLDRAW_VALID_COLORS: ReadonlySet<string> = new Set(TLDrawColorValidator.VALID_COLORS);
export const _TLDRAW_VALID_FILLS: ReadonlySet<string> = new Set(TLDrawFillValidator.VALID_FILLS);
export const _TLDRAW_VALID_SHAPES: ReadonlySet<string> = new Set(TLDrawShapeValidator.VALID_SHAPES);
export const _LAYOUT_OWNED_FIELDS: ReadonlySet<string> = new Set([
  'x',
  'y',
  'w',
  'h',
  'width',
  'height',
  'min_width',
  'min_height',
]);

type Dict = Record<string, unknown>;

/** ``dict.get(key)`` */
function get(d: Dict, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(d, key) ? d[key] : null;
}

/** ``key in dict`` */
function has(d: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(d, key);
}

/** ``value in some_set`` — unhashable values (list/dict/set) raise TypeError like Python. */
function setHas(set: ReadonlySet<string>, value: unknown): boolean {
  if (value !== null && typeof value === 'object') {
    throw new PyTypeError(`unhashable type: '${pyTypeName(value)}'`);
  }
  return set.has(value as string);
}

/** ``for item in value`` for the JSON values a structure field may hold. */
function iterate(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (value instanceof Set) return [...value];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError(`'${pyTypeName(value)}' object is not iterable`);
}

/** Validate Styling output against Structure ids and canvas-specific fields. */
export function validate_styling_instantiation(
  instantiation: unknown,
  structure_instantiation: Dict | null,
  canvas_library = 'excalidraw',
): Dict {
  if (!isDict(instantiation)) {
    throw new StylingValidationError(
      'Styling instantiation must be a JSON object; '
      + `got ${pyTypeName(instantiation)}.`,
    );
  }

  const structure = unwrap_structure_instantiation(structure_instantiation);
  const node_ids = _collect_ids(structure, 'nodes');
  const group_ids = _collect_ids(structure, 'groups');
  const edge_ids = _collect_ids(structure, 'edges');
  const allowed_ids = _allowed_styling_ids(node_ids, group_ids, edge_ids);
  const canvas = _normalise_canvas(canvas_library);
  const group_shells = new Set<string>();
  let decorations: string[];
  [instantiation, decorations] = drop_canvas_decorations(instantiation, allowed_ids);
  const entries = instantiation as Dict;
  if (decorations.length) {
    logger.warning('Styling added undeclared canvas captions %s; dropping them.', decorations);
  }

  for (const [element_id, element_data] of Object.entries(entries)) {
    if (typeof element_id !== 'string' || !pyStrip(element_id)) {
      throw new StylingValidationError(`Styling element id must be a non-empty string; got ${pyRepr(element_id)}.`);
    }
    if (!allowed_ids.has(element_id)) {
      throw new StylingValidationError(`Unknown styling id ${pyRepr(element_id)}; Styling must reuse Structure ids.`);
    }
    if (!isDict(element_data)) {
      throw new StylingValidationError(`Styling entry ${pyRepr(element_id)} must be an object.`);
    }
    _reject_layout_owned_fields(element_id, element_data);

    if (_is_icon_key(element_id)) {
      _validate_icon_entry(element_id, element_data, node_ids);
    } else if (edge_ids.has(element_id)) {
      _validate_edge_entry(element_id, element_data, canvas);
    } else if (element_id.endsWith(TITLE_SUFFIX)) {
      _validate_title_entry(element_id, element_data, canvas);
    } else if (
      canvas === 'excalidraw'
      && group_ids.has(element_id)
      && _entry_type(element_data) === null
      && has(entries, companion_id(element_id, BACKGROUND_SUFFIX))
    ) {
      // Some models repeat the logical group beside its actual surface.
      // Validate that surface separately, then omit the non-rendering
      // shell so Layout does not invent a second box for the same group.
      group_shells.add(element_id);
    } else {
      _validate_shape_entry(element_id, element_data, canvas, group_ids.has(element_id));
    }
  }

  _validate_required_coverage(entries, node_ids, edge_ids, structure);
  if (group_shells.size) {
    const out: Dict = Object.create(null);
    for (const [key, value] of Object.entries(entries)) {
      if (!group_shells.has(key)) out[key] = value;
    }
    return out;
  }
  return entries;
}

export function _normalise_canvas(canvas_library: string): string {
  try {
    return normalize_canvas_library(pyOr(canvas_library, 'excalidraw'));
  } catch (exc) {
    if (exc instanceof ValueError) {
      throw new StylingValidationError(
        `Unknown canvas_library for Styling validation: ${pyRepr(canvas_library)}.`,
      );
    }
    throw exc;
  }
}

export function _collect_ids(structure_instantiation: Dict, field_name: string): Set<string> {
  const ids = new Set<string>();
  iterate(pyOr(get(structure_instantiation, field_name), [])).forEach((item, index) => {
    if (!isDict(item)) {
      throw new StylingValidationError(`Structure field ${field_name}[${index}] must be an object.`);
    }
    const item_id = get(item, 'id');
    if (typeof item_id === 'string' && pyStrip(item_id)) {
      ids.add(item_id);
    }
  });
  return ids;
}

export function _allowed_styling_ids(node_ids: Set<string>, group_ids: Set<string>, edge_ids: Set<string>): Set<string> {
  const allowed = new Set<string>([...node_ids, ...group_ids, ...edge_ids]);
  for (const node_id of node_ids) {
    allowed.add(companion_id(node_id, ICON_SUFFIX));
  }
  for (const group_id of group_ids) {
    allowed.add(companion_id(group_id, BACKGROUND_SUFFIX));
    allowed.add(companion_id(group_id, TITLE_SUFFIX));
  }
  return allowed;
}

export function _validate_required_coverage(
  instantiation: Dict,
  node_ids: Set<string>,
  edge_ids: Set<string>,
  structure: Dict,
): void {
  const missing_nodes = pySorted([...node_ids].filter((node_id) => !has(instantiation, node_id)));
  if (missing_nodes.length) {
    throw new StylingValidationError(
      'Missing styling entries for Structure node ids: ' + missing_nodes.join(', '),
    );
  }

  const missing_edges = pySorted([...edge_ids].filter((edge_id) => !has(instantiation, edge_id)));
  if (missing_edges.length) {
    throw new StylingValidationError(
      'Missing styling entries for Structure edge ids: ' + missing_edges.join(', '),
    );
  }

  for (const group of iterate(pyOr(get(structure, 'groups'), []))) {
    if (!isDict(group)) {
      continue;
    }
    const group_id = get(group, 'id');
    if (typeof group_id !== 'string' || !pyStrip(group_id)) {
      continue;
    }
    if (!has(instantiation, group_id) && !has(instantiation, companion_id(group_id, BACKGROUND_SUFFIX))) {
      throw new StylingValidationError(
        `Missing styling surface for Structure group id ${pyRepr(group_id)}; `
        + "expected group entry or group ':background'.",
      );
    }
    const label = get(group, 'label');
    // Sequence lanes are navigation containers, not repeated headings.
    // Their sole participant header already carries the visible label.
    const members = iterate(pyOr(get(group, 'members'), []));
    const participant_lane = (get(structure, 'chart_type') === 'sequence_diagram'
                              && members.length === 1 && setHas(node_ids, members[0]));
    if (participant_lane) {
      continue;
    }
    if (typeof label === 'string' && pyStrip(label) && !_has_group_title(instantiation, group_id)) {
      throw new StylingValidationError(
        `Missing title styling for labelled Structure group id ${pyRepr(group_id)}.`,
      );
    }
  }
}

export function _has_group_title(instantiation: Dict, group_id: string): boolean {
  const title = get(instantiation, companion_id(group_id, TITLE_SUFFIX));
  if (isDict(title) && _extract_text(title)) {
    return true;
  }
  const group_entry = get(instantiation, group_id);
  if (isDict(group_entry) && _entry_type(group_entry) === 'text' && _extract_text(group_entry)) {
    return true;
  }
  return false;
}

export function _is_icon_key(element_id: string): boolean {
  return element_id.endsWith(ICON_SUFFIX);
}

export function _icon_owner_id(element_id: string): string {
  return pyOr(companion_base_id(element_id), element_id) as string;
}

export function _validate_icon_entry(element_id: string, element_data: Dict, node_ids: Set<string>): void {
  const owner_id = _icon_owner_id(element_id);
  if (!node_ids.has(owner_id)) {
    throw new StylingValidationError(`Icon styling id ${pyRepr(element_id)} must reference a Structure node id.`);
  }
  if (get(element_data, 'type') !== 'icon') {
    throw new StylingValidationError(`Icon styling id ${pyRepr(element_id)} must have type='icon'.`);
  }
  const props = get(element_data, 'props');
  if (!isDict(props) || typeof get(props, 'icon') !== 'string' || !pyStrip(props.icon as string)) {
    throw new StylingValidationError(`Icon styling id ${pyRepr(element_id)} must include props.icon.`);
  }
}

export function _reject_layout_owned_fields(element_id: string, element_data: Dict): void {
  const top_level = pySorted(Object.keys(element_data).filter((key) => _LAYOUT_OWNED_FIELDS.has(key)));
  if (top_level.length) {
    throw new StylingValidationError(
      `Styling entry ${pyRepr(element_id)} must not include layout-owned fields: `
      + top_level.join(', ')
      + '. Layout owns geometry.',
    );
  }

  const props = get(element_data, 'props');
  if (isDict(props)) {
    const prop_fields = pySorted(Object.keys(props).filter((key) => _LAYOUT_OWNED_FIELDS.has(key)));
    if (prop_fields.length) {
      throw new StylingValidationError(
        `Styling entry ${pyRepr(element_id)} props must not include layout-owned fields: `
        + prop_fields.join(', ')
        + '. Layout owns geometry.',
      );
    }
  }
}

export function _validate_edge_entry(element_id: string, element_data: Dict, canvas: string): void {
  if (canvas === 'excalidraw') {
    const allowed_keys = new Set(['strokeColor']);
    const extra_keys = pySorted(Object.keys(element_data).filter((key) => !allowed_keys.has(key)));
    if (extra_keys.length) {
      throw new StylingValidationError(
        `Excalidraw edge styling ${pyRepr(element_id)} must be color-only; unexpected keys: `
        + extra_keys.join(', '),
      );
    }
    _require_hex_color(element_id, get(element_data, 'strokeColor'), 'strokeColor');
    return;
  }

  const allowed_keys = new Set(['props']);
  const extra_keys = pySorted(Object.keys(element_data).filter((key) => !allowed_keys.has(key)));
  if (extra_keys.length) {
    throw new StylingValidationError(
      `TLDraw edge styling ${pyRepr(element_id)} must be props.color-only; unexpected keys: `
      + extra_keys.join(', '),
    );
  }
  const props = _require_props(element_id, element_data);
  _require_tldraw_color(element_id, get(props, 'color'), 'props.color');
}

export function _validate_title_entry(element_id: string, element_data: Dict, canvas: string): void {
  if (_entry_type(element_data) !== 'text') {
    throw new StylingValidationError(`Title styling ${pyRepr(element_id)} must be a text entry.`);
  }
  if (!_extract_text(element_data)) {
    throw new StylingValidationError(`Title styling ${pyRepr(element_id)} must include non-empty text.`);
  }
  if (canvas === 'excalidraw') {
    const color = _first_present(
      get(element_data, 'strokeColor'),
      _label_value(element_data, 'strokeColor'),
    );
    _require_hex_color(element_id, color, 'strokeColor');
  } else {
    const props = _require_props(element_id, element_data);
    _require_tldraw_color(element_id, get(props, 'color'), 'props.color');
  }
}

export function _validate_shape_entry(element_id: string, element_data: Dict, canvas: string,
  group_surface = false): void {
  if (canvas === 'excalidraw') {
    const shape = _entry_type(element_data);
    if (!setHas(_EXCALIDRAW_NATIVE_SHAPES, shape) && shape !== 'text') {
      throw new StylingValidationError(
        `Excalidraw styling ${pyRepr(element_id)} has unsupported shape/type ${pyRepr(shape)}.`,
      );
    }
    if (shape === 'text') {
      if (!_extract_text(element_data)) {
        throw new StylingValidationError(`Text styling ${pyRepr(element_id)} must include non-empty text.`);
      }
      const color = _first_present(
        get(element_data, 'strokeColor'),
        _label_value(element_data, 'strokeColor'),
      );
      _require_hex_color(element_id, color, 'strokeColor');
      return;
    }
    const is_surface = group_surface || element_id.endsWith(BACKGROUND_SUFFIX);
    if (!_extract_text(element_data) && !is_surface) {
      throw new StylingValidationError(`Shape styling ${pyRepr(element_id)} must include renderable label text.`);
    }
    _require_hex_color(element_id, get(element_data, 'strokeColor'), 'strokeColor');
    const background = get(element_data, 'backgroundColor');
    if (background === 'transparent' && is_surface) {
      return;
    }
    _require_hex_color(element_id, background, 'backgroundColor');
    return;
  }

  const entry_type = get(element_data, 'type');
  if (entry_type === 'text') {
    _validate_title_entry(element_id, element_data, canvas);
    return;
  }
  if (entry_type !== 'geo') {
    throw new StylingValidationError(`TLDraw styling ${pyRepr(element_id)} must have type='geo'.`);
  }
  const props = _require_props(element_id, element_data);
  const geo = get(props, 'geo');
  if (!setHas(_TLDRAW_VALID_SHAPES, geo)) {
    throw new StylingValidationError(`TLDraw styling ${pyRepr(element_id)} has unsupported props.geo ${pyRepr(geo)}.`);
  }
  _require_tldraw_color(element_id, get(props, 'color'), 'props.color');
  const fill = get(props, 'fill');
  if (!setHas(_TLDRAW_VALID_FILLS, fill)) {
    throw new StylingValidationError(`TLDraw styling ${pyRepr(element_id)} has unsupported props.fill ${pyRepr(fill)}.`);
  }
  if (!_extract_text(element_data) && !element_id.endsWith(BACKGROUND_SUFFIX)) {
    throw new StylingValidationError(`TLDraw styling ${pyRepr(element_id)} must include props.text or label.text.`);
  }
}

export function _entry_type(element_data: Dict): unknown {
  const shape = get(element_data, 'shape');
  return truthy(shape) ? shape : get(element_data, 'type');
}

export function _extract_text(element_data: Dict): string {
  const label = get(element_data, 'label');
  if (isDict(label) && typeof get(label, 'text') === 'string' && pyStrip(label.text as string)) {
    return pyStrip(label.text as string);
  }
  const props = get(element_data, 'props');
  if (isDict(props) && typeof get(props, 'text') === 'string' && pyStrip(props.text as string)) {
    return pyStrip(props.text as string);
  }
  const text = get(element_data, 'text');
  if (typeof text === 'string' && pyStrip(text)) {
    return pyStrip(text);
  }
  return '';
}

export function _label_value(element_data: Dict, key: string): unknown {
  const label = get(element_data, 'label');
  if (isDict(label)) {
    return get(label, key);
  }
  return null;
}

export function _require_props(element_id: string, element_data: Dict): Dict {
  const props = get(element_data, 'props');
  if (!isDict(props)) {
    throw new StylingValidationError(`Styling ${pyRepr(element_id)} must include a props object.`);
  }
  return props;
}

/** ``re.match(r"^#[0-9A-Fa-f]{6}$", value)`` — ``$`` also matches before a final newline. */
function hexColorMatch(value: string): boolean {
  return _HEX_COLOR_RE.test(value) || (value.endsWith('\n') && _HEX_COLOR_RE.test(value.slice(0, -1)));
}

export function _require_hex_color(element_id: string, value: unknown, field_name: string): void {
  if (typeof value !== 'string' || !hexColorMatch(value)) {
    throw new StylingValidationError(
      `Styling ${pyRepr(element_id)} field ${field_name} must be a #RRGGBB hex color.`,
    );
  }
}

export function _require_tldraw_color(element_id: string, value: unknown, field_name: string): void {
  if (!setHas(_TLDRAW_VALID_COLORS, value)) {
    throw new StylingValidationError(
      `Styling ${pyRepr(element_id)} field ${field_name} must be a valid TLDraw color.`,
    );
  }
}

export function _first_present(...values: unknown[]): unknown {
  for (const value of values) {
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
}
