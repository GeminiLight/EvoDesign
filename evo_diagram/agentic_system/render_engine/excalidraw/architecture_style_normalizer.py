"""Normalize architecture scenes to a formal, draw.io-like visual language."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation


_ARCHITECTURE_TYPES = {"architecture", "architecture_diagram"}
_HELVETICA = 2


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
    for element in output.get("elements", []):
        if not isinstance(element, dict):
            continue
        if element.get("type") == "text":
            element["fontFamily"] = _HELVETICA
        elif element.get("type") == "arrow":
            element["roughness"] = 0
            label = element.get("label")
            if isinstance(label, dict):
                label["fontFamily"] = _HELVETICA
    return output


__all__ = ["normalize_architecture_style"]
