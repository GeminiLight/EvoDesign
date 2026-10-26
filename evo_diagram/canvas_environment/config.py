"""Configuration objects for the canvas environment facade."""

from __future__ import annotations

from dataclasses import dataclass

from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
    normalize_canvas_library,
)


@dataclass(frozen=True)
class CanvasEnvironmentConfig:
    """Runtime options for canvas conversion and rendering.

    The first facade version still delegates to the existing implementation in
    ``agentic_system.render_engine``. Keeping these options explicit here makes
    the eventual physical extraction much less invasive.
    """

    canvas_library: str = "excalidraw"
    viewport_width: int = CANVAS_DEFAULT_VIEWPORT_WIDTH
    viewport_height: int = CANVAS_DEFAULT_VIEWPORT_HEIGHT

    @classmethod
    def from_settings(cls) -> "CanvasEnvironmentConfig":
        """Build config from the repo's current AppSettings singleton."""
        from evo_diagram.config.settings import AppSettings

        settings = AppSettings.get_default()
        return cls(canvas_library=settings.canvas_library)

    def normalized_canvas_library(self) -> str:
        return normalize_canvas_library(self.canvas_library)


__all__ = ["CanvasEnvironmentConfig"]
