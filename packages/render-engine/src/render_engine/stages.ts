// Ported from evodesign/agentic_system/render_engine/stages.py — keep in sync.
//
// Render workflow stage names.

export const CONVERT = 'convert';
export const SIZE_FIT = 'size_fit';
export const ARROW = 'arrow';
export const FIT_GROUPS = 'fit_groups';
export const ALIGN_GROUPS = 'align_groups';
export const ZORDER_REPAIR = 'zorder_repair';
export const VALIDATE = 'validate';
export const RENDER = 'render';

export const MANIFEST_STAGES: ReadonlySet<string> = new Set([
  CONVERT,
  SIZE_FIT,
  ARROW,
  FIT_GROUPS,
  ALIGN_GROUPS,
  ZORDER_REPAIR,
]);

export const __all__ = [
  'CONVERT',
  'SIZE_FIT',
  'ARROW',
  'FIT_GROUPS',
  'ALIGN_GROUPS',
  'ZORDER_REPAIR',
  'VALIDATE',
  'RENDER',
  'MANIFEST_STAGES',
];
