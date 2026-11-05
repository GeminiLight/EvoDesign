// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_routing/ports.py — keep in sync.
//
// Face selection and port/corridor ranks, decided for all edges at once.
//
// Each edge becomes a plan dict holding its relation, endpoint shapes, chosen
// faces and obstacles. Ranks are then assigned across siblings so that edges
// sharing a node face fan out instead of collapsing onto the face midpoint.

import { pyGet } from '../../../py/dict.ts';
import { pyIn } from '../../../py/eq.ts';
import * as logging from '../../../py/logging.ts';
import { pySort, pySorted } from '../../../py/sort.ts';
import { pyStr } from '../../../py/str.ts';
import { isDict, isStr, truthy } from '../../../py/truthy.ts';
import {
  audit_sides,
  extract_side_from_port,
  find_shape_id,
  normalize_port,
  resolve_edge_payload,
  shape_bbox,
} from '../../shared/edge_routing.ts';
import { DiagramContext } from './context.ts';
import { type ObstacleIndex, _edge_obstacles, _prefer_clear_port_pair } from './detours.ts';
import { _bbox_center } from './geometry.ts';

type Dict = Record<string, unknown>;

const logger = logging.getLogger('evodesign.agentic_system.render_engine.excalidraw.arrow_routing.ports');

export type EdgePlan = Dict;

/**
 * ``collections.defaultdict`` keyed by tuples (arrays). Keys are matched by
 * value (JSON of the tuple), and iteration yields the first-inserted tuple
 * object, so the dict compares like the Python one. ``getItem`` is
 * ``d[key]`` (inserts the default when missing); ``get`` is ``d.get(key)``.
 */
export class TupleDefaultDict<V> extends Map<unknown, V> {
  readonly #canonical = new Map<string, unknown>();
  readonly #factory: () => V;

  constructor(factory: () => V, entries?: Iterable<readonly [unknown, V]> | Record<string, V> | null) {
    super();
    this.#factory = factory;
    if (entries) {
      const pairs = isDict(entries) ? Object.entries(entries) : entries;
      for (const [key, value] of pairs as Iterable<readonly [unknown, V]>) this.set(key, value);
    }
  }

  static #serialize(key: unknown): string {
    return typeof key === 'string' ? `s:${key}` : JSON.stringify(key);
  }

  override has(key: unknown): boolean {
    return this.#canonical.has(TupleDefaultDict.#serialize(key));
  }

  override get(key: unknown): V | undefined {
    const serialized = TupleDefaultDict.#serialize(key);
    if (!this.#canonical.has(serialized)) return undefined;
    return super.get(this.#canonical.get(serialized));
  }

  override set(key: unknown, value: V): this {
    const serialized = TupleDefaultDict.#serialize(key);
    if (!this.#canonical.has(serialized)) this.#canonical.set(serialized, key);
    return super.set(this.#canonical.get(serialized), value);
  }

  override delete(key: unknown): boolean {
    const serialized = TupleDefaultDict.#serialize(key);
    if (!this.#canonical.has(serialized)) return false;
    const canonical = this.#canonical.get(serialized);
    this.#canonical.delete(serialized);
    return super.delete(canonical);
  }

  override clear(): void {
    this.#canonical.clear();
    super.clear();
  }

  /** ``d[key]`` for a defaultdict: inserts ``factory()`` when missing. */
  getItem(key: unknown): V {
    if (!this.has(key)) this.set(key, this.#factory());
    return this.get(key) as V;
  }
}

/** ``d[key]`` on a string-keyed ``defaultdict(int)`` held as a plain object. */
export function _defaultdict_int_getitem(mapping: Record<string, number> | Map<unknown, number>, key: string): number {
  if (mapping instanceof TupleDefaultDict) return mapping.getItem(key);
  if (mapping instanceof Map) {
    if (!mapping.has(key)) mapping.set(key, 0);
    return mapping.get(key)!;
  }
  if (!Object.prototype.hasOwnProperty.call(mapping, key)) mapping[key] = 0;
  return mapping[key];
}

/** Dataclass ``PortTotals``; tuple-keyed counters are ``TupleDefaultDict``s, node-keyed ones plain objects. */
export class PortTotals {
  // (source, start_side, end_side) -> edges sharing one bend corridor
  corridor_counts: TupleDefaultDict<number>;
  // (node, side) -> edges using that face, outgoing and incoming
  source_port_counts: TupleDefaultDict<number>;
  target_port_counts: TupleDefaultDict<number>;
  source_degrees: Record<string, number>;
  target_degrees: Record<string, number>;

  constructor(
    corridor_counts: TupleDefaultDict<number> = new TupleDefaultDict(() => 0),
    source_port_counts: TupleDefaultDict<number> = new TupleDefaultDict(() => 0),
    target_port_counts: TupleDefaultDict<number> = new TupleDefaultDict(() => 0),
    source_degrees: Record<string, number> = {},
    target_degrees: Record<string, number> = {},
  ) {
    this.corridor_counts = corridor_counts;
    this.source_port_counts = source_port_counts;
    this.target_port_counts = target_port_counts;
    this.source_degrees = source_degrees;
    this.target_degrees = target_degrees;
  }

  /** Rebuild from dataclass fields (e.g. a decoded fixture with Map / object counters). */
  static from_fields(fields: Dict | PortTotals): PortTotals {
    if (fields instanceof PortTotals) return fields;
    const counter = (value: unknown) => new TupleDefaultDict<number>(
      () => 0,
      value instanceof Map ? (value as Map<unknown, number>) : (value as Record<string, number>) ?? {},
    );
    const degrees = (value: unknown): Record<string, number> =>
      value instanceof Map ? Object.fromEntries(value) : { ...((value as Record<string, number>) ?? {}) };
    return new PortTotals(
      counter(fields.corridor_counts),
      counter(fields.source_port_counts),
      counter(fields.target_port_counts),
      degrees(fields.source_degrees),
      degrees(fields.target_degrees),
    );
  }
}

/** Choose architecture ports from layer semantics before raw geometry. */
export function _architecture_port_hint(
  source_ref: string,
  target_ref: string,
  source_shape: Dict,
  target_shape: Dict,
  node_group_ids: Record<string, string>,
  side_group_ids: Set<string>,
): Record<string, string> | null {
  const source_group = pyGet(node_group_ids, source_ref, '') as string;
  const target_group = pyGet(node_group_ids, target_ref, '') as string;
  const source_bbox = shape_bbox(source_shape);
  const target_bbox = shape_bbox(target_shape);
  const [source_x, source_y] = _bbox_center(source_bbox);
  const [target_x, target_y] = _bbox_center(target_bbox);

  if (pyIn(target_group, side_group_ids) || pyIn(source_group, side_group_ids)) {
    return source_x <= target_x ? { start: 'right', end: 'left' } : { start: 'left', end: 'right' };
  }

  const inter_layer = truthy(source_group) && truthy(target_group) && source_group !== target_group;
  const row_separation = Math.abs(target_y - source_y);
  const min_vertical_gap = (target_bbox.h > source_bbox.h ? target_bbox.h : source_bbox.h) + 24.0;
  if (inter_layer || row_separation >= min_vertical_gap) {
    return source_y <= target_y ? { start: 'bottom', end: 'top' } : { start: 'top', end: 'bottom' };
  }
  return null;
}

/** Authored faces: structure hints, then relation ports, then layout ports. */
export function _port_hint(rel: Dict, port_hints: Dict, edge_payload: Dict | null): Dict | null {
  const edge_id = pyGet(rel, 'id', '');
  let hinted = (isStr(edge_id) ? pyGet(port_hints, edge_id) : null) as Dict | null;
  if (!truthy(hinted)) {
    const start_hint = normalize_port(pyGet(rel, 'start') as string | null);
    const end_hint = normalize_port(pyGet(rel, 'end') as string | null);
    if (truthy(start_hint) && truthy(end_hint)) hinted = { start: start_hint, end: end_hint };
  }
  if (!truthy(hinted) && truthy(edge_payload)) {
    const start_hint = extract_side_from_port(pyGet(edge_payload!, 'start'));
    const end_hint = extract_side_from_port(pyGet(edge_payload!, 'end'));
    if (truthy(start_hint) || truthy(end_hint)) hinted = { start: start_hint, end: end_hint };
  }
  return hinted;
}

/** Resolve each relation's shapes and faces; drop relations without shapes. */
export function _plan_edges(
  relations: Dict[],
  store: Dict,
  structure_instantiation: Dict,
  edge_data: Dict,
  port_hints: Dict,
  diagram: DiagramContext,
  obstacle_index: ObstacleIndex,
): EdgePlan[] {
  const plans: EdgePlan[] = [];
  for (const rel of relations) {
    const source_ref = pyGet(rel, 'source', '') as string;
    const target_ref = pyGet(rel, 'target', '') as string;
    const edge_payload = resolve_edge_payload(edge_data as Record<string, Dict>, pyGet(rel, 'id', ''));

    const source_shape_key = find_shape_id(store, source_ref, structure_instantiation);
    const target_shape_key = find_shape_id(store, target_ref, structure_instantiation);
    if (!(truthy(source_shape_key) && truthy(target_shape_key))) {
      logger.warning(`Could not find shapes for relation source='${pyStr(source_ref)}' -> target='${pyStr(target_ref)}'`);
      continue;
    }
    const source_shape = store[source_shape_key!] as Dict;
    const target_shape = store[target_shape_key!] as Dict;

    let hinted = _port_hint(rel, port_hints, edge_payload);
    if (diagram.is_architecture) {
      const architecture_hint = _architecture_port_hint(
        pyStr(source_ref),
        pyStr(target_ref),
        source_shape,
        target_shape,
        diagram.node_group_ids,
        diagram.side_group_ids,
      );
      hinted = truthy(architecture_hint) ? architecture_hint : hinted;
    }

    let [start_edge, end_edge] = audit_sides(hinted, source_shape, target_shape);
    const source_bbox = shape_bbox(source_shape);
    const target_bbox = shape_bbox(target_shape);
    const obstacles = _edge_obstacles(
      obstacle_index, source_shape._excalidraw_id as string, target_shape._excalidraw_id as string,
    );
    [start_edge, end_edge] = _prefer_clear_port_pair(start_edge, end_edge, source_bbox, target_bbox, obstacles);
    plans.push({
      rel,
      source_ref,
      target_ref,
      source_shape,
      target_shape,
      source_bbox,
      target_bbox,
      obstacles,
      start_edge,
      end_edge,
      edge_payload,
    });
  }
  return plans;
}

/** Order ports along a face by where the opposite endpoint sits. */
export function _port_order_key(item: EdgePlan, shape_key: string, side: string): [number, number, string] {
  const [center_x, center_y] = _bbox_center(shape_bbox(item[shape_key] as Dict));
  let primary: number;
  let secondary: number;
  if (side === 'left') [primary, secondary] = [center_y, center_x];
  else if (side === 'right') [primary, secondary] = [center_y, -center_x];
  else if (side === 'top') [primary, secondary] = [center_x, center_y];
  else [primary, secondary] = [center_x, -center_y];
  return [primary, secondary, pyStr(pyGet(item.rel as Dict, 'id', ''))];
}

/** ``defaultdict(list)`` keyed by tuples: insertion-ordered ``[key, siblings]`` groups. */
class _Groups<K extends unknown[]> {
  readonly entries = new Map<string, [K, EdgePlan[]]>();

  append(key: K, plan: EdgePlan): void {
    const serialized = JSON.stringify(key);
    if (!this.entries.has(serialized)) this.entries.set(serialized, [key, []]);
    this.entries.get(serialized)![1].push(plan);
  }

  get(key: K): EdgePlan[] {
    return this.entries.get(JSON.stringify(key))![1];
  }

  has(key: K): boolean {
    return this.entries.has(JSON.stringify(key));
  }
}

/** Rank every edge on its faces and corridors; return the sibling counts. */
export function _assign_port_ranks(plans: EdgePlan[]): PortTotals {
  const totals = new PortTotals();
  const source_groups = new _Groups<[string, string]>();
  const target_groups = new _Groups<[string, string]>();
  const corridor_groups = new _Groups<[string, string, string]>();
  const all_source_groups = new _Groups<[string]>();
  const all_target_groups = new _Groups<[string]>();
  const increment = (counter: TupleDefaultDict<number>, key: unknown[]) => counter.set(key, counter.getItem(key) + 1);
  for (const plan of plans) {
    const source_ref = plan.source_ref as string;
    const target_ref = plan.target_ref as string;
    const corridor_key: [string, string, string] = [source_ref, plan.start_edge as string, plan.end_edge as string];
    increment(totals.corridor_counts, corridor_key);
    // Port fan-out is independent of the target orientation; the target
    // side is grouped separately for fan-in at a shared face.
    increment(totals.source_port_counts, [source_ref, plan.start_edge as string]);
    increment(totals.target_port_counts, [target_ref, plan.end_edge as string]);
    totals.source_degrees[source_ref] = _defaultdict_int_getitem(totals.source_degrees, source_ref) + 1;
    totals.target_degrees[target_ref] = _defaultdict_int_getitem(totals.target_degrees, target_ref) + 1;
    source_groups.append([source_ref, plan.start_edge as string], plan);
    target_groups.append([target_ref, plan.end_edge as string], plan);
    corridor_groups.append(corridor_key, plan);
    all_source_groups.append([source_ref], plan);
    all_target_groups.append([target_ref], plan);
  }

  // Ports follow the opposite endpoint's visual order, while bend corridors
  // put the farthest branch closest to the source.
  for (const [groups, role, opposite] of [
    [source_groups, 'source', 'target_shape'],
    [target_groups, 'target', 'source_shape'],
  ] as const) {
    for (const [[, side], siblings] of groups.entries.values()) {
      const ordered = pySorted(siblings, (item) => _port_order_key(item, opposite, side));
      ordered.forEach((item, rank) => {
        item[`${role}_port_index`] = rank;
      });
    }
  }

  // Incoming and outgoing edges occupy the same physical node face. Reserve
  // ports together. (Python iterates a key-set intersection; each key writes
  // disjoint fields, so the iteration order does not matter.)
  for (const [key] of source_groups.entries.values()) {
    if (!target_groups.has(key)) continue;
    const side = key[1];
    const endpoints: [EdgePlan, string, string][] = source_groups.get(key).map((item) => [item, 'source', 'target_shape']);
    endpoints.push(...target_groups.get(key).map((item) => [item, 'target', 'source_shape'] as [EdgePlan, string, string]));
    pySort(endpoints, (entry) => _port_order_key(entry[0], entry[2], side));
    totals.source_port_counts.set(key, endpoints.length);
    totals.target_port_counts.set(key, endpoints.length);
    endpoints.forEach(([item, role], rank) => {
      item[`${role}_port_index`] = rank;
    });
  }

  for (const [, siblings] of corridor_groups.entries.values()) {
    if (siblings.length <= 1) {
      siblings[0].stagger_index = 0;
      continue;
    }
    const cross_axis = ['top', 'bottom'].includes(siblings[0].start_edge as string) ? 0 : 1;
    const travel_axis = 1 - cross_axis;

    const cross_distance = (item: EdgePlan): number => {
      const source_center = _bbox_center(item.source_bbox as Dict);
      const target_center = _bbox_center(item.target_bbox as Dict);
      return Math.abs(target_center[cross_axis] - source_center[cross_axis]);
    };

    const ordered = pySorted(siblings, cross_distance, true);
    const source_axis = _bbox_center(siblings[0].source_bbox as Dict)[travel_axis];
    let total = 0;
    for (const item of siblings) total += _bbox_center(item.target_bbox as Dict)[travel_axis];
    const average_target_axis = total / siblings.length;
    const ranks = ordered.map((_, index) => index);
    if (!(average_target_axis >= source_axis)) ranks.reverse();
    ordered.forEach((item, index) => {
      item.stagger_index = ranks[index];
    });
  }

  // Per-node ranks along each axis, used when a later pass moves an edge
  // to a different face of the same node.
  for (const [groups, role, opposite] of [
    [all_source_groups, 'source', 'target_bbox'],
    [all_target_groups, 'target', 'source_bbox'],
  ] as const) {
    for (const [, siblings] of groups.entries.values()) {
      for (const [axis, key] of [[0, `${role}_x_index`], [1, `${role}_y_index`]] as const) {
        const ordered = pySorted(siblings, (value) => _bbox_center(value[opposite] as Dict)[axis]);
        ordered.forEach((item, rank) => {
          item[key] = rank;
        });
      }
    }
  }
  return totals;
}

