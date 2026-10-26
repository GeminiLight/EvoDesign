import logging

from langgraph.graph import END
from langchain_core.language_models import BaseChatModel

from .layout_agent import LayoutAgent
from .element_shape_estimator import estimate_element_sizes
from .state import WorkflowState
from .sequence_layout import sequence_layout_geometry
from ...common.base_workflow import BaseWorkflow
from ...common.spec_utils import build_assistant_content, unwrap_structure_instantiation

logger = logging.getLogger(__name__)


class LayoutWorkflow(BaseWorkflow):
    """
    Layout Workflow:
        estimate_sizes -> sequence geometry or LayoutAgent(LLM)

    The LLM autonomously determines coordinates based on semantic
    structure, group containment, and visual layout principles.
    """

    def __init__(self, model: BaseChatModel):
        self.layout_agent = LayoutAgent(model=model)
        super().__init__(WorkflowState)

    def _run_estimate_sizes(self, state: WorkflowState) -> WorkflowState:
        """Pre-processing: estimate min_width/min_height for node elements only."""
        state.styling_instantiation = estimate_element_sizes(
            state.styling_instantiation or {},
            state.structure_instantiation,
        )
        logger.info("[LayoutWorkflow] Element size estimation completed (nodes only)")
        return state

    def _run_layout(self, state: WorkflowState) -> WorkflowState:
        structure = unwrap_structure_instantiation(state.structure_instantiation)
        if state.canvas_library == 'excalidraw' and structure.get('chart_type') == 'sequence_diagram':
            styling = state.styling_instantiation or {}
            geometry = sequence_layout_geometry(structure, styling)
            merged = self.layout_agent._merge_layout_with_styling(
                geometry, styling, canvas_library=state.canvas_library,
                structure_instantiation=structure)
            specification = {'strategy': 'deterministic_sequence',
                             'participant_order': [node['id'] for node in structure['nodes']],
                             'message_order': 'sequence_idx'}
            state.update_stage('layout_specification', specification)
            state.update_stage('layout_instantiation', merged)
            state.conversation_history = [*state.conversation_history, {
                'role': 'assistant', 'content': build_assistant_content('Layout', specification, merged)}]
            logger.info('[LayoutWorkflow] Sequence geometry derived without a model call')
            return state
        return self.layout_agent.run(state)

    def _build_workflow(self):
        workflow = self.workflow
        workflow.add_node("estimate_sizes", self._run_estimate_sizes)
        workflow.add_node("layout", self._run_layout)

        workflow.set_entry_point("estimate_sizes")
        workflow.add_edge("estimate_sizes", "layout")
        workflow.add_edge("layout", END)
        return workflow.compile()

    def _validate_inputs(self, state: WorkflowState) -> None:
        if state.structure_instantiation is None:
            raise ValueError("Required input structure_instantiation missing in state.")
        if state.styling_instantiation is None:
            raise ValueError("Required input styling_instantiation missing in state.")
