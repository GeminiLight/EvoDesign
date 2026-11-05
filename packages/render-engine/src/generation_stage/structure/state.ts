// Ported from evodesign/agentic_system/generation_stage/structure/state.py — keep in sync.

import { WorkflowStateBase } from '../../common/workflow_state_base.ts';
import { field, type FieldSpec } from '../../py/pydantic.ts';

/** ``datetime.now(UTC).isoformat()`` (JS clocks have millisecond resolution). */
export function _utc_now_isoformat(): string {
  const now = new Date();
  const base = now.toISOString().slice(0, 19);
  const ms = now.getUTCMilliseconds();
  return `${base}${ms ? `.${String(ms * 1000).padStart(6, '0')}` : ''}+00:00`;
}

/** Holds state for the Structure Workflow. */
export class WorkflowState extends WorkflowStateBase {
  static override pythonName = 'evodesign.agentic_system.generation_stage.structure.state.WorkflowState';

  static override model_fields: Record<string, FieldSpec> = {
    ...WorkflowStateBase.model_fields,
    // === Metadata ===
    doc_id: field({ type: 'optional_str', default: null }),
    created_at: field({ type: 'str', default_factory: _utc_now_isoformat }),

    // === Intermediate Artifacts ===
    structure_specification: field({ type: 'optional_dict', default: null }),
    structure_instantiation: field({ type: 'optional_dict', default: null }),

    // === Execution Tracking ===
    logs: field({ type: 'list', default_factory: () => [] }),
    errors: field({ type: 'list', default_factory: () => [] }),
    status: field({ type: 'str', default: 'running' }), // running, completed, failed
  };

  declare doc_id: string | null;
  declare created_at: string;
  declare structure_specification: Record<string, unknown> | null;
  declare structure_instantiation: Record<string, unknown> | null;
  declare logs: string[];
  declare errors: string[];
  declare status: string;

  add_log(message: string): void {
    this.logs.push(message);
  }

  add_error(error: string): void {
    this.errors.push(error);
    this.status = 'failed';
  }
}

/** Unbound method forms (``WorkflowState.add_log(self, message)``), returning None. */
export function WorkflowState_add_log(self: WorkflowState, message: string): null {
  self.add_log(message);
  return null;
}

export function WorkflowState_add_error(self: WorkflowState, error: string): null {
  self.add_error(error);
  return null;
}
