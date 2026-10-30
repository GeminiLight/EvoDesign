"""IterativeRefinerWorkflow — orchestrates verify → fix → render loop.

This is the **iteration orchestrator**. It composes three independent stages:

  1. **Verification** — ``verification_stage.checks.run_all_checks()``
     returns findings; the orchestrator does not own check logic.
  2. **Refinement** — deterministic fixers + LLM agent produce EditOps,
     which are applied to the manifest.
  3. **Rendering** — ``canvas_environment.render_png_result()`` re-draws
     the PNG for the next iteration's VLM input while preserving failures.

LangGraph nodes:

  load_inputs        read manifest, structure, verifier report
  run_iteration      verify → fix → apply → re-render (loop body)
  check_convergence  conditional edge: loop or finalize
  finalize           write refined manifest + image + report
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from evo_diagram.canvas_environment import render_png_result
from evo_diagram.canvas_runtime import normalize_canvas_library
from evo_diagram.agentic_system.verification_stage.checks.aggregator import run_all_checks
from evo_diagram.agentic_system.verification_stage.checks.finding import (
    Finding,
    summarize_findings,
)

from evo_diagram.agentic_system.refinement_stage.agent.llm_agent import (
    RefinerLLMAgent,
    build_manifest_summary,
)
from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
    DeterministicFixerError,
    patch_schema_defaults,
    run_all_deterministic_fixers,
)
from evo_diagram.agentic_system.refinement_stage.reports.refiner_report import (
    build_refiner_report,
    write_refiner_report,
)
from evo_diagram.agentic_system.refinement_stage.state import (
    EditApplyOutcome,
    IterationLog,
    SUPPORTED_REFINER_CANVAS_LIBRARIES,
    VerifierRefinerState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _findings_to_dicts(findings: List[Finding]) -> List[Dict[str, Any]]:
    return [f.to_dict() for f in findings]


def _finding_element_ids(findings: List[Finding]) -> set[str]:
    ids: set[str] = set()
    for finding in findings:
        if finding.element_id:
            ids.add(finding.element_id)
        loc = finding.location or {}
        if not isinstance(loc, dict):
            continue
        for key in ("other_id", "holder_id", "element_id"):
            value = loc.get(key)
            if isinstance(value, str) and value:
                ids.add(value)
        pairs = loc.get("pairs")
        if isinstance(pairs, list):
            for pair in pairs:
                if not isinstance(pair, (list, tuple)):
                    continue
                for value in pair:
                    if isinstance(value, str) and value:
                        ids.add(value)
    return ids


def _any_applied(outcomes: List[EditApplyOutcome]) -> bool:
    return any(outcome.applied for outcome in outcomes)


def _major_or_critical_count(findings: List[Finding]) -> int:
    return sum(
        1 for f in findings
        if f.severity.value in ("critical", "major")
    )


def _fingerprint_findings(findings: List[Finding]) -> str:
    """Deterministic string fingerprint of a findings list.

    Used for stagnation detection: if two consecutive iterations produce the
    same fingerprint, the fixes had no effect and we should stop.
    """
    parts = sorted(
        (f.category, f.element_id or "", f.message) for f in findings
    )
    return "|".join(f"{c}:{e}:{m}" for c, e, m in parts)


def _normalize_refiner_canvas_library(canvas_library: str) -> str:
    value = normalize_canvas_library(canvas_library)
    if value not in SUPPORTED_REFINER_CANVAS_LIBRARIES:
        raise ValueError(
            "IterativeRefinerWorkflow currently supports Excalidraw manifests "
            f"only; got canvas_library={canvas_library!r}."
        )
    return value


def _iter_log_to_prompt_dict(log: IterationLog) -> Dict[str, Any]:
    return {
        "iteration": log.iteration,
        "deterministic_edits": [
            {"applied": o.applied, "edit": o.edit.to_dict(), "error": o.error}
            for o in log.deterministic_edits
        ],
        "llm_edits": [
            {"applied": o.applied, "edit": o.edit.to_dict(), "error": o.error}
            for o in log.llm_edits
        ],
    }


def _run_objective_checks(state: VerifierRefinerState) -> List[Finding]:
    return run_all_checks(
        state.manifest,
        state.structure,
        layout_instantiation=state.layout_instantiation,
        canvas_library=state.canvas_library,
    )


def _apply_edit_batch(
    state: VerifierRefinerState,
    edits: List[Any],
    *,
    log: IterationLog,
    target_attr: str,
    log_prefix: str,
) -> List[EditApplyOutcome]:
    if not edits:
        return []

    state.manifest, outcomes = apply_edits(state.manifest, edits)
    setattr(log, target_attr, outcomes)
    applied_n = sum(1 for outcome in outcomes if outcome.applied)
    state.add_log(f"{log_prefix} emitted={len(edits)} applied={applied_n}")
    return outcomes


def _propose_llm_edits(
    state: VerifierRefinerState,
    *,
    llm_agent: RefinerLLMAgent,
    log: IterationLog,
    iteration: int,
) -> List[Any]:
    critique = (state.initial_report or {}).get("subjective") or None
    previous_attempts = [
        _iter_log_to_prompt_dict(iter_log) for iter_log in state.iteration_logs
    ]

    # Re-verify after deterministic pass so LLM sees remaining issues.
    findings_after_det = _run_objective_checks(state)

    try:
        proposed_edits = llm_agent.propose_edits(
            image_path=state.current_image_path,
            chart_type=(state.structure or {}).get("chart_type"),
            remaining_findings=_findings_to_dicts(findings_after_det),
            critique=critique,
            manifest_summary=build_manifest_summary(
                state.manifest,
                pinned_ids=_finding_element_ids(findings_after_det),
            ),
            previous_attempts=previous_attempts,
            iteration=iteration,
            max_iterations=state.max_iterations,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "LLM agent failed; degrading to deterministic-only this iteration"
        )
        state.add_error(f"iteration {iteration} LLM failed: {exc}")
        proposed_edits = []

    if getattr(llm_agent, "last_exhaustion_error", None):
        state.add_error(
            f"iteration {iteration} LLM exhausted retries: "
            f"{llm_agent.last_exhaustion_error}"
        )
        log.notes.append(
            f"LLM unavailable: {llm_agent.last_exhaustion_error}"
        )

    return proposed_edits


def _rerender_iteration_image(
    state: VerifierRefinerState,
    *,
    log: IterationLog,
    iteration: int,
) -> None:
    out_dir = Path(state.output_dir or Path(state.manifest_path).parent)
    if state.skip_rerender_between_iterations:
        log.notes.append("re-render skipped (--no-rerender)")
        return

    iter_image = out_dir / f"refined_iter_{iteration}.png"
    render_result = render_png_result(
        state.manifest,
        str(iter_image),
        canvas_library=state.canvas_library,
    )
    log.rerender_ok = render_result.ok
    if render_result.ok:
        log.rerender_path = render_result.output_path or str(iter_image)
        state.current_image_path = log.rerender_path
        state.add_log(f"  re-rendered to {iter_image}")
    else:
        log.rerender_error = render_result.error or None
        detail = f": {render_result.error}" if render_result.error else ""
        message = (
            "intermediate re-render failed; stopping before next LLM iteration "
            f"to avoid stale image input{detail}"
        )
        log.notes.append(message)
        state.add_error(message)
        state.status = "failed"


def _mark_convergence(
    state: VerifierRefinerState,
    *,
    log: IterationLog,
    findings_after_iter: List[Finding],
    edits_applied: bool,
    iteration: int,
) -> None:
    state.iteration_logs.append(log)
    state.current_iteration = iteration

    remaining_serious = _major_or_critical_count(findings_after_iter)
    current_fp = _fingerprint_findings(findings_after_iter)
    is_stagnant = (
        state._prev_findings_fingerprint is not None
        and current_fp == state._prev_findings_fingerprint
    )
    state._prev_findings_fingerprint = current_fp

    if is_stagnant:
        state.termination_reason = "stagnant"
        state.converged = remaining_serious == 0
        state.add_log(
            f"  → stagnant (findings unchanged after round {iteration}; "
            f"{remaining_serious} serious finding(s) remain)"
        )
        log.notes.append(
            "stagnation: findings identical to previous round"
        )
    elif not edits_applied:
        if remaining_serious == 0:
            state.converged = True
            state.termination_reason = "no_edits_resolved"
            state.add_log(
                "  → converged (no edits emitted and no serious findings remain)"
            )
        else:
            state.converged = False
            state.termination_reason = "fixed_point_unresolved"
            state.add_log(
                f"  → fixed point reached ({remaining_serious} serious finding(s) "
                "remain but no fixer can address them)"
            )
            log.notes.append(
                f"stopped at fixed point: {remaining_serious} serious finding(s) unfixable"
            )
    elif remaining_serious == 0:
        state.converged = True
        state.termination_reason = "resolved"
        state.add_log(
            "  → converged (no serious findings remain after this round)"
        )


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def _node_load_inputs(state: VerifierRefinerState) -> VerifierRefinerState:
    state.add_log(f"loading manifest from {state.manifest_path}")

    manifest = _load_json(state.manifest_path)
    if manifest is None:
        state.add_error(f"could not load manifest from {state.manifest_path}")
        state.status = "failed"
        return state
    state.manifest = manifest

    if state.structure_path:
        state.structure = _load_json(state.structure_path)
        if state.structure is None:
            state.add_error(
                f"could not load explicit structure_path from {state.structure_path}; "
                "refiner cannot safely run structure-dependent fixes."
            )
            state.status = "failed"
            return state

    if state.layout_path:
        state.layout_instantiation = _load_json(state.layout_path)
        if state.layout_instantiation is None:
            state.add_error(
                f"could not load explicit layout_path from {state.layout_path}; "
                "refiner cannot safely run layout-dependent fixes."
            )
            state.status = "failed"
            return state

    if not state.verifier_report_path:
        candidate = Path(state.manifest_path).parent / "verifier_report.json"
        if candidate.exists():
            state.verifier_report_path = str(candidate)

    state.initial_report = _load_json(state.verifier_report_path)
    if state.initial_report is None:
        state.add_log(
            f"no pre-existing verifier_report found "
            f"(looked at {state.verifier_report_path}); will compute fresh "
            "objective findings each iteration."
        )

    # Pre-processing: patch missing schema fields so all downstream code
    # sees well-formed elements. Runs once (not per-iteration).
    patch_schema_defaults(state.manifest)

    state.current_image_path = state.image_path
    state.status = "loaded"
    return state


def _run_one_iteration(
    state: VerifierRefinerState,
    *,
    llm_agent: Optional[RefinerLLMAgent],
) -> VerifierRefinerState:
    """Single iteration: verify → fix → apply → verify → render."""
    iteration = state.current_iteration + 1
    state.add_log(f"--- iteration {iteration}/{state.max_iterations} ---")

    # ── Phase 1: Verify ──────────────────────────────────────────────
    findings_before = _run_objective_checks(state)
    state.latest_findings = findings_before

    log = IterationLog(
        iteration=iteration,
        findings_before=summarize_findings(findings_before),
    )

    # ── Phase 2: Fix — deterministic ─────────────────────────────────
    try:
        det_edits = run_all_deterministic_fixers(
            state.manifest, findings_before, state.structure
        )
    except DeterministicFixerError as exc:
        message = str(exc)
        state.add_error(message)
        state.status = "failed"
        log.notes.append(message)
        state.iteration_logs.append(log)
        state.current_iteration = iteration
        return state

    det_outcomes = _apply_edit_batch(
        state,
        det_edits,
        log=log,
        target_attr="deterministic_edits",
        log_prefix="  deterministic:",
    )

    # ── Phase 3: Fix — LLM ──────────────────────────────────────────
    llm_outcomes: List[EditApplyOutcome] = []
    if llm_agent is not None:
        proposed_edits = _propose_llm_edits(
            state,
            llm_agent=llm_agent,
            log=log,
            iteration=iteration,
        )

        if proposed_edits:
            llm_outcomes = _apply_edit_batch(
                state,
                proposed_edits,
                log=log,
                target_attr="llm_edits",
                log_prefix="  llm:          ",
            )
        else:
            state.add_log("  llm:           emitted=0 (no proposals)")

    # ── Phase 4: Verify (post-fix) ───────────────────────────────────
    findings_after_iter = _run_objective_checks(state)
    log.findings_after = summarize_findings(findings_after_iter)
    state.latest_findings = findings_after_iter

    # ── Phase 5: Re-render ───────────────────────────────────────────
    _rerender_iteration_image(state, log=log, iteration=iteration)
    if state.status == "failed":
        state.iteration_logs.append(log)
        state.current_iteration = iteration
        return state

    # ── Phase 6: Convergence check ───────────────────────────────────
    _mark_convergence(
        state,
        log=log,
        findings_after_iter=findings_after_iter,
        edits_applied=_any_applied(det_outcomes) or _any_applied(llm_outcomes),
        iteration=iteration,
    )

    return state


def _node_finalize(
    state: VerifierRefinerState, *, vlm_model_name: str = "unknown"
) -> VerifierRefinerState:
    out_dir = Path(state.output_dir or Path(state.manifest_path).parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed_before_finalize = state.status == "failed"

    if failed_before_finalize:
        state.add_log("skipping refined manifest/render because refiner failed before finalize")
    else:
        should_promote_refined = state.converged is True
        manifest_name = "refined_manifest.json" if should_promote_refined else "candidate_manifest.json"
        image_name = "refined_diagram.png" if should_promote_refined else "candidate_diagram.png"
        output_manifest_path = out_dir / manifest_name
        output_image_path = out_dir / image_name

        stale_paths = (
            out_dir / "refined_manifest.json",
            out_dir / "refined_diagram.png",
            out_dir / "candidate_manifest.json",
            out_dir / "candidate_diagram.png",
        )
        for artifact_path in stale_paths:
            try:
                artifact_path.unlink(missing_ok=True)
            except OSError as exc:
                state.add_error(f"could not remove stale refiner artifact {artifact_path}: {exc}")
                state.status = "failed"

        final_image_ready = False
        if state.status != "failed":
            if should_promote_refined or state.skip_rerender_between_iterations:
                render_result = render_png_result(
                    state.manifest,
                    str(output_image_path),
                    canvas_library=state.canvas_library,
                )
                if render_result.ok:
                    final_image_ready = True
                else:
                    detail = f": {render_result.error}" if render_result.error else ""
                    label = "final" if should_promote_refined else "candidate"
                    state.add_error(f"{label} render failed{detail}")
                    state.status = "failed"
                    try:
                        output_image_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning(
                            "Could not remove failed refiner image: %s",
                            output_image_path,
                            exc_info=True,
                        )
            elif state.current_image_path and Path(state.current_image_path).exists():
                try:
                    shutil.copyfile(state.current_image_path, output_image_path)
                    final_image_ready = True
                    state.add_log(f"copied non-converged candidate image to {output_image_path}")
                except OSError as exc:
                    state.add_error(f"could not write candidate image: {exc}")

        if state.status != "failed":
            try:
                output_manifest_path.write_text(
                    json.dumps(state.manifest, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                if should_promote_refined:
                    state.refined_manifest_path = str(output_manifest_path)
                    state.add_log(f"wrote refined manifest to {output_manifest_path}")
                    if final_image_ready:
                        state.refined_image_path = str(output_image_path)
                        state.add_log(f"final render → {output_image_path}")
                else:
                    state.candidate_manifest_path = str(output_manifest_path)
                    state.add_log(f"wrote non-converged candidate manifest to {output_manifest_path}")
                    if final_image_ready:
                        state.candidate_image_path = str(output_image_path)
            except Exception as exc:  # noqa: BLE001
                state.add_error(f"could not write refiner manifest: {exc}")
                state.status = "failed"
                if final_image_ready:
                    try:
                        output_image_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning(
                            "Could not remove refiner image after manifest write failure: %s",
                            output_image_path,
                            exc_info=True,
                        )

    if state.status != "failed":
        exhausted_iterations = (
            state.current_iteration >= state.max_iterations
            and not state.converged
        )
        if state.termination_reason is None and exhausted_iterations:
            state.termination_reason = "max_iterations_exhausted"
        state.status = "reported_degraded" if state.errors else "reported"
    report = build_refiner_report(state, vlm_model_name=vlm_model_name)
    paths = write_refiner_report(
        report,
        output_dir=str(out_dir),
        markdown_name="refiner_report.md" if state.emit_markdown else None,
    )
    state.refiner_report_path = paths.get("json")
    if state.status != "failed":
        state.status = "reported_degraded" if state.errors else "reported"
    return state


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class IterativeRefinerWorkflow:
    """Orchestrates verify → fix → render iteration loop.

    Verification, refinement, and rendering are independent stages — this
    workflow composes them into an iteration loop with convergence checking.
    """

    def __init__(self, llm_agent: Optional[RefinerLLMAgent] = None) -> None:
        self._llm_agent: Optional[RefinerLLMAgent] = llm_agent
        self.graph = self._build_graph()

    def _ensure_llm(self) -> RefinerLLMAgent:
        if self._llm_agent is None:
            self._llm_agent = RefinerLLMAgent()
        return self._llm_agent

    def _build_graph(self):
        vlm_model_name = "unknown"
        try:
            from evo_diagram.config.model_loader import ModelConfig
            params = ModelConfig.get_default().get_model_config("refiner")
            vlm_model_name = params.get("model", "unknown")
        except (KeyError, FileNotFoundError):
            pass

        graph = StateGraph(VerifierRefinerState)

        graph.add_node("load_inputs", _node_load_inputs)
        graph.add_node("run_iteration", self._iteration_node)
        graph.add_node(
            "finalize", partial(_node_finalize, vlm_model_name=vlm_model_name)
        )

        graph.add_edge(START, "load_inputs")
        graph.add_conditional_edges(
            "load_inputs",
            lambda s: "finalize" if s.status == "failed" else "run_iteration",
            {"finalize": "finalize", "run_iteration": "run_iteration"},
        )
        graph.add_conditional_edges(
            "run_iteration",
            self._after_iteration,
            {"run_iteration": "run_iteration", "finalize": "finalize"},
        )
        graph.add_edge("finalize", END)

        return graph.compile()

    def _iteration_node(
        self, state: VerifierRefinerState
    ) -> VerifierRefinerState:
        return _run_one_iteration(state, llm_agent=self._ensure_llm())

    def _after_iteration(self, state: VerifierRefinerState) -> str:
        if state.status == "failed":
            return "finalize"
        if state.termination_reason:
            return "finalize"
        if state.converged:
            return "finalize"
        if state.current_iteration >= state.max_iterations:
            if state.termination_reason is None:
                state.termination_reason = "max_iterations_exhausted"
            return "finalize"
        return "run_iteration"

    def run(
        self,
        manifest_path: str,
        image_path: str,
        *,
        verifier_report_path: Optional[str] = None,
        structure_path: Optional[str] = None,
        layout_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        canvas_library: str = "excalidraw",
        max_iterations: int = 3,
        skip_rerender_between_iterations: bool = False,
        emit_markdown: bool = False,
    ) -> VerifierRefinerState:
        canvas_library = _normalize_refiner_canvas_library(canvas_library)
        initial = VerifierRefinerState(
            manifest_path=manifest_path,
            image_path=image_path,
            verifier_report_path=verifier_report_path,
            structure_path=structure_path,
            layout_path=layout_path,
            output_dir=output_dir,
            canvas_library=canvas_library,
            max_iterations=max_iterations,
            skip_rerender_between_iterations=skip_rerender_between_iterations,
            emit_markdown=emit_markdown,
        )
        result = self.graph.invoke(initial)
        if isinstance(result, VerifierRefinerState):
            return result
        if isinstance(result, dict):
            return VerifierRefinerState.model_validate(result)
        return initial


__all__ = ["IterativeRefinerWorkflow"]
