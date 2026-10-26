"""Base workflow class providing a unified run() template for all Generation workflows."""

import logging
from typing import Type

from langgraph.graph import StateGraph

from ..common.workflow_state_base import WorkflowStateBase

logger = logging.getLogger(__name__)


class BaseWorkflow:
    """Unified workflow execution template.

    Subclasses implement ``_build_workflow()`` to define their LangGraph
    nodes and edges.  The base class handles graph compilation, invocation,
    and dict-to-State conversion.

    Override ``_validate_inputs(state)`` to add input validation (default is
    a no-op).
    """

    def __init__(self, workflow_state_cls: Type[WorkflowStateBase]) -> None:
        self._workflow_state_cls = workflow_state_cls
        self.workflow = StateGraph(workflow_state_cls)
        self.graph = self._build_workflow()

    # ------------------------------------------------------------------
    # Extension points for subclasses
    # ------------------------------------------------------------------

    def _build_workflow(self):
        """Build and compile the LangGraph StateGraph.  Must be implemented
        by every subclass."""
        raise NotImplementedError

    def _validate_inputs(self, _state: WorkflowStateBase) -> None:
        """Optional input validation.  Override to enforce required fields.
        Raise ``ValueError`` on missing inputs."""

    # ------------------------------------------------------------------
    # Template method
    # ------------------------------------------------------------------

    def run(self, state: WorkflowStateBase) -> WorkflowStateBase:
        """Execute the compiled graph and return the result as a
        ``WorkflowStateBase`` instance."""
        self._validate_inputs(state)
        result_dict = self.graph.invoke(state)
        if isinstance(result_dict, dict):
            return self._workflow_state_cls(**result_dict)
        return result_dict
