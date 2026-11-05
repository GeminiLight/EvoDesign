// Ported from evodesign/agentic_system/generation_stage/unified/native_defaults.py — keep in sync.
//
// Complete mechanical Excalidraw fields without inventing scene geometry.
//
// ``dict`` keyed by arbitrary JSON values (``by_id``/``nodes``) → ``Map``, so a
// missing/None key lookup behaves like ``dict.get`` (no "undefined"/"null"
// string coercion).

import { excalidraw_element_defaults } from '../../canvas_environment/scene.ts';
import { pyPop, pySetdefault } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { KeyError, ValueError } from '../../py/errors.ts';
import { pyRepr, pyStr } from '../../py/str.ts';
import { isDict, isList, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

function has(d: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(d, key);
}

function get(d: Dict, key: string, defaultValue: unknown = null): unknown {
  return has(d, key) ? d[key] : defaultValue;
}

/** ``d[key]`` (KeyError when absent). */
function item(d: Dict, key: string): unknown {
  if (!has(d, key)) throw new KeyError(pyRepr(key));
  return d[key];
}

/** ``dict.setdefault`` */
function setdefault(d: Dict, key: string, value: unknown): unknown {
  return pySetdefault(d, key, value);
}

/** Fill omitted native metadata and derive reciprocal binding references. */
export function complete_native_elements(manifest: Dict): null {
  const elements = get(manifest, 'elements');
  if (!isList(elements)) {
    return null;
  }
  const by_id = new Map<string, Dict>();
  for (const element of elements) {
    if (isDict(element) && isStr(get(element, 'id'))) {
      by_id.set(element.id as string, element);
    }
  }
  for (const element of by_id.values()) {
    const defaults = excalidraw_element_defaults(['native', element.id]);
    // Colours, coordinates, sizes, paths, and semantic IDs remain authored.
    pyPop(defaults, 'strokeColor');
    pyPop(defaults, 'backgroundColor');
    defaults.roughness = 0;
    defaults.strokeWidth = 1.5;
    for (const [key, value] of Object.entries(defaults)) {
      if (!has(element, key)) element[key] = structuredClone(value);
    }
    if (get(element, 'type') === 'text') {
      const text_defaults: Dict = {
        fontFamily: 2, autoResize: true, lineHeight: 1.25,
        textAlign: 'left', verticalAlign: 'top', containerId: null,
      };
      if (isStr(get(element, 'text'))) {
        text_defaults.originalText = element.text;
      }
      for (const [key, value] of Object.entries(text_defaults)) {
        setdefault(element, key, value);
      }
    }
  }

  for (const element of by_id.values()) {
    const owners: unknown[] = [];
    if (get(element, 'type') === 'text' && truthy(get(element, 'containerId'))) {
      owners.push(element.containerId);
    } else if (get(element, 'type') === 'arrow') {
      for (const side of ['startBinding', 'endBinding']) {
        const binding = get(element, side);
        if (isDict(binding) && truthy(get(binding, 'elementId'))) {
          owners.push(binding.elementId);
        }
      }
    }
    for (const owner_id of owners) {
      const owner = isStr(owner_id) ? by_id.get(owner_id) : undefined;
      if (owner === undefined) {
        continue; // Leave invalid authored references for validation.
      }
      if (get(owner, 'boundElements') === null) {
        owner.boundElements = [];
      }
      const bindings = get(owner, 'boundElements');
      if (isList(bindings) && !bindings.some(
        (binding) => isDict(binding) && pyEq(get(binding, 'id'), element.id),
      )) {
        bindings.push({ id: element.id, type: element.type });
      }
    }
  }
  return null;
}

/** Project authored semantic mappings into the shared router's metadata. */
export function complete_native_semantics(manifest: Dict): null {
  const meta = pyOr(get(manifest, '_meta'), {}) as Dict;
  const structure = pyOr(get(meta, 'structure_instantiation'), {}) as Dict;
  const id_map = pyOr(get(meta, 'id_map'), {}) as Dict;
  const by_id = new Map<unknown, Dict>();
  for (const element of get(manifest, 'elements', []) as Dict[]) {
    by_id.set(item(element, 'id'), element);
  }
  const nodes = new Map<unknown, Dict>();
  for (const node of get(structure, 'nodes', []) as Dict[]) {
    nodes.set(item(node, 'id'), node);
  }
  const edge_data = setdefault(meta, 'edge_data', {}) as Dict;
  const lookup = (key: unknown): Dict | null => by_id.get(key) ?? null;
  for (const [node_id, node] of nodes) {
    void node;
    const shape = lookup(get(id_map, pyStr(node_id)));
    if (shape !== null) {
      setdefault(setdefault(shape, 'meta', {}) as Dict, 'semanticId', node_id);
    }
  }
  for (const edge of get(structure, 'edges', []) as Dict[]) {
    const edge_id = item(edge, 'id');
    const arrow = lookup(get(id_map, edge_id as string));
    if (arrow === null || get(arrow, 'type') !== 'arrow') {
      throw new ValueError(`Native semantic edge ${pyRepr(edge_id)} must map to its arrow`);
    }
    const arrow_meta = setdefault(arrow, 'meta', {}) as Dict;
    if (!pyEq(get(arrow_meta, 'semantic_edge_id'), edge_id)) {
      throw new ValueError(`Native semantic edge ${pyRepr(edge_id)} has a conflicting arrow mapping`);
    }
    if (['source', 'target'].some((key) => !pyEq(get(arrow_meta, key, item(edge, key)), item(edge, key)))) {
      throw new ValueError(`Native semantic edge ${pyRepr(edge_id)} has conflicting endpoint metadata`);
    }
    Object.assign(arrow_meta, { source: edge.source, target: edge.target });
    const payload: Dict = {
      type: 'arrow',
      start: { elementId: edge.source },
      end: { elementId: edge.target },
      routing: truthy(get(arrow, 'elbowed')) ? 'elbowed' : 'straight',
    };
    for (const key of [
      'strokeColor', 'strokeWidth', 'strokeStyle', 'opacity',
      'startArrowhead', 'endArrowhead',
    ]) {
      if (has(arrow, key)) payload[key] = arrow[key];
    }
    const label_id = get(id_map, `${pyStr(edge_id)}:label`);
    let label: Dict | null = lookup(label_id);
    if (label === null) {
      label = null;
      for (const element of by_id.values()) {
        if (get(element, 'type') === 'text' && pyEq(get(element, 'containerId'), item(arrow, 'id'))) {
          label = element;
          break;
        }
      }
    }
    if (label !== null) {
      if (get(label, 'type') !== 'text') {
        throw new ValueError(`Native semantic edge ${pyRepr(edge_id)} label must map to text`);
      }
      const label_meta = setdefault(label, 'meta', {}) as Dict;
      if (!pyEq(get(label_meta, 'semantic_edge_id', edge_id), edge_id)) {
        throw new ValueError(`Native semantic edge ${pyRepr(edge_id)} has a conflicting label mapping`);
      }
      Object.assign(label_meta, { semantic_edge_id: edge_id, semantic_arrow_id: arrow.id });
      id_map[`${pyStr(edge_id)}:label`] = item(label, 'id');
      const label_payload: Dict = {};
      for (const key of [
        'text', 'fontSize', 'fontFamily', 'strokeColor', 'textAlign', 'verticalAlign',
      ]) {
        if (has(label, key)) label_payload[key] = label[key];
      }
      payload.label = label_payload;
    } else if (truthy(get(edge, 'label'))) {
      payload.label = edge.label;
    }
    edge_data[pyStr(edge_id)] = payload;
  }
  return null;
}
