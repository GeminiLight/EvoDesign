// Ported from evodesign/agentic_system/common/workflow_state_base.py — keep in sync.
//
// Base workflow state class with shared fields and validation logic.
//
// pydantic ``BaseModel`` → ``py/pydantic.ts BaseModel``: fields live in the
// static ``model_fields`` table and are declared with ``declare`` (see the
// header of py/pydantic.ts). Subclasses spread ``WorkflowStateBase.model_fields``.

import { getLogger } from '../py/logging.ts';
import { BaseModel, field, type FieldSpec } from '../py/pydantic.ts';
import { normalize_canvas_library } from '../canvas_runtime.ts';

const logger = getLogger('evodesign.agentic_system.common.workflow_state_base');
void logger;

/**
 * Base class for all workflow state classes.
 *
 * Common fields shared across all workflows:
 * - current_stage: Current workflow stage
 * - canvas_library: Canvas library selection (validated)
 * - text_content: Original input text
 * - user_query: User query for guidance
 * - design_expertise: Cross-session knowledge retrieved from ChromaDB
 *   (design memory, user preferences). Reference-quality, not authoritative.
 * - runtime_directives: Per-request override context the caller injects
 *   with HIGHEST priority (incremental-edit snapshot or refiner feedback).
 * - conversation_history: Multi-turn message thread used by the generation
 *   pipeline so downstream agents inherit upstream tasks and outputs.
 * - content_area: Optional domain / subject-area hint from the dataset or API
 *   request. It is prompt context, not a schema field emitted by the stages.
 */
export class WorkflowStateBase extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.common.workflow_state_base.WorkflowStateBase';

  static override model_fields: Record<string, FieldSpec> = {
    // Stage tracking
    current_stage: field({ type: 'str', default: 'init' }),
    // Canvas library selection (validated)
    canvas_library: field({
      type: 'str',
      default: 'excalidraw',
      description: "The canvas library for which the workflow is being executed: 'tldraw' or 'excalidraw'.",
      before: (v) => WorkflowStateBase.validate_canvas_library(v as string),
    }),
    // Input fields
    text_content: field({ type: 'str', default: '' }),
    user_query: field({ type: 'optional_str', default: null }),
    // Knowledge/context fields
    stage_knowledge: field({ type: 'str', default: '' }), // System-built per-type knowledge from system_prompt/type_patterns/*.md
    design_expertise: field({ type: 'str', default: '' }), // External knowledge (ChromaDB, user preferences)
    runtime_directives: field({ type: 'str', default: '' }),
    diagram_type: field({ type: 'optional_str', default: null }), // Current diagram type for dynamic system prompt
    content_area: field({ type: 'optional_str', default: null }),
    // Conversation thread for multi-turn pipeline mode.
    // [{"role": "system", "content": ...}, {"role": "user", "content": ...}, ...]
    conversation_history: field({ type: 'list_of_dict', default_factory: () => [] }),
  };

  declare current_stage: string;
  declare canvas_library: string;
  declare text_content: string;
  declare user_query: string | null;
  declare stage_knowledge: string;
  declare design_expertise: string;
  declare runtime_directives: string;
  declare diagram_type: string | null;
  declare content_area: string | null;
  declare conversation_history: Record<string, string>[];

  /** Validate and normalize canvas_library value. */
  static validate_canvas_library(v: string): string {
    return normalize_canvas_library(v);
  }

  /**
   * Update workflow stage and assign data to the matching field.
   *
   * If ``stage`` matches a field name on this model, ``data`` is assigned
   * to that field.
   */
  update_stage(stage: string, data: unknown = null): void {
    this.current_stage = stage;
    if (Object.prototype.hasOwnProperty.call((this.constructor as typeof WorkflowStateBase).model_fields, stage)) {
      (this as Record<string, unknown>)[stage] = data;
    }
  }
}

/** Unbound method form, ``WorkflowStateBase.update_stage(self, stage, data)`` (returns None). */
export function WorkflowStateBase_update_stage(self: WorkflowStateBase, stage: string, data: unknown = null): null {
  self.update_stage(stage, data);
  return null;
}
