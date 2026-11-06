import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { PACKAGE_ROOT } from '../harness/fixtures.ts';
import { _set_project_root } from '../../src/config/model_loader.ts';

const REPO_ROOT = join(PACKAGE_ROOT, '..', '..');

export default {
  // pytest points _PROJECT_ROOT at an empty tmp dir to reach the packaged-defaults fallback.
  _default_models_path: {
    args: (bound) => {
      _set_project_root(join(tmpdir(), 'evodesign-parity-empty-root'));
      return bound;
    },
    result: (actual) => {
      _set_project_root(REPO_ROOT);
      return actual;
    },
  },
  // Python returns None; the TS port is void.
  _ensure_project_env_loaded: { result: (actual) => actual ?? null },
} satisfies Record<string, Adapter>;
