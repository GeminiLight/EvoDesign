// Ported from evodesign/canvas_runtime.py — keep in sync.
//
// Low-level canvas runtime contract shared across EvoDesign surfaces.
//
// This module intentionally has no dependency on ``canvas_environment`` or
// ``agentic_system``. It is safe for legacy render code, facade modules,
// backend adapters, and verification checks to import.

import { ValueError } from './py/errors.ts';
import { pyRepr, pyStr, pyStrip } from './py/str.ts';

export const VALID_CANVAS_LIBRARIES = ['tldraw', 'excalidraw'] as const;

export const CANVAS_MAX_X = 4000.0;
export const CANVAS_MAX_Y = 4000.0;
export const CANVAS_MARGIN = 16.0;

export const CANVAS_DEFAULT_VIEWPORT_WIDTH = 4000;
export const CANVAS_DEFAULT_VIEWPORT_HEIGHT = 4000;

/** Output of canvas manifest rendering. */
export class RenderResult {
  constructor(
    public manifest: Record<string, unknown>,
    public png_path: string,
    public manifest_path: string,
  ) {}
}

/** Outcome of rendering an existing manifest to PNG. */
export class RenderPngResult {
  constructor(
    public ok: boolean,
    public output_path: string,
    public error: string = '',
  ) {}
}

/** Normalize and validate a canvas backend name. */
export function normalize_canvas_library(canvas_library: unknown): string {
  const canvas = pyStrip(pyStr(canvas_library)).toLowerCase();
  if (!(VALID_CANVAS_LIBRARIES as readonly string[]).includes(canvas)) {
    throw new ValueError(
      `Unknown canvas_library: ${pyRepr(canvas_library)}. `
      + `Use one of: ${VALID_CANVAS_LIBRARIES.join(', ')}.`,
    );
  }
  return canvas;
}

export const __all__ = [
  'CANVAS_MARGIN',
  'CANVAS_MAX_X',
  'CANVAS_MAX_Y',
  'CANVAS_DEFAULT_VIEWPORT_HEIGHT',
  'CANVAS_DEFAULT_VIEWPORT_WIDTH',
  'RenderPngResult',
  'RenderResult',
  'VALID_CANVAS_LIBRARIES',
  'normalize_canvas_library',
];
