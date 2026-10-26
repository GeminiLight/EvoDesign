"""Choose a compact, topology-aware layout for concept maps."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations, permutations
import logging
from math import ceil, hypot, log
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from evo_diagram.agentic_system.common.semantic_ids import id_map_from_manifest
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.generation_stage.layout.element_shape_estimator import _estimate_text_dimensions


_CONCEPT_MAP = {"concept_map", "concept map", "conceptmap"}
logger = logging.getLogger(__name__)
_SLOT_ORDER = ("upper_left", "upper_right", "lower_left", "lower_right")
_NODE_FONT_SIZE = 16
_SECTION_FONT_SIZE = 18
_RELATION_FONT_SIZE = 14

# Stable semantic colors make repeated generations comparable and keep the
# branch meaning visible even when the styling model chooses a different
# palette family on each call. These are intentionally light fills paired with
# the same-family dark strokes used by the styling contract.
_CONCEPT_PALETTE = {
    "core": {
        "anchor": "#202124",
        "leaf": "#202124",
        "frame": "#FFFFFF",
        "stroke": "#202124",
        "text": "#FFFFFF",
    },
    "upper_left": {
        "anchor": "#F3D6D8",
        "leaf": "#FCEBED",
        "frame": "#FFF7F8",
        "stroke": "#9E4F61",
        "text": "#43242C",
    },
    "lower_left": {
        "anchor": "#D8E6D1",
        "leaf": "#ECF4E8",
        "frame": "#F8FCF6",
        "stroke": "#56765A",
        "text": "#243D28",
    },
    "upper_right": {
        "anchor": "#D2E9EB",
        "leaf": "#E9F5F6",
        "frame": "#F5FBFB",
        "stroke": "#3F7E8C",
        "text": "#173D45",
    },
    "lower_right": {
        "anchor": "#F1E4C7",
        "leaf": "#FAF2E2",
        "frame": "#FFFAF0",
        "stroke": "#8A6A2F",
        "text": "#493817",
    },
    "branch_1": {
        "anchor": "#DDE7F5",
        "leaf": "#EFF4FB",
        "frame": "#F8FAFD",
        "stroke": "#4D6D99",
        "text": "#243A59",
    },
    "branch_2": {
        "anchor": "#E6DFF0",
        "leaf": "#F3EFF8",
        "frame": "#FBF9FD",
        "stroke": "#75608F",
        "text": "#372A49",
    },
    "branch_3": {
        "anchor": "#F2DED4",
        "leaf": "#FAEEE8",
        "frame": "#FDF9F7",
        "stroke": "#9A6650",
        "text": "#4B3025",
    },
    "branch_4": {
        "anchor": "#DDE8DE",
        "leaf": "#EEF5EF",
        "frame": "#F8FBF8",
        "stroke": "#607A63",
        "text": "#2D402F",
    },
}

_NEUTRAL_CONNECTOR = "#64707A"
_STRUCTURAL_CONNECTOR = "#A8B0B7"
_STRUCTURAL_RELATION_TYPES = {"hierarchy", "composition", "exemplification"}
_STRUCTURAL_RELATION_LABELS = {
    "organized into",
    "has subtype",
    "includes",
    "contains",
    "has example",
    "exemplifies",
}


def _palette_for_branch(branch_id: Optional[str]) -> Mapping[str, str]:
    """Return a stable palette without depending on the branch's subject text."""
    if branch_id in _CONCEPT_PALETTE:
        return _CONCEPT_PALETTE[str(branch_id)]
    if isinstance(branch_id, str) and branch_id.startswith("branch_"):
        try:
            branch_number = int(branch_id.rsplit("_", 1)[1])
        except (TypeError, ValueError):
            branch_number = 1
        overflow_keys = ("branch_1", "branch_2", "branch_3", "branch_4")
        return _CONCEPT_PALETTE[overflow_keys[(branch_number - 1) % len(overflow_keys)]]
    return _CONCEPT_PALETTE["upper_left"]


def _sectors(width: float, height: float) -> Dict[str, Tuple[float, float, float, float]]:
    """Reserve four sectors around a center gap at any supported viewport."""
    margin_x = max(40.0, width * 0.04)
    margin_y = max(40.0, height * 0.05)
    gap_x = max(180.0, width * 0.15)
    gap_y = max(140.0, height * 0.16)
    sector_width = max(260.0, (width - 2.0 * margin_x - gap_x) / 2.0)
    sector_height = max(220.0, (height - 2.0 * margin_y - gap_y) / 2.0)
    left = margin_x
    right = width - margin_x - sector_width
    top = margin_y
    bottom = height - margin_y - sector_height
    return {
        "upper_left": (left, top, sector_width, sector_height),
        "lower_left": (left, bottom, sector_width, sector_height),
        "upper_right": (right, top, sector_width, sector_height),
        "lower_right": (right, bottom, sector_width, sector_height),
    }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _node_shape(elements_by_id: Mapping[str, Dict[str, Any]], id_map: Mapping[str, str], node_id: str) -> Optional[Dict[str, Any]]:
    element = elements_by_id.get(str(id_map.get(node_id, "")))
    if not element or element.get("type") in {"arrow", "text", "image"}:
        return None
    return element


def _move_node(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    node_id: str,
    x: float,
    y: float,
) -> None:
    shape = _node_shape(elements_by_id, id_map, node_id)
    if shape is None:
        return
    dx = x - _number(shape.get("x"))
    dy = y - _number(shape.get("y"))
    shape["x"] = x
    shape["y"] = y
    for element in elements_by_id.values():
        if element is shape:
            continue
        if element.get("containerId") == shape.get("id"):
            element["x"] = _number(element.get("x")) + dx
            element["y"] = _number(element.get("y")) + dy


def _bound_text_elements(
    elements_by_id: Mapping[str, Dict[str, Any]],
    shape: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    shape_id = shape.get("id")
    return [
        element
        for element in elements_by_id.values()
        if element.get("type") == "text" and element.get("containerId") == shape_id
    ]


def _sync_bound_text(
    elements_by_id: Mapping[str, Dict[str, Any]],
    shape: Mapping[str, Any],
) -> None:
    for text in _bound_text_elements(elements_by_id, shape):
        dimensions = _estimate_text_dimensions(str(text.get("text") or ""), int(text.get("fontSize") or 16))
        text.update(dimensions)
        text["x"] = (
            _number(shape.get("x"))
            + (_number(shape.get("width")) - _number(text.get("width"))) / 2.0
        )
        text["y"] = (
            _number(shape.get("y"))
            + (_number(shape.get("height")) - _number(text.get("height"))) / 2.0
        )


def _resize_node(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    node_id: str,
    width: float,
    height: float,
) -> None:
    """Resize around the current center and keep bound text centered."""
    shape = _node_shape(elements_by_id, id_map, node_id)
    if shape is None:
        return
    center_x, center_y = _shape_center(shape)
    shape["width"] = width
    shape["height"] = height
    shape["x"] = center_x - width / 2.0
    shape["y"] = center_y - height / 2.0
    _sync_bound_text(elements_by_id, shape)


def _stable_element_number(namespace: str, semantic_id: str) -> int:
    digest = hashlib.sha256(f"{namespace}:{semantic_id}".encode("utf-8")).hexdigest()
    return (int(digest[:12], 16) % 2_000_000_000) + 1


def _concept_frame(
    anchor_id: str,
    slot_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> Dict[str, Any]:
    palette = _palette_for_branch(slot_name)
    render_id = hashlib.sha256(
        f"concept-frame:{anchor_id}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "id": render_id,
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": 0,
        "strokeColor": palette["stroke"],
        "backgroundColor": palette["frame"],
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": "a00000",
        "roundness": {"type": 3},
        "seed": _stable_element_number("concept-frame-seed", anchor_id),
        "version": 2,
        "versionNonce": _stable_element_number("concept-frame-version", anchor_id),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
        "is_group": True,
    }


def _normalize_concept_shape_language(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    node_ids: Iterable[str],
    core_id: str,
    sectors: Mapping[str, str],
    ownership: Mapping[str, str],
    category_ids: Optional[set[str]] = None,
) -> None:
    """Apply a compact draw.io-like rounded-rectangle shape system."""
    anchor_ids = set(sectors.values())
    leaf_widths: Dict[str, float] = {}
    for branch_id in sectors:
        widths = [
            _estimate_text_dimensions(str(text.get("text") or ""), _NODE_FONT_SIZE)["width"] + 32.0
            for node_id in node_ids
            if node_id not in {core_id, *anchor_ids}
            and ownership.get(node_id) == branch_id
            for shape in [_node_shape(elements_by_id, id_map, node_id)]
            if shape is not None
            for text in _bound_text_elements(elements_by_id, shape)
        ]
        natural_width = max(widths, default=160.0)
        # Styling has already changed the display font. Old layout widths
        # reflect the previous font and needlessly enlarge every peer card.
        # Never cap below the final label width, including CJK and long text.
        leaf_widths[branch_id] = max(160.0, ceil(natural_width / 8.0) * 8.0)

    anchor_width = max(
        (
            _number((_node_shape(elements_by_id, id_map, anchor_id) or {}).get("width"))
            for anchor_id in anchor_ids
        ),
        default=240.0,
    )
    anchor_width = min(304.0, max(240.0, ceil(anchor_width / 8.0) * 8.0))

    for node_id in node_ids:
        shape = _node_shape(elements_by_id, id_map, node_id)
        if shape is None:
            continue
        is_core = node_id == core_id
        is_anchor = node_id in anchor_ids
        is_category = node_id in (category_ids or set()) and not is_core and not is_anchor
        branch_id = ownership.get(node_id)
        palette_key = "core" if is_core else branch_id
        palette = _palette_for_branch(palette_key)

        shape["type"] = "rectangle"
        shape["roundness"] = {"type": 3}
        shape["roughness"] = 0
        shape["fillStyle"] = "solid"
        shape["strokeStyle"] = "solid"
        shape["opacity"] = 100
        shape["backgroundColor"] = palette["anchor" if (is_core or is_anchor or is_category) else "leaf"]
        shape["strokeColor"] = palette["stroke"]
        shape["strokeWidth"] = 2.0 if (is_core or is_anchor) else (1.5 if is_category else 1.25)

        if is_core:
            target_width = min(440.0, max(360.0, _number(shape.get("width"))))
            target_height = 64.0
        elif is_anchor:
            target_width = anchor_width
            target_height = 56.0
        else:
            target_width = leaf_widths.get(branch_id or "", 168.0)
            target_height = max(52.0, max(
                (_estimate_text_dimensions(str(text.get("text") or ""), _NODE_FONT_SIZE)["height"] + 24.0
                 for text in _bound_text_elements(elements_by_id, shape)),
                default=52.0,
            ))
        _resize_node(elements_by_id, id_map, node_id, target_width, target_height)

        for text in _bound_text_elements(elements_by_id, shape):
            text["fontFamily"] = 2
            text["fontSize"] = 24 if is_core else (_SECTION_FONT_SIZE if is_anchor else _NODE_FONT_SIZE)
            text["fontStyle"] = 1 if (is_core or is_anchor) else 0
            text["strokeColor"] = palette["text"]
            text["lineHeight"] = 1.2
        _sync_bound_text(elements_by_id, shape)


def _edge_endpoints(edge: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    source = edge.get("source") or edge.get("from")
    target = edge.get("target") or edge.get("to")
    return (
        str(source) if isinstance(source, str) else None,
        str(target) if isinstance(target, str) else None,
    )


def _edge_is_structural(edge: Mapping[str, Any]) -> bool:
    evidence_basis = str(edge.get("evidence_basis", "")).strip().lower()
    if evidence_basis:
        return evidence_basis == "structural"
    relation_type = str(edge.get("relation_type", "")).strip().lower()
    if relation_type:
        return relation_type in _STRUCTURAL_RELATION_TYPES
    label = str(edge.get("label") or edge.get("relation") or "").strip().lower()
    if not label:
        return True
    return label in _STRUCTURAL_RELATION_LABELS


def _edge_uses_containment_encoding(
    edge: Mapping[str, Any],
    *,
    anchor_ids: set[str],
    ownership: Mapping[str, str],
) -> bool:
    """Return whether local placement already expresses this membership fact.

    This is a visual encoding decision only. The explicit edge remains in the
    semantic graph and fact ledger; it is not reclassified as a structural
    organizer merely because a frame can communicate it without another arrow.
    """
    source, target = _edge_endpoints(edge)
    relation_type = str(edge.get("relation_type", "")).strip().lower()
    label = str(edge.get("label") or edge.get("relation") or "").strip().lower()
    membership = relation_type in {"composition", "exemplification"}
    topical_focus = relation_type == "association" and label in {
        "emphasizes", "highlights", "focuses on", "addresses", "covers",
    }
    return bool(
        source in anchor_ids
        and target
        and ownership.get(source or "") == ownership.get(target)
        and (membership or topical_focus)
    )


def _display_relation_label(edge: Mapping[str, Any], label: str) -> str:
    """Use a concise canonical label without changing the semantic artifact."""
    relation_type = str(edge.get("relation_type", "")).strip().lower()
    if relation_type == "exemplification":
        # The concept-map contract fixes exemplification direction as
        # category -> example, so this wording is both short and unambiguous.
        return "has example"
    return label


def _semantic_connector_style(
    edge: Mapping[str, Any],
    *,
    cross_branch: bool,
    local_color: str,
) -> Dict[str, Any]:
    """Map relation semantics to a consistent draw.io-style connector grammar."""
    relation_type = str(edge.get("relation_type", "")).strip().lower()
    directionality = str(edge.get("directionality", "")).strip().lower()
    if not directionality:
        directionality = "undirected" if relation_type == "association" else "directed"

    style: Dict[str, Any] = {
        "strokeColor": _NEUTRAL_CONNECTOR if cross_branch else local_color,
        "strokeWidth": 1.35,
        "strokeStyle": "solid",
        "opacity": 82,
        "roughness": 0,
        "startArrowhead": None,
        "endArrowhead": "arrow" if directionality == "directed" else None,
    }
    if relation_type == "association":
        style.update({
            "strokeColor": local_color,
            "strokeStyle": "dashed",
            "strokeWidth": 1.35,
            "opacity": 78,
        })
    elif relation_type == "dependency":
        style.update({"strokeStyle": "dashed", "strokeWidth": 1.1, "opacity": 62})
    elif relation_type in {"composition", "exemplification"}:
        style.update({"strokeWidth": 1.1, "opacity": 68})
    return style


def _infer_core_id(
    nodes: List[Mapping[str, Any]],
    edges: List[Mapping[str, Any]],
) -> Optional[str]:
    """Resolve the concept root from roles first, then directed topology."""
    node_ids = [
        str(node["id"])
        for node in nodes
        if isinstance(node.get("id"), str)
    ]
    explicit = next(
        (
            str(node["id"])
            for node in nodes
            if isinstance(node.get("id"), str)
            and str(node.get("class", "")).lower() in {"core_concept", "core"}
        ),
        None,
    )
    if explicit is not None:
        return explicit

    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
    incoming_count: Dict[str, int] = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        source, target = _edge_endpoints(edge)
        if source not in outgoing or target not in incoming_count:
            continue
        if target not in outgoing[source]:
            outgoing[source].append(target)
            incoming_count[target] += 1

    def reachable_count(start: str) -> int:
        seen = {start}
        frontier = list(outgoing[start])
        while frontier:
            node_id = frontier.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            frontier.extend(outgoing.get(node_id, []))
        return len(seen) - 1

    source_index = {node_id: index for index, node_id in enumerate(node_ids)}
    candidates = [
        node_id
        for node_id in node_ids
        if incoming_count[node_id] == 0 and len(outgoing[node_id]) >= 2
    ]
    if not candidates:
        candidates = [node_id for node_id in node_ids if len(outgoing[node_id]) >= 2]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda node_id: (
            reachable_count(node_id),
            len(outgoing[node_id]),
            -source_index[node_id],
        ),
    )


def _infer_profile(node_count: int) -> Tuple[float, float]:
    if node_count <= 8:
        return 1200.0, 800.0
    if node_count <= 16:
        return 1600.0, 900.0
    # A concept map is cropped to its content. Keeping this logical profile
    # tight makes the root and branch anchors read as one composition instead
    # of four unrelated diagrams at the corners of a large canvas.
    return 1880.0, 1080.0


def _dependency_layers(
    node_ids: Iterable[str],
    edges: Iterable[Mapping[str, Any]],
) -> Dict[int, List[str]]:
    """Group branch-local nodes by longest-path depth."""
    members = list(node_ids)
    member_set = set(members)
    adjacency: Dict[str, List[str]] = {node_id: [] for node_id in members}
    indegree: Dict[str, int] = {node_id: 0 for node_id in members}
    for edge in edges:
        source, target = _edge_endpoints(edge)
        if source in member_set and target in member_set and target not in adjacency[source]:
            adjacency[source].append(target)
            indegree[target] += 1

    depth = {node_id: 0 for node_id in members}
    queue = [node_id for node_id in members if indegree[node_id] == 0]
    while queue:
        source = queue.pop(0)
        for target in adjacency[source]:
            depth[target] = max(depth[target], depth[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    layers: Dict[int, List[str]] = {}
    for node_id in members:
        layers.setdefault(depth[node_id], []).append(node_id)
    return layers


def _branch_interactions(
    edges: Iterable[Mapping[str, Any]],
    ownership: Mapping[str, str],
) -> Dict[Tuple[str, str], float]:
    """Count relations whose endpoints belong to different branches."""
    interactions: Dict[Tuple[str, str], float] = {}
    for edge in edges:
        source, target = _edge_endpoints(edge)
        source_branch = ownership.get(source or "")
        target_branch = ownership.get(target or "")
        if not source_branch or not target_branch or source_branch == target_branch:
            continue
        pair = tuple(sorted((source_branch, target_branch)))
        relation_type = str(edge.get("relation_type", "")).strip().lower()
        weight = 0.25 if relation_type == "association" else 1.0
        interactions[pair] = interactions.get(pair, 0.0) + weight
    return interactions


def _best_branch_order(
    branch_ids: Iterable[str],
    interactions: Mapping[Tuple[str, str], float],
) -> List[str]:
    """Put strongly connected branches next to one another in a row."""
    original = list(branch_ids)
    if len(original) > 7:
        return original
    best = original
    best_cost: Optional[Tuple[float, int]] = None
    original_index = {branch_id: index for index, branch_id in enumerate(original)}
    for candidate in permutations(original):
        positions = {branch_id: index for index, branch_id in enumerate(candidate)}
        distance = sum(
            weight * abs(positions[left] - positions[right])
            for (left, right), weight in interactions.items()
        )
        churn = sum(
            abs(index - original_index[branch_id])
            for index, branch_id in enumerate(candidate)
        )
        # Keep source order stable unless moving a branch materially shortens
        # cross-branch relations. This avoids long divider-like connectors
        # without letting one weak association reshuffle the document.
        cost = (float(distance) + churn * 0.35, churn)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best = list(candidate)
    return best


def _best_radial_slots(
    branch_ids: Iterable[str],
    interactions: Mapping[Tuple[str, str], float],
) -> Dict[str, str]:
    """Assign branches to quadrants so cross-branch relations stay local."""
    branches = list(branch_ids)
    slot_names = ["upper_left", "upper_right", "lower_left", "lower_right"]
    default = {branch_id: branch_id for branch_id in branches if branch_id in slot_names}
    if len(branches) != 4:
        return default

    slot_xy = {
        "upper_left": (0, 0),
        "upper_right": (1, 0),
        "lower_left": (0, 1),
        "lower_right": (1, 1),
    }
    best = default
    best_cost: Optional[Tuple[float, int]] = None
    for assigned_slots in permutations(slot_names):
        candidate = dict(zip(branches, assigned_slots))
        distance = 0.0
        for (left, right), weight in interactions.items():
            if left not in candidate or right not in candidate:
                continue
            lx, ly = slot_xy[candidate[left]]
            rx, ry = slot_xy[candidate[right]]
            distance += weight * (abs(lx - rx) + abs(ly - ry))
        churn = sum(candidate.get(branch_id) != default.get(branch_id) for branch_id in branches)
        cost = (distance, churn)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best = candidate
    return best


def _shape_center(shape: Mapping[str, Any]) -> Tuple[float, float]:
    return (
        _number(shape.get("x")) + _number(shape.get("width")) / 2.0,
        _number(shape.get("y")) + _number(shape.get("height")) / 2.0,
    )


def _place_shared_parents_near_external_peers(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    children: Mapping[str, set[str]],
    parents: Mapping[str, set[str]],
    edges: Iterable[Mapping[str, Any]],
    ownership: Mapping[str, str],
) -> None:
    """Swap equivalent parent slots to shorten external links without changing ranks."""
    external_peers: Dict[str, list[str]] = {}
    for edge in edges:
        source, target = _edge_endpoints(edge)
        if (
            source not in ownership or target not in ownership
            or ownership[source] == ownership[target] or _edge_is_structural(edge)
        ):
            continue
        external_peers.setdefault(source, []).append(target)
        external_peers.setdefault(target, []).append(source)

    def external_distance(node_id: str, position: Tuple[float, float]) -> float:
        distance = 0.0
        for peer in external_peers.get(node_id, []):
            shape = _node_shape(elements_by_id, id_map, peer)
            if shape:
                px, py = _shape_center(shape)
                distance += abs(position[0] - px) + abs(position[1] - py)
        return distance

    hubs = sorted(node_id for node_id in children if len(children[node_id]) >= 2 and not parents[node_id])
    for first, second in combinations(hubs, 2):
        if children[first] != children[second]:
            continue
        a = _node_shape(elements_by_id, id_map, first)
        b = _node_shape(elements_by_id, id_map, second)
        if a is None or b is None:
            continue
        # Equal-sized slots in one column preserve all occupied rectangles;
        # neither parent has an incoming local fact whose order could reverse.
        if any(abs(_number(a.get(key)) - _number(b.get(key))) > 0.01 for key in ("x", "width", "height")):
            continue
        a_center, b_center = _shape_center(a), _shape_center(b)
        lowest_bottom = max(_number(a["y"]) + _number(a["height"]), _number(b["y"]) + _number(b["height"]))
        if any(
            _number((_node_shape(elements_by_id, id_map, child) or {}).get("y")) <= lowest_bottom
            for child in children[first]
        ):
            continue
        before = external_distance(first, a_center) + external_distance(second, b_center)
        after = external_distance(first, b_center) + external_distance(second, a_center)
        if after >= before - 1.0:
            continue
        ax, ay, bx, by = _number(a["x"]), _number(a["y"]), _number(b["x"]), _number(b["y"])
        _move_node(elements_by_id, id_map, first, bx, by)
        _move_node(elements_by_id, id_map, second, ax, ay)


def _segments_cross(
    first: Tuple[float, float, float, float],
    second: Tuple[float, float, float, float],
) -> bool:
    """Return whether two center-to-center edge segments cross properly."""
    ax, ay, bx, by = first
    cx, cy, dx, dy = second

    def orientation(
        px: float,
        py: float,
        qx: float,
        qy: float,
        rx: float,
        ry: float,
    ) -> float:
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    first_c = orientation(ax, ay, bx, by, cx, cy)
    first_d = orientation(ax, ay, bx, by, dx, dy)
    second_a = orientation(cx, cy, dx, dy, ax, ay)
    second_b = orientation(cx, cy, dx, dy, bx, by)
    return first_c * first_d < 0.0 and second_a * second_b < 0.0


def _layout_score(
    manifest: Mapping[str, Any],
    id_map: Mapping[str, str],
    node_ids: Iterable[str],
    edges: Iterable[Mapping[str, Any]],
    structural_edge_ids: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """Score candidate node geometry before the shared router adds arrows."""
    elements_by_id = {
        str(element.get("id")): element
        for element in manifest.get("elements", [])
        if isinstance(element, Mapping) and element.get("id")
    }
    shapes = {
        node_id: _node_shape(elements_by_id, id_map, node_id)
        for node_id in node_ids
    }
    shapes = {node_id: shape for node_id, shape in shapes.items() if shape is not None}
    if not shapes:
        return {"total": float("inf")}

    overlap_pairs: List[List[str]] = []
    shape_items = list(shapes.items())
    for index, (left_id, left) in enumerate(shape_items):
        lx = _number(left.get("x"))
        ly = _number(left.get("y"))
        lr = lx + _number(left.get("width"))
        lb = ly + _number(left.get("height"))
        for right_id, right in shape_items[index + 1:]:
            rx = _number(right.get("x"))
            ry = _number(right.get("y"))
            rr = rx + _number(right.get("width"))
            rb = ry + _number(right.get("height"))
            if min(lr, rr) > max(lx, rx) and min(lb, rb) > max(ly, ry):
                overlap_pairs.append([str(left_id), str(right_id)])

    overlaps = len(overlap_pairs)

    edge_segments: List[Tuple[str, str, Tuple[float, float, float, float]]] = []
    total_edge_length = 0.0
    weighted_edge_length = 0.0
    for edge in edges:
        source, target = _edge_endpoints(edge)
        if source not in shapes or target not in shapes:
            continue
        sx, sy = _shape_center(shapes[source])
        tx, ty = _shape_center(shapes[target])
        edge_length = hypot(tx - sx, ty - sy)
        total_edge_length += edge_length
        edge_id = edge.get("id")
        is_structural = edge_id in (structural_edge_ids or set())
        if not is_structural:
            edge_segments.append((source, target, (sx, sy, tx, ty)))
        # In a grouped composition, core-to-section relationships are encoded
        # primarily by containment. Their hidden/quiet connector geometry must
        # not overpower the visible local and cross-branch relationships.
        edge_weight = 0.12 if is_structural else 1.0
        weighted_edge_length += edge_length * edge_weight

    crossings = 0
    for index, (source, target, segment) in enumerate(edge_segments):
        for other_source, other_target, other_segment in edge_segments[index + 1:]:
            if {source, target} & {other_source, other_target}:
                continue
            if _segments_cross(segment, other_segment):
                crossings += 1

    min_x = min(_number(shape.get("x")) for shape in shapes.values())
    min_y = min(_number(shape.get("y")) for shape in shapes.values())
    max_x = max(_number(shape.get("x")) + _number(shape.get("width")) for shape in shapes.values())
    max_y = max(_number(shape.get("y")) + _number(shape.get("height")) for shape in shapes.values())
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)
    area = width * height
    aspect_ratio = width / height
    if aspect_ratio < 1.15:
        aspect_penalty = abs(log(aspect_ratio / 1.15))
    elif aspect_ratio > 2.05:
        aspect_penalty = abs(log(aspect_ratio / 2.05))
    else:
        aspect_penalty = 0.0
    extreme_aspect_penalty = max(0.0, aspect_ratio - 2.6) ** 2 * 180_000.0
    total = (
        overlaps * 1_000_000_000.0
        + crossings * 1_000_000.0
        + weighted_edge_length
        + area / 180.0
        + aspect_penalty * 70_000.0
        + extreme_aspect_penalty
    )
    return {
        "total": round(total, 3),
        "node_overlaps": float(overlaps),
        "overlap_pairs": overlap_pairs,
        "straight_edge_crossings": float(crossings),
        "edge_length": round(total_edge_length, 3),
        "weighted_edge_length": round(weighted_edge_length, 3),
        "area": round(area, 3),
        "aspect_ratio": round(aspect_ratio, 3),
    }


def _sector_grid(
    node_ids: Iterable[str],
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    sector: Tuple[float, float, float, float],
    anchor_id: str,
    sector_name: str,
    edges: Iterable[Mapping[str, Any]],
    ownership: Mapping[str, str],
) -> List[Tuple[str, float, float]]:
    """Return dependency-layered positions while reserving the anchor."""
    left, top, width, height = sector
    members = [node_id for node_id in node_ids if node_id != anchor_id]
    if not members:
        return []

    member_set = set(members)
    layers = _dependency_layers(members, edges)

    # Order same-rank nodes by the corridor needed by their cross-branch
    # relations. In a left sector, a vertical same-column cross-link belongs
    # at the outer (left) edge while a link to a right sector belongs at the
    # inner edge; mirror that rule on the right. This is the radial equivalent
    # of the barycentric sweep used by layered graph layout engines.
    member_order = {node_id: index for index, node_id in enumerate(members)}
    external_preferences: Dict[str, List[float]] = {node_id: [] for node_id in members}
    sector_is_left = sector_name.endswith("left")
    for edge in edges:
        source, target = _edge_endpoints(edge)
        if source in member_set:
            member_id, other_id = source, target
        elif target in member_set:
            member_id, other_id = target, source
        else:
            continue
        other_sector = ownership.get(other_id or "")
        if not other_sector or other_sector == sector_name:
            continue
        same_column = other_sector.endswith("left") == sector_is_left
        if same_column:
            preference = 0.0 if sector_is_left else 1.0
        else:
            preference = 1.0 if sector_is_left else 0.0
        external_preferences[member_id].append(preference)

    for depth_members in layers.values():
        depth_members.sort(
            key=lambda node_id: (
                (
                    sum(external_preferences[node_id])
                    / len(external_preferences[node_id])
                )
                if external_preferences[node_id]
                else 0.5,
                member_order[node_id],
            )
        )
    max_depth = max(layers)
    upper_sector = sector_name in {"upper_left", "upper_right"}
    outer_y = top + 20.0
    # Leave a real routing channel between the upper branch anchor and its
    # nearest dependency layer. The earlier 0.62/0.72 pair put two fitted
    # labels less than half a node-height apart on dense branches.
    inner_y = top + height * 0.58
    layer_gap = (
        min(120.0, max(90.0, (inner_y - outer_y) / max(1, max_depth)))
        if max_depth
        else 0.0
    )

    positions: List[Tuple[str, float, float]] = []
    for layer_depth in sorted(layers):
        layer = layers[layer_depth]
        widths = []
        heights = []
        for node_id in layer:
            shape = _node_shape(elements_by_id, id_map, node_id)
            widths.append(_number(shape.get("width"), 180.0) if shape else 180.0)
            heights.append(_number(shape.get("height"), 60.0) if shape else 60.0)
        gap = min(72.0, max(40.0, (width - sum(widths)) / (len(layer) + 1)))
        row_width = sum(widths) + gap * (len(layer) - 1)
        cursor_x = left + (width - row_width) / 2.0
        visual_rank = max_depth - layer_depth if upper_sector else layer_depth
        row_y = outer_y + visual_rank * layer_gap if upper_sector else inner_y + visual_rank * layer_gap
        for node_id, node_width, node_height in zip(layer, widths, heights):
            positions.append((node_id, cursor_x, row_y - node_height / 2.0))
            cursor_x += node_width + gap
    return positions


def _apply_radial_candidate(
    manifest: Dict[str, Any],
    id_map: Mapping[str, str],
    node_ids: List[str],
    core_id: str,
    sectors: Mapping[str, str],
    assigned: Mapping[str, str],
    edges: List[Mapping[str, Any]],
    interactions: Mapping[Tuple[str, str], float],
) -> Dict[str, Any]:
    """Lay branches around the root, with topology-selected quadrants."""
    elements_by_id = {
        str(element.get("id")): element
        for element in manifest.get("elements", [])
        if isinstance(element, dict) and element.get("id")
    }
    width, height = _infer_profile(len(node_ids))
    slots = _sectors(width, height)
    slot_by_branch = _best_radial_slots(sectors.keys(), interactions)
    physical_ownership = {
        node_id: slot_by_branch.get(branch_id, branch_id)
        for node_id, branch_id in assigned.items()
    }

    center_shape = _node_shape(elements_by_id, id_map, core_id)
    if center_shape is None:
        return manifest
    _move_node(
        elements_by_id,
        id_map,
        core_id,
        width / 2.0 - _number(center_shape.get("width")) / 2.0,
        height / 2.0 - _number(center_shape.get("height")) / 2.0,
    )

    for branch_id, anchor_id in sectors.items():
        slot_name = slot_by_branch.get(branch_id, branch_id)
        slot = slots.get(slot_name)
        if slot is None:
            continue
        sx, sy, sw, sh = slot
        anchor_shape = _node_shape(elements_by_id, id_map, anchor_id)
        if anchor_shape is None:
            continue
        anchor_on_right = slot_name in {"upper_left", "lower_left"}
        anchor_on_bottom = slot_name in {"upper_left", "upper_right"}
        anchor_x = (
            sx + sw * (0.75 if anchor_on_right else 0.0)
            - _number(anchor_shape.get("width")) / 2.0
        )
        anchor_y = (
            sy + sh * (0.84 if anchor_on_bottom else 0.12)
            - _number(anchor_shape.get("height")) / 2.0
        )
        _move_node(elements_by_id, id_map, anchor_id, anchor_x, anchor_y)

        branch_members = [
            node_id
            for node_id in node_ids
            if node_id not in {core_id, anchor_id}
            and assigned.get(node_id) == branch_id
        ]
        for node_id, x, y in _sector_grid(
            branch_members,
            elements_by_id,
            id_map,
            slot,
            anchor_id,
            slot_name,
            edges,
            physical_ownership,
        ):
            _move_node(elements_by_id, id_map, node_id, x, y)

    manifest["elements"] = list(elements_by_id.values())
    return manifest


def _layer_external_preferences(
    members: Iterable[str],
    edges: Iterable[Mapping[str, Any]],
    ownership: Mapping[str, str],
    branch_positions: Mapping[str, int],
) -> Dict[str, float]:
    """Return a barycentric ordering hint for nodes with cross-branch edges."""
    member_list = list(members)
    preferences: Dict[str, List[float]] = {node_id: [] for node_id in member_list}
    member_set = set(member_list)
    for edge in edges:
        source, target = _edge_endpoints(edge)
        if source in member_set:
            member_id, other_id = source, target
        elif target in member_set:
            member_id, other_id = target, source
        else:
            continue
        other_branch = ownership.get(other_id or "")
        if other_branch in branch_positions:
            preferences[member_id].append(float(branch_positions[other_branch]))
    return {
        node_id: (
            sum(values) / len(values)
            if values
            else float(branch_positions.get(ownership.get(node_id, ""), 0))
        )
        for node_id, values in preferences.items()
    }


def _apply_layered_candidate(
    manifest: Dict[str, Any],
    id_map: Mapping[str, str],
    node_ids: List[str],
    core_id: str,
    sectors: Mapping[str, str],
    assigned: Mapping[str, str],
    edges: List[Mapping[str, Any]],
    interactions: Mapping[Tuple[str, str], float],
) -> Dict[str, Any]:
    """Lay the root above compact branch lanes ordered by cross-links."""
    elements_by_id = {
        str(element.get("id")): element
        for element in manifest.get("elements", [])
        if isinstance(element, dict) and element.get("id")
    }
    branch_order = _best_branch_order(sectors.keys(), interactions)
    branch_positions = {
        branch_id: index for index, branch_id in enumerate(branch_order)
    }
    layers_by_branch: Dict[str, Dict[int, List[str]]] = {}
    lane_widths: Dict[str, float] = {}
    max_nodes_per_row = 3
    row_gap = 36.0

    for branch_id in branch_order:
        anchor_id = sectors[branch_id]
        members = [
            node_id
            for node_id in node_ids
            if node_id not in {core_id, anchor_id}
            and assigned.get(node_id) == branch_id
        ]
        layers = _dependency_layers(members, edges)
        preferences = _layer_external_preferences(
            members,
            edges,
            assigned,
            branch_positions,
        )
        source_order = {node_id: index for index, node_id in enumerate(members)}
        for layer in layers.values():
            layer.sort(
                key=lambda node_id: (
                    preferences[node_id],
                    source_order[node_id],
                )
            )
        layers_by_branch[branch_id] = layers

        anchor_shape = _node_shape(elements_by_id, id_map, anchor_id)
        required_width = _number(anchor_shape.get("width"), 220.0) if anchor_shape else 220.0
        for layer in layers.values():
            for start in range(0, len(layer), max_nodes_per_row):
                chunk = layer[start:start + max_nodes_per_row]
                chunk_width = sum(
                    _number(
                        (_node_shape(elements_by_id, id_map, node_id) or {}).get("width"),
                        160.0,
                    )
                    for node_id in chunk
                ) + row_gap * max(0, len(chunk) - 1)
                required_width = max(required_width, chunk_width)
        lane_widths[branch_id] = min(520.0, max(330.0, required_width + 56.0))

    margin_x = 50.0
    lane_gap = 64.0
    width = (
        margin_x * 2.0
        + sum(lane_widths.values())
        + lane_gap * max(0, len(branch_order) - 1)
    )
    core_shape = _node_shape(elements_by_id, id_map, core_id)
    if core_shape is None:
        return manifest
    _move_node(
        elements_by_id,
        id_map,
        core_id,
        width / 2.0 - _number(core_shape.get("width")) / 2.0,
        36.0,
    )

    lane_left = margin_x
    for branch_id in branch_order:
        lane_width = lane_widths[branch_id]
        anchor_id = sectors[branch_id]
        anchor_shape = _node_shape(elements_by_id, id_map, anchor_id)
        if anchor_shape is None:
            lane_left += lane_width + lane_gap
            continue
        anchor_y = 156.0
        _move_node(
            elements_by_id,
            id_map,
            anchor_id,
            lane_left + (lane_width - _number(anchor_shape.get("width"))) / 2.0,
            anchor_y,
        )

        cursor_y = anchor_y + _number(anchor_shape.get("height")) + 70.0
        for layer_depth in sorted(layers_by_branch[branch_id]):
            layer = layers_by_branch[branch_id][layer_depth]
            for start in range(0, len(layer), max_nodes_per_row):
                chunk = layer[start:start + max_nodes_per_row]
                shapes = [
                    _node_shape(elements_by_id, id_map, node_id)
                    for node_id in chunk
                ]
                widths = [
                    _number(shape.get("width"), 160.0) if shape else 160.0
                    for shape in shapes
                ]
                heights = [
                    _number(shape.get("height"), 50.0) if shape else 50.0
                    for shape in shapes
                ]
                row_width = sum(widths) + row_gap * max(0, len(chunk) - 1)
                cursor_x = lane_left + (lane_width - row_width) / 2.0
                for node_id, node_width, node_height in zip(chunk, widths, heights):
                    _move_node(
                        elements_by_id,
                        id_map,
                        node_id,
                        cursor_x,
                        cursor_y - node_height / 2.0,
                    )
                    cursor_x += node_width + row_gap
                cursor_y += max(heights) + 46.0
            cursor_y += 24.0
        lane_left += lane_width + lane_gap

    manifest["elements"] = list(elements_by_id.values())
    return manifest


def _stacked_branch_rows(
    members: List[str],
    edges: List[Mapping[str, Any]],
    anchor_id: Optional[str] = None,
    max_nodes_per_row: int = 4,
    horizontal_chains: bool = True,
) -> List[List[str]]:
    """Turn relation ranks into compact rows, keeping short chains horizontal."""
    if not members:
        return []
    layers = _dependency_layers(members, edges)
    if anchor_id is not None:
        member_set = set(members)
        semantic_targets = {
            target
            for edge in edges
            for source, target in [_edge_endpoints(edge)]
            if source == anchor_id
            and target in member_set
            and str(edge.get("relation_type", "")).strip().lower()
            in {"causal", "dependency"}
        }
        if semantic_targets:
            depth_by_node = {
                node_id: depth
                for depth, layer in layers.items()
                for node_id in layer
            }
            for target in semantic_targets:
                depth = depth_by_node.get(target, 0)
                if depth > 0:
                    continue
                layers[0] = [node_id for node_id in layers.get(0, []) if node_id != target]
                layers.setdefault(1, []).append(target)
            layers = {depth: layer for depth, layer in layers.items() if layer}
    ordered_depths = sorted(layers)
    if horizontal_chains and len(ordered_depths) > 1 and all(len(layers[depth]) == 1 for depth in ordered_depths):
        chain = [layers[depth][0] for depth in ordered_depths]
        directed_pairs = {
            (source, target)
            for edge in edges
            for source, target in [_edge_endpoints(edge)]
            if source in set(chain) and target in set(chain)
        }
        if all(pair in directed_pairs for pair in zip(chain, chain[1:])):
            return [
                chain[start:start + max_nodes_per_row]
                for start in range(0, len(chain), max_nodes_per_row)
            ]

    rows: List[List[str]] = []
    for depth in ordered_depths:
        layer = layers[depth]
        for start in range(0, len(layer), max_nodes_per_row):
            rows.append(layer[start:start + max_nodes_per_row])
    return rows


def _apply_stacked_bands_candidate(
    manifest: Dict[str, Any],
    id_map: Mapping[str, str],
    node_ids: List[str],
    core_id: str,
    sectors: Mapping[str, str],
    assigned: Mapping[str, str],
    edges: List[Mapping[str, Any]],
    interactions: Mapping[Tuple[str, str], float],
    columns: int = 1,
) -> Dict[str, Any]:
    """Compose concept branches as draw.io-like horizontal group bands."""
    elements_by_id = {
        str(element.get("id")): element
        for element in manifest.get("elements", [])
        if isinstance(element, dict) and element.get("id")
    }
    candidate_id_map = id_map_from_manifest(manifest)
    branch_order = _best_branch_order(sectors.keys(), interactions)
    if columns > 1:
        original = list(sectors)
        original_index = {branch: index for index, branch in enumerate(original)}

        def grid_cost(order: Tuple[str, ...]) -> Tuple[float, int]:
            positions = {branch: (index % columns, index // columns) for index, branch in enumerate(order)}
            distance = sum(
                weight * (abs(positions[left][0] - positions[right][0]) + abs(positions[left][1] - positions[right][1]))
                for (left, right), weight in interactions.items()
                if left in positions and right in positions
            )
            return distance, sum(abs(index - original_index[branch]) for index, branch in enumerate(order))

        branch_order = list(min(permutations(original), key=grid_cost))

    outer_x = 40.0
    anchor_ids = set(sectors.values())
    connected_anchors = {
        node_id
        for edge in edges
        if not _edge_is_structural(edge)
        and not _edge_uses_containment_encoding(
            edge, anchor_ids=anchor_ids, ownership=assigned
        )
        for node_id in _edge_endpoints(edge)
        if node_id in anchor_ids
    }
    header_text_widths = [
        _number(text.get("width"))
        for anchor_id in anchor_ids
        for shape in [_node_shape(elements_by_id, id_map, anchor_id)]
        if shape is not None
        for text in _bound_text_elements(elements_by_id, shape)
    ]
    header_width = min(
        256.0,
        max(
            160.0,
            ceil((max(header_text_widths, default=136.0) + 24.0) / 8.0) * 8.0,
        ),
    )
    max_nodes_per_row = 3 if columns > 1 else (2 if len(sectors) == 2 else (3 if len(sectors) == 3 else 4))
    branch_rows = {
        branch_id: _stacked_branch_rows(
            [
                node_id
                for node_id in node_ids
                if node_id not in {core_id, *anchor_ids}
                and assigned.get(node_id) == branch_id
            ],
            edges,
            anchor_id=sectors[branch_id],
            max_nodes_per_row=max_nodes_per_row,
            horizontal_chains=columns == 1,
        )
        for branch_id in sectors
    }
    branch_row_widths = {
        branch_id: max((
            sum(
                _number((_node_shape(elements_by_id, id_map, node_id) or {}).get("width"), 168.0)
                for node_id in row
            )
            + (64.0 if columns > 1 else 32.0) * max(0, len(row) - 1)
            for row in rows
        ), default=0.0)
        for branch_id, rows in branch_rows.items()
    }
    widest_row = max(branch_row_widths.values(), default=0.0)
    header_x = outer_x + 24.0
    content_left = outer_x + 24.0
    base_canvas_width = 800.0 if len(sectors) <= 3 else 960.0
    canvas_width = max(
        base_canvas_width,
        content_left + widest_row + outer_x + 24.0,
    )
    band_width = canvas_width - 2.0 * outer_x
    column_gap = 80.0
    column_widths = [band_width]
    if columns > 1:
        # Align frames within a column without making a sparse column inherit
        # the widest row of a different column.
        column_widths = [
            max(620.0, max(
                (branch_row_widths[branch] + 48.0 for branch in branch_order[column::columns]),
                default=0.0,
            ))
            for column in range(columns)
        ]
        canvas_width = 2.0 * outer_x + sum(column_widths) + (columns - 1) * column_gap
    title_shape = _node_shape(elements_by_id, id_map, core_id)
    if title_shape is None:
        return manifest
    title_width = min(440.0, _number(title_shape.get("width"), 440.0)) if columns > 1 else band_width
    _resize_node(elements_by_id, id_map, core_id, title_width, 52.0)
    _move_node(elements_by_id, id_map, core_id, (canvas_width - title_width) / 2.0, 28.0)
    if columns > 1:
        title_shape.update({"backgroundColor": "transparent", "strokeColor": "transparent", "strokeWidth": 0})
    for text in _bound_text_elements(elements_by_id, title_shape):
        text["fontSize"] = 28 if columns > 1 else 22
        if columns > 1:
            text["strokeColor"] = "#202A36"
        text["lineHeight"] = 1.15
    _sync_bound_text(elements_by_id, title_shape)

    current_y = 112.0
    row_gap_y = 56.0
    band_gap = 48.0 if columns > 1 else 24.0
    branch_heights = {
        branch_id: max(136.0, 80.0 + sum(
            max(_number((_node_shape(elements_by_id, id_map, node_id) or {}).get("height"), 52.0) for node_id in row)
            for row in rows
        ) + row_gap_y * max(0, len(rows) - 1))
        for branch_id, rows in branch_rows.items()
    }

    for branch_index, branch_id in enumerate(branch_order):
        column = branch_index % columns
        band_width = column_widths[column]
        content_width = band_width - 48.0
        band_x = outer_x + sum(column_widths[:column]) + column * column_gap
        header_x = band_x + 24.0
        content_left = band_x + 24.0
        anchor_id = sectors[branch_id]
        anchor_shape = _node_shape(elements_by_id, id_map, anchor_id)
        if anchor_shape is None:
            continue
        rows = branch_rows[branch_id]
        row_heights = [
            max(
                _number((_node_shape(elements_by_id, id_map, node_id) or {}).get("height"), 52.0)
                for node_id in row
            )
            for row in rows
        ]
        content_height = (
            sum(row_heights) + row_gap_y * max(0, len(rows) - 1)
            if rows
            else 56.0
        )
        band_height = max(136.0, content_height + 80.0)
        if columns > 1:
            row_start = branch_index - column
            band_height = max(branch_heights[branch] for branch in branch_order[row_start:row_start + columns])

        # In a stacked composition the frame already carries containment.
        # A heading that also participates in a fact needs a visible boundary
        # so its connector does not appear to originate in empty space.
        local_header_width = max(
            (_number(text.get("width")) + 20.0 for text in _bound_text_elements(elements_by_id, anchor_shape)),
            default=header_width,
        )
        _resize_node(elements_by_id, id_map, anchor_id, local_header_width, 32.0)
        _move_node(
            elements_by_id,
            id_map,
            anchor_id,
            header_x,
            current_y + 12.0,
        )
        anchor_shape = _node_shape(elements_by_id, id_map, anchor_id)
        if anchor_shape is not None:
            palette = _palette_for_branch(branch_id)
            connected = anchor_id in connected_anchors
            anchor_shape.setdefault("meta", {})["conceptFactAnchor"] = connected
            anchor_shape["backgroundColor"] = palette["leaf"] if connected else "transparent"
            anchor_shape["strokeColor"] = palette["stroke"] if connected else "transparent"
            anchor_shape["strokeWidth"] = 1.0 if connected else 0.0
            anchor_shape.setdefault("meta", {})["conceptSectionColor"] = (
                _palette_for_branch(branch_id)["stroke"]
            )
            for text in _bound_text_elements(elements_by_id, anchor_shape):
                text["fontSize"] = _SECTION_FONT_SIZE
                text["fontStyle"] = 1
                text["strokeColor"] = _palette_for_branch(branch_id)["text"]
                text["lineHeight"] = 1.15
            _sync_bound_text(elements_by_id, anchor_shape)
            for text in _bound_text_elements(elements_by_id, anchor_shape):
                text["x"] = header_x + 10.0

        row_y = current_y + 56.0
        for row, row_height in zip(rows, row_heights):
            row_widths = [
                _number((_node_shape(elements_by_id, id_map, node_id) or {}).get("width"), 168.0)
                for node_id in row
            ]
            if len(row) > 1:
                gap_x = min(
                    104.0,
                    max(32.0, (content_width - sum(row_widths)) / (len(row) - 1)),
                )
            else:
                gap_x = 0.0
            occupied_width = sum(row_widths) + gap_x * max(0, len(row) - 1)
            cursor_x = content_left + max(0.0, (content_width - occupied_width) / 2.0)
            for node_id, node_width in zip(row, row_widths):
                shape = _node_shape(elements_by_id, id_map, node_id)
                node_height = _number(shape.get("height"), 52.0) if shape else 52.0
                _move_node(
                    elements_by_id,
                    id_map,
                    node_id,
                    cursor_x,
                    row_y + (row_height - node_height) / 2.0,
                )
                cursor_x += node_width + gap_x
            row_y += row_height + row_gap_y

        frame = _concept_frame(
            anchor_id,
            branch_id,
            band_x,
            current_y,
            band_width,
            band_height,
        )
        frame["meta"] = {
            "conceptBranch": branch_id,
            "semanticId": f"{anchor_id}:background",
            "memberIds": [
                candidate_id_map[node_id]
                for node_id in node_ids
                if assigned.get(node_id) == branch_id and node_id in candidate_id_map
            ],
        }
        elements_by_id[frame["id"]] = frame
        candidate_id_map[f"{anchor_id}:background"] = frame["id"]
        if column == columns - 1 or branch_index == len(branch_order) - 1:
            current_y += band_height + band_gap

    if columns > 1:
        # A cross-section target belongs on the side nearest its peer. For
        # example, a left-hand section should not enter the rightmost card
        # through all the intervening cards in another section's row.
        for branch_id, rows in branch_rows.items():
            frame = elements_by_id[candidate_id_map[f"{sectors[branch_id]}:background"]]
            center_x = _number(frame["x"]) + _number(frame["width"]) / 2.0

            def external_side(node_id: str) -> int:
                peers = [
                    target if source == node_id else source
                    for edge in edges
                    for source, target in [_edge_endpoints(edge)]
                    if node_id in {source, target}
                    and source in assigned and target in assigned
                    and assigned[source] != assigned[target]
                ]
                if not peers:
                    return 0
                peer_x = sum(_shape_center(_node_shape(elements_by_id, id_map, peer) or {})[0] for peer in peers) / len(peers)
                offset = peer_x - center_x
                threshold = _number(frame["width"]) / 4.0
                return -1 if offset < -threshold else (1 if offset > threshold else 0)

            for row in rows:
                slots = [(_number((_node_shape(elements_by_id, id_map, node_id) or {}).get("x")), _number((_node_shape(elements_by_id, id_map, node_id) or {}).get("y"))) for node_id in row]
                for node_id, (x, y) in zip(sorted(row, key=external_side), slots):
                    _move_node(elements_by_id, id_map, node_id, x, y)

            if max((len(row) for row in rows), default=0) < 3:
                continue
            members = {node_id for row in rows for node_id in row}
            children = {node_id: set() for node_id in members}
            parents = {node_id: set() for node_id in members}
            for edge in edges:
                source, target = _edge_endpoints(edge)
                if source in members and target in members and not _edge_is_structural(edge):
                    children[source].add(target)
                    parents[target].add(source)

            def place_in_column(node_id: str, column: int) -> None:
                shape = _node_shape(elements_by_id, id_map, node_id)
                if shape is None:
                    return
                width = _number(shape.get("width"))
                left = _number(frame["x"]) + 24.0
                span = _number(frame["width"]) - 48.0 - width
                _move_node(elements_by_id, id_map, node_id, left + span * column / 2.0, _number(shape.get("y")))

            for row in rows:
                if len(row) != 2:
                    continue
                hubs = [node_id for node_id in row if len(children[node_id]) >= 2]
                if len(hubs) == 1:
                    # Align the fan-out parent with the center of its outcomes;
                    # an unrelated peer can occupy an outer grid column.
                    hub = hubs[0]
                    peer = next(node_id for node_id in row if node_id != hub)
                    place_in_column(hub, 1)
                    place_in_column(peer, 2 if external_side(peer) > 0 else 0)
                elif len(parents[row[0]] & parents[row[1]]) >= 2:
                    # Shared outcomes need separate channels for each parent.
                    ordered = sorted(row, key=lambda node_id: _number((_node_shape(elements_by_id, id_map, node_id) or {}).get("x")))
                    place_in_column(ordered[0], 0)
                    place_in_column(ordered[1], 2)

            _place_shared_parents_near_external_peers(
                elements_by_id, id_map, children, parents, edges, assigned,
            )

    manifest["elements"] = list(elements_by_id.values())
    metadata = manifest.setdefault("_meta", {})
    if isinstance(metadata, dict):
        metadata["id_map"] = candidate_id_map
    return manifest


def _refresh_edge_ports(
    manifest: Dict[str, Any],
    id_map: Mapping[str, str],
    edges: Iterable[Mapping[str, Any]],
    core_id: str,
    ownership: Mapping[str, str],
) -> None:
    """Synchronize layout-owned port intent with the selected geometry."""
    metadata = manifest.get("_meta")
    if not isinstance(metadata, dict):
        return
    edge_data = metadata.get("edge_data")
    if not isinstance(edge_data, dict):
        return
    elements_by_id = {
        str(element.get("id")): element
        for element in manifest.get("elements", [])
        if isinstance(element, dict) and element.get("id")
    }

    for edge in edges:
        edge_id = edge.get("id")
        source, target = _edge_endpoints(edge)
        if not isinstance(edge_id, str) or source is None or target is None:
            continue
        payload = edge_data.get(edge_id)
        if not isinstance(payload, dict):
            continue
        source_shape = _node_shape(elements_by_id, id_map, source)
        target_shape = _node_shape(elements_by_id, id_map, target)
        if source_shape is None or target_shape is None:
            continue
        source_x, source_y = _shape_center(source_shape)
        target_x, target_y = _shape_center(target_shape)
        source_top = _number(source_shape.get("y"))
        source_bottom = source_top + _number(source_shape.get("height"))
        target_top = _number(target_shape.get("y"))
        target_bottom = target_top + _number(target_shape.get("height"))
        source_branch = ownership.get(source)
        target_branch = ownership.get(target)
        hierarchical = (
            source == core_id
            or (source_branch is not None and source_branch == target_branch)
        )
        vertical_clearance = (
            target_top - source_bottom
            if target_y >= source_y
            else source_top - target_bottom
        )
        # Center points can differ even while the node bounds overlap. Using
        # top/bottom ports in that case creates a nearly flat path whose long
        # segment rides along (or inside) the target border. Reserve vertical
        # ports for geometry with an actual approach corridor.
        if hierarchical and vertical_clearance >= 16.0:
            if target_y >= source_y:
                start_side, end_side = "bottom", "top"
            else:
                start_side, end_side = "top", "bottom"
        elif target_x >= source_x:
            start_side, end_side = "right", "left"
        else:
            start_side, end_side = "left", "right"
        payload["start"] = {"elementId": source, "side": start_side}
        payload["end"] = {"elementId": target, "side": end_side}
        payload["routing"] = "elbowed"
        payload["_layoutCrossBranch"] = bool(
            source_branch is not None
            and target_branch is not None
            and source_branch != target_branch
        )


def _set_structural_edge_visibility(
    manifest: Dict[str, Any],
    edges: Iterable[Mapping[str, Any]],
    structural_edge_ids: set[str],
    core_id: str,
    ownership: Mapping[str, str],
    *,
    hidden_by_containment: bool,
) -> None:
    """Hide hierarchy links only when group frames already express ownership."""
    metadata = manifest.get("_meta")
    edge_data = metadata.get("edge_data") if isinstance(metadata, dict) else None
    if not isinstance(edge_data, dict):
        return
    for edge in edges:
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or edge_id not in structural_edge_ids:
            continue
        payload = edge_data.get(edge_id)
        if not isinstance(payload, dict):
            continue
        source, _ = _edge_endpoints(edge)
        owner = ownership.get(source or "")
        palette = _palette_for_branch(owner) if owner else None
        payload.update({
            "strokeColor": (
                _STRUCTURAL_CONNECTOR
                if source == core_id or palette is None
                else palette["stroke"]
            ),
            "strokeWidth": 1.0,
            "strokeStyle": "solid",
            "opacity": 0 if hidden_by_containment else 58,
            "roughness": 0,
            "startArrowhead": None,
            "endArrowhead": None,
            "_suppressLabel": True,
        })


def compact_concept_map_layout(
    manifest: Dict[str, Any],
    structure_instantiation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Select the best deterministic candidate before connector routing.

    This pass owns only node positions. It compares a compact radial candidate
    with a layered branch-lane candidate using the semantic graph and real
    post-fit node sizes. Edge geometry remains owned by ``arrow_adder``.
    """
    if not isinstance(manifest, dict) or not isinstance(structure_instantiation, dict):
        return manifest
    structure = unwrap_structure_instantiation(structure_instantiation)
    chart_type = str(structure.get("chart_type", "")).strip().lower()
    if chart_type not in _CONCEPT_MAP:
        return manifest

    nodes = [node for node in structure.get("nodes", []) or [] if isinstance(node, Mapping)]
    edges = [edge for edge in structure.get("edges", []) or [] if isinstance(edge, Mapping)]
    if len(nodes) < 5:
        return manifest
    node_ids = [str(node.get("id")) for node in nodes if isinstance(node.get("id"), str)]
    node_by_id = {str(node.get("id")): node for node in nodes if isinstance(node.get("id"), str)}
    core_id = _infer_core_id(nodes, edges)
    if core_id is None:
        return manifest

    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
    incoming: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source, target = _edge_endpoints(edge)
        if source in outgoing and target in incoming:
            outgoing[source].append(target)
            incoming[target].append(source)

    has_explicit_branch_ids = any("branch_id" in node for node in nodes)
    anchor_ids = [
        node_id for node_id in node_ids
        if node_id != core_id and (
            str(node_by_id[node_id].get("class", "")).lower()
            in {"branch_anchor", "category"}
            or (
                has_explicit_branch_ids
                and node_by_id[node_id].get("branch_id") == node_id
            )
            or (
                not has_explicit_branch_ids
                and (
                    core_id in incoming.get(node_id, [])
                    or core_id in outgoing.get(node_id, [])
                )
            )
        )
    ]
    sectors: Dict[str, str] = {}
    for index, anchor_id in enumerate(anchor_ids):
        branch_id = (
            _SLOT_ORDER[index]
            if index < len(_SLOT_ORDER)
            else f"branch_{index - len(_SLOT_ORDER) + 1}"
        )
        sectors[branch_id] = anchor_id
    if len(sectors) < 2:
        return manifest

    output = deepcopy(manifest)
    elements_by_id = {
        str(element.get("id")): element
        for element in output.get("elements", [])
        if isinstance(element, dict) and element.get("id")
    }
    id_map = id_map_from_manifest(output)
    center_shape = _node_shape(elements_by_id, id_map, core_id)
    if center_shape is None:
        return manifest

    # Prefer explicit branch ownership; legacy structures fall back to direct
    # anchor children and graph propagation. This mirrors draw.io's compartment
    # model: ownership is structural, while cross-links remain routing-only.
    assigned: Dict[str, str] = {anchor_id: sector for sector, anchor_id in sectors.items()}
    sector_by_anchor = {anchor_id: sector for sector, anchor_id in sectors.items()}
    for node in nodes:
        node_id = node.get("id")
        branch_id = node.get("branch_id")
        if not isinstance(node_id, str) or not isinstance(branch_id, str):
            continue
        sector = sector_by_anchor.get(branch_id)
        if sector is not None and node_id != core_id:
            assigned[node_id] = sector

    for edge in edges:
        source, target = _edge_endpoints(edge)
        sector = sector_by_anchor.get(source or "")
        if sector is None or target is None:
            continue
        if has_explicit_branch_ids and not _edge_is_structural(edge):
            continue
        if target not in assigned and target not in {core_id, *sectors.values()}:
            assigned[target] = sector

    # Propagate ownership globally in the source edge order.  This is
    # intentionally done across all branches at once: a cross-link must not
    # claim a node already reached through its primary structural path.
    # The first structural path wins; later cross-links remain routed edges.
    changed = True
    while changed:
        changed = False
        for edge in edges:
            source, target = _edge_endpoints(edge)
            if source is None or target is None or target in assigned:
                continue
            if has_explicit_branch_ids and not _edge_is_structural(edge):
                continue
            owner = assigned.get(source)
            if owner is None or target in {core_id, *sectors.values()}:
                continue
            assigned[target] = owner
            changed = True

    # Legacy structures without branch_id may still need a convergence-based
    # ownership correction. Require at least two agreeing parents and a strict
    # majority so a single isolated cross-link cannot steal ownership.
    reassigned: set[str] = set()
    for _ in range(len(node_ids)):
        updates: Dict[str, str] = {}
        for target in node_ids:
            if target in {core_id, *sectors.values()}:
                continue
            if has_explicit_branch_ids and isinstance(
                node_by_id[target].get("branch_id"),
                str,
            ):
                continue
            owner_counts: Dict[str, int] = {}
            for source in set(incoming.get(target, [])):
                owner = assigned.get(source)
                if owner is not None:
                    owner_counts[owner] = owner_counts.get(owner, 0) + 1
            if not owner_counts:
                continue
            ranked = sorted(owner_counts.items(), key=lambda item: (-item[1], item[0]))
            best_owner, best_count = ranked[0]
            current_owner = assigned.get(target)
            current_count = owner_counts.get(current_owner, 0)
            runner_up = ranked[1][1] if len(ranked) > 1 else 0
            if best_count >= 2 and best_count > current_count and best_count > runner_up:
                updates[target] = best_owner
        if not updates:
            break
        assigned.update(updates)
        reassigned.update(updates)

    # Styling is generated before this deterministic graph pass. Keep it
    # semantically aligned with any ownership correction by inheriting the
    # winning branch anchor's palette, without changing size or node shape.
    for node_id in reassigned:
        owner = assigned.get(node_id)
        anchor_id = sectors.get(owner or "")
        shape = _node_shape(elements_by_id, id_map, node_id)
        anchor_shape = _node_shape(elements_by_id, id_map, anchor_id) if anchor_id else None
        if shape is None or anchor_shape is None:
            continue
        for key in ("backgroundColor", "strokeColor"):
            if anchor_shape.get(key) is not None:
                shape[key] = anchor_shape[key]

    # Styling models previously encoded hierarchy with wide ellipses and a
    # mix of sharp boxes. Normalize to draw.io's restrained default language:
    # one rounded-rectangle family, consistent peer dimensions, and hierarchy
    # carried by title/header/leaf treatments rather than arbitrary geometry.
    _normalize_concept_shape_language(
        elements_by_id,
        id_map,
        node_ids,
        core_id,
        sectors,
        assigned,
        category_ids={
            source
            for edge in edges
            if str(edge.get("relation_type", "")).strip().lower() == "exemplification"
            for source, target in [_edge_endpoints(edge)]
            if source in assigned and assigned.get(source) == assigned.get(target)
        },
    )

    anchor_id_set = set(sectors.values())
    has_relation_metadata = any(
        isinstance(edge.get("relation_type"), str)
        and bool(str(edge.get("relation_type")).strip())
        for edge in edges
    )
    structural_edge_ids = {
        str(edge.get("id"))
        for edge in edges
        if (
            (
                _edge_endpoints(edge)[0] == core_id
                and _edge_endpoints(edge)[1] in anchor_id_set
            )
            or (
                _edge_endpoints(edge)[0] in anchor_id_set
                and assigned.get(_edge_endpoints(edge)[0] or "")
                == assigned.get(_edge_endpoints(edge)[1] or "")
            )
        )
        and (not has_relation_metadata or _edge_is_structural(edge))
        and isinstance(edge.get("id"), str)
    }
    containment_edge_ids = {
        str(edge.get("id"))
        for edge in edges
        if isinstance(edge.get("id"), str)
        and _edge_uses_containment_encoding(
            edge,
            anchor_ids=anchor_id_set,
            ownership=assigned,
        )
    }
    metadata = output.get("_meta")
    edge_data = metadata.get("edge_data") if isinstance(metadata, dict) else None
    if isinstance(edge_data, dict):
        for edge in edges:
            edge_id = edge.get("id")
            if not isinstance(edge_id, str):
                continue
            payload = edge_data.get(edge_id)
            if not isinstance(payload, dict):
                continue
            # Layout selection is replayable. Never inherit a suppression
            # decision from an older topology classification; the current
            # structure below will mark organizer edges again as needed.
            payload.pop("_suppressLabel", None)
            source, target = _edge_endpoints(edge)
            source_owner = assigned.get(source or "")
            target_owner = assigned.get(target or "")
            if edge_id in structural_edge_ids or edge_id in containment_edge_ids:
                payload.update({
                    "strokeColor": _STRUCTURAL_CONNECTOR,
                    "strokeWidth": 1.0,
                    "strokeStyle": "solid",
                    "opacity": 0,
                    "roughness": 0,
                    "startArrowhead": None,
                    "endArrowhead": None,
                    "_suppressLabel": True,
                })
            else:
                label_payload = payload.get("label")
                label_text = (
                    str(label_payload.get("text", ""))
                    if isinstance(label_payload, Mapping)
                    else str(label_payload or "")
                )
                label_text = _display_relation_label(edge, label_text)
                palette = _palette_for_branch(source_owner) if source_owner else None
                payload.update(_semantic_connector_style(
                    edge,
                    cross_branch=bool(
                        source_owner and target_owner and source_owner != target_owner
                    ),
                    local_color=palette["stroke"] if palette else _NEUTRAL_CONNECTOR,
                ))
                payload.update({
                    # Line styles distinguish relation families, but cannot
                    # express the predicate. Preserve facts on the canvas;
                    # containment already removes organizer-only labels.
                    "_suppressLabel": False,
                    "label": {
                        "text": label_text,
                        "fontSize": _RELATION_FONT_SIZE,
                        "fontFamily": 2,
                        "strokeColor": "#39434D",
                    },
                })

    output["elements"] = list(elements_by_id.values())
    interactions = _branch_interactions(edges, assigned)
    candidates = {
        "stacked_bands": _apply_stacked_bands_candidate(
            deepcopy(output),
            id_map,
            node_ids,
            core_id,
            sectors,
            assigned,
            edges,
            interactions,
        ),
        "layered_lanes": _apply_layered_candidate(
            deepcopy(output),
            id_map,
            node_ids,
            core_id,
            sectors,
            assigned,
            edges,
            interactions,
        ),
    }
    if len(sectors) in {2, 4}:
        candidates["panel_grid"] = _apply_stacked_bands_candidate(
            deepcopy(output), id_map, node_ids, core_id, sectors, assigned,
            edges, interactions, columns=2,
        )
    if len(sectors) <= len(_SLOT_ORDER):
        candidates["compact_radial"] = _apply_radial_candidate(
            deepcopy(output),
            id_map,
            node_ids,
            core_id,
            sectors,
            assigned,
            edges,
            interactions,
        )
    scores = {
        name: _layout_score(
            candidate,
            id_map,
            node_ids,
            edges,
            structural_edge_ids,
        )
        for name, candidate in candidates.items()
    }
    stacked_score = scores.get("stacked_bands", {})
    stacked_is_viable = (
        len(sectors) >= 2
        and stacked_score.get("node_overlaps") == 0
        and 0.85 <= _number(stacked_score.get("aspect_ratio")) <= 2.75
    )
    # Draw.io's composition grammar is organizer-first: once a graph has
    # several stable semantic branches, containment and aligned regions are a
    # stronger readability signal than a center-to-center crossing estimate.
    # The shared router will compute the actual orthogonal paths afterward.
    selected_name = (
        "stacked_bands"
        if stacked_is_viable
        else min(scores, key=lambda name: scores[name]["total"])
    )
    panel_score = scores.get("panel_grid", {})
    if (
        panel_score.get("node_overlaps") == 0
        and 1.15 <= _number(panel_score.get("aspect_ratio")) <= 2.5
    ):
        selected_name = "panel_grid"
    selected = candidates[selected_name]
    _set_structural_edge_visibility(
        selected,
        edges,
        structural_edge_ids,
        core_id,
        assigned,
        hidden_by_containment=selected_name in {"stacked_bands", "panel_grid"},
    )
    _refresh_edge_ports(selected, id_map, edges, core_id, assigned)
    metadata = selected.setdefault("_meta", {})
    if isinstance(metadata, dict):
        metadata["concept_layout_selection"] = {
            "strategy": selected_name,
            "scores": scores,
        }
    logger.info(
        "[ConceptLayout] selected %s from %s",
        selected_name,
        {name: score["total"] for name, score in scores.items()},
    )
    return selected


__all__ = ["compact_concept_map_layout"]
