from __future__ import annotations

import warnings

from pydantic.warnings import PydanticDeprecatedSince211

from evo_diagram.agentic_system.common.workflow_state_base import WorkflowStateBase


def test_update_stage_uses_class_model_fields_without_pydantic_deprecation():
    state = WorkflowStateBase()

    with warnings.catch_warnings():
        warnings.simplefilter("error", PydanticDeprecatedSince211)
        state.update_stage("diagram_type", "flowchart")

    assert state.current_stage == "diagram_type"
    assert state.diagram_type == "flowchart"
