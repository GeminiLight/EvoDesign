"""Normalize architecture scenes to a formal, draw.io-like visual language."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    TITLE_SUFFIX,
    group_frame_render_id,
    id_map_from_manifest,
    reverse_id_map,
)
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation


_ARCHITECTURE_TYPES = {"architecture", "architecture_diagram"}
_HELVETICA = 2
_GROUP_TITLE_FONT_SIZE = 18
_NODE_FONT_SIZE = 16
_EDGE_LABEL_FONT_SIZE = 13
_MAIN_CONNECTOR_WIDTH = 1.5
_CONNECTOR_ARROWHEAD = "triangle"
_DARK_INK = "#1F2937"
_CONNECTOR_INK = "#4B5563"

# Draw.io's strongest default diagrams use a small set of paired light fills
# and darker borders. Keep that grammar, but reserve each pair for a stable
# architecture role instead of cycling colours for decoration.
_ROLE_STYLES = {
    "presentation": ("#DAE8FC", "#6C8EBF"),
    "business": ("#D5E8D4", "#82B366"),
    "data": ("#E1D5E7", "#9673A6"),
    "external": ("#FFF2CC", "#D6B656"),
    "governance": ("#F8CECC", "#B85450"),
    "neutral": ("#F5F5F5", "#666666"),
}

# A light surface makes the group boundary legible without turning the
# architecture diagram into a collection of heavy dashed boxes.  The tints
# deliberately stay close in value so that node fills remain the recognition
# anchors inside each layer.
_FRAME_TINTS = {
    "presentation": "#F7FAFE",
    "service": "#F7FAF6",
    "business": "#F7FAF6",
    "data": "#FAF8FC",
    "cross": "#FFF8F7",
    "governance": "#FFF8F7",
}

# Group frames are orientation aids, not primary content. Keeping their
# opacity below the node/connector layer preserves the draw.io-like hierarchy
# even when a frame spans several dense layers.
_FRAME_OPACITY = 72


def _role_from_token(value: Any) -> str:
    token = str(value or "").strip().lower().replace("-", "_")
    if any(part in token for part in ("cross", "governance", "security", "operational", "communication")):
        return "governance"
    if any(part in token for part in ("external", "gateway", "queue", "message")):
        return "external"
    if any(part in token for part in ("data", "database", "store", "persistence", "integration")):
        return "data"
    if any(part in token for part in ("service", "business", "api", "domain")):
        return "business"
    if any(part in token for part in ("presentation", "ui", "client", "user")):
        return "presentation"
    return "neutral"


def _semantic_id_for_element(
    reverse_map: Mapping[str, str], element: Mapping[str, Any]
) -> str:
    return str(reverse_map.get(str(element.get("id", "")), ""))


def _is_group_frame(
    element: Mapping[str, Any],
    semantic_id: str,
    group_frame_ids: set[str],
) -> bool:
    element_id = str(element.get("id", "")).lower()
    return (
        element.get("type") in {"rectangle", "ellipse"}
        and (
            element_id.startswith("frame-")
            or str(element.get("id", "")) in group_frame_ids
            or semantic_id.endswith(BACKGROUND_SUFFIX)
        )
    )


def _is_group_title(element: Mapping[str, Any], semantic_id: str) -> bool:
    element_id = str(element.get("id", "")).lower()
    return element.get("type") == "text" and (
        element_id.startswith("title-")
        or element_id.endswith(TITLE_SUFFIX)
        or semantic_id.endswith(TITLE_SUFFIX)
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
    id_map = id_map_from_manifest(output)
    reverse_map = reverse_id_map(id_map)
    groups = [
        group
        for group in structure.get("groups", []) or []
        if isinstance(group, Mapping)
    ]
    group_roles = {
        str(group.get("id", "")): _role_from_token(
            " ".join(
                str(group.get(key, ""))
                for key in ("id", "label", "class")
            )
        )
        for group in groups
    }
    member_group_roles = {
        str(member_id): group_roles.get(str(group.get("id", "")), "neutral")
        for group in groups
        for member_id in group.get("members", []) or []
        if isinstance(member_id, str)
    }
    member_group_roles.update(
        {
            str(node.get("id")): group_roles.get(str(node.get("group_id", "")), "neutral")
            for node in structure.get("nodes", []) or []
            if isinstance(node, Mapping)
            and isinstance(node.get("id"), str)
            and node.get("group_id")
        }
    )
    node_roles: Dict[str, str] = {}
    for node in structure.get("nodes", []) or []:
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            continue
        node_id = str(node["id"])
        own_role = _role_from_token(
            " ".join(str(node.get(key, "")) for key in ("id", "label", "class"))
        )
        group_role = member_group_roles.get(node_id, "neutral")
        # Architecture layers carry the primary colour meaning. External and
        # governance nodes remain explicit exceptions; generic words such as
        # "data model" must not recolour a business-layer component.
        node_roles[node_id] = (
            own_role
            if own_role in {"external", "governance"} or group_role == "neutral"
            else group_role
        )
    node_render_roles = {
        render_id: node_roles[semantic_id]
        for semantic_id, role in node_roles.items()
        for render_id in [id_map.get(semantic_id)]
        if render_id and role
    }
    group_frame_ids = {
        render_id
        for group in structure.get("groups", []) or []
        if isinstance(group, Mapping)
        for render_id in [group_frame_render_id(id_map, group.get("id"))]
        if render_id
    }
    group_frame_roles = {
        render_id: group_roles.get(str(group.get("id", "")), "neutral")
        for group in groups
        for render_id in [group_frame_render_id(id_map, group.get("id"))]
        if render_id
    }
    output.setdefault("appState", {})["viewBackgroundColor"] = "#FFFFFF"
    for element in output.get("elements", []):
        if not isinstance(element, dict):
            continue
        render_id = str(element.get("id", ""))
        semantic_id = _semantic_id_for_element(reverse_map, element)
        if _is_group_frame(element, semantic_id, group_frame_ids):
            role = group_frame_roles.get(render_id, _role_from_token(semantic_id))
            element["backgroundColor"] = _FRAME_TINTS.get(role, "#F8FAFC")
            element["strokeColor"] = _ROLE_STYLES.get(role, _ROLE_STYLES["neutral"])[1]
            element["fillStyle"] = "solid"
            element["strokeStyle"] = "solid"
            element["strokeWidth"] = 1
            element["opacity"] = _FRAME_OPACITY
            element["roundness"] = {"type": 3}
            element["roughness"] = 0
            continue
        if element.get("type") == "text":
            element["fontFamily"] = _HELVETICA
            element["strokeColor"] = _DARK_INK
            if _is_group_title(element, semantic_id):
                element["fontStyle"] = 1
                element["fontSize"] = _GROUP_TITLE_FONT_SIZE
                element["lineHeight"] = 1.15
            else:
                element["lineHeight"] = 1.2
                if str(element.get("containerId", "")) in node_render_roles:
                    element["fontSize"] = _NODE_FONT_SIZE
                elif str(element.get("containerId", "")):
                    current_font_size = element.get("fontSize")
                    element["fontSize"] = (
                        min(16, int(current_font_size))
                        if isinstance(current_font_size, (int, float))
                        else 16
                    )
        elif element.get("type") in {"rectangle", "ellipse", "diamond"}:
            element["roughness"] = 0
            role = node_render_roles.get(render_id)
            if role and element.get("type") == "ellipse":
                # Architecture components are box-shaped units. Ellipses have
                # formal meaning in other chart families (events, ER
                # attributes, sets), but here they are decorative and make
                # sibling components look inconsistent.
                element["type"] = "rectangle"
            # A coherent rounded-rectangle language is easier to scan than a
            # mixture of sharp and rounded boxes.  Diamonds retain their own
            # geometry and are intentionally excluded from this rule.
            element["roundness"] = {"type": 3}
            if role:
                fill, stroke = _ROLE_STYLES[role]
                element["backgroundColor"] = fill
                element["strokeColor"] = stroke
                element["fillStyle"] = "solid"
                element["strokeStyle"] = "solid"
                # A 1.5px border matches draw.io's compact node language and
                # leaves the 2px main-flow connectors as the stronger signal.
                element["strokeWidth"] = 1.5
                element["opacity"] = 100
        elif element.get("type") == "arrow":
            element["roughness"] = 0
            meta = element.get("meta")
            target_id = str(meta.get("target", "")) if isinstance(meta, Mapping) else ""
            is_supporting = node_roles.get(target_id) == "governance"
            element["strokeColor"] = (
                _ROLE_STYLES["governance"][1] if is_supporting else _CONNECTOR_INK
            )
            # Supporting relationships should recede behind the primary
            # architecture flow.  Draw.io uses a lighter dashed connector
            # for this hierarchy; keep the distinction visible in Excalidraw
            # without changing the semantic edge or its arrowhead.
            element["strokeWidth"] = 1.5 if is_supporting else _MAIN_CONNECTOR_WIDTH
            element["opacity"] = 78 if is_supporting else 100
            element["strokeStyle"] = "dashed" if is_supporting else "solid"
            element["startArrowhead"] = None
            element["endArrowhead"] = _CONNECTOR_ARROWHEAD
            points = element.get("points")
            element["elbowed"] = isinstance(points, list) and len(points) > 2
            element["roundness"] = None
            label = element.get("label")
            if isinstance(label, dict):
                label["fontFamily"] = _HELVETICA
                label["fontSize"] = _EDGE_LABEL_FONT_SIZE
                label["lineHeight"] = 1.15
                label["strokeColor"] = _DARK_INK
    return output


__all__ = ["normalize_architecture_style"]
