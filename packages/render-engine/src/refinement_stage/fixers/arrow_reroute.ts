// Ported from evodesign/agentic_system/refinement_stage/fixers/arrow_reroute.py — keep in sync.
//
// Re-route Excalidraw arrows whose endpoint shapes moved or were resized.
//
// An Excalidraw arrow carries no live link to the shapes it connects: its shape
// is baked into the absolute ``x``/``y``/``points`` polyline the renderer wrote
// once, at arrow-add time. ``op_set_position`` / ``op_set_size`` relocate a shape
// and its bound label, and nothing else — so every geometry edit the refiner
// applies silently detaches the arrows attached to that shape, while every
// id-level binding stays perfectly intact.
//
// This module closes the loop by asking the canvas facade to redraw the arrow
// from the new bounding boxes after each batch of edits. Endpoint shapes are
// resolved the same way the verifier's ``check_arrow_endpoint_geometry``
// resolves them, so the fixer and the check always agree on what "attached"
// means.

import { markF } from '../../py/float_marks.ts';
import { route_arrow_between_bboxes, type ArrowRouteGeometry } from '../../canvas_environment/geometry.ts';
import { id_map_from_manifest } from '../../common/semantic_ids.ts';
import { pyGet } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyMin } from '../../py/sort.ts';
import { pyFormatFixed } from '../../py/str.ts';
import { isDict, isList, isStr, pyTypeName, truthy } from '../../py/truthy.ts';
import {
  ARROW_ENDPOINT_TOLERANCE_PX,
  arrow_absolute_endpoints,
  element_bbox,
  has_derived_bindings,
  point_gap_to_bbox,
  resolve_arrow_endpoint_shapes,
} from '../../verification_stage/checks/binding_consistency.ts';
import { _bump_version } from './primitives.ts';

type Dict = Record<string, unknown>;
export type _BBox = readonly number[];
type _Point = readonly number[];

const logger = getLogger('evodesign.agentic_system.refinement_stage.fixers.arrow_reroute');

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${pyTypeName(value)}'`);
}

export function _as_route_bbox(bbox: _BBox): { x: number; y: number; w: number; h: number } {
  const [x, y, w, h] = bbox;
  return { x, y, w, h };
}

/**
 * Which face of ``bbox`` the endpoint currently sits on, if any.
 *
 * Passed to the router as a *hint* so an arrow whose other end moved keeps
 * the face it already used.
 */
export function _infer_side(point: _Point, bbox: _BBox): string | null {
  const [px, py] = point;
  const [x, y, w, h] = bbox;
  if (point_gap_to_bbox(point, bbox) > ARROW_ENDPOINT_TOLERANCE_PX) {
    return null;
  }
  const distances: Record<string, number> = {
    left: Math.abs(px - x),
    right: Math.abs(px - (x + w)),
    top: Math.abs(py - y),
    bottom: Math.abs(py - (y + h)),
  };
  return pyMin(Object.keys(distances), (side) => distances[side]);
}

export function _arrow_label_elements(elements: unknown[], arrow: Dict): Dict[] {
  const arrow_id = pyGet(arrow, 'id');
  const bounds = pyGet(arrow, 'boundElements');
  const bound_ids = new Set<unknown>(
    ((truthy(bounds) ? bounds : []) as unknown[]).filter((item) => isDict(item)).map((item) => pyGet(item, 'id')),
  );
  const labels: Dict[] = [];
  for (const elem of elements) {
    if (!isDict(elem) || pyGet(elem, 'type') !== 'text') {
      continue;
    }
    if (pyEq(pyGet(elem, 'containerId'), arrow_id) || bound_ids.has(pyGet(elem, 'id'))) {
      labels.push(elem);
    }
  }
  return labels;
}

export function _midpoint(endpoints: readonly (readonly number[])[]): [number, number] {
  const [[sx, sy], [ex, ey]] = endpoints;
  return [(sx + ex) / 2.0, (sy + ey) / 2.0];
}

/** ``max(a, b)`` for floats (first wins unless the second is strictly larger). */
function _max2(a: number, b: number): number {
  return b > a ? b : a;
}

/**
 * Recompute arrow geometry so arrows follow the shapes they connect.
 *
 * Returns one record per re-routed arrow (empty list when nothing moved).
 * Mutates ``manifest`` in place, like ``patch_schema_defaults``.
 */
export function reroute_bound_arrows(
  manifest: Dict,
  canvas_library = 'excalidraw',
  touched_ids: Iterable<unknown> | null = null,
  tolerance: number = ARROW_ENDPOINT_TOLERANCE_PX,
): Dict[] {
  if (!isDict(manifest) || has_derived_bindings(manifest)) {
    return [];
  }
  const elements = pyGet(manifest, 'elements');
  if (!isList(elements)) {
    return [];
  }

  const by_id = new Map<unknown, Dict>();
  for (const elem of elements) {
    if (isDict(elem) && truthy(pyGet(elem, 'id')) && !truthy(pyGet(elem, 'isDeleted'))) {
      by_id.set(pyGet(elem, 'id'), elem);
    }
  }
  const id_map = id_map_from_manifest(manifest);
  const touched = new Set<string>();
  for (const tid of (truthy(touched_ids) ? touched_ids! : []) as Iterable<unknown>) {
    if (isStr(tid)) touched.add(tid);
  }

  const rerouted: Dict[] = [];
  for (const arrow of elements) {
    if (!isDict(arrow) || truthy(pyGet(arrow, 'isDeleted'))) {
      continue;
    }
    if (pyGet(arrow, 'type') !== 'arrow') {
      continue;
    }

    const endpoints = arrow_absolute_endpoints(arrow);
    if (endpoints === null) {
      continue;
    }
    const [start_shape, end_shape] = resolve_arrow_endpoint_shapes(arrow, by_id, id_map);
    if (start_shape === null || end_shape === null) {
      // A half-anchored arrow has no second bbox to route against; the
      // verifier still reports the drifted side so it is not hidden.
      continue;
    }
    const src_bbox = element_bbox(start_shape);
    const tgt_bbox = element_bbox(end_shape);
    if (src_bbox === null || tgt_bbox === null) {
      continue;
    }

    const start_gap = point_gap_to_bbox(endpoints[0], src_bbox);
    const end_gap = point_gap_to_bbox(endpoints[1], tgt_bbox);
    const shape_touched = (
      touched.has(pyGet(start_shape, 'id') as string) || touched.has(pyGet(end_shape, 'id') as string)
    );
    const drifted = start_gap > tolerance || end_gap > tolerance;
    if (!(shape_touched || drifted)) {
      continue;
    }

    let route: ArrowRouteGeometry;
    try {
      route = route_arrow_between_bboxes(
        _as_route_bbox(src_bbox),
        _as_route_bbox(tgt_bbox),
        canvas_library,
        _infer_side(endpoints[0], src_bbox),
        _infer_side(endpoints[1], tgt_bbox),
      );
    } catch (error) {
      if (error instanceof ValueError || error instanceof PyTypeError || error instanceof KeyError || error instanceof TypeError) {
        logger.warning("arrow re-route failed for %r; leaving its geometry untouched", pyGet(arrow, 'id'));
        continue;
      }
      throw error;
    }
    if (route.absolute_points.length < 2) {
      continue;
    }

    const old_mid = _midpoint(endpoints);
    arrow.x = route.x;
    arrow.y = route.y;
    arrow.points = route.points;
    arrow.width = _max2(1.0, route.width);
    arrow.height = _max2(1.0, route.height);
    // ArrowRouteGeometry holds float(...) values; max(1.0, float) is a float.
    for (const key of ['x', 'y', 'width', 'height']) markF(arrow, key, true);
    for (const point of route.points as number[][]) {
      markF(point, 0, true);
      markF(point, 1, true);
    }
    // Locked elbow segments describe the OLD polyline; keeping them would
    // fight the new one on re-import.
    delete arrow.fixedSegments;
    _bump_version(arrow);

    const absolute = route.absolute_points;
    const new_endpoints = [
      [absolute[0][0], absolute[0][1]],
      [absolute[absolute.length - 1][0], absolute[absolute.length - 1][1]],
    ];
    const new_mid = _midpoint(new_endpoints);
    const dx = new_mid[0] - old_mid[0];
    const dy = new_mid[1] - old_mid[1];
    if (dx || dy) {
      for (const label of _arrow_label_elements(elements, arrow)) {
        try {
          const lx = pyGet(label, 'x', 0);
          const nx = _float(truthy(lx) ? lx : 0) + dx;
          label.x = nx;
          const ly = pyGet(label, 'y', 0);
          label.y = _float(truthy(ly) ? ly : 0) + dy;
          markF(label, 'x', true);
          markF(label, 'y', true);
        } catch (error) {
          if (error instanceof PyTypeError || error instanceof ValueError) continue;
          throw error;
        }
        _bump_version(label);
      }
    }

    const reason = shape_touched
      ? 'endpoint shape moved'
      : `endpoint drift ${pyFormatFixed(_max2(start_gap, end_gap), 0)}px`;
    rerouted.push({
      arrow_id: pyGet(arrow, 'id'),
      start_shape: pyGet(start_shape, 'id'),
      end_shape: pyGet(end_shape, 'id'),
      start_side: route.start_side,
      end_side: route.end_side,
      reason,
    });
  }

  if (rerouted.length) {
    logger.info('[ArrowReroute] recomputed geometry for %d arrow(s)', rerouted.length);
  }
  return rerouted;
}

export const __all__ = ['reroute_bound_arrows'];
