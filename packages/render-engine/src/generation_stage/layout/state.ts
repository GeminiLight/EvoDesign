// Ported from evodesign/agentic_system/generation_stage/layout/state.py — keep in sync.

import { WorkflowStateBase } from '../../common/workflow_state_base.ts';
import { field, type FieldSpec } from '../../py/pydantic.ts';

export class WorkflowState extends WorkflowStateBase {
  static override pythonName = 'evodesign.agentic_system.generation_stage.layout.state.WorkflowState';

  static override model_fields: Record<string, FieldSpec> = {
    ...WorkflowStateBase.model_fields,
    structure_instantiation: field({ type: 'dict', required: true }),
    styling_instantiation: field({ type: 'dict', required: true }),
    structure_specification: field({ type: 'optional_dict', default: null }), // Upstream spec from structure
    styling_specification: field({ type: 'optional_dict', default: null }), // Upstream spec from styling

    layout_specification: field({ type: 'optional_dict', default: null }),
    layout_instantiation: field({ type: 'optional_dict', default: null }),
  };

  declare structure_instantiation: Record<string, unknown>;
  declare styling_instantiation: Record<string, unknown>;
  declare structure_specification: Record<string, unknown> | null;
  declare styling_specification: Record<string, unknown> | null;
  declare layout_specification: Record<string, unknown> | null;
  declare layout_instantiation: Record<string, unknown> | null;
}
