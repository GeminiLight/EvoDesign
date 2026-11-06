// Ported from evodesign/agentic_system/generation_stage/styling/state.py — keep in sync.

import { field, type FieldSpec } from '../../py/pydantic.ts';
import { WorkflowStateBase } from '../../common/workflow_state_base.ts';
import { DEFAULT_PALETTE_KEY } from '../router/agent.ts';

/**
 * Workflow state for the styling pipeline.
 *
 * Stages:
 * 1. init -> styling_instantiation (StylingAgent one-shot)
 */
export class WorkflowState extends WorkflowStateBase {
  static override pythonName = 'evodesign.agentic_system.generation_stage.styling.state.WorkflowState';

  static override model_fields: Record<string, FieldSpec> = {
    ...WorkflowStateBase.model_fields,
    // from the parser
    structure_instantiation: field({ type: 'dict', required: true }), // Semantic topology input from structure workflow
    structure_specification: field({ type: 'optional_dict', default: null }), // Upstream spec from structure workflow

    styling_specification: field({ type: 'optional_dict', default: null }), // Styling design specification output
    styling_instantiation: field({ type: 'optional_dict', default: null }), // One-shot styling output (including optional :icon entries)

    // Router-injected dynamic content
    palette_key: field({ type: 'str', default: DEFAULT_PALETTE_KEY }), // Router-selected or explicit default palette slug
  };

  declare structure_instantiation: Record<string, unknown>;
  declare structure_specification: Record<string, unknown> | null;
  declare styling_specification: Record<string, unknown> | null;
  declare styling_instantiation: Record<string, unknown> | null;
  declare palette_key: string;
}
