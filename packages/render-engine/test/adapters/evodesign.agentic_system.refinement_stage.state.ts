import type { Adapter } from '../parity/functions.test.ts';
import { VerifierRefinerState } from '../../src/refinement_stage/state.ts';

// ``self`` is recorded as the model's field dict: rebuild the instance and call
// the unbound-method wrapper. Python returns None.
const method = (exportName: string): Adapter => ({
  exportName,
  args: (bound) => [new VerifierRefinerState(bound[0] as Record<string, unknown>), ...bound.slice(1)],
  result: (actual) => actual ?? null,
});

export default {
  'EditOp.to_dict': { exportName: 'EditOp_to_dict' },
  'VerifierRefinerState.add_log': method('VerifierRefinerState_add_log'),
  'VerifierRefinerState.add_error': method('VerifierRefinerState_add_error'),
} satisfies Record<string, Adapter>;
