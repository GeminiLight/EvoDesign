// Ported from evodesign/agentic_system/render_engine/excalidraw/arrow_routing/passes.py — keep in sync.
//
// Scene-wide route optimization once every edge has a first route.
//
// Each pass mutates the arrow elements in place and records the faces it
// chose in ``route_contexts`` so later passes and label placement agree.

import { markF, pyMerge, pyUpdate } from '../../../py/float_marks.ts';
import { pyGet, pyGetItem, pyPop, type PyMapping } from '../../../py/dict.ts';
import { pyEq, pyIn } from '../../../py/eq.ts';
import { PyTypeError } from '../../../py/errors.ts';
import { pyFloatParse, pyInt } from '../../../py/number.ts';
import { pyLt, pyMax, pyMin, pySorted } from '../../../py/sort.ts';
import { pyStr } from '../../../py/str.ts';
import { pyOr, truthy } from '../../../py/truthy.ts';
import { count_arrow_crossings, detect_crossings } from '../../shared/edge_crossing_detector.ts';
import { compute_waypoints, type WayPoint } from '../edge_router.ts';
import {
  _avoid_node_intersections,
  _facing_side_pairs,
  _prefer_architecture_outer_route,
  _prefer_crosscutting_lower_corridor_route,
} from './detours.ts';
import {
  type BBox,
  type Box,
  type Point,
  _absolute_arrow_points,
  _arrow_path_fields,
  _compress_orthogonal_path,
  _is_orthogonal,
  _path_avoids_endpoint_interiors,
  _path_crossing_count,
  _path_length,
  _path_parallel_channel_penalty,
  _route_is_legal,
  _visible_arrows,
  _waypoints,
  _xy,
} from './geometry.ts';
import { _refresh_bound_labels } from './labels.ts';
import { _defaultdict_int_getitem } from './ports.ts';

type Dict = Record<string, unknown>;
type PointLike = readonly number[];

export type RouteContexts = Record<string, Dict> | Map<unknown, Dict>;
// (crossings, length, arrow, waypoints, start_side, end_side)
export type _Update = [number, number, Dict, WayPoint[], string, string];

type Context = Dict & {
  source_bbox: BBox;
  target_bbox: BBox;
  obstacles: Box[];
  start_side: string;
  end_side: string;
};

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

function _at<T>(items: readonly T[], index: number): T {
  return items[index < 0 ? items.length + index : index];
}

/** ``max(value, 1.0)`` */
function _at_least_one(value: number): number {
  return 1.0 > value ? 1.0 : value;
}

function _context(route_contexts: RouteContexts, key: string): Context | null {
  return pyGet(route_contexts, key) as Context | null;
}

/** Scene crossing count if ``arrow`` took the candidate path. */
export function _trial_crossings(arrow: Dict, candidate_fields: Dict, others: Dict[], scene_crossings: number): number {
  const candidate = { ...arrow, ...candidate_fields };
  return scene_crossings - count_arrow_crossings(arrow, others) + count_arrow_crossings(candidate, others);
}

/** Greedy descent: apply the best single-edge reroute until none helps. */
export function _commit_best_updates(
  arrow_elems: Dict[],
  route_contexts: RouteContexts,
  propose: () => _Update | null,
  max_rounds: number | null = null,
  after_commit: ((arrow: Dict) => void) | null = null,
): null {
  void arrow_elems;
  let rounds = 0;
  while (max_rounds === null || rounds < max_rounds) {
    rounds += 1;
    const best_update = propose();
    if (best_update === null) break;
    const [, , arrow, candidate, start_side, end_side] = best_update;
    pyUpdate(arrow, _arrow_path_fields(candidate));
    const context = pyGetItem(route_contexts as PyMapping<Dict>, pyStr(arrow.id));
    context.start_side = start_side;
    context.end_side = end_side;
    if (after_commit) after_commit(arrow);
  }
  return null;
}

export function _better(update: _Update, best: _Update | null): _Update {
  return best === null || pyLt(update.slice(0, 2), best.slice(0, 2)) ? update : best;
}

function _unique_pairs(pairs: [string, string][]): [string, string][] {
  const seen = new Set<string>();
  const result: [string, string][] = [];
  for (const pair of pairs) {
    const key = `${pair[0]}\u0000${pair[1]}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(pair);
  }
  return result;
}

/** Draw.io-style global port reconsideration. */
export function _reduce_crossings(
  arrow_elems: Dict[],
  route_contexts: RouteContexts,
  elements_by_id: Record<string, Dict> | Map<unknown, Dict>,
  port_spacing: number,
): null {
  const propose = (): _Update | null => {
    const crossing_pairs = detect_crossings(arrow_elems);
    const current_crossings = crossing_pairs.length;
    if (current_crossings === 0) return null;
    const crossing_neighbors = new Map<string, Set<string>>();
    for (const [first_id, second_id] of crossing_pairs) {
      if (!crossing_neighbors.has(first_id)) crossing_neighbors.set(first_id, new Set());
      crossing_neighbors.get(first_id)!.add(second_id);
      if (!crossing_neighbors.has(second_id)) crossing_neighbors.set(second_id, new Set());
      crossing_neighbors.get(second_id)!.add(first_id);
    }
    let best_update: _Update | null = null;
    for (const arrow of arrow_elems) {
      const arrow_id = pyStr(pyGet(arrow, 'id', ''));
      const context = crossing_neighbors.has(arrow_id) ? _context(route_contexts, arrow_id) : null;
      if (!truthy(context)) continue;
      const source_bbox = context!.source_bbox;
      const target_bbox = context!.target_bbox;
      const [horizontal, vertical] = _facing_side_pairs(source_bbox, target_bbox);
      const side_pairs = _unique_pairs([
        [context!.start_side, context!.end_side],
        horizontal,
        vertical,
        [horizontal[0], vertical[1]],
        [vertical[0], horizontal[1]],
      ]);
      const current_length = _at_least_one(_path_length(_absolute_arrow_points([arrow])));
      const other_arrows = arrow_elems.filter((item) => item !== arrow);
      // Seed the visibility grid only with the routes that currently
      // conflict with this edge.
      const neighbors = crossing_neighbors.get(arrow_id)!;
      const conflicting_arrows = other_arrows.filter((item) => neighbors.has(pyStr(pyGet(item, 'id', ''))));
      for (const [start_side, end_side] of side_pairs) {
        let [candidate] = compute_waypoints(
          start_side,
          end_side,
          source_bbox,
          target_bbox,
          undefined,
          undefined,
          undefined,
          undefined,
          undefined,
          context![['top', 'bottom'].includes(start_side) ? 'source_x_index' : 'source_y_index'] as number,
          context!.source_degree as number,
          context![['top', 'bottom'].includes(end_side) ? 'target_x_index' : 'target_y_index'] as number,
          context!.target_degree as number,
          port_spacing,
        );
        candidate = _avoid_node_intersections(candidate, context!.obstacles, undefined, conflicting_arrows);
        const points = _xy(candidate);
        const candidate_length = _path_length(points);
        if (
          !_route_is_legal(points, context!.obstacles, source_bbox, target_bbox)
          || candidate_length > current_length * 1.6
        ) {
          continue;
        }
        const trial_crossings = _trial_crossings(arrow, _arrow_path_fields(candidate), other_arrows, current_crossings);
        if (trial_crossings >= current_crossings) continue;
        best_update = _better([trial_crossings, candidate_length, arrow, candidate, start_side, end_side], best_update);
      }
    }
    return best_update;
  };

  _commit_best_updates(arrow_elems, route_contexts, propose, 8, (arrow) => {
    _refresh_bound_labels(arrow, elements_by_id);
  });
  return null;
}

/** Send long concept-map cross-section relations along a clear corridor. */
export function _route_concept_corridors(
  arrow_elems: Dict[],
  route_contexts: RouteContexts,
  elements_by_id: Record<string, Dict> | Map<unknown, Dict>,
  concept_frames: [string, BBox][],
  port_spacing: number,
): null {
  if (concept_frames.length < 3) return null;
  const frame_index = new Map<string, number>();
  concept_frames.forEach(([frame_id], index) => frame_index.set(frame_id, index));

  const containing_frame = (box: BBox): string | null => {
    const center_x = box.x + box.w / 2.0;
    const center_y = box.y + box.h / 2.0;
    for (const [frame_id, frame] of concept_frames) {
      if (
        frame.x <= center_x && center_x <= frame.x + frame.w
        && frame.y <= center_y && center_y <= frame.y + frame.h
      ) {
        return frame_id;
      }
    }
    return null;
  };

  const frame_by_id = new Map<string, BBox>(concept_frames);
  const min_left = pyMin(concept_frames.map(([, frame]) => frame.x)) as number;
  const max_right = pyMax(concept_frames.map(([, frame]) => frame.x + frame.w)) as number;
  const corridor_margin = 28.0;
  const band_clearance = 14.0;
  for (const arrow of arrow_elems) {
    const context = _context(route_contexts, pyStr(pyGet(arrow, 'id', '')));
    if (!truthy(context) || !truthy(pyGet(context!, 'cross_branch'))) continue;
    const source_frame_id = containing_frame(context!.source_bbox);
    const target_frame_id = containing_frame(context!.target_bbox);
    if (!truthy(source_frame_id) || !truthy(target_frame_id)) continue;
    const source_frame_index = frame_index.get(source_frame_id!)!;
    const target_frame_index = frame_index.get(target_frame_id!)!;
    if (Math.abs(target_frame_index - source_frame_index) < 2) continue;

    const source_box = context!.source_bbox;
    const target_box = context!.target_bbox;
    const source_frame = frame_by_id.get(source_frame_id!)!;
    const target_frame = frame_by_id.get(target_frame_id!)!;
    const downward = target_frame_index > source_frame_index;
    const source_x = source_box.x + source_box.w / 2.0;
    const target_x = target_box.x + target_box.w / 2.0;
    const source_y = downward ? source_box.y + source_box.h : source_box.y;
    const target_y = downward ? target_box.y : target_box.y + target_box.h;
    const source_gap_y = downward
      ? source_frame.y + source_frame.h + band_clearance
      : source_frame.y - band_clearance;
    const target_gap_y = downward
      ? target_frame.y - band_clearance
      : target_frame.y + target_frame.h + band_clearance;
    const route_candidates: [number, number, WayPoint[], string][] = [];
    const other_arrows = arrow_elems.filter((item) => item !== arrow);

    const consider = (raw_candidate: Point[], start_side: string): void => {
      const compressed = _compress_orthogonal_path(raw_candidate);
      if (!_route_is_legal(compressed, context!.obstacles, source_box, target_box)) return;
      route_candidates.push([
        _path_crossing_count(compressed, other_arrows),
        _path_length(compressed),
        _waypoints(compressed),
        start_side,
      ]);
    };

    // First consider clear rails inside the band composition.
    const interior_corridors = new Set<number>([source_x, target_x]);
    for (const [left, , width] of context!.obstacles) {
      interior_corridors.add(left - band_clearance);
      interior_corridors.add(left + width + band_clearance);
    }
    const source_ports = new Set<number>([source_x]);
    const source_margin = 8.0;
    const port_limit = pyInt(context!.source_degree as number) + 2;
    for (let offset_index = 1; offset_index < port_limit; offset_index += 1) {
      const offset = _float(offset_index) * _float(port_spacing);
      for (const candidate_x of [source_x - offset, source_x + offset]) {
        if (source_box.x + source_margin <= candidate_x && candidate_x <= source_box.x + source_box.w - source_margin) {
          source_ports.add(candidate_x);
        }
      }
    }

    const sorted_corridors = [...interior_corridors].sort((a, b) => a - b);
    for (const source_port_x of [...source_ports].sort((a, b) => a - b)) {
      for (const corridor_x of sorted_corridors) {
        if (!(min_left + band_clearance < corridor_x && corridor_x < max_right - band_clearance)) continue;
        consider(
          [
            [source_port_x, source_y],
            [source_port_x, source_gap_y],
            [corridor_x, source_gap_y],
            [corridor_x, target_gap_y],
            [target_x, target_gap_y],
            [target_x, target_y],
          ],
          downward ? 'bottom' : 'top',
        );
      }
    }

    // The exterior rails remain a robust fallback.
    for (const [corridor_x, side] of [[min_left - corridor_margin, 'left'], [max_right + corridor_margin, 'right']] as const) {
      const side_source_x = side === 'left' ? source_box.x : source_box.x + source_box.w;
      const side_source_y = source_box.y + source_box.h / 2.0;
      const escape_y = downward ? source_box.y - 24.0 : source_box.y + source_box.h + 24.0;
      consider(
        [
          [source_x, source_y],
          [source_x, source_gap_y],
          [corridor_x, source_gap_y],
          [corridor_x, target_gap_y],
          [target_x, target_gap_y],
          [target_x, target_y],
        ],
        downward ? 'bottom' : 'top',
      );
      consider(
        [
          [side_source_x, side_source_y],
          [corridor_x, side_source_y],
          [corridor_x, target_gap_y],
          [target_x, target_gap_y],
          [target_x, target_y],
        ],
        side_source_x === source_x && downward ? 'bottom' : side_source_x === source_x ? 'top' : side,
      );
      consider(
        [
          [source_x, downward ? source_box.y : source_box.y + source_box.h],
          [source_x, escape_y],
          [corridor_x, escape_y],
          [corridor_x, target_gap_y],
          [target_x, target_gap_y],
          [target_x, target_y],
        ],
        downward ? 'top' : 'bottom',
      );
    }
    if (!route_candidates.length) continue;
    const [, , candidate, candidate_start_side] = pyMin(route_candidates, (item) => [item[0], item[1]]);
    pyUpdate(arrow, _arrow_path_fields(candidate));
    context!.start_side = candidate_start_side;
    context!.end_side = downward ? 'top' : 'bottom';
    _detach_corridor_labels(arrow, elements_by_id, candidate, target_x, target_gap_y, downward);
  }
  return null;
}

/** Pin a corridor route's predicate beside its final approach. */
export function _detach_corridor_labels(
  arrow: Dict,
  elements_by_id: Record<string, Dict> | Map<unknown, Dict>,
  candidate: WayPoint[],
  target_x: number,
  target_gap_y: number,
  downward: boolean,
): null {
  const retained_bindings: Dict[] = [];
  for (const binding of (pyOr(pyGet(arrow, 'boundElements', []), []) as Dict[])) {
    if (pyGet(binding, 'type') !== 'text' || !truthy(pyGet(binding, 'id'))) {
      retained_bindings.push(binding);
      continue;
    }
    const label = pyGet(elements_by_id, pyStr(binding.id)) as Dict | null;
    if (label === null) continue;
    const label_width = _float(pyOr(pyGet(label, 'width', 0.0), 0.0));
    const label_height = _float(pyOr(pyGet(label, 'height', 0.0), 0.0));
    const approach_x = _float(_at(candidate, -2).x);
    const label_x = approach_x < target_x ? target_x - label_width - 18.0 : target_x + 18.0;
    const label_y = downward ? target_gap_y - label_height - 8.0 : target_gap_y + 8.0;
    Object.assign(label, {
      x: label_x > 0.0 ? label_x : 0.0,
      y: label_y > 0.0 ? label_y : 0.0,
      containerId: null,
      meta: { semantic_edge_id: pyGet(pyGet(arrow, 'meta', {}), 'semantic_edge_id') },
    });
    markF(label, 'x', true); // max(0.0, float)
    markF(label, 'y', true);
  }
  if (retained_bindings.length) arrow.boundElements = retained_bindings;
  else pyPop(arrow, 'boundElements', null);
  return null;
}

/** Move unlabeled architecture edges onto outer faces or the lower corridor. */
export function _reroute_architecture_edges(
  arrow_elems: Dict[],
  route_contexts: RouteContexts,
  side_group_ids: Set<string>,
  source_degrees: Record<string, number>,
  target_degrees: Record<string, number>,
): null {
  const propose = (): _Update | null => {
    const current_crossings = detect_crossings(arrow_elems).length;
    let best_update: _Update | null = null;
    for (const arrow of arrow_elems) {
      const context = _context(route_contexts, pyStr(pyGet(arrow, 'id', '')));
      if (!truthy(context) || truthy(pyGet(arrow, 'boundElements'))) continue;
      const is_crosscutting = pyIn(pyGet(context!, 'source_group'), side_group_ids)
        || pyIn(pyGet(context!, 'target_group'), side_group_ids);
      if (
        !is_crosscutting
        && (
          _defaultdict_int_getitem(source_degrees, context!.source_ref as string) !== 1
          || _defaultdict_int_getitem(target_degrees, context!.target_ref as string) !== 1
        )
      ) {
        continue;
      }
      const current_points: WayPoint[] = (pyGet(arrow, 'points', []) as unknown[][]).map((point) => ({
        x: _float(pyGet(arrow, 'x', 0.0)) + _float(point[0]),
        y: _float(pyGet(arrow, 'y', 0.0)) + _float(point[1]),
      }));
      const other_arrows = arrow_elems.filter((item) => item !== arrow);
      const route_args = [
        context!.start_side,
        context!.end_side,
        context!.source_bbox,
        context!.target_bbox,
        context!.obstacles,
        other_arrows,
      ] as const;
      // A lower-corridor move for a cross-cutting edge takes precedence
      // over trying its outer faces.
      const crosscutting_candidate = is_crosscutting
        ? _prefer_crosscutting_lower_corridor_route(current_points, ...route_args)
        : null;
      const used_crosscutting_candidate = truthy(crosscutting_candidate) && !pyEq(crosscutting_candidate, current_points);
      let candidate: WayPoint[];
      let start_side: string;
      let end_side: string;
      if (used_crosscutting_candidate) {
        [candidate, start_side, end_side] = [crosscutting_candidate!, context!.start_side, context!.end_side];
      } else {
        [candidate, start_side, end_side] = _prefer_architecture_outer_route(current_points, ...route_args);
      }
      if (pyEq(candidate, current_points)) continue;
      const candidate_points = _xy(candidate);
      if (!_path_avoids_endpoint_interiors(candidate_points, context!.source_bbox, context!.target_bbox)) continue;
      const trial_crossings = _trial_crossings(arrow, _arrow_path_fields(candidate), other_arrows, current_crossings);
      if (trial_crossings > current_crossings) continue;
      if (
        trial_crossings === current_crossings
        && !(
          used_crosscutting_candidate
          && _path_parallel_channel_penalty(candidate, other_arrows) < _path_parallel_channel_penalty(current_points, other_arrows)
        )
      ) {
        continue;
      }
      best_update = _better(
        [trial_crossings, _path_length(candidate_points), arrow, candidate, start_side, end_side],
        best_update,
      );
    }
    return best_update;
  };

  _commit_best_updates(arrow_elems, route_contexts, propose);
  return null;
}

/** Separate incoming ports after route optimization has changed faces. */
export function _spread_final_target_ports(arrows: Dict[], route_contexts: RouteContexts, spacing: number): null {
  if (spacing <= 0) return null;
  const groups = new Map<string, [[unknown, string], Dict[]]>();
  for (const arrow of _visible_arrows(arrows)) {
    const context = _context(route_contexts, pyStr(pyGet(arrow, 'id', '')));
    if (truthy(context)) {
      const key: [unknown, string] = [context!.target_ref, context!.end_side];
      const serialized = JSON.stringify(key);
      if (!groups.has(serialized)) groups.set(serialized, [key, []]);
      groups.get(serialized)![1].push(arrow);
    }
  }

  for (const [[, side], siblings] of groups.values()) {
    if (siblings.length < 2) continue;
    const axis = side === 'top' || side === 'bottom' ? 0 : 1;
    const box = pyGetItem(route_contexts as PyMapping<Dict>, pyStr(siblings[0].id)).target_bbox as BBox;
    const span = axis === 0 ? box.w : box.h;
    const spread = (span - 16.0 > 0.0 ? span - 16.0 : 0.0) / (siblings.length - 1);
    const step = spread < spacing ? spread : spacing;
    if (step <= 0) continue;
    const paths = new Map<string, Point[]>();
    for (const arrow of siblings) paths.set(pyStr(arrow.id), _absolute_arrow_points([arrow]));
    // Preserve simple direct connections.
    if ([...paths.values()].some((points) => points.length < 3)) continue;
    const ordered = pySorted(siblings, (arrow) => {
      const path = paths.get(pyStr(arrow.id))!;
      return [_at(path, -1)[axis], path[0][axis], pyStr(arrow.id)];
    });
    const positions = ordered.map((arrow) => _at(paths.get(pyStr(arrow.id))!, -1)[axis]);
    const gaps: number[] = [];
    for (let i = 0; i + 1 < positions.length; i += 1) gaps.push(positions[i + 1] - positions[i]);
    if ((pyMin(gaps) as number) >= step - 1e-6) continue;
    const center = (axis === 0 ? box.x : box.y) + span / 2.0;
    let boundary = axis === 0 ? box.y : box.x;
    if (side === 'bottom') boundary += box.h;
    else if (side === 'right') boundary += box.w;
    const replacements = new Map<string, Dict>();
    for (let rank = 0; rank < ordered.length; rank += 1) {
      const arrow = ordered[rank];
      const arrow_id = pyStr(arrow.id);
      const points = paths.get(arrow_id)!.map((point) => [...point]);
      // The final segment must enter this actual face normally.
      if (
        Math.abs(_at(points, -1)[1 - axis] - boundary) > 1e-6
        || Math.abs(_at(points, -2)[axis] - _at(points, -1)[axis]) > 1e-6
      ) {
        break;
      }
      const coordinate = center + (rank - (ordered.length - 1) / 2.0) * step;
      _at(points, -1)[axis] = coordinate;
      _at(points, -2)[axis] = coordinate;
      const candidate_points = points as PointLike[];
      const context = pyGetItem(route_contexts as PyMapping<Context>, arrow_id);
      if (
        !(
          _is_orthogonal(candidate_points)
          && _route_is_legal(candidate_points, context.obstacles, context.source_bbox, context.target_bbox)
        )
      ) {
        break;
      }
      replacements.set(arrow_id, pyMerge<Dict>(arrow, _arrow_path_fields(_waypoints(candidate_points))));
    }
    if (replacements.size !== siblings.length) continue;
    const trial = arrows.map((arrow) => replacements.get(pyStr(arrow.id)) ?? arrow);
    if (detect_crossings(trial).length > detect_crossings(arrows).length) continue;
    for (const arrow of siblings) pyUpdate(arrow, replacements.get(pyStr(arrow.id))!);
  }
  return null;
}

/** Separate crowded dogleg channels without changing either endpoint. */
export function _separate_final_channels(arrows: Dict[], route_contexts: RouteContexts): null {
  for (let round = 0; round < 2; round += 1) {
    let changed = false;
    for (const arrow of _visible_arrows(arrows)) {
      const context = _context(route_contexts, pyStr(pyGet(arrow, 'id', '')));
      const points = _absolute_arrow_points([arrow]);
      if (context === null || points.length !== 4) continue;
      const middle = [points[1], points[2]];
      const vertical = Math.abs(middle[0][0] - middle[1][0]) < 1e-6;
      const horizontal = Math.abs(middle[0][1] - middle[1][1]) < 1e-6;
      if (vertical === horizontal || _path_length(middle) < 24.0) continue;
      const axis = vertical ? 0 : 1;
      const other_arrows = arrows.filter((item) => item !== arrow);
      const penalty = _path_parallel_channel_penalty(points, other_arrows);
      if (penalty <= 1e-6) continue;
      const crossings = _path_crossing_count(points, other_arrows);
      const length = _path_length(points);
      let best: [[number, number, number], PointLike[]] | null = null;
      for (const delta of [-16.0, -8.0, 8.0, 16.0]) {
        const candidate = points.map((point) => [...point]);
        candidate[1][axis] += delta;
        candidate[2][axis] += delta;
        const candidate_points = candidate as PointLike[];
        const candidate_length = _path_length(candidate_points);
        if (
          candidate_length > length + 32.0
          || !_is_orthogonal(candidate_points)
          || !_route_is_legal(candidate_points, context.obstacles, context.source_bbox, context.target_bbox)
          || _path_crossing_count(candidate_points, other_arrows) > crossings
        ) {
          continue;
        }
        const candidate_penalty = _path_parallel_channel_penalty(candidate_points, other_arrows);
        if (candidate_penalty >= penalty - 1e-6) continue;
        const score: [number, number, number] = [candidate_penalty, candidate_length, Math.abs(delta)];
        if (best === null || pyLt(score, best[0])) best = [score, candidate_points];
      }
      if (best === null) continue;
      pyUpdate(arrow, _arrow_path_fields(_waypoints(best[1])));
      changed = true;
    }
    if (!changed) break;
  }
  return null;
}
