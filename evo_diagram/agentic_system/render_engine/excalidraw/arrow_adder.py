# -*- coding: utf-8 -*-
"""
Excalidraw Arrow Adder - Add directional arrows to an Excalidraw manifest.
"""

import logging
import math
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from evo_diagram.agentic_system.common.semantic_ids import (
    id_map_from_manifest,
    reverse_id_map,
)
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from ..shared.edge_crossing_detector import detect_crossings
from ..shared.edge_routing import (
    audit_sides,
    collect_relations,
    derive_routing_from_sides,
    extract_edge_port_hints,
    extract_side_from_port,
    find_shape_id,
    normalize_port,
    normalize_routing,
    relations_from_edge_data,
    resolve_edge_payload,
    shape_bbox,
)
from .converter import (
    _estimate_text_dimensions,
    _excalidraw_defaults,
    _generate_excalidraw_id,
)
from .edge_router import (
    compute_waypoints,
    to_relative_points,
    waypoints_bbox,
)

logger = logging.getLogger(__name__)

DEFAULT_STAGGER_SPACING = 50.0
MAX_EDGE_LABEL_WORDS = 5


def _build_fixed_segments(points: List[List[float]]) -> Optional[List[Dict[str, Any]]]:
    """Lock middle elbow segments so explicit turns survive render/import."""
    if len(points) < 4:
        return None

    fixed_segments: List[Dict[str, Any]] = []
    for i in range(1, len(points) - 2):
        fixed_segments.append(
            {
                "start": points[i],
                "end": points[i + 1],
                "index": i + 1,
            }
        )
    return fixed_segments or None


def _normalize_label_payload(label_payload: Any) -> Optional[Dict[str, Any]]:
    """Normalize edge label payload into text styling fields."""
    if isinstance(label_payload, str):
        text = label_payload.strip()
        if not text:
            return None
        return {
            "text": text,
            "fontSize": 16,
            "fontFamily": 1,
            "strokeColor": "#1e1e1e",
            "textAlign": "center",
        }

    if not isinstance(label_payload, dict):
        return None

    text = label_payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    normalized: Dict[str, Any] = {
        "text": text,
        "fontSize": label_payload.get("fontSize", 16),
        "fontFamily": label_payload.get("fontFamily", 1),
        "strokeColor": label_payload.get("strokeColor", "#1e1e1e"),
        "textAlign": label_payload.get("textAlign", "center"),
    }

    if label_payload.get("verticalAlign") in {"top", "middle", "bottom"}:
        normalized["verticalAlign"] = label_payload["verticalAlign"]

    return normalized


# ---------------------------------------------------------------------------
# Edge-label sanity filter (2026-04-25 — user complaint about edge-text clutter).
#
# Acts as the deterministic backstop to the prompt-level "non-essential edge
# labels are forbidden" rule in STRUCTURE_TASK_PROMPT. Even when the LLM
# slips and emits a stop-verb / over-long / target-paraphrasing label, this
# filter drops it before it lands on the canvas.
# ---------------------------------------------------------------------------

# Generic direction-verbs and connectors that the arrow itself already
# encodes. Comparison is case-insensitive after stripping.
_STOP_LABELS: frozenset = frozenset({
    "next", "then", "after", "before", "follows", "follow",
    "leads to", "leads_to", "lead to",
    "goes to", "goes_to", "go to",
    "flows to", "flows_to", "flow to",
    "passes to", "passes_to", "pass to",
    "sent to", "sent_to", "sends to",
    "is part of", "part of", "part_of",
    "contains", "containing", "includes", "including",
    "has", "have", "is a", "is_a", "is an",
    "uses", "use", "using", "calls", "call",
    "to", "from", "and", "or",
    "→", "->", "=>", "⇒", ">",
})


def _node_label_lookup(structure_instantiation: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Build a {node_id -> node.label} map from structure_instantiation
    so we can detect when an edge label paraphrases its target node.

    Tolerates both ``{instantiation: {nodes: [...]}}`` and flat shapes.
    """
    inst = unwrap_structure_instantiation(structure_instantiation)
    nodes = inst.get("nodes") or []
    out: Dict[str, str] = {}
    for n in nodes:
        if isinstance(n, dict):
            nid = n.get("id")
            label = n.get("label")
            if isinstance(nid, str) and isinstance(label, str):
                out[nid] = label
    return out


def _should_drop_edge_label(
    label_text: str,
    source_ref: Any,
    target_ref: Any,
    node_labels: Dict[str, str],
) -> Optional[str]:
    """Return a reason string (for logging) if the label should be dropped,
    or ``None`` to keep it. Three rules, in order:

    1. **stop-verb match** — generic direction-verbs the arrow already
       encodes (next / then / leads to / contains / has / uses / "→" / ...).
    2. **too long** — more than ``MAX_EDGE_LABEL_WORDS`` words is a description,
       not a relation. Mirrors the ``≤5 words`` rule in STRUCTURE_TASK_PROMPT.
    3. **paraphrases an endpoint** — when the source or target node's
       label appears as a substring inside the edge label, the edge text
       is just repeating what the destination shape already says.
    """
    if not isinstance(label_text, str):
        return None
    text = label_text.strip()
    if not text:
        return None  # already empty, nothing to drop

    low = text.lower()

    if low in _STOP_LABELS:
        return f"stop-verb '{text}'"

    word_count = len(text.split())
    if word_count > MAX_EDGE_LABEL_WORDS:
        return f"too long ({word_count} words)"

    for ref in (target_ref, source_ref):
        ref_label = (node_labels.get(str(ref)) or "").strip().lower()
        if not ref_label:
            continue
        # Substring match either direction: edge label contains node label,
        # or node label contains edge label (handles abbreviations / partials).
        if ref_label in low or low in ref_label:
            role = "target" if ref is target_ref else "source"
            return f"paraphrases {role} node '{node_labels[str(ref)]}'"

    return None


def _build_label_path_points(
    ax: float,
    ay: float,
    dx: float,
    dy: float,
    arrow_elem: Dict[str, Any],
) -> List[List[float]]:
    """Build an absolute path polyline for label placement."""
    rel_points = arrow_elem.get("points")
    if isinstance(rel_points, list) and len(rel_points) >= 2:
        abs_points: List[List[float]] = []
        for point in rel_points:
            if not (
                isinstance(point, (list, tuple))
                and len(point) == 2
                and isinstance(point[0], (int, float))
                and isinstance(point[1], (int, float))
            ):
                abs_points = []
                break
            abs_points.append([float(ax + point[0]), float(ay + point[1])])
        if len(abs_points) >= 2:
            return abs_points

    return [[float(ax), float(ay)], [float(ax + dx), float(ay + dy)]]


def _segment_orientation(dx: float, dy: float) -> str:
    if abs(dy) < 1e-6:
        return "horizontal"
    if abs(dx) < 1e-6:
        return "vertical"
    return "diagonal"


def _choose_label_segment(path_points: List[List[float]], routing: str) -> Optional[Dict[str, float]]:
    """Choose the most readable path segment for a label."""
    segments: List[Dict[str, float]] = []
    for start, end in zip(path_points, path_points[1:]):
        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        orientation = _segment_orientation(dx, dy)
        length = abs(dx) if orientation == "horizontal" else abs(dy) if orientation == "vertical" else math.hypot(dx, dy)
        if length < 1:
            continue
        segments.append(
            {
                "start_x": float(start[0]),
                "start_y": float(start[1]),
                "end_x": float(end[0]),
                "end_y": float(end[1]),
                "mid_x": float((start[0] + end[0]) / 2),
                "mid_y": float((start[1] + end[1]) / 2),
                "dx": dx,
                "dy": dy,
                "length": float(length),
                "orientation": orientation,
            }
        )

    if not segments:
        return None

    if routing == "elbowed":
        horizontal = [segment for segment in segments if segment["orientation"] == "horizontal"]
        if horizontal:
            return max(horizontal, key=lambda segment: segment["length"])
        vertical = [segment for segment in segments if segment["orientation"] == "vertical"]
        if vertical:
            return max(vertical, key=lambda segment: segment["length"])

    if routing == "curved":
        non_diagonal = [segment for segment in segments if segment["orientation"] != "diagonal"]
        if non_diagonal:
            return max(non_diagonal, key=lambda segment: segment["length"])

    return max(segments, key=lambda segment: segment["length"])


def _compute_label_geometry(
    ax: float,
    ay: float,
    dx: float,
    dy: float,
    arrow_elem: Dict[str, Any],
    normalized_label: Dict[str, Any],
) -> Dict[str, float]:
    """Compute text box geometry from the arrow path instead of the raw endpoint midpoint."""
    dims = _estimate_text_dimensions(
        normalized_label["text"],
        int(normalized_label["fontSize"]),
    )
    width = float(dims["width"])
    height = float(dims["height"])

    if arrow_elem.get("elbowed"):
        routing = "elbowed"
    elif isinstance(arrow_elem.get("roundness"), dict):
        routing = "curved"
    else:
        routing = "straight"

    path_points = _build_label_path_points(ax, ay, dx, dy, arrow_elem)
    segment = _choose_label_segment(path_points, routing)

    if segment is None:
        mid_x = float(ax + dx / 2)
        mid_y = float(ay + dy / 2)
        return {
            "x": max(0.0, mid_x - width / 2),
            "y": max(0.0, mid_y - height / 2),
            "width": width,
            "height": height,
        }

    if segment["orientation"] == "horizontal":
        x = segment["mid_x"] - width / 2
        y = segment["mid_y"] - height - 8
    elif segment["orientation"] == "vertical":
        x = segment["mid_x"] + 8
        y = segment["mid_y"] - height / 2
    else:
        segment_length = max(segment["length"], 1.0)
        normal_x = -segment["dy"] / segment_length
        normal_y = segment["dx"] / segment_length
        offset = 14.0
        x = segment["mid_x"] + normal_x * offset - width / 2
        y = segment["mid_y"] + normal_y * offset - height / 2

    return {
        "x": max(0.0, x),
        "y": max(0.0, y),
        "width": width,
        "height": height,
    }


def _find_element_by_excalidraw_id(elements: List[Dict[str, Any]], eid: str) -> Optional[Dict[str, Any]]:
    """Find an element in the elements list by its Excalidraw ID."""
    for elem in elements:
        if elem.get("id") == eid:
            return elem
    return None


def _build_lookup_store(elements: List[Dict[str, Any]], id_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Build a shape lookup store from Excalidraw elements for shared edge routing.

    The store maps `shape:{semantic_id}` to shape-like entries accepted by
    shared edge routing helpers.
    """
    store: Dict[str, Any] = {}
    # Build reverse map: excalidraw_id -> semantic_id
    reverse_map = reverse_id_map(id_map)

    for elem in elements:
        eid = elem.get("id", "")
        semantic_id = reverse_map.get(eid)
        if not semantic_id:
            continue
        # Create a shape-like entry for the shared lookup/geometry helpers.
        shape_key = f"shape:{semantic_id}"
        store[shape_key] = {
            "x": elem.get("x", 0),
            "y": elem.get("y", 0),
            "type": elem.get("type", "rectangle"),
            "props": {
                "w": elem.get("width", 100),
                "h": elem.get("height", 100),
            },
            "parentId": "page:page",
            "_excalidraw_id": eid,
        }
    return store


def add_excalidraw_arrows_to_manifest(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add arrow elements to an Excalidraw manifest based on structure_instantiation edges.

    Args:
        manifest: Excalidraw manifest with elements, files, _meta
        structure_instantiation: Semantic graph with edges

    Returns:
        Updated manifest with arrow elements added
    """
    manifest = deepcopy(manifest)
    elements = manifest.get("elements", [])
    id_map = id_map_from_manifest(manifest)
    meta = manifest.get("_meta")
    edge_data = meta.get("edge_data", {}) if isinstance(meta, dict) else {}
    if not isinstance(edge_data, dict):
        edge_data = {}

    # Build a store for shared edge lookup and routing helpers.
    store = _build_lookup_store(elements, id_map)

    # Pick the authoritative edge source.
    #
    # Layout-derived ``edge_data`` is keyed by the same ID space as ``id_map``.
    # Prefer it over structure edges so arrows bind to the shapes that were
    # actually rendered, even when an upstream layout payload has diverged from
    # the original semantic ids.
    #
    # Falls back to structure edges when ``edge_data`` is missing (older
    # converter, unified mode, or hand-built manifests in tests).
    layout_relations = (
        relations_from_edge_data(edge_data, valid_element_ids=set(id_map))
        if edge_data
        else []
    )
    if layout_relations:
        relations = layout_relations
        logger.info(
            "[ArrowAdder] Using %d edges from manifest._meta.edge_data",
            len(relations),
        )
    else:
        relations = collect_relations(structure_instantiation)
        logger.info(
            "[ArrowAdder] edge_data empty - falling back to structure.edges (%d edges)",
            len(relations),
        )
    port_hints = extract_edge_port_hints(structure_instantiation)

    # Cached for the deterministic edge-label sanity filter further down. Maps
    # node id -> node.label so we can detect when an edge label simply
    # paraphrases the destination node (the most common over-labeling pattern
    # observed on the 2026-04-25 finance/dataflow runs).
    node_label_map = _node_label_lookup(structure_instantiation)
    dropped_label_count = 0

    # ------------------------------------------------------------------
    # Fan-out stagger pre-computation (2026-05-06 AB test)
    # ------------------------------------------------------------------
    from collections import defaultdict

    _relation_sides: List[Dict[str, Any]] = []
    for rel in relations:
        source_ref = rel.get("source", "")
        target_ref = rel.get("target", "")
        edge_id = rel.get("id", "")
        edge_payload = resolve_edge_payload(edge_data, edge_id)

        source_shape_key = find_shape_id(store, source_ref, structure_instantiation)
        target_shape_key = find_shape_id(store, target_ref, structure_instantiation)
        if not (source_shape_key and target_shape_key):
            logger.warning(
                f"Could not find shapes for relation source='{source_ref}' -> target='{target_ref}'"
            )
            continue

        source_shape = store[source_shape_key]
        target_shape = store[target_shape_key]

        hinted = port_hints.get(edge_id) if isinstance(edge_id, str) else None
        if not hinted and isinstance(rel, dict):
            start_hint = normalize_port(rel.get("start"))
            end_hint = normalize_port(rel.get("end"))
            if start_hint and end_hint:
                hinted = {"start": start_hint, "end": end_hint}

        if not hinted and edge_payload:
            start_hint = extract_side_from_port(edge_payload.get("start"))
            end_hint = extract_side_from_port(edge_payload.get("end"))
            if start_hint or end_hint:
                hinted = {"start": start_hint, "end": end_hint}

        start_edge, end_edge = audit_sides(hinted, source_shape, target_shape)
        _relation_sides.append({
            "rel": rel,
            "source_shape_key": source_shape_key,
            "target_shape_key": target_shape_key,
            "source_shape": source_shape,
            "target_shape": target_shape,
            "source_excalidraw_id": source_shape["_excalidraw_id"],
            "target_excalidraw_id": target_shape["_excalidraw_id"],
            "start_edge": start_edge,
            "end_edge": end_edge,
            "edge_payload": edge_payload,
        })

    # Count how many edges share the same (source, start_side, end_side)
    _fanout_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)
    for rs in _relation_sides:
        key = (rs["rel"].get("source", ""), rs["start_edge"], rs["end_edge"])
        _fanout_counts[key] += 1

    # ------------------------------------------------------------------
    # Second pass: render arrows with stagger
    # ------------------------------------------------------------------
    new_arrows: List[Dict[str, Any]] = []
    _fanout_indices: Dict[Tuple[str, str, str], int] = defaultdict(int)

    for rs in _relation_sides:
        rel = rs["rel"]
        source_ref = rel.get("source", "")
        target_ref = rel.get("target", "")
        edge_id = rel.get("id", "")
        edge_payload = rs["edge_payload"]
        source_shape = rs["source_shape"]
        target_shape = rs["target_shape"]
        source_excalidraw_id = rs["source_excalidraw_id"]
        target_excalidraw_id = rs["target_excalidraw_id"]
        start_edge = rs["start_edge"]
        end_edge = rs["end_edge"]

        # Compute stagger index for this edge
        fanout_key = (source_ref, start_edge, end_edge)
        stagger_index = _fanout_indices[fanout_key]
        stagger_total = _fanout_counts[fanout_key]
        _fanout_indices[fanout_key] += 1

        # Compute an explicit polyline path for the arrow.
        src_bbox = shape_bbox(source_shape)
        tgt_bbox = shape_bbox(target_shape)
        abs_waypoints, focus_s, focus_e = compute_waypoints(
            start_edge, end_edge, src_bbox, tgt_bbox,
            stagger_index=stagger_index,
            stagger_total=stagger_total,
            stagger_spacing=DEFAULT_STAGGER_SPACING,
        )
        ox, oy, rel_points = to_relative_points(abs_waypoints)
        bbox_w, bbox_h = waypoints_bbox(abs_waypoints)

        # Label-geometry helpers below still expect a straight-line
        # (ax, ay)→(ax+dx, ay+dy) summary.  Derive that from the polyline
        # endpoints so existing label placement keeps working.
        ax = abs_waypoints[0]["x"]
        ay = abs_waypoints[0]["y"]
        dx = abs_waypoints[-1]["x"] - ax
        dy = abs_waypoints[-1]["y"] - ay
        start_center = {"x": ax, "y": ay}
        end_center = {"x": abs_waypoints[-1]["x"], "y": abs_waypoints[-1]["y"]}

        edge_seed = [
            "edge",
            edge_id or f"{source_ref}->{target_ref}",
            source_ref,
            target_ref,
            stagger_index,
            start_edge,
            end_edge,
        ]
        arrow_id = _generate_excalidraw_id(edge_seed)
        arrow_elem = {
            **_excalidraw_defaults(["arrow", edge_seed]),
            "id": arrow_id,
            "type": "arrow",
            "meta": {
                "semantic_edge_id": edge_id,
                "source": source_ref,
                "target": target_ref,
            },
            "x": ox,
            "y": oy,
            "width": max(1.0, bbox_w),
            "height": max(1.0, bbox_h),
            "points": rel_points,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "lastCommittedPoint": None,
        }

        # Apply edge routing mode.
        #
        # routing 同时控制 ``elbowed`` 和 ``roundness``，让 LLM 的三选一真正生效：
        #
        #   routing=straight → elbowed=False, roundness=None  (普通直线)
        #   routing=elbowed  → elbowed=True,  roundness=None  (带弯折的尖锐线)
        #   routing=curved   → elbowed=True,  roundness={"type": 2} (带弯折的平滑曲线)
        routing_hint: Optional[str] = (
            normalize_routing(edge_payload.get("routing")) if edge_payload else None
        )

        if routing_hint is None:
            routing_hint = normalize_routing(rel.get("routing"))

        if routing_hint is None:
            # Diagram-type-aware fallback — preserves identity signals (e.g.
            # mindmap radial branches must be curved, not elbowed).
            chart_type = unwrap_structure_instantiation(structure_instantiation).get("chart_type")
            routing_hint = derive_routing_from_sides(start_edge, end_edge, chart_type)

        if routing_hint == "straight":
            arrow_elem["elbowed"] = False
            arrow_elem["roundness"] = None
        elif routing_hint == "curved":
            arrow_elem["elbowed"] = True
            arrow_elem["roundness"] = {"type": 2}
        elif routing_hint == "elbowed":
            # Elbowed: explicit polyline with corner routing (no binding).
            # Distinct from straight — has intermediate turns.
            arrow_elem["elbowed"] = True
            arrow_elem["roundness"] = None
        else:
            # Unknown / None — treat as straight polyline.
            arrow_elem["elbowed"] = False
            arrow_elem["roundness"] = None

        if edge_payload:
            if "startArrowhead" in edge_payload:
                arrow_elem["startArrowhead"] = edge_payload["startArrowhead"]
            if "endArrowhead" in edge_payload:
                arrow_elem["endArrowhead"] = edge_payload["endArrowhead"]

        # Apply edge styling from edge_data if available
        if edge_payload:
            if "strokeColor" in edge_payload:
                arrow_elem["strokeColor"] = edge_payload["strokeColor"]
            if "strokeWidth" in edge_payload:
                arrow_elem["strokeWidth"] = edge_payload["strokeWidth"]
            if "strokeStyle" in edge_payload:
                arrow_elem["strokeStyle"] = edge_payload["strokeStyle"]
            props = edge_payload.get("props", {})
            if isinstance(props, dict):
                if "color" in props:
                    arrow_elem["strokeColor"] = props["color"]

            # Note: LLM-supplied ``waypoints`` are no longer honored.  The
            # 2026-04-22 schema removed the field; ``compute_waypoints``
            # above produces the authoritative polyline from the audited
            # (start_side, end_side) pair.

        new_arrows.append(arrow_elem)

        # Handle edge labels
        label_payload: Any = rel.get("label", "")
        if (not label_payload) and edge_payload:
            label_payload = edge_payload.get("label", "")

        normalized_label = _normalize_label_payload(label_payload)

        # Deterministic stop-label filter (2026-04-25 — backstop for the
        # "non-essential edge labels are forbidden" prompt rule). Drops
        # generic direction-verbs, over-long descriptions, and labels that
        # paraphrase their target node. Logs each drop at INFO; aggregate
        # WARNING after the loop if anything was dropped.
        if normalized_label:
            drop_reason = _should_drop_edge_label(
                normalized_label.get("text", ""),
                source_ref,
                target_ref,
                node_label_map,
            )
            if drop_reason:
                logger.info(
                    "[ArrowAdder] dropping edge label edge=%s text=%r reason=%s",
                    edge_id,
                    normalized_label.get("text", ""),
                    drop_reason,
                )
                normalized_label = None
                dropped_label_count += 1

        if normalized_label:
            label_geometry = _compute_label_geometry(
                ax=ax,
                ay=ay,
                dx=dx,
                dy=dy,
                arrow_elem=arrow_elem,
                normalized_label=normalized_label,
            )
            text_seed = [
                "edge_label",
                edge_id or arrow_id,
                normalized_label["text"],
            ]
            text_id = _generate_excalidraw_id(text_seed)
            text_elem = {
                **_excalidraw_defaults(["edge_label", text_seed]),
                "id": text_id,
                "type": "text",
                "x": label_geometry["x"],
                "y": label_geometry["y"],
                "width": label_geometry["width"],
                "height": label_geometry["height"],
                "text": normalized_label["text"],
                "fontSize": normalized_label["fontSize"],
                "fontFamily": normalized_label["fontFamily"],
                "strokeColor": normalized_label["strokeColor"],
                "textAlign": normalized_label["textAlign"],
                "verticalAlign": normalized_label.get("verticalAlign", "middle"),
                "containerId": arrow_id,
                "originalText": normalized_label["text"],
                "autoResize": True,
                "lineHeight": 1.25,
            }
            arrow_elem["boundElements"] = [{"type": "text", "id": text_id}]
            new_arrows.append(text_elem)

    elements.extend(new_arrows)
    manifest["elements"] = elements

    # Observational crossing check — warn-only, no manifest changes.
    # Reports arrows whose polylines intersect (shared-endpoint
    # convergences are excluded).  The warning signal is intended for
    # future Layout-side iteration; we never modify already-committed
    # geometry here.
    arrow_elems = [a for a in new_arrows if a.get("type") == "arrow"]
    crossings = detect_crossings(arrow_elems)
    if crossings:
        for a_id, b_id, meta in crossings:
            logger.warning(
                "[CrossingDetector] Arrow %s crosses %s (segment a=%s, b=%s)",
                a_id,
                b_id,
                meta.get("segment_index_a"),
                meta.get("segment_index_b"),
            )
        logger.warning(
            "[CrossingDetector] %d edge crossing pair(s) detected in manifest",
            len(crossings),
        )

    if dropped_label_count:
        logger.warning(
            "[ArrowAdder] dropped %d non-informative edge label(s) (stop-verb / too long / paraphrase of node)",
            dropped_label_count,
        )

    return manifest
