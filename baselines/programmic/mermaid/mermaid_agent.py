"""
Mermaid Agent - Generates Mermaid diagrams from text using LLM.

This module provides a class-based implementation for generating Mermaid
flowchart diagrams from text input using large language models.
"""

import logging
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.core.base_agent import BaseAgent

from baselines.programmic.mermaid.prompts import SYSTEM_PROMPT, TASK_PROMPT

logger = logging.getLogger(__name__)


class MermaidAgent(BaseAgent):
    """Agent for generating Mermaid diagrams from text using LLM.

    This class inherits from BaseAgent and provides Mermaid-specific prompts
    for generating diagram code from text input.

    Attributes:
        model_name: Name of the LLM model to use
    """

    def __init__(
        self,
        model: BaseChatModel,
        system_prompt: Optional[str] = None,
        task_prompt: Optional[str] = None
    ):
        """Initialize the MermaidAgent.

        Args:
            model: Pre-configured LLM model (required).
            system_prompt: Optional custom system prompt. If None, uses default.
            task_prompt: Optional custom task prompt. If None, uses default.
        """

        # Use default prompts if not provided
        if system_prompt is None:
            system_prompt = SYSTEM_PROMPT
        if task_prompt is None:
            task_prompt = TASK_PROMPT

        # Initialize base agent with system and task prompts
        super().__init__(
            model,
            system_prompt,
            task_prompt,
            exclude_think=True,
            jsonalize_output=False
        )

        logger.info("MermaidAgent initialized")

    def run(self, state: Any) -> Any:
        """Abstract method implementation — delegates to invoke."""
        content = state.get("content", "")
        query = state.get("query", "Generate a diagram representing this content")
        return self.invoke({"content": content, "query": query})

    def __repr__(self) -> str:
        """String representation of the agent."""
        return f"MermaidAgent()"


if __name__ == "__main__":
    import os
    from evo_diagram.utils.env_loader import ensure_env_loaded
    from dotenv import load_dotenv
    from evo_diagram.core.llm_factory import LLMFactory
    from pathlib import Path

    # Load environment variables from project root .env
    ensure_env_loaded()
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env", override=True)

    # Create model
    model = LLMFactory.create(
        model=os.getenv("LLM_MODEL_NAME", "qwen3-vl-plus"),
        model_provider=os.getenv("LLM_MODEL_PROVIDER", "openai"),
        base_url=os.getenv("LLM_ENDPOINT_URL", "https://apis.iflow.cn/v1"),
        api_key=os.getenv("LLM_API_KEY"),
        temperature=0,
        max_tokens=16384,
        max_retries=6
    )

    # Initialize agent
    agent = MermaidAgent(model)

    # Test generation
    content = "A user logs in with username and password"
    query = "Show the authentication flow"

    response = agent.invoke({"content": content, "query": query})

    # Clean response
    mermaid_code = response.strip()
    if mermaid_code.startswith("```mermaid"):
        mermaid_code = mermaid_code[len("```mermaid"):].strip()
    if mermaid_code.startswith("```"):
        mermaid_code = mermaid_code[3:].strip()
    if mermaid_code.endswith("```"):
        mermaid_code = mermaid_code[:-3].strip()

    print("Generated Mermaid code:")
    print(mermaid_code)
