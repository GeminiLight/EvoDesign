"""Schemas for VLM visual observations."""

from typing import List, Literal
from pydantic import BaseModel, Field


class CategoryObservation(BaseModel):
    """Observation for a specific category of changes."""

    description: str = Field(
        ..., description="What changed in this category"
    )
    magnitude: Literal["minor", "moderate", "major"] = Field(
        ..., description="Change magnitude: minor, moderate, or major"
    )
    affected_properties: List[str] = Field(
        default_factory=list,
        description="Properties likely affected by this change"
    )


class VisualObservation(BaseModel):
    """High-level visual differences observed by VLM."""

    structural_changes: CategoryObservation = Field(
        ..., description="Changes to diagram structure (nodes, edges, groups)"
    )
    styling_changes: CategoryObservation = Field(
        ..., description="Changes to visual styling (colors, shapes, fonts)"
    )
    layout_changes: CategoryObservation = Field(
        ..., description="Changes to spatial layout (positions, spacing)"
    )
    semantic_changes: CategoryObservation = Field(
        ..., description="Changes to semantic content (labels, text)"
    )
    overall_intent: str = Field(
        ..., description="Inferred user intent for making these changes"
    )
