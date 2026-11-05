"""Edge labels: filtering, measurement and obstacle-free placement."""
from __future__ import annotations

import logging
import math
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from evodesign.agentic_system.common.spec_utils import unwrap_structure_instantiation

from ...shared.edge_crossing_detector import detect_crossings
from ...shared.label_geometry import disjoint_segment_box_distance
from ..converter import _estimate_text_dimensions
from .geometry import (
    Box,
    Point,
    _absolute_arrow_points,
    _arrow_path_fields,
    _path_length,
    _path_parallel_channel_penalty,
    _route_is_legal,
    _segment_hits_box,
    _visible_arrows,
    _waypoints,
)

logger = logging.getLogger(__name__)

MAX_EDGE_LABEL_WORDS = 5
# Reverse-containment guard for the edge-label paraphrase filter (see
# ``_should_drop_edge_label``): a node label that *contains* the edge label
# only signals a paraphrase when the edge label is substantial.
MIN_REVERSE_PARAPHRASE_CHARS = 4

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


def _normalize_label_payload(label_payload: Any) -> Optional[Dict[str, Any]]:
    """Normalize edge label payload into text styling fields."""
    if isinstance(label_payload, str):
        text = label_payload.strip()
        if not text:
            return None
        return {
            "text": text,
            "fontSize": 13,
            "fontFamily": 2,
            "strokeColor": "#374151",
            "textAlign": "center",
        }

    if not isinstance(label_payload, dict):
        return None

    text = label_payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    normalized: Dict[str, Any] = {
        "text": text,
        "fontSize": label_payload.get("fontSize", 13),
        "fontFamily": label_payload.get("fontFamily", 2),
        "strokeColor": label_payload.get("strokeColor", "#374151"),
        "textAlign": label_payload.get("textAlign", "center"),
    }

    if label_payload.get("verticalAlign") in {"top", "middle", "bottom"}:
        normalized["verticalAlign"] = label_payload["verticalAlign"]

    return normalized


def _edge_label_payload(relation: Dict[str, Any], edge_payload: Optional[Dict[str, Any]]) -> Any:
    """The relation's own label, else the layout edge's label."""
    label_payload = relation.get("label", "")
    if not label_payload and edge_payload:
        label_payload = edge_payload.get("label", "")
    return label_payload


def _node_label_lookup(structure_instantiation: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Build a {node_id -> node.label} map from structure_instantiation
    so we can detect when an edge label paraphrases its target node.

    Tolerates both ``{instantiation: {nodes: [...]}}`` and flat shapes.
    """
    inst = unwrap_structure_instantiation(structure_instantiation)
    out: Dict[str, str] = {}
    for n in inst.get("nodes") or []:
        if isinstance(n, dict):
            nid = n.get("id")
            label = n.get("label")
            if isinstance(nid, str) and isinstance(label, str):
                out[nid] = label
    return out


def _merge_semantic_edge_labels(
    relations: List[Dict[str, Any]],
    structure_instantiation: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Restore semantic labels omitted by a layout response.

    Layout owns ports and routing, but it must not be able to erase a
    relationship label that Structure already validated. Keep layout endpoint
    records authoritative and fill only missing labels from the semantic edge
    with the same stable id.
    """
    structure = unwrap_structure_instantiation(structure_instantiation)
    semantic_by_id: Dict[str, Dict[str, Any]] = {
        str(edge.get("id")): edge
        for edge in structure.get("edges", []) or []
        if isinstance(edge, dict) and isinstance(edge.get("id"), str)
    }
    merged: List[Dict[str, Any]] = []
    for relation in relations:
        enriched = dict(relation)
        if not enriched.get("label"):
            semantic = semantic_by_id.get(str(enriched.get("id")))
            if semantic:
                # A semantic predicate is not necessarily visible text. Flow
                # edges, for example, may record "followed by" in the ledger
                # while deliberately displaying only their Yes/No branches.
                label = semantic.get("label")
                if not label and structure.get("chart_type") == "concept_map":
                    label = semantic.get("relation")
                if label:
                    enriched["label"] = label
        merged.append(enriched)
    return merged


def _should_drop_edge_label(
    label_text: str,
    source_ref: Any,
    target_ref: Any,
    node_labels: Dict[str, str],
    *,
    preserve_structural_labels: bool = False,
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
    if preserve_structural_labels:
        # Concept-map arrows alone do not express a predicate. Containment
        # suppression is handled explicitly before this filter; a long fact,
        # a modal qualifier, or "uses" must not silently lose its meaning.
        return None

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
        # Forward direction: the edge label spells out the node label.
        matched = ref_label in low
        # Reverse direction (node label contains the edge label) catches
        # abbreviations / partials, but a bare substring test fires on almost
        # any short label — "no" is inside "Notify user", so a decision
        # diamond loses the very branch labels it needs. Require the edge
        # label to be substantial enough to actually be a paraphrase.
        if not matched and low in ref_label:
            matched = len(low) >= MIN_REVERSE_PARAPHRASE_CHARS or len(low.split()) >= 2
        if matched:
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
        segments.append({
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
        })

    if not segments:
        return None

    def longest(orientation_filter) -> Optional[Dict[str, float]]:
        matching = [segment for segment in segments if orientation_filter(segment["orientation"])]
        return max(matching, key=lambda segment: segment["length"]) if matching else None

    preferred = None
    if routing == "elbowed":
        preferred = longest(lambda o: o == "horizontal") or longest(lambda o: o == "vertical")
    elif routing == "curved":
        preferred = longest(lambda o: o != "diagonal")
    return preferred or longest(lambda o: True)


def _arrow_routing(arrow_elem: Dict[str, Any]) -> str:
    if arrow_elem.get("elbowed"):
        return "elbowed"
    if isinstance(arrow_elem.get("roundness"), dict):
        return "curved"
    return "straight"


def _compute_label_geometry(
    ax: float,
    ay: float,
    dx: float,
    dy: float,
    arrow_elem: Dict[str, Any],
    normalized_label: Dict[str, Any],
) -> Dict[str, float]:
    """Compute text box geometry from the arrow path instead of the raw endpoint midpoint."""
    dims = _estimate_text_dimensions(normalized_label["text"], int(normalized_label["fontSize"]))
    width = float(dims["width"])
    height = float(dims["height"])

    path_points = _build_label_path_points(ax, ay, dx, dy, arrow_elem)
    segment = _choose_label_segment(path_points, _arrow_routing(arrow_elem))
    if segment and segment["orientation"] == "horizontal" and segment["length"] < width + 16.0:
        vertical_segments = [
            _choose_label_segment([start, end], "straight")
            for start, end in zip(path_points, path_points[1:])
            if abs(start[0] - end[0]) < 1.0 and abs(start[1] - end[1]) >= height + 16.0
        ]
        if vertical_segments:
            segment = max(vertical_segments, key=lambda item: item["length"])

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


def _refresh_bound_labels(arrow: Dict[str, Any], elements_by_id: Dict[str, Dict[str, Any]]) -> None:
    """Re-place the text bound to ``arrow`` on its current path."""
    for binding in arrow.get("boundElements", []) or []:
        if binding.get("type") != "text":
            continue
        label = elements_by_id.get(str(binding.get("id")))
        if label is None:
            continue
        endpoints = _absolute_arrow_points([arrow])
        label.update(_compute_label_geometry(
            endpoints[0][0],
            endpoints[0][1],
            endpoints[-1][0] - endpoints[0][0],
            endpoints[-1][1] - endpoints[0][1],
            arrow,
            label,
        ))


def _reposition_edge_labels(
    elements: List[Dict[str, Any]],
    generated_elements: List[Dict[str, Any]],
) -> None:
    """Move edge labels to the nearest node- and foreign-edge-free position."""
    arrows = {
        str(element.get("id")): element
        for element in _visible_arrows(generated_elements)
        if element.get("id")
    }
    node_boxes = [
        (
            float(element.get("x", 0.0) or 0.0),
            float(element.get("y", 0.0) or 0.0),
            float(element.get("width", 0.0) or 0.0),
            float(element.get("height", 0.0) or 0.0),
        )
        for element in elements
        if element.get("type") not in {"arrow", "text", "image"}
        and not element.get("isDeleted")
        and not element.get("is_group")
    ]
    for element in elements:
        if not element.get("is_group") or element.get("isDeleted"):
            continue
        if float(element.get("opacity", 100)) <= 0 or element.get("strokeColor") in {"transparent", "none"}:
            continue
        left = float(element.get("x", 0.0) or 0.0)
        top = float(element.get("y", 0.0) or 0.0)
        width = float(element.get("width", 0.0) or 0.0)
        height = float(element.get("height", 0.0) or 0.0)
        # Labels may live inside a section, but must not straddle its outline.
        node_boxes.extend([
            (left, top, width, 0.0), (left, top + height, width, 0.0),
            (left, top, 0.0, height), (left + width, top, 0.0, height),
        ])
    placed: List[Box] = []
    arrow_segments = {
        arrow_id: [
            (points[index], points[index + 1])
            for index in range(len(points) - 1)
            if points[index] != points[index + 1]
        ]
        for arrow_id, arrow in arrows.items()
        if len(points := _absolute_arrow_points([arrow])) >= 2
    }
    all_segments = [segment for segments in arrow_segments.values() for segment in segments]

    def overlaps(box: Box, obstacle: Box) -> bool:
        x, y, width, height = box
        ox, oy, obstacle_width, obstacle_height = obstacle
        padding = 4.0
        return (
            x < ox + obstacle_width + padding
            and x + width > ox - padding
            and y < oy + obstacle_height + padding
            and y + height > oy - padding
        )

    def placement_candidates(geometry, own_segments):
        base_x, base_y = geometry["x"], geometry["y"]
        width, height = geometry["width"], geometry["height"]
        candidates = [(base_x, base_y)]
        for start, end in sorted(own_segments, key=lambda segment: -math.dist(*segment)):
            if abs(start[1] - end[1]) < 1e-6:
                available = abs(end[0] - start[0]) - width - 16.0
                if available < 0:
                    continue
                for fraction in (0.5, 0.0, 1.0, 0.25, 0.75):
                    x = min(start[0], end[0]) + 8.0 + fraction * available
                    candidates.extend([(x, start[1] - height - 8.0), (x, start[1] + 8.0)])
            elif abs(start[0] - end[0]) < 1e-6:
                available = abs(end[1] - start[1]) - height - 16.0
                if available < 0:
                    continue
                for fraction in (0.5, 0.0, 1.0, 0.25, 0.75):
                    y = min(start[1], end[1]) + 8.0 + fraction * available
                    candidates.extend([(start[0] + 8.0, y), (start[0] - width - 8.0, y)])
        # A short elbow can still have room for its label beside the bend.
        # Explore small offsets before falling back to a colliding midpoint;
        # the clearance and owner-distance checks still constrain every move.
        for offset in (8.0, 16.0, 24.0, 32.0, 48.0):
            candidates.extend((base_x + dx, base_y + dy) for dx, dy in (
                (0.0, -offset), (0.0, offset), (-offset, 0.0), (offset, 0.0),
            ))
        return [(max(0.0, x), max(0.0, y), width, height) for x, y in candidates]

    def clear(candidate):
        if any(overlaps(candidate, obstacle) for obstacle in [*node_boxes, *placed]):
            return False
        padded = (candidate[0] - 3.0, candidate[1] - 3.0, candidate[2] + 6.0, candidate[3] + 6.0)
        return not any(_segment_hits_box(start, end, padded) for start, end in all_segments)

    for label in generated_elements:
        if label.get("type") != "text" or str(label.get("containerId", "")) not in arrows:
            continue
        own_arrow = arrows[str(label["containerId"])]
        own_segments = arrow_segments.get(str(label["containerId"]), [])
        original_text = label.get("text", "")
        font_size = float(label.get("fontSize", 13))
        variants = [original_text]
        words = original_text.split()
        # Preserve every word. Only try a two-line label when the authored
        # form has no clear nearby placement; balanced breaks come first.
        breaks = sorted(range(1, len(words)), key=lambda index: abs(
            len(" ".join(words[:index])) - len(" ".join(words[index:]))
        ))[:6]
        variants.extend(" ".join(words[:index]) + "\n" + " ".join(words[index:]) for index in breaks)
        chosen = None
        nearest_clear = None
        default = None
        for variant_index, text in enumerate(variants):
            geometry = {key: float(label.get(key, 0.0) or 0.0) for key in ("x", "y", "width", "height")}
            if text:
                geometry = _compute_label_geometry(
                    ax=float(own_arrow.get("x", 0.0)), ay=float(own_arrow.get("y", 0.0)),
                    dx=float(own_arrow.get("width", 0.0)), dy=float(own_arrow.get("height", 0.0)),
                    arrow_elem=own_arrow, normalized_label={"text": text, "fontSize": font_size},
                )
            if default is None:
                default = (text, tuple(geometry[key] for key in ("x", "y", "width", "height")))
            for candidate in placement_candidates(geometry, own_segments):
                if not clear(candidate):
                    continue
                distance = min((disjoint_segment_box_distance(start, end, candidate)
                                for start, end in own_segments), default=0.0)
                if distance <= max(24.0, 1.5 * font_size):
                    chosen = (text, candidate)
                    break
                score = (distance, variant_index)
                if nearest_clear is None or score < nearest_clear[0]:
                    nearest_clear = (score, text, candidate)
            if chosen is not None:
                break
        if chosen is None:
            chosen = (nearest_clear[1], nearest_clear[2]) if nearest_clear else default
        text, box = chosen
        label.update(dict(zip(("x", "y", "width", "height"), box)))
        if text != original_text:
            label["text"] = text
            label["originalText"] = text
        placed.append(box)


def _position_architecture_bound_labels(elements, generated_elements, route_contexts, group_frame_ids=None) -> None:
    """Clear native bound-label midpoints by moving dogleg channels, not text.

    Excalidraw restores/exports arrow text at the middle point/segment, ignoring
    authored text x/y. Keep native binding and edit behavior intact, and test
    clearance at that actual position before accepting any route adjustment.
    """
    arrows = {str(item['id']): item for item in _visible_arrows(generated_elements)}
    labels = {str(item.get('containerId')): item for item in generated_elements
              if item.get('type') == 'text' and str(item.get('containerId')) in arrows}
    if not labels:
        return
    obstacles = []
    for item in elements:
        if item.get('isDeleted') or item.get('type') in {'text', 'image', 'arrow'}:
            continue
        x, y, w, h = (float(item.get(key, 0) or 0) for key in ('x', 'y', 'width', 'height'))
        if item.get('is_group') or item.get('id') in (group_frame_ids or set()):
            if item.get('opacity', 100) > 0 and item.get('strokeColor') not in {'transparent', 'none'}:
                obstacles.extend([(x, y, w, 0), (x, y+h, w, 0), (x, y, 0, h), (x+w, y, 0, h)])
        else:
            obstacles.append((x, y, w, h))

    def native_box(points, label):
        middle = len(points) // 2
        cx, cy = points[middle]
        if len(points) % 2 == 0:
            cx, cy = ((a+b)/2 for a, b in zip(points[middle-1], points[middle]))
        w, h = float(label['width']), float(label['height'])
        return (cx-w/2, cy-h/2, w, h)

    def overlap(a, b):
        return a[0] < b[0]+b[2]+6 and a[0]+a[2] > b[0]-6 and a[1] < b[1]+b[3]+6 and a[1]+a[3] > b[1]-6

    def penalty(paths):
        boxes = {key: native_box(paths[key], label) for key, label in labels.items() if len(paths[key]) >= 2}
        count = 0
        for key, box in boxes.items():
            count += sum(overlap(box, obstacle) for obstacle in obstacles)
            count += sum(overlap(box, other) for other_key, other in boxes.items() if other_key != key)
            padded = (box[0]-6, box[1]-6, box[2]+12, box[3]+12)
            count += sum(_segment_hits_box(a, b, padded) for other_key, points in paths.items()
                         if other_key != key for a, b in zip(points, points[1:]))
        return count

    def creates_crossing(candidate, original, others):
        # Moving a bend can turn an existing shared corner into a counted T
        # intersection. Reject new intersection locations, not that relabeling.
        for other in others:
            foreign = _absolute_arrow_points([other])
            for a, b in zip(candidate, candidate[1:]):
                rx, ry = b[0]-a[0], b[1]-a[1]
                for c, d in zip(foreign, foreign[1:]):
                    sx, sy = d[0]-c[0], d[1]-c[1]
                    denominator = rx*sy-ry*sx
                    if abs(denominator) < 1e-9:
                        continue
                    qx, qy = c[0]-a[0], c[1]-a[1]
                    t, u = (qx*sy-qy*sx)/denominator, (qx*ry-qy*rx)/denominator
                    if not (0 <= t <= 1 and 0 <= u <= 1):
                        continue
                    point = (a[0]+t*rx, a[1]+t*ry, 0, 0)
                    if all(disjoint_segment_box_distance(p, q, point) > 1e-6
                           for p, q in zip(original, original[1:])):
                        return True
        return False

    def legal(points, context):
        return _route_is_legal(points, context['obstacles'], context['source_bbox'], context['target_bbox'])

    paths = {key: _absolute_arrow_points([arrow]) for key, arrow in arrows.items()}
    originals = deepcopy(arrows)
    original_score = penalty(paths)

    def set_path(key, points):
        arrows[key].update(_arrow_path_fields(_waypoints(points), min_size=1))
        if len(points) > 2:
            arrows[key]['elbowed'] = True
        paths[key] = points

    # Earlier route optimization can collapse an incoming and outgoing port
    # back onto the same face center. Reserve room for their actual labels,
    # ordering both roles together by the opposite endpoint's position.
    faces = {}
    for key, context in route_contexts.items():
        if key not in paths or len(paths[key]) < 2:
            continue
        for role, ref_key, side_key in [('source', 'source_ref', 'start_side'), ('target', 'target_ref', 'end_side')]:
            if ref_key in context:
                faces.setdefault((context[ref_key], context[side_key]), []).append((key, role))
    for (_, side), endpoints in faces.items():
        if {role for _, role in endpoints} != {'source', 'target'}:
            continue
        axis = 0 if side in {'top', 'bottom'} else 1
        positions = sorted(paths[key][0 if role == 'source' else -1][axis] for key, role in endpoints)
        if min(b-a for a, b in zip(positions, positions[1:])) >= 8:
            continue
        first_key, first_role = endpoints[0]
        box = route_contexts[first_key][first_role+'_bbox']
        span = box['w' if axis == 0 else 'h']
        center = box['x' if axis == 0 else 'y'] + span/2
        spacing = max([32.0] + [float(labels[key]['width' if axis == 0 else 'height']) + 20
                                for key, _ in endpoints if key in labels])
        spacing = min(spacing, max(0, span-24)/(len(endpoints)-1))
        ordered = sorted(endpoints, key=lambda item: (
            paths[item[0]][-1 if item[1] == 'source' else 0][axis], item[0]))
        trial = deepcopy(paths)
        valid = True
        for rank, (key, role) in enumerate(ordered):
            points = [list(point) for point in trial[key]]
            if len(points) == 2:
                # A near-vertical single segment can share the exact same
                # face as an outgoing dogleg. Give it a middle channel before
                # reserving distinct ports; retain it only if clearance wins.
                midpoint = (points[0][1-axis] + points[-1][1-axis]) / 2
                first, last = list(points[0]), list(points[-1])
                first[1-axis] = last[1-axis] = midpoint
                points = [points[0], first, last, points[-1]]
            i, j = (0, 1) if role == 'source' else (-1, -2)
            boundary = box['y' if axis == 0 else 'x'] + (box['h'] if side == 'bottom' else box['w'] if side == 'right' else 0)
            if abs(points[i][1-axis]-boundary) > 1e-6 or abs(points[i][axis]-points[j][axis]) > 1e-6:
                valid = False
                break
            points[i][axis] = points[j][axis] = center + (rank-(len(ordered)-1)/2)*spacing
            trial[key] = [tuple(point) for point in points]
            if not legal(trial[key], route_contexts[key]):
                valid = False
                break
        if valid:
            for key, _ in endpoints:
                set_path(key, trial[key])

    score = penalty(paths)
    for _ in range(2):
        changed = False
        for key in labels:
            arrow, points = arrows[key], paths[key]
            context = route_contexts.get(key)
            if not context or len(points) != 4 or not arrow.get('elbowed'):
                continue
            vertical = abs(points[1][0]-points[2][0]) < 1e-6
            horizontal = abs(points[1][1]-points[2][1]) < 1e-6
            if vertical == horizontal:
                continue
            axis = 0 if vertical else 1
            others = [item for other_key, item in arrows.items() if other_key != key]
            channel_penalty = _path_parallel_channel_penalty(points, others)
            best = None
            for offset in (-16, 16, -32, 32, -48, 48, -64, 64):
                candidate = [list(point) for point in points]
                candidate[1][axis] += offset
                candidate[2][axis] += offset
                candidate = [tuple(point) for point in candidate]
                if (min(min(point) for point in candidate) < 0
                        or _path_length(candidate) > _path_length(points)+64
                        or not legal(candidate, context)
                        or _path_parallel_channel_penalty(candidate, others) > channel_penalty + 1e-6
                        or creates_crossing(candidate, points, others)):
                    continue
                next_score = penalty({**paths, key: candidate})
                rank = (next_score, abs(offset))
                if next_score < score and (best is None or rank < best[0]):
                    best = (rank, candidate)
            if best is None:
                continue
            (score, _), paths[key] = best
            set_path(key, paths[key])
            changed = True
        if not changed or score == 0:
            break
    if score >= original_score or len(detect_crossings(list(arrows.values()))) > len(detect_crossings(list(originals.values()))):
        for key, original in originals.items():
            arrows[key].update(original)
            paths[key] = _absolute_arrow_points([original])
    for key, label in labels.items():
        if len(paths[key]) >= 2:
            label.update(dict(zip(('x', 'y', 'width', 'height'), native_box(paths[key], label))))


def _detach_concept_labels(generated_elements: List[Dict[str, Any]]) -> None:
    """Export concept predicates as grouped free text at their computed spots.

    Excalidraw ignores authored x/y for text bound to an arrow when exporting,
    and places it back on the path. Concept predicates need the obstacle-free
    positions computed above. Keep semantic ownership and an editor group
    while exporting them as independent text.
    """
    arrows_by_id = {element["id"]: element for element in generated_elements if element.get("type") == "arrow"}
    arrows_by_semantic_id = {
        (arrow.get("meta") or {}).get("semantic_edge_id"): arrow_id
        for arrow_id, arrow in arrows_by_id.items()
    }
    for label in generated_elements:
        arrow_id = label.get("containerId") or arrows_by_semantic_id.get(
            (label.get("meta") or {}).get("semantic_edge_id")
        )
        if label.get("type") != "text" or arrow_id not in arrows_by_id:
            continue
        arrow = arrows_by_id[arrow_id]
        group_id = f"relation:{arrow_id}"
        label["containerId"] = None
        label.setdefault("meta", {})["semantic_arrow_id"] = arrow_id
        label["groupIds"] = [group_id]
        arrow["groupIds"] = [group_id]
        arrow["boundElements"] = [binding for binding in arrow.get("boundElements", []) if binding.get("id") != label["id"]]
