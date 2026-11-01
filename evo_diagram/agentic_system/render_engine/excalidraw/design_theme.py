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

from evo_diagram.agentic_system.common.diagram_types import normalize_diagram_type
from evo_diagram.agentic_system.common.node_icons import ICON_KEY, bundled_icons, icon_file
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation

from .architecture_design_system import (
    _ICON_KEYWORDS,
    _MUTED,
    _MUTED_TITLE_INK,
    _PRIMARY_STROKE_WIDTH,
    aesthetic_enabled,
    emphasis_of,
    _SUBLABEL_INK,
    _TITLE_INK,
    _hex,
    _mix,
    is_enabled,
)

logger = logging.getLogger(__name__)

# Node-and-link types take the full treatment. Area types (blocks whose fill
# is the content) keep more of their colour so neighbouring blocks stay
# distinct. Venn diagrams are excluded: their overlaps are drawn by
# translucent fills that a lighter tint washes out.
LINK_TYPES = {
    "flowchart", "swimlane", "data_flow_diagram", "state_diagram", "sequence_diagram",
    "class_diagram", "er_diagram", "network_topology", "orgchart", "tree", "mindmap",
    "concept_map", "fishbone",
}
AREA_TYPES = {"gantt", "timeline", "funnel", "pyramid", "swot", "matrix", "infographic"}
THEMED_TYPES = LINK_TYPES | AREA_TYPES
# Chen-notation ER links carry no direction, whatever heads the agents drew.
UNDIRECTED_TYPES = {"er_diagram"}
_LINK_TINT = 0.55
_LEAF_TINT = 0.75
# Types whose hierarchy is the tree itself: the root leads and leaves recede.
TREE_TYPES = {"mindmap", "tree", "orgchart"}
_AREA_TINT = 0.3
THEME_KEY = "evoDesignTheme"
_STROKE_WIDTH = 1.5


def _ink(stroke: tuple) -> str:
    """The border colour, darkened when too light to carry an icon or a connector."""
    luminance = (0.299 * stroke[0] + 0.587 * stroke[1] + 0.114 * stroke[2]) / 255
    return _mix(stroke if luminance < 0.62 else tuple(round(c * 0.55) for c in stroke), 0)


def _outline_icon(label: str, current: str) -> str:
    """The outline twin of the agent's icon, else one matched on the label."""
    if current.startswith("outline_"):
        return current
    outline = f"outline_{current}"
    if outline in bundled_icons():
        return outline
    haystack = label.lower()
    for needles, name in _ICON_KEYWORDS:
        if any(needle in haystack for needle in needles):
            return name
    return current


def _head(value: Any) -> Any:
    """Plain heads become solid triangles; UML heads (hollow triangle, diamond) keep their meaning."""
    return "triangle" if value == "arrow" else value


def _tree_emphasis(nodes: list, edges: list, agent: Dict[str, str]) -> Dict[str, str]:
    """Root reads as primary and leaves recede, unless the agent said otherwise."""
    ids = {str(n["id"]) for n in nodes}
    children: Dict[str, list] = {}
    parent: Dict[str, str] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in ids and target in ids and target not in parent:
            parent[target] = source
            children.setdefault(source, []).append(target)
    for node in nodes:
        pid = node.get("parent_id") or node.get("parent")
        if pid and str(pid) in ids and str(node["id"]) not in parent:
            parent[str(node["id"])] = str(pid)
            children.setdefault(str(pid), []).append(str(node["id"]))
    roots = [i for i in ids if i not in parent and i in children]
    result = dict(agent)
    for node_id in ids:
        if result.get(node_id):
            continue
        if node_id in roots and len(roots) == 1:
            result[node_id] = "primary"
        elif node_id not in children and node_id in parent and parent[node_id] not in roots:
            result[node_id] = "leaf"
    return result


# Process types read along one happy path from start to end.
MAIN_PATH_TYPES = {"flowchart", "swimlane"}
_POSITIVE = ("yes", "是", "通过", "成功", "ok", "pass", "approve", "批准", "同意", "true")
_SIDE_OPACITY = 60


def _main_path(nodes: list, edges: list) -> set:
    """Edges of the longest start-to-end run, preferring positive branches; back edges ignored."""
    ids = [str(n["id"]) for n in nodes]
    out: Dict[str, list] = {}
    incoming = set()
    for edge in edges:
        if isinstance(edge, dict) and str(edge.get("source")) in ids and str(edge.get("target")) in ids:
            out.setdefault(str(edge["source"]), []).append(edge)
            incoming.add(str(edge["target"]))
    starts = [str(n["id"]) for n in nodes if n.get("class") == "start"] or [i for i in ids if i not in incoming]
    best: Dict[str, tuple] = {}

    def walk(node: str, seen: frozenset) -> tuple:
        if node in best:
            return best[node]
        result = (0, 0, ())
        for edge in out.get(node, []):
            target = str(edge["target"])
            if target in seen:
                continue
            length, positive, path = walk(target, seen | {target})
            label = str(edge.get("label") or "").lower()
            candidate = (length + 1, positive + any(w in label for w in _POSITIVE), (edge.get("id"),) + path)
            result = max(result, candidate, key=lambda r: (r[0], r[1]))
        best[node] = result
        return result

    paths = [walk(s, frozenset({s})) for s in starts]
    return set(max(paths, key=lambda r: (r[0], r[1]), default=(0, 0, ()))[2]) - {None}


def apply_design_theme(manifest: Dict[str, Any], structure_instantiation: Any,
                       layout_instantiation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Restyle a non-architecture scene in place of its old treatment; unchanged on any doubt."""
    if not is_enabled() or not isinstance(manifest, dict):
        return manifest
    structure = unwrap_structure_instantiation(structure_instantiation)
    chart_type = normalize_diagram_type(str(structure.get("chart_type") or ""))
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

    emphasis = {str(n["id"]): emphasis_of(n) for n in nodes}
    if chart_type in TREE_TYPES:
        emphasis = _tree_emphasis(nodes, structure.get("edges") or [], emphasis)
    use_emphasis = aesthetic_enabled("EMPHASIS")

    host_ink: Dict[str, str] = {}
    node_ink: Dict[str, str] = {}
    muted_hosts = set()
    for node in nodes:
        host = by_eid.get(id_map.get(str(node["id"]), ""))
        if not host or host.get("type") not in {"rectangle", "ellipse", "diamond"}:
            continue
        style = styling.get(node["id"]) if isinstance(styling.get(node["id"]), dict) else {}
        fill = _hex(style.get("backgroundColor")) or _hex(host.get("backgroundColor"))
        tint = _AREA_TINT if chart_type in AREA_TYPES else _LINK_TINT
        stroke = _hex(style.get("strokeColor")) or _hex(host.get("strokeColor"))
        if not fill or not stroke:
            continue
        ink = _ink(stroke)
        level = emphasis.get(str(node["id"]), "") if use_emphasis else ""
        background, width = _mix(fill, tint), _STROKE_WIDTH
        if level == "primary":
            background, width = _mix(_hex(ink), 0.82), _PRIMARY_STROKE_WIDTH
        elif level == "leaf":
            background, width = _mix(fill, _LEAF_TINT), 1
        elif level == "muted":
            background, ink, width = _MUTED[0], _MUTED[2], 1
            muted_hosts.add(host["id"])
        host.update({
            "backgroundColor": background, "strokeColor": ink, "strokeWidth": width,
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
            ink = _MUTED_TITLE_INK if element.get("containerId") in muted_hosts else _TITLE_INK
            element.update({"strokeColor": ink, "fontFamily": 2, "roughness": 0})
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

    main_edges = set()
    if chart_type in MAIN_PATH_TYPES and aesthetic_enabled("MAINPATH"):
        main_edges = _main_path(nodes, structure.get("edges") or [])
    arrow_ids = set()
    for element in elements:
        if element.get("type") != "arrow":
            continue
        source = str((element.get("meta") or {}).get("source") or "")
        if not source:
            binding = element.get("startBinding") or {}
            source = next((n for n, eid in id_map.items() if eid == binding.get("elementId")), "")
        on_main = (element.get("meta") or {}).get("semantic_edge_id") in main_edges
        element.update({
            "strokeColor": node_ink.get(source, _SUBLABEL_INK),
            "strokeWidth": _PRIMARY_STROKE_WIDTH if on_main else _STROKE_WIDTH,
            "opacity": 100 if on_main or not main_edges else _SIDE_OPACITY,
            # Undirected links (ER, mind map) stay undirected.
            "roughness": 0,
            "endArrowhead": None if chart_type in UNDIRECTED_TYPES else _head(element.get("endArrowhead")),
            "startArrowhead": None if chart_type in UNDIRECTED_TYPES else _head(element.get("startArrowhead")),
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
