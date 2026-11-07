"""Face selection and port/corridor ranks, decided for all edges at once.

Each edge becomes a plan dict holding its relation, endpoint shapes, chosen
faces and obstacles. Ranks are then assigned across siblings so that edges
sharing a node face fan out instead of collapsing onto the face midpoint.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ...shared.edge_routing import (
    audit_sides,
    extract_side_from_port,
    find_shape_id,
    normalize_port,
    resolve_edge_payload,
    shape_bbox,
)
from .context import DiagramContext
from .detours import ObstacleIndex, _edge_obstacles, _prefer_clear_port_pair
from .geometry import _bbox_center

logger = logging.getLogger(__name__)

EdgePlan = Dict[str, Any]


@dataclass
class PortTotals:
    # (source, start_side, end_side) -> edges sharing one bend corridor
    corridor_counts: Dict[Tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    # (node, side) -> edges using that face, outgoing and incoming
    source_port_counts: Dict[Tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    target_port_counts: Dict[Tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    source_degrees: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    target_degrees: Dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _architecture_port_hint(
    source_ref: str,
    target_ref: str,
    source_shape: Dict[str, Any],
    target_shape: Dict[str, Any],
    node_group_ids: Dict[str, str],
    side_group_ids: set[str],
) -> Optional[Dict[str, str]]:
    """Choose architecture ports from layer semantics before raw geometry."""
    source_group = node_group_ids.get(source_ref, "")
    target_group = node_group_ids.get(target_ref, "")
    source_bbox = shape_bbox(source_shape)
    target_bbox = shape_bbox(target_shape)
    source_x, source_y = _bbox_center(source_bbox)
    target_x, target_y = _bbox_center(target_bbox)

    if target_group in side_group_ids or source_group in side_group_ids:
        return (
            {"start": "right", "end": "left"}
            if source_x <= target_x
            else {"start": "left", "end": "right"}
        )

    inter_layer = source_group and target_group and source_group != target_group
    row_separation = abs(target_y - source_y)
    min_vertical_gap = max(source_bbox["h"], target_bbox["h"]) + 24.0
    if inter_layer or row_separation >= min_vertical_gap:
        return (
            {"start": "bottom", "end": "top"}
            if source_y <= target_y
            else {"start": "top", "end": "bottom"}
        )
    return None


def _port_hint(
    rel: Dict[str, Any],
    port_hints: Dict[str, Any],
    edge_payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Authored faces: structure hints, then relation ports, then layout ports."""
    edge_id = rel.get("id", "")
    hinted = port_hints.get(edge_id) if isinstance(edge_id, str) else None
    if not hinted:
        start_hint = normalize_port(rel.get("start"))
        end_hint = normalize_port(rel.get("end"))
        if start_hint and end_hint:
            hinted = {"start": start_hint, "end": end_hint}
    if not hinted and edge_payload:
        start_hint = extract_side_from_port(edge_payload.get("start"))
        end_hint = extract_side_from_port(edge_payload.get("end"))
        if start_hint or end_hint:
            hinted = {"start": start_hint, "end": end_hint}
    return hinted


def _plan_edges(
    relations: List[Dict[str, Any]],
    store: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    edge_data: Dict[str, Any],
    port_hints: Dict[str, Any],
    diagram: DiagramContext,
    obstacle_index: ObstacleIndex,
) -> List[EdgePlan]:
    """Resolve each relation's shapes and faces; drop relations without shapes."""
    plans: List[EdgePlan] = []
    for rel in relations:
        source_ref = rel.get("source", "")
        target_ref = rel.get("target", "")
        edge_payload = resolve_edge_payload(edge_data, rel.get("id", ""))

        source_shape_key = find_shape_id(store, source_ref, structure_instantiation)
        target_shape_key = find_shape_id(store, target_ref, structure_instantiation)
        if not (source_shape_key and target_shape_key):
            logger.warning(
                f"Could not find shapes for relation source='{source_ref}' -> target='{target_ref}'"
            )
            continue
        source_shape = store[source_shape_key]
        target_shape = store[target_shape_key]

        hinted = _port_hint(rel, port_hints, edge_payload)
        if diagram.is_architecture:
            hinted = _architecture_port_hint(
                str(source_ref),
                str(target_ref),
                source_shape,
                target_shape,
                diagram.node_group_ids,
                diagram.side_group_ids,
            ) or hinted

        start_edge, end_edge = audit_sides(hinted, source_shape, target_shape)
        source_bbox = shape_bbox(source_shape)
        target_bbox = shape_bbox(target_shape)
        obstacles = _edge_obstacles(
            obstacle_index, source_shape["_excalidraw_id"], target_shape["_excalidraw_id"]
        )
        start_edge, end_edge = _prefer_clear_port_pair(
            start_edge, end_edge, source_bbox, target_bbox, obstacles,
        )
        plans.append({
            "rel": rel,
            "source_ref": source_ref,
            "target_ref": target_ref,
            "source_shape": source_shape,
            "target_shape": target_shape,
            "source_bbox": source_bbox,
            "target_bbox": target_bbox,
            "obstacles": obstacles,
            "start_edge": start_edge,
            "end_edge": end_edge,
            "edge_payload": edge_payload,
        })
    return plans


def _port_order_key(item: EdgePlan, shape_key: str, side: str) -> Tuple[float, float, str]:
    """Order ports along a face by where the opposite endpoint sits."""
    center_x, center_y = _bbox_center(shape_bbox(item[shape_key]))
    if side == "left":
        primary, secondary = center_y, center_x
    elif side == "right":
        primary, secondary = center_y, -center_x
    elif side == "top":
        primary, secondary = center_x, center_y
    else:
        primary, secondary = center_x, -center_y
    return primary, secondary, str(item["rel"].get("id", ""))


def _assign_port_ranks(plans: List[EdgePlan]) -> PortTotals:
    """Rank every edge on its faces and corridors; return the sibling counts."""
    totals = PortTotals()
    source_groups: Dict[Tuple[str, str], List[EdgePlan]] = defaultdict(list)
    target_groups: Dict[Tuple[str, str], List[EdgePlan]] = defaultdict(list)
    corridor_groups: Dict[Tuple[str, str, str], List[EdgePlan]] = defaultdict(list)
    all_source_groups: Dict[str, List[EdgePlan]] = defaultdict(list)
    all_target_groups: Dict[str, List[EdgePlan]] = defaultdict(list)
    for plan in plans:
        source_ref, target_ref = plan["source_ref"], plan["target_ref"]
        corridor_key = (source_ref, plan["start_edge"], plan["end_edge"])
        totals.corridor_counts[corridor_key] += 1
        # Port fan-out is independent of the target orientation: two edges
        # leaving the same face should not collapse onto the same midpoint
        # merely because they eventually use different target faces. The
        # target side is grouped separately for fan-in at a shared face.
        totals.source_port_counts[(source_ref, plan["start_edge"])] += 1
        totals.target_port_counts[(target_ref, plan["end_edge"])] += 1
        totals.source_degrees[source_ref] += 1
        totals.target_degrees[target_ref] += 1
        source_groups[(source_ref, plan["start_edge"])].append(plan)
        target_groups[(target_ref, plan["end_edge"])].append(plan)
        corridor_groups[corridor_key].append(plan)
        all_source_groups[source_ref].append(plan)
        all_target_groups[target_ref].append(plan)

    # Port order and corridor order solve different problems. Ports follow the
    # opposite endpoint's visual order, while bend corridors put the farthest
    # branch closest to the source. Keeping them separate prevents a wide
    # fan-out from cutting across its own nearer branches.
    for groups, role, opposite in ((source_groups, "source", "target_shape"), (target_groups, "target", "source_shape")):
        for (_, side), siblings in groups.items():
            ordered = sorted(siblings, key=lambda item: _port_order_key(item, opposite, side))
            for rank, item in enumerate(ordered):
                item[f"{role}_port_index"] = rank

    # Incoming and outgoing edges occupy the same physical node face.
    # Reserve ports together so a feedback cycle cannot hide its outgoing
    # line underneath an incoming arrowhead at the face midpoint.
    for key in source_groups.keys() & target_groups.keys():
        side = key[1]
        endpoints = [(item, "source", "target_shape") for item in source_groups[key]]
        endpoints += [(item, "target", "source_shape") for item in target_groups[key]]
        endpoints.sort(key=lambda entry: _port_order_key(entry[0], entry[2], side))
        totals.source_port_counts[key] = totals.target_port_counts[key] = len(endpoints)
        for rank, (item, role, _) in enumerate(endpoints):
            item[f"{role}_port_index"] = rank

    for siblings in corridor_groups.values():
        if len(siblings) <= 1:
            siblings[0]["stagger_index"] = 0
            continue
        cross_axis = 0 if siblings[0]["start_edge"] in {"top", "bottom"} else 1
        travel_axis = 1 - cross_axis

        def cross_distance(item: EdgePlan) -> float:
            source_center = _bbox_center(item["source_bbox"])
            target_center = _bbox_center(item["target_bbox"])
            return abs(target_center[cross_axis] - source_center[cross_axis])

        ordered = sorted(siblings, key=cross_distance, reverse=True)
        source_axis = _bbox_center(siblings[0]["source_bbox"])[travel_axis]
        average_target_axis = sum(
            _bbox_center(item["target_bbox"])[travel_axis] for item in siblings
        ) / len(siblings)
        ranks = range(len(ordered)) if average_target_axis >= source_axis else reversed(range(len(ordered)))
        for rank, item in zip(ranks, ordered):
            item["stagger_index"] = rank

    # Per-node ranks along each axis, used when a later pass moves an edge
    # to a different face of the same node.
    for groups, role, opposite in (
        (all_source_groups, "source", "target_bbox"),
        (all_target_groups, "target", "source_bbox"),
    ):
        for siblings in groups.values():
            for axis, key in ((0, f"{role}_x_index"), (1, f"{role}_y_index")):
                ordered = sorted(siblings, key=lambda value: _bbox_center(value[opposite])[axis])
                for rank, item in enumerate(ordered):
                    item[key] = rank
    return totals
