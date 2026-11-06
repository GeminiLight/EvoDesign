import type { Adapter } from '../parity/functions.test.ts';
import { pngPathAdapter } from './evodesign.agentic_system.render_engine.shared.png_validation.ts';

const ASYNC_RENDER = 'async (Promise) and drives the live renderer page; replayed by the WP14 render check (notes/WP14.md) and parity:runs';

export default {
  _ensure_valid_png: pngPathAdapter,
  render_manifest: { skip: ASYNC_RENDER },
  render_png_result: { skip: ASYNC_RENDER },
} satisfies Record<string, Adapter>;
