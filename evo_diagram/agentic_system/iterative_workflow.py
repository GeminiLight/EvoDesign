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
  run_iteration      verify → fix → apply → repair → re-render (loop body)
  check_convergence  conditional edge: loop or finalize
  finalize           write refined manifest + image + report

Two invariants the loop body maintains, both of which used to be missing:

* **Derived geometry is repaired after every edit batch.** Arrow polylines and
  the elements-array paint order cannot be expressed as EditOps, so they are
  recomputed in place once the batch has been applied. Otherwise every shape
  the refiner moved left its arrows pointing at empty canvas.
* **A round that makes things worse is rolled back.** Each round starts from a
  deepcopy snapshot and is discarded if its post-fix findings score is worse
  than what it started from, so the manifest at every round boundary is the
  best result seen so far — not merely the last one attempted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from .quality_policy import objective_rank, needs_refinement

from evo_diagram.canvas_environment import ANALYSIS_RENDER_SCALE, normalize_manifest, render_png_result
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
from evo_diagram.agentic_system.refinement_stage.fixers.arrow_reroute import (
    reroute_bound_arrows,
)
from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
    DeterministicFixerError,
    patch_schema_defaults,
    reorder_elements_by_index,
    run_all_deterministic_fixers,
)
from evo_diagram.agentic_system.refinement_stage.reports.refiner_report import (
    build_refiner_report,
    write_refiner_report,
)
from evo_diagram.agentic_system.refinement_stage.state import (
    EditApplyOutcome,
    IterationLog,
    PreparedIteration,
    SUPPORTED_REFINER_CANVAS_LIBRARIES,
    VerifierRefinerState,
)
from evo_diagram.canvas_environment import (
    rebuild_excalidraw_arrows,
)

logger = logging.getLogger(__name__)


def _manifest_fingerprint(manifest: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def _input_fingerprint(state: VerifierRefinerState) -> str:
    """Bind prepared work to these exact inputs, never a different request."""
    digest = hashlib.sha256(state.design_constraints.encode())
    for path in (state.manifest_path, state.image_path, state.structure_path, state.layout_path):
        digest.update(str(path).encode())
        if path:
            digest.update(Path(path).read_bytes())
    return digest.hexdigest()


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


# Weighted histogram used to compare two rounds. Convergence still keys off
# "no serious findings", but progress must be measured across ALL severities,
# otherwise a round that trades one MAJOR for six MINORs reads as an
# improvement — and a round that wrecks the layout and happens to end at zero
# serious findings reads as success.
_SEVERITY_WEIGHTS = {"critical": 100.0, "major": 10.0, "minor": 1.0, "info": 0.0}


def _findings_score(findings: List[Finding]) -> float:
    """Lower is better. 0.0 means nothing above INFO remains."""
    return sum(
        _SEVERITY_WEIGHTS.get(f.severity.value, 1.0) for f in findings
    )


def _touched_geometry_ids(*outcome_batches: List[EditApplyOutcome]) -> set[str]:
    """Ids whose position or size actually changed in the given batches."""
    touched: set[str] = set()
    for outcomes in outcome_batches:
        for outcome in outcomes:
            if not outcome.applied or outcome.edit is None:
                continue
            if outcome.edit.op in ("set_position", "set_size", "set_icon"):
                touched.add(outcome.edit.id)
    return touched


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


def _outcome_to_prompt_dict(outcome: EditApplyOutcome) -> Dict[str, Any]:
    return {
        "applied": outcome.applied,
        "edit": outcome.edit.to_dict() if outcome.edit is not None else None,
        "error": outcome.error,
    }


def _iter_log_to_prompt_dict(log: IterationLog) -> Dict[str, Any]:
    return {
        "iteration": log.iteration,
        "deterministic_edits": [
            _outcome_to_prompt_dict(o) for o in log.deterministic_edits
        ],
        "llm_edits": [_outcome_to_prompt_dict(o) for o in log.llm_edits],
    }


LAYOUT_AUDIT_SKIP_NOTE = (
    "layout_audit — no layout_instantiation was provided, so the layout-stage "
    "checks (empty title / edge classifier) did NOT run. Pass "
    "--layout to enable them."
)


def _objective_skip_categories(state: VerifierRefinerState) -> List[str]:
    """Objective checks the refiner must not run this session.

    ``check_layout_audit`` returns a CRITICAL when layout is missing, which is
    right for the verifier (a configured check silently returning [] is worse
    than a loud failure) but fatal for the refiner: no fixer can ever produce a
    layout_instantiation, so the serious-finding count never reaches zero,
    ``converged`` stays False forever, and a fully repaired diagram is written
    out as a mere candidate with exit code 1. ``--layout`` is documented as
    optional, so the refiner skips the check and says so in the report instead
    of failing on an input it never required.
    """
    skip: List[str] = list(state.skip_checks or [])
    if state.layout_instantiation is None and "layout_audit" not in skip:
        skip.append("layout_audit")
    return skip


def _run_objective_checks(state: VerifierRefinerState) -> List[Finding]:
    skip = _objective_skip_categories(state)
    return run_all_checks(
        state.manifest,
        state.structure,
        layout_instantiation=state.layout_instantiation,
        canvas_library=state.canvas_library,
        skip_categories=skip or None,
    )


def _apply_edit_batch(
    state: VerifierRefinerState,
    edits: List[Any],
    *,
    log: IterationLog,
    target_attr: str,
    log_prefix: str,
) -> List[EditApplyOutcome]:
    from .common.design_constraints import icons_disabled, locked_scene_elements
    constraints = state.design_constraints or (state.initial_report or {}).get("design_constraints", "")
    locked_before = locked_scene_elements(state.manifest, constraints)
    snapshot = deepcopy(state.manifest) if locked_before else None
    state.manifest, outcomes = apply_edits(state.manifest, edits, allow_icons=not icons_disabled(constraints))
    # extend, not assign: schema-rejected LLM proposals were already recorded
    # on this log before anything reached the dispatcher.
    getattr(log, target_attr).extend(outcomes)
    applied_n = sum(1 for outcome in outcomes if outcome.applied)
    state.add_log(f"{log_prefix} emitted={len(edits)} applied={applied_n}")
    geometry_refreshed = _refresh_edited_geometry(state, outcomes, log=log)
    _repair_derived_geometry(
        state,
        log=log,
        touched_ids=_touched_geometry_ids(outcomes),
        geometry_refreshed=geometry_refreshed,
    )
    if snapshot is not None and locked_scene_elements(state.manifest, constraints) != locked_before:
        state.manifest = snapshot
        for outcome in outcomes:
            if outcome.applied:
                outcome.applied = False
                outcome.error = "Batch rejected: would change a user-locked element"
        log.notes.append("Preserved locked elements; rejected the entire conflicting edit batch")
    return outcomes


def _refresh_edited_geometry(
    state: VerifierRefinerState,
    outcomes: List[EditApplyOutcome],
    *,
    log: IterationLog,
) -> bool:
    """Refresh routes and label geometry after shape or typography edits."""
    manifest = state.manifest or {}
    metadata = manifest.get("_meta") or {}
    if not state.structure or not metadata.get("edge_data"):
        return False
    elements = {element.get("id"): element for element in manifest.get("elements", [])}
    changed_shapes = {
        outcome.edit.id
        for outcome in outcomes
        if outcome.applied
        and outcome.edit.op in {"set_position", "set_size", "set_icon"}
        and elements.get(outcome.edit.id, {}).get("type")
        in {"rectangle", "ellipse", "diamond", "image"}
    }
    changed_edge_labels = {
        outcome.edit.id
        for outcome in outcomes
        if outcome.applied
        and outcome.edit.op == "set_style"
        and {"fontSize", "fontFamily"}.intersection(outcome.edit.payload)
        and elements.get(outcome.edit.id, {}).get("type") == "text"
        and (
            (elements[outcome.edit.id].get("meta") or {}).get("semantic_edge_id")
            or elements.get(elements[outcome.edit.id].get("containerId"), {}).get("type") == "arrow"
        )
    }
    if not changed_shapes and not changed_edge_labels:
        return False

    # Excalidraw exports authored polylines as supplied; changing a shape's
    # bbox alone does not retarget or reroute them. Reuse the scene router,
    # which also preserves semantic IDs and authored connector styles.
    state.manifest = rebuild_excalidraw_arrows(manifest, state.structure)
    normalize_manifest(state.manifest, canvas_library=state.canvas_library)
    message = (
        f"rebuilt connectors after edits to {len(changed_shapes)} shape(s) "
        f"and {len(changed_edge_labels)} edge label(s)"
    )
    log.notes.append(message)
    state.add_log(message)
    return True


def _propose_llm_edits(
    state: VerifierRefinerState,
    *,
    llm_agent: RefinerLLMAgent,
    log: IterationLog,
    iteration: int,
    image_note: Optional[str] = None,
) -> List[Any]:
    critique = (state.initial_report or {}).get("subjective") or None
    previous_attempts = [
        _iter_log_to_prompt_dict(iter_log) for iter_log in state.iteration_logs
    ]
    # This round's own deterministic edits are not in ``iteration_logs`` yet —
    # the log is only appended at convergence marking — so without this the
    # model is told nothing about the fixes that just moved the elements it is
    # looking at, and re-proposes them.
    previous_attempts.append(_iter_log_to_prompt_dict(log))

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
            image_note=image_note,
            design_constraints=state.design_constraints or (state.initial_report or {}).get("design_constraints", ""),
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

    _record_rejected_llm_edits(
        state,
        llm_agent=llm_agent,
        log=log,
        iteration=iteration,
        accepted=len(proposed_edits),
    )
    return proposed_edits


def _record_rejected_llm_edits(
    state: VerifierRefinerState,
    *,
    llm_agent: RefinerLLMAgent,
    log: IterationLog,
    iteration: int,
    accepted: int,
) -> None:
    """Log LLM proposals that never became EditOps.

    ``EditOp`` forbids extra keys, so a single drifted field name invalidates a
    whole proposal. Dropping those with only a logger warning made "20 edits
    proposed, 20 malformed" indistinguishable from "the model saw nothing to
    fix" — the same ambiguity ``last_exhaustion_error`` was added to close for
    the transport failure path.
    """
    rejected = list(getattr(llm_agent, "last_rejected_edits", None) or [])
    if not rejected:
        return

    for item in rejected:
        log.llm_edits.append(
            EditApplyOutcome(
                edit=None,
                applied=False,
                error=item.get("error") or "schema: rejected",
                raw=item.get("raw"),
            )
        )
    state.add_log(f"  llm:           rejected={len(rejected)} (schema)")
    log.notes.append(
        f"{len(rejected)} LLM proposal(s) rejected by EditOp schema validation"
    )
    if accepted == 0:
        state.add_error(
            f"iteration {iteration} LLM: all {len(rejected)} proposed edit(s) "
            "failed EditOp schema validation; no edit reached the manifest"
        )


def _repair_derived_geometry(
    state: VerifierRefinerState,
    *,
    log: IterationLog,
    touched_ids: set[str],
    geometry_refreshed: bool = False,
) -> None:
    """Restore the two invariants no EditOp can express.

    1. **Arrow polylines.** An Excalidraw arrow bakes its shape into absolute
       ``x``/``y``/``points``; moving or resizing a shape leaves the arrow
       behind while every id-level binding still looks perfect.
    2. **Elements-array order.** ``set_index`` carries only half of what
       ``repair_manifest_zorder`` does — the array itself must be re-sorted to
       match, or the manifest asserts two contradictory paint orders.
    """
    if not isinstance(state.manifest, dict):
        return

    if (state.canvas_library == "excalidraw" and state.structure
            and state.structure.get("chart_type") == "sequence_diagram"):
        repaired = rebuild_excalidraw_arrows(state.manifest, state.structure)
        before = {item["id"]: item for item in state.manifest.get("elements", [])}
        for item in repaired.get("elements", []):
            if item.get("type") == "arrow" and item != before.get(item["id"]):
                log.rerouted_arrows.append({"arrow_id": item["id"], "reason": "restored sequence chronology"})
        state.manifest = repaired
        geometry_refreshed = True

    # The scene router already accounts for obstacles, shared ports and label
    # placement. Endpoint-only fallback routing would overwrite those routes.
    # Keep it for imported scenes without semantic structure/edge metadata.
    rerouted = [] if geometry_refreshed else reroute_bound_arrows(
        state.manifest,
        canvas_library=state.canvas_library,
        touched_ids=touched_ids,
    )
    if rerouted:
        log.rerouted_arrows.extend(rerouted)
        state.add_log(f"  arrows:        re-routed={len(rerouted)}")
        sample = ", ".join(str(item.get("arrow_id")) for item in rerouted[:5])
        more = "" if len(rerouted) <= 5 else f" (+{len(rerouted) - 5} more)"
        log.notes.append(
            f"re-routed {len(rerouted)} arrow(s) onto their moved endpoints: "
            f"{sample}{more}"
        )

    if reorder_elements_by_index(state.manifest):
        state.add_log("  zorder:        elements array re-sorted to match index")
        log.notes.append(
            "elements array re-sorted so paint order matches the repaired "
            "fractional indices"
        )


def _rerender_iteration_image(
    state: VerifierRefinerState,
    *,
    log: IterationLog,
    iteration: int,
    stage: Optional[str] = None,
) -> None:
    """Re-render the current manifest and point the VLM at the new PNG.

    ``stage`` names an intra-round render (currently ``"det"``, taken after the
    deterministic pass and before the LLM call) and keeps it in its own file.
    Only the end-of-round render, ``stage=None``, is recorded as the log's
    canonical ``rerender_*`` result.

    Iteration PNGs are **analysis renders**: exported at scale 1 (one image
    pixel = one manifest unit) with the post-export smart crop disabled, so
    the VLM measures the same units the manifest summary quotes and the
    framing no longer drifts with pixel-content detection between rounds.
    The product render in ``_node_finalize`` deliberately keeps the default
    magnified + cropped pipeline.
    """
    out_dir = Path(state.output_dir or Path(state.manifest_path).parent)
    if state.skip_rerender_between_iterations:
        if stage is None:
            log.notes.append("re-render skipped (--no-rerender)")
        return

    suffix = "" if stage is None else f"_{stage}"
    iter_image = out_dir / f"refined_iter_{iteration}{suffix}.png"
    render_result = render_png_result(
        state.manifest,
        str(iter_image),
        canvas_library=state.canvas_library,
        render_scale=ANALYSIS_RENDER_SCALE,
        crop=False,
    )
    if stage is None:
        log.rerender_ok = render_result.ok
    if render_result.ok:
        rendered_path = render_result.output_path or str(iter_image)
        if stage is None:
            log.rerender_path = rendered_path
        state.current_image_path = rendered_path
        state.analysis_manifest_fingerprint = _manifest_fingerprint(state.manifest)
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
    baseline = state.iteration_logs[0].findings_before
    current = summarize_findings(findings_after_iter)
    has_regression = objective_rank(current) > objective_rank(baseline)
    quality_resolved = not any(objective_rank(current)) and not has_regression
    subjective = (state.initial_report or {}).get("subjective") or {}
    visual_work_remains = needs_refinement({"score": subjective.get("overall_score"),
                                          "constraint_violations": subjective.get("constraint_violations", [])})
    if not edits_applied and visual_work_remains:
        quality_resolved = False
    current_fp = _fingerprint_findings(findings_after_iter)
    is_stagnant = (
        state.prev_findings_fingerprint is not None
        and current_fp == state.prev_findings_fingerprint
    )
    state.prev_findings_fingerprint = current_fp

    if is_stagnant:
        state.termination_reason = "stagnant"
        state.converged = quality_resolved
        state.add_log(
            f"  → stagnant (findings unchanged after round {iteration}; "
            f"{remaining_serious} serious finding(s) remain)"
        )
        log.notes.append(
            "stagnation: findings identical to previous round"
        )
    elif not edits_applied:
        if quality_resolved:
            state.converged = True
            state.termination_reason = "no_edits_resolved"
            state.add_log(
                "  → converged (no edits emitted, no serious findings or objective regression)"
            )
        else:
            state.converged = False
            state.termination_reason = "fixed_point_unresolved"
            state.add_log(
                f"  → fixed point reached ({remaining_serious} serious finding(s), "
                f"objective regression={has_regression}, no applicable edits)"
            )
            log.notes.append(
                "stopped at fixed point with unresolved findings or objective regression"
            )
    elif quality_resolved:
        state.converged = True
        state.termination_reason = "resolved"
        state.add_log(
            "  → converged (no serious findings or objective regression remain)"
        )
    elif has_regression:
        state.add_log("  → continuing to repair objective regression from the initial scene")


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

    for skipped in _objective_skip_categories(state):
        if skipped == "layout_audit":
            note = LAYOUT_AUDIT_SKIP_NOTE
        else:
            note = f"{skipped} — skipped by the refiner; this check did NOT run"
        if note not in state.skipped_objective_checks:
            state.skipped_objective_checks.append(note)
        state.add_log(f"objective check skipped: {note}")

    state.current_image_path = state.image_path
    state.status = "loaded"
    return state


def _prepare_iteration(
    state: VerifierRefinerState,
    *,
    prepare_image: bool,
) -> Optional[PreparedIteration]:
    """Run deterministic work without a model call or a final quality decision."""
    iteration = state.current_iteration + 1
    state.add_log(f"--- iteration {iteration}/{state.max_iterations} ---")

    # ── Phase 1: Verify ──────────────────────────────────────────────
    findings_before = _run_objective_checks(state)
    state.latest_findings = findings_before
    # Rollback point. Every op mutates ``state.manifest`` in place and a batch
    # is not transactional, so without a snapshot a round that half-applies a
    # bad plan leaves the damage in the artifact that eventually ships.
    snapshot = deepcopy(state.manifest) if isinstance(state.manifest, dict) else None

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
        return None

    _apply_edit_batch(
        state,
        det_edits,
        log=log,
        target_attr="deterministic_edits",
        log_prefix="  deterministic:",
    )

    image_note = None
    # Serious defects commonly also produce a low critic score. Prepare their
    # corrected view speculatively so a necessary model call does not wait for
    # another render after the critic. Clean/minor-only drafts stay lazy.
    prepare_visual = (_major_or_critical_count(findings_before) > 0
                      or any(objective_rank(summarize_findings(_run_objective_checks(state)))))
    if prepare_image and prepare_visual:
        image_note = _refresh_image_for_llm(state, log=log, iteration=iteration)
        if state.status == "failed":
            state.iteration_logs.append(log)
            state.current_iteration = iteration
            return None
    return PreparedIteration(
        iteration=iteration, findings_before=findings_before,
        snapshot=snapshot, log=log, image_note=image_note,
    )


def _run_one_iteration(
    state: VerifierRefinerState,
    *,
    llm_agent: Optional[RefinerLLMAgent],
) -> VerifierRefinerState:
    prepared = state.prepared_iteration
    state.prepared_iteration = None
    if prepared is None:
        prepared = _prepare_iteration(state, prepare_image=llm_agent is not None)
    if prepared is None:
        return state
    iteration = prepared.iteration
    findings_before = prepared.findings_before
    score_before = _findings_score(findings_before)
    snapshot = prepared.snapshot
    log = prepared.log
    det_outcomes = log.deterministic_edits

    # ── Phase 3: Fix — LLM ──────────────────────────────────────────
    llm_outcomes: List[EditApplyOutcome] = []
    subjective = (state.initial_report or {}).get("subjective") or {}
    remaining = summarize_findings(_run_objective_checks(state))
    model_needed = (not state.initial_report or needs_refinement({
        "findings": remaining, "score": subjective.get("overall_score"),
        "constraint_violations": subjective.get("constraint_violations", []),
    }))
    if llm_agent is not None and model_needed:
        if not prepared.image_note:
            prepared.image_note = _refresh_image_for_llm(state, log=log, iteration=iteration)
            if state.status == "failed":
                state.iteration_logs.append(log)
                state.current_iteration = iteration
                return state
        proposed_edits = _propose_llm_edits(
            state,
            llm_agent=llm_agent,
            log=log,
            iteration=iteration,
            image_note=prepared.image_note,
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

    if not model_needed:
        log.notes.append("LLM skipped: deterministic fixes resolved the requested quality work")

    # ── Phase 4: Verify (post-fix) ───────────────────────────────────
    findings_after_iter = _run_objective_checks(state)
    edits_applied = _any_applied(det_outcomes) or _any_applied(llm_outcomes) or bool(log.rerouted_arrows)

    # ── Phase 4b: Roll back a round that made things worse ───────────
    score_after = _findings_score(findings_after_iter)
    if snapshot is not None and objective_rank(summarize_findings(findings_after_iter)) > objective_rank(summarize_findings(findings_before)):
        state.manifest = snapshot
        log.rolled_back = True
        message = (
            f"round {iteration} rolled back: objective severity regressed; diagnostic score "
            f"{score_before:.0f} → {score_after:.0f} "
            f"(discarded: {summarize_findings(findings_after_iter)})"
        )
        log.notes.append(message)
        state.add_log(f"  → {message}")
        findings_after_iter = findings_before
        score_after = score_before
        # Nothing survived, so the round made no progress. Reporting otherwise
        # would let the loop keep spending iterations re-deriving the same
        # regression from the same input.
        edits_applied = False

    log.findings_after = summarize_findings(findings_after_iter)
    state.latest_findings = findings_after_iter
    state.best_findings_score = (
        score_after
        if state.best_findings_score is None
        else min(state.best_findings_score, score_after)
    )

    # Decide whether another analysis image will actually be consumed. A
    # converged round proceeds directly to the required product render.
    _mark_convergence(
        state, log=log, findings_after_iter=findings_after_iter,
        edits_applied=edits_applied, iteration=iteration,
    )
    if not state.converged:
        _rerender_iteration_image(state, log=log, iteration=iteration)
    elif state.skip_rerender_between_iterations:
        log.notes.append("re-render skipped (--no-rerender)")
    else:
        log.notes.append("terminal analysis render omitted; final product render follows")

    return state


def _refresh_image_for_llm(
    state: VerifierRefinerState,
    *,
    log: IterationLog,
    iteration: int,
) -> str:
    """Re-render between the deterministic pass and the LLM call.

    Costs one extra headless render per iteration. The alternative — telling
    the model in prose that the picture predates the listed edits — is cheaper
    but leaves it reasoning about a diagram that no longer exists, which is
    exactly the failure this exists to prevent. ``--no-rerender`` still buys
    the cheap path, and then the prose note is all the model gets.
    """
    if state.skip_rerender_between_iterations:
        return (
            "this PNG predates this iteration's deterministic edits (re-render "
            "disabled). It may also be the magnified, cropped product export "
            "rather than a 1:1 analysis render, so treat it as qualitative "
            "only: do not read pixel distances from it, treat the edits listed "
            "below as already applied, and trust the manifest summary over the "
            "picture where they disagree."
        )
    if (state.analysis_manifest_fingerprint == _manifest_fingerprint(state.manifest)
            and state.current_image_path and Path(state.current_image_path).is_file()):
        log.notes.append("reused unchanged 1:1 analysis image")
    else:
        _rerender_iteration_image(state, log=log, iteration=iteration, stage="det")
    if state.status == "failed":
        return ""
    return (
        "rendered AFTER this iteration's deterministic edits as a 1:1 "
        "analysis render (one image pixel = one manifest unit, uncropped), "
        "so it matches the manifest summary below."
    )


def _node_finalize(
    state: VerifierRefinerState, *, vlm_model_name: str = "unknown"
) -> VerifierRefinerState:
    out_dir = Path(state.output_dir or Path(state.manifest_path).parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed_before_finalize = state.status == "failed"

    if failed_before_finalize:
        state.add_log("skipping refined manifest/render because refiner failed before finalize")
    else:
        # ``state.manifest`` is already the historical best: every round that
        # scored worse than the manifest it started from was rolled back in
        # _run_one_iteration, so each round boundary holds the best result
        # seen so far rather than the last one attempted.
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
                # Product render: renderer-default scale + smart crop. The
                # analysis mode (scale 1, uncropped) is for VLM iteration
                # input only and must not leak into shipped artifacts.
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
                # Non-converged candidate: reuse the last re-rendered image.
                # That PNG is an analysis render (scale 1, uncropped); this is
                # acceptable because the candidate is a debug-only artifact —
                # the orchestrator keeps the original product render as the
                # final output whenever the refiner does not converge.
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

        graph.add_conditional_edges(
            START,
            lambda s: "run_iteration" if s.prepared_iteration is not None else "load_inputs",
            {"run_iteration": "run_iteration", "load_inputs": "load_inputs"},
        )
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

    def prepare(self, **kwargs: Any) -> VerifierRefinerState:
        """Prepare the first iteration while the initial critic is running.

        No edits leave this private state until run_prepared consumes the
        completed critic report and the normal final quality gate accepts it.
        """
        initial = VerifierRefinerState(**kwargs)
        initial.prepared_input_fingerprint = _input_fingerprint(initial)
        state = _node_load_inputs(initial)
        if state.status != "failed":
            state.prepared_iteration = _prepare_iteration(state, prepare_image=True)
        return state

    def run_prepared(
        self, state: VerifierRefinerState, *, verifier_report_path: str,
    ) -> VerifierRefinerState:
        if state.prepared_input_fingerprint != _input_fingerprint(state):
            raise ValueError("Refiner inputs changed after preparation")
        if state.status == "failed" or state.prepared_iteration is None:
            raise ValueError("Refiner preparation did not produce a usable iteration")
        state.verifier_report_path = verifier_report_path
        state.initial_report = _load_json(verifier_report_path)
        if state.initial_report is None:
            raise ValueError("Completed verifier report is unavailable")
        result = self.graph.invoke(state)
        return result if isinstance(result, VerifierRefinerState) else VerifierRefinerState.model_validate(result)

    def run(
        self,
        manifest_path: str,
        image_path: str,
        *,
        verifier_report_path: Optional[str] = None,
        design_constraints: str = "",
        structure_path: Optional[str] = None,
        layout_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        canvas_library: str = "excalidraw",
        max_iterations: int = 3,
        skip_rerender_between_iterations: bool = False,
        skip_checks: Optional[List[str]] = None,
        emit_markdown: bool = False,
    ) -> VerifierRefinerState:
        canvas_library = _normalize_refiner_canvas_library(canvas_library)
        initial = VerifierRefinerState(
            manifest_path=manifest_path,
            image_path=image_path,
            verifier_report_path=verifier_report_path,
            design_constraints=design_constraints,
            structure_path=structure_path,
            layout_path=layout_path,
            output_dir=output_dir,
            canvas_library=canvas_library,
            max_iterations=max_iterations,
            skip_rerender_between_iterations=skip_rerender_between_iterations,
            skip_checks=skip_checks or [],
            emit_markdown=emit_markdown,
        )
        result = self.graph.invoke(initial)
        if isinstance(result, VerifierRefinerState):
            return result
        if isinstance(result, dict):
            return VerifierRefinerState.model_validate(result)
        return initial


__all__ = ["IterativeRefinerWorkflow"]
