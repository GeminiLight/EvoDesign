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
    "data_flow": "data_flow_diagram",
    "data_flow_diagram": "data_flow_diagram",
    "dataflow": "data_flow_diagram",
    "er": "er_diagram",
    "er_diagram": "er_diagram",
    "fishbone_diagram": "fishbone",
    "flow": "flowchart",
    "flow_chart": "flowchart",
    "flow_diagram": "flowchart",
    "funnel_chart": "funnel",
    "gantt_chart": "gantt",
    "hybrid": "infographic",
    "infographic": "infographic",
    "matrix_chart": "matrix",
    "mind_map": "mindmap",
    "network": "network_topology",
    "network_diagram": "network_topology",
    "org_chart": "orgchart",
    "sequence": "sequence_diagram",
    "sequence_diagram": "sequence_diagram",
    "state": "state_diagram",
    "state_diagram": "state_diagram",
    "state_machine": "state_diagram",
    "swimlane_diagram": "swimlane",
    "swot_analysis": "swot",
    "timeline_diagram": "timeline",
    "tree_diagram": "tree",
    "uml_class_diagram": "class_diagram",
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
