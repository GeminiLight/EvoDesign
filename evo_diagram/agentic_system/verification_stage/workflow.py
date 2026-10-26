"""VerifierWorkflow — LangGraph orchestrator for objective + subjective verify.

Four nodes:
    load_inputs           load manifest / structure / layout JSON from disk
    run_objective_checks  pure-Python, no LLM
    run_subjective_critic single VLM call (skipped when state.skip_critic)
    build_report          merge → write verifier_report.json (+.md optional)

Each node only mutates ``state`` and never raises out of the graph: failures
go into ``state.errors`` so partial results still get written. This matches
the render/validation boundary's "always emit something" philosophy.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from evo_diagram.canvas_environment import validate_png_file

from .checks import run_all_checks, summarize_findings
from .reports.report_builder import build_report, write_report
from .state import VerifierState
from ..common.design_constraints import constraint_prompt

logger = logging.getLogger(__name__)


def _load_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load JSON from %s: %s", path, exc)
        return None


def _resolve_layout_path(structure_path: Optional[str]) -> Optional[str]:
    """If structure_path is .../1_structure/structure_instantiation.json, look
    for the sibling .../3_layout/layout_instantiation.json."""
    if not structure_path:
        return None
    p = Path(structure_path)
    if "1_structure" not in p.parts:
        return None
    layout_p = Path(*[
        "3_layout" if part == "1_structure" else part for part in p.parts
    ]).with_name("layout_instantiation.json")
    if layout_p.exists():
        return str(layout_p)
    return None


def _node_load_inputs(state: VerifierState) -> VerifierState:
    state.add_log(f"loading inputs: manifest={state.manifest_path}")

    manifest = _load_json(state.manifest_path)
    if manifest is None:
        state.add_error(f"Could not load manifest from {state.manifest_path}")
        state.status = "failed"
        return state
    state.manifest = manifest

    if state.structure_path:
        state.structure = _load_json(state.structure_path)
        if state.structure is None:
            state.add_error(
                f"Could not load explicit structure_path from {state.structure_path}; "
                "structure-dependent verification checks were skipped."
            )

    explicit_layout_path = state.layout_path
    layout_path = explicit_layout_path or _resolve_layout_path(state.structure_path)
    if layout_path:
        state.layout_instantiation = _load_json(layout_path)
        if state.layout_instantiation:
            state.add_log(f"loaded layout_instantiation from {layout_path}")
        elif explicit_layout_path:
            state.add_error(
                f"Could not load explicit layout_path from {layout_path}; "
                "layout-dependent verification checks cannot run."
            )
        else:
            state.add_log(f"layout_path {layout_path} could not be loaded")

    image_p = Path(state.image_path)
    try:
        validate_png_file(image_p, context="verifier input")
        state.add_log(f"loaded PNG image from {state.image_path}")
    except RuntimeError as exc:
        state.add_error(str(exc))
        state.status = "failed"
        return state

    state.status = "loaded"
    return state


def _node_run_objective_checks(state: VerifierState) -> VerifierState:
    if state.manifest is None:
        return state
    try:
        findings = run_all_checks(
            manifest=state.manifest,
            structure=state.structure,
            layout_instantiation=state.layout_instantiation,
            canvas_library=state.canvas_library,
            skip_categories=state.skip_checks,
        )
        state.objective_findings = findings
        state.objective_summary = summarize_findings(findings)
        state.add_log(f"objective: {len(findings)} findings ({state.objective_summary})")
        state.status = "checked"
    except Exception as exc:  # noqa: BLE001
        logger.exception("objective checks failed")
        state.add_error(f"objective checks failed: {exc}")
        state.status = "failed"
    return state


def _node_run_subjective_critic(state: VerifierState) -> VerifierState:
    if state.skip_critic:
        state.add_log("subjective critic skipped (--no-critic)")
        return state

    image_p = Path(state.image_path)
    if not image_p.exists():
        state.add_error(f"cannot critique — image missing at {state.image_path}")
        return state

    try:
        from .critic.critic_agent import VerifierCriticAgent, review_image_edge_limit

        chart_type = None
        if isinstance(state.structure, dict):
            chart_type = state.structure.get("chart_type")

        agent = VerifierCriticAgent(
            max_image_edge=review_image_edge_limit(state.image_path, state.manifest),
        )
        critique = agent.critique(
            image_path=state.image_path,
            chart_type=chart_type,
            source_text=(state.source_text or "") + constraint_prompt(state.design_constraints),
            objective_summary=dict(state.objective_summary) if state.objective_summary else None,
        )
        state.critique = critique
        state.status = "critiqued"
        state.add_log(
            f"subjective critic ok: structure={critique.structure.score:.1f}, "
            f"styling={critique.styling.score:.1f}, "
            f"layout={critique.layout.score:.1f}, overall={critique.overall_score:.1f}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("subjective critic failed")
        state.add_error(f"subjective critic failed: {exc}", blocking=False)
    return state


def _node_build_report(state: VerifierState) -> VerifierState:
    out_dir = state.output_dir or str(Path(state.manifest_path).parent)

    vlm_model = "unknown"
    try:
        from evo_diagram.config.model_loader import ModelConfig
        params = ModelConfig.get_default().get_model_config("verifier")
        vlm_model = params.get("model", "unknown")
    except (KeyError, FileNotFoundError):
        pass

    if state.has_blocking_errors:
        final_status = "reported_with_errors"
    elif state.has_blocking_findings:
        final_status = "reported_with_findings"
    elif state.has_nonblocking_errors:
        final_status = "reported_with_warnings"
    else:
        final_status = "reported"
    state.status = final_status
    report = build_report(state, vlm_model_name=vlm_model)
    state.report = report

    try:
        paths = write_report(
            report,
            output_dir=out_dir,
            markdown_name="verifier_report.md" if state.emit_markdown else None,
        )
        state.report_path = paths.get("json")
        state.add_log(f"report written to {state.report_path}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to write verifier report")
        state.add_error(f"failed to write report: {exc}", blocking=False)
        state.status = "reported_with_warnings"
        state.report = build_report(state, vlm_model_name=vlm_model)

    return state


class VerifierWorkflow:
    """Compile-once / invoke-many wrapper around the 4-node verifier graph."""

    def __init__(self) -> None:
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(VerifierState)

        graph.add_node("load_inputs", _node_load_inputs)
        graph.add_node("run_objective_checks", _node_run_objective_checks)
        graph.add_node("run_subjective_critic", _node_run_subjective_critic)
        graph.add_node("build_report", _node_build_report)

        graph.add_edge(START, "load_inputs")
        graph.add_conditional_edges(
            "load_inputs",
            lambda s: "build_report" if s.status == "failed" else "run_objective_checks",
            {"build_report": "build_report", "run_objective_checks": "run_objective_checks"},
        )
        graph.add_conditional_edges(
            "run_objective_checks",
            lambda s: "build_report" if s.status == "failed" else "run_subjective_critic",
            {"build_report": "build_report", "run_subjective_critic": "run_subjective_critic"},
        )
        graph.add_edge("run_subjective_critic", "build_report")
        graph.add_edge("build_report", END)

        return graph.compile()

    def run(
        self,
        manifest_path: str,
        image_path: str,
        *,
        canvas_library: str = "excalidraw",
        structure_path: Optional[str] = None,
        layout_path: Optional[str] = None,
        source_text: Optional[str] = None,
        design_constraints: str = "",
        output_dir: Optional[str] = None,
        skip_critic: bool = False,
        skip_checks: Optional[list[str]] = None,
        emit_markdown: bool = False,
    ) -> VerifierState:
        """Run the full workflow end-to-end. Returns the final state."""
        initial = VerifierState(
            manifest_path=manifest_path,
            image_path=image_path,
            canvas_library=canvas_library,
            structure_path=structure_path,
            layout_path=layout_path,
            source_text=source_text,
            design_constraints=design_constraints,
            output_dir=output_dir,
            skip_critic=skip_critic,
            skip_checks=skip_checks or [],
            emit_markdown=emit_markdown,
        )
        # LangGraph's invoke returns a plain dict (the state schema), so we
        # rebuild the pydantic model for typed access at call sites.
        result = self.graph.invoke(initial)
        if isinstance(result, VerifierState):
            return result
        if isinstance(result, dict):
            return VerifierState.model_validate(result)
        # Should never happen; defensively return the original.
        return initial


__all__ = ["VerifierWorkflow"]
