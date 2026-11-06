// Ported from evodesign/agentic_system/generation_stage/compact_decisions.py — keep in sync.
//
// Lossless expansion of flowchart model decisions before canonical validation.
//
// Only repeated serialization moves into code. Models still choose every visual
// style, element box and edge port pair; no topology or geometry is inferred.
// Persisted artifacts and downstream stages always use the existing full schema.

import { unwrap_structure_instantiation } from '../common/spec_utils.ts';
import { KeyError, ValueError } from '../py/errors.ts';
import { pyRepr } from '../py/str.ts';
import { isDict, isStr } from '../py/truthy.ts';

const has = (obj: Record<string, unknown>, key: string): boolean => Object.prototype.hasOwnProperty.call(obj, key);

/** ``set(mapping) - allowed`` is non-empty. */
const hasKeysOutside = (obj: Record<string, unknown>, allowed: readonly string[]): boolean =>
  Object.keys(obj).some((key) => !allowed.includes(key));

export function use_compact_decisions(structure: unknown, canvas_library: string): boolean {
  if (canvas_library !== 'excalidraw') return false;
  const inst = unwrap_structure_instantiation(structure);
  return (has(inst, 'chart_type') ? inst.chart_type : null) === 'flowchart';
}

export function _object(value: unknown, name: string): Record<string, unknown> {
  if (!isDict(value)) {
    throw new ValueError(`Compact decisions: ${name} must be an object.`);
  }
  return value;
}

export function _merge(base: Record<string, unknown>, override: Record<string, unknown>): Record<string, unknown> {
  const result = structuredClone(base);
  for (const [key, value] of Object.entries(override)) {
    const current = has(result, key) ? result[key] : null;
    if (isDict(value) && isDict(current)) {
      result[key] = _merge(current, value);
    } else {
      result[key] = structuredClone(value);
    }
  }
  return result;
}

/**
 * Expand explicitly versioned templates; legacy full maps pass through.
 *
 * Edge defaults are an explicit model decision applied to canonical edge IDs.
 * Unknown IDs and incomplete coverage remain errors in the existing validator.
 * Templates cannot carry text: exact semantic labels are injected separately.
 */
export function expand_styling_output(output: unknown, structure: unknown): unknown {
  if (!isDict(output)) {
    return output;
  }
  const inst = has(output, 'instantiation') ? output.instantiation : null;
  if (!isDict(inst) || !isStr(has(inst, 'format') ? inst.format : null)) {
    return output;
  }
  if (inst.format !== 'style_templates_v1') {
    throw new ValueError('Unknown compact Styling format.');
  }
  if (hasKeysOutside(inst, ['format', 'styles', 'elements', 'edge_default'])) {
    throw new ValueError('Unknown compact Styling fields.');
  }
  const styles = _object(has(inst, 'styles') ? inst.styles : null, 'styles');
  const elements = _object(has(inst, 'elements') ? inst.elements : null, 'elements');
  for (const [name, style] of Object.entries(styles)) {
    _object(style, `style ${name}`);
    const styleDict = style as Record<string, unknown>;
    const label = has(styleDict, 'label') ? _object(styleDict.label, `style ${name} label`) : {};
    if (has(label, 'text')) {
      throw new ValueError('Style templates must not contain label text.');
    }
  }
  const expanded: Record<string, unknown> = {};
  for (const [element_id, decision] of Object.entries(elements)) {
    let ref: unknown;
    let override: Record<string, unknown>;
    if (isStr(decision)) {
      ref = decision;
      override = {};
    } else {
      override = structuredClone(_object(decision, `element ${element_id}`));
      ref = has(override, 'style') ? override.style : null;
      delete override.style;
    }
    if (ref !== null && (!isStr(ref) || !has(styles, ref))) {
      throw new ValueError(`Unknown style reference for ${pyRepr(element_id)}: ${pyRepr(ref)}.`);
    }
    expanded[element_id] = _merge(ref !== null ? (styles[ref as string] as Record<string, unknown>) : {}, override);
  }
  if (has(inst, 'edge_default')) {
    const fallback = _object(inst.edge_default, 'edge_default');
    const keys = Object.keys(fallback);
    if (!(keys.length === 1 && keys[0] === 'strokeColor')) {
      throw new ValueError('Compact edge_default must contain only strokeColor.');
    }
    const structureInst = unwrap_structure_instantiation(structure);
    for (const edge of (has(structureInst, 'edges') ? structureInst.edges : []) as Record<string, unknown>[]) {
      if (!has(edge, 'id')) throw new KeyError("'id'");
      const edge_id = edge.id as string;
      expanded[edge_id] = _merge(fallback, (has(expanded, edge_id) ? expanded[edge_id] : {}) as Record<string, unknown>);
    }
  }
  const result = structuredClone(output);
  result.instantiation = expanded;
  return result;
}

/**
 * Expand flat geometry tuples using exact, validated Structure endpoints.
 *
 * [x,y,w,h] is a box; [source_side,target_side,options?] is an edge.
 * Full objects remain valid for explicit ports/labels or legacy providers.
 * Every edge must still be emitted; nothing is supplied for missing entries.
 */
export function expand_layout_output(output: unknown, structure: unknown): unknown {
  if (!isDict(output) || !isDict(has(output, 'instantiation') ? output.instantiation : null)) {
    return output;
  }
  const structureInst = unwrap_structure_instantiation(structure);
  const edges = new Map<unknown, Record<string, unknown>>();
  for (const edge of (has(structureInst, 'edges') ? structureInst.edges : []) as Record<string, unknown>[]) {
    if (!has(edge, 'id')) throw new KeyError("'id'");
    edges.set(edge.id, edge);
  }
  const result = structuredClone(output);
  const instantiation = result.instantiation as Record<string, unknown>;
  for (const [element_id, value] of Object.entries(instantiation)) {
    if (!Array.isArray(value)) {
      continue;
    }
    let expanded: Record<string, unknown>;
    if (edges.has(element_id)) {
      if (value.length !== 2 && value.length !== 3) {
        throw new ValueError(`Compact edge ${pyRepr(element_id)} needs two sides and optional options.`);
      }
      const options = value.length === 3 ? _object(value[2], 'edge options') : {};
      if (hasKeysOutside(options, ['routing', 'startArrowhead', 'endArrowhead', 'label'])) {
        throw new ValueError(`Unsupported compact edge options for ${pyRepr(element_id)}.`);
      }
      const edge = edges.get(element_id)!;
      const field = (key: string) => {
        if (!has(edge, key)) throw new KeyError(pyRepr(key));
        return edge[key];
      };
      expanded = {
        ...options,
        start: { elementId: field('source'), side: value[0] },
        end: { elementId: field('target'), side: value[1] },
      };
    } else {
      if (value.length !== 4) {
        throw new ValueError(`Compact box ${pyRepr(element_id)} needs x,y,w,h.`);
      }
      expanded = { x: value[0], y: value[1], w: value[2], h: value[3] };
    }
    instantiation[element_id] = expanded;
  }
  return result;
}
