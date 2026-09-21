"""Geometric collision detection: node overlap and edge path defects.

These two checks are pure pixel-math: they don't depend on chart_type or any
LLM output, and complement the structural checks in render_validation /
binding_consistency.

**Node overlap** — two non-arrow shapes whose bboxes intersect, EXCLUDING:
- group ⊃ child (legitimate containment)
- text ⊂ shape (bound label inside its container)
- shape inside its own group background

**Edge crossings** — pairs of arrow segments that cross. Reported only as
INFO unless the count exceeds a threshold (then MINOR), since some crossings
are unavoidable.

**Edge-node intersections** — an arrow path entering a non-endpoint node is a
MAJOR visual defect. The source and target shapes are excluded because the
path intentionally terminates on their faces.

Out-of-canvas: shape bbox outside the configured safe area
`[CANVAS_MARGIN, MAX_CANVAS-CANVAS_MARGIN]`. Reported as MINOR.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from evo_diagram.canvas_environment import (
    CANVAS_MARGIN,
    CANVAS_MAX_X,
    CANVAS_MAX_Y,
    detect_group_frame_ids,
)
from evo_diagram.agentic_system.common.semantic_ids import id_map_from_manifest
from .finding import Finding, Severity

_OVERLAP_TOLERANCE_PX = 2  # ignore touching edges
_EDGE_CROSSING_INFO_THRESHOLD = 0  # 0..N crossings → INFO
_EDGE_CROSSING_MINOR_THRESHOLD = 4  # >N crossings → MINOR


def _is_fully_transparent(elem: Dict[str, Any]) -> bool:
    """Return whether an element is intentionally absent from the visual surface."""
    try:
        return float(elem.get("opacity", 100)) <= 0
    except (TypeError, ValueError):
        return False


def _bbox(elem: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    try:
        x = float(elem.get("x", 0) or 0)
        y = float(elem.get("y", 0) or 0)
        w = float(elem.get("width", 0) or 0)
        h = float(elem.get("height", 0) or 0)
    except (TypeError, ValueError):
        return None
    return (x, y, w, h)


def _bboxes_overlap(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
    tol: float = _OVERLAP_TOLERANCE_PX,
) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return not (
        ax + aw <= bx + tol
        or bx + bw <= ax + tol
        or ay + ah <= by + tol
        or by + bh <= ay + tol
    )


def _segments_intersect(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    p4: Tuple[float, float],
) -> bool:
    """Standard 2D segment-segment intersection test (proper crossings only)."""

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    return False


def _arrow_segments(elem: Dict[str, Any]) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """All consecutive waypoint segments of an Excalidraw arrow in screen space.

    Excalidraw arrows are multi-segment polylines (orthogonal routing).
    A 4-point arrow ``[(0,0), (0,40), (300,40), (300,80)]`` is three Z-shape
    segments, NOT a single diagonal line. Treating an arrow as just
    ``points[0] → points[-1]`` produces both false positives (the chord
    crosses what the actual zig-zag avoids) and false negatives (a Z-bend
    crosses something the chord misses).
    """
    try:
        x0 = float(elem.get("x", 0) or 0)
        y0 = float(elem.get("y", 0) or 0)
    except (TypeError, ValueError):
        return []

    points = elem.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return []

    abs_pts: List[Tuple[float, float]] = []
    for p in points:
        try:
            abs_pts.append((x0 + float(p[0]), y0 + float(p[1])))
        except (TypeError, ValueError, IndexError):
            return []

    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for i in range(len(abs_pts) - 1):
        a, b = abs_pts[i], abs_pts[i + 1]
        if a == b:
            continue   # zero-length segment, ignore
        segments.append((a, b))
    return segments


def _segment_intersects_rect_interior(
    start: Tuple[float, float],
    end: Tuple[float, float],
    bbox: Tuple[float, float, float, float],
    epsilon: float = 1e-6,
) -> bool:
    """Return whether a segment enters the strict interior of a rectangle."""
    x, y, width, height = bbox
    if width <= 0 or height <= 0:
        return False

    # Liang-Barsky clipping against a slightly inset rectangle.  Insetting
    # avoids treating a path that merely touches a node border as an overlap.
    left = x + epsilon
    right = x + width - epsilon
    top = y + epsilon
    bottom = y + height - epsilon
    if left >= right or top >= bottom:
        return False

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    t_enter, t_exit = 0.0, 1.0
    for p, q in (
        (-dx, start[0] - left),
        (dx, right - start[0]),
        (-dy, start[1] - top),
        (dy, bottom - start[1]),
    ):
        if abs(p) <= epsilon:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            t_enter = max(t_enter, ratio)
        else:
            t_exit = min(t_exit, ratio)
        if t_enter >= t_exit:
            return False
    return t_enter < t_exit and t_exit > epsilon and t_enter < 1.0 - epsilon


def _arrow_endpoint_ids(
    arrow: Dict[str, Any],
    id_map: Dict[str, str],
) -> Dict[str, set[str]]:
    """Resolve semantic or direct endpoint references by endpoint role."""
    endpoint_ids: Dict[str, set[str]] = {"source": set(), "target": set()}
    for binding_key, role in (("startBinding", "source"), ("endBinding", "target")):
        binding = arrow.get(binding_key)
        if isinstance(binding, dict) and binding.get("elementId"):
            endpoint_ids[role].add(str(binding["elementId"]))

    metadata = arrow.get("meta")
    if not isinstance(metadata, dict):
        metadata = arrow.get("_meta")
    if isinstance(metadata, dict):
        for key in ("source", "target"):
            ref = metadata.get(key)
            if ref is not None:
                ref = str(ref)
                endpoint_ids[key].add(str(id_map.get(ref, ref)))
    return endpoint_ids


def _segment_tracks_border(
    start: Tuple[float, float], end: Tuple[float, float],
    bbox: Tuple[float, float, float, float], clearance: float,
) -> bool:
    """Detect a visible parallel run along an unrelated node border."""
    x, y, width, height = bbox
    if abs(start[1] - end[1]) <= 1e-6:
        overlap = min(max(start[0], end[0]), x + width) - max(min(start[0], end[0]), x)
        distance = min(abs(start[1] - y), abs(start[1] - y - height))
    elif abs(start[0] - end[0]) <= 1e-6:
        overlap = min(max(start[1], end[1]), y + height) - max(min(start[1], end[1]), y)
        distance = min(abs(start[0] - x), abs(start[0] - x - width))
    else:
        return False
    return overlap >= 12.0 and distance < clearance


def check_edge_node_intersections(
    manifest: Dict[str, Any], node_clearance: float = 0.0,
) -> List[Finding]:
    """Report node crossings and optionally ambiguous parallel border runs."""
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return findings

    id_map = {}
    meta = manifest.get("_meta")
    if isinstance(meta, dict) and isinstance(meta.get("id_map"), dict):
        id_map = {str(key): str(value) for key, value in meta["id_map"].items()}
    background_ids = detect_group_frame_ids(
        [elem for elem in elements if isinstance(elem, dict)],
        structural=True,
        id_map=id_map,
    )
    candidates: List[Tuple[str, Tuple[float, float, float, float]]] = []
    for elem in elements:
        if not isinstance(elem, dict) or elem.get("isDeleted"):
            continue
        if elem.get("type") in {"arrow", "text", "image", "line", "freedraw"}:
            continue
        element_id = elem.get("id")
        if not element_id or element_id in background_ids:
            continue
        bbox = _bbox(elem)
        if bbox is not None:
            candidates.append((str(element_id), bbox))

    for arrow in elements:
        if not isinstance(arrow, dict) or arrow.get("isDeleted") or arrow.get("type") != "arrow":
            continue
        if _is_fully_transparent(arrow):
            continue
        arrow_id = str(arrow.get("id", "<no-id>"))
        endpoint_ids = _arrow_endpoint_ids(arrow, id_map)
        segments = _arrow_segments(arrow)
        for node_id, bbox in candidates:
            indexes = list(range(len(segments)))
            if node_id in endpoint_ids["source"]:
                indexes = [index for index in indexes if index != 0]
            if node_id in endpoint_ids["target"]:
                indexes = [index for index in indexes if index != len(segments) - 1]
            hit_segment = next(
                (
                    index
                    for index in indexes
                    for segment in [segments[index]]
                    if _segment_intersects_rect_interior(segment[0], segment[1], bbox)
                ),
                None,
            )
            if hit_segment is None:
                if node_clearance > 0 and node_id not in endpoint_ids["source"] | endpoint_ids["target"]:
                    border_segment = next((
                        index for index, (start, end) in enumerate(segments)
                        if _segment_tracks_border(start, end, bbox, node_clearance)
                    ), None)
                    if border_segment is not None:
                        findings.append(Finding(
                            category="collision/edge_node_clearance",
                            severity=Severity.MAJOR,
                            message=(
                                f"arrow {arrow_id!r} runs along unrelated node {node_id!r} "
                                f"on segment {border_segment}; leave at least {node_clearance:g}px "
                                "so the line does not imply an extra connection."
                            ),
                            element_id=arrow_id,
                            location={"node_id": node_id, "segment_index": border_segment, "bbox": list(bbox)},
                        ))
                continue
            findings.append(
                Finding(
                    category="collision/edge_node_intersection",
                    severity=Severity.MAJOR,
                    message=(
                        f"arrow {arrow_id!r} enters node {node_id!r} on segment "
                        f"{hit_segment}; only the first source segment and final "
                        "target segment may touch endpoint nodes."
                    ),
                    element_id=arrow_id,
                    location={"node_id": node_id, "segment_index": hit_segment, "bbox": list(bbox)},
                )
            )
    return findings


def check_edge_node_clearance(manifest: Dict[str, Any]) -> List[Finding]:
    """Report sustained near-border routes that imply unrelated connections."""
    return [
        finding for finding in check_edge_node_intersections(manifest, node_clearance=4.0)
        if finding.category == "collision/edge_node_clearance"
    ]


def check_node_overlap(manifest: Dict[str, Any]) -> List[Finding]:
    """Pairs of shape bboxes that overlap when neither contains the other."""
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings

    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return findings

    # Identify group/frame background containers & bound text containers —
    # they are allowed to enclose other shapes legitimately. Support both
    # explicit ":background" semantic ids and the common Excalidraw group/frame
    # semantic id convention prefixed with "g_"; also support direct group
    # frames that are marked by a sibling title entry.
    idm = id_map_from_manifest(manifest)
    background_ids = detect_group_frame_ids(
        [elem for elem in elements if isinstance(elem, dict)],
        structural=True,
        id_map=idm,
    )

    candidates: List[Tuple[str, Tuple[float, float, float, float], Dict[str, Any]]] = []
    for elem in elements:
        if not isinstance(elem, dict):
            continue
        if elem.get("isDeleted"):
            continue
        etype = elem.get("type")
        if etype in ("arrow", "freedraw", "line", "image"):
            continue
        if etype == "text" and elem.get("containerId"):
            continue
        eid = elem.get("id")
        if not eid:
            continue
        if eid in background_ids:
            continue
        bbox = _bbox(elem)
        if bbox is None:
            continue
        candidates.append((eid, bbox, elem))

    n = len(candidates)
    for i in range(n):
        eid_a, bbox_a, elem_a = candidates[i]
        for j in range(i + 1, n):
            eid_b, bbox_b, elem_b = candidates[j]

            if not _bboxes_overlap(bbox_a, bbox_b):
                continue

            # Same-group children of a banded layout (swimlane) can legitimately
            # share x-spans only if their lane widths span the canvas; we still
            # report node-vs-node overlaps inside a lane though, since those
            # ARE visual bugs.

            findings.append(
                Finding(
                    category="collision/node_overlap",
                    severity=Severity.MAJOR,
                    message=(
                        f"shapes {eid_a!r} and {eid_b!r} overlap. "
                        f"a=({bbox_a[0]:.0f},{bbox_a[1]:.0f},"
                        f"{bbox_a[2]:.0f}x{bbox_a[3]:.0f}); "
                        f"b=({bbox_b[0]:.0f},{bbox_b[1]:.0f},"
                        f"{bbox_b[2]:.0f}x{bbox_b[3]:.0f})."
                    ),
                    element_id=eid_a,
                    location={"a": list(bbox_a), "b": list(bbox_b), "other_id": eid_b},
                )
            )

    return findings


def check_edge_crossings(manifest: Dict[str, Any]) -> List[Finding]:
    """Pairwise arrow crossings — segment-aware over the full polyline path.

    Counts each ARROW PAIR at most once, regardless of how many of its
    segments intersect. Skips arrow pairs that share an endpoint (fan-out
    from the same source, fan-in to the same target). Severity buckets:

    - 0 crossings → no finding
    - 1..N crossings → INFO
    - >N crossings → MINOR
    """
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return findings

    arrows: List[Tuple[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]]] = []
    for elem in elements:
        if not isinstance(elem, dict) or elem.get("isDeleted") or elem.get("type") != "arrow":
            continue
        if _is_fully_transparent(elem):
            continue
        eid = elem.get("id", "")
        segs = _arrow_segments(elem)
        if not segs:
            continue
        arrows.append((eid, segs))

    crossing_pairs: List[Tuple[str, str]] = []
    n = len(arrows)
    for i in range(n):
        id_a, segs_a = arrows[i]
        a_first = segs_a[0][0]
        a_last = segs_a[-1][1]
        for j in range(i + 1, n):
            id_b, segs_b = arrows[j]
            b_first = segs_b[0][0]
            b_last = segs_b[-1][1]

            # Skip arrows that share an endpoint (legit branch / merge fan).
            if a_first in (b_first, b_last) or a_last in (b_first, b_last):
                continue

            # Look for any segment-vs-segment intersection across the two
            # polylines. Stop at the first hit — one finding per pair.
            crossed = False
            for sa, ea in segs_a:
                for sb, eb in segs_b:
                    if _segments_intersect(sa, ea, sb, eb):
                        crossed = True
                        break
                if crossed:
                    break
            if crossed:
                crossing_pairs.append((id_a, id_b))

    count = len(crossing_pairs)
    if count <= _EDGE_CROSSING_INFO_THRESHOLD:
        return findings  # nothing worth reporting

    severity = (
        Severity.MINOR if count > _EDGE_CROSSING_MINOR_THRESHOLD else Severity.INFO
    )
    sample = ", ".join(f"{a!r}×{b!r}" for a, b in crossing_pairs[:3])
    findings.append(
        Finding(
            category="collision/edge_crossing",
            severity=severity,
            message=(
                f"{count} arrow crossing pair(s) detected. Sample: {sample}."
            ),
            location={"count": count, "pairs": crossing_pairs[:20]},
        )
    )
    return findings


def check_out_of_canvas(manifest: Dict[str, Any]) -> List[Finding]:
    """Shapes whose bbox violates the canvas safe area."""
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return findings

    arrow_ids = {
        str(elem.get("id"))
        for elem in elements
        if isinstance(elem, dict) and elem.get("type") == "arrow" and elem.get("id")
    }
    for elem in elements:
        if not isinstance(elem, dict):
            continue
        if elem.get("isDeleted"):
            continue
        if elem.get("type") in ("arrow", "freedraw", "line"):
            continue
        # Excalidraw positions text bound to an arrow from the arrow geometry.
        # Its serialized x/y can remain a placeholder outside the canvas even
        # though the rendered label is correctly located on the connector.
        if elem.get("type") == "text" and str(elem.get("containerId")) in arrow_ids:
            continue
        bbox = _bbox(elem)
        if bbox is None:
            continue
        x, y, w, h = bbox
        if (
            x < CANVAS_MARGIN
            or y < CANVAS_MARGIN
            or x + w > CANVAS_MAX_X - CANVAS_MARGIN
            or y + h > CANVAS_MAX_Y - CANVAS_MARGIN
        ):
            findings.append(
                Finding(
                    category="collision/out_of_canvas",
                    severity=Severity.MINOR,
                    message=(
                        f"element {elem.get('id', '?')!r} bbox=({x:.0f},"
                        f"{y:.0f},{w:.0f}x{h:.0f}) violates canvas safe "
                        f"area [{CANVAS_MARGIN},{CANVAS_MAX_X - CANVAS_MARGIN}]"
                        f"x[{CANVAS_MARGIN},{CANVAS_MAX_Y - CANVAS_MARGIN}]."
                    ),
                    element_id=elem.get("id"),
                    location={"x": x, "y": y, "w": w, "h": h},
                )
            )
    return findings


__all__ = [
    "check_node_overlap",
    "check_edge_crossings",
    "check_edge_node_intersections",
    "check_out_of_canvas",
]
