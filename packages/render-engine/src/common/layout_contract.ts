// Ported from evodesign/agentic_system/common/layout_contract.py — keep in sync.
//
// Layout-stage contract checks shared by generation and render boundaries.
//
// Python sets of ids are ``Set<string>``; ``_collect_edge_contracts`` returns a
// plain object ``{edge_id: [source, target]}`` (string keys, insertion order).
// Layout / Styling dicts may arrive as plain objects or ``Map`` (non-string
// keys), so every dict access goes through ``py/dict.ts``.

import { pyGet, pyGetItem, pyItems, pyKeys, type PyMapping } from '../py/dict.ts';
import { pyIn } from '../py/eq.ts';
import { ValueError } from '../py/errors.ts';
import { pySorted } from '../py/sort.ts';
import { pyRepr, pyStrip } from '../py/str.ts';
import { isMapping, isNumber, isStr, pyTypeName, truthy } from '../py/truthy.ts';
import { BACKGROUND_SUFFIX, ICON_SUFFIX, TITLE_SUFFIX, companion_id } from './semantic_ids.ts';
import { unwrap_structure_instantiation } from './spec_utils.ts';

/** Raised when Layout output violates cross-stage element contracts. */
export class LayoutValidationError extends ValueError {}

export const VALID_EDGE_SIDES: ReadonlySet<string> = new Set(['top', 'bottom', 'left', 'right']);

type Contracts = Record<string, [string, string]>;

/**
 * Validate Layout output against Structure ids and Styling render keys.
 *
 * Layout is allowed to add geometry and edge routing only. It must not invent
 * semantic elements, omit geometry for styled renderable elements, or rewrite
 * the Structure edge endpoints.
 */
export function validate_layout_instantiation(
  layout_instantiation: unknown,
  structure_instantiation: Record<string, unknown> | null = null,
  styling_instantiation: PyMapping | null = null,
  require_complete_styling_geometry = true,
): PyMapping {
  if (!isMapping(layout_instantiation)) {
    throw new LayoutValidationError(
      'Layout instantiation must be a JSON object; '
      + `got ${pyTypeName(layout_instantiation)}.`,
    );
  }

  const styling = isMapping(styling_instantiation) ? styling_instantiation : null;
  const structure = unwrap_structure_instantiation(structure_instantiation);
  const edge_contracts = _collect_edge_contracts(structure);
  const structure_edge_ids = new Set(Object.keys(edge_contracts));
  const structure_group_ids = _collect_structure_ids(structure, 'groups');

  const allowed_layout_ids = _allowed_layout_ids(structure, styling);
  for (const [element_id, element_data] of pyItems(layout_instantiation)) {
    if (element_id === 'specification') {
      throw new LayoutValidationError(
        "Layout instantiation must not contain a nested 'specification' key; "
        + 'unwrap the agent output before validation.',
      );
    }
    if (!isStr(element_id) || !pyStrip(element_id)) {
      throw new LayoutValidationError(`Layout element id must be a non-empty string; got ${pyRepr(element_id)}.`);
    }

    if (_is_rejected_underscore_icon_key(element_id)) {
      throw new LayoutValidationError(
        `Unsupported underscore icon layout id ${pyRepr(element_id)}; `
        + "use the canonical '<node_id>:icon' suffix.",
      );
    }

    if (_is_icon_key(element_id)) {
      _validate_known_id(element_id, allowed_layout_ids);
      continue;
    }

    if (is_layout_edge_entry(element_id, element_data, structure_edge_ids)) {
      _validate_known_edge_id(element_id, styling, edge_contracts);
      _validate_edge_payload(element_id, element_data, pyGet(edge_contracts, element_id) as [string, string] | null);
      continue;
    }

    _validate_known_id(element_id, allowed_layout_ids);
    if (_is_group_shell_with_background(element_id, layout_instantiation, structure_group_ids)) {
      continue;
    }
    _validate_geometry(element_id, element_data);
  }

  if (require_complete_styling_geometry && styling !== null) {
    _validate_all_styled_renderables_have_geometry(
      layout_instantiation,
      styling,
      structure_edge_ids,
      structure_group_ids,
    );
  }

  for (const [edge_id, endpoints] of Object.entries(edge_contracts)) {
    const edge_payload = pyGet(layout_instantiation, edge_id);
    if (edge_payload === null || edge_payload === undefined) {
      throw new LayoutValidationError(`Missing layout edge entry for Structure edge ${pyRepr(edge_id)}.`);
    }
    _validate_edge_payload(edge_id, edge_payload, endpoints);
  }

  return layout_instantiation;
}

/** Return whether a layout map entry represents an edge. */
export function is_layout_edge_entry(
  element_id: unknown,
  element_data: unknown,
  structure_edge_ids: ReadonlySet<string> | null = null,
): boolean {
  if (isStr(element_id)) {
    if (element_id.startsWith('edge:')) {
      return true;
    }
    if (truthy(structure_edge_ids) && structure_edge_ids!.has(element_id)) {
      return true;
    }
  }
  if (isMapping(element_data)) {
    const start = pyGet(element_data, 'start');
    const end = pyGet(element_data, 'end');
    return isMapping(start) && isMapping(end);
  }
  return false;
}

export function _collect_edge_contracts(structure_instantiation: PyMapping): Contracts {
  const contracts: Contracts = {};
  const edges = pyGet(structure_instantiation, 'edges');
  ((truthy(edges) ? edges : []) as unknown[]).forEach((edge, index) => {
    if (!isMapping(edge)) {
      throw new LayoutValidationError(`Structure edge at index ${index} must be an object.`);
    }
    const edge_id = pyGet(edge, 'id');
    const source = pyGet(edge, 'source', pyGet(edge, 'from'));
    const target = pyGet(edge, 'target', pyGet(edge, 'to'));
    if (![edge_id, source, target].every((value) => isStr(value) && truthy(pyStrip(value)))) {
      throw new LayoutValidationError(
        `Structure edge at index ${index} must include non-empty id/source/target fields.`,
      );
    }
    contracts[edge_id as string] = [source as string, target as string];
  });
  return contracts;
}

export function _collect_structure_ids(structure_instantiation: PyMapping, field_name: string): Set<string> {
  const ids = new Set<string>();
  const items = pyGet(structure_instantiation, field_name);
  for (const item of (truthy(items) ? items : []) as unknown[]) {
    if (isMapping(item) && isStr(pyGet(item, 'id')) && truthy(pyStrip(pyGetItem(item, 'id') as string))) {
      ids.add(pyGetItem(item, 'id') as string);
    }
  }
  return ids;
}

export function _allowed_layout_ids(
  structure_instantiation: PyMapping,
  styling_instantiation: PyMapping | null,
): Set<string> {
  if (truthy(styling_instantiation)) {
    return new Set(pyKeys(styling_instantiation!).filter(isStr));
  }

  const allowed = new Set<string>();
  const nodes = pyGet(structure_instantiation, 'nodes');
  for (const node of (truthy(nodes) ? nodes : []) as unknown[]) {
    if (isMapping(node) && isStr(pyGet(node, 'id'))) {
      const node_id = pyGetItem(node, 'id') as string;
      allowed.add(node_id);
      allowed.add(companion_id(node_id, ICON_SUFFIX));
    }
  }

  const groups = pyGet(structure_instantiation, 'groups');
  for (const group of (truthy(groups) ? groups : []) as unknown[]) {
    if (isMapping(group) && isStr(pyGet(group, 'id'))) {
      const group_id = pyGetItem(group, 'id') as string;
      allowed.add(group_id);
      allowed.add(companion_id(group_id, BACKGROUND_SUFFIX));
      allowed.add(companion_id(group_id, TITLE_SUFFIX));
    }
  }

  for (const edge_id of Object.keys(_collect_edge_contracts(structure_instantiation))) allowed.add(edge_id);
  return allowed;
}

export function _is_icon_key(element_id: string): boolean {
  return element_id.endsWith(ICON_SUFFIX);
}

export function _is_rejected_underscore_icon_key(element_id: string): boolean {
  return element_id.endsWith('_icon');
}

export function _validate_known_id(element_id: string, allowed_layout_ids: ReadonlySet<string> | null): null {
  // ``None`` means "no id set was derivable, skip the check". An *empty* set
  // means the upstream Structure/Styling stages produced no renderable ids at
  // all, so every layout id is unknown by definition — treating the empty set
  // as falsy here let a node-less Structure wave through arbitrary layout ids.
  if (allowed_layout_ids !== null && allowed_layout_ids !== undefined && !allowed_layout_ids.has(element_id)) {
    throw new LayoutValidationError(`Unknown layout id ${pyRepr(element_id)}; Layout must reuse Styling/Structure ids.`);
  }
  return null;
}

export function _validate_known_edge_id(
  edge_id: string,
  styling_instantiation: PyMapping | null,
  edge_contracts: Contracts,
): null {
  if (truthy(edge_contracts)) {
    if (!pyIn(edge_id, edge_contracts)) {
      throw new LayoutValidationError(`Unknown layout id ${pyRepr(edge_id)}; no matching Structure edge id.`);
    }
    return null;
  }
  if (styling_instantiation !== null && styling_instantiation !== undefined && !pyIn(edge_id, styling_instantiation)) {
    throw new LayoutValidationError(`Unknown layout id ${pyRepr(edge_id)}; Layout must reuse Styling edge ids.`);
  }
  return null;
}

export function _validate_all_styled_renderables_have_geometry(
  layout_instantiation: PyMapping,
  styling_instantiation: PyMapping,
  structure_edge_ids: ReadonlySet<string>,
  structure_group_ids: ReadonlySet<string>,
): null {
  for (const [element_id, element_data] of pyItems(styling_instantiation)) {
    if (!isStr(element_id)) {
      continue;
    }
    if (element_id.startsWith('_') || element_id === 'metadata' || element_id === 'meta' || element_id === 'specification') {
      continue;
    }
    if (_is_icon_key(element_id)) {
      continue;
    }
    if (is_layout_edge_entry(element_id, element_data, structure_edge_ids)) {
      continue;
    }
    if (element_id.startsWith('edge:') || structure_edge_ids.has(element_id)) {
      continue;
    }
    if (_is_group_shell_with_background(element_id, layout_instantiation, structure_group_ids)) {
      continue;
    }

    if (!pyIn(element_id, layout_instantiation)) {
      throw new LayoutValidationError(`Missing layout geometry for styled element ${pyRepr(element_id)}.`);
    }
    _validate_geometry(element_id, pyGetItem(layout_instantiation, element_id));
  }
  return null;
}

export function _validate_geometry(element_id: string, element_data: unknown): null {
  if (!isMapping(element_data)) {
    throw new LayoutValidationError(
      `Missing layout geometry for ${pyRepr(element_id)}; expected object with x, y, w, h.`,
    );
  }
  const missing = ['x', 'y', 'w', 'h'].filter((field) => !pyIn(field, element_data));
  if (missing.length) {
    const fields = missing.join(', ');
    throw new LayoutValidationError(`Missing geometry fields for ${pyRepr(element_id)}: ${fields}.`);
  }

  const non_numeric = ['x', 'y', 'w', 'h'].filter((field) => !_is_number(pyGet(element_data, field)));
  if (non_numeric.length) {
    const fields = non_numeric.join(', ');
    throw new LayoutValidationError(`Geometry fields for ${pyRepr(element_id)} must be numeric: ${fields}.`);
  }
  if ((pyGetItem(element_data, 'w') as number) <= 0 || (pyGetItem(element_data, 'h') as number) <= 0) {
    throw new LayoutValidationError(`Geometry fields for ${pyRepr(element_id)} must have positive w and h.`);
  }
  return null;
}

export function _is_group_shell_with_background(
  element_id: string,
  layout_instantiation: PyMapping,
  structure_group_ids: ReadonlySet<string>,
): boolean {
  return (
    structure_group_ids.has(element_id)
    && pyIn(companion_id(element_id, BACKGROUND_SUFFIX), layout_instantiation)
  );
}

export function _validate_edge_payload(
  edge_id: string,
  element_data: unknown,
  expected_endpoints: readonly [string, string] | readonly string[] | null,
): null {
  if (!isMapping(element_data)) {
    throw new LayoutValidationError(`Layout edge ${pyRepr(edge_id)} must be an object with start/end ports.`);
  }

  const start = pyGet(element_data, 'start');
  const end = pyGet(element_data, 'end');
  if (!isMapping(start) || !isMapping(end)) {
    throw new LayoutValidationError(`Layout edge ${pyRepr(edge_id)} must include start and end port objects.`);
  }

  const start_id = pyGet(start, 'elementId');
  const end_id = pyGet(end, 'elementId');
  const start_side = pyGet(start, 'side');
  const end_side = pyGet(end, 'side');
  if (!isStr(start_id) || !pyStrip(start_id)) {
    throw new LayoutValidationError(`Layout edge ${pyRepr(edge_id)} start.elementId must be a non-empty string.`);
  }
  if (!isStr(end_id) || !pyStrip(end_id)) {
    throw new LayoutValidationError(`Layout edge ${pyRepr(edge_id)} end.elementId must be a non-empty string.`);
  }
  if (!isStr(start_side) || !pyStrip(start_side)) {
    throw new LayoutValidationError(`Layout edge ${pyRepr(edge_id)} start.side must be a non-empty string.`);
  }
  if (!isStr(end_side) || !pyStrip(end_side)) {
    throw new LayoutValidationError(`Layout edge ${pyRepr(edge_id)} end.side must be a non-empty string.`);
  }
  if (!VALID_EDGE_SIDES.has(start_side)) {
    throw new LayoutValidationError(
      `Layout edge ${pyRepr(edge_id)} start.side must be one of `
      + `${pyRepr(pySorted(VALID_EDGE_SIDES))}; got ${pyRepr(start_side)}.`,
    );
  }
  if (!VALID_EDGE_SIDES.has(end_side)) {
    throw new LayoutValidationError(
      `Layout edge ${pyRepr(edge_id)} end.side must be one of `
      + `${pyRepr(pySorted(VALID_EDGE_SIDES))}; got ${pyRepr(end_side)}.`,
    );
  }
  if (pyIn('waypoints', element_data)) {
    throw new LayoutValidationError(
      `Layout edge ${pyRepr(edge_id)} must not include waypoints; `
      + 'renderer computes the path from start/end sides.',
    );
  }

  if (expected_endpoints === null || expected_endpoints === undefined) {
    return null;
  }

  const [expected_source, expected_target] = expected_endpoints;
  if (start_id !== expected_source || end_id !== expected_target) {
    throw new LayoutValidationError(
      `Edge endpoint mismatch for ${pyRepr(edge_id)}: expected `
      + `${pyRepr(expected_source)}->${pyRepr(expected_target)}, got ${pyRepr(start_id)}->${pyRepr(end_id)}.`,
    );
  }
  return null;
}

export function _is_number(value: unknown): boolean {
  return isNumber(value);
}
