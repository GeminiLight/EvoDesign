# -*- coding: utf-8 -*-
"""
Styling Workflow - Unified One-Shot Styling Pipeline

Stages:
1. StylingAgent - Generates styling JSON + icons + icon colors in one call
"""

import logging

from langgraph.graph import END
from langchain_core.language_models import BaseChatModel

from .styling_agent import StylingAgent
from .state import WorkflowState
from ...common.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


class StylingWorkflow(BaseWorkflow):
    """
    Unified Styling Workflow (One-Shot):
    structure -> StylingAgent -> styling.json

    StylingAgent performs design thinking and execution in one LLM call,
    including icon selection and icon color decisions.
    """

    def __init__(self, model: BaseChatModel, use_icons: bool = False):
        self.styling_agent = StylingAgent(model=model, use_icons=use_icons)
        super().__init__(WorkflowState)

    def _validate_inputs(self, state: WorkflowState) -> None:
        if state.structure_instantiation is None:
            raise ValueError("Initial state must contain structure_instantiation data")

    def _run_styling(self, state: WorkflowState) -> WorkflowState:
        logger.info("[Stage 1/1] Running StylingAgent...")
        try:
            updated_state = self.styling_agent.run(state)
            logger.info("[Stage 1/1] StylingAgent completed")
            return updated_state
        except Exception as e:
            logger.error(f"StylingAgent failed: {e}")
            raise

    def _build_workflow(self):
        workflow = self.workflow
        workflow.add_node("styling", self._run_styling)
        workflow.set_entry_point("styling")
        workflow.add_edge("styling", END)
        return workflow.compile()
