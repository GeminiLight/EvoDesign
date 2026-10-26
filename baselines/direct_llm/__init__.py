"""
Baseline Direct LLM Workflow

A simplified workflow that uses LLM to directly convert text to Excalidraw-renderable JSON.
"""

__all__ = [
    "BaselineWorkflow",
    "WorkflowState",
    "DiagramGenerator",
    "create_workflow",
]


def __getattr__(name):
    """Lazy public exports so module entrypoint help does not load LLM stacks."""
    if name in {"BaselineWorkflow", "create_workflow"}:
        from .workflow import BaselineWorkflow, create_workflow

        value = BaselineWorkflow if name == "BaselineWorkflow" else create_workflow
    elif name == "WorkflowState":
        from .state import WorkflowState

        value = WorkflowState
    elif name == "DiagramGenerator":
        from .diagram_generator import DiagramGenerator

        value = DiagramGenerator
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value
