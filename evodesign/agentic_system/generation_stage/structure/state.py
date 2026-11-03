from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from ...common.workflow_state_base import WorkflowStateBase


class WorkflowState(WorkflowStateBase):
    """Holds state for the Structure Workflow."""

    # === Metadata ===
    doc_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # === Intermediate Artifacts ===
    structure_specification: Optional[Dict[str, Any]] = None
    structure_instantiation: Optional[Dict[str, Any]] = None

    # === Execution Tracking ===
    logs: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    status: str = "running" # running, completed, failed

    def add_log(self, message: str):
        self.logs.append(message)

    def add_error(self, error: str):
        self.errors.append(error)
        self.status = "failed"
