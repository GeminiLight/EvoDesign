"""UnifiedGeneratorWorkflow — wires UnifiedGenerator into a single-node LangGraph.

One generation call produces the Excalidraw scene; then we run a trimmed post-pass:
a deterministic normalizer that mirrors the pipeline-mode converter's
z-order + group-title-dedup guarantees (so the unified path doesn't silently
regress the 2026-04 render-fidelity fixes), followed by the validator.
The group fitter is still skipped here because the unified generator already
derives group bounds itself. Contract failures return the current scene and
diagnostic to generation for at most two repairs before failing closed.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph

from evo_diagram.canvas_environment import audit_manifest, normalize_manifest, validate_manifest
from .state import UnifiedWorkflowState
from .generator import UnifiedGenerator
from .native_defaults import complete_native_elements, complete_native_semantics
from .sidecar import validate_semantic_sidecar

logger = logging.getLogger(__name__)
MAX_SCENE_ATTEMPTS = 3


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
        workflow.add_node("generate_validate", self._run_generation_cycle)
        workflow.set_entry_point("generate_validate")
        workflow.add_conditional_edges(
            "generate_validate",
            lambda state: "repair" if (
                state.validation_error and len(state.generation_attempts) < MAX_SCENE_ATTEMPTS
            ) else "done",
            {"repair": "generate_validate", "done": END},
        )
        return workflow.compile()

    def _run_generation_cycle(self, state: UnifiedWorkflowState) -> UnifiedWorkflowState:
        """Return contract failures to generation, without retrying runtime failures."""
        stage = "generate"
        state.candidate_output = None
        state.diagram_manifest = None
        state.structure_instantiation = None
        try:
            state = self._run_agent(state)
            stage = "normalize"
            state = self._run_normalizer(state)
            stage = "validate"
            state = self._run_validator(state)
        except (ValueError, RuntimeError) as exc:
            if isinstance(exc, RuntimeError) and stage != "normalize":
                raise
            if state.candidate_output is None:
                # Transport, prompt configuration, and JSON parsing failures
                # have their own policies; there is no scene to repair here.
                raise
            detail = str(exc)
            if exc.__cause__:
                detail += f" Cause: {exc.__cause__}"
            state.validation_error = detail
            state.generation_attempts.append({
                "attempt": len(state.generation_attempts) + 1,
                "stage": stage,
                "error": detail,
                "output": deepcopy(
                    state.diagram_manifest if state.diagram_manifest is not None
                    else state.candidate_output
                ),
            })
            logger.warning("[UnifiedGeneratorWorkflow] Scene validation failed: %s", detail)
        else:
            state.validation_error = None
            state.generation_attempts.append({
                "attempt": len(state.generation_attempts) + 1,
                "stage": "complete",
                "error": None,
            })
        self._save_attempt_report(state)
        return state

    @staticmethod
    def _save_attempt_report(state: UnifiedWorkflowState) -> None:
        if not state.validation_report_path:
            return
        path = Path(state.validation_report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        status = "complete" if not state.validation_error else (
            "failed" if len(state.generation_attempts) >= MAX_SCENE_ATTEMPTS else "repairing"
        )
        path.write_text(json.dumps({
            "status": status,
            "max_attempts": MAX_SCENE_ATTEMPTS,
            "attempts": state.generation_attempts,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

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
            complete_native_elements(manifest)
            complete_native_semantics(manifest)
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
        # Keep one-shot output visually consistent with the pipeline renderer.
        # The unified generator emits native Excalidraw, so this is a small
        # deterministic polish pass rather than a second layout strategy.
        from evo_diagram.canvas_environment import (
            normalize_architecture_style,
            rebuild_excalidraw_arrows,
            compact_architecture_layout,
        )
        polished = compact_architecture_layout(
            manifest,
            state.structure_instantiation,
        )
        if polished is not manifest:
            polished = rebuild_excalidraw_arrows(
                polished,
                state.structure_instantiation,
            )
        state.diagram_manifest = normalize_architecture_style(
            polished,
            state.structure_instantiation,
        )
        if state.diagram_manifest is not manifest:
            try:
                normalize_manifest(
                    state.diagram_manifest,
                    canvas_library="excalidraw",
                )
                state.structure_instantiation = validate_semantic_sidecar(
                    state.diagram_manifest
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    "UnifiedGeneratorWorkflow post-layout normalization failed; "
                    "refusing to render stale arrow geometry."
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
        if final.validation_error:
            raise ValueError(
                f"Unified scene remains invalid after {len(final.generation_attempts)} "
                f"attempts: {final.validation_error}"
            )
        logger.info("Unified generator workflow finished.")
        return final
