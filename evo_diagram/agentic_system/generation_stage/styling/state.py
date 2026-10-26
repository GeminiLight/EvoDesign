from typing import Any, Dict, Optional

from ...common.workflow_state_base import WorkflowStateBase
from ..router import DEFAULT_PALETTE_KEY


class WorkflowState(WorkflowStateBase):
    """
    Workflow state for the styling pipeline.

    Stages:
    1. init -> styling_instantiation (StylingAgent one-shot)
    """

    # from the parser
    structure_instantiation: Dict[str, Any]  # Semantic topology input from structure workflow
    structure_specification: Optional[Dict[str, Any]] = None  # Upstream spec from structure workflow

    styling_specification: Optional[Dict[str, Any]] = None  # Styling design specification output
    styling_instantiation: Optional[Dict[str, Any]] = None  # One-shot styling output (including optional :icon entries)

    # Router-injected dynamic content
    palette_key: str = DEFAULT_PALETTE_KEY  # Router-selected or explicit default palette slug
