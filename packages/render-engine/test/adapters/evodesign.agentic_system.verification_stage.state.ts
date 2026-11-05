import type { Adapter } from '../parity/functions.test.ts';
import { VerifierState } from '../../src/verification_stage/state.ts';

// ``self`` is recorded as the model's field dict: rebuild the instance and call
// the unbound-method wrapper. Python returns None.
const method = (exportName: string): Adapter => ({
  exportName,
  args: (bound) => [new VerifierState(bound[0] as Record<string, unknown>), ...bound.slice(1)],
  result: (actual) => actual ?? null,
});

export default {
  'VerifierState.add_log': method('VerifierState_add_log'),
  'VerifierState.add_error': method('VerifierState_add_error'),
} satisfies Record<string, Adapter>;
