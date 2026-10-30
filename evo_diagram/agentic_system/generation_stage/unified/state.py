"""State for the experimental single-shot unified workflow."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from ...common.workflow_state_base import WorkflowStateBase
from ..router import DEFAULT_PALETTE_KEY


class UnifiedWorkflowState(WorkflowStateBase):
    """State for the one-shot Excalidraw generation path.

    Inherits ``text_content``, ``user_query``, ``design_expertise``, etc. from
    :class:`WorkflowStateBase`. Unified mode still emits the final scene in one
    model call, but it also carries a Structure-shaped semantic sidecar so the
    verifier can run the same structure-aware checks as pipeline mode.
    """

    # Router-injected metadata (optional — UnifiedGenerator can infer from text if
    # Router is not configured, but providing it improves type accuracy).
    diagram_type: Optional[str] = None
    palette_key: str = DEFAULT_PALETTE_KEY

    # The final scene is a regular Excalidraw clipboard JSON: type/elements/
    # files/appState. We keep it as a loose dict so group-fitter and validator
    # can still mutate it in place.
    diagram_manifest: Optional[Dict[str, Any]] = None
    structure_instantiation: Optional[Dict[str, Any]] = None

    # Router / orchestrator metadata that may influence downstream behaviour.
    content_area: Optional[str] = None

    # Extra bookkeeping for token accounting / debugging during A/B runs.
    raw_llm_output: Optional[str] = None
    audit_warnings: List[str] = Field(default_factory=list)
