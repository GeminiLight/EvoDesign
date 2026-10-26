"""
Baseline Workflow for Direct LLM Text-to-Diagram Conversion

This module implements a workflow that uses LLM to directly convert
text to Excalidraw-renderable JSON format using the BaseAgent infrastructure.
"""

import logging
from typing import Dict, Any, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.core.llm_factory import LLMFactory
from baselines.direct_llm.diagram_generator import DiagramGenerator
from baselines.direct_llm.prompts import SYSTEM_PROMPT, TASK_PROMPT
from baselines.direct_llm.state import WorkflowState as WorkflowStateClass

logger = logging.getLogger(__name__)


class BaselineWorkflow:
    """Baseline workflow for direct LLM text-to-diagram conversion."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the baseline workflow.

        Args:
            config: Configuration dictionary with LLM settings
        """
        self.config = config or {}
        self._model = None
        self._agent = None

    def _initialize_model(self) -> BaseChatModel:
        """Initialize the LLM model from configuration.

        Returns:
            Configured BaseChatModel instance
        """
        if self._model is None:
            llm_config = self.config.copy()
            # LLMFactory expects specific keys
            self._model = LLMFactory.create(
                model=llm_config.get("model_name"),
                model_provider=llm_config.get("provider"),
                base_url=llm_config.get("base_url"),
                api_key=llm_config.get("api_key"),
                temperature=llm_config.get("temperature", 0),
                max_tokens=llm_config.get("max_tokens", 16384),
                max_retries=llm_config.get("max_retries", 6),
                streaming=False,
            )
            logger.info(f"Model initialized: {self._model}")
        return self._model

    def _initialize_agent(self) -> DiagramGenerator:
        """Initialize the diagram generator agent.

        Returns:
            Configured DiagramGenerator instance
        """
        if self._agent is None:
            model = self._initialize_model()
            canvas_library = self.config.get("canvas_library", "excalidraw")
            self._agent = DiagramGenerator(
                model=model,
                canvas_library=canvas_library,
            )
            logger.info(f"DiagramGenerator agent initialized ({canvas_library})")
        return self._agent

    def run(self, text_content: str, user_query: str = "") -> WorkflowStateClass:
        """Run the baseline workflow.

        Args:
            text_content: Input text to convert to diagram
            user_query: User query or request text

        Returns:
            WorkflowState containing the output JSON
        """
        # Initialize state
        state = WorkflowStateClass(text_content=text_content, config=self.config, user_query=user_query)

        # Initialize and run agent
        agent = self._initialize_agent()
        state = agent.run(state)

        return state


def create_workflow(config: Optional[Dict[str, Any]] = None) -> BaselineWorkflow:
    """Factory function to create a BaselineWorkflow instance.

    Args:
        config: Configuration dictionary with LLM settings

    Returns:
        Configured BaselineWorkflow instance
    """
    return BaselineWorkflow(config=config)
