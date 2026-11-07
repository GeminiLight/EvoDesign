// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_adder.py — keep in sync.
//
// Excalidraw Arrow Adder - Add directional arrows to an Excalidraw manifest.
//
// The pass runs in stages; the routing primitives live in ``arrow_routing``:
// 1. Plan: resolve each relation's shapes, pick its faces, rank its ports.
// 2. Route: draw every edge in turn, avoiding nodes and earlier edges.
// 3. Optimize: scene-wide passes that trade routes for fewer crossings.
// 4. Label: filter and place edge labels on the final routes.
// 5. Compare: keep midpoint ports instead when fan-out added crossings.

import { copyF, markF, pyUpdate } from '../../py/float_marks.ts';
import { pyDeepcopy } from '../../py/float_marks.ts';
import { id_map_from_manifest, reverse_id_map } from '../../common/semantic_ids.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { pyGet, pyPop, pySetdefault } from '../../py/dict.ts';
import { ValueError } from '../../py/errors.ts';
import * as logging from '../../py/logging.ts';
import { pyFloatParse, pyInt } from '../../py/number.ts';
import { pyLower, pySplit, pyStr } from '../../py/str.ts';
import { isDict, pyOr, truthy } from '../../py/truthy.ts';
import { detect_crossings } from '../shared/edge_crossing_detector.ts';
import {
  collect_relations,
  derive_routing_from_sides,
  extract_edge_port_hints,
  normalize_routing,
  relations_from_edge_data,
} from '../shared/edge_routing.ts';
import { sequential_index } from '../shared/order_keys.ts';
import { DiagramContext, _diagram_context } from './arrow_routing/context.ts';
import { _avoid_node_intersections, _obstacle_index } from './arrow_routing/detours.ts';
import { _arrow_path_fields, _box_tuple, type BBox } from './arrow_routing/geometry.ts';
import { _ROUTE_MEMO } from './arrow_routing/grid_router.ts';
import {
  _compute_label_geometry,
  _detach_concept_labels,
  _edge_label_payload,
  _merge_semantic_edge_labels,
  _node_label_lookup,
  _normalize_label_payload,
  _position_architecture_bound_labels,
  _reposition_edge_labels,
  _should_drop_edge_label,
} from './arrow_routing/labels.ts';
import {
  _reduce_crossings,
  _reroute_architecture_edges,
  _route_concept_corridors,
  _separate_final_channels,
  _spread_final_target_ports,
} from './arrow_routing/passes.ts';
import { type EdgePlan, PortTotals, _assign_port_ranks, _defaultdict_int_getitem, _plan_edges } from './arrow_routing/ports.ts';
import { _excalidraw_defaults, _generate_excalidraw_id } from './converter.ts';
import { compute_waypoints, type WayPoint } from './edge_router.ts';
import { render_sequence_messages } from './sequence_layout.ts';

type Dict = Record<string, unknown>;

const logger = logging.getLogger('evodesign.agentic_system.render_engine.excalidraw.arrow_adder');

export const DEFAULT_STAGGER_SPACING = 50.0;
export const DEFAULT_PORT_SPACING = 32.0;

// routing controls both ``elbowed`` and ``roundness``:
//   straight → elbowed=False, roundness=None
//   elbowed  → elbowed=True,  roundness=None
//   curved   → elbowed=True,  roundness={"type": 2}
// Unknown routing is drawn as a straight polyline.
export const _ELBOWED_ROUTINGS: ReadonlySet<string> = new Set(['elbowed', 'curved']);
export const _EDGE_STYLE_KEYS = ['strokeColor', 'strokeWidth', 'strokeStyle', 'opacity', 'roughness'] as const;

function _has(mapping: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(mapping, key);
}

/** Build a shape lookup store (``shape:{semantic_id}`` -> shape-like entry) from Excalidraw elements. */
export function _build_lookup_store(elements: Dict[], id_map: Record<string, string>): Dict {
  const store: Dict = {};
  const reverse_map = reverse_id_map(id_map);
  for (const elem of elements) {
    const eid = pyGet(elem, 'id', '');
    const semantic_id = pyGet(reverse_map, eid);
    if (!truthy(semantic_id)) continue;
    store[`shape:${pyStr(semantic_id)}`] = {
      x: pyGet(elem, 'x', 0),
      y: pyGet(elem, 'y', 0),
      type: pyGet(elem, 'type', 'rectangle'),
      props: {
        w: pyGet(elem, 'width', 100),
        h: pyGet(elem, 'height', 100),
      },
      parentId: 'page:page',
      _excalidraw_id: eid,
    };
  }
  return store;
}

/** Show a core concept's repeated structural predicate only once. */
export function _mark_repeated_concept_labels(plans: EdgePlan[], core_node_ids: Set<string>): null {
  const repeated = new Map<string, [[string, string], EdgePlan[]]>();
  for (const plan of plans) {
    const normalized = _normalize_label_payload(_edge_label_payload(plan.rel as Dict, pyGet(plan, 'edge_payload') as Dict | null));
    if (!truthy(normalized)) continue;
    const label_key = pySplit(pyLower(normalized!.text as string)).join(' ');
    const key: [string, string] = [pyStr(pyGet(plan.rel as Dict, 'source', '')), label_key];
    const serialized = JSON.stringify(key);
    if (!repeated.has(serialized)) repeated.set(serialized, [key, []]);
    repeated.get(serialized)![1].push(plan);
  }
  for (const [[source_ref, label_key], siblings] of repeated.values()) {
    if (
      siblings.length >= 2
      && core_node_ids.has(source_ref)
      && (label_key === 'organized into' || siblings.every((item) => pyGet(item.rel as Dict, 'evidence_basis') === 'structural'))
    ) {
      for (const item of siblings) item.suppress_repeated_label = true;
    }
  }
  return null;
}

/** First route for one edge: staggered face ports, then node avoidance. */
export function _route_edge(plan: EdgePlan, totals: PortTotals, existing: Dict[], port_spacing: number): WayPoint[] {
  const source_ref = plan.source_ref as string;
  const target_ref = plan.target_ref as string;
  const start_edge = plan.start_edge as string;
  const end_edge = plan.end_edge as string;
  const [waypoints] = compute_waypoints(
    start_edge,
    end_edge,
    plan.source_bbox as Dict,
    plan.target_bbox as Dict,
    undefined,
    undefined,
    pyInt(pyGet(plan, 'stagger_index', 0) as number),
    totals.corridor_counts.getItem([source_ref, start_edge, end_edge]),
    DEFAULT_STAGGER_SPACING,
    pyInt(pyGet(plan, 'source_port_index', 0) as number),
    totals.source_port_counts.getItem([source_ref, start_edge]),
    pyInt(pyGet(plan, 'target_port_index', 0) as number),
    totals.target_port_counts.getItem([target_ref, end_edge]),
    port_spacing,
  );
  return _avoid_node_intersections(
    waypoints,
    plan.obstacles as number[][],
    undefined,
    existing,
    [_box_tuple(plan.source_bbox as BBox), _box_tuple(plan.target_bbox as BBox)],
  );
}

export function _arrow_element(plan: EdgePlan, waypoints: WayPoint[], index: string, chart_type: unknown): Dict {
  const rel = plan.rel as Dict;
  const edge_payload = plan.edge_payload as Dict | null;
  const source_ref = plan.source_ref;
  const target_ref = plan.target_ref;
  const edge_id = pyGet(rel, 'id', '');
  const edge_seed = [
    'edge',
    truthy(edge_id) ? edge_id : `${pyStr(source_ref)}->${pyStr(target_ref)}`,
    source_ref,
    target_ref,
    pyInt(pyGet(plan, 'stagger_index', 0) as number),
    plan.start_edge,
    plan.end_edge,
  ];
  const arrow: Dict = {
    ..._excalidraw_defaults(['arrow', edge_seed]),
    id: _generate_excalidraw_id(edge_seed),
    type: 'arrow',
    index,
    strokeColor: '#64748B',
    strokeWidth: 1.5,
    roughness: 0,
    meta: {
      semantic_edge_id: edge_id,
      source: source_ref,
      target: target_ref,
    },
    ..._arrow_path_fields(waypoints),
    startArrowhead: null,
    endArrowhead: 'arrow',
    lastCommittedPoint: null,
  };
  for (const key of ['x', 'y', 'width', 'height']) markF(arrow, key, true); // _arrow_path_fields: floats

  let routing = truthy(edge_payload) ? normalize_routing(pyGet(edge_payload!, 'routing')) : null;
  if (routing === null) routing = normalize_routing(pyGet(rel, 'routing'));
  if (routing === null) {
    // Diagram-type-aware fallback (e.g. mindmap radial branches are curved).
    routing = derive_routing_from_sides(plan.start_edge as string, plan.end_edge as string, chart_type as string | null);
  }
  arrow.elbowed = _ELBOWED_ROUTINGS.has(routing);
  arrow.roundness = routing === 'curved' ? { type: 2 } : null;

  // Authored arrowheads and stroke styling from the layout edge win.
  if (truthy(edge_payload)) {
    for (const key of ['startArrowhead', 'endArrowhead', ..._EDGE_STYLE_KEYS]) {
      if (_has(edge_payload!, key)) {
        arrow[key] = edge_payload![key];
        copyF(edge_payload, key, arrow, key);
      }
    }
    const props = pyGet(edge_payload!, 'props', {});
    if (isDict(props) && _has(props, 'color')) arrow.strokeColor = props.color;
  }
  return arrow;
}

/** Whether an authored label is drawn, or suppressed as noise. */
export function _keeps_edge_label(
  plan: EdgePlan,
  normalized: Dict,
  diagram: DiagramContext,
  node_label_map: Record<string, string>,
): boolean {
  const rel = plan.rel as Dict;
  const edge_payload = plan.edge_payload as Dict | null;
  if (truthy(edge_payload) && truthy(pyGet(edge_payload!, '_suppressLabel'))) return false;
  if (truthy(pyGet(plan, 'suppress_repeated_label'))) return false;
  // Deterministic stop-label filter.
  const drop_reason = _should_drop_edge_label(
    pyGet(normalized, 'text', ''),
    plan.source_ref,
    plan.target_ref,
    node_label_map,
    diagram.is_concept_map,
  );
  if (truthy(drop_reason)) {
    logger.info(`[ArrowAdder] dropping edge label edge=${pyStr(pyGet(rel, 'id', ''))} reason=${drop_reason}`);
    return false;
  }
  return true;
}

export function _label_element(arrow: Dict, label: Dict, waypoints: WayPoint[], index: string): Dict {
  const edge_id = (arrow.meta as Dict).semantic_edge_id;
  const ax = waypoints[0].x;
  const ay = waypoints[0].y;
  const geometry = _compute_label_geometry(
    ax,
    ay,
    waypoints[waypoints.length - 1].x - ax,
    waypoints[waypoints.length - 1].y - ay,
    arrow,
    label,
  );
  const text_seed = ['edge_label', truthy(edge_id) ? edge_id : arrow.id, label.text];
  return {
    ..._excalidraw_defaults(['edge_label', text_seed]),
    id: _generate_excalidraw_id(text_seed),
    type: 'text',
    index,
    ...geometry,
    text: label.text,
    fontSize: label.fontSize,
    fontFamily: label.fontFamily,
    strokeColor: label.strokeColor,
    textAlign: label.textAlign,
    verticalAlign: pyGet(label, 'verticalAlign', 'middle'),
    containerId: arrow.id,
    originalText: label.text,
    autoResize: true,
    lineHeight: 1.15,
    meta: { semantic_edge_id: edge_id },
  };
}

/** What the scene-wide passes need to reconsider one edge's route. */
export function _route_context(plan: EdgePlan, totals: PortTotals, diagram: DiagramContext): Dict {
  const source_ref = plan.source_ref as string;
  const target_ref = plan.target_ref as string;
  const edge_payload = plan.edge_payload as Dict | null;
  return {
    source_ref,
    target_ref,
    source_group: pyGet(diagram.node_group_ids, source_ref, ''),
    target_group: pyGet(diagram.node_group_ids, target_ref, ''),
    source_bbox: plan.source_bbox,
    target_bbox: plan.target_bbox,
    obstacles: plan.obstacles,
    start_side: plan.start_edge,
    end_side: plan.end_edge,
    source_x_index: pyInt(pyGet(plan, 'source_x_index', 0) as number),
    source_y_index: pyInt(pyGet(plan, 'source_y_index', 0) as number),
    target_x_index: pyInt(pyGet(plan, 'target_x_index', 0) as number),
    target_y_index: pyInt(pyGet(plan, 'target_y_index', 0) as number),
    source_degree: _defaultdict_int_getitem(totals.source_degrees, source_ref),
    target_degree: _defaultdict_int_getitem(totals.target_degrees, target_ref),
    cross_branch: truthy(edge_payload) && truthy(pyGet(edge_payload!, '_layoutCrossBranch')),
  };
}

/**
 * Add arrows; see :func:`_add_excalidraw_arrows_to_manifest`. The outermost
 * call owns the route memo, so nested comparison passes reuse routes and
 * nothing outlives one arrow pass.
 */
export function add_excalidraw_arrows_to_manifest(
  manifest: Dict,
  structure_instantiation: Dict,
  port_spacing: number | null = null,
  _adaptive_ports = true,
  _report_crossings = true,
): Dict {
  if (_ROUTE_MEMO.get() !== null) {
    return _add_excalidraw_arrows_to_manifest(manifest, structure_instantiation, port_spacing, _adaptive_ports, _report_crossings);
  }
  const token = _ROUTE_MEMO.set(new Map());
  try {
    return _add_excalidraw_arrows_to_manifest(manifest, structure_instantiation, port_spacing, _adaptive_ports, _report_crossings);
  } finally {
    _ROUTE_MEMO.reset(token);
  }
}

/** Add arrow elements to an Excalidraw manifest based on structure_instantiation edges. */
export function _add_excalidraw_arrows_to_manifest(
  manifest: Dict,
  structure_instantiation: Dict,
  port_spacing: number | null = null,
  _adaptive_ports = true,
  _report_crossings = true,
): Dict {
  const structure = unwrap_structure_instantiation(structure_instantiation);
  if (pyGet(structure, 'chart_type') === 'sequence_diagram') {
    return render_sequence_messages(manifest, structure_instantiation);
  }
  if (port_spacing === null || port_spacing === undefined) port_spacing = DEFAULT_PORT_SPACING;
  if (port_spacing < 0) throw new ValueError('port_spacing must be non-negative');
  manifest = pyDeepcopy(manifest);
  const elements = pyGet(manifest, 'elements', []) as Dict[];
  const id_map = id_map_from_manifest(manifest);
  const meta = pyGet(manifest, '_meta');
  let edge_data = (isDict(meta) ? pyGet(meta, 'edge_data', {}) : {}) as Dict;
  if (!isDict(edge_data)) edge_data = {};

  // Prefer layout-derived ``edge_data`` (same ID space as ``id_map``); fall
  // back to structure edges when it is missing.
  const layout_relations = truthy(edge_data) ? relations_from_edge_data(edge_data, new Set(Object.keys(id_map))) : [];
  let relations: Dict[];
  if (layout_relations.length) {
    relations = layout_relations;
    logger.info(`[ArrowAdder] Using ${relations.length} edges from manifest._meta.edge_data`);
  } else {
    relations = collect_relations(structure_instantiation);
    logger.info(`[ArrowAdder] edge_data empty - falling back to structure.edges (${relations.length} edges)`);
  }
  relations = _merge_semantic_edge_labels(relations, structure);
  const diagram = _diagram_context(structure, id_map, elements);

  // 1. Plan faces and port ranks for every edge.
  const plans = _plan_edges(
    relations,
    _build_lookup_store(elements, id_map),
    structure_instantiation,
    edge_data,
    extract_edge_port_hints(structure_instantiation),
    diagram,
    _obstacle_index(elements, id_map, diagram.group_frame_ids),
  );
  const totals = _assign_port_ranks(plans);
  if (diagram.is_concept_map) _mark_repeated_concept_labels(plans, diagram.core_node_ids);

  // 2. Route each edge around nodes and the edges drawn before it.
  const node_label_map = _node_label_lookup(structure_instantiation);
  let dropped_label_count = 0;
  const new_arrows: Dict[] = [];
  const route_contexts: Record<string, Dict> = Object.create(null);
  for (const plan of plans) {
    const waypoints = _route_edge(plan, totals, new_arrows, port_spacing);
    const arrow = _arrow_element(
      plan, waypoints, sequential_index(elements.length + new_arrows.length), pyGet(structure, 'chart_type'),
    );
    route_contexts[arrow.id as string] = _route_context(plan, totals, diagram);
    new_arrows.push(arrow);

    const label = _normalize_label_payload(_edge_label_payload(plan.rel as Dict, plan.edge_payload as Dict | null));
    if (!truthy(label)) continue;
    if (!_keeps_edge_label(plan, label!, diagram, node_label_map)) {
      dropped_label_count += 1;
      continue;
    }
    const text = _label_element(arrow, label!, waypoints, sequential_index(elements.length + new_arrows.length));
    arrow.boundElements = [{ type: 'text', id: text.id }];
    new_arrows.push(text);
  }

  // 3. Scene-wide route optimization.
  const arrow_elems = new_arrows.filter((element) =>
    pyGet(element, 'type') === 'arrow' && pyFloatParse(pyOr(pyGet(element, 'opacity', 100), 0) as number) > 0);
  const elements_by_id: Record<string, Dict> = Object.create(null);
  for (const element of new_arrows) pySetdefault<unknown>(elements_by_id, pyStr(pyGet(element, 'id', '')), element);
  if (arrow_elems.length) {
    _reduce_crossings(arrow_elems, route_contexts, elements_by_id, port_spacing);
    _route_concept_corridors(arrow_elems, route_contexts, elements_by_id, diagram.concept_frames, port_spacing);
  }
  if (diagram.is_architecture) {
    _reroute_architecture_edges(arrow_elems, route_contexts, diagram.side_group_ids, totals.source_degrees, totals.target_degrees);
  }
  _spread_final_target_ports(arrow_elems, route_contexts, port_spacing);
  _separate_final_channels(arrow_elems, route_contexts);

  // 4. Labels follow the final routes.
  _reposition_edge_labels(elements, new_arrows);
  if (diagram.is_architecture) {
    _position_architecture_bound_labels(elements, new_arrows, route_contexts, diagram.group_frame_ids);
  }
  if (diagram.is_concept_map) _detach_concept_labels(new_arrows);

  // 5. Compare against the same scene with midpoint ports and keep the
  // lower-crossing candidate.
  if (_adaptive_ports && port_spacing > 0) {
    const midpoint_manifest = add_excalidraw_arrows_to_manifest(manifest, structure_instantiation, 0.0, false, false);
    const midpoint_arrows = (pyGet(midpoint_manifest, 'elements', []) as Dict[]).filter((element) => pyGet(element, 'type') === 'arrow');
    const fanout_crossings = detect_crossings(arrow_elems).length;
    const midpoint_crossings = detect_crossings(midpoint_arrows).length;
    if (midpoint_crossings < fanout_crossings) {
      logger.info(`[ArrowAdder] midpoint ports selected (${midpoint_crossings} crossings vs ${fanout_crossings} with fan-out)`);
      return midpoint_manifest;
    }
  }

  elements.push(...new_arrows);
  manifest.elements = elements;

  if (_report_crossings) {
    // Observational crossing check — warn-only, no manifest changes.
    const crossings = detect_crossings(arrow_elems);
    for (const [a_id, b_id, crossing] of crossings) {
      logger.warning(
        `[CrossingDetector] Arrow ${a_id} crosses ${b_id} (segment a=${pyStr(pyGet(crossing, 'segment_index_a'))}, b=${pyStr(pyGet(crossing, 'segment_index_b'))})`,
      );
    }
    if (crossings.length) logger.warning(`[CrossingDetector] ${crossings.length} edge crossing pair(s) detected in manifest`);
    if (dropped_label_count) logger.warning(`[ArrowAdder] suppressed ${dropped_label_count} non-informative or repeated edge label(s)`);
  }

  return manifest;
}

/** Recompute arrow geometry after a deterministic node layout pass. */
export function rebuild_excalidraw_arrows(manifest: Dict, structure_instantiation: Dict): Dict {
  if (pyGet(unwrap_structure_instantiation(structure_instantiation), 'chart_type') === 'sequence_diagram') {
    return render_sequence_messages(manifest, structure_instantiation);
  }
  const source = pyDeepcopy(manifest);
  const elements = (pyGet(source, 'elements', []) as unknown[]).filter(isDict);
  const old_arrows = new Map<string, Dict>();
  for (const element of elements) {
    if (pyGet(element, 'type') === 'arrow' && truthy(pyGet(element, 'id'))) old_arrows.set(pyStr(element.id), element);
  }
  if (!old_arrows.size) return add_excalidraw_arrows_to_manifest(source, structure_instantiation);

  const old_styles = new Map<string, Dict>();
  const old_semantic_edge_ids = new Set<string>();
  for (const arrow of old_arrows.values()) {
    const meta = pyGet(arrow, 'meta');
    const edge_id = isDict(meta) ? pyStr(pyGet(meta, 'semantic_edge_id', '')) : '';
    if (edge_id) {
      old_semantic_edge_ids.add(edge_id);
      const style: Dict = {};
      for (const key of ['strokeColor', 'strokeWidth', 'strokeStyle', 'opacity', 'startArrowhead', 'endArrowhead']) {
        if (_has(arrow, key)) {
          style[key] = arrow[key];
          copyF(arrow, key, style, key);
        }
      }
      old_styles.set(edge_id, style);
    }
  }

  const old_arrow_ids = new Set(old_arrows.keys());
  const old_label_ids = new Set<string>();
  for (const element of elements) {
    if (
      pyGet(element, 'type') === 'text'
      && (
        old_arrow_ids.has(pyStr(pyGet(element, 'containerId', '')))
        || (isDict(pyGet(element, 'meta')) && old_semantic_edge_ids.has(pyStr(pyGet(element.meta as Dict, 'semantic_edge_id', ''))))
      )
      && truthy(pyGet(element, 'id'))
    ) {
      old_label_ids.add(pyStr(element.id));
    }
  }
  const edge_data = pyGet(pyOr(pyGet(source, '_meta'), {}), 'edge_data');
  if (isDict(edge_data)) {
    for (const element of elements) {
      if (!old_label_ids.has(pyStr(pyGet(element, 'id')))) continue;
      let edge_id = pyGet(pyOr(pyGet(element, 'meta'), {}), 'semantic_edge_id');
      if (!truthy(edge_id)) {
        const owner = old_arrows.get(pyStr(pyGet(element, 'containerId'))) ?? {};
        edge_id = pyGet(pyOr(pyGet(owner, 'meta'), {}), 'semantic_edge_id');
      }
      const payload = pyGet(edge_data, edge_id);
      if (!isDict(payload)) continue;
      let label = _normalize_label_payload(pyGet(payload, 'label'));
      if (label === null) label = _normalize_label_payload(pyGet(element, 'text'));
      if (label === null) continue;
      // Feed edited typography into routing before measuring labels.
      for (const key of ['fontSize', 'fontFamily', 'strokeColor', 'textAlign', 'verticalAlign']) {
        if (_has(element, key)) label[key] = element[key];
      }
      payload.label = label;
    }
  }
  const removed_ids = new Set<string>([...old_arrow_ids, ...old_label_ids]);
  const retained: Dict[] = [];
  for (const element of elements) {
    if (removed_ids.has(pyStr(pyGet(element, 'id', '')))) continue;
    const bound_elements = pyGet(element, 'boundElements');
    if (Array.isArray(bound_elements)) {
      element.boundElements = bound_elements.filter((binding) =>
        !(isDict(binding) && removed_ids.has(pyStr(pyGet(binding, 'id', '')))));
    }
    retained.push(element);
  }
  source.elements = retained;

  const rebuilt = add_excalidraw_arrows_to_manifest(source, structure_instantiation);
  const id_map: Record<string, string> = Object.create(null);
  for (const [key, value] of Object.entries(id_map_from_manifest(rebuilt))) {
    if (!removed_ids.has(value)) id_map[key] = value;
  }
  const semantic_edge_ids = new Set<string>();
  for (const edge of (pyOr(pyGet(unwrap_structure_instantiation(structure_instantiation), 'edges', []), []) as unknown[])) {
    if (isDict(edge) && truthy(pyGet(edge, 'id'))) semantic_edge_ids.add(pyStr(edge.id));
  }
  for (const edge_id of semantic_edge_ids) pyPop(id_map, edge_id, null);
  for (const element of (pyGet(rebuilt, 'elements', []) as unknown[])) {
    if (!isDict(element)) continue;
    const meta = pyGet(element, 'meta');
    const edge_id = isDict(meta) ? pyStr(pyGet(meta, 'semantic_edge_id', '')) : '';
    if (!edge_id) continue;
    if (pyGet(element, 'type') === 'text') {
      id_map[`${edge_id}:label`] = pyStr(pyGet(element, 'id', ''));
      continue;
    }
    if (pyGet(element, 'type') !== 'arrow') continue;
    pyUpdate(element, old_styles.get(edge_id) ?? {});
    id_map[edge_id] = pyStr(pyGet(element, 'id', ''));
  }

  const meta = pySetdefault<unknown>(rebuilt, '_meta', {});
  if (isDict(meta)) meta.id_map = id_map;
  return rebuilt;
}
