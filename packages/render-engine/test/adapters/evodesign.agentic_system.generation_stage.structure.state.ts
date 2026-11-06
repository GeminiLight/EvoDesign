import type { Adapter } from '../parity/functions.test.ts';
import { WorkflowState } from '../../src/generation_stage/structure/state.ts';

// self is the recorded model (field dict): rebuild the state instance, keeping
// the recorded field values (created_at included).
function stateFrom(fields: Record<string, unknown>): WorkflowState {
  return new WorkflowState(fields);
}

export default {
  'WorkflowState.add_error': {
    args: (bound) => [stateFrom(bound[0] as Record<string, unknown>), ...bound.slice(1)],
    exportName: 'WorkflowState_add_error',
  },
} satisfies Record<string, Adapter>;
