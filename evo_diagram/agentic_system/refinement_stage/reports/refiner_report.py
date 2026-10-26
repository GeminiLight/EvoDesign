"""Build refiner_report.json (and optional .md) from VerifierRefinerState.

The JSON layout mirrors verifier_report's pattern:
- ``inputs``: file paths used as inputs
- ``iterations``: per-iteration audit trail
- ``final``: convergence state, paths to refined artifacts
- ``metadata``: timestamp, vlm model, status
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..state import IterationLog, VerifierRefinerState


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _outcome_to_dict(outcome) -> Dict[str, Any]:
    """One edit row. ``edit`` is None for a proposal rejected before validation."""
    row: Dict[str, Any] = {
        "applied": outcome.applied,
        "error": outcome.error,
        "edit": outcome.edit.to_dict() if outcome.edit is not None else None,
    }
    if outcome.raw is not None:
        row["raw"] = outcome.raw
    return row


def _iteration_to_dict(log: IterationLog) -> Dict[str, Any]:
    return {
        "iteration": log.iteration,
        "rolled_back": log.rolled_back,
        "findings_before": log.findings_before,
        "findings_after": log.findings_after,
        "rerender_ok": log.rerender_ok,
        "rerender_path": log.rerender_path,
        "rerender_error": log.rerender_error,
        "deterministic_edits": [
            _outcome_to_dict(o) for o in log.deterministic_edits
        ],
        "llm_edits": [_outcome_to_dict(o) for o in log.llm_edits],
        "rerouted_arrows": log.rerouted_arrows,
        "notes": log.notes,
    }


def build_refiner_report(state: VerifierRefinerState, vlm_model_name: str = "unknown") -> Dict[str, Any]:
    return {
        "inputs": {
            "manifest_path": state.manifest_path,
            "image_path": state.image_path,
            "structure_path": state.structure_path,
            "verifier_report_path": state.verifier_report_path,
        },
        "controls": {
            "max_iterations": state.max_iterations,
            "skip_rerender_between_iterations": state.skip_rerender_between_iterations,
        },
        "iterations": [_iteration_to_dict(log) for log in state.iteration_logs],
        "final": {
            "converged": state.converged,
            "termination_reason": state.termination_reason,
            "iterations_run": state.current_iteration,
            "best_findings_score": state.best_findings_score,
            "refined_manifest_path": state.refined_manifest_path,
            "refined_image_path": state.refined_image_path,
        },
        # Objective checks that deliberately did not run. Without this a clean
        # report is indistinguishable from a fully verified one.
        "skipped_objective_checks": list(state.skipped_objective_checks),
        "metadata": {
            "timestamp": _utc_timestamp(),
            "vlm_model": vlm_model_name,
            "status": state.status,
            "errors": list(state.errors),
            "logs": list(state.logs[-20:]),  # tail to keep report size bounded
        },
    }


def _edit_row_md(outcome) -> str:
    """One markdown table row; ``edit is None`` means schema-rejected."""
    mark = "✓" if outcome.applied else "✗"
    if outcome.edit is None:
        detail = (outcome.error or "rejected").replace("|", "\\|")[:80]
        return f"| {mark} | `(rejected)` | `-` | {detail} |"
    edit = outcome.edit
    rationale = (edit.rationale or (outcome.error or "")).replace("|", "\\|")[:80]
    return f"| {mark} | `{edit.op}` | `{edit.id}` | {rationale} |"


def _render_iteration_md(log: IterationLog) -> List[str]:
    lines: List[str] = [f"### Iteration {log.iteration}"]
    counts_before = ", ".join(f"{k}={v}" for k, v in log.findings_before.items())
    counts_after = ", ".join(f"{k}={v}" for k, v in log.findings_after.items())
    lines.append(f"- Findings before: {counts_before or '(none)'}")
    lines.append(f"- Findings after:  {counts_after or '(none)'}")
    lines.append(
        f"- Re-render: {'ok' if log.rerender_ok else 'skipped/failed'} "
        f"{('(' + log.rerender_path + ')') if log.rerender_path else ''}"
    )
    if log.rerender_error:
        lines.append(f"- Re-render error: {log.rerender_error}")

    if log.deterministic_edits:
        lines.append("")
        lines.append(f"**Deterministic edits ({len(log.deterministic_edits)}):**")
        lines.append("")
        lines.append("| applied | op | id | rationale |")
        lines.append("|---|---|---|---|")
        for o in log.deterministic_edits:
            lines.append(_edit_row_md(o))

    if log.llm_edits:
        lines.append("")
        lines.append(f"**LLM edits ({len(log.llm_edits)}):**")
        lines.append("")
        lines.append("| applied | op | id | rationale |")
        lines.append("|---|---|---|---|")
        for o in log.llm_edits:
            lines.append(_edit_row_md(o))

    if log.rerouted_arrows:
        lines.append("")
        lines.append(
            f"**Arrows re-routed onto moved endpoints ({len(log.rerouted_arrows)}):** "
            + ", ".join(
                f"`{item.get('arrow_id')}`" for item in log.rerouted_arrows[:10]
            )
        )

    if log.notes:
        lines.append("")
        lines.append("**Notes:**")
        for n in log.notes:
            lines.append(f"- {n}")

    lines.append("")
    return lines


def build_markdown_report(report: Dict[str, Any]) -> str:
    inputs = report.get("inputs", {})
    final = report.get("final", {})
    meta = report.get("metadata", {})
    iterations = report.get("iterations", [])

    lines: List[str] = []
    lines.append("# Refiner Report")
    lines.append("")
    lines.append(f"- Manifest: `{inputs.get('manifest_path')}`")
    lines.append(f"- Image: `{inputs.get('image_path')}`")
    if inputs.get("structure_path"):
        lines.append(f"- Structure: `{inputs.get('structure_path')}`")
    if inputs.get("verifier_report_path"):
        lines.append(f"- Verifier report: `{inputs.get('verifier_report_path')}`")
    lines.append(f"- Timestamp: {meta.get('timestamp')}")
    lines.append(f"- VLM model: `{meta.get('vlm_model')}`")
    lines.append(f"- Status: **{meta.get('status')}**")
    lines.append("")

    converged = final.get("converged")
    iters_run = final.get("iterations_run", 0)
    termination_reason = final.get("termination_reason") or "unknown"
    outcome = "CONVERGED" if converged else f"STOPPED: {termination_reason}"
    lines.append(
        f"## Outcome: {outcome} "
        f"({iters_run} iteration{'s' if iters_run != 1 else ''})"
    )
    lines.append("")
    if final.get("refined_manifest_path"):
        lines.append(f"- Refined manifest: `{final['refined_manifest_path']}`")
    if final.get("refined_image_path"):
        lines.append(f"- Refined image: `{final['refined_image_path']}`")
    lines.append("")

    if iterations:
        lines.append("## Iteration audit")
        lines.append("")
        for it_dict in iterations:
            # Convert dict back to IterationLog for the helper.
            log = IterationLog.model_validate(it_dict)
            lines.extend(_render_iteration_md(log))

    if report.get("skipped_objective_checks"):
        lines.append("## Objective checks NOT run")
        lines.append("")
        for skipped in report["skipped_objective_checks"]:
            lines.append(f"- {skipped}")
        lines.append("")

    if meta.get("errors"):
        lines.append("## Errors")
        lines.append("")
        for err in meta["errors"]:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


def write_refiner_report(
    report: Dict[str, Any],
    output_dir: str,
    *,
    json_name: str = "refiner_report.json",
    markdown_name: Optional[str] = None,
) -> Dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / json_name
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    paths = {"json": str(json_path)}
    if markdown_name:
        md_path = out / markdown_name
        md_path.write_text(build_markdown_report(report), encoding="utf-8")
        paths["markdown"] = str(md_path)
    return paths


__all__ = ["build_refiner_report", "build_markdown_report", "write_refiner_report"]
