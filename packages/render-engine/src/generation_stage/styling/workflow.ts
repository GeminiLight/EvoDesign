// Ported from evodesign/agentic_system/generation_stage/styling/workflow.py — keep in sync.
// server-only (LangGraph.js / BaseAgent)
//
// Styling Workflow - Unified One-Shot Styling Pipeline
//
// Stages:
// 1. StylingAgent - Generates styling JSON + icons + icon colors in one call

import { END, START } from '@langchain/langgraph';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { StylingAgent } from './styling_agent.ts';
import { WorkflowState } from './state.ts';
import { BaseWorkflow } from '../../common/base_workflow.ts';
import { ValueError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.styling.workflow');

/**
 * Unified Styling Workflow (One-Shot):
 * structure -> StylingAgent -> styling.json
 *
 * StylingAgent performs design thinking and execution in one LLM call,
 * including icon selection and icon color decisions.
 */
export class StylingWorkflow extends BaseWorkflow<WorkflowState> {
  // Assigned after super(): Python sets it before BaseWorkflow.__init__, but
  // the graph built there only reads it when a node runs.
  styling_agent!: StylingAgent;

  constructor(model: BaseChatModel, use_icons = false) {
    super(WorkflowState);
    this.styling_agent = new StylingAgent(model, null, use_icons);
  }

  override _validate_inputs(state: WorkflowState): void {
    if (state.structure_instantiation === null || state.structure_instantiation === undefined) {
      throw new ValueError('Initial state must contain structure_instantiation data');
    }
  }

  async _run_styling(state: WorkflowState): Promise<WorkflowState> {
    logger.info('[Stage 1/1] Running StylingAgent...');
    try {
      const updated_state = await this.styling_agent.run(state);
      logger.info('[Stage 1/1] StylingAgent completed');
      return updated_state;
    } catch (e) {
      logger.error(`StylingAgent failed: ${(e as Error)?.message ?? e}`);
      throw e;
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  override _build_workflow(): any {
    const workflow = this.workflow;
    workflow.addNode('styling', (state: WorkflowState) => this._run_styling(state));
    // ``set_entry_point("styling")``
    workflow.addEdge(START, 'styling');
    workflow.addEdge('styling', END);
    return workflow.compile();
  }
}
