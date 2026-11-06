// Ported from evodesign/agentic_system/generation_stage/structure/workflow.py — keep in sync.
// server-only (LangGraph.js / BaseAgent)

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { END, START } from '@langchain/langgraph';
import { BaseWorkflow } from '../../common/base_workflow.ts';
import { getLogger } from '../../py/logging.ts';
import { StructureAgent } from './structure_agent.ts';
import { WorkflowState } from './state.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.structure.workflow');
void logger;

/**
 * Structure Workflow:
 * Text -> StructureAgent -> ElementStructure
 *
 * Single agent that performs design thinking and structure synthesis in one LLM call.
 *
 * Python sets ``self.structure_agent`` before ``super().__init__``; in TS the
 * base constructor runs ``_build_workflow`` first, which is fine because the
 * node body only reads the agent when the graph runs.
 */
export class StructureWorkflow extends BaseWorkflow<WorkflowState> {
  structure_agent!: StructureAgent;

  constructor(model: BaseChatModel) {
    super(WorkflowState);
    this.structure_agent = new StructureAgent(model);
  }

  _run_structure(state: WorkflowState): Promise<WorkflowState> {
    return this.structure_agent.run(state);
  }

  override _build_workflow() {
    const workflow = this.workflow;
    const _run_structure = (state: WorkflowState) => this._run_structure(state);
    workflow.addNode('structure', _run_structure);

    workflow.addEdge(START, 'structure');
    workflow.addEdge('structure', END);
    return workflow.compile();
  }
}
