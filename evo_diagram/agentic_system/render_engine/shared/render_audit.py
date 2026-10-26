# -*- coding: utf-8 -*-
"""Render-time audits for silent fidelity losses.

The 2026-04 PNG-quality incident traced back to three silent-drop bugs between
Layout JSON and the rendered scene: group titles with empty text, edges whose
keys did not match the classifier, and arrow_adder reading the wrong endpoint
keys. Those bugs are now patched, but the class of failure (the LLM emitted
correct semantics, the deterministic layer silently dropped them) will recur
as the prompt / converter evolve.

This module catches that failure mode at render time. It inspects
``layout_instantiation`` and the post-arrow Excalidraw/TLDraw manifest, logs
any suspicious gap under the ``[RenderAudit]`` prefix, and never raises — so
enabling it cannot break a rendering run that would otherwise succeed.

All checks are intentionally loose (heuristic) — their job is to surface
regressions, not to reject valid outputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.common.semantic_ids import (
    TITLE_SUFFIX,
    group_frame_render_id,
    id_map_from_manifest,
)

logger = logging.getLogger(__name__)

_AUDIT_PREFIX = "[RenderAudit]"


@dataclass
class AuditIssue:
    """One structured audit finding, with element_id for targeted fixing."""
    category: str        # "zorder" | "contrast" | "empty_text" | "arrow_coverage" | ...
    message: str
    element_id: Optional[str] = None
    severity: str = "MAJOR"   # MAJOR | MINOR


@dataclass
class AuditReport:
    """Combined output: human-readable warnings + machine-parseable issues."""
    warnings: List[str] = field(default_factory=list)
    issues: List[AuditIssue] = field(default_factory=list)


def _is_title_key(element_id: Any) -> bool:
    return isinstance(element_id, str) and element_id.endswith(TITLE_SUFFIX)


def _text_empty(element_data: Any) -> bool:
    """Return True if the entry is a text element without renderable text."""
    if not isinstance(element_data, dict):
        return True
    label = element_data.get("label")
    if isinstance(label, dict) and label.get("text"):
        return False
    props = element_data.get("props")
    if isinstance(props, dict) and props.get("text"):
        return False
    return not element_data.get("text")


def _looks_like_edge(element_data: Any) -> bool:
    """Heuristic: dict with start+end subdicts is structurally an edge."""
    if not isinstance(element_data, dict):
        return False
    start = element_data.get("start")
    end = element_data.get("end")
    return isinstance(start, dict) and isinstance(end, dict)


def _edge_coverage(
    *,
    expected_edge_count: int,
    expected_edge_ids: set[str],
    rendered_arrow_count: int,
    rendered_semantic_edge_ids: set[str],
) -> Tuple[float, List[str]]:
    """Return coverage plus any missing stable Structure edge ids.

    Stable edge ids are semantic contracts; a count-only fallback must not hide
    a named edge that was dropped or rendered under the wrong id. Anonymous
    edges still use count coverage because they cannot be matched directly.
    """
    if expected_edge_count <= 0:
        return 1.0, []

    missing_edge_ids = sorted(expected_edge_ids - rendered_semantic_edge_ids)

    if expected_edge_ids:
        matched_named_count = len(expected_edge_ids & rendered_semantic_edge_ids)
        anonymous_expected_count = max(0, expected_edge_count - len(expected_edge_ids))
        anonymous_rendered_count = max(0, rendered_arrow_count - len(rendered_semantic_edge_ids))
        matched_anonymous_count = min(anonymous_expected_count, anonymous_rendered_count)
        return (
            (matched_named_count + matched_anonymous_count) / expected_edge_count,
            missing_edge_ids,
        )

    return rendered_arrow_count / expected_edge_count, []


def audit_layout_instantiation(
    layout_instantiation: Optional[Dict[str, Any]],
    structure_instantiation: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Inspect layout output for fidelity gaps. Log + return warnings.

    Checks:
        1. ``*:title`` entries with no renderable text. Caused Bug A before the
           2026-04 fix — lane titles came out blank.
        2. Entries that look like edges (dict with ``start`` + ``end``) but the
           id is not in the structure's edge id list and doesn't start with
           ``edge:``. A near miss here means the converter's edge classifier
           may quietly skip the entry.

    Duplicate ids are NOT checked here on purpose: a layout instantiation is
    a dict, so its keys are unique by construction — and duplicate keys in
    the source JSON file are already collapsed (last-one-wins) by the JSON
    parser before this code ever sees them. The real duplicate risk is the
    converter's id_map collapsing two semantic ids onto one render id, which
    surfaces as duplicate element ids in the post-conversion manifest; that
    is caught by ``audit_excalidraw_manifest`` (warn-only, targeted) and hard
    rejected by ``validate_excalidraw_manifest`` (``Duplicate element ID``).
    """
    warnings: List[str] = []
    if not isinstance(layout_instantiation, dict):
        return warnings

    structure = unwrap_structure_instantiation(structure_instantiation)
    structure_edge_ids: set = {
        edge.get("id")
        for edge in structure.get("edges", []) or []
        if isinstance(edge, dict) and edge.get("id")
    }

    for element_id, element_data in layout_instantiation.items():
        if element_id == "specification":
            continue

        # Check 1: empty title text
        if _is_title_key(element_id) and _text_empty(element_data):
            msg = (
                f"{_AUDIT_PREFIX} empty title text for id={element_id!r}; "
                "check that styling emits label.text for every group."
            )
            warnings.append(msg)
            logger.warning(msg)

        # Check 2: edge-like payload missed by the classifier
        if _looks_like_edge(element_data):
            is_classified = (
                isinstance(element_id, str) and element_id.startswith("edge:")
            ) or element_id in structure_edge_ids
            if not is_classified:
                msg = (
                    f"{_AUDIT_PREFIX} entry id={element_id!r} has start+end dicts "
                    "but is not recognised as an edge (not prefixed with 'edge:' "
                    "and not present in structure.edges[].id)."
                )
                warnings.append(msg)
                logger.warning(msg)

    return warnings


def audit_excalidraw_manifest(
    manifest: Optional[Dict[str, Any]],
    structure_instantiation: Optional[Dict[str, Any]] = None,
    *,
    arrow_coverage_threshold: float = 0.7,
) -> AuditReport:
    """Inspect the post-arrow-adder Excalidraw manifest for render-time gaps.

    Returns an ``AuditReport`` with:
    - ``warnings``: human-readable strings for logs and reports
    - ``issues``: per-element ``AuditIssue`` list (for targeted fixing)

    Checks:
        1. Standalone text elements (containerId is None) with empty text.
        2. Arrow count vs structure edge count.
        3. Group frame z-order vs children.
        4. Bound text contrast (WCAG AA).
        5. Duplicate element ids in the elements list — the converter's
           id_map can collapse two semantic ids onto one render id, and
           Excalidraw then silently keeps only one element.
    """
    report = AuditReport()
    if not isinstance(manifest, dict):
        return report

    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return report

    structure = unwrap_structure_instantiation(structure_instantiation)
    structure_edges = [
        edge
        for edge in structure.get("edges", []) or []
        if isinstance(edge, dict)
    ]
    expected_edge_ids = {
        str(edge["id"])
        for edge in structure_edges
        if isinstance(edge.get("id"), str) and edge["id"].strip()
    }
    expected_edge_count = len(structure_edges)

    empty_text_ids: List[str] = []
    rendered_arrow_count = 0
    rendered_semantic_edge_ids: set[str] = set()
    id_counts: Dict[str, int] = {}

    for elem in elements:
        if not isinstance(elem, dict):
            continue
        elem_id = elem.get("id")
        if isinstance(elem_id, str) and elem_id:
            id_counts[elem_id] = id_counts.get(elem_id, 0) + 1
        etype = elem.get("type")
        if etype == "arrow":
            rendered_arrow_count += 1
            meta = elem.get("meta")
            if isinstance(meta, dict) and isinstance(meta.get("semantic_edge_id"), str):
                rendered_semantic_edge_ids.add(meta["semantic_edge_id"])
            continue
        if etype == "text":
            if elem.get("containerId"):
                continue
            if not (elem.get("text") or elem.get("originalText")):
                empty_text_ids.append(str(elem.get("id", "?")))

    # Duplicate ids: warn-only here (with a targeted per-element issue), but
    # a real defect — Excalidraw keeps one element per id, so a collapse
    # silently deletes a shape. The schema validator hard-fails on this
    # later in the render workflow; this check surfaces it earlier and on
    # audit-only paths (verifier checks, regression renders) that never run
    # the validator.
    duplicate_ids = sorted(eid for eid, count in id_counts.items() if count > 1)
    if duplicate_ids:
        sample = ", ".join(duplicate_ids[:5])
        msg = (
            f"{_AUDIT_PREFIX} {len(duplicate_ids)} element id(s) appear more "
            f"than once in the manifest (sample: {sample}). Excalidraw keeps "
            "only one element per id; the converter's id_map likely collapsed "
            "two semantic ids onto one render id."
        )
        report.warnings.append(msg)
        logger.warning(msg)
        for eid in duplicate_ids:
            report.issues.append(AuditIssue(
                category="duplicate_id",
                message=f"element id {eid!r} appears {id_counts[eid]} times",
                element_id=eid,
            ))

    if empty_text_ids:
        sample = ", ".join(empty_text_ids[:5])
        msg = (
            f"{_AUDIT_PREFIX} {len(empty_text_ids)} standalone text element(s) "
            f"have empty text (sample: {sample}). Likely group titles without "
            "label.text — check styling output contract."
        )
        report.warnings.append(msg)
        logger.warning(msg)
        for eid in empty_text_ids:
            report.issues.append(AuditIssue(
                category="empty_text",
                message=f"standalone text {eid} has empty text",
                element_id=eid,
            ))

    if expected_edge_count > 0:
        coverage, missing_edge_ids = _edge_coverage(
            expected_edge_count=expected_edge_count,
            expected_edge_ids=expected_edge_ids,
            rendered_arrow_count=rendered_arrow_count,
            rendered_semantic_edge_ids=rendered_semantic_edge_ids,
        )
        if missing_edge_ids or coverage < arrow_coverage_threshold:
            missing_suffix = ""
            if missing_edge_ids:
                missing_suffix = f" Missing Structure edge ids: {', '.join(missing_edge_ids[:5])}."
            msg = (
                f"{_AUDIT_PREFIX} rendered arrows={rendered_arrow_count} / "
                f"structure.edges={expected_edge_count} (coverage "
                f"{coverage:.0%}; threshold {arrow_coverage_threshold:.0%}). arrow_adder "
                f"likely failed to resolve some edge endpoints.{missing_suffix}"
            )
            report.warnings.append(msg)
            logger.warning(msg)
            report.issues.append(AuditIssue(
                category="arrow_coverage",
                message=msg,
            ))

    # Z-order and contrast — both return (warnings, issues)
    z_warnings, z_issues = _audit_group_frame_zorder(manifest, structure)
    report.warnings.extend(z_warnings)
    report.issues.extend(z_issues)

    c_warnings, c_issues = _audit_text_contrast(manifest)
    report.warnings.extend(c_warnings)
    report.issues.extend(c_issues)

    return report


def audit_tldraw_manifest(
    manifest: Optional[Dict[str, Any]],
    structure_instantiation: Optional[Dict[str, Any]] = None,
    *,
    arrow_coverage_threshold: float = 0.7,
) -> AuditReport:
    """Inspect the post-arrow-adder TLDraw snapshot for render-time gaps.

    This mirrors the Excalidraw audit at the semantic-fidelity layer. The
    TLDraw schema validator can prove the snapshot is structurally loadable,
    but it cannot tell whether Structure edges or title text were silently
    dropped by conversion / arrow generation.
    """
    report = AuditReport()
    if not isinstance(manifest, dict):
        return report

    document = manifest.get("document")
    store = document.get("store") if isinstance(document, dict) else None
    if not isinstance(store, dict):
        return report

    structure = unwrap_structure_instantiation(structure_instantiation)
    structure_edges = [
        edge
        for edge in structure.get("edges", []) or []
        if isinstance(edge, dict)
    ]
    expected_edge_ids = {
        str(edge["id"])
        for edge in structure_edges
        if isinstance(edge.get("id"), str) and edge["id"].strip()
    }
    expected_edge_count = len(structure_edges)

    rendered_arrow_count = 0
    rendered_semantic_edge_ids: set[str] = set()
    empty_title_ids: List[str] = []
    empty_text_ids: List[str] = []

    for key, entry in store.items():
        if not isinstance(entry, dict) or entry.get("typeName") != "shape":
            continue

        shape_id = str(entry.get("id") or key)
        shape_type = entry.get("type")
        props = entry.get("props") if isinstance(entry.get("props"), dict) else {}

        if shape_type == "arrow":
            rendered_arrow_count += 1
            meta = entry.get("meta")
            if isinstance(meta, dict) and isinstance(meta.get("semantic_edge_id"), str):
                rendered_semantic_edge_ids.add(meta["semantic_edge_id"])
            continue

        text = props.get("text")
        has_text = isinstance(text, str) and bool(text.strip())
        is_title = shape_id.endswith(TITLE_SUFFIX) or (isinstance(key, str) and key.endswith(TITLE_SUFFIX))
        if is_title and not has_text:
            empty_title_ids.append(shape_id)
        elif shape_type == "text" and not has_text:
            empty_text_ids.append(shape_id)

    if empty_title_ids:
        sample = ", ".join(empty_title_ids[:5])
        msg = (
            f"{_AUDIT_PREFIX} {len(empty_title_ids)} TLDraw title shape(s) "
            f"have empty props.text (sample: {sample}). Likely group titles "
            "lost their label during Styling/Layout conversion."
        )
        report.warnings.append(msg)
        logger.warning(msg)
        for eid in empty_title_ids:
            report.issues.append(AuditIssue(
                category="empty_text",
                message=f"TLDraw title shape {eid} has empty props.text",
                element_id=eid,
            ))

    if empty_text_ids:
        sample = ", ".join(empty_text_ids[:5])
        msg = (
            f"{_AUDIT_PREFIX} {len(empty_text_ids)} TLDraw text shape(s) "
            f"have empty props.text (sample: {sample})."
        )
        report.warnings.append(msg)
        logger.warning(msg)
        for eid in empty_text_ids:
            report.issues.append(AuditIssue(
                category="empty_text",
                message=f"TLDraw text shape {eid} has empty props.text",
                element_id=eid,
            ))

    if expected_edge_count > 0:
        coverage, missing_edge_ids = _edge_coverage(
            expected_edge_count=expected_edge_count,
            expected_edge_ids=expected_edge_ids,
            rendered_arrow_count=rendered_arrow_count,
            rendered_semantic_edge_ids=rendered_semantic_edge_ids,
        )
        if missing_edge_ids or coverage < arrow_coverage_threshold:
            missing_suffix = ""
            if missing_edge_ids:
                missing_suffix = f" Missing Structure edge ids: {', '.join(missing_edge_ids[:5])}."
            msg = (
                f"{_AUDIT_PREFIX} TLDraw rendered arrows={rendered_arrow_count} / "
                f"structure.edges={expected_edge_count} (coverage "
                f"{coverage:.0%}; threshold {arrow_coverage_threshold:.0%}). arrow_adder "
                f"likely failed to resolve some edge endpoints.{missing_suffix}"
            )
            report.warnings.append(msg)
            logger.warning(msg)
            report.issues.append(AuditIssue(
                category="arrow_coverage",
                message=msg,
            ))

    return report


# ---------------------------------------------------------------------------
# Text contrast audit (WCAG AA, warn-only).
#
# Catches the dark-on-dark failure observed on 2026-04-25: a node fill of
# ``#003366`` (Corporate Navy Gold's deep navy identity) carrying the
# Excalidraw default bound-text color ``#1e1e1e`` produced ~1.32:1 contrast
# — completely unreadable. The fill_family palette redesign makes that
# specific failure syntactically impossible, but the guard remains as a
# regression net: if a future palette tweak or LLM drift puts dark text on
# dark fill again, it surfaces here in the render log immediately.
# ---------------------------------------------------------------------------

_WCAG_AA_BODY = 4.5


def _hex_to_rgb(hex_str: str) -> Optional[tuple]:
    """Parse '#RRGGBB' (or '#RGB' shorthand) to (r, g, b) ints. None on bad input."""
    if not isinstance(hex_str, str):
        return None
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _relative_luminance(rgb: tuple) -> float:
    """WCAG 2.1 relative luminance formula."""
    def chan(c: int) -> float:
        c_lin = c / 255.0
        return c_lin / 12.92 if c_lin <= 0.03928 else ((c_lin + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> Optional[float]:
    """WCAG contrast ratio between two hex colors. None if either won't parse."""
    rgb_a, rgb_b = _hex_to_rgb(hex_a), _hex_to_rgb(hex_b)
    if rgb_a is None or rgb_b is None:
        return None
    l_a, l_b = _relative_luminance(rgb_a), _relative_luminance(rgb_b)
    lighter, darker = max(l_a, l_b), min(l_a, l_b)
    return (lighter + 0.05) / (darker + 0.05)


def _audit_text_contrast(manifest: Dict[str, Any]) -> tuple[List[str], List[AuditIssue]]:
    """Warn when bound text on a shape fails WCAG AA (4.5:1) body-text contrast.

    Returns (warnings, issues) where issues are per-element for targeted fixing.
    """
    warnings: List[str] = []
    issues: List[AuditIssue] = []
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return warnings, issues

    shapes_by_id: Dict[str, Dict[str, Any]] = {
        e["id"]: e
        for e in elements
        if isinstance(e, dict) and isinstance(e.get("id"), str) and e.get("type") in ("rectangle", "ellipse", "diamond")
    }

    failures: List[tuple] = []  # (text_label, text_color, fill, ratio, text_id)
    for elem in elements:
        if not isinstance(elem, dict) or elem.get("type") != "text":
            continue
        container_id = elem.get("containerId")
        if not container_id or container_id not in shapes_by_id:
            continue
        text_color = elem.get("strokeColor")
        fill = shapes_by_id[container_id].get("backgroundColor")
        if not isinstance(text_color, str) or not isinstance(fill, str) or not fill.startswith("#"):
            continue
        ratio = _contrast_ratio(text_color, fill)
        if ratio is None:
            continue
        if ratio < _WCAG_AA_BODY:
            label = elem.get("text") or elem.get("originalText") or ""
            failures.append((str(label)[:32], text_color, fill, ratio, elem.get("id")))

    if failures:
        failures.sort(key=lambda t: t[3])
        sample_lines = "; ".join(
            f"'{lbl}' text={tc} on fill={f} → {r:.2f}:1"
            for lbl, tc, f, r, _ in failures[:5]
        )
        msg = (
            f"{_AUDIT_PREFIX} {len(failures)} bound-text element(s) fail "
            f"WCAG AA body-text contrast (<{_WCAG_AA_BODY}:1). "
            f"Worst pairs: {sample_lines}. Likely cause: node backgroundColor "
            "is darker than expected — check that styling output uses "
            "fill_family.fill values (always light) for backgroundColor."
        )
        warnings.append(msg)
        logger.warning(msg)

        for lbl, tc, f, r, text_id in failures:
            issues.append(AuditIssue(
                category="contrast",
                message=f"text='{lbl}' color={tc} on fill={f} → {r:.2f}:1",
                element_id=text_id,
            ))

    return warnings, issues


def _audit_group_frame_zorder(
    manifest: Dict[str, Any],
    structure: Dict[str, Any],
) -> tuple[List[str], List[AuditIssue]]:
    """Warn when a group frame's fractional index is higher than any of its
    semantic children — the frame would paint over the children.

    Returns (warnings, issues) where issues include the specific frame element_id.
    """
    warnings: List[str] = []
    issues: List[AuditIssue] = []
    id_map = id_map_from_manifest(manifest)
    if not id_map:
        return warnings, issues

    groups = structure.get("groups") or []
    if not isinstance(groups, list) or not groups:
        return warnings, issues

    # Build excalidraw_id -> fractional index lookup.
    index_by_eid: Dict[str, str] = {}
    for elem in manifest.get("elements", []):
        if isinstance(elem, dict) and elem.get("id") and elem.get("index"):
            index_by_eid[elem["id"]] = elem["index"]

    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        children = group.get("children") or group.get("members") or []
        if not gid or not isinstance(children, list):
            continue

        frame_eid = group_frame_render_id(id_map, gid)
        frame_idx = index_by_eid.get(frame_eid) if frame_eid else None
        if not frame_idx:
            continue

        for child_id in children:
            child_eid = id_map.get(child_id) if isinstance(child_id, str) else None
            child_idx = index_by_eid.get(child_eid) if child_eid else None
            if not child_idx:
                continue
            if frame_idx > child_idx:
                msg = (
                    f"{_AUDIT_PREFIX} group frame id={gid!r} has fractional "
                    f"index={frame_idx!r} greater than child id={child_id!r} "
                    f"index={child_idx!r}; the opaque frame will occlude the "
                    "child in the rendered PNG. Check the converter's layer sort."
                )
                warnings.append(msg)
                logger.warning(msg)
                issues.append(AuditIssue(
                    category="zorder",
                    message=msg,
                    element_id=frame_eid,
                ))
                break  # one warning per group is enough

    return warnings, issues


__all__ = [
    "AuditIssue",
    "AuditReport",
    "audit_layout_instantiation",
    "audit_excalidraw_manifest",
    "audit_tldraw_manifest",
]
