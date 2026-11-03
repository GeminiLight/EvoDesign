from typing import Any, Dict, Optional

from ...common.workflow_state_base import WorkflowStateBase


class WorkflowState(WorkflowStateBase):

    structure_instantiation: Dict[str, Any]
    styling_instantiation: Dict[str, Any]
    structure_specification: Optional[Dict[str, Any]] = None  # Upstream spec from structure
    styling_specification: Optional[Dict[str, Any]] = None    # Upstream spec from styling

    layout_specification: Optional[Dict[str, Any]] = None
    layout_instantiation: Optional[Dict[str, Any]] = None
