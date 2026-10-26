"""Shared input contract for backend diagram generation."""

from __future__ import annotations

from app.core.canvas import (
    SUPPORTED_CANVAS_LIBRARIES,
    CanvasLibrary,
    normalize_canvas_library_value,
)
from app.core.exceptions import PublicErrorMixin


GENERATION_INVALID_REQUEST_DETAIL = "Diagram generation request is invalid"
GENERATION_UNSUPPORTED_CANVAS_DETAIL = "Unsupported canvas library"


class GenerationInputValidationError(PublicErrorMixin, ValueError):
    """Raised when generation input is invalid before engine execution."""

    default_public_detail = GENERATION_INVALID_REQUEST_DETAIL


def normalize_canvas_library(canvas_library: str) -> CanvasLibrary:
    """Normalize and validate the requested canvas library."""
    try:
        return normalize_canvas_library_value(canvas_library)
    except ValueError as exc:
        raise GenerationInputValidationError(
            f"Unsupported canvas library: {canvas_library}",
            public_detail=GENERATION_UNSUPPORTED_CANVAS_DETAIL,
        ) from exc


__all__ = (
    "CanvasLibrary",
    "GENERATION_INVALID_REQUEST_DETAIL",
    "GENERATION_UNSUPPORTED_CANVAS_DETAIL",
    "GenerationInputValidationError",
    "SUPPORTED_CANVAS_LIBRARIES",
    "normalize_canvas_library",
)
