// Ported from evodesign/agentic_system/common/design_constraints.py — keep in sync.
//
// Carry the user's design intent unchanged across every quality stage.

import { pyGet, pyGetItem, pyItems, type PyMapping } from '../py/dict.ts';
import { pyEq, pyIn } from '../py/eq.ts';
import { AttributeError, PyTypeError, ValueError } from '../py/errors.ts';
import { pyJsonDumps, pyJsonLoads } from '../py/json.ts';
import { isDict, isMapping, pyOr, truthy } from '../py/truthy.ts';

export const ICONS_DISABLED_CONSTRAINT = 'Node icons are disabled. Do not add or recommend them.';

/** ``set(value)`` for the JSON values ``json.loads`` can return. */
function pySet(value: unknown): Set<unknown> {
  if (typeof value === 'string') return new Set([...value]);
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item !== null && typeof item === 'object') throw new PyTypeError('unhashable type');
    }
    const result = new Set<unknown>();
    for (const item of value) if (!pyIn(item, result)) result.add(item);
    return result;
  }
  if (isMapping(value)) return new Set(pyItems(value as PyMapping).map(([key]) => key));
  throw new PyTypeError('object is not iterable');
}

/** Saved locks and explicit DNA take priority over an automatic theme. */
export function preserve_explicit_design(manifest: Record<string, unknown>, constraints: string): boolean {
  const elements = pyGet(manifest, 'elements', []) as unknown[];
  if (elements.some((element) => truthy(pyGet(element, 'locked')))) {
    return true;
  }
  try {
    const policy = pyJsonLoads(pyOr(constraints, '{}'));
    return truthy(pyOr(pyGet(policy, 'user_design_preferences'), pyGet(policy, 'locked_element_ids')));
  } catch (error) {
    if (error instanceof ValueError || error instanceof PyTypeError || error instanceof AttributeError) {
      return truthy(constraints);
    }
    throw error;
  }
}

/** Honor the explicit web toggle without guessing intent from free text. */
export function icons_disabled(constraints: string): boolean {
  try {
    return pyEq(pyGet(pyJsonLoads(pyOr(constraints, '{}')), 'icons'), ICONS_DISABLED_CONSTRAINT);
  } catch (error) {
    if (error instanceof ValueError || error instanceof PyTypeError || error instanceof AttributeError) {
      return false;
    }
    throw error;
  }
}

export function build_design_constraints(
  source_text = '',
  requirements = '',
  design_expertise = '',
  diagram_type: string | null = null,
  use_icons: boolean | null = null,
  locked_nodes: string[] | null = null,
): string {
  // No extra model call: these are authoritative inputs, not inferred advice.
  const data: Record<string, unknown> = {
    source_and_explicit_design_requests: source_text,
    requirements,
    user_design_preferences: design_expertise,
    diagram_type,
    locked_element_ids: pyOr(locked_nodes, []),
  };
  if (use_icons !== null && use_icons !== undefined) {
    data.icons = truthy(use_icons)
      ? 'Optional small icons on selected key nodes only. Partial coverage is intentional; '
        + 'obey any explicitly named inclusions/exclusions. Do not demand icons everywhere.'
      : ICONS_DISABLED_CONSTRAINT;
  }
  return pyJsonDumps(data, { ensureAscii: false });
}

export function constraint_prompt(constraints: string | null): string {
  if (!truthy(constraints)) {
    return '';
  }
  return ('\nUSER DESIGN CONSTRAINTS (preserve throughout review and refinement):\n'
    + constraints + '\nExplicit user choices take priority over generic aesthetic preferences. '
    + 'Do not penalize requested partial icon coverage, palette or layout direction. '
    + 'Preserve entities, edge directions, labels and feedback loops. '
    + 'Report a constraint violation only with visible, concrete evidence.\n');
}

/** Include the locked node's text/icon; derived connector paths may move. */
export function locked_scene_elements(manifest: Record<string, unknown>, constraints: string): Record<string, unknown> {
  let ids: Set<unknown>;
  try {
    ids = pySet(pyGet(pyJsonLoads(pyOr(constraints, '{}')), 'locked_element_ids', []));
  } catch (error) {
    if (error instanceof ValueError || error instanceof PyTypeError) {
      ids = new Set();
    } else {
      throw error;
    }
  }
  const id_map = pyOr(pyGet(pyOr(pyGet(manifest, '_meta'), {}), 'id_map'), {}) as PyMapping;
  for (const key of [...ids]) {
    if (pyIn(key, id_map)) ids.add(pyGetItem(id_map, key));
  }
  const fields = ['x', 'y', 'width', 'height', 'angle', 'text', 'originalText', 'isDeleted',
    'strokeColor', 'backgroundColor', 'fontSize', 'fontFamily', 'opacity', 'fileId'];
  const protectedElements: Record<string, unknown> = {};
  for (const item of pyGet(manifest, 'elements', []) as unknown[]) {
    const icon = pyOr(pyGet(pyOr(pyGet(item, 'customData'), {}), 'evoDesignIcon'), {});
    const part = pyOr(pyGet(pyOr(pyGet(item, 'customData'), {}), 'evoDesignCardPart'), {});
    if (pyIn(pyGet(item, 'id'), ids) || pyIn(pyGet(item, 'containerId'), ids)
        || (isDict(icon) && pyIn(pyGet(icon, 'hostId'), ids))
        || (isDict(part) && pyIn(pyGet(part, 'hostId'), ids))) {
      const entry: Record<string, unknown> = {};
      for (const key of fields) entry[key] = pyGet(item, key);
      protectedElements[pyGetItem(item as PyMapping, 'id') as string] = entry;
    }
  }
  return protectedElements;
}
