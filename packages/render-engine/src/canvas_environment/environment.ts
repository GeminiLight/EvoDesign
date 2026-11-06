// Ported from evodesign/canvas_environment/environment.py — keep in sync.
// server-only (rendering)
//
// Object-oriented facade for canvas conversion, rendering, and checks.
// The render methods are async in TS (Node playwright).

import { CanvasEnvironmentConfig } from './config.ts';
import {
  RenderPngResult,
  RenderResult,
  render_canvas_file,
  render_manifest,
  render_png_result,
} from './rendering.ts';
import {
  CanvasAuditReport,
  audit_layout_instantiation,
  audit_manifest,
  normalize_manifest,
  repair_manifest_zorder,
  validate_manifest,
} from './validation.ts';

type Dict = Record<string, unknown>;

/**
 * Stable boundary around the canvas runtime.
 *
 * Agentic workflows should use this class or the module-level facade
 * functions instead of reaching into ``agentic_system.render_engine``
 * internals.
 */
export class CanvasEnvironment {
  config: CanvasEnvironmentConfig;

  constructor(config: CanvasEnvironmentConfig | null = null) {
    this.config = config || new CanvasEnvironmentConfig();
  }

  get canvas_library(): string {
    return this.config.normalized_canvas_library();
  }

  async render_manifest(layout_instantiation: Dict, structure_instantiation: Dict, output_dir: string | null = null): Promise<RenderResult> {
    return render_manifest(
      layout_instantiation,
      structure_instantiation,
      this.canvas_library,
      output_dir,
      this.config.viewport_width,
      this.config.viewport_height,
    );
  }

  async render_png(manifest: Dict, output_path: string): Promise<boolean> {
    return (await render_png_result(
      manifest,
      output_path,
      this.canvas_library,
      this.config.viewport_width,
      this.config.viewport_height,
    )).ok;
  }

  async render_png_result(manifest: Dict, output_path: string): Promise<RenderPngResult> {
    return render_png_result(
      manifest,
      output_path,
      this.canvas_library,
      this.config.viewport_width,
      this.config.viewport_height,
    );
  }

  async render_file(input_path: string, output_path: string): Promise<Record<string, string>> {
    return render_canvas_file(
      input_path,
      output_path,
      this.canvas_library,
      this.config.viewport_width,
      this.config.viewport_height,
    );
  }

  normalize_manifest(manifest: Dict): Dict {
    return normalize_manifest(manifest, this.canvas_library);
  }

  validate_manifest(manifest: Dict): Dict {
    return validate_manifest(manifest, this.canvas_library);
  }

  audit_manifest(manifest: Dict, structure_instantiation: Dict | null = null): CanvasAuditReport {
    return audit_manifest(manifest, structure_instantiation, this.canvas_library);
  }

  audit_layout_instantiation(layout_instantiation: Dict, structure_instantiation: Dict | null = null): string[] {
    return audit_layout_instantiation(layout_instantiation, structure_instantiation);
  }

  repair_zorder(manifest: Dict): Dict {
    return repair_manifest_zorder(manifest, this.canvas_library);
  }
}

export const __all__ = ['CanvasEnvironment'];
