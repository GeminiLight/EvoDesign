// Ported from evodesign/canvas_environment/_render_engine_adapter.py — keep in sync.
// server-only (rendering delegates to the browser renderer and the file system)
//
// Private adapter to the legacy agentic render engine.
//
// The public ``canvas_environment`` package is the stable boundary. The current
// implementation still delegates to ``agentic_system.render_engine``; keeping all
// of those imports here makes that transitional dependency explicit and avoids
// spreading legacy render-engine paths across the facade modules.
//
// Python imports lazily inside each function; the TS port imports statically
// (none of these modules has import-time side effects). The TLDraw validator
// (``render_engine/tldraw``) is not ported (out of scope, PHASE2_PLAN.md §1):
// ``validate_tldraw_manifest`` raises NotImplementedError.

import type { RenderPngResult, RenderResult } from '../canvas_runtime.ts';
import { NotImplementedError } from '../py/errors.ts';
import * as canvas_render from '../render_engine/canvas_render.ts';
import { rebuild_excalidraw_arrows as rebuild } from '../render_engine/excalidraw/arrow_adder.ts';
import { normalize_architecture_style as normalize } from '../render_engine/excalidraw/architecture_style_normalizer.ts';
import { _excalidraw_defaults } from '../render_engine/excalidraw/converter.ts';
import { compute_waypoints, to_relative_points, waypoints_bbox } from '../render_engine/excalidraw/edge_router.ts';
import { compact_architecture_layout as compact } from '../render_engine/excalidraw/layered_layout_compactor.ts';
import { normalize_excalidraw_manifest as _normalize_excalidraw_manifest } from '../render_engine/excalidraw/normalizer.ts';
import { validate_excalidraw_manifest as _validate_excalidraw_manifest } from '../render_engine/excalidraw/validator.ts';
import * as zorder_repair from '../render_engine/excalidraw/zorder_repair.ts';
import * as service from '../render_engine/service.ts';
import { audit_sides } from '../render_engine/shared/edge_routing.ts';
import { disjoint_segment_box_distance as distance } from '../render_engine/shared/label_geometry.ts';
import { detect_group_frame_ids as _detect_group_frame_ids } from '../render_engine/shared/normalization.ts';
import { validate_png_file as _validate_png_file } from '../render_engine/shared/png_validation.ts';
import {
  _contrast_ratio,
  audit_excalidraw_manifest as _audit_excalidraw_manifest,
  audit_layout_instantiation as _audit_layout_instantiation,
  audit_tldraw_manifest as _audit_tldraw_manifest,
} from '../render_engine/shared/render_audit.ts';

type Dict = Record<string, unknown>;

export function excalidraw_element_defaults(seed: unknown): Dict {
  return _excalidraw_defaults(seed);
}

export function rebuild_excalidraw_arrows(manifest: Dict, structure_instantiation: Dict): Dict {
  return rebuild(manifest, structure_instantiation);
}

export function compact_architecture_layout(manifest: Dict, structure_instantiation: Dict): Dict {
  return compact(manifest, structure_instantiation);
}

export function normalize_architecture_style(manifest: Dict, structure_instantiation: Dict): Dict {
  return normalize(manifest, structure_instantiation);
}

export function disjoint_segment_box_distance(start: readonly number[], end: readonly number[], box: readonly number[]): number {
  return distance(start as [number, number], end as [number, number], box);
}

export function color_contrast_ratio(color_a: string, color_b: string): number | null {
  return _contrast_ratio(color_a, color_b);
}

export async function render_manifest(
  layout_instantiation: Dict,
  structure_instantiation: Dict,
  canvas_library: string,
  output_dir: string | null,
  viewport_width: number,
  viewport_height: number,
  layout_specification: Dict | null = null,
  design_constraints = '',
): Promise<RenderResult> {
  return service.render_manifest(
    layout_instantiation,
    structure_instantiation,
    canvas_library,
    output_dir,
    viewport_width,
    viewport_height,
    layout_specification,
    design_constraints,
  );
}

export async function render_png_result(
  manifest: Dict,
  output_path: string,
  canvas_library: string,
  viewport_width: number,
  viewport_height: number,
  render_scale: number | null = null,
  crop = true,
): Promise<RenderPngResult> {
  return service.render_png_result(
    manifest,
    output_path,
    canvas_library,
    viewport_width,
    viewport_height,
    render_scale,
    crop,
  );
}

export async function render_canvas(
  data: unknown,
  output_path: string,
  canvas_library: string,
  viewport_width: number | null,
  viewport_height: number | null,
): Promise<Record<string, string>> {
  return canvas_render.render_canvas(data as Dict, output_path, canvas_library, {
    viewport_width,
    viewport_height,
  });
}

export function normalize_excalidraw_manifest(manifest: Dict): null {
  _normalize_excalidraw_manifest(manifest);
  return null;
}

export function validate_excalidraw_manifest(manifest: Dict): Dict {
  return _validate_excalidraw_manifest(manifest);
}

export function validate_tldraw_manifest(_manifest: Dict): Dict {
  throw new NotImplementedError(
    'render_engine/tldraw/validator is not ported to TypeScript (out of phase-2 scope).',
  );
}

export function audit_excalidraw_manifest(manifest: Dict, structure_instantiation: Dict | null): unknown {
  return _audit_excalidraw_manifest(manifest, structure_instantiation);
}

export function audit_tldraw_manifest(manifest: Dict, structure_instantiation: Dict | null): unknown {
  return _audit_tldraw_manifest(manifest, structure_instantiation);
}

export function audit_layout_instantiation(layout_instantiation: Dict, structure_instantiation: Dict | null): string[] {
  return _audit_layout_instantiation(layout_instantiation, structure_instantiation);
}

export function repair_excalidraw_zorder(manifest: Dict): Dict {
  return zorder_repair.repair_zorder(manifest);
}

export function detect_group_frame_ids(elements: Dict[], structural: boolean, id_map: unknown): Set<string> {
  return _detect_group_frame_ids(elements, structural, id_map);
}

/**
 * Recompute one Excalidraw arrow polyline from its endpoint bounding boxes.
 *
 * Runs the same three steps the arrow adder runs when it first draws an
 * arrow — face selection, waypoint computation, conversion to the element's
 * origin-relative form — so a re-routed arrow is indistinguishable from a
 * freshly drawn one.
 */
export function route_excalidraw_arrow(
  source_bbox: Dict,
  target_bbox: Dict,
  start_side_hint: string | null,
  end_side_hint: string | null,
): Dict {
  const source_shape = {
    x: Number(source_bbox.x),
    y: Number(source_bbox.y),
    width: Number(source_bbox.w),
    height: Number(source_bbox.h),
  };
  const target_shape = {
    x: Number(target_bbox.x),
    y: Number(target_bbox.y),
    width: Number(target_bbox.w),
    height: Number(target_bbox.h),
  };
  let hinted: Dict | null = null;
  if (start_side_hint || end_side_hint) {
    hinted = { start: start_side_hint, end: end_side_hint };
  }

  const [start_side, end_side] = audit_sides(hinted, source_shape, target_shape);
  const [waypoints] = compute_waypoints(
    start_side,
    end_side,
    { ...source_bbox },
    { ...target_bbox },
  ) as unknown as [Dict[], unknown, unknown];
  const [origin_x, origin_y, relative_points] = to_relative_points(waypoints);
  const [width, height] = waypoints_bbox(waypoints);
  return {
    x: origin_x,
    y: origin_y,
    width,
    height,
    points: relative_points,
    absolute_points: waypoints.map((point) => [Number(point.x), Number(point.y)]),
    start_side,
    end_side,
  };
}

export function validate_png_file(output_file: string, context: string): void {
  _validate_png_file(output_file, context);
}

export const __all__ = [
  'render_manifest',
  'render_png_result',
  'render_canvas',
  'normalize_excalidraw_manifest',
  'validate_excalidraw_manifest',
  'validate_tldraw_manifest',
  'audit_excalidraw_manifest',
  'audit_tldraw_manifest',
  'audit_layout_instantiation',
  'repair_excalidraw_zorder',
  'detect_group_frame_ids',
  'route_excalidraw_arrow',
  'validate_png_file',
];
