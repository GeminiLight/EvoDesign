// Ported from evodesign/canvas_environment/scene.py — keep in sync.
//
// Scene preparation and visual geometry exposed to generation and refinement.

import * as _render_engine_adapter from './_render_engine_adapter.ts';

type Dict = Record<string, unknown>;

/** Return deterministic metadata defaults for one native element. */
export function excalidraw_element_defaults(seed: unknown): Dict {
  return _render_engine_adapter.excalidraw_element_defaults(seed);
}

/** Rebuild semantic connectors while retaining authored styles and labels. */
export function rebuild_excalidraw_arrows(manifest: Dict, structure_instantiation: Dict): Dict {
  return _render_engine_adapter.rebuild_excalidraw_arrows(manifest, structure_instantiation);
}

/** Compact native architecture scenes; preserve identity for other types. */
export function compact_architecture_layout(manifest: Dict, structure_instantiation: Dict): Dict {
  return _render_engine_adapter.compact_architecture_layout(manifest, structure_instantiation);
}

/** Apply consistent architecture typography and role-based styling. */
export function normalize_architecture_style(manifest: Dict, structure_instantiation: Dict): Dict {
  return _render_engine_adapter.normalize_architecture_style(manifest, structure_instantiation);
}

/** Measure the gap between a disjoint connector segment and label box. */
export function disjoint_segment_box_distance(start: readonly number[], end: readonly number[], box: readonly number[]): number {
  return _render_engine_adapter.disjoint_segment_box_distance(start, end, box);
}

/** Return color contrast, or None when either color cannot be resolved. */
export function color_contrast_ratio(color_a: string, color_b: string): number | null {
  return _render_engine_adapter.color_contrast_ratio(color_a, color_b);
}
