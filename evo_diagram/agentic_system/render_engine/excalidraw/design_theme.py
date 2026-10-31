"""Shared visual treatment for non-architecture diagrams.

Architecture diagrams get the full card design system. Other diagram types
keep their own layout and shapes (decisions stay diamonds, start and end stay
ellipses), but take the same treatment so every diagram reads as one design:
the style agent's family becomes a light fill and a coloured border, text is
one dark ink, connectors are thin, solid-headed and coloured by their source,
edge labels are muted, and icons use the outline set.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, Optional

from evo_diagram.agentic_system.common.node_icons import ICON_KEY, bundled_icons, icon_file
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation

from .architecture_design_system import (
    _ICON_KEYWORDS,
    _SUBLABEL_INK,
    _TITLE_INK,
    _hex,
    _mix,
    is_enabled,
)

logger = logging.getLogger(__name__)

THEMED_TYPES = {"flowchart", "flow_chart", "flow"}
THEME_KEY = "evoDesignTheme"
_STROKE_WIDTH = 1.5


def _ink(stroke: tuple) -> str:
    """The border colour, darkened when too light to carry an icon or a connector."""
    luminance = (0.299 * stroke[0] + 0.587 * stroke[1] + 0.114 * stroke[2]) / 255
    return _mix(stroke if luminance < 0.62 else tuple(round(c * 0.55) for c in stroke), 0)


def _outline_icon(label: str, current: str) -> str:
    if current.startswith("outline_"):
        return current
    haystack = label.lower()
    for needles, name in _ICON_KEYWORDS:
        if any(needle in haystack for needle in needles):
            return name
    outline = f"outline_{current}"
    return outline if outline in bundled_icons() else current


def apply_design_theme(manifest: Dict[str, Any], structure_instantiation: Any,
                       layout_instantiation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Restyle a non-architecture scene in place of its old treatment; unchanged on any doubt."""
    if not is_enabled() or not isinstance(manifest, dict):
        return manifest
    structure = unwrap_structure_instantiation(structure_instantiation)
    chart_type = str(structure.get("chart_type") or "").strip().lower()
    if chart_type not in THEMED_TYPES:
        return manifest

    result = deepcopy(manifest)
    elements = result.get("elements") or []
    meta = result.setdefault("_meta", {})
    id_map: Dict[str, str] = meta.get("id_map") or {}
    by_eid = {e.get("id"): e for e in elements}
    nodes = [n for n in structure.get("nodes") or [] if isinstance(n, dict) and n.get("id")]
    styling = layout_instantiation if isinstance(layout_instantiation, dict) else {}
    files = result.setdefault("files", {})

    host_ink: Dict[str, str] = {}
    node_ink: Dict[str, str] = {}
    for node in nodes:
        host = by_eid.get(id_map.get(str(node["id"]), ""))
        if not host or host.get("type") not in {"rectangle", "ellipse", "diamond"}:
            continue
        style = styling.get(node["id"]) if isinstance(styling.get(node["id"]), dict) else {}
        fill = _hex(style.get("backgroundColor")) or _hex(host.get("backgroundColor"))
        stroke = _hex(style.get("strokeColor")) or _hex(host.get("strokeColor"))
        if not fill or not stroke:
            continue
        ink = _ink(stroke)
        host.update({
            "backgroundColor": _mix(fill, 0.55), "strokeColor": ink, "strokeWidth": _STROKE_WIDTH,
            "roughness": 0, "fillStyle": "solid",
            "customData": {**(host.get("customData") or {}), THEME_KEY: True},
            "version": int(host.get("version", 1)) + 1,
        })
        if host["type"] == "rectangle":
            host["roundness"] = {"type": 3}
        host_ink[host["id"]] = node_ink[str(node["id"])] = ink

    for element in elements:
        kind = element.get("type")
        if kind == "text" and element.get("containerId") in host_ink:
            element.update({"strokeColor": _TITLE_INK, "fontFamily": 2, "roughness": 0})
        elif kind == "image":
            data = (element.get("customData") or {}).get(ICON_KEY) or {}
            host_id = data.get("hostId")
            if host_id not in host_ink or not data.get("name"):
                continue
            label = " ".join(str(t.get("text") or "") for t in elements
                             if t.get("type") == "text" and t.get("containerId") == host_id)
            name = _outline_icon(label, str(data["name"]))
            if name not in bundled_icons():
                continue
            asset = icon_file(name, host_ink[host_id])
            files[asset["id"]] = asset
            element.update({"fileId": asset["id"], "customData": {
                **(element.get("customData") or {}), ICON_KEY: {**data, "name": name}}})

    arrow_ids = set()
    for element in elements:
        if element.get("type") != "arrow":
            continue
        source = str((element.get("meta") or {}).get("source") or "")
        if not source:
            binding = element.get("startBinding") or {}
            source = next((n for n, eid in id_map.items() if eid == binding.get("elementId")), "")
        element.update({
            "strokeColor": node_ink.get(source, _SUBLABEL_INK), "strokeWidth": _STROKE_WIDTH,
            "roughness": 0, "endArrowhead": "triangle",
            "startArrowhead": "triangle" if element.get("startArrowhead") else None,
        })
        arrow_ids.add(element.get("id"))
    for element in elements:
        if element.get("type") == "text" and element.get("containerId") in arrow_ids:
            element.update({"strokeColor": _SUBLABEL_INK, "fontFamily": 2, "roughness": 0})

    used_files = {e.get("fileId") for e in elements if e.get("type") == "image"}
    result["files"] = {k: v for k, v in files.items() if k in used_files}
    result.setdefault("appState", {})["viewBackgroundColor"] = "#FFFFFF"
    meta["design_theme"] = {"chart_type": chart_type, "nodes": len(host_ink)}
    logger.info("[DesignTheme] Applied to %d nodes of a %s", len(host_ink), chart_type)
    return result
