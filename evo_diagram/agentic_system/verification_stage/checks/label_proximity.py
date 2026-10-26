"""Check that independent relationship labels remain near their connectors."""

from __future__ import annotations

from typing import Any

from evo_diagram.canvas_environment import disjoint_segment_box_distance

from .collision_detection import _arrow_segments, _bbox, _segment_intersects_rect_interior
from .finding import Finding, Severity


def _segment_box_distance(start, end, box) -> float:
    if _segment_intersects_rect_interior(start, end, box):
        return 0.0
    return disjoint_segment_box_distance(start, end, box)


def check_edge_label_proximity(manifest: dict[str, Any]) -> list[Finding]:
    """Report detached predicates too far from the edge they describe."""
    elements = [element for element in manifest.get("elements", [])
                if isinstance(element, dict) and not element.get("isDeleted")
                and float(element.get("opacity", 100)) > 0]
    arrows = {element["id"]: element for element in elements if element.get("type") == "arrow"}
    semantic_arrows = {(arrow.get("meta") or {}).get("semantic_edge_id"): arrow
                       for arrow in arrows.values()}
    findings = []
    for label in elements:
        # Native bound text is positioned by the renderer, not its saved x/y.
        if label.get("type") != "text" or label.get("containerId"):
            continue
        metadata = label.get("meta") or {}
        edge_id = metadata.get("semantic_edge_id")
        arrow = arrows.get(metadata.get("semantic_arrow_id"))
        if arrow is None and edge_id:
            arrow = semantic_arrows.get(edge_id)
        box = _bbox(label)
        if arrow is None or box is None:
            continue
        segments = _arrow_segments(arrow)
        if not segments:
            continue
        distance = min(_segment_box_distance(start, end, box) for start, end in segments)
        font_size = float(label.get("fontSize", 16))
        limit = max(24.0, 1.5 * font_size)
        major_limit = max(48.0, 3.0 * font_size)
        if distance > limit:
            findings.append(Finding(
                category="binding/edge_label_distance",
                severity=Severity.MAJOR if distance > major_limit else Severity.MINOR,
                element_id=label.get("id"),
                message=f"Relationship label is {distance:.1f}px from its connector; keep it within {limit:.0f}px of that edge.",
                location={"arrow_id": arrow["id"], "distance": round(distance, 1), "limit": limit},
            ))
    return findings
