// Ported from evodesign/canvas_environment/capabilities.py — keep in sync.
//
// Canvas capability matrix shared by EvoDesign runtime surfaces.

import { VALID_CANVAS_LIBRARIES, normalize_canvas_library } from '../canvas_runtime.ts';
import { normalize_generation_mode } from '../config/settings.ts';
import { ValueError } from '../py/errors.ts';
import { pyRepr } from '../py/str.ts';

export { VALID_CANVAS_LIBRARIES };

/** ``@dataclass(frozen=True)`` */
export class CanvasCapabilities {
  constructor(
    readonly canvas_library: string,
    readonly supports_multiagent: boolean,
    readonly supports_oneshot: boolean,
    readonly supports_refiner: boolean,
    readonly supports_knowledge_evolution: boolean,
  ) {
    Object.freeze(this);
  }
}

export const _CAPABILITIES: Record<string, CanvasCapabilities> = {
  excalidraw: new CanvasCapabilities('excalidraw', true, true, true, true),
  tldraw: new CanvasCapabilities('tldraw', true, false, false, false),
};

export function get_canvas_capabilities(canvas_library: string): CanvasCapabilities {
  return _CAPABILITIES[normalize_canvas_library(canvas_library)];
}

export function generation_mode_unsupported_reason(canvas_library: string, mode: string): string | null {
  const capabilities = get_canvas_capabilities(canvas_library);
  const normalized_mode = normalize_generation_mode(mode);
  if (normalized_mode === 'multiagent' && !capabilities.supports_multiagent) {
    return (
      'multiagent generation is not supported for '
      + `canvas_library=${pyRepr(capabilities.canvas_library)}.`
    );
  }
  if (normalized_mode === 'oneshot' && !capabilities.supports_oneshot) {
    return (
      'oneshot generation currently emits Excalidraw scenes only; '
      + "use canvas_library='excalidraw' or switch to mode='multiagent'."
    );
  }
  return null;
}

export function require_generation_capability(canvas_library: string, mode: string): null {
  const reason = generation_mode_unsupported_reason(canvas_library, mode);
  if (reason) {
    throw new ValueError(reason);
  }
  return null;
}

export function refiner_unsupported_reason(canvas_library: string, mode: string): string | null {
  normalize_generation_mode(mode);
  const capabilities = get_canvas_capabilities(canvas_library);
  if (!capabilities.supports_refiner) {
    return (
      'iterative refiner currently supports Excalidraw manifests only '
      + `(canvas_library=${pyRepr(capabilities.canvas_library)}).`
    );
  }
  return null;
}

export function require_refiner_capability(canvas_library: string, mode: string): null {
  const reason = refiner_unsupported_reason(canvas_library, mode);
  if (reason) {
    throw new ValueError(reason);
  }
  return null;
}

export function knowledge_evolution_unsupported_reason(canvas_library: string): string | null {
  const capabilities = get_canvas_capabilities(canvas_library);
  if (!capabilities.supports_knowledge_evolution) {
    return (
      'knowledge evolution currently requires Excalidraw-compatible '
      + 'refinement primitives; '
      + `canvas_library=${pyRepr(capabilities.canvas_library)} is generation-only `
      + 'for this loop.'
    );
  }
  return null;
}

export function require_knowledge_evolution_capability(canvas_library: string): null {
  const reason = knowledge_evolution_unsupported_reason(canvas_library);
  if (reason) {
    throw new ValueError(reason);
  }
  return null;
}

export const __all__ = [
  'CanvasCapabilities',
  'VALID_CANVAS_LIBRARIES',
  'generation_mode_unsupported_reason',
  'get_canvas_capabilities',
  'knowledge_evolution_unsupported_reason',
  'refiner_unsupported_reason',
  'require_generation_capability',
  'require_knowledge_evolution_capability',
  'require_refiner_capability',
];
