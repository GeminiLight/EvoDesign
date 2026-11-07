import type { Adapter } from '../parity/functions.test.ts';
import { pngPathAdapter } from './evodesign.agentic_system.render_engine.shared.png_validation.ts';

export default {
  validate_png_file: pngPathAdapter,
} satisfies Record<string, Adapter>;
