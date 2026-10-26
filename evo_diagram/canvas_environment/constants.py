"""Compatibility re-exports for shared canvas runtime constants."""

from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
    CANVAS_MARGIN,
    CANVAS_MAX_X,
    CANVAS_MAX_Y,
    VALID_CANVAS_LIBRARIES,
)

__all__ = [
    "VALID_CANVAS_LIBRARIES",
    "CANVAS_MAX_X",
    "CANVAS_MAX_Y",
    "CANVAS_MARGIN",
    "CANVAS_DEFAULT_VIEWPORT_WIDTH",
    "CANVAS_DEFAULT_VIEWPORT_HEIGHT",
]
