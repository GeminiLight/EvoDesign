// Ported from evodesign/agentic_system/render_engine/shared/edge_routing.py — keep in sync.
//
// Shared edge resolution and routing helpers for canvas renderers.

import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { pyGet, pyItems } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { AttributeError, PyTypeError } from '../../py/errors.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyLower, pySplit, pyStrip } from '../../py/str.ts';
import { isDict, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

/** ``float(value)`` for the JSON-ish values seen here (raises like Python on None/containers). */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

/** ``for x in value`` over a list (or the keys of a dict); ``None`` raises like Python. */
function _iter(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (value instanceof Map || value instanceof Set) return [...value.keys()];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError(`'${value === null || value === undefined ? 'NoneType' : typeof value}' object is not iterable`);
}

function _has(mapping: unknown, key: string): boolean {
  if (mapping instanceof Map) return mapping.has(key);
  return isDict(mapping) && Object.prototype.hasOwnProperty.call(mapping, key);
}

function _lower(text: unknown): string {
  if (!isStr(text)) throw new AttributeError(`'${text === null ? 'NoneType' : typeof text}' object has no attribute 'lower'`);
  return pyLower(text);
}

export function* iter_concept_nodes(concept_hierarchy: Dict): Generator<Dict> {
  const data = unwrap_structure_instantiation(concept_hierarchy);

  if (_has(data, 'nodes') && Array.isArray(data.nodes)) {
    for (const node of data.nodes) {
      yield node as Dict;
    }
  }

  // Groups are valid arrow endpoints in architecture/swimlane diagrams when
  // an edge targets a container boundary instead of an inner node.
  if (_has(data, 'groups') && Array.isArray(data.groups)) {
    for (const group of data.groups) {
      yield group as Dict;
    }
  }

  // Renderer adapter boundary tolerance: persisted wrapped Structure payloads
  // may carry nested member objects, while current canonical groups use member
  // id strings.
  for (const group of _iter(pyGet(data, 'groups', []))) {
    if (!isDict(group)) {
      continue;
    }
    if (truthy(pyGet(group, 'id'))) {
      yield group;
    }
    for (const member of _iter(pyGet(group, 'members', []))) {
      if (isDict(member) && pyGet(member, 'kind') === 'node') {
        const node = pyOr(pyGet(member, 'node'), {});
        yield node as Dict;
      }
    }
  }
}

/** Classify a layout entry as edge styling / routing data. */
export function is_layout_edge_entry(element_id: unknown, element_data: unknown): boolean {
  if (isStr(element_id) && element_id.startsWith('edge:')) {
    return true;
  }
  if (isDict(element_data)) {
    const start = pyGet(element_data, 'start');
    const end = pyGet(element_data, 'end');
    if (isDict(start) && isDict(end)) {
      return true;
    }
  }
  return false;
}

export function resolve_label_from_node_ref(concept_hierarchy: Dict, node_ref: string): string | null {
  for (const node of iter_concept_nodes(concept_hierarchy)) {
    if (pyGet(node, 'id') === node_ref || pyGet(node, 'node_id') === node_ref) {
      return pyGet(node, 'label') as string | null;
    }
  }
  return null;
}

export function normalize_text(text: string | null | undefined): string | null {
  if (text === null || text === undefined) {
    return null;
  }
  if (!isStr(text)) throw new AttributeError(`'${typeof text}' object has no attribute 'replace'`);
  return pyStrip(pySplit(text.replace(/\n/g, ' ')).join(' '));
}

export function* iter_shape_id_candidates(node_ref: string): Generator<string> {
  if (!isStr(node_ref) || !node_ref) {
    return;
  }

  yield node_ref;

  if (!node_ref.startsWith('shape:')) {
    yield `shape:${node_ref}`;
    yield `shape:n_${node_ref}`;
  }

  if (node_ref.startsWith('n_')) {
    yield `shape:${node_ref.slice(2)}`;
  }

  // Container endpoints should bind to the drawable background shape.
  if (!node_ref.endsWith(':background')) {
    yield `shape:${node_ref}:background`;
  }

  if (node_ref.startsWith('group:')) {
    const base = node_ref.slice('group:'.length);
    yield `shape:${base}:background`;
  } else if (!node_ref.startsWith('shape:')) {
    yield `shape:group:${node_ref}:background`;
  }
}

export function find_shape_id(store: Dict, node_ref: string, concept_hierarchy: Dict | null = null): string | null {
  for (const candidate of iter_shape_id_candidates(node_ref)) {
    if (pyIn(candidate, store)) {
      return candidate;
    }
  }

  let label: string | null = null;
  if (concept_hierarchy !== null && concept_hierarchy !== undefined) {
    label = resolve_label_from_node_ref(concept_hierarchy, node_ref);
  }

  if (truthy(label)) {
    const normalized_label = pyOr(normalize_text(label), label);
    for (const [sid, shape] of pyItems(store)) {
      if (!isDict(shape)) {
        continue;
      }
      const shapeType = pyGet(shape, 'type');
      if (shapeType !== 'text' && shapeType !== 'geo') {
        continue;
      }
      const props = pyOr(pyGet(shape, 'props', {}), {});
      const shape_text = normalize_text(pyGet(props, 'text') as string | null);
      if (shape_text === normalized_label) {
        return sid as string;
      }
    }

    const target_by_label = `shape:node_${_lower(label)}`;
    if (pyIn(target_by_label, store)) {
      return target_by_label;
    }
  }

  const target = `shape:${_lower(node_ref)}`;
  if (pyIn(target, store)) {
    return target;
  }

  return null;
}

/** Read ``x/y/w/h`` from a TLDraw or Excalidraw shape-like element. */
export function shape_bbox(shape: Dict): { x: number; y: number; w: number; h: number } {
  const x = pyOr(pyGet(shape, 'x', 0), 0);
  const y = pyOr(pyGet(shape, 'y', 0), 0);
  let w = pyGet(shape, 'width');
  let h = pyGet(shape, 'height');
  if (w === null || h === null) {
    const props = pyOr(pyGet(shape, 'props'), {});
    if (w === null) {
      w = pyGet(props, 'w');
    }
    if (h === null) {
      h = pyGet(props, 'h');
    }
  }
  if (w === null) {
    w = 100;
  }
  if (h === null) {
    h = 100;
  }
  return { x: _float(x), y: _float(y), w: _float(w), h: _float(h) };
}

export function pick_sides_from_geometry(source_shape: Dict, target_shape: Dict): [string, string] {
  const source = shape_bbox(source_shape);
  const target = shape_bbox(target_shape);
  const source_center_x = source.x + source.w / 2;
  const source_center_y = source.y + source.h / 2;
  const target_center_x = target.x + target.w / 2;
  const target_center_y = target.y + target.h / 2;

  const dx = source_center_x - target_center_x;
  const dy = source_center_y - target_center_y;

  // Compare the two axes against each other and nothing else.
  if (Math.abs(dy) >= Math.abs(dx)) {
    if (dy < 0) {
      return ['bottom', 'top'];
    }
    return ['top', 'bottom'];
  }
  if (dx < 0) {
    return ['right', 'left'];
  }
  return ['left', 'right'];
}

export function is_side_plausible(side: string, source_shape: Dict, target_shape: Dict, role: string): boolean {
  const source = shape_bbox(source_shape);
  const target = shape_bbox(target_shape);
  const source_center_x = source.x + source.w / 2;
  const source_center_y = source.y + source.h / 2;
  const target_center_x = target.x + target.w / 2;
  const target_center_y = target.y + target.h / 2;

  side = pyOr(normalize_port(side), '') as string;

  if (role === 'source') {
    if (side === 'top') return source_center_y > target_center_y;
    if (side === 'bottom') return source_center_y < target_center_y;
    if (side === 'left') return source_center_x > target_center_x;
    if (side === 'right') return source_center_x < target_center_x;
  } else if (role === 'target') {
    if (side === 'top') return source_center_y < target_center_y;
    if (side === 'bottom') return source_center_y > target_center_y;
    if (side === 'left') return source_center_x < target_center_x;
    if (side === 'right') return source_center_x > target_center_x;
  }
  return false;
}

export function audit_sides(hinted: Dict | null, source_shape: Dict, target_shape: Dict): [string, string] {
  const [geom_start, geom_end] = pick_sides_from_geometry(source_shape, target_shape);

  if (!truthy(hinted)) {
    return [geom_start, geom_end];
  }

  const start_hint = normalize_port(pyGet(hinted, 'start') as string | null);
  const end_hint = normalize_port(pyGet(hinted, 'end') as string | null);

  // A same-face hint pair expresses a loop-back edge: honour it.
  if (truthy(start_hint) && start_hint === end_hint) {
    return [start_hint!, end_hint!];
  }

  let start_side = geom_start;
  let end_side = geom_end;

  if (truthy(start_hint) && is_side_plausible(start_hint!, source_shape, target_shape, 'source')) {
    start_side = start_hint!;
  }

  if (truthy(end_hint) && is_side_plausible(end_hint!, source_shape, target_shape, 'target')) {
    end_side = end_hint!;
  }

  return [start_side, end_side];
}

export function derive_routing_from_sides(source_side: string, target_side: string, chart_type: string | null = null): string {
  if (truthy(chart_type)) {
    const chart_key = _lower(chart_type).split('_diagram').join('').split('_').join('');
    if (chart_key === 'mindmap') {
      return 'curved';
    }
    if (chart_key === 'orgchart' || chart_key === 'tree') {
      return 'straight';
    }
    if (chart_key === 'state') {
      if (source_side === target_side || (source_side === 'bottom' && target_side === 'top')) {
        return 'curved';
      }
    }
    if (chart_key === 'architecture') {
      if (source_side === 'bottom' && target_side === 'top') {
        return 'straight';
      }
      if (source_side === 'top' && target_side === 'bottom') {
        return 'curved';
      }
    }
  }

  const aligned: [unknown, unknown][] = [
    ['right', 'left'],
    ['left', 'right'],
    ['bottom', 'top'],
    ['top', 'bottom'],
  ];
  if (aligned.some(([s, t]) => s === source_side && t === target_side)) {
    return 'straight';
  }
  if (source_side === target_side) {
    return 'curved';
  }
  return 'elbowed';
}

export function get_edge_center(element: Dict, edge: string): { x: number; y: number } {
  const bbox = shape_bbox(element);
  const { x, y, w, h } = bbox;

  if (edge === 'left') return { x, y: y + h / 2 };
  if (edge === 'right') return { x: x + w, y: y + h / 2 };
  if (edge === 'top') return { x: x + w / 2, y };
  if (edge === 'bottom') return { x: x + w / 2, y: y + h };
  return { x: x + w, y: y + h / 2 };
}

export function normalize_port(port: string | null | undefined): string | null {
  if (!truthy(port) || !isStr(port)) {
    return null;
  }
  let normalized = pyLower(pyStrip(port));
  if (normalized === 'botton') {
    normalized = 'bottom';
  }
  if (normalized === 'left' || normalized === 'right' || normalized === 'top' || normalized === 'bottom') {
    return normalized;
  }
  return null;
}

export function extract_side_from_port(port_payload: unknown): string | null {
  if (isStr(port_payload)) {
    return normalize_port(port_payload);
  }
  if (isDict(port_payload)) {
    const side = pyOr(pyGet(port_payload, 'side'), pyGet(port_payload, 'port'));
    return isStr(side) ? normalize_port(side) : null;
  }
  return null;
}

export function collect_edge_payloads(concept_hierarchy: Dict, store: Dict | null = null): Record<string, Dict> {
  const payloads: Record<string, Dict> = {};

  const styling_instantiation = pyOr(pyGet(concept_hierarchy, 'styling_instantiation'), {});
  if (isDict(styling_instantiation)) {
    for (const [key, value] of pyItems(styling_instantiation)) {
      if (isStr(key) && isDict(value)) {
        payloads[key] = value;
      }
    }
  }

  if (truthy(store)) {
    const document = pyGet(store, 'document:document');
    const meta = isDict(document) ? pyGet(document, 'meta') : null;
    if (isDict(meta)) {
      const edge_payloads = pyGet(meta, 'edge_data');
      if (isDict(edge_payloads)) {
        for (const [key, value] of pyItems(edge_payloads)) {
          if (isStr(key) && isDict(value)) {
            payloads[key] = value;
          }
        }
      }
    }
  }

  return payloads;
}

/** Build relation records from layout-derived edge payloads. */
export function relations_from_edge_data(edge_data: Dict, valid_element_ids: Set<string> | null = null): Dict[] {
  const relations: Dict[] = [];
  for (const [edge_id, payload] of pyItems(edge_data)) {
    if (!isStr(edge_id) || !isDict(payload)) {
      continue;
    }
    const start = pyGet(payload, 'start');
    const end = pyGet(payload, 'end');
    if (!isDict(start) || !isDict(end)) {
      continue;
    }
    const source = pyGet(start, 'elementId');
    const target = pyGet(end, 'elementId');
    if (!isStr(source) || !isStr(target)) {
      continue;
    }
    if (valid_element_ids !== null && valid_element_ids !== undefined
      && (!pyIn(source, valid_element_ids) || !pyIn(target, valid_element_ids))) {
      continue;
    }

    const relation: Dict = {
      id: edge_id,
      source,
      target,
      start: pyGet(start, 'side'),
      end: pyGet(end, 'side'),
    };
    for (const key of ['label', 'routing', 'startArrowhead', 'endArrowhead', 'arrowheadStart', 'arrowheadEnd']) {
      if (_has(payload, key)) {
        relation[key] = payload[key];
      }
    }
    relations.push(relation);
  }
  return relations;
}

export function resolve_edge_payload(edge_payloads: Record<string, Dict>, edge_id: unknown): Dict | null {
  if (isStr(edge_id) && edge_id) {
    const payload = pyGet(edge_payloads, edge_id);
    if (isDict(payload)) {
      return payload;
    }
  }
  return null;
}

export function edge_payload_value(edge_payload: Dict | null, key: string): unknown {
  if (!isDict(edge_payload)) {
    return null;
  }
  const props = pyGet(edge_payload, 'props');
  if (isDict(props) && _has(props, key)) {
    return props[key];
  }
  return pyGet(edge_payload, key);
}

export function extract_edge_port_hints(
  concept_hierarchy: Dict,
  store: Dict | null = null,
): Record<string, { start: string | null; end: string | null }> {
  const hints: Record<string, { start: string | null; end: string | null }> = {};

  const styling_instantiation = pyOr(pyGet(concept_hierarchy, 'styling_instantiation'), {});
  if (isDict(styling_instantiation)) {
    for (const [key, value] of pyItems(styling_instantiation)) {
      if (isStr(key) && isDict(value)) {
        const start_port = extract_side_from_port(pyGet(value, 'start'));
        const end_port = extract_side_from_port(pyGet(value, 'end'));
        if (truthy(start_port) || truthy(end_port)) {
          hints[key] = { start: start_port, end: end_port };
        }
      }
    }
  }

  if (truthy(store)) {
    const document = pyGet(store, 'document:document');
    if (truthy(document) && isDict(document)) {
      const meta = pyGet(document, 'meta');
      if (truthy(meta) && isDict(meta)) {
        const edge_data = pyGet(meta, 'edge_data');
        if (truthy(edge_data) && isDict(edge_data)) {
          for (const [key, value] of pyItems(edge_data)) {
            if (isStr(key) && isDict(value)) {
              const start_port = extract_side_from_port(pyGet(value, 'start'));
              const end_port = extract_side_from_port(pyGet(value, 'end'));
              if (truthy(start_port) || truthy(end_port)) {
                hints[key] = { start: start_port, end: end_port };
              }
            }
          }
        }
      }
    }
  }

  return hints;
}

export function normalize_routing(value: unknown): string | null {
  if (!isStr(value)) {
    return null;
  }
  let routing = pyLower(pyStrip(value));
  if (routing === 'elbow') {
    routing = 'elbowed';
  }
  if (routing === 'straight' || routing === 'elbowed' || routing === 'curved') {
    return routing;
  }
  return null;
}

export function edge_endpoints(relation: Dict): [string, string] {
  const source = pyOr(pyOr(pyGet(relation, 'from'), pyGet(relation, 'source')), '');
  const target = pyOr(pyOr(pyGet(relation, 'to'), pyGet(relation, 'target')), '');
  return [source as string, target as string];
}

export function collect_relations(concept_hierarchy: Dict): Dict[] {
  const data = unwrap_structure_instantiation(concept_hierarchy);

  if (_has(data, 'edges') && Array.isArray(data.edges)) {
    const normalized: Dict[] = [];
    for (const edge of data.edges) {
      if (!isDict(edge)) {
        continue;
      }
      const [source, target] = edge_endpoints(edge);
      const enriched: Dict = { ...edge };
      if (!_has(enriched, 'source')) enriched.source = source;
      if (!_has(enriched, 'target')) enriched.target = target;
      normalized.push(enriched);
    }
    return normalized;
  }

  const relations: unknown[] = [];
  for (const group of _iter(pyGet(data, 'groups', []))) {
    relations.push(..._iter(pyGet(group, 'relations', [])));
  }
  return relations as Dict[];
}

export const __all__ = [
  'audit_sides',
  'collect_edge_payloads',
  'collect_relations',
  'derive_routing_from_sides',
  'edge_endpoints',
  'edge_payload_value',
  'extract_edge_port_hints',
  'extract_side_from_port',
  'find_shape_id',
  'get_edge_center',
  'normalize_port',
  'normalize_routing',
  'relations_from_edge_data',
  'resolve_edge_payload',
  'shape_bbox',
];
