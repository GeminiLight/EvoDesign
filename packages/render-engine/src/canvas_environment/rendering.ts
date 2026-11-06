// Ported from evodesign/canvas_environment/rendering.py — keep in sync.
// server-only (renderer, file system)
//
// Public rendering facade for EvoDesign canvas runtimes. Rendering is async
// in TS (Node playwright); call order is unchanged.

import { existsSync, readFileSync } from '../py/fs.ts';
import {
  CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  CANVAS_DEFAULT_VIEWPORT_WIDTH,
  RenderPngResult,
  RenderResult,
  normalize_canvas_library,
} from '../canvas_runtime.ts';
import { pyJsonLoads } from '../py/json.ts';
import { FileNotFoundError } from '../render_engine/canvas_render.ts';
import * as _render_engine_adapter from './_render_engine_adapter.ts';

export { RenderPngResult, RenderResult };

type Dict = Record<string, unknown>;

/**
 * Export scale for analysis renders: one image pixel = one manifest unit.
 *
 * Analysis renders are the PNGs shown to VLM stages (refiner iterations) so
 * that distances measured on the image are directly manifest-unit quantities.
 * Pair with ``crop=False``. Product renders keep the renderer defaults
 * (magnified export + smart crop).
 */
export const ANALYSIS_RENDER_SCALE = 1.0;

/**
 * Build a canvas manifest from layout+structure and render a PNG.
 *
 * This is a render boundary, not the full quality gate. It validates the
 * backend manifest shape and blocks a small set of render-time semantic
 * losses; complete quality checks still belong to the verification/refiner
 * workflows.
 */
export async function render_manifest(
  layout_instantiation: Dict,
  structure_instantiation: Dict,
  canvas_library = 'excalidraw',
  output_dir: string | null = null,
  viewport_width: number = CANVAS_DEFAULT_VIEWPORT_WIDTH,
  viewport_height: number = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  layout_specification: Dict | null = null,
  design_constraints = '',
): Promise<RenderResult> {
  canvas_library = normalize_canvas_library(canvas_library);
  const result = await _render_engine_adapter.render_manifest(
    layout_instantiation,
    structure_instantiation,
    canvas_library,
    output_dir,
    viewport_width,
    viewport_height,
    layout_specification,
    design_constraints,
  );
  return new RenderResult(result.manifest, result.png_path, result.manifest_path);
}

/**
 * Render an existing canvas manifest to PNG and preserve failure detail.
 *
 * Defaults reproduce the product render (renderer-default export scale,
 * smart crop on). Pass ``render_scale=ANALYSIS_RENDER_SCALE, crop=False``
 * for the analysis render used as VLM refinement input.
 */
export async function render_png_result(
  manifest: Dict,
  output_path: string,
  canvas_library = 'excalidraw',
  viewport_width: number = CANVAS_DEFAULT_VIEWPORT_WIDTH,
  viewport_height: number = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  render_scale: number | null = null,
  crop = true,
): Promise<RenderPngResult> {
  canvas_library = normalize_canvas_library(canvas_library);
  return _render_engine_adapter.render_png_result(
    manifest,
    output_path,
    canvas_library,
    viewport_width,
    viewport_height,
    render_scale,
    crop,
  );
}

/** Render raw Excalidraw/TLDraw canvas data to an image file. */
export async function render_canvas(
  data: Dict | unknown[],
  output_path = 'output.png',
  canvas_library = 'excalidraw',
  viewport_width: number | null = null,
  viewport_height: number | null = null,
): Promise<Record<string, string>> {
  canvas_library = normalize_canvas_library(canvas_library);
  return _render_engine_adapter.render_canvas(data, output_path, canvas_library, viewport_width, viewport_height);
}

/** Render a canvas JSON file to an image file. */
export async function render_canvas_file(
  input_path: string,
  output_path: string,
  canvas_library = 'excalidraw',
  viewport_width: number | null = null,
  viewport_height: number | null = null,
): Promise<Record<string, string>> {
  const path = input_path;
  if (!existsSync(path)) {
    throw new FileNotFoundError(`Canvas JSON file not found: ${path}`);
  }
  const data = pyJsonLoads(readFileSync(path, 'utf-8')) as Dict | unknown[];
  canvas_library = normalize_canvas_library(canvas_library);
  return render_canvas(data, output_path, canvas_library, viewport_width, viewport_height);
}

export const __all__ = [
  'ANALYSIS_RENDER_SCALE',
  'RenderPngResult',
  'RenderResult',
  'render_manifest',
  'render_png_result',
  'render_canvas',
  'render_canvas_file',
];
