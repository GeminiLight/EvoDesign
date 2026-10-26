"""
Tlkz Agent - Generates TiKZ diagrams from text using LLM.

This module provides a class-based implementation for generating TiKZ
diagram code from text input using large language models.
"""

import logging
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.core.base_agent import BaseAgent

from baselines.programmic.tlkz.prompts import SYSTEM_PROMPT, TASK_PROMPT

logger = logging.getLogger(__name__)


class TlkzAgent(BaseAgent):
    """Agent for generating TiKZ diagrams from text using LLM.

    This class inherits from BaseAgent and provides TiKZ-specific prompts
    for generating diagram code from text input.

    Attributes:
        model: The LLM model instance
    """

    def __init__(
        self,
        model: BaseChatModel,
        system_prompt: Optional[str] = None,
        task_prompt: Optional[str] = None
    ):
        """Initialize the TlkzAgent.

        Args:
            model: Pre-configured LLM model (required).
            system_prompt: Optional custom system prompt. If None, uses default.
            task_prompt: Optional custom task prompt. If None, uses default.
        """
        # Initialize base agent with system and task prompts
        super().__init__(
            model,
            system_prompt if system_prompt else SYSTEM_PROMPT,
            task_prompt if task_prompt else TASK_PROMPT,
            exclude_think=True,
            jsonalize_output=False
        )

        logger.info(f"TlkzAgent initialized")

    def run(self, state: Any) -> Any:
        """Abstract method implementation — delegates to invoke."""
        content = state.get("content", "")
        query = state.get("query", "Generate a diagram representing this content")
        return self.invoke({"content": content, "query": query})

    def __repr__(self) -> str:
        """String representation of the agent."""
        return f"TlkzAgent(model={type(self._model).__name__})"


if __name__ == "__main__":
    """Test the TlkzAgent"""
    import os
    from evo_diagram.utils.env_loader import ensure_env_loaded
    from dotenv import load_dotenv
    from evo_diagram.core.llm_factory import LLMFactory
    from pathlib import Path

    # Load environment variables from project root
    ensure_env_loaded()
    env_path = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(env_path, override=True)

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
    agent = TlkzAgent(model)

    # Test generation
    content = "A user logs in with username and password"
    query = "Show the authentication flow"
    response = agent.invoke({"content": content, "query": query})

    # Clean response
    tikz_code = response.strip()
    if tikz_code.startswith("```latex"):
        tikz_code = tikz_code[len("```latex"):].strip()
    if tikz_code.startswith("```"):
        tikz_code = tikz_code[3:].strip()
    if tikz_code.endswith("```"):
        tikz_code = tikz_code[:-3].strip()

    print("Generated TiKZ code:")
    print(tikz_code)
