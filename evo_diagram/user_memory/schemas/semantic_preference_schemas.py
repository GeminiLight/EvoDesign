"""
Semantic Preference Schemas - LLM-extracted user preferences

These schemas represent high-level, context-rich preferences extracted by LLM
from diagram modifications, replacing the previous rule-based approach.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class SemanticPreference(BaseModel):
    """
    A single semantic preference extracted by LLM.

    Unlike rule-based preferences (e.g., "changes_color_blue_to_red"),
    semantic preferences are context-rich and actionable:
    "User prefers red color for entity nodes in class diagrams to emphasize core domain objects"
    """

    preference_text: str = Field(
        description=(
            "Natural language description of the preference, context-rich and actionable. "
            "Should be specific enough for agents to apply in future diagrams."
        )
    )

    agent_category: Literal["Structure", "Styling", "Layout"] = Field(
        description=(
            "Which agent workflow this preference primarily affects:\n"
            "- Structure: Semantic organization (node types, edge relations, grouping)\n"
            "- Styling: Visual appearance (colors, shapes, fills, arrows, fonts)\n"
            "- Layout: Spatial arrangement (positions, spacing, sizing)"
        )
    )

    applies_to: Dict[str, Any] = Field(
        description=(
            "Context where this preference applies. Should include:\n"
            "- diagram_type: e.g., 'class', 'dataflow', 'sequence'\n"
            "- content_area: e.g., 'Software Engineering', 'Business Process'\n"
            "- element_type: e.g., 'node', 'edge', 'arrow', 'group'\n"
            "- element_role (optional): e.g., 'entity', 'service', 'flow'"
        ),
        default_factory=dict
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence score (0.0-1.0). Higher confidence indicates:\n"
            "- Consistent pattern across multiple elements\n"
            "- Strong alignment with VLM observations\n"
            "- Clear design rationale"
        )
    )

    design_rationale: str = Field(
        description=(
            "Explanation of why this preference improves the diagram. "
            "Should articulate the design principle or user intent."
        )
    )

    evidence_summary: str = Field(
        description=(
            "Brief summary of the changes that support this preference. "
            "E.g., 'Changed 4 entity nodes from blue to red'"
        )
    )


class PreferenceExtractionResult(BaseModel):
    """Result of LLM-based preference extraction."""

    status: Literal["succeeded", "no_preferences", "failed"] = Field(
        default="succeeded",
        description=(
            "Extraction status. no_preferences is a clean empty result; failed "
            "means extraction could not complete."
        ),
    )

    preferences: List[SemanticPreference] = Field(
        default_factory=list,
        description="Extracted semantic preferences (confidence >= min_threshold)"
    )

    filtered_count: int = Field(
        default=0,
        description="Number of preferences filtered due to low confidence"
    )

    task_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context from task.json (diagram_type, content_area, etc.)"
    )

    reasoning: Optional[str] = Field(
        default=None,
        description="LLM's reasoning process (not stored in memory, used for debugging)"
    )

    errors: List[str] = Field(
        default_factory=list,
        description="Extraction errors when status is failed",
    )

    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal extraction warnings",
    )


class PreferenceQuery(BaseModel):
    """Query for retrieving preferences from memory."""

    query: str = Field(
        description="Natural language query describing what preferences to retrieve"
    )

    agent_category: Optional[Literal["Structure", "Styling", "Layout"]] = Field(
        default=None,
        description="Filter by agent workflow category"
    )

    diagram_type: Optional[str] = Field(
        default=None,
        description="Filter by diagram type (e.g., 'class', 'dataflow')"
    )

    content_area: Optional[str] = Field(
        default=None,
        description="Filter by content area (e.g., 'Software Engineering')"
    )

    user_id: str = Field(
        description="User identifier for multi-user scenarios"
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of preferences to retrieve"
    )
