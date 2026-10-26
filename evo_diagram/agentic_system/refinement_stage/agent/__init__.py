"""refinement_stage.agent — single-shot VLM call producing EditOps.

Uses core.LLMFactory.create_for_role("refiner") for the VLM client.
"""

from .llm_agent import RefinerLLMAgent, refine_with_llm  # noqa: F401

__all__ = ["RefinerLLMAgent", "refine_with_llm"]
