"""Shared render service — layout+structure → manifest JSON + PNG.

Wraps RenderWorkflow (LangGraph pipeline) + render_canvas into a single
callable. Used by both the main orchestrator (Phase 2) and the refiner
(re-render between iterations).
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
    RenderPngResult,
    RenderResult,
    normalize_canvas_library,
)

from .canvas_render import render_canvas
from .shared.png_validation import validate_png_file
from .state import WorkflowState as RenderWorkflowState
from .workflow import RenderWorkflow

logger = logging.getLogger(__name__)


def _ensure_valid_png(path: Path, *, context: str) -> None:
    validate_png_file(path, context=context)


def render_manifest(
    layout_instantiation: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    canvas_library: str = "excalidraw",
    output_dir: Optional[str] = None,
    viewport_width: int = CANVAS_DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
) -> RenderResult:
    """Build manifest from layout+structure, then render to PNG.

    Args:
        layout_instantiation: Positioned elements from layout workflow.
        structure_instantiation: Semantic graph from structure workflow.
        canvas_library: "excalidraw" or "tldraw".
        output_dir: Directory to write manifest JSON and PNG. If None,
            files are written to a unique temp directory owned by the caller.
        viewport_width: Render viewport width in pixels.
        viewport_height: Render viewport height in pixels.

    Returns:
        RenderResult with manifest dict, png_path, and manifest_path.
    """
    canvas_library = normalize_canvas_library(canvas_library)

    # --- Phase 1: build manifest via RenderWorkflow ---
    render_wf = RenderWorkflow(canvas_library=canvas_library)
    render_state = RenderWorkflowState(
        structure_instantiation=structure_instantiation,
        layout_instantiation=layout_instantiation,
        canvas_library=canvas_library,
    )
    render_state = render_wf.run(render_state)

    manifest = render_state.diagram_manifest
    if not manifest:
        raise RuntimeError("RenderWorkflow produced no diagram_manifest")

    # --- Phase 2: save manifest + render PNG ---
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="evodiagram-render-")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest_path = str(out / "diagram_manifest.json")
    png_path = str(out / "diagram_manifest.png")

    # Save manifest JSON
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    logger.info(f"Manifest saved to {manifest_path}")

    # Save .excalidraw file for Excalidraw canvas library
    if canvas_library == "excalidraw":
        from copy import deepcopy

        excalidraw_manifest = deepcopy(manifest)
        excalidraw_manifest.pop("_meta", None)
        excalidraw_manifest.update(type="excalidraw", version=2)
        excalidraw_path = str(out / "rendered_diagram.excalidraw")
        with open(excalidraw_path, "w", encoding="utf-8") as f:
            json.dump(excalidraw_manifest, f, indent=2, ensure_ascii=False)

    # Render to PNG
    render_canvas(
        data=manifest,
        output_path=png_path,
        canvas_library=canvas_library,
        capture_output=True,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    _ensure_valid_png(Path(png_path), context="render_manifest")
    logger.info(f"PNG rendered to {png_path}")

    return RenderResult(
        manifest=manifest,
        png_path=png_path,
        manifest_path=manifest_path,
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
    """Render an existing manifest dict to PNG and preserve failure detail.

    Used by the refiner for re-rendering between iterations. Defaults
    reproduce the product render (renderer-default export scale, smart
    crop on); pass ``render_scale=1.0, crop=False`` for the analysis
    render consumed by VLM stages.
    """
    canvas_library = normalize_canvas_library(canvas_library)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        render_canvas(
            data=manifest,
            output_path=str(out),
            canvas_library=canvas_library,
            capture_output=True,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            render_scale=render_scale,
            crop=crop,
        )
    except Exception as exc:
        logger.warning(f"render_png_result({output_path}) failed: {exc}")
        return RenderPngResult(
            ok=False,
            output_path=str(out),
            error=f"{type(exc).__name__}: {exc}",
        )

    try:
        _ensure_valid_png(out, context="render_png_result")
    except RuntimeError as exc:
        logger.warning(str(exc))
        return RenderPngResult(
            ok=False,
            output_path=str(out),
            error=f"{type(exc).__name__}: {exc}",
        )

    return RenderPngResult(ok=True, output_path=str(out))
