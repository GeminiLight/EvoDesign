"""Public rendering facade for EvoDiagram canvas runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
    RenderPngResult,
    RenderResult,
    normalize_canvas_library,
)

from . import _render_engine_adapter


ANALYSIS_RENDER_SCALE = 1.0
"""Export scale for analysis renders: one image pixel = one manifest unit.

Analysis renders are the PNGs shown to VLM stages (refiner iterations) so
that distances measured on the image are directly manifest-unit quantities.
Pair with ``crop=False``: skipping the pixel-content smart crop keeps the
renderer's deterministic export framing, so the image origin no longer
drifts with detection noise between rounds. Product renders keep the
renderer defaults (magnified export + smart crop).
"""


def render_manifest(
    layout_instantiation: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    canvas_library: str = "excalidraw",
    output_dir: Optional[str] = None,
    viewport_width: int = CANVAS_DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
) -> RenderResult:
    """Build a canvas manifest from layout+structure and render a PNG.

    This is a render boundary, not the full quality gate. It validates the
    backend manifest shape and blocks a small set of render-time semantic
    losses; complete quality checks still belong to the verification/refiner
    workflows.
    """
    canvas_library = normalize_canvas_library(canvas_library)
    result = _render_engine_adapter.render_manifest(
        layout_instantiation=layout_instantiation,
        structure_instantiation=structure_instantiation,
        canvas_library=canvas_library,
        output_dir=output_dir,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    return RenderResult(
        manifest=result.manifest,
        png_path=result.png_path,
        manifest_path=result.manifest_path,
    )


def render_png_result(
    manifest: Dict[str, Any],
    output_path: str,
    canvas_library: str = "excalidraw",
    viewport_width: int = CANVAS_DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    *,
    render_scale: Optional[float] = None,
    crop: bool = True,
) -> RenderPngResult:
    """Render an existing canvas manifest to PNG and preserve failure detail.

    Defaults reproduce the product render (renderer-default export scale,
    smart crop on). Pass ``render_scale=ANALYSIS_RENDER_SCALE, crop=False``
    for the analysis render used as VLM refinement input: one image pixel
    equals one manifest unit and the exported canvas is kept whole, so
    measurements on the image are manifest-unit quantities and the framing
    is identical for identical content.
    """
    canvas_library = normalize_canvas_library(canvas_library)
    return _render_engine_adapter.render_png_result(
        manifest=manifest,
        output_path=output_path,
        canvas_library=canvas_library,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        render_scale=render_scale,
        crop=crop,
    )


def render_canvas(
    data: Union[Dict[str, Any], List[Any]],
    output_path: str = "output.png",
    canvas_library: str = "excalidraw",
    *,
    viewport_width: Optional[int] = None,
    viewport_height: Optional[int] = None,
) -> Dict[str, str]:
    """Render raw Excalidraw/TLDraw canvas data to an image file."""
    canvas_library = normalize_canvas_library(canvas_library)
    return _render_engine_adapter.render_canvas(
        data=data,
        output_path=output_path,
        canvas_library=canvas_library,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )


def render_canvas_file(
    input_path: str,
    output_path: str,
    canvas_library: str = "excalidraw",
    *,
    viewport_width: Optional[int] = None,
    viewport_height: Optional[int] = None,
) -> Dict[str, str]:
    """Render a canvas JSON file to an image file."""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Canvas JSON file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    canvas_library = normalize_canvas_library(canvas_library)
    return render_canvas(
        data=data,
        output_path=output_path,
        canvas_library=canvas_library,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )


__all__ = [
    "ANALYSIS_RENDER_SCALE",
    "RenderPngResult",
    "RenderResult",
    "render_manifest",
    "render_png_result",
    "render_canvas",
    "render_canvas_file",
]
