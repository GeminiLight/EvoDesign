"""Schemas for user preference memory system."""

from .observation_schemas import CategoryObservation, VisualObservation
from .diff_schemas import (
    PropertyChange,
    ShapeAddition,
    ShapeDeletion,
    ShapeModification,
    GuidedDiff,
)
from .semantic_preference_schemas import (
    SemanticPreference,
    PreferenceExtractionResult,
    PreferenceQuery,
)

__all__ = [
    # Observation schemas
    "CategoryObservation",
    "VisualObservation",
    # Diff schemas
    "PropertyChange",
    "ShapeAddition",
    "ShapeDeletion",
    "ShapeModification",
    "GuidedDiff",
    # Semantic preference schemas
    "SemanticPreference",
    "PreferenceExtractionResult",
    "PreferenceQuery",
]
