"""Edge-geometry facade for canvas manifests.

Arrow shape is backend-specific: an Excalidraw arrow bakes its path into an
absolute ``x``/``y`` plus an origin-relative ``points`` polyline, so any
consumer that moves a shape has to ask the canvas backend to redraw the arrows
attached to it. This module exposes that one capability as a public, backend
neutral call, keeping the routing math itself inside the render engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from evo_diagram.canvas_runtime import normalize_canvas_library

from . import _render_engine_adapter
from .capabilities import get_canvas_capabilities

# Sides an arrow may leave from / arrive at. Anything else is treated as "no
# hint" rather than an error: a hint is advisory by definition.
ARROW_SIDES = ("top", "bottom", "left", "right")


@dataclass(frozen=True)
class ArrowRouteGeometry:
    """Backend-neutral geometry for one re-routed arrow.

    ``points`` are relative to ``(x, y)`` — the element storage form —
    while ``absolute_points`` are canvas coordinates, which is what a caller
    needs to reposition anything riding along the arrow (an edge label, say).
    """

    x: float
    y: float
    width: float
    height: float
    points: List[List[float]]
    absolute_points: List[List[float]]
    start_side: str
    end_side: str


def _normalize_side(side: Optional[str]) -> Optional[str]:
    if isinstance(side, str) and side in ARROW_SIDES:
        return side
    return None


def _as_bbox(bbox: Mapping[str, Any]) -> dict[str, float]:
    return {
        "x": float(bbox["x"]),
        "y": float(bbox["y"]),
        "w": float(bbox["w"]),
        "h": float(bbox["h"]),
    }


def route_arrow_between_bboxes(
    source_bbox: Mapping[str, Any],
    target_bbox: Mapping[str, Any],
    *,
    canvas_library: str = "excalidraw",
    start_side_hint: Optional[str] = None,
    end_side_hint: Optional[str] = None,
) -> ArrowRouteGeometry:
    """Recompute an arrow's geometry from the bboxes of the shapes it connects.

    Both bboxes are ``{"x", "y", "w", "h"}`` in canvas units. The optional side
    hints name the face each end currently uses; the backend keeps a hint when
    the new geometry still supports it and picks the face from geometry
    otherwise.

    Only canvases whose capability matrix marks the refiner as supported can be
    routed here: re-routing rewrites stored element geometry, and doing that
    against a backend the refinement primitives were never validated on would
    corrupt the manifest rather than repair it.
    """
    canvas_library = normalize_canvas_library(canvas_library)
    capabilities = get_canvas_capabilities(canvas_library)
    if not capabilities.supports_refiner:
        raise NotImplementedError(
            "route_arrow_between_bboxes rewrites stored arrow geometry and is "
            "only available for canvases with refinement support; "
            f"canvas_library={capabilities.canvas_library!r} does not have it."
        )

    result = _render_engine_adapter.route_excalidraw_arrow(
        source_bbox=_as_bbox(source_bbox),
        target_bbox=_as_bbox(target_bbox),
        start_side_hint=_normalize_side(start_side_hint),
        end_side_hint=_normalize_side(end_side_hint),
    )
    return ArrowRouteGeometry(
        x=float(result["x"]),
        y=float(result["y"]),
        width=float(result["width"]),
        height=float(result["height"]),
        points=[[float(px), float(py)] for px, py in result["points"]],
        absolute_points=[
            [float(px), float(py)] for px, py in result["absolute_points"]
        ],
        start_side=str(result["start_side"]),
        end_side=str(result["end_side"]),
    )


__all__ = [
    "ARROW_SIDES",
    "ArrowRouteGeometry",
    "route_arrow_between_bboxes",
]
