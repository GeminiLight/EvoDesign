"""Canonical diagram-type registry shared by generation stages."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence


SYSTEM_PROMPT_DIR = Path(__file__).resolve().parents[1] / "system_prompt"
TYPE_PATTERNS_DIR = SYSTEM_PROMPT_DIR / "type_patterns"


DIAGRAM_TYPE_ALIASES = {
    "architecture_diagram": "architecture",
    "class": "class_diagram",
    "class_diagram": "class_diagram",
    "concept": "concept_map",
    "concept_map": "concept_map",
    "containment_diagram": "nested",
    "customer_journey": "user_journey",
    "customer_journey_map": "user_journey",
    "cycle_diagram": "cycle",
    "data_flow": "data_flow_diagram",
    "data_flow_diagram": "data_flow_diagram",
    "dataflow": "data_flow_diagram",
    "dependency": "dependency_graph",
    "dependency_diagram": "dependency_graph",
    "dependency_graph": "dependency_graph",
    "deployment_diagram": "deployment",
    "er": "er_diagram",
    "er_diagram": "er_diagram",
    "fishbone_diagram": "fishbone",
    "flow": "flowchart",
    "flow_chart": "flowchart",
    "flow_diagram": "flowchart",
    "flywheel": "cycle",
    "funnel_chart": "funnel",
    "gantt_chart": "gantt",
    "hybrid": "infographic",
    "infographic": "infographic",
    "infrastructure_diagram": "deployment",
    "journey_map": "user_journey",
    "kanban_board": "kanban",
    "layer_diagram": "layer_stack",
    "layered_diagram": "layer_stack",
    "layers": "layer_stack",
    "loop": "cycle",
    "loop_diagram": "cycle",
    "matrix_chart": "matrix",
    "mind_map": "mindmap",
    "nested_diagram": "nested",
    "network": "network_topology",
    "network_diagram": "network_topology",
    "org_chart": "orgchart",
    "priority_quadrant": "quadrant",
    "quadrant_chart": "quadrant",
    "quadrant_diagram": "quadrant",
    "sequence": "sequence_diagram",
    "sequence_diagram": "sequence_diagram",
    "stack_diagram": "layer_stack",
    "state": "state_diagram",
    "state_diagram": "state_diagram",
    "state_machine": "state_diagram",
    "story_mapping": "story_map",
    "swimlane_diagram": "swimlane",
    "swot_analysis": "swot",
    "task_board": "kanban",
    "timeline_diagram": "timeline",
    "tree_diagram": "tree",
    "two_by_two": "quadrant",
    "uml_class_diagram": "class_diagram",
    "uml_deployment_diagram": "deployment",
    "user_journey_map": "user_journey",
    "user_story_map": "story_map",
    "venn_diagram": "venn",
}


class DiagramTypeValidationError(ValueError):
    """Raised when a caller supplies a diagram type outside the supported catalog."""


def slugify(value: str) -> str:
    """Normalize a free-form chart type or stage name into a stable lookup key."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


@lru_cache(maxsize=1)
def get_supported_diagram_types() -> tuple[str, ...]:
    """Return the canonical diagram types backed by curated type-pattern files."""
    if not TYPE_PATTERNS_DIR.is_dir():
        return ()
    return tuple(sorted(path.stem for path in TYPE_PATTERNS_DIR.glob("*.md")))


def normalize_diagram_type(diagram_type: Optional[str]) -> str:
    """Map dataset/user chart type labels onto canonical knowledge keys."""
    if not diagram_type:
        return ""
    normalized = slugify(str(diagram_type))
    return DIAGRAM_TYPE_ALIASES.get(normalized, normalized)


def is_supported_diagram_type(diagram_type: Optional[str]) -> bool:
    """Return whether *diagram_type* resolves to a supported canonical type."""
    normalized = normalize_diagram_type(diagram_type)
    return bool(normalized) and normalized in get_supported_diagram_types()


def normalize_supported_diagram_type(
    diagram_type: Optional[str],
    *,
    field_name: str = "diagram_type",
    supported_types: Sequence[str] | None = None,
) -> str:
    """Normalize and validate a diagram type against the supported catalog."""
    normalized = normalize_diagram_type(diagram_type)
    if not normalized:
        raise DiagramTypeValidationError(f"{field_name} must be a non-empty string.")

    supported = tuple(supported_types) if supported_types is not None else get_supported_diagram_types()
    if normalized not in supported:
        supported_text = ", ".join(supported) if supported else "(none)"
        raise DiagramTypeValidationError(
            f"Unsupported {field_name} {diagram_type!r} (normalized to {normalized!r}). "
            f"Supported diagram types: {supported_text}."
        )
    return normalized


__all__ = [
    "DIAGRAM_TYPE_ALIASES",
    "DiagramTypeValidationError",
    "TYPE_PATTERNS_DIR",
    "get_supported_diagram_types",
    "is_supported_diagram_type",
    "normalize_diagram_type",
    "normalize_supported_diagram_type",
    "slugify",
]
