"""Low-level canvas runtime contract shared across EvoDiagram surfaces.

This module intentionally has no dependency on ``canvas_environment`` or
``agentic_system``. It is safe for legacy render code, facade modules, backend
adapters, and verification checks to import without re-entering higher-level
runtime packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


VALID_CANVAS_LIBRARIES = ("tldraw", "excalidraw")

CANVAS_MAX_X: float = 4000.0
CANVAS_MAX_Y: float = 4000.0
CANVAS_MARGIN: float = 16.0

CANVAS_DEFAULT_VIEWPORT_WIDTH: int = 4000
CANVAS_DEFAULT_VIEWPORT_HEIGHT: int = 4000


@dataclass
class RenderResult:
    """Output of canvas manifest rendering."""

    manifest: Dict[str, Any]
    png_path: str
    manifest_path: str


@dataclass
class RenderPngResult:
    """Outcome of rendering an existing manifest to PNG."""

    ok: bool
    output_path: str
    error: str = ""


def normalize_canvas_library(canvas_library: str) -> str:
    """Normalize and validate a canvas backend name."""
    canvas = str(canvas_library).strip().lower()
    if canvas not in VALID_CANVAS_LIBRARIES:
        raise ValueError(
            f"Unknown canvas_library: {canvas_library!r}. "
            f"Use one of: {', '.join(VALID_CANVAS_LIBRARIES)}."
        )
    return canvas


__all__ = [
    "CANVAS_MARGIN",
    "CANVAS_MAX_X",
    "CANVAS_MAX_Y",
    "CANVAS_DEFAULT_VIEWPORT_HEIGHT",
    "CANVAS_DEFAULT_VIEWPORT_WIDTH",
    "RenderPngResult",
    "RenderResult",
    "VALID_CANVAS_LIBRARIES",
    "normalize_canvas_library",
]
