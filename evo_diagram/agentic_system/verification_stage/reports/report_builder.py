"""Build the verifier_report.json (and optional .md) from VerifierState.

The JSON is the canonical artifact. The Markdown form is for humans
when they want to scan results in a PR / review without piping through
``jq``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..checks.finding import Finding, summarize_findings
from ..state import Critique, DimensionCritique, VerifierState


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _findings_to_dicts(findings: List[Finding]) -> List[Dict[str, Any]]:
    return [f.to_dict() for f in findings]


def _critique_to_dict(critique: Optional[Critique]) -> Optional[Dict[str, Any]]:
    if critique is None:
        return None
    payload = critique.model_dump(exclude_none=True, mode="json")
    # Drop raw_response from the canonical report — it's debug only.
    payload.pop("raw_response", None)
    return payload


def _effective_blocking_errors(state: VerifierState) -> List[str]:
    if state.blocking_errors:
        return list(state.blocking_errors)
    if state.status not in {"failed", "reported_with_errors"}:
        return []
    return [
        err
        for err in state.errors
        if err not in state.nonblocking_errors
    ]


def build_report(state: VerifierState, *, vlm_model_name: Optional[str] = None) -> Dict[str, Any]:
    """Assemble the canonical verifier_report.json payload."""
    summary = summarize_findings(state.objective_findings)
    had_errors = state.has_errors
    blocking_findings = state.blocking_finding_count
    blocking_errors = _effective_blocking_errors(state)

    return {
        "manifest_path": state.manifest_path,
        "image_path": state.image_path,
        "canvas_library": state.canvas_library,
        "structure_path": state.structure_path,
        "layout_path": state.layout_path,
        "objective": {
            "summary": summary,
            "findings": _findings_to_dicts(state.objective_findings),
        },
        "subjective": _critique_to_dict(state.critique),
        "design_constraints": state.design_constraints,
        "metadata": {
            "timestamp": _utc_timestamp(),
            "vlm_model": vlm_model_name,
            "skip_critic": state.skip_critic,
            "canvas_library": state.canvas_library,
            "status": state.status,
            "had_errors": had_errors,
            "had_blocking_errors": state.has_blocking_errors,
            "had_blocking_findings": blocking_findings > 0,
            "quality_passed": state.quality_passed,
            "errors": list(state.errors),
            "blocking_errors": blocking_errors,
            "nonblocking_errors": list(state.nonblocking_errors),
        },
    }


def _render_dimension_md(name: str, dim: Optional[DimensionCritique]) -> List[str]:
    if dim is None:
        return [f"#### {name}", "_(unavailable)_", ""]
    lines = [f"#### {name} — score **{dim.score:.1f}/10**"]
    if dim.strengths:
        lines.append("- **Strengths:**")
        for s in dim.strengths:
            lines.append(f"  - {s}")
    if dim.weaknesses:
        lines.append("- **Weaknesses:**")
        for s in dim.weaknesses:
            lines.append(f"  - {s}")
    if dim.suggestions:
        lines.append("- **Suggestions:**")
        for s in dim.suggestions:
            lines.append(f"  - {s}")
    lines.append("")
    return lines


def build_markdown_report(report: Dict[str, Any]) -> str:
    """Render the JSON report as Markdown for human review."""
    obj = report.get("objective", {}) or {}
    sub = report.get("subjective")
    meta = report.get("metadata", {}) or {}

    lines: List[str] = []
    lines.append("# Verifier Report")
    lines.append("")
    lines.append(f"- Manifest: `{report.get('manifest_path')}`")
    lines.append(f"- Image: `{report.get('image_path')}`")
    if report.get("canvas_library"):
        lines.append(f"- Canvas: `{report.get('canvas_library')}`")
    if report.get("structure_path"):
        lines.append(f"- Structure: `{report.get('structure_path')}`")
    if report.get("layout_path"):
        lines.append(f"- Layout: `{report.get('layout_path')}`")
    if meta.get("timestamp"):
        lines.append(f"- Timestamp: {meta['timestamp']}")
    if meta.get("vlm_model"):
        lines.append(f"- VLM model: `{meta['vlm_model']}`")
    lines.append("")

    # Objective
    summary = obj.get("summary", {}) or {}
    lines.append("## Objective Findings")
    lines.append("")
    counts_line = ", ".join(
        f"{k}={summary.get(k, 0)}" for k in ("critical", "major", "minor", "info", "total")
    )
    lines.append(f"Counts: {counts_line}")
    lines.append("")

    findings = obj.get("findings", []) or []
    if findings:
        lines.append("| Severity | Category | Element | Message |")
        lines.append("|---|---|---|---|")
        for f in findings:
            sev = f.get("severity", "?")
            cat = f.get("category", "?")
            eid = f.get("element_id", "") or ""
            msg = (f.get("message", "") or "").replace("|", "\\|")
            lines.append(f"| {sev} | {cat} | `{eid}` | {msg} |")
        lines.append("")
    else:
        lines.append("_No objective findings._")
        lines.append("")

    # Subjective
    if sub is None:
        lines.append("## Subjective Critique")
        lines.append("")
        lines.append("_Skipped or unavailable._")
        lines.append("")
    else:
        lines.append("## Subjective Critique (VLM)")
        lines.append("")
        overall = sub.get("overall_score")
        if overall is not None:
            lines.append(f"**Overall score: {float(overall):.1f}/10**")
        if sub.get("summary"):
            lines.append(f"\n> {sub['summary']}")
        lines.append("")

        # Use raw dicts here — pydantic models were already dumped.
        for key in ("structure", "styling", "layout"):
            payload = sub.get(key)
            dim_obj = (
                DimensionCritique(**payload) if isinstance(payload, dict) else None
            )
            lines.extend(_render_dimension_md(key.capitalize(), dim_obj))

    blocking_errors = meta.get("blocking_errors") or []
    nonblocking_errors = meta.get("nonblocking_errors") or []
    uncategorized_errors = [
        err
        for err in meta.get("errors", []) or []
        if err not in blocking_errors and err not in nonblocking_errors
    ]

    if blocking_errors or uncategorized_errors:
        lines.append("## Errors")
        lines.append("")
        for err in [*blocking_errors, *uncategorized_errors]:
            lines.append(f"- {err}")
        lines.append("")

    if nonblocking_errors:
        lines.append("## Warnings")
        lines.append("")
        for err in nonblocking_errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


def write_report(
    report: Dict[str, Any],
    output_dir: str,
    *,
    json_name: str = "verifier_report.json",
    markdown_name: Optional[str] = None,
) -> Dict[str, str]:
    """Persist the report. Returns dict of written paths."""
    import json

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / json_name
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    paths = {"json": str(json_path)}
    if markdown_name:
        md_path = out_dir / markdown_name
        md_path.write_text(build_markdown_report(report), encoding="utf-8")
        paths["markdown"] = str(md_path)

    return paths


__all__ = ["build_report", "build_markdown_report", "write_report"]
