import type { Adapter } from '../parity/functions.test.ts';
import { pngPathAdapter } from './evodesign.agentic_system.render_engine.shared.png_validation.ts';

const ASYNC_RENDER = 'async (Promise) and drives the live renderer page; replayed by the WP14 render check (notes/WP14.md) and parity:runs';

export default {
  validate_png_file: pngPathAdapter,
  render_manifest: { skip: ASYNC_RENDER },
  render_png_result: { skip: ASYNC_RENDER },
  validate_tldraw_manifest: { skip: 'render_engine/tldraw/validator is out of phase-2 scope (PHASE2_PLAN.md §1); the TS facade raises NotImplementedError' },
  // Python returns None; the TS function returns undefined (void).
  normalize_excalidraw_manifest: { result: (actual) => (actual === undefined ? null : actual) },
} satisfies Record<string, Adapter>;
