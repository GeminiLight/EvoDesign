"""Choose a bounded logical viewport for the layout agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
)


@dataclass(frozen=True)
class LayoutViewportPlan:
    """Program-selected composition budget passed to the layout model."""

    profile: str
    width: int
    height: int
    node_count: int
    edge_count: int
    group_count: int
    label_char_count: int

    def to_prompt(self) -> str:
        return (
            "- Program-selected profile: "
            f"{self.profile}\n"
            f"- Preferred logical viewport: {self.width} x {self.height}\n"
            "- Target content occupancy: 70%-90% of the preferred viewport's "
            "longest axis\n"
            f"- Input load: {self.node_count} nodes, {self.edge_count} edges, "
            f"{self.group_count} groups, {self.label_char_count} label characters\n"
            f"- Hard safety bounds: {CANVAS_DEFAULT_VIEWPORT_WIDTH} x "
            f"{CANVAS_DEFAULT_VIEWPORT_HEIGHT}\n"
            "- Treat the preferred viewport as the composition constraint. "
            "Exceed it only when the supplied minimum element sizes cannot fit; "
            "never spread elements merely to fill the hard safety bounds."
        )


_PROFILES = {
    "compact": (1200, 800),
    "wide": (1600, 900),
    "large": (2400, 1600),
    "extended": (3200, 2200),
}


def _label_char_count(structure: Mapping[str, Any]) -> int:
    count = 0
    for collection in ("nodes", "groups"):
        for item in structure.get(collection, []) or []:
            if isinstance(item, Mapping):
                count += len(str(item.get("label") or "").strip())
    for edge in structure.get("edges", []) or []:
        if isinstance(edge, Mapping):
            count += len(str(edge.get("label") or "").strip())
    return count


def choose_layout_viewport(
    structure_instantiation: Optional[Mapping[str, Any]],
) -> LayoutViewportPlan:
    """Select a viewport from semantic load instead of exposing a 4000px blank page.

    Draw.io's compact single-page discipline works because the model receives a
    real composition budget. EvoDiagram keeps its 4000 x 4000 hard bounds for
    exceptional diagrams, but ordinary inputs get a substantially smaller
    preferred viewport chosen before coordinates are generated.
    """

    structure = structure_instantiation or {}
    nodes = [item for item in structure.get("nodes", []) or [] if isinstance(item, Mapping)]
    edges = [item for item in structure.get("edges", []) or [] if isinstance(item, Mapping)]
    groups = [item for item in structure.get("groups", []) or [] if isinstance(item, Mapping)]
    label_chars = _label_char_count(structure)

    node_count = len(nodes)
    edge_count = len(edges)
    group_count = len(groups)

    # Relationships and organizers both consume routing space, while long labels
    # consume horizontal space. Keep the thresholds intentionally coarse so a
    # small semantic change does not make the whole composition jump profiles.
    complexity = (
        node_count
        + edge_count * 0.45
        + group_count * 2.0
        + max(0, label_chars - node_count * 14) / 90.0
    )
    if node_count <= 8 and complexity <= 14:
        profile = "compact"
    elif node_count <= 16 and complexity <= 28:
        profile = "wide"
    elif node_count <= 32 and complexity <= 52:
        profile = "large"
    else:
        profile = "extended"

    width, height = _PROFILES[profile]
    return LayoutViewportPlan(
        profile=profile,
        width=width,
        height=height,
        node_count=node_count,
        edge_count=edge_count,
        group_count=group_count,
        label_char_count=label_chars,
    )


__all__ = ["LayoutViewportPlan", "choose_layout_viewport"]
