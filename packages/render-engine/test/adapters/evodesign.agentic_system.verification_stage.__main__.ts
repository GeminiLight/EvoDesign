import type { Adapter } from '../parity/functions.test.ts';
import { AppSettings } from '../../src/config/settings.ts';

// _resolve_canvas_library(None) reads settings/env. The recorded call comes
// from test_resolve_canvas_library_uses_settings_env_when_cli_omitted, which
// sets CANVAS_LIBRARY=tldraw (monkeypatch.setenv); the adapter does the same
// for that call and restores the environment afterwards.
let saved: string | undefined;

export default {
  _resolve_canvas_library: {
    args: (bound) => {
      saved = process.env.CANVAS_LIBRARY;
      if (bound[0] === null) process.env.CANVAS_LIBRARY = 'tldraw';
      AppSettings._instance = null;
      return bound;
    },
    result: (actual) => {
      if (saved === undefined) delete process.env.CANVAS_LIBRARY;
      else process.env.CANVAS_LIBRARY = saved;
      AppSettings._instance = null;
      return actual;
    },
  },
  main: {
    skip: 'async; the recorded pytest calls replace VerifierWorkflow with a fake (monkeypatch). CLI checked by hand on run artifacts (notes/WP20.md)',
  },
} satisfies Record<string, Adapter>;
