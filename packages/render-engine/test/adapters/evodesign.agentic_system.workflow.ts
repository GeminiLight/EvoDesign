import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';

// WP23 adapters for agentic_system.workflow.
//
// * _save_json writes into the recorded (deleted) run directory: redirected to
//   a fresh temp dir. Python returns None; the TS void result is mapped to null.
// * reset_design_memory_cache returns None (TS: undefined → null).
// * _load_design_memory_retriever: evodesign.design_memory is out of scope
//   (PHASE2_PLAN §1); the pytest vectors exercise chromadb /
//   sentence-transformers failures of the real loader. The TS entry point is
//   an injectable hook (design_memory_hooks) that defaults to the
//   "dependencies unavailable" result.

let saveRoot: string | null = null;

export default {
  _save_json: {
    args: (bound) => {
      saveRoot ??= mkdtempSync(join(tmpdir(), 'wp23-save-json-'));
      return [join(saveRoot, basename(String(bound[0]))), ...bound.slice(1)];
    },
    result: (actual) => (actual === undefined ? null : actual),
    checkMutation: false,
  },
  reset_design_memory_cache: { result: (actual) => (actual === undefined ? null : actual) },
  _load_design_memory_retriever: { skip: 'design_memory is not ported (PHASE2_PLAN §1); the pytest vectors exercise the real chromadb / sentence-transformers loader. TS keeps an injectable hook (design_memory_hooks)' },
} satisfies Record<string, Adapter>;
