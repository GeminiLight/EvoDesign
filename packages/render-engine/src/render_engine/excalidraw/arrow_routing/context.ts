// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_routing/context.py — keep in sync.
//
// Diagram facts the routers read from the structure and the rendered scene.

import { group_frame_render_id } from '../../../common/semantic_ids.ts';
import { pyGet, pyItems, pySetdefault, type PyMapping } from '../../../py/dict.ts';
import { PyTypeError } from '../../../py/errors.ts';
import { pyFloatParse } from '../../../py/number.ts';
import { pySorted } from '../../../py/sort.ts';
import { pyEndswith, pyLower, pyStr } from '../../../py/str.ts';
import { isDict, isStr, pyOr, truthy } from '../../../py/truthy.ts';

type Dict = Record<string, unknown>;
export type FrameBox = { x: number; y: number; w: number; h: number };

export const ARCHITECTURE_TYPES: ReadonlySet<string> = new Set(['architecture', 'architecture_diagram']);
export const CONCEPT_MAP_TYPES: ReadonlySet<string> = new Set(['concept_map', 'concept map', 'conceptmap']);

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

function _list(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (!truthy(value)) return [];
  if (value instanceof Set || value instanceof Map) return [...value.keys()];
  if (isDict(value)) return Object.keys(value);
  if (typeof value === 'string') return [...value];
  throw new PyTypeError('object is not iterable');
}

/** Dataclass ``DiagramContext``; ``is_architecture`` / ``is_concept_map`` are properties. */
export class DiagramContext {
  chart_type: string;
  // node id -> group id, from node.group_id first, then group membership
  node_group_ids: Record<string, string>;
  core_node_ids: Set<string>;
  // Cross-cutting / governance groups that sit beside architecture layers.
  side_group_ids: Set<string>;
  group_frame_ids: Set<string>;
  // Rendered concept-map section frames, top-to-bottom then left-to-right.
  concept_frames: [string, FrameBox][];

  constructor(
    chart_type = '',
    node_group_ids: Record<string, string> = {},
    core_node_ids: Set<string> = new Set(),
    side_group_ids: Set<string> = new Set(),
    group_frame_ids: Set<string> = new Set(),
    concept_frames: [string, FrameBox][] = [],
  ) {
    this.chart_type = chart_type;
    this.node_group_ids = node_group_ids;
    this.core_node_ids = core_node_ids;
    this.side_group_ids = side_group_ids;
    this.group_frame_ids = group_frame_ids;
    this.concept_frames = concept_frames;
  }

  get is_architecture(): boolean {
    return ARCHITECTURE_TYPES.has(this.chart_type);
  }

  get is_concept_map(): boolean {
    return CONCEPT_MAP_TYPES.has(this.chart_type);
  }

  /** Rebuild a context from its dataclass fields (e.g. a decoded fixture). */
  static from_fields(fields: Dict | DiagramContext): DiagramContext {
    if (fields instanceof DiagramContext) return fields;
    const asSet = (value: unknown): Set<string> => new Set(_list(value) as string[]);
    return new DiagramContext(
      (fields.chart_type as string) ?? '',
      (fields.node_group_ids as Record<string, string>) ?? {},
      asSet(fields.core_node_ids),
      asSet(fields.side_group_ids),
      asSet(fields.group_frame_ids),
      (fields.concept_frames as [string, FrameBox][]) ?? [],
    );
  }
}

export function _diagram_context(structure: Dict, id_map: PyMapping, elements: unknown[]): DiagramContext {
  const nodes = _list(pyOr(pyGet(structure, 'nodes', []), [])).filter(isDict);
  const groups = _list(pyOr(pyGet(structure, 'groups', []), [])).filter(isDict);
  const context = new DiagramContext(pyLower(pyStr(pyGet(structure, 'chart_type', ''))));
  const node_group_ids: Record<string, string> = {};
  for (const node of nodes) {
    if (truthy(pyGet(node, 'id')) && truthy(pyGet(node, 'group_id'))) {
      node_group_ids[pyStr(pyGet(node, 'id'))] = pyStr(pyGet(node, 'group_id'));
    }
  }
  context.node_group_ids = node_group_ids;
  context.core_node_ids = new Set(
    nodes
      .filter((node) => truthy(pyGet(node, 'id')) && ['core', 'core_concept'].includes(pyLower(pyStr(pyGet(node, 'class', '')))))
      .map((node) => pyStr(pyGet(node, 'id'))),
  );
  for (const group of groups) {
    if (!truthy(pyGet(group, 'id'))) continue;
    const group_id = pyStr(group.id);
    const token = ['id', 'class', 'label'].map((key) => pyLower(pyStr(pyGet(group, key, '')))).join(' ');
    if (token.includes('cross') || token.includes('governance')) context.side_group_ids.add(group_id);
    for (const member_id of _list(pyOr(pyGet(group, 'members', []), []))) {
      if (isStr(member_id)) pySetdefault(context.node_group_ids, member_id, group_id);
    }
  }
  const group_frame_ids = new Set<string>();
  for (const group of groups) {
    const render_id = group_frame_render_id(id_map, pyGet(group, 'id'));
    if (truthy(render_id)) group_frame_ids.add(render_id as string);
  }
  context.group_frame_ids = group_frame_ids;
  if (context.is_concept_map) {
    const rendered_frames = new Set<unknown>();
    for (const [semantic_id, render_id] of pyItems(id_map)) {
      if (pyEndswith(semantic_id as string, ':background')) rendered_frames.add(render_id);
    }
    const frames: [string, FrameBox][] = [];
    for (const element of elements) {
      if (!isDict(element) || !rendered_frames.has(pyGet(element, 'id'))) continue;
      frames.push([
        pyStr(element.id),
        {
          x: _float(pyOr(pyGet(element, 'x', 0.0), 0.0)),
          y: _float(pyOr(pyGet(element, 'y', 0.0), 0.0)),
          w: _float(pyOr(pyGet(element, 'width', 0.0), 0.0)),
          h: _float(pyOr(pyGet(element, 'height', 0.0), 0.0)),
        },
      ]);
    }
    context.concept_frames = pySorted(frames, (item) => [item[1].y, item[1].x]);
  }
  return context;
}
