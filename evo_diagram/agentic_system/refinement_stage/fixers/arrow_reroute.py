"""Re-route Excalidraw arrows whose endpoint shapes moved or were resized.

An Excalidraw arrow carries no live link to the shapes it connects: its shape
is baked into the absolute ``x``/``y``/``points`` polyline the renderer wrote
once, at arrow-add time. ``op_set_position`` / ``op_set_size`` relocate a shape
and its bound label, and nothing else — so every geometry edit the refiner
applies silently detaches the arrows attached to that shape, while every
id-level binding stays perfectly intact.

Nothing in the refinement loop used to re-run edge routing (the render stage
owns ``arrow_adder`` / ``edge_router``, and the loop never calls back into it),
so the more the refiner moved, the more arrows broke — invisibly to the
verifier.

This module closes the loop by asking the canvas facade to redraw the arrow
from the new bounding boxes after each batch of edits. The facade runs the same
routing the arrow adder runs when it first draws an arrow, so a re-routed arrow
is indistinguishable from a freshly drawn one. Endpoint shapes are resolved the
same way the verifier's ``check_arrow_endpoint_geometry`` resolves them, so the
fixer and the check always agree on what "attached" means.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from evo_diagram.canvas_environment import route_arrow_between_bboxes
from evo_diagram.agentic_system.common.semantic_ids import id_map_from_manifest
from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
    ARROW_ENDPOINT_TOLERANCE_PX,
    arrow_absolute_endpoints,
    element_bbox,
    has_derived_bindings,
    point_gap_to_bbox,
    resolve_arrow_endpoint_shapes,
)

from .primitives import _bump_version

logger = logging.getLogger(__name__)

_BBox = Tuple[float, float, float, float]


def _as_route_bbox(bbox: _BBox) -> Dict[str, float]:
    x, y, w, h = bbox
    return {"x": x, "y": y, "w": w, "h": h}


def _infer_side(point: Tuple[float, float], bbox: _BBox) -> Optional[str]:
    """Which face of ``bbox`` the endpoint currently sits on, if any.

    Passed to the router as a *hint* so an arrow whose other end moved keeps
    the face it already used. The router honours a hint the new geometry still
    supports and otherwise picks the face from geometry; a same-side pair (both
    ends leaving through the same direction, i.e. a back edge routed as an
    outward U-turn) is preserved as given, so a back edge keeps its detour
    instead of collapsing into a straight line through its own source.
    """
    px, py = point
    x, y, w, h = bbox
    if point_gap_to_bbox(point, bbox) > ARROW_ENDPOINT_TOLERANCE_PX:
        return None
    distances = {
        "left": abs(px - x),
        "right": abs(px - (x + w)),
        "top": abs(py - y),
        "bottom": abs(py - (y + h)),
    }
    return min(distances, key=lambda side: distances[side])


def _arrow_label_elements(
    elements: List[Dict[str, Any]],
    arrow: Dict[str, Any],
) -> List[Dict[str, Any]]:
    arrow_id = arrow.get("id")
    bound_ids = {
        item.get("id")
        for item in (arrow.get("boundElements") or [])
        if isinstance(item, dict)
    }
    labels: List[Dict[str, Any]] = []
    for elem in elements:
        if not isinstance(elem, dict) or elem.get("type") != "text":
            continue
        if elem.get("containerId") == arrow_id or elem.get("id") in bound_ids:
            labels.append(elem)
    return labels


def _midpoint(
    endpoints: Tuple[Tuple[float, float], Tuple[float, float]],
) -> Tuple[float, float]:
    (sx, sy), (ex, ey) = endpoints
    return ((sx + ex) / 2.0, (sy + ey) / 2.0)


def reroute_bound_arrows(
    manifest: Dict[str, Any],
    *,
    canvas_library: str = "excalidraw",
    touched_ids: Optional[Iterable[str]] = None,
    tolerance: float = ARROW_ENDPOINT_TOLERANCE_PX,
) -> List[Dict[str, Any]]:
    """Recompute arrow geometry so arrows follow the shapes they connect.

    Parameters
    ----------
    canvas_library:
        Passed through to the canvas facade, which refuses to rewrite stored
        geometry for a backend without refinement support rather than silently
        producing Excalidraw-shaped output for it.
    touched_ids:
        Element ids whose position or size changed in this batch. Arrows
        attached to one of them are re-routed even when the drift is still
        within tolerance, because a move can flip which face the arrow should
        leave from without moving the endpoint much.
    tolerance:
        Endpoint-to-shape gap (px) treated as "still attached". Same constant
        the verifier's geometry check uses, so a re-route always clears the
        finding it was emitted for.

    Returns one record per re-routed arrow (empty list when nothing moved).
    Mutates ``manifest`` in place, like ``patch_schema_defaults``.
    """
    if not isinstance(manifest, dict) or has_derived_bindings(manifest):
        return []
    elements = manifest.get("elements")
    if not isinstance(elements, list):
        return []

    by_id: Dict[str, Dict[str, Any]] = {
        elem.get("id"): elem
        for elem in elements
        if isinstance(elem, dict) and elem.get("id") and not elem.get("isDeleted")
    }
    id_map = id_map_from_manifest(manifest)
    touched: Set[str] = {tid for tid in (touched_ids or []) if isinstance(tid, str)}

    rerouted: List[Dict[str, Any]] = []
    for arrow in elements:
        if not isinstance(arrow, dict) or arrow.get("isDeleted"):
            continue
        if arrow.get("type") != "arrow":
            continue

        endpoints = arrow_absolute_endpoints(arrow)
        if endpoints is None:
            continue
        start_shape, end_shape = resolve_arrow_endpoint_shapes(arrow, by_id, id_map)
        if start_shape is None or end_shape is None:
            # A half-anchored arrow has no second bbox to route against; the
            # verifier still reports the drifted side so it is not hidden.
            continue
        src_bbox = element_bbox(start_shape)
        tgt_bbox = element_bbox(end_shape)
        if src_bbox is None or tgt_bbox is None:
            continue

        start_gap = point_gap_to_bbox(endpoints[0], src_bbox)
        end_gap = point_gap_to_bbox(endpoints[1], tgt_bbox)
        shape_touched = (
            start_shape.get("id") in touched or end_shape.get("id") in touched
        )
        drifted = start_gap > tolerance or end_gap > tolerance
        if not (shape_touched or drifted):
            continue

        try:
            route = route_arrow_between_bboxes(
                _as_route_bbox(src_bbox),
                _as_route_bbox(tgt_bbox),
                canvas_library=canvas_library,
                start_side_hint=_infer_side(endpoints[0], src_bbox),
                end_side_hint=_infer_side(endpoints[1], tgt_bbox),
            )
        except (ValueError, TypeError, KeyError):
            logger.warning(
                "arrow re-route failed for %r; leaving its geometry untouched",
                arrow.get("id"),
                exc_info=True,
            )
            continue
        if len(route.absolute_points) < 2:
            continue

        old_mid = _midpoint(endpoints)
        arrow["x"] = route.x
        arrow["y"] = route.y
        arrow["points"] = route.points
        arrow["width"] = max(1.0, route.width)
        arrow["height"] = max(1.0, route.height)
        # Locked elbow segments describe the OLD polyline; keeping them would
        # fight the new one on re-import.
        arrow.pop("fixedSegments", None)
        _bump_version(arrow)

        new_endpoints = (
            (route.absolute_points[0][0], route.absolute_points[0][1]),
            (route.absolute_points[-1][0], route.absolute_points[-1][1]),
        )
        new_mid = _midpoint(new_endpoints)
        dx = new_mid[0] - old_mid[0]
        dy = new_mid[1] - old_mid[1]
        if dx or dy:
            for label in _arrow_label_elements(elements, arrow):
                try:
                    label["x"] = float(label.get("x", 0) or 0) + dx
                    label["y"] = float(label.get("y", 0) or 0) + dy
                except (TypeError, ValueError):
                    continue
                _bump_version(label)

        reason = (
            "endpoint shape moved"
            if shape_touched
            else f"endpoint drift {max(start_gap, end_gap):.0f}px"
        )
        rerouted.append(
            {
                "arrow_id": arrow.get("id"),
                "start_shape": start_shape.get("id"),
                "end_shape": end_shape.get("id"),
                "start_side": route.start_side,
                "end_side": route.end_side,
                "reason": reason,
            }
        )

    if rerouted:
        logger.info(
            "[ArrowReroute] recomputed geometry for %d arrow(s)", len(rerouted)
        )
    return rerouted


__all__ = ["reroute_bound_arrows"]
