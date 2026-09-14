"""Normalize architecture scenes to a formal, draw.io-like visual language."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    TITLE_SUFFIX,
    id_map_from_manifest,
    reverse_id_map,
)
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation


_ARCHITECTURE_TYPES = {"architecture", "architecture_diagram"}
_HELVETICA = 2
_DARK_INK = "#24313A"

# A light surface makes the group boundary legible without turning the
# architecture diagram into a collection of heavy dashed boxes.  The tints
# deliberately stay close in value so that node fills remain the recognition
# anchors inside each layer.
_FRAME_TINTS = {
    "presentation": "#F3FAFB",
    "service": "#F5F7FD",
    "business": "#F4FAF3",
    "data": "#F5F6FC",
    "cross": "#FFFBF2",
    "governance": "#FFFBF2",
}


def _semantic_id_for_element(
    reverse_map: Mapping[str, str], element: Mapping[str, Any]
) -> str:
    return str(reverse_map.get(str(element.get("id", "")), ""))


def _frame_tint(semantic_id: str, stroke_color: Any) -> str:
    token = semantic_id.lower()
    if "presentation" in token or "ui" in token:
        return _FRAME_TINTS["presentation"]
    if "service" in token:
        return _FRAME_TINTS["service"]
    if "business" in token:
        return _FRAME_TINTS["business"]
    if "data" in token or "integration" in token:
        return _FRAME_TINTS["data"]
    if "cross" in token or "governance" in token:
        return _FRAME_TINTS["cross"]
    # Keep a stable fallback for older manifests whose frame IDs are opaque.
    color = str(stroke_color or "").upper()
    if color in {"#8A6A2F", "#A66B18"}:
        return _FRAME_TINTS["cross"]
    return "#F8FAFC"


def _is_group_frame(element: Mapping[str, Any], semantic_id: str) -> bool:
    element_id = str(element.get("id", "")).lower()
    return (
        element.get("type") in {"rectangle", "ellipse"}
        and (
            element_id.startswith("frame-")
            or semantic_id.endswith(BACKGROUND_SUFFIX)
        )
    )


def _is_group_title(element: Mapping[str, Any], semantic_id: str) -> bool:
    element_id = str(element.get("id", "")).lower()
    return element.get("type") == "text" and (
        element_id.startswith("title-") or semantic_id.endswith(TITLE_SUFFIX)
    )


def normalize_architecture_style(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Use consistent typography and connector strokes for architecture charts.

    Styling output may omit font settings for bound labels, which makes the
    Excalidraw converter fall back to its playful Virgil font. Architecture
    diagrams are formal technical artifacts, so normalize only this chart
    family after arrows have been created. Other chart types retain their
    authored styling.
    """
    if not isinstance(manifest, dict) or not isinstance(structure_instantiation, dict):
        return manifest
    structure = unwrap_structure_instantiation(structure_instantiation)
    if str(structure.get("chart_type", "")).strip().lower() not in _ARCHITECTURE_TYPES:
        return manifest

    output = deepcopy(manifest)
    reverse_map = reverse_id_map(id_map_from_manifest(output))
    for element in output.get("elements", []):
        if not isinstance(element, dict):
            continue
        semantic_id = _semantic_id_for_element(reverse_map, element)
        if _is_group_frame(element, semantic_id):
            element["backgroundColor"] = _frame_tint(
                semantic_id, element.get("strokeColor")
            )
            element["fillStyle"] = "solid"
            element["strokeStyle"] = "solid"
            element["strokeWidth"] = 1
            element["opacity"] = 100
            element["roundness"] = {"type": 3}
            element["roughness"] = 0
            continue
        if element.get("type") == "text":
            element["fontFamily"] = _HELVETICA
            element.setdefault("strokeColor", _DARK_INK)
            if _is_group_title(element, semantic_id):
                element["fontStyle"] = 1
                element["strokeColor"] = element.get("strokeColor") or _DARK_INK
            else:
                element.setdefault("lineHeight", 1.25)
        elif element.get("type") in {"rectangle", "diamond"}:
            element["roughness"] = 0
            # A coherent rounded-rectangle language is easier to scan than a
            # mixture of sharp and rounded boxes.  Diamonds retain their own
            # geometry and are intentionally excluded from this rule.
            element["roundness"] = {"type": 3}
        elif element.get("type") == "arrow":
            element["roughness"] = 0
            if not isinstance(element.get("strokeWidth"), (int, float)) or element.get("strokeWidth", 0) <= 0:
                element["strokeWidth"] = 2
            label = element.get("label")
            if isinstance(label, dict):
                label["fontFamily"] = _HELVETICA
                label.setdefault("strokeColor", _DARK_INK)
    return output


__all__ = ["normalize_architecture_style"]
