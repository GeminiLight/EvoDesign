"""UnifiedGeneratorWorkflow — wires UnifiedGenerator into a single-node LangGraph.

One LLM call produces the Excalidraw scene; then we run a trimmed post-pass:
a deterministic normalizer that mirrors the pipeline-mode converter's
z-order + group-title-dedup guarantees (so the unified path doesn't silently
regress the 2026-04 render-fidelity fixes), followed by the validator.
The group fitter is still skipped here because the unified generator already
derives group bounds itself.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph

from evo_diagram.canvas_environment import audit_manifest, normalize_manifest, validate_manifest
from .state import UnifiedWorkflowState
from .generator import UnifiedGenerator
from .sidecar import validate_semantic_sidecar

logger = logging.getLogger(__name__)


class UnifiedGeneratorWorkflow:
    """Single-shot workflow: UnifiedGenerator -> normalizer -> validator.

    The normalizer is a belt for the pipeline-mode converter's suspenders:
    group frames paint behind their children, duplicate bound+standalone
    titles collapse to a single header, and fractional indices become
    zero-padded so lexicographic order matches numeric order. All three
    are enforced by the pipeline's ``InstantiationToExcalidrawConverter``
    but were silently bypassed on the ``--mode oneshot`` path before
    this node was added.
    """

    def __init__(
        self,
        model: BaseChatModel,
        full_domain_knowledge: bool = True,
    ) -> None:
        self.agent = UnifiedGenerator(
            model=model,
            full_domain_knowledge=full_domain_knowledge,
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(UnifiedWorkflowState)
        workflow.add_node("generate_scene", self._run_agent)
        workflow.add_node("normalize_scene", self._run_normalizer)
        workflow.add_node("validate_scene", self._run_validator)
        workflow.set_entry_point("generate_scene")
        workflow.add_edge("generate_scene", "normalize_scene")
        workflow.add_edge("normalize_scene", "validate_scene")
        workflow.add_edge("validate_scene", END)
        return workflow.compile()

    def _run_agent(self, state: UnifiedWorkflowState) -> UnifiedWorkflowState:
        return self.agent.run(state)

    def _run_normalizer(self, state: UnifiedWorkflowState) -> UnifiedWorkflowState:
        """Enforce layer-based z-order + title dedup on the LLM-emitted scene.

        Normalization is part of the one-shot contract: if it fails, the scene is
        not safe to pass to render because z-order and title semantics may be
        wrong while still passing schema validation.
        """
        manifest = state.diagram_manifest
        if not isinstance(manifest, dict):
            return state
        try:
            normalize_manifest(manifest, canvas_library="excalidraw")
            logger.info(
                "[UnifiedGeneratorWorkflow/normalizer] z-order + title dedup applied (%d elements)",
                len(manifest.get("elements") or []),
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "UnifiedGeneratorWorkflow normalizer failed; refusing to render "
                "an unnormalized one-shot manifest."
            ) from exc
        try:
            state.structure_instantiation = validate_semantic_sidecar(manifest)
        except ValueError as exc:
            raise ValueError(
                "UnifiedGeneratorWorkflow normalizer produced an invalid "
                f"semantic sidecar: {exc}"
            ) from exc
        return state

    def _run_validator(self, state: UnifiedWorkflowState) -> UnifiedWorkflowState:
        manifest = state.diagram_manifest or {}
        # Validator mutates nothing; schema errors must stop one-shot output
        # before it reaches the renderer, especially when the caller disables
        # the downstream verifier.
        report = validate_manifest(manifest, canvas_library="excalidraw")
        if not report.get("is_valid", True):
            errors = report.get("errors", []) or []
            for err in errors:
                logger.error("[UnifiedGeneratorWorkflow] validator: %s", err)
            message = "; ".join(str(err) for err in errors) or "unknown schema error"
            raise ValueError(f"UnifiedGeneratorWorkflow schema validation failed: {message}")
        audit_report = audit_manifest(
            manifest,
            structure_instantiation=state.structure_instantiation,
            canvas_library="excalidraw",
        )
        state.audit_warnings = list(audit_report.warnings)
        return state

    def run(self, state: UnifiedWorkflowState) -> UnifiedWorkflowState:
        logger.info("Starting unified generator workflow (single-shot)...")
        result = self.graph.invoke(state)
        final = (
            UnifiedWorkflowState(**result) if isinstance(result, dict) else result
        )
        logger.info("Unified generator workflow finished.")
        return final
