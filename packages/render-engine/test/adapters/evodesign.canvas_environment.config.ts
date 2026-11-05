import type { Adapter } from '../parity/functions.test.ts';

export default {
  // self is the frozen dataclass's fields; the unbound-method wrapper rebuilds it.
  'CanvasEnvironmentConfig.normalized_canvas_library': { exportName: 'CanvasEnvironmentConfig_normalized_canvas_library' },
} satisfies Record<string, Adapter>;
