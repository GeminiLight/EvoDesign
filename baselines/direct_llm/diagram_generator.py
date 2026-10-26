"""
Diagram Generator Agent

This module defines the DiagramGenerator class, which is an agent that
converts text descriptions into Excalidraw-renderable JSON diagrams by default.
"""

import logging
from typing import Dict, Any, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.core.base_agent import BaseAgent
from baselines.direct_llm.prompts import SYSTEM_PROMPT, TASK_PROMPT
from baselines.direct_llm.excalidraw_prompts import EXCALIDRAW_SYSTEM_PROMPT, EXCALIDRAW_TASK_PROMPT
from baselines.direct_llm.state import WorkflowState
from baselines.direct_llm.direct_code_converter import DirectCodeConverter
from baselines.direct_llm.excalidraw_converter import ExcalidrawDirectCodeConverter

logger = logging.getLogger(__name__)


class DiagramGenerator(BaseAgent):
    """Agent that generates Excalidraw or tldraw JSON diagrams from text descriptions.

    This agent uses a language model to analyze text input and generate
    valid canvas JSON that can be rendered as diagrams.
    """

    def __init__(
        self,
        model: BaseChatModel,
        system_prompt: str = None,
        task_prompt: str = None,
        canvas_library: str = "excalidraw",
        **kwargs
    ):
        """Initialize the DiagramGenerator agent.

        Args:
            model: LangChain-compatible chat model
            canvas_library: "tldraw" or "excalidraw"
            **kwargs: Additional arguments passed to BaseAgent
        """
        self.canvas_library = canvas_library
        # Select prompts based on canvas library
        if canvas_library == "excalidraw":
            system_prompt = system_prompt or EXCALIDRAW_SYSTEM_PROMPT
            task_prompt = task_prompt or EXCALIDRAW_TASK_PROMPT
        else:
            system_prompt = system_prompt or SYSTEM_PROMPT
            task_prompt = task_prompt or TASK_PROMPT

        super().__init__(
            model=model,
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            exclude_think=True,
            jsonalize_output=True,
            **kwargs
        )
        logger.info(f"DiagramGenerator agent initialized ({canvas_library})")

    def run(self, state: WorkflowState) -> WorkflowState:
        """Run the diagram generator on a workflow state.

        This method updates the workflow state with the generated diagram
        by using BaseAgent's invoke method, then converts the simplified
        JSON output to a complete tldraw snapshot using DirectCodeConverter.

        Args:
            state: WorkflowState containing input text

        Returns:
            Updated WorkflowState with output diagram
        """
        try:
            state.status = "generating"

            logger.info(f"Generating simplified diagram JSON for text (length: {len(state.text_content)})")

            # Prepare input for BaseAgent's invoke method
            input_dict = {
                "text_content": state.text_content,
                "user_query": getattr(state, "user_query", "")
            }

            # Use BaseAgent's invoke method to get simplified JSON from LLM
            simplified_output = self.invoke(input_dict)

            logger.info("LLM generated simplified JSON successfully")

            # Validate output - ensure it's a valid dict with elements
            if not isinstance(simplified_output, dict):
                raise ValueError(f"LLM returned non-dict output: {type(simplified_output).__name__}")
            if "elements" not in simplified_output and "shapes" not in simplified_output:
                raise ValueError(f"LLM returned invalid structure (no 'elements' or 'shapes'): {list(simplified_output.keys())}")

            # Convert simplified JSON to complete snapshot
            if self.canvas_library == "excalidraw":
                converter = ExcalidrawDirectCodeConverter()
            else:
                converter = DirectCodeConverter()
            complete_snapshot = converter.convert(simplified_output)

            # Update state with complete output
            state.output = complete_snapshot
            state.simplified_output = simplified_output  # Store simplified version too
            state.status = "completed"

            logger.info("Diagram generation and conversion completed successfully")

        except Exception as e:
            state.status = "failed"
            error_msg = f"DiagramGenerator error: {str(e)}"
            state.add_error(error_msg)
            logger.error(f"Diagram generation failed: {e}", exc_info=True)

        return state
