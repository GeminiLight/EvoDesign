"""Schemas for JSON diff extraction."""

from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field

from .observation_schemas import VisualObservation


class PropertyChange(BaseModel):
    """A single property change detected in JSON diff."""

    property_path: str = Field(
        ..., description="Path to the property (e.g., 'props.color', 'x')"
    )
    from_value: Any = Field(
        ..., description="Original value in model-generated diagram"
    )
    to_value: Any = Field(
        ..., description="New value in user-adjusted diagram"
    )
    category: Literal["structure", "styling", "layout", "other"] = Field(
        ..., description="Agent category: structure, styling, layout, or other"
    )
    is_priority: bool = Field(
        default=False,
        description="Whether VLM flagged this as important change"
    )
    vlm_hint: Optional[str] = Field(
        default=None,
        description="VLM observation category: structural, styling, layout, or semantic"
    )


class ShapeAddition(BaseModel):
    """A shape added by the user."""

    shape_id: str = Field(..., description="ID of the added shape")
    shape_type: str = Field(..., description="Type of shape (geo, arrow, text, frame)")
    properties: dict = Field(..., description="All properties of the added shape")
    related_observation: str = Field(
        ..., description="Related VLM observation category"
    )


class ShapeDeletion(BaseModel):
    """A shape deleted by the user."""

    shape_id: str = Field(..., description="ID of the deleted shape")
    shape_type: str = Field(..., description="Type of shape")
    properties: dict = Field(..., description="All properties of the deleted shape")
    related_observation: str = Field(
        ..., description="Related VLM observation category"
    )


class ShapeModification(BaseModel):
    """Modifications to an existing shape."""

    shape_id: str = Field(..., description="ID of the modified shape")
    changes: List[PropertyChange] = Field(
        default_factory=list,
        description="List of property changes for this shape"
    )


class GuidedDiff(BaseModel):
    """Complete JSON diff guided by VLM observations."""

    visual_observation: VisualObservation = Field(
        ..., description="VLM observations that guide this diff"
    )
    additions: List[ShapeAddition] = Field(
        default_factory=list,
        description="Shapes added by user"
    )
    deletions: List[ShapeDeletion] = Field(
        default_factory=list,
        description="Shapes deleted by user"
    )
    modifications: List[ShapeModification] = Field(
        default_factory=list,
        description="Shapes modified by user"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Warnings from format detection and normalization"
    )
