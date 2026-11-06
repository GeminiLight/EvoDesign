// Ported from evodesign/canvas_environment/constants.py — keep in sync.
//
// Compatibility re-exports for shared canvas runtime constants.

export {
  CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  CANVAS_DEFAULT_VIEWPORT_WIDTH,
  CANVAS_MARGIN,
  CANVAS_MAX_X,
  CANVAS_MAX_Y,
  VALID_CANVAS_LIBRARIES,
} from '../canvas_runtime.ts';

export const __all__ = [
  'VALID_CANVAS_LIBRARIES',
  'CANVAS_MAX_X',
  'CANVAS_MAX_Y',
  'CANVAS_MARGIN',
  'CANVAS_DEFAULT_VIEWPORT_WIDTH',
  'CANVAS_DEFAULT_VIEWPORT_HEIGHT',
];
