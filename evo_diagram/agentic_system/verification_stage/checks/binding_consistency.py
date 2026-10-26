"""Arrow ↔ shape binding consistency — id level and geometry level.

For every Excalidraw arrow with `startBinding`/`endBinding`, the referenced
shape's `boundElements` MUST list the arrow id back. Mismatch causes visual
disconnects (arrows not following their endpoints when the shape is moved
in Excalidraw, or rendering glitches in headless export).

Also catches:
- arrow startBinding/endBinding pointing at non-existent element ids
- text element containerId pointing at non-existent shape
- shape boundElements listing arrow ids that no longer exist
- arrow endpoints that drifted away from the shape they connect
  (``check_arrow_endpoint_geometry``)

The id-level check alone is blind to the most common breakage: an Excalidraw
arrow's shape is baked into its absolute ``x``/``y``/``points`` polyline, so a
shape can be moved anywhere on the canvas while every id-level reference stays
perfectly intact and the drawn arrow points at empty space.

**Derived projections.** ``objective_manifest`` synthesises Excalidraw-shaped
bindings for TLDraw snapshots, including the very ``boundElements`` back-refs
the id-level check verifies. Verifying synthesised data is not verification, so
both the back-ref sub-check and the geometry check stand down on a projected
manifest and say so with an INFO finding instead of silently passing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from evo_diagram.agentic_system.common.semantic_ids import id_map_from_manifest

from .finding import Finding, Severity

# An arrow endpoint sits on the face of its shape, so any real gap is drift.
# The tolerance absorbs binding ``gap``, rounding, and stroke width.
ARROW_ENDPOINT_TOLERANCE_PX = 12.0

DERIVED_BINDINGS_META_KEY = "derived_bindings"


def has_derived_bindings(manifest: Any) -> bool:
    """True when arrow bindings in this manifest were synthesised by projection."""
    if not isinstance(manifest, Mapping):
        return False
    meta = manifest.get("_meta")
    if not isinstance(meta, Mapping):
        return False
    return bool(meta.get(DERIVED_BINDINGS_META_KEY))


def check_arrow_shape_binding(manifest: Dict[str, Any]) -> List[Finding]:
    """Verify arrow.{start,end}Binding ↔ shape.boundElements two-way."""
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings

    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return findings

    # On a projected manifest the back-refs were written by the projection a
    # few microseconds ago, so the sub-check can only ever pass. Report it as
    # NOT RUN rather than letting a MAJOR-severity check fail open.
    derived = has_derived_bindings(manifest)
    if derived:
        findings.append(
            Finding(
                category="binding/missing_back_ref/not_run",
                severity=Severity.INFO,
                message=(
                    "arrow→shape back-reference check did NOT run: this manifest "
                    "is a projection whose boundElements back-refs are derived "
                    "from the source binding records, so the check would verify "
                    "its own input. Native back-refs are not represented in this "
                    "canvas format."
                ),
            )
        )

    by_id: Dict[str, Dict[str, Any]] = {
        elem.get("id"): elem
        for elem in elements
        if isinstance(elem, dict) and elem.get("id") and not elem.get("isDeleted")
    }
    all_ids = set(by_id.keys())

    for elem in elements:
        if not isinstance(elem, dict):
            continue
        if elem.get("isDeleted"):
            continue

        eid = elem.get("id", "<no-id>")
        etype = elem.get("type")

        if etype == "arrow":
            for side in ("startBinding", "endBinding"):
                binding = elem.get(side)
                if not isinstance(binding, dict):
                    continue
                target_id = binding.get("elementId")
                if not target_id:
                    continue

                if target_id not in all_ids:
                    findings.append(
                        Finding(
                            category="binding/dangling_reference",
                            severity=Severity.CRITICAL,
                            message=(
                                f"arrow {eid!r} {side}.elementId={target_id!r} "
                                "references a non-existent element."
                            ),
                            element_id=eid,
                        )
                    )
                    continue

                target = by_id[target_id]
                bound = target.get("boundElements")
                back_refs = (
                    {b.get("id") for b in bound if isinstance(b, dict)}
                    if isinstance(bound, list)
                    else set()
                )
                if eid not in back_refs and not derived:
                    findings.append(
                        Finding(
                            category="binding/missing_back_ref",
                            severity=Severity.MAJOR,
                            message=(
                                f"arrow {eid!r} binds to shape {target_id!r} via "
                                f"{side}, but the shape's boundElements does not "
                                "list this arrow id back."
                            ),
                            element_id=eid,
                        )
                    )

        if etype == "text":
            container_id = elem.get("containerId")
            if container_id and container_id not in all_ids:
                findings.append(
                    Finding(
                        category="binding/dangling_reference",
                        severity=Severity.CRITICAL,
                        message=(
                            f"text {eid!r} containerId={container_id!r} "
                            "references a non-existent element."
                        ),
                        element_id=eid,
                        location={"missing_container_id": container_id},
                    )
                )

        bound = elem.get("boundElements")
        if isinstance(bound, list):
            for b in bound:
                if not isinstance(b, dict):
                    continue
                bid = b.get("id")
                if bid and bid not in all_ids:
                    findings.append(
                        Finding(
                            category="binding/dangling_reference",
                            severity=Severity.MAJOR,
                            message=(
                                f"element {eid!r} boundElements lists id={bid!r} "
                                "but no element with that id exists."
                            ),
                            element_id=eid,
                            location={
                                "holder_id": eid,
                                "missing_bound_id": bid,
                            },
                        )
                    )

    return findings


# ---------------------------------------------------------------------------
# Geometry-level: do the arrow's endpoints still touch the shapes it connects?
# ---------------------------------------------------------------------------


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def element_bbox(elem: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """``(x, y, w, h)`` of a shape, or None when it has no drawable extent."""
    try:
        x = float(elem.get("x", 0) or 0)
        y = float(elem.get("y", 0) or 0)
        w = float(elem.get("width", 0) or 0)
        h = float(elem.get("height", 0) or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def arrow_absolute_endpoints(
    arrow: Dict[str, Any],
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """First and last waypoint of an arrow in absolute canvas coordinates.

    Excalidraw stores ``points`` relative to the arrow's own ``x``/``y``.
    """
    points = arrow.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return None
    origin_x = _number(arrow.get("x"))
    origin_y = _number(arrow.get("y"))
    try:
        first = (origin_x + float(points[0][0]), origin_y + float(points[0][1]))
        last = (origin_x + float(points[-1][0]), origin_y + float(points[-1][1]))
    except (TypeError, ValueError, IndexError):
        return None
    return first, last


def point_gap_to_bbox(
    point: Tuple[float, float],
    bbox: Tuple[float, float, float, float],
) -> float:
    """Distance from ``point`` to the rectangle ``bbox``; 0.0 when inside."""
    px, py = point
    x, y, w, h = bbox
    dx = max(x - px, 0.0, px - (x + w))
    dy = max(y - py, 0.0, py - (y + h))
    return (dx * dx + dy * dy) ** 0.5


def resolve_arrow_endpoint_shapes(
    arrow: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    id_map: Optional[Mapping[str, str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Best-effort ``(start_shape, end_shape)`` for one arrow.

    Two sources, in priority order:

    1. ``startBinding`` / ``endBinding`` — authoritative when present.
    2. ``meta.source`` / ``meta.target`` — the semantic endpoint refs the
       renderer's arrow adder stamps on every arrow it emits. The Excalidraw
       arrow adder does not write start/end bindings at all, so without this
       fallback the geometry check would be dead code on real pipeline output.
    """
    id_map = id_map or {}

    def _by_binding(side: str) -> Optional[Dict[str, Any]]:
        binding = arrow.get(f"{side}Binding")
        if not isinstance(binding, dict):
            return None
        target_id = binding.get("elementId")
        if not isinstance(target_id, str):
            return None
        return by_id.get(target_id)

    def _by_semantic_ref(key: str) -> Optional[Dict[str, Any]]:
        meta = arrow.get("meta")
        if not isinstance(meta, Mapping):
            return None
        ref = meta.get(key)
        if not isinstance(ref, str) or not ref:
            return None
        # Sequence messages terminate on lifelines below their headers. Keep
        # checking real endpoint geometry, using the line only when its actor
        # ownership is explicit and consistent with the semantic endpoint.
        if "sequence_idx" in meta:
            lifeline = by_id.get(id_map.get(f"{ref}:lifeline", ""))
            if (lifeline and lifeline.get("type") == "line"
                    and (lifeline.get("meta") or {}).get("actor_id") == ref):
                return lifeline
        for candidate in (
            by_id.get(ref),
            by_id.get(id_map.get(ref, "")),
            by_id.get(id_map.get(f"{ref}:background", "")),
        ):
            if candidate is not None:
                return candidate
        return None

    start = _by_binding("start") or _by_semantic_ref("source")
    end = _by_binding("end") or _by_semantic_ref("target")
    return start, end


def _binding_gap(arrow: Dict[str, Any], side: str) -> float:
    binding = arrow.get(f"{side}Binding")
    if isinstance(binding, dict):
        return max(0.0, _number(binding.get("gap")))
    return 0.0


def check_arrow_endpoint_geometry(
    manifest: Dict[str, Any],
    tolerance: float = ARROW_ENDPOINT_TOLERANCE_PX,
) -> List[Finding]:
    """Report arrows whose endpoints no longer touch the shapes they connect.

    ``check_arrow_shape_binding`` only compares ids, so a shape that gets moved
    or resized leaves every reference intact while the arrow keeps pointing at
    the shape's former location. Without this check the verifier gets *cleaner*
    the more the refiner moves things, and a diagram with detached arrows is
    promoted as converged.
    """
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings

    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return findings

    if has_derived_bindings(manifest):
        return [
            Finding(
                category="binding/arrow_endpoint_drift/not_run",
                severity=Severity.INFO,
                message=(
                    "arrow endpoint geometry check did NOT run: this manifest is "
                    "a projection whose arrow polyline is reconstructed from "
                    "canvas-native anchors rather than stored waypoints, so a "
                    "gap here would not mean the same thing."
                ),
            )
        ]

    by_id: Dict[str, Dict[str, Any]] = {
        elem.get("id"): elem
        for elem in elements
        if isinstance(elem, dict) and elem.get("id") and not elem.get("isDeleted")
    }
    id_map = id_map_from_manifest(manifest)

    for elem in elements:
        if not isinstance(elem, dict) or elem.get("isDeleted"):
            continue
        if elem.get("type") != "arrow":
            continue
        endpoints = arrow_absolute_endpoints(elem)
        if endpoints is None:
            continue
        start_shape, end_shape = resolve_arrow_endpoint_shapes(elem, by_id, id_map)
        start_bbox = element_bbox(start_shape) if start_shape else None
        end_bbox = element_bbox(end_shape) if end_shape else None
        arrow_id = elem.get("id", "<no-id>")

        # Re-routing needs a usable bbox at BOTH ends. When only one end can be
        # resolved the drift is real but nothing can repair it, and a permanent
        # MAJOR would stop the refiner converging and get the whole refined
        # artifact thrown away. Report it, do not make it blocking.
        repairable = start_bbox is not None and end_bbox is not None

        for side, point, shape, bbox in (
            ("start", endpoints[0], start_shape, start_bbox),
            ("end", endpoints[1], end_shape, end_bbox),
        ):
            if shape is None or bbox is None:
                continue
            gap = point_gap_to_bbox(point, bbox) - _binding_gap(elem, side)
            if gap <= tolerance:
                continue
            hint = (
                ""
                if repairable
                else " Its other endpoint cannot be resolved to a shape, so the "
                "re-route pass cannot repair this automatically."
            )
            findings.append(
                Finding(
                    category="binding/arrow_endpoint_drift",
                    severity=Severity.MAJOR if repairable else Severity.MINOR,
                    message=(
                        f"arrow {arrow_id!r} {side} point "
                        f"({point[0]:.0f},{point[1]:.0f}) is {gap:.0f}px away from "
                        f"shape {shape.get('id')!r} bbox=({bbox[0]:.0f},"
                        f"{bbox[1]:.0f},{bbox[2]:.0f}x{bbox[3]:.0f}); the arrow no "
                        f"longer touches the element it connects.{hint}"
                    ),
                    element_id=arrow_id,
                    location={
                        "side": side,
                        "shape_id": shape.get("id"),
                        "point": [point[0], point[1]],
                        "shape_bbox": list(bbox),
                        "gap": gap,
                        "repairable": repairable,
                    },
                )
            )

    return findings


__all__ = [
    "ARROW_ENDPOINT_TOLERANCE_PX",
    "DERIVED_BINDINGS_META_KEY",
    "arrow_absolute_endpoints",
    "check_arrow_endpoint_geometry",
    "check_arrow_shape_binding",
    "element_bbox",
    "has_derived_bindings",
    "point_gap_to_bbox",
    "resolve_arrow_endpoint_shapes",
]
