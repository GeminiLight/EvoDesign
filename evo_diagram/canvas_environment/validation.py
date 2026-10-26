"""Validation, normalization, and audit facade for canvas manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from evo_diagram.canvas_runtime import normalize_canvas_library

from . import _render_engine_adapter


@dataclass
class CanvasAuditIssue:
    """Public, backend-neutral render audit finding."""

    category: str
    message: str
    element_id: Optional[str] = None
    severity: str = "MAJOR"


@dataclass
class CanvasAuditReport:
    """Public, backend-neutral audit report for canvas manifests."""

    warnings: List[str] = field(default_factory=list)
    issues: List[CanvasAuditIssue] = field(default_factory=list)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _coerce_audit_issue(issue: Any) -> CanvasAuditIssue:
    if isinstance(issue, CanvasAuditIssue):
        return issue

    if isinstance(issue, dict):
        category = issue.get("category")
        message = issue.get("message")
        element_id = issue.get("element_id")
        severity = issue.get("severity")
    else:
        category = getattr(issue, "category", None)
        message = getattr(issue, "message", None)
        element_id = getattr(issue, "element_id", None)
        severity = getattr(issue, "severity", None)

    return CanvasAuditIssue(
        category=str(category or "unknown"),
        message=str(message or ""),
        element_id=element_id if isinstance(element_id, str) else None,
        severity=str(severity or "MAJOR"),
    )


def _audit_report_field(report: Any, field: str, default: Any) -> Any:
    if isinstance(report, dict):
        return report.get(field, default)
    return getattr(report, field, default)


def _coerce_audit_report(report: Any) -> CanvasAuditReport:
    if isinstance(report, CanvasAuditReport):
        return report

    warnings = [
        str(warning)
        for warning in _as_list(_audit_report_field(report, "warnings", []))
    ]
    issues = [
        _coerce_audit_issue(issue)
        for issue in _as_list(_audit_report_field(report, "issues", []))
    ]
    return CanvasAuditReport(warnings=warnings, issues=issues)


def normalize_manifest(
    manifest: Dict[str, Any],
    canvas_library: str = "excalidraw",
) -> Dict[str, Any]:
    """Normalize a canvas manifest in place and return it.

    Excalidraw manifests are normalized through the renderer's z-order/title
    pass. TLDraw normalization is currently a passthrough because the active
    normalizer is Excalidraw-specific.
    """
    canvas_library = normalize_canvas_library(canvas_library)
    if canvas_library == "excalidraw":
        _render_engine_adapter.normalize_excalidraw_manifest(manifest)
        return manifest

    if canvas_library == "tldraw":
        return manifest

    raise NotImplementedError(f"normalize_manifest is not implemented for {canvas_library!r}")


def validate_manifest(
    manifest: Dict[str, Any],
    canvas_library: str = "excalidraw",
) -> Dict[str, Any]:
    """Validate a canvas manifest for the selected backend."""
    canvas_library = normalize_canvas_library(canvas_library)
    if canvas_library == "excalidraw":
        return _render_engine_adapter.validate_excalidraw_manifest(manifest)

    if canvas_library == "tldraw":
        return _render_engine_adapter.validate_tldraw_manifest(manifest)

    raise ValueError(f"Unknown canvas library: {canvas_library}")


def audit_manifest(
    manifest: Dict[str, Any],
    structure_instantiation: Optional[Dict[str, Any]] = None,
    canvas_library: str = "excalidraw",
) -> CanvasAuditReport:
    """Run backend-specific render audit and return a stable facade report."""
    canvas_library = normalize_canvas_library(canvas_library)
    if canvas_library == "excalidraw":
        return _coerce_audit_report(
            _render_engine_adapter.audit_excalidraw_manifest(
                manifest,
                structure_instantiation=structure_instantiation,
            )
        )

    if canvas_library == "tldraw":
        return _coerce_audit_report(
            _render_engine_adapter.audit_tldraw_manifest(
                manifest,
                structure_instantiation=structure_instantiation,
            )
        )

    raise NotImplementedError(f"audit_manifest is not implemented for {canvas_library!r}")


def audit_layout_instantiation(
    layout_instantiation: Dict[str, Any],
    structure_instantiation: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Audit layout-stage output before backend-specific conversion."""
    return _render_engine_adapter.audit_layout_instantiation(
        layout_instantiation,
        structure_instantiation,
    )


def repair_manifest_zorder(
    manifest: Dict[str, Any],
    canvas_library: str = "excalidraw",
) -> Dict[str, Any]:
    """Repair backend-specific manifest z-order through the canvas facade.

    Excalidraw manifests are repaired in place; TLDraw is currently a
    passthrough because its z-order model is handled in the TLDraw converter.
    """
    canvas_library = normalize_canvas_library(canvas_library)
    if canvas_library == "excalidraw":
        return _render_engine_adapter.repair_excalidraw_zorder(manifest)

    if canvas_library == "tldraw":
        return manifest

    raise NotImplementedError(f"repair_manifest_zorder is not implemented for {canvas_library!r}")


def detect_group_frame_ids(
    elements: List[Dict[str, Any]],
    *,
    structural: bool = False,
    id_map: Optional[Mapping[str, Any]] = None,
) -> Set[str]:
    """Detect backend group-frame element ids through the canvas facade."""
    return _render_engine_adapter.detect_group_frame_ids(
        elements,
        structural=structural,
        id_map=id_map,
    )


def validate_png_file(output_file: Path, *, context: str) -> None:
    """Validate a rendered PNG artifact through the canvas facade."""
    _render_engine_adapter.validate_png_file(output_file, context=context)


__all__ = [
    "CanvasAuditIssue",
    "CanvasAuditReport",
    "normalize_manifest",
    "validate_manifest",
    "audit_manifest",
    "audit_layout_instantiation",
    "repair_manifest_zorder",
    "detect_group_frame_ids",
    "validate_png_file",
]
