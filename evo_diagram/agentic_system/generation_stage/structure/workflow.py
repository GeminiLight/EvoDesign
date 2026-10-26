import logging
from langgraph.graph import END
from langchain_core.language_models import BaseChatModel

from .structure_agent import StructureAgent
from .state import WorkflowState
from ...common.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


class StructureWorkflow(BaseWorkflow):
    """
    Structure Workflow:
    Text -> StructureAgent -> ElementStructure

    Single agent that performs design thinking and structure synthesis in one LLM call.
    """

    def __init__(self, model: BaseChatModel):
        self.structure_agent = StructureAgent(model=model)
        super().__init__(WorkflowState)

    def _run_structure(self, state: WorkflowState) -> WorkflowState:
        return self.structure_agent.run(state)

    def _build_workflow(self):
        workflow = self.workflow
        workflow.add_node("structure", self._run_structure)

        workflow.set_entry_point("structure")
        workflow.add_edge("structure", END)
        return workflow.compile()
