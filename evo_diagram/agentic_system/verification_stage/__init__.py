"""verification_stage — objective checks + VLM-based subjective critic.

This package is fully independent from refinement_stage: it does NOT import
refiner code. It reuses canvas_environment render audit and validation
for objective checks (read-only) and uses core.llm_factory.LLMFactory for
the VLM critic call.

Public surface:
    - VerifierWorkflow (workflow.py)  — LangGraph orchestrator
    - VerifierState (state.py)        — pydantic state
    - run_all_checks (checks/aggregator.py) — pure-Python objective scan
    - critique (critic/critic_agent.py) — single VLM call

CLI:
    python -m evo_diagram.agentic_system.verification_stage --manifest <path> --image <path>
"""

from .state import VerifierState  # noqa: F401
from .workflow import VerifierWorkflow  # noqa: F401

__all__ = ["VerifierState", "VerifierWorkflow"]
