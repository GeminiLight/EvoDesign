"""Diagram facts the routers read from the structure and the rendered scene."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from evodesign.agentic_system.common.semantic_ids import group_frame_render_id

ARCHITECTURE_TYPES = {"architecture", "architecture_diagram"}
CONCEPT_MAP_TYPES = {"concept_map", "concept map", "conceptmap"}


@dataclass
class DiagramContext:
    chart_type: str = ""
    # node id -> group id, from node.group_id first, then group membership
    node_group_ids: Dict[str, str] = field(default_factory=dict)
    core_node_ids: Set[str] = field(default_factory=set)
    # Cross-cutting / governance groups that sit beside architecture layers.
    side_group_ids: Set[str] = field(default_factory=set)
    group_frame_ids: Set[str] = field(default_factory=set)
    # Rendered concept-map section frames, top-to-bottom then left-to-right.
    concept_frames: List[Tuple[str, Dict[str, float]]] = field(default_factory=list)

    @property
    def is_architecture(self) -> bool:
        return self.chart_type in ARCHITECTURE_TYPES

    @property
    def is_concept_map(self) -> bool:
        return self.chart_type in CONCEPT_MAP_TYPES


def _diagram_context(
    structure: Dict[str, Any],
    id_map: Dict[str, str],
    elements: List[Dict[str, Any]],
) -> DiagramContext:
    nodes = [node for node in structure.get("nodes", []) or [] if isinstance(node, dict)]
    groups = [group for group in structure.get("groups", []) or [] if isinstance(group, dict)]
    context = DiagramContext(chart_type=str(structure.get("chart_type", "")).lower())
    context.node_group_ids = {
        str(node.get("id")): str(node.get("group_id"))
        for node in nodes
        if node.get("id") and node.get("group_id")
    }
    context.core_node_ids = {
        str(node.get("id"))
        for node in nodes
        if node.get("id") and str(node.get("class", "")).lower() in {"core", "core_concept"}
    }
    for group in groups:
        if not group.get("id"):
            continue
        group_id = str(group["id"])
        token = " ".join(str(group.get(key, "")).lower() for key in ("id", "class", "label"))
        if "cross" in token or "governance" in token:
            context.side_group_ids.add(group_id)
        for member_id in group.get("members", []) or []:
            if isinstance(member_id, str):
                context.node_group_ids.setdefault(member_id, group_id)
    context.group_frame_ids = {
        render_id
        for group in groups
        for render_id in [group_frame_render_id(id_map, group.get("id"))]
        if render_id
    }
    if context.is_concept_map:
        rendered_frames = {
            render_id
            for semantic_id, render_id in id_map.items()
            if semantic_id.endswith(":background")
        }
        context.concept_frames = sorted(
            (
                (
                    str(element["id"]),
                    {
                        "x": float(element.get("x", 0.0) or 0.0),
                        "y": float(element.get("y", 0.0) or 0.0),
                        "w": float(element.get("width", 0.0) or 0.0),
                        "h": float(element.get("height", 0.0) or 0.0),
                    },
                )
                for element in elements
                if isinstance(element, dict) and element.get("id") in rendered_frames
            ),
            key=lambda item: (item[1]["y"], item[1]["x"]),
        )
    return context
