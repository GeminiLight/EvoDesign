// Ported from backend/app/core/canvas.py and
// backend/app/services/diagram_generation_contract.py — keep in sync
// (PHASE3_PLAN.md WP29).

import { ValueError } from '../py/errors.ts';
import { pyStr, pyStrip } from '../py/str.ts';

export type CanvasLibrary = 'excalidraw' | 'tldraw';
export const SUPPORTED_CANVAS_LIBRARIES: readonly CanvasLibrary[] = ['excalidraw', 'tldraw'];
export const SUPPORTED_REFINER_CANVAS_LIBRARIES: readonly CanvasLibrary[] = ['excalidraw'];

/** Normalize and validate a supported canvas library identifier. */
export function normalize_canvas_library_value(canvas_library: unknown): CanvasLibrary {
  const canvas = pyStrip(pyStr(canvas_library)).toLowerCase();
  if (!(SUPPORTED_CANVAS_LIBRARIES as readonly string[]).includes(canvas)) {
    throw new ValueError(`Unsupported canvas library: ${pyStr(canvas_library)}`);
  }
  return canvas as CanvasLibrary;
}

/** Whether the workflow runtime may run iterative refinement. */
export function canvas_library_supports_refiner(canvas_library: unknown): boolean {
  return (SUPPORTED_REFINER_CANVAS_LIBRARIES as readonly string[]).includes(normalize_canvas_library_value(canvas_library));
}

// ── app/services/diagram_generation_contract.py ──────────────────────────

export const GENERATION_INVALID_REQUEST_DETAIL = 'Diagram generation request is invalid';
export const GENERATION_UNSUPPORTED_CANVAS_DETAIL = 'Unsupported canvas library';

/** Raised when generation input is invalid before engine execution (``PublicErrorMixin, ValueError``). */
export class GenerationInputValidationError extends ValueError {
  static default_public_detail = GENERATION_INVALID_REQUEST_DETAIL;
  readonly public_detail: string;

  constructor(message: string | null = null, { public_detail = null }: { public_detail?: string | null } = {}) {
    const detail = public_detail || GenerationInputValidationError.default_public_detail;
    super(message || detail);
    this.public_detail = detail;
  }
}

/** Normalize and validate the requested canvas library. */
export function normalize_canvas_library(canvas_library: string): CanvasLibrary {
  try {
    return normalize_canvas_library_value(canvas_library);
  } catch (exc) {
    if (!(exc instanceof ValueError)) throw exc;
    throw new GenerationInputValidationError(`Unsupported canvas library: ${canvas_library}`, {
      public_detail: GENERATION_UNSUPPORTED_CANVAS_DETAIL,
    });
  }
}
