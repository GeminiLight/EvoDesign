// Ported from evodesign/agentic_system/render_engine/excalidraw/sequence_layout.py — keep in sync.
//
// Render sequence chronology as lifelines and message rows, never graph routes.

import { isF, markF, pyDeepcopy } from '../../py/float_marks.ts';
import { sync_node_icons } from '../../common/node_icons.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { _estimate_text_dimensions } from '../../generation_stage/layout/element_shape_estimator.ts';
import { pyGet, pyGetItem, pyItems, pySetdefault } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { ValueError } from '../../py/errors.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyMax, pyMin, pySorted } from '../../py/sort.ts';
import { pyLower, pyStr } from '../../py/str.ts';
import { isDict, pyOr, truthy } from '../../py/truthy.ts';
import { _excalidraw_defaults, _generate_excalidraw_id } from './converter.ts';
import { normalize_excalidraw_manifest } from './normalizer.ts';

type Dict = Record<string, unknown>;

function _float(value: unknown): number {
  return pyFloatParse(value as number | string | boolean);
}

/** ``max(a, b)`` for numbers: the first argument unless the second is greater. */
function _max2(a: number, b: number): number {
  return b > a ? b : a;
}

/** Preserve participant order, exact message labels and sequence_idx. */
export function render_sequence_messages(manifest: Dict, structure: Dict): Dict {
  structure = unwrap_structure_instantiation(structure);
  const output = pyDeepcopy(manifest);
  const meta = pySetdefault<unknown>(output, '_meta', {}) as Dict;
  let id_map = pySetdefault<unknown>(meta, 'id_map', {}) as Record<string, string>;
  const nodes = pyGet(structure, 'nodes', []) as Dict[];
  const edges = pySorted(pyGet(structure, 'edges', []) as Dict[], (edge) => pyGetItem(edge, 'sequence_idx'));
  const by_id = new Map<unknown, Dict>();
  for (const element of output.elements as Dict[]) by_id.set(pyGetItem(element, 'id'), element);
  const semantic_edge_id = (item: Dict) => pyGet(pyOr(pyGet(item, 'meta'), {}), 'semantic_edge_id');
  const old_messages = new Map<unknown, Dict>();
  for (const item of output.elements as Dict[]) {
    if (pyGet(item, 'type') === 'arrow') old_messages.set(semantic_edge_id(item), item);
  }
  const old_labels = new Map<unknown, Dict>();
  for (const item of output.elements as Dict[]) {
    if (pyGet(item, 'type') === 'text' && truthy(semantic_edge_id(item))) old_labels.set(semantic_edge_id(item), item);
  }
  const headers = new Map<unknown, Dict | null>();
  for (const node of nodes) headers.set(pyGetItem(node, 'id'), by_id.get(pyGet(id_map, node.id)) ?? null);
  if ([...headers.values()].some((header) => header === null)) {
    throw new ValueError('Sequence diagram is missing a participant header');
  }
  const actor_ids = nodes.map((node) => pyGet(node, 'actor_id', node.id));
  if (new Set(actor_ids).size !== actor_ids.length) {
    throw new ValueError('Sequence diagrams require one semantic node per participant; activations are visual annotations');
  }
  const old_arrow_ids = new Set<unknown>();
  for (const item of output.elements as Dict[]) if (pyGet(item, 'type') === 'arrow') old_arrow_ids.add(item.id);
  const removed_ids = new Set<unknown>();
  for (const item of output.elements as Dict[]) {
    if (
      pyGet(item, 'type') === 'arrow'
      || old_arrow_ids.has(pyGet(item, 'containerId'))
      || ['lifeline', 'message_label'].includes(pyGet(pyOr(pyGet(item, 'meta'), {}), 'sequence_role') as string)
    ) {
      removed_ids.add(item.id);
    }
  }
  output.elements = (output.elements as Dict[]).filter((item) => !removed_ids.has(item.id));
  const filtered: Record<string, string> = {};
  for (const [key, value] of pyItems(id_map)) if (!removed_ids.has(value)) filtered[key as string] = value;
  meta.id_map = id_map = filtered;
  for (const item of output.elements as Dict[]) {
    item.boundElements = (pyOr(pyGet(item, 'boundElements'), []) as Dict[]).filter((bound) => !removed_ids.has(pyGet(bound, 'id')));
  }
  sync_node_icons(output);
  const payloads = pyGet(meta, 'edge_data', {}) as Dict;
  const labels = new Map<unknown, [string, number, { width: number; height: number }]>();
  let spacing = pyMax([...headers.values()].map((header) => _float(header!.width) + 64), null, 240) as number;
  const indices = new Map<unknown, number>();
  nodes.forEach((node, i) => indices.set(node.id, i));
  for (const edge of edges) {
    const payload = pyGet(payloads, edge.id, {}) as Dict;
    let label: unknown = pyOr(pyOr(pyGet(edge, 'label'), pyGet(edge, 'relation')), '');
    if (isDict(label)) label = pyGet(label, 'text', '');
    let font_size: number = isDict(pyGet(payload, 'label'))
      ? _float(pyGet(pyOr(pyGet(payload, 'label'), {}), 'fontSize', 14))
      : 14;
    font_size = _float(pyGet(old_labels.get(edge.id) ?? {}, 'fontSize', font_size));
    const dimensions = _estimate_text_dimensions(pyStr(label), font_size);
    labels.set(edge.id, [pyStr(label), font_size, dimensions]);
    const distance = Math.abs(indices.get(edge.source)! - indices.get(edge.target)!);
    if (truthy(distance)) spacing = _max2(spacing, (dimensions.width + 48) / distance);
  }
  const first_header = headers.get(nodes[0].id)!;
  const left = _float(first_header.x) + _float(first_header.width) / 2 - spacing / 2;
  const top = pyMin([...headers.values()].map((header) => _float(header!.y))) as number;
  const header_height = pyMax([...headers.values()].map((header) => _float(header!.height))) as number;
  const centers = new Map<unknown, number>();
  nodes.forEach((node, index) => {
    const header = headers.get(node.id)!;
    const center_x = left + spacing / 2 + index * spacing;
    const dx = center_x - (_float(header.x) + _float(header.width) / 2);
    Object.assign(header, { x: center_x - _float(header.width) / 2, y: top, height: header_height, angle: 0 });
    // float(...) arithmetic: x/y/height are floats; ``angle=0`` is an int.
    markF(header, 'x', true);
    markF(header, 'y', true);
    markF(header, 'height', true);
    markF(header, 'angle', false);
    for (const item of output.elements as Dict[]) {
      if (pyEq(pyGet(item, 'containerId'), header.id)) {
        item.x = (item.x as number) + dx;
        item.y = top + (header_height - _float(item.height)) / 2;
        markF(item, 'x', true);
        markF(item, 'y', true);
      }
    }
    centers.set(node.id, center_x);
  });
  sync_node_icons(output);
  const row_height = pyMax([64.0, ...[...labels.values()].map(([, , dimensions]) => _float(dimensions.height) + 36)]) as number;
  const first_y = top + header_height + 56;
  const bottom = first_y + row_height * _max2(edges.length - 1, 0) + 48;
  // Lane backgrounds are navigation only; headers already carry their labels.
  for (const group of pyGet(structure, 'groups', []) as Dict[]) {
    const members = pyGet(group, 'members', []) as unknown[];
    const found = members.find((member) => centers.has(member));
    const member = found === undefined ? null : found;
    for (const key of [group.id as string, `${group.id as string}:background`]) {
      const frame = by_id.get(pyGet(id_map, key)) ?? null;
      if (frame !== null && member !== null) {
        Object.assign(frame, {
          x: centers.get(member)! - spacing / 2,
          y: top - 16,
          width: spacing,
          height: bottom - top + 32,
          opacity: 0,
          is_group: true,
        });
        for (const key of ['x', 'y', 'width', 'height']) markF(frame, key, true);
        markF(frame, 'opacity', false);
        for (const item of output.elements as Dict[]) {
          if (pyEq(pyGet(item, 'containerId'), frame.id)) {
            item.opacity = 0;
            markF(item, 'opacity', false);
          }
        }
      }
    }
    const title = by_id.get(pyGet(id_map, `${group.id as string}:title`)) ?? null;
    if (title !== null) {
      Object.assign(title, { opacity: 0, x: centers.has(member) ? centers.get(member) : left, y: top });
      markF(title, 'opacity', false);
      markF(title, 'x', true);
      markF(title, 'y', true);
    }
  }
  for (const node of nodes) {
    const semantic_id = `${node.id as string}:lifeline`;
    const line_id = _generate_excalidraw_id(['sequence', semantic_id]);
    id_map[semantic_id] = line_id;
    (output.elements as Dict[]).push({
      ..._excalidraw_defaults(['sequence', semantic_id]),
      id: line_id,
      type: 'line',
      x: centers.get(node.id),
      y: top + header_height,
      width: 0,
      height: bottom - top - header_height,
      points: [[0, 0], [0, bottom - top - header_height]],
      strokeColor: '#94A3B8',
      backgroundColor: 'transparent',
      strokeStyle: 'dashed',
      strokeWidth: 1,
      roughness: 0,
      roundness: null,
      startArrowhead: null,
      endArrowhead: null,
      meta: { sequence_role: 'lifeline', actor_id: node.id },
    });
    const line = (output.elements as Dict[])[(output.elements as Dict[]).length - 1];
    markF(line, 'x', true);
    markF(line, 'y', true);
    markF(line, 'height', true);
    markF((line.points as number[][])[1], 1, true); // [[0, 0], [0, float]]
  }
  edges.forEach((edge, index) => {
    const [label, font_size, dimensions] = labels.get(edge.id)!;
    const payload = pyGet(payloads, edge.id, {}) as Dict;
    const previous = old_messages.get(edge.id) ?? {};
    const x1 = centers.get(edge.source)!;
    const x2 = centers.get(edge.target)!;
    const y = first_y + index * row_height;
    let points: number[][] = [[0, 0], [x2 - x1, 0]];
    if (pyEq(edge.source, edge.target)) {
      // A self-message has a short rectangular return, consuming one row.
      const loop = _max2(88, dimensions.width + 24);
      points = [[0, 0], [loop, 0], [loop, 24], [0, 24]];
    }
    const arrow_id = _generate_excalidraw_id(['sequence-message', edge.id]);
    id_map[edge.id as string] = arrow_id;
    const kind = pyLower(pyStr(pyOr(pyOr(pyGet(edge, 'message_kind'), pyGet(edge, 'message_type')), '')));
    const stroke_style = ['return', 'reply', 'response'].includes(kind)
      ? 'dashed'
      : pyGet(previous, 'strokeStyle', pyGet(payload, 'strokeStyle', 'solid'));
    (output.elements as Dict[]).push({
      ..._excalidraw_defaults(['sequence-message', edge.id]),
      id: arrow_id,
      type: 'arrow',
      x: x1,
      y,
      width: pyMax(points.map((point) => Math.abs(point[0]))),
      height: pyMax(points.map((point) => point[1])),
      points,
      strokeColor: pyGet(previous, 'strokeColor', pyGet(payload, 'strokeColor', '#475569')),
      strokeWidth: pyGet(previous, 'strokeWidth', pyGet(payload, 'strokeWidth', 1.5)),
      strokeStyle: stroke_style,
      roughness: 0,
      roundness: null,
      elbowed: false,
      startArrowhead: null,
      endArrowhead: 'triangle',
      startBinding: null,
      endBinding: null,
      meta: { semantic_edge_id: edge.id, source: edge.source, target: edge.target, sequence_idx: edge.sequence_idx },
    });
    const message = (output.elements as Dict[])[(output.elements as Dict[]).length - 1];
    markF(message, 'x', true);
    markF(message, 'y', true);
    if (pyEq(edge.source, edge.target)) {
      // max(88, width + 24) keeps the int 88 unless the float is larger.
      const loop_f = dimensions.width + 24 > 88;
      markF(points[1], 0, loop_f);
      markF(points[2], 0, loop_f);
      markF(message, 'width', loop_f);
    } else {
      markF(points[1], 0, true); // x2 - x1
      markF(message, 'width', Math.abs(points[1][0]) > 0); // max(abs(0), abs(float))
    }
    markF(message, 'strokeWidth', Object.prototype.hasOwnProperty.call(previous, 'strokeWidth')
      ? isF(previous, 'strokeWidth')
      : isF(payload, 'strokeWidth'));
    if (truthy(label)) {
      const text_id = _generate_excalidraw_id(['sequence-label', edge.id]);
      id_map[`${edge.id as string}:label`] = text_id;
      const label_center = x1 !== x2 ? (x1 + x2) / 2 : x1 + points[1][0] / 2;
      (output.elements as Dict[]).push({
        ..._excalidraw_defaults(['sequence-label', edge.id]),
        id: text_id,
        type: 'text',
        x: label_center - dimensions.width / 2,
        y: y - dimensions.height - 8,
        width: dimensions.width,
        height: dimensions.height,
        text: label,
        originalText: label,
        fontSize: font_size,
        fontFamily: 2,
        strokeColor: pyGet(old_labels.get(edge.id) ?? {}, 'strokeColor', '#1E293B'),
        textAlign: 'center',
        verticalAlign: 'middle',
        containerId: null,
        autoResize: true,
        lineHeight: 1.2,
        meta: { sequence_role: 'message_label', semantic_edge_id: edge.id },
      });
      const text = (output.elements as Dict[])[(output.elements as Dict[]).length - 1];
      markF(text, 'x', true);
      markF(text, 'y', true);
      markF(text, 'width', isF(dimensions, 'width'));
      markF(text, 'height', isF(dimensions, 'height'));
      markF(text, 'fontSize', true); // float(...)
    }
  });
  return normalize_excalidraw_manifest(output) as Dict;
}
