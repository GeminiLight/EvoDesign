"""Core building blocks shared across all subsystems.

The package root keeps public compatibility exports lazy so lightweight
submodules such as ``evo_diagram.core.experiment`` do not import the LLM stack.
"""

__all__ = ["BaseAgent", "LLMFactory", "LLMResponseError"]


def __getattr__(name: str):
    if name in {"BaseAgent", "LLMResponseError"}:
        from .base_agent import BaseAgent, LLMResponseError

        return {"BaseAgent": BaseAgent, "LLMResponseError": LLMResponseError}[name]
    if name == "LLMFactory":
        from .llm_factory import LLMFactory

        return LLMFactory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
