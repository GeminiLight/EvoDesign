"""Wrap canvas_environment render audit + manifest validation.

Re-exports their string warnings as Finding objects with severity classified
by the source. Both modules are imported read-only and never mutated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from evo_diagram.canvas_environment import (
    audit_layout_instantiation,
    audit_manifest,
    validate_manifest,
)

from .finding import Finding, Severity

# Map audit category → Finding severity.
_SEVERITY_MAP = {
    "zorder": Severity.MAJOR,
    "contrast": Severity.MAJOR,
    "empty_text": Severity.MAJOR,
    "arrow_coverage": Severity.MAJOR,
}


def check_schema(
    manifest: Dict[str, Any],
    canvas_library: str = "excalidraw",
) -> List[Finding]:
    """Run the selected canvas backend's schema validator.

    `errors` from the validator → CRITICAL Findings.
    `warnings` from the validator → MINOR Findings.
    """
    findings: List[Finding] = []
    report = validate_manifest(manifest, canvas_library=canvas_library)

    for err in report.get("errors", []) or []:
        findings.append(
            Finding(
                category="render_validation/schema",
                severity=Severity.CRITICAL,
                message=str(err),
            )
        )
    for warn in report.get("warnings", []) or []:
        findings.append(
            Finding(
                category="render_validation/schema",
                severity=Severity.MINOR,
                message=str(warn),
            )
        )

    return findings


def check_render_audit(
    manifest: Dict[str, Any],
    structure: Optional[Dict[str, Any]] = None,
    canvas_library: str = "excalidraw",
) -> List[Finding]:
    """Run render_audit on the post-arrow canvas manifest.

    Uses per-element ``AuditIssue`` data for zorder and contrast findings,
    so downstream fixers can target specific elements instead of scanning all.
    """
    findings: List[Finding] = []
    report = audit_manifest(
        manifest,
        structure_instantiation=structure,
        canvas_library=canvas_library,
    )

    # Use structured issues (per-element) instead of aggregated warnings.
    for issue in report.issues:
        sev = _SEVERITY_MAP.get(issue.category, Severity.MAJOR)
        findings.append(
            Finding(
                category=f"render_validation/audit/{issue.category}",
                severity=sev,
                message=issue.message,
                element_id=issue.element_id,
            )
        )

    return findings


def check_layout_audit(
    layout_instantiation: Optional[Dict[str, Any]],
    structure: Optional[Dict[str, Any]] = None,
) -> List[Finding]:
    """Run render_audit's layout-stage check (empty title / edge classifier / dup id).

    ``layout_audit`` is layout-dependent. Returning [] when layout input is
    missing makes standalone verifier runs look clean even though a configured
    objective check never actually ran, so missing or malformed layout is a
    blocking finding unless the caller explicitly skips ``layout_audit``.
    """
    findings: List[Finding] = []
    if not isinstance(layout_instantiation, dict):
        kind = (
            "missing"
            if layout_instantiation is None
            else type(layout_instantiation).__name__
        )
        return [
            Finding(
                category="render_validation/layout_audit/missing_layout",
                severity=Severity.CRITICAL,
                message=(
                    "layout_audit requires layout_instantiation as a JSON object; "
                    f"got {kind}. Pass --layout, provide the sibling "
                    "3_layout/layout_instantiation.json, or skip layout_audit "
                    "explicitly when running manifest-only verification."
                ),
            )
        ]
    warnings = audit_layout_instantiation(
        layout_instantiation,
        structure_instantiation=structure,
    )
    for warn in warnings:
        findings.append(
            Finding(
                category="render_validation/layout_audit",
                severity=Severity.MAJOR,
                message=str(warn),
            )
        )
    return findings


__all__ = ["check_schema", "check_render_audit", "check_layout_audit"]
