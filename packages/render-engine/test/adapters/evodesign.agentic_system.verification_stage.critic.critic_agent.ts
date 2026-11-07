import type { Adapter } from '../parity/functions.test.ts';
import { pngPathAdapter } from './evodesign.agentic_system.render_engine.shared.png_validation.ts';

// review_image_edge_limit reads only the PNG size: the recorded temp path is
// replaced by the run's artifact copy (same mapping as validate_png_file).
export default {
  review_image_edge_limit: {
    args: (bound, vector) => [pngPathAdapter.args!([bound[0]], vector)[0], ...bound.slice(1)],
    checkMutation: false,
  },
} satisfies Record<string, Adapter>;
