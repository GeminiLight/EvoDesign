import type { Adapter } from '../parity/functions.test.ts';
import { WorkflowStateBase } from '../../src/common/workflow_state_base.ts';
import { field, type FieldSpec } from '../../src/py/pydantic.ts';

// Vectors come from subclasses (generation_stage WorkflowState, WP17): self is
// the model's field dict. Replay on a WorkflowStateBase subclass that declares
// exactly those fields, then compare the instance's fields after the call.
function stateFrom(fields: Record<string, unknown>): WorkflowStateBase {
  const extra: Record<string, FieldSpec> = {};
  for (const key of Object.keys(fields)) if (!(key in WorkflowStateBase.model_fields)) extra[key] = field({ type: 'any', default: null });
  class RecordedState extends WorkflowStateBase {
    static override model_fields = { ...WorkflowStateBase.model_fields, ...extra };
  }
  const state = new RecordedState(fields);
  // Keep the recorded key order (Python model field order).
  const ordered = Object.create(RecordedState.prototype) as WorkflowStateBase;
  for (const key of Object.keys(fields)) Object.defineProperty(ordered, key, { value: (state as unknown as Record<string, unknown>)[key], writable: true, enumerable: true, configurable: true });
  return ordered;
}

export default {
  'WorkflowStateBase.update_stage': {
    args: (bound) => [stateFrom(bound[0] as Record<string, unknown>), ...bound.slice(1)],
    exportName: 'WorkflowStateBase_update_stage',
  },
} satisfies Record<string, Adapter>;
