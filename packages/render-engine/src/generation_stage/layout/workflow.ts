// Ported from evodesign/agentic_system/generation_stage/layout/workflow.py — keep in sync.
// server-only (LangGraph.js / BaseAgent)

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { END, START } from '@langchain/langgraph';
import { LayoutAgent } from './layout_agent.ts';
import { estimate_element_sizes } from './element_shape_estimator.ts';
import { WorkflowState } from './state.ts';
import { _with_py_floats, sequence_layout_geometry } from './sequence_layout.ts';
import { BaseWorkflow } from '../../common/base_workflow.ts';
import { build_assistant_content, unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pyRepr } from '../../py/str.ts';
import { isDict, pyOr, pyTypeName } from '../../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.layout.workflow');

type Dict = Record<string, unknown>;

/**
 * Layout Workflow:
 *     estimate_sizes -> sequence geometry or LayoutAgent(LLM)
 *
 * The LLM autonomously determines coordinates based on semantic
 * structure, group containment, and visual layout principles.
 *
 * Python sets ``self.layout_agent`` before ``super().__init__``; in TS the
 * base constructor builds the graph first, which is fine because the node
 * bodies only read the agent when the graph runs.
 */
export class LayoutWorkflow extends BaseWorkflow<WorkflowState> {
  layout_agent!: LayoutAgent;

  constructor(model: BaseChatModel) {
    super(WorkflowState);
    this.layout_agent = new LayoutAgent(model);
  }

  /** Pre-processing: estimate min_width/min_height for node elements only. */
  _run_estimate_sizes(state: WorkflowState): WorkflowState {
    state.styling_instantiation = estimate_element_sizes(
      pyOr(state.styling_instantiation, {}) as Dict,
      state.structure_instantiation,
    ) as Dict;
    logger.info('[LayoutWorkflow] Element size estimation completed (nodes only)');
    return state;
  }

  async _run_layout(state: WorkflowState): Promise<WorkflowState> {
    const structure = unwrap_structure_instantiation(state.structure_instantiation);
    if (state.canvas_library === 'excalidraw' && (Object.prototype.hasOwnProperty.call(structure, 'chart_type') ? structure.chart_type : null) === 'sequence_diagram') {
      const styling = pyOr(state.styling_instantiation, {}) as Dict;
      const geometry = sequence_layout_geometry(structure, styling);
      const merged = this.layout_agent._merge_layout_with_styling(
        geometry, styling, state.canvas_library,
        structure);
      if (!Object.prototype.hasOwnProperty.call(structure, 'nodes')) throw new KeyError(pyRepr('nodes'));
      const participant_order = (structure.nodes as unknown[]).map((node) => {
        if (!isDict(node)) throw new PyTypeError(`'${pyTypeName(node)}' object is not subscriptable`);
        if (!Object.prototype.hasOwnProperty.call(node, 'id')) throw new KeyError(pyRepr('id'));
        return node.id;
      });
      const specification = {
        strategy: 'deterministic_sequence',
        participant_order,
        message_order: 'sequence_idx',
      };
      state.update_stage('layout_specification', specification);
      state.update_stage('layout_instantiation', merged);
      state.conversation_history = [...state.conversation_history, {
        role: 'assistant', content: build_assistant_content('Layout', specification, _with_py_floats(merged)),
      }];
      logger.info('[LayoutWorkflow] Sequence geometry derived without a model call');
      return state;
    }
    return this.layout_agent.run(state);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  override _build_workflow(): any {
    const workflow = this.workflow;
    workflow.addNode('estimate_sizes', (state: WorkflowState) => this._run_estimate_sizes(state));
    workflow.addNode('layout', (state: WorkflowState) => this._run_layout(state));

    // ``set_entry_point("estimate_sizes")``
    workflow.addEdge(START, 'estimate_sizes');
    workflow.addEdge('estimate_sizes', 'layout');
    workflow.addEdge('layout', END);
    return workflow.compile();
  }

  override _validate_inputs(state: WorkflowState): void {
    if (state.structure_instantiation === null || state.structure_instantiation === undefined) {
      throw new ValueError('Required input structure_instantiation missing in state.');
    }
    if (state.styling_instantiation === null || state.styling_instantiation === undefined) {
      throw new ValueError('Required input styling_instantiation missing in state.');
    }
  }
}
