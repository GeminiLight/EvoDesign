// Ported from evodesign/agentic_system/generation_stage/unified/state.py — keep in sync.
//
// State for the experimental single-shot unified workflow.

import { WorkflowStateBase } from '../../common/workflow_state_base.ts';
import { field, type FieldSpec } from '../../py/pydantic.ts';
import { DEFAULT_PALETTE_KEY } from '../router/agent.ts';

/**
 * State for the one-shot Excalidraw generation path.
 *
 * Inherits ``text_content``, ``user_query``, ``design_expertise``, etc. from
 * :class:`WorkflowStateBase`. Unified mode still emits the final scene in one
 * model call, but it also carries a Structure-shaped semantic sidecar so the
 * verifier can run the same structure-aware checks as pipeline mode.
 */
export class UnifiedWorkflowState extends WorkflowStateBase {
  static override pythonName = 'evodesign.agentic_system.generation_stage.unified.state.UnifiedWorkflowState';

  static override model_fields: Record<string, FieldSpec> = {
    ...WorkflowStateBase.model_fields,
    // Router-injected metadata (optional — UnifiedGenerator can infer from text if
    // Router is not configured, but providing it improves type accuracy).
    diagram_type: field({ type: 'optional_str', default: null }),
    palette_key: field({ type: 'str', default: DEFAULT_PALETTE_KEY }),

    // The final scene is a regular Excalidraw clipboard JSON: type/elements/
    // files/appState. We keep it as a loose dict so group-fitter and validator
    // can still mutate it in place.
    diagram_manifest: field({ type: 'optional_dict', default: null }),
    structure_instantiation: field({ type: 'optional_dict', default: null }),

    // Router / orchestrator metadata that may influence downstream behaviour.
    content_area: field({ type: 'optional_str', default: null }),

    // Extra bookkeeping for token accounting / debugging during A/B runs.
    raw_llm_output: field({ type: 'optional_str', default: null }),
    audit_warnings: field({ type: 'list', default_factory: () => [] }),
    candidate_output: field({ type: 'any', default: null }),
    validation_error: field({ type: 'optional_str', default: null }),
    generation_attempts: field({ type: 'list_of_dict', default_factory: () => [] }),
    validation_report_path: field({ type: 'optional_str', default: null }),
  };

  declare diagram_type: string | null;
  declare palette_key: string;
  declare diagram_manifest: Record<string, unknown> | null;
  declare structure_instantiation: Record<string, unknown> | null;
  declare content_area: string | null;
  declare raw_llm_output: string | null;
  declare audit_warnings: string[];
  declare candidate_output: unknown;
  declare validation_error: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  declare generation_attempts: Record<string, any>[];
  declare validation_report_path: string | null;
}
