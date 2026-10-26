"""Shared canvas runtime identifiers."""

from __future__ import annotations

from typing import Literal, cast


CanvasLibrary = Literal["excalidraw", "tldraw"]
SUPPORTED_CANVAS_LIBRARIES: tuple[CanvasLibrary, ...] = ("excalidraw", "tldraw")
SUPPORTED_REFINER_CANVAS_LIBRARIES: tuple[CanvasLibrary, ...] = ("excalidraw",)


def normalize_canvas_library_value(canvas_library: object) -> CanvasLibrary:
    """Normalize and validate a supported canvas library identifier."""
    canvas = str(canvas_library).strip().lower()
    if canvas not in SUPPORTED_CANVAS_LIBRARIES:
        raise ValueError(f"Unsupported canvas library: {canvas_library}")
    return cast(CanvasLibrary, canvas)


def canvas_library_supports_refiner(canvas_library: object) -> bool:
    """Return whether backend workflow runtime may run iterative refinement."""
    return (
        normalize_canvas_library_value(canvas_library)
        in SUPPORTED_REFINER_CANVAS_LIBRARIES
    )
