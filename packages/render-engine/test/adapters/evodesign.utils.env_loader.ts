import type { Adapter } from '../parity/functions.test.ts';

// Python functions without a return statement return None; the TS ports are
// ``void`` (undefined). Compare undefined as None.
const returnsNone: Adapter = { result: (actual) => actual ?? null };

export default {
  _apply_stepfun_legacy_llm_defaults: returnsNone,
  ensure_env_loaded: returnsNone,
} satisfies Record<string, Adapter>;
