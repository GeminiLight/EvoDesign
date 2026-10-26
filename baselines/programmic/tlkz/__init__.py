"""
Tlkz Agent Package

A package for generating TiKZ diagrams from text using LLM.
"""

__all__ = ["TlkzAgent", "SYSTEM_PROMPT", "TASK_PROMPT"]
__version__ = "1.0.0"


def __getattr__(name):
    """Lazy public exports so CLI help does not load the LLM stack."""
    if name == "TlkzAgent":
        from .tlkz_agent import TlkzAgent

        value = TlkzAgent
    elif name in {"SYSTEM_PROMPT", "TASK_PROMPT"}:
        from .prompts import SYSTEM_PROMPT, TASK_PROMPT

        value = SYSTEM_PROMPT if name == "SYSTEM_PROMPT" else TASK_PROMPT
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value
