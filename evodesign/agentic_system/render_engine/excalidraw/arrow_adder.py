# -*- coding: utf-8 -*-
"""
Excalidraw Arrow Adder - Add directional arrows to an Excalidraw manifest.

The pass runs in stages; the routing primitives live in ``arrow_routing``:

1. Plan: resolve each relation's shapes, pick its faces, rank its ports.
2. Route: draw every edge in turn, avoiding nodes and earlier edges.
3. Optimize: scene-wide passes that trade routes for fewer crossings.
4. Label: filter and place edge labels on the final routes.
5. Compare: keep midpoint ports instead when fan-out added crossings.
"""

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from evodesign.agentic_system.common.semantic_ids import (
    id_map_from_manifest,
    reverse_id_map,
)
from evodesign.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evodesign.agentic_system.render_engine.shared.order_keys import sequential_index
from ..shared.edge_crossing_detector import detect_crossings
from ..shared.edge_routing import (
    collect_relations,
    derive_routing_from_sides,
    extract_edge_port_hints,
    normalize_routing,
    relations_from_edge_data,
)
from .arrow_routing.context import DiagramContext, _diagram_context
from .arrow_routing.detours import _avoid_node_intersections, _obstacle_index
from .arrow_routing.geometry import _arrow_path_fields, _box_tuple
from .arrow_routing.grid_router import _ROUTE_MEMO
from .arrow_routing.labels import (
    _compute_label_geometry,
    _detach_concept_labels,
    _edge_label_payload,
    _merge_semantic_edge_labels,
    _node_label_lookup,
    _normalize_label_payload,
    _position_architecture_bound_labels,
    _reposition_edge_labels,
    _should_drop_edge_label,
)
from .arrow_routing.passes import (
    _reduce_crossings,
    _reroute_architecture_edges,
    _route_concept_corridors,
    _separate_final_channels,
    _spread_final_target_ports,
)
from .arrow_routing.ports import EdgePlan, PortTotals, _assign_port_ranks, _plan_edges
from .converter import _excalidraw_defaults, _generate_excalidraw_id
from .edge_router import compute_waypoints

logger = logging.getLogger(__name__)

DEFAULT_STAGGER_SPACING = 50.0
DEFAULT_PORT_SPACING = 32.0

# routing 同时控制 ``elbowed`` 和 ``roundness``，让 LLM 的三选一真正生效：
#
#   routing=straight → elbowed=False, roundness=None  (普通直线)
#   routing=elbowed  → elbowed=True,  roundness=None  (带弯折的尖锐线)
#   routing=curved   → elbowed=True,  roundness={"type": 2} (带弯折的平滑曲线)
#
# Unknown routing is drawn as a straight polyline.
_ELBOWED_ROUTINGS = {"elbowed", "curved"}
_EDGE_STYLE_KEYS = ("strokeColor", "strokeWidth", "strokeStyle", "opacity", "roughness")


def _build_lookup_store(elements: List[Dict[str, Any]], id_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Build a shape lookup store from Excalidraw elements for shared edge routing.

    The store maps `shape:{semantic_id}` to shape-like entries accepted by
    shared edge routing helpers.
    """
    store: Dict[str, Any] = {}
    reverse_map = reverse_id_map(id_map)
    for elem in elements:
        eid = elem.get("id", "")
        semantic_id = reverse_map.get(eid)
        if not semantic_id:
            continue
        store[f"shape:{semantic_id}"] = {
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


def _mark_repeated_concept_labels(plans: List[EdgePlan], core_node_ids: set[str]) -> None:
    """Show a core concept's repeated structural predicate only once.

    Independently routed edges need independently readable predicates, even
    when they share a source and wording. A single label is valid only for an
    actual shared branching trunk out of a core concept.
    """
    repeated: Dict[tuple, List[EdgePlan]] = {}
    for plan in plans:
        normalized = _normalize_label_payload(_edge_label_payload(plan["rel"], plan.get("edge_payload")))
        if not normalized:
            continue
        label_key = " ".join(normalized["text"].lower().split())
        repeated.setdefault((str(plan["rel"].get("source", "")), label_key), []).append(plan)
    for (source_ref, label_key), siblings in repeated.items():
        if (
            len(siblings) >= 2
            and source_ref in core_node_ids
            and (
                label_key == "organized into"
                or all(item["rel"].get("evidence_basis") == "structural" for item in siblings)
            )
        ):
            for item in siblings:
                item["suppress_repeated_label"] = True


def _route_edge(
    plan: EdgePlan,
    totals: PortTotals,
    existing: List[Dict[str, Any]],
    port_spacing: float,
) -> List[Dict[str, float]]:
    """First route for one edge: staggered face ports, then node avoidance."""
    source_ref, target_ref = plan["source_ref"], plan["target_ref"]
    start_edge, end_edge = plan["start_edge"], plan["end_edge"]
    waypoints, _, _ = compute_waypoints(
        start_edge, end_edge, plan["source_bbox"], plan["target_bbox"],
        stagger_index=int(plan.get("stagger_index", 0)),
        stagger_total=totals.corridor_counts[(source_ref, start_edge, end_edge)],
        stagger_spacing=DEFAULT_STAGGER_SPACING,
        start_port_index=int(plan.get("source_port_index", 0)),
        start_port_total=totals.source_port_counts[(source_ref, start_edge)],
        end_port_index=int(plan.get("target_port_index", 0)),
        end_port_total=totals.target_port_counts[(target_ref, end_edge)],
        port_spacing=port_spacing,
    )
    return _avoid_node_intersections(
        waypoints,
        plan["obstacles"],
        existing_arrows=existing,
        endpoint_boxes=[_box_tuple(plan["source_bbox"]), _box_tuple(plan["target_bbox"])],
    )


def _arrow_element(
    plan: EdgePlan,
    waypoints: List[Dict[str, float]],
    index: str,
    chart_type: Any,
) -> Dict[str, Any]:
    rel, edge_payload = plan["rel"], plan["edge_payload"]
    source_ref, target_ref = plan["source_ref"], plan["target_ref"]
    edge_id = rel.get("id", "")
    edge_seed = [
        "edge",
        edge_id or f"{source_ref}->{target_ref}",
        source_ref,
        target_ref,
        int(plan.get("stagger_index", 0)),
        plan["start_edge"],
        plan["end_edge"],
    ]
    arrow = {
        **_excalidraw_defaults(["arrow", edge_seed]),
        "id": _generate_excalidraw_id(edge_seed),
        "type": "arrow",
        "index": index,
        "strokeColor": "#64748B",
        "strokeWidth": 1.5,
        "roughness": 0,
        "meta": {
            "semantic_edge_id": edge_id,
            "source": source_ref,
            "target": target_ref,
        },
        **_arrow_path_fields(waypoints),
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "lastCommittedPoint": None,
    }

    routing = normalize_routing(edge_payload.get("routing")) if edge_payload else None
    if routing is None:
        routing = normalize_routing(rel.get("routing"))
    if routing is None:
        # Diagram-type-aware fallback — preserves identity signals (e.g.
        # mindmap radial branches must be curved, not elbowed).
        routing = derive_routing_from_sides(plan["start_edge"], plan["end_edge"], chart_type)
    arrow["elbowed"] = routing in _ELBOWED_ROUTINGS
    arrow["roundness"] = {"type": 2} if routing == "curved" else None

    # Authored arrowheads and stroke styling from the layout edge win. The
    # 2026-04-22 schema removed LLM ``waypoints``; ``compute_waypoints`` owns
    # the polyline.
    if edge_payload:
        for key in ("startArrowhead", "endArrowhead", *_EDGE_STYLE_KEYS):
            if key in edge_payload:
                arrow[key] = edge_payload[key]
        props = edge_payload.get("props", {})
        if isinstance(props, dict) and "color" in props:
            arrow["strokeColor"] = props["color"]
    return arrow


def _keeps_edge_label(
    plan: EdgePlan,
    normalized: Dict[str, Any],
    diagram: DiagramContext,
    node_label_map: Dict[str, str],
) -> bool:
    """Whether an authored label is drawn, or suppressed as noise."""
    rel, edge_payload = plan["rel"], plan["edge_payload"]
    if edge_payload and edge_payload.get("_suppressLabel"):
        return False
    if plan.get("suppress_repeated_label"):
        return False
    # Deterministic stop-label filter (2026-04-25 — backstop for the
    # "non-essential edge labels are forbidden" prompt rule). Drops generic
    # direction-verbs, over-long descriptions, and labels that paraphrase
    # their target node.
    drop_reason = _should_drop_edge_label(
        normalized.get("text", ""),
        plan["source_ref"],
        plan["target_ref"],
        node_label_map,
        preserve_structural_labels=diagram.is_concept_map,
    )
    if drop_reason:
        logger.info(
            "[ArrowAdder] dropping edge label edge=%s text=%r reason=%s",
            rel.get("id", ""),
            normalized.get("text", ""),
            drop_reason,
        )
        return False
    return True


def _label_element(
    arrow: Dict[str, Any],
    label: Dict[str, Any],
    waypoints: List[Dict[str, float]],
    index: str,
) -> Dict[str, Any]:
    edge_id = arrow["meta"]["semantic_edge_id"]
    ax, ay = waypoints[0]["x"], waypoints[0]["y"]
    geometry = _compute_label_geometry(
        ax=ax,
        ay=ay,
        dx=waypoints[-1]["x"] - ax,
        dy=waypoints[-1]["y"] - ay,
        arrow_elem=arrow,
        normalized_label=label,
    )
    text_seed = ["edge_label", edge_id or arrow["id"], label["text"]]
    return {
        **_excalidraw_defaults(["edge_label", text_seed]),
        "id": _generate_excalidraw_id(text_seed),
        "type": "text",
        "index": index,
        **geometry,
        "text": label["text"],
        "fontSize": label["fontSize"],
        "fontFamily": label["fontFamily"],
        "strokeColor": label["strokeColor"],
        "textAlign": label["textAlign"],
        "verticalAlign": label.get("verticalAlign", "middle"),
        "containerId": arrow["id"],
        "originalText": label["text"],
        "autoResize": True,
        "lineHeight": 1.15,
        "meta": {"semantic_edge_id": edge_id},
    }


def _route_context(plan: EdgePlan, totals: PortTotals, diagram: DiagramContext) -> Dict[str, Any]:
    """What the scene-wide passes need to reconsider one edge's route."""
    source_ref, target_ref = plan["source_ref"], plan["target_ref"]
    edge_payload = plan["edge_payload"]
    return {
        "source_ref": source_ref,
        "target_ref": target_ref,
        "source_group": diagram.node_group_ids.get(source_ref, ""),
        "target_group": diagram.node_group_ids.get(target_ref, ""),
        "source_bbox": plan["source_bbox"],
        "target_bbox": plan["target_bbox"],
        "obstacles": plan["obstacles"],
        "start_side": plan["start_edge"],
        "end_side": plan["end_edge"],
        "source_x_index": int(plan.get("source_x_index", 0)),
        "source_y_index": int(plan.get("source_y_index", 0)),
        "target_x_index": int(plan.get("target_x_index", 0)),
        "target_y_index": int(plan.get("target_y_index", 0)),
        "source_degree": totals.source_degrees[source_ref],
        "target_degree": totals.target_degrees[target_ref],
        "cross_branch": bool(edge_payload and edge_payload.get("_layoutCrossBranch")),
    }


def add_excalidraw_arrows_to_manifest(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    *,
    port_spacing: Optional[float] = None,
    _adaptive_ports: bool = True,
    _report_crossings: bool = True,
) -> Dict[str, Any]:
    """Add arrows; see :func:`_add_excalidraw_arrows_to_manifest`.

    The outermost call owns the route memo, so nested comparison passes reuse
    routes and nothing outlives one arrow pass.
    """
    kwargs = dict(port_spacing=port_spacing, _adaptive_ports=_adaptive_ports,
                  _report_crossings=_report_crossings)
    if _ROUTE_MEMO.get() is not None:
        return _add_excalidraw_arrows_to_manifest(manifest, structure_instantiation, **kwargs)
    token = _ROUTE_MEMO.set({})
    try:
        return _add_excalidraw_arrows_to_manifest(manifest, structure_instantiation, **kwargs)
    finally:
        _ROUTE_MEMO.reset(token)


def _add_excalidraw_arrows_to_manifest(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    *,
    port_spacing: Optional[float] = None,
    _adaptive_ports: bool = True,
    _report_crossings: bool = True,
) -> Dict[str, Any]:
    """
    Add arrow elements to an Excalidraw manifest based on structure_instantiation edges.

    Args:
        manifest: Excalidraw manifest with elements, files, _meta
        structure_instantiation: Semantic graph with edges

    Returns:
        Updated manifest with arrow elements added
    """
    structure = unwrap_structure_instantiation(structure_instantiation)
    if structure.get("chart_type") == "sequence_diagram":
        from .sequence_layout import render_sequence_messages
        return render_sequence_messages(manifest, structure_instantiation)
    if port_spacing is None:
        port_spacing = DEFAULT_PORT_SPACING
    if port_spacing < 0:
        raise ValueError("port_spacing must be non-negative")
    manifest = deepcopy(manifest)
    elements = manifest.get("elements", [])
    id_map = id_map_from_manifest(manifest)
    meta = manifest.get("_meta")
    edge_data = meta.get("edge_data", {}) if isinstance(meta, dict) else {}
    if not isinstance(edge_data, dict):
        edge_data = {}

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
        logger.info("[ArrowAdder] Using %d edges from manifest._meta.edge_data", len(relations))
    else:
        relations = collect_relations(structure_instantiation)
        logger.info(
            "[ArrowAdder] edge_data empty - falling back to structure.edges (%d edges)",
            len(relations),
        )
    relations = _merge_semantic_edge_labels(relations, structure)
    diagram = _diagram_context(structure, id_map, elements)

    # 1. Plan faces and port ranks for every edge.
    plans = _plan_edges(
        relations,
        _build_lookup_store(elements, id_map),
        structure_instantiation,
        edge_data,
        extract_edge_port_hints(structure_instantiation),
        diagram,
        _obstacle_index(elements, id_map, excluded_ids=diagram.group_frame_ids),
    )
    totals = _assign_port_ranks(plans)
    if diagram.is_concept_map:
        _mark_repeated_concept_labels(plans, diagram.core_node_ids)

    # 2. Route each edge around nodes and the edges drawn before it.
    node_label_map = _node_label_lookup(structure_instantiation)
    dropped_label_count = 0
    new_arrows: List[Dict[str, Any]] = []
    route_contexts: Dict[str, Dict[str, Any]] = {}
    for plan in plans:
        waypoints = _route_edge(plan, totals, new_arrows, port_spacing)
        arrow = _arrow_element(
            plan, waypoints, sequential_index(len(elements) + len(new_arrows)), structure.get("chart_type"),
        )
        route_contexts[arrow["id"]] = _route_context(plan, totals, diagram)
        new_arrows.append(arrow)

        label = _normalize_label_payload(_edge_label_payload(plan["rel"], plan["edge_payload"]))
        if not label:
            continue
        if not _keeps_edge_label(plan, label, diagram, node_label_map):
            dropped_label_count += 1
            continue
        text = _label_element(arrow, label, waypoints, sequential_index(len(elements) + len(new_arrows)))
        arrow["boundElements"] = [{"type": "text", "id": text["id"]}]
        new_arrows.append(text)

    # 3. Scene-wide route optimization. Fan-out is a local readability
    # improvement, but it must not trade away global route clarity.
    arrow_elems = [
        element
        for element in new_arrows
        if element.get("type") == "arrow" and float(element.get("opacity", 100) or 0) > 0
    ]
    elements_by_id: Dict[str, Dict[str, Any]] = {}
    for element in new_arrows:
        elements_by_id.setdefault(str(element.get("id", "")), element)
    if arrow_elems:
        _reduce_crossings(arrow_elems, route_contexts, elements_by_id, port_spacing)
        _route_concept_corridors(arrow_elems, route_contexts, elements_by_id, diagram.concept_frames, port_spacing)
    if diagram.is_architecture:
        _reroute_architecture_edges(
            arrow_elems, route_contexts, diagram.side_group_ids, totals.source_degrees, totals.target_degrees,
        )
    _spread_final_target_ports(arrow_elems, route_contexts, port_spacing)
    _separate_final_channels(arrow_elems, route_contexts)

    # 4. Labels follow the final routes.
    _reposition_edge_labels(elements, new_arrows)
    if diagram.is_architecture:
        _position_architecture_bound_labels(elements, new_arrows, route_contexts, diagram.group_frame_ids)
    if diagram.is_concept_map:
        _detach_concept_labels(new_arrows)

    # 5. Compare against the same scene with midpoint ports and keep the
    # lower-crossing candidate. This makes fan-out deterministic and falls
    # back on dense layouts where moving a shared face adds crossings.
    if _adaptive_ports and port_spacing > 0:
        midpoint_manifest = add_excalidraw_arrows_to_manifest(
            manifest,
            structure_instantiation,
            port_spacing=0.0,
            _adaptive_ports=False,
            _report_crossings=False,
        )
        midpoint_arrows = [
            element for element in midpoint_manifest.get("elements", []) if element.get("type") == "arrow"
        ]
        fanout_crossings = len(detect_crossings(arrow_elems))
        midpoint_crossings = len(detect_crossings(midpoint_arrows))
        if midpoint_crossings < fanout_crossings:
            logger.info(
                "[ArrowAdder] midpoint ports selected (%d crossings vs %d with fan-out)",
                midpoint_crossings,
                fanout_crossings,
            )
            return midpoint_manifest

    elements.extend(new_arrows)
    manifest["elements"] = elements

    if _report_crossings:
        # Observational crossing check — warn-only, no manifest changes. The
        # warning signal is intended for future Layout-side iteration.
        crossings = detect_crossings(arrow_elems)
        for a_id, b_id, crossing in crossings:
            logger.warning(
                "[CrossingDetector] Arrow %s crosses %s (segment a=%s, b=%s)",
                a_id,
                b_id,
                crossing.get("segment_index_a"),
                crossing.get("segment_index_b"),
            )
        if crossings:
            logger.warning("[CrossingDetector] %d edge crossing pair(s) detected in manifest", len(crossings))
        if dropped_label_count:
            logger.warning(
                "[ArrowAdder] suppressed %d non-informative or repeated edge label(s)",
                dropped_label_count,
            )

    return manifest


def rebuild_excalidraw_arrows(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    """Recompute arrow geometry after a deterministic node layout pass.

    Unified scenes already contain LLM-authored arrows. When a post-processor
    moves their endpoint shapes, those coordinates become stale. Remove the
    old arrows and their bound labels, clear reverse bindings, then delegate
    geometry to the same router used by pipeline mode. Semantic mappings and
    authored connector styling are restored on the rebuilt elements.
    """
    if unwrap_structure_instantiation(structure_instantiation).get("chart_type") == "sequence_diagram":
        from .sequence_layout import render_sequence_messages
        return render_sequence_messages(manifest, structure_instantiation)
    source = deepcopy(manifest)
    elements = [
        element
        for element in source.get("elements", [])
        if isinstance(element, dict)
    ]
    old_arrows = {
        str(element.get("id")): element
        for element in elements
        if element.get("type") == "arrow" and element.get("id")
    }
    if not old_arrows:
        return add_excalidraw_arrows_to_manifest(source, structure_instantiation)

    old_styles: Dict[str, Dict[str, Any]] = {}
    old_semantic_edge_ids: set[str] = set()
    for arrow in old_arrows.values():
        meta = arrow.get("meta")
        edge_id = str(meta.get("semantic_edge_id", "")) if isinstance(meta, dict) else ""
        if edge_id:
            old_semantic_edge_ids.add(edge_id)
            old_styles[edge_id] = {
                key: arrow[key]
                for key in (
                    "strokeColor",
                    "strokeWidth",
                    "strokeStyle",
                    "opacity",
                    "startArrowhead",
                    "endArrowhead",
                )
                if key in arrow
            }

    old_arrow_ids = set(old_arrows)
    old_label_ids = {
        str(element.get("id"))
        for element in elements
        if element.get("type") == "text"
        and (
            str(element.get("containerId", "")) in old_arrow_ids
            or (
                isinstance(element.get("meta"), dict)
                and str(element["meta"].get("semantic_edge_id", ""))
                in old_semantic_edge_ids
            )
        )
        and element.get("id")
    }
    edge_data = (source.get("_meta") or {}).get("edge_data")
    if isinstance(edge_data, dict):
        for element in elements:
            if str(element.get("id")) not in old_label_ids:
                continue
            edge_id = (element.get("meta") or {}).get("semantic_edge_id")
            if not edge_id:
                owner = old_arrows.get(str(element.get("containerId")), {})
                edge_id = (owner.get("meta") or {}).get("semantic_edge_id")
            payload = edge_data.get(edge_id)
            if not isinstance(payload, dict):
                continue
            label = _normalize_label_payload(payload.get("label"))
            if label is None:
                label = _normalize_label_payload(element.get("text"))
            if label is None:
                continue
            # Feed edited typography into routing before measuring/repositioning
            # labels. Restoring it only afterward would leave stale text boxes.
            label.update({
                key: element[key]
                for key in ("fontSize", "fontFamily", "strokeColor", "textAlign", "verticalAlign")
                if key in element
            })
            payload["label"] = label
    removed_ids = old_arrow_ids | old_label_ids
    retained: List[Dict[str, Any]] = []
    for element in elements:
        if str(element.get("id", "")) in removed_ids:
            continue
        bound_elements = element.get("boundElements")
        if isinstance(bound_elements, list):
            element["boundElements"] = [
                binding
                for binding in bound_elements
                if not (
                    isinstance(binding, dict)
                    and str(binding.get("id", "")) in removed_ids
                )
            ]
        retained.append(element)
    source["elements"] = retained

    rebuilt = add_excalidraw_arrows_to_manifest(source, structure_instantiation)
    id_map = {key: value for key, value in id_map_from_manifest(rebuilt).items() if value not in removed_ids}
    semantic_edge_ids = {
        str(edge.get("id"))
        for edge in unwrap_structure_instantiation(structure_instantiation).get("edges", []) or []
        if isinstance(edge, dict) and edge.get("id")
    }
    for edge_id in semantic_edge_ids:
        id_map.pop(edge_id, None)
    for element in rebuilt.get("elements", []):
        if not isinstance(element, dict):
            continue
        meta = element.get("meta")
        edge_id = str(meta.get("semantic_edge_id", "")) if isinstance(meta, dict) else ""
        if not edge_id:
            continue
        if element.get("type") == "text":
            id_map[f"{edge_id}:label"] = str(element.get("id", ""))
            continue
        if element.get("type") != "arrow":
            continue
        element.update(old_styles.get(edge_id, {}))
        id_map[edge_id] = str(element.get("id", ""))

    meta = rebuilt.setdefault("_meta", {})
    if isinstance(meta, dict):
        meta["id_map"] = id_map
    return rebuilt
