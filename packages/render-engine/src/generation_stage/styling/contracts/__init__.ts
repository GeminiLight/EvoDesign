// Ported from evodesign/agentic_system/generation_stage/styling/contracts/__init__.py — keep in sync.
// Canvas-specific styling contracts for the Styling Agent.

import { normalize_canvas_library } from '../../../canvas_runtime.ts';
import { EXCALIDRAW_STYLING_CONTRACT } from './excalidraw.ts';
import { TLDRAW_STYLING_CONTRACT } from './tldraw.ts';

export { EXCALIDRAW_STYLING_CONTRACT, TLDRAW_STYLING_CONTRACT };

// Map canvas library name to contract
export const _CANVAS_CONTRACTS: Record<string, string> = {
  excalidraw: EXCALIDRAW_STYLING_CONTRACT,
  tldraw: TLDRAW_STYLING_CONTRACT,
};

/**
 * Return the full styling contract for the given canvas.
 *
 * @param canvas Canvas library name ("excalidraw" or "tldraw").
 */
export function get_styling_contract(canvas: string): string {
  return _CANVAS_CONTRACTS[normalize_canvas_library(canvas)];
}

/** Return Excalidraw-only styling contract. */
export function get_excalidraw_contract(): string {
  return EXCALIDRAW_STYLING_CONTRACT;
}

/** Return TLDraw-only styling contract. */
export function get_tldraw_contract(): string {
  return TLDRAW_STYLING_CONTRACT;
}
