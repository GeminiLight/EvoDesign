"""refinement_stage — fix logic for diagram refinement.

Contains the building blocks used by ``IterativeRefinerWorkflow`` (which lives
at ``agentic_system/iterative_workflow.py``):

- ``agent/`` — LLM agent that proposes EditOps
- ``fixers/`` — deterministic fixers + edit applicator
- ``state.py`` — VerifierRefinerState, EditOp, IterationLog
- ``reports/`` — refiner report builder

Public surface:
    - VerifierRefinerState, EditOp, IterationLog (state.py)
"""

from .state import EditOp, IterationLog, VerifierRefinerState  # noqa: F401

__all__ = [
    "VerifierRefinerState",
    "EditOp",
    "IterationLog",
]
