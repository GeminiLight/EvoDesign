// Ported from evodesign/canvas_environment/config.py — keep in sync.
//
// Configuration objects for the canvas environment facade.

import { CANVAS_DEFAULT_VIEWPORT_HEIGHT, CANVAS_DEFAULT_VIEWPORT_WIDTH, normalize_canvas_library } from '../canvas_runtime.ts';
import { AppSettings } from '../config/settings.ts';

/**
 * Runtime options for canvas conversion and rendering.
 *
 * The first facade version still delegates to the existing implementation in
 * ``agentic_system.render_engine``. Keeping these options explicit here makes
 * the eventual physical extraction much less invasive.
 *
 * ``@dataclass(frozen=True)``
 */
export class CanvasEnvironmentConfig {
  readonly canvas_library: string;
  readonly viewport_width: number;
  readonly viewport_height: number;

  constructor(
    canvas_library = 'excalidraw',
    viewport_width: number = CANVAS_DEFAULT_VIEWPORT_WIDTH,
    viewport_height: number = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  ) {
    this.canvas_library = canvas_library;
    this.viewport_width = viewport_width;
    this.viewport_height = viewport_height;
    Object.freeze(this);
  }

  /** Build config from the repo's current AppSettings singleton. */
  static from_settings(): CanvasEnvironmentConfig {
    const settings = AppSettings.get_default();
    return new CanvasEnvironmentConfig(settings.canvas_library);
  }

  normalized_canvas_library(): string {
    return normalize_canvas_library(this.canvas_library);
  }
}

/** Unbound-method form for the parity harness: ``CanvasEnvironmentConfig.normalized_canvas_library(self)``. */
export function CanvasEnvironmentConfig_normalized_canvas_library(self: {
  canvas_library?: string;
  viewport_width?: number;
  viewport_height?: number;
}): string {
  return new CanvasEnvironmentConfig(self.canvas_library, self.viewport_width, self.viewport_height).normalized_canvas_library();
}

export const __all__ = ['CanvasEnvironmentConfig'];
