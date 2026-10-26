"""Lazy EvoDiagram engine port for backend workflow integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.evo_imports import ensure_evo_diagram_importable


@dataclass(frozen=True)
class StreamingEngineDependencies:
    """Engine objects required by the backend streaming workflow adapter."""

    workflow_cls: Any
    verifier_workflow_cls: Any
    iterative_refiner_workflow_cls: Any
    severity_cls: Any
    render_manifest: Any
    prepare_design_memory: Any = None
    learn_design_memory: Any = None


class WorkflowEnginePort(Protocol):
    """Backend-facing contract for loading EvoDiagram workflow primitives."""

    def load_text_workflow_cls(self) -> Any:
        """Return the synchronous text-to-diagram workflow class."""
        ...

    def load_streaming_dependencies(self) -> StreamingEngineDependencies:
        """Return the engine primitives used by streaming generation."""
        ...


class EvoDiagramWorkflowEnginePort:
    """Production engine port backed by the local EvoDiagram package.

    Imports stay inside method bodies so importing backend services does not
    eagerly import the agentic engine, mutate ``sys.path``, or require model
    runtime configuration.
    """

    def load_text_workflow_cls(self) -> Any:
        ensure_evo_diagram_importable()
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow

        return Text2DiagramWorkflow

    def load_streaming_dependencies(self) -> StreamingEngineDependencies:
        ensure_evo_diagram_importable()
        from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow
        from evo_diagram.agentic_system.verification_stage.checks.finding import Severity
        from evo_diagram.agentic_system.verification_stage.workflow import VerifierWorkflow
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        from evo_diagram.canvas_environment import render_manifest
        from evo_diagram.design_memory.web_memory import prepare_web_memory, learn_verified_refinement

        return StreamingEngineDependencies(
            workflow_cls=Text2DiagramWorkflow,
            verifier_workflow_cls=VerifierWorkflow,
            iterative_refiner_workflow_cls=IterativeRefinerWorkflow,
            severity_cls=Severity,
            render_manifest=render_manifest,
            prepare_design_memory=prepare_web_memory,
            learn_design_memory=learn_verified_refinement,
        )


__all__ = [
    "EvoDiagramWorkflowEnginePort",
    "StreamingEngineDependencies",
    "WorkflowEnginePort",
]
