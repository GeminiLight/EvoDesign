"""Private adapter to the legacy agentic render engine.

The public ``canvas_environment`` package is the stable boundary. The current
implementation still delegates to ``agentic_system.render_engine``; keeping all
of those imports here makes that transitional dependency explicit and avoids
spreading legacy render-engine paths across the facade modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set


def excalidraw_element_defaults(seed: Any) -> Dict[str, Any]:
    from evo_diagram.agentic_system.render_engine.excalidraw.converter import _excalidraw_defaults

    return _excalidraw_defaults(seed)


def rebuild_excalidraw_arrows(
    manifest: Dict[str, Any], structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
        rebuild_excalidraw_arrows as rebuild,
    )

    return rebuild(manifest, structure_instantiation)


def compact_architecture_layout(
    manifest: Dict[str, Any], structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    from evo_diagram.agentic_system.render_engine.excalidraw.layered_layout_compactor import (
        compact_architecture_layout as compact,
    )

    return compact(manifest, structure_instantiation)


def normalize_architecture_style(
    manifest: Dict[str, Any], structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    from evo_diagram.agentic_system.render_engine.excalidraw.architecture_style_normalizer import (
        normalize_architecture_style as normalize,
    )

    return normalize(manifest, structure_instantiation)


def disjoint_segment_box_distance(
    start: Sequence[float], end: Sequence[float], box: Sequence[float],
) -> float:
    from evo_diagram.agentic_system.render_engine.shared.label_geometry import (
        disjoint_segment_box_distance as distance,
    )

    return distance(start, end, box)


def color_contrast_ratio(color_a: str, color_b: str) -> Optional[float]:
    from evo_diagram.agentic_system.render_engine.shared.render_audit import _contrast_ratio

    return _contrast_ratio(color_a, color_b)


def render_manifest(
    *,
    layout_instantiation: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    canvas_library: str,
    output_dir: Optional[str],
    viewport_width: int,
    viewport_height: int,
) -> Any:
    from evo_diagram.agentic_system.render_engine import service

    return service.render_manifest(
        layout_instantiation=layout_instantiation,
        structure_instantiation=structure_instantiation,
        canvas_library=canvas_library,
        output_dir=output_dir,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )


def render_png_result(
    *,
    manifest: Dict[str, Any],
    output_path: str,
    canvas_library: str,
    viewport_width: int,
    viewport_height: int,
    render_scale: Optional[float] = None,
    crop: bool = True,
):
    from evo_diagram.agentic_system.render_engine import service

    return service.render_png_result(
        manifest=manifest,
        output_path=output_path,
        canvas_library=canvas_library,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        render_scale=render_scale,
        crop=crop,
    )


def render_canvas(
    *,
    data: Any,
    output_path: str,
    canvas_library: str,
    viewport_width: Optional[int],
    viewport_height: Optional[int],
) -> Dict[str, str]:
    from evo_diagram.agentic_system.render_engine import canvas_render

    return canvas_render.render_canvas(
        data=data,
        output_path=output_path,
        canvas_library=canvas_library,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )


def normalize_excalidraw_manifest(manifest: Dict[str, Any]) -> None:
    from evo_diagram.agentic_system.render_engine.excalidraw.normalizer import (
        normalize_excalidraw_manifest as _normalize_excalidraw_manifest,
    )

    _normalize_excalidraw_manifest(manifest)


def validate_excalidraw_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    from evo_diagram.agentic_system.render_engine.excalidraw.validator import (
        validate_excalidraw_manifest as _validate_excalidraw_manifest,
    )

    return _validate_excalidraw_manifest(manifest_data=manifest)


def validate_tldraw_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    from evo_diagram.agentic_system.render_engine.tldraw.validator import (
        validate_tldraw_manifest as _validate_tldraw_manifest,
    )

    return _validate_tldraw_manifest(manifest_data=manifest)


def audit_excalidraw_manifest(
    manifest: Dict[str, Any],
    *,
    structure_instantiation: Optional[Dict[str, Any]],
) -> Any:
    from evo_diagram.agentic_system.render_engine.shared.render_audit import (
        audit_excalidraw_manifest as _audit_excalidraw_manifest,
    )

    return _audit_excalidraw_manifest(
        manifest,
        structure_instantiation=structure_instantiation,
    )


def audit_tldraw_manifest(
    manifest: Dict[str, Any],
    *,
    structure_instantiation: Optional[Dict[str, Any]],
) -> Any:
    from evo_diagram.agentic_system.render_engine.shared.render_audit import (
        audit_tldraw_manifest as _audit_tldraw_manifest,
    )

    return _audit_tldraw_manifest(
        manifest,
        structure_instantiation=structure_instantiation,
    )


def audit_layout_instantiation(
    layout_instantiation: Dict[str, Any],
    structure_instantiation: Optional[Dict[str, Any]],
) -> list[str]:
    from evo_diagram.agentic_system.render_engine.shared.render_audit import (
        audit_layout_instantiation as _audit_layout_instantiation,
    )

    return _audit_layout_instantiation(
        layout_instantiation,
        structure_instantiation,
    )


def repair_excalidraw_zorder(manifest: Dict[str, Any]) -> Dict[str, Any]:
    from evo_diagram.agentic_system.render_engine.excalidraw import zorder_repair

    return zorder_repair.repair_zorder(manifest)


def detect_group_frame_ids(
    elements: List[Dict[str, Any]],
    *,
    structural: bool,
    id_map: Optional[Mapping[str, Any]],
) -> Set[str]:
    from evo_diagram.agentic_system.render_engine.shared.normalization import (
        detect_group_frame_ids as _detect_group_frame_ids,
    )

    return _detect_group_frame_ids(
        elements,
        structural=structural,
        id_map=id_map,
    )


def route_excalidraw_arrow(
    *,
    source_bbox: Mapping[str, float],
    target_bbox: Mapping[str, float],
    start_side_hint: Optional[str],
    end_side_hint: Optional[str],
) -> Dict[str, Any]:
    """Recompute one Excalidraw arrow polyline from its endpoint bounding boxes.

    Runs the same three steps the arrow adder runs when it first draws an
    arrow — face selection, waypoint computation, conversion to the element's
    origin-relative form — so a re-routed arrow is indistinguishable from a
    freshly drawn one.
    """
    from evo_diagram.agentic_system.render_engine.excalidraw.edge_router import (
        compute_waypoints,
        to_relative_points,
        waypoints_bbox,
    )
    from evo_diagram.agentic_system.render_engine.shared.edge_routing import audit_sides

    source_shape = {
        "x": float(source_bbox["x"]),
        "y": float(source_bbox["y"]),
        "width": float(source_bbox["w"]),
        "height": float(source_bbox["h"]),
    }
    target_shape = {
        "x": float(target_bbox["x"]),
        "y": float(target_bbox["y"]),
        "width": float(target_bbox["w"]),
        "height": float(target_bbox["h"]),
    }
    hinted = None
    if start_side_hint or end_side_hint:
        hinted = {"start": start_side_hint, "end": end_side_hint}

    start_side, end_side = audit_sides(hinted, source_shape, target_shape)
    waypoints, _focus_start, _focus_end = compute_waypoints(
        start_side,
        end_side,
        dict(source_bbox),
        dict(target_bbox),
    )
    origin_x, origin_y, relative_points = to_relative_points(waypoints)
    width, height = waypoints_bbox(waypoints)
    return {
        "x": origin_x,
        "y": origin_y,
        "width": width,
        "height": height,
        "points": relative_points,
        "absolute_points": [
            [float(point["x"]), float(point["y"])] for point in waypoints
        ],
        "start_side": start_side,
        "end_side": end_side,
    }


def validate_png_file(output_file: Path, *, context: str) -> None:
    from evo_diagram.agentic_system.render_engine.shared.png_validation import (
        validate_png_file as _validate_png_file,
    )

    _validate_png_file(output_file, context=context)


__all__ = [
    "render_manifest",
    "render_png_result",
    "render_canvas",
    "normalize_excalidraw_manifest",
    "validate_excalidraw_manifest",
    "validate_tldraw_manifest",
    "audit_excalidraw_manifest",
    "audit_tldraw_manifest",
    "audit_layout_instantiation",
    "repair_excalidraw_zorder",
    "detect_group_frame_ids",
    "route_excalidraw_arrow",
    "validate_png_file",
]
