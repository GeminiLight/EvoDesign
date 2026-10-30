"""Shared edge resolution and routing helpers for canvas renderers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation


def iter_concept_nodes(concept_hierarchy: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    data = unwrap_structure_instantiation(concept_hierarchy)

    if "nodes" in data and isinstance(data["nodes"], list):
        for node in data["nodes"]:
            yield node

    # Groups are valid arrow endpoints in architecture/swimlane diagrams when
    # an edge targets a container boundary instead of an inner node.
    if "groups" in data and isinstance(data["groups"], list):
        for group in data["groups"]:
            yield group

    # Renderer adapter boundary tolerance: persisted wrapped Structure payloads
    # may carry nested member objects, while current canonical groups use member
    # id strings.
    for group in data.get("groups", []):
        if not isinstance(group, dict):
            continue
        if group.get("id"):
            yield group
        for member in group.get("members", []):
            if isinstance(member, dict) and member.get("kind") == "node":
                node = member.get("node") or {}
                yield node


def is_layout_edge_entry(element_id: Any, element_data: Any) -> bool:
    """Classify a layout entry as edge styling / routing data.

    Renderer converters accept both namespaced edge keys and bare Structure
    edge ids. The structural signature is authoritative: nodes and groups do
    not carry both ``start`` and ``end`` dicts.
    """
    if isinstance(element_id, str) and element_id.startswith("edge:"):
        return True
    if isinstance(element_data, dict):
        start = element_data.get("start")
        end = element_data.get("end")
        if isinstance(start, dict) and isinstance(end, dict):
            return True
    return False


def resolve_label_from_node_ref(
    concept_hierarchy: Dict[str, Any],
    node_ref: str,
) -> Optional[str]:
    for node in iter_concept_nodes(concept_hierarchy):
        if node.get("id") == node_ref or node.get("node_id") == node_ref:
            return node.get("label")
    return None


def normalize_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return " ".join(text.replace("\n", " ").split()).strip()


def iter_shape_id_candidates(node_ref: str) -> Iterable[str]:
    if not isinstance(node_ref, str) or not node_ref:
        return

    yield node_ref

    if not node_ref.startswith("shape:"):
        yield f"shape:{node_ref}"
        yield f"shape:n_{node_ref}"

    if node_ref.startswith("n_"):
        yield f"shape:{node_ref[2:]}"

    # Container endpoints should bind to the drawable background shape.
    if not node_ref.endswith(":background"):
        yield f"shape:{node_ref}:background"

    if node_ref.startswith("group:"):
        base = node_ref[len("group:") :]
        yield f"shape:{base}:background"
    elif not node_ref.startswith("shape:"):
        yield f"shape:group:{node_ref}:background"


def find_shape_id(
    store: Dict[str, Any],
    node_ref: str,
    concept_hierarchy: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    for candidate in iter_shape_id_candidates(node_ref):
        if candidate in store:
            return candidate

    label: Optional[str] = None
    if concept_hierarchy is not None:
        label = resolve_label_from_node_ref(concept_hierarchy, node_ref)

    if label:
        normalized_label = normalize_text(label) or label
        for sid, shape in store.items():
            if not isinstance(shape, dict):
                continue
            if shape.get("type") not in {"text", "geo"}:
                continue
            props = shape.get("props", {}) or {}
            shape_text = normalize_text(props.get("text"))
            if shape_text == normalized_label:
                return sid

        target_by_label = f"shape:node_{label.lower()}"
        if target_by_label in store:
            return target_by_label

    target = f"shape:{node_ref.lower()}"
    if target in store:
        return target

    return None


def shape_bbox(shape: Dict[str, Any]) -> Dict[str, float]:
    """Read ``x/y/w/h`` from a TLDraw or Excalidraw shape-like element."""
    x = shape.get("x", 0) or 0
    y = shape.get("y", 0) or 0
    w = shape.get("width")
    h = shape.get("height")
    if w is None or h is None:
        props = shape.get("props") or {}
        if w is None:
            w = props.get("w")
        if h is None:
            h = props.get("h")
    if w is None:
        w = 100
    if h is None:
        h = 100
    return {"x": float(x), "y": float(y), "w": float(w), "h": float(h)}


def pick_sides_from_geometry(
    source_shape: Dict[str, Any],
    target_shape: Dict[str, Any],
) -> tuple[str, str]:
    source = shape_bbox(source_shape)
    target = shape_bbox(target_shape)
    source_center_x = source["x"] + source["w"] / 2
    source_center_y = source["y"] + source["h"] / 2
    target_center_x = target["x"] + target["w"] / 2
    target_center_y = target["y"] + target["h"] / 2

    dx = source_center_x - target_center_x
    dy = source_center_y - target_center_y
    vertical_threshold = 30.0

    if abs(dy) >= abs(dx) or abs(dy) > vertical_threshold:
        if dy < 0:
            return "bottom", "top"
        return "top", "bottom"
    if dx < 0:
        return "right", "left"
    return "left", "right"


def is_side_plausible(
    side: str,
    source_shape: Dict[str, Any],
    target_shape: Dict[str, Any],
    role: str,
) -> bool:
    source = shape_bbox(source_shape)
    target = shape_bbox(target_shape)
    source_center_x = source["x"] + source["w"] / 2
    source_center_y = source["y"] + source["h"] / 2
    target_center_x = target["x"] + target["w"] / 2
    target_center_y = target["y"] + target["h"] / 2

    side = normalize_port(side) or ""

    if role == "source":
        if side == "top":
            return source_center_y > target_center_y
        if side == "bottom":
            return source_center_y < target_center_y
        if side == "left":
            return source_center_x > target_center_x
        if side == "right":
            return source_center_x < target_center_x
    elif role == "target":
        if side == "top":
            return source_center_y < target_center_y
        if side == "bottom":
            return source_center_y > target_center_y
        if side == "left":
            return source_center_x < target_center_x
        if side == "right":
            return source_center_x > target_center_x
    return False


def audit_sides(
    hinted: Optional[Dict[str, Any]],
    source_shape: Dict[str, Any],
    target_shape: Dict[str, Any],
) -> tuple[str, str]:
    geom_start, geom_end = pick_sides_from_geometry(source_shape, target_shape)

    if not hinted:
        return geom_start, geom_end

    start_hint = normalize_port(hinted.get("start"))
    end_hint = normalize_port(hinted.get("end"))

    start_side = geom_start
    end_side = geom_end

    if start_hint and is_side_plausible(start_hint, source_shape, target_shape, "source"):
        start_side = start_hint

    if end_hint and is_side_plausible(end_hint, source_shape, target_shape, "target"):
        end_side = end_hint

    return start_side, end_side


def derive_routing_from_sides(
    source_side: str,
    target_side: str,
    chart_type: Optional[str] = None,
) -> str:
    if chart_type:
        chart_key = chart_type.lower().replace("_diagram", "").replace("_", "")
        if chart_key == "mindmap":
            return "curved"
        if chart_key in ("orgchart", "tree"):
            return "straight"
        if chart_key == "state":
            if source_side == target_side or (
                source_side == "bottom" and target_side == "top"
            ):
                return "curved"
        if chart_key == "architecture":
            if source_side == "bottom" and target_side == "top":
                return "straight"
            if source_side == "top" and target_side == "bottom":
                return "curved"

    aligned = {
        ("right", "left"),
        ("left", "right"),
        ("bottom", "top"),
        ("top", "bottom"),
    }
    if (source_side, target_side) in aligned:
        return "straight"
    if source_side == target_side:
        return "curved"
    return "elbowed"


def get_edge_center(element: Dict[str, Any], edge: str) -> Dict[str, float]:
    bbox = shape_bbox(element)
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]

    if edge == "left":
        return {"x": x, "y": y + h / 2}
    if edge == "right":
        return {"x": x + w, "y": y + h / 2}
    if edge == "top":
        return {"x": x + w / 2, "y": y}
    if edge == "bottom":
        return {"x": x + w / 2, "y": y + h}
    return {"x": x + w, "y": y + h / 2}


def normalize_port(port: Optional[str]) -> Optional[str]:
    if not port or not isinstance(port, str):
        return None
    normalized = port.strip().lower()
    if normalized == "botton":
        normalized = "bottom"
    if normalized in {"left", "right", "top", "bottom"}:
        return normalized
    return None


def extract_side_from_port(port_payload: Any) -> Optional[str]:
    if isinstance(port_payload, str):
        return normalize_port(port_payload)
    if isinstance(port_payload, dict):
        side = port_payload.get("side") or port_payload.get("port")
        return normalize_port(side) if isinstance(side, str) else None
    return None


def collect_edge_payloads(
    concept_hierarchy: Dict[str, Any],
    store: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    payloads: Dict[str, Dict[str, Any]] = {}

    styling_instantiation = concept_hierarchy.get("styling_instantiation") or {}
    if isinstance(styling_instantiation, dict):
        for key, value in styling_instantiation.items():
            if isinstance(key, str) and isinstance(value, dict):
                payloads[key] = value

    if store:
        document = store.get("document:document")
        meta = document.get("meta") if isinstance(document, dict) else None
        if isinstance(meta, dict):
            edge_payloads = meta.get("edge_data")
            if isinstance(edge_payloads, dict):
                for key, value in edge_payloads.items():
                    if isinstance(key, str) and isinstance(value, dict):
                        payloads[key] = value

    return payloads


def relations_from_edge_data(
    edge_data: Dict[str, Any],
    valid_element_ids: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    """Build relation records from layout-derived edge payloads.

    Layout output is the authoritative endpoint source once a converter has
    produced shapes from it. Structure remains the semantic source, but the
    renderer boundary must resolve arrows from the same id space as the rendered
    shapes.
    """
    relations: List[Dict[str, Any]] = []
    for edge_id, payload in edge_data.items():
        if not isinstance(edge_id, str) or not isinstance(payload, dict):
            continue
        start = payload.get("start")
        end = payload.get("end")
        if not isinstance(start, dict) or not isinstance(end, dict):
            continue
        source = start.get("elementId")
        target = end.get("elementId")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        if valid_element_ids is not None and (
            source not in valid_element_ids or target not in valid_element_ids
        ):
            continue

        relation: Dict[str, Any] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "start": start.get("side"),
            "end": end.get("side"),
        }
        for key in (
            "label",
            "routing",
            "startArrowhead",
            "endArrowhead",
            "arrowheadStart",
            "arrowheadEnd",
        ):
            if key in payload:
                relation[key] = payload[key]
        relations.append(relation)
    return relations


def resolve_edge_payload(
    edge_payloads: Dict[str, Dict[str, Any]],
    edge_id: Any,
) -> Optional[Dict[str, Any]]:
    if isinstance(edge_id, str) and edge_id:
        payload = edge_payloads.get(edge_id)
        if isinstance(payload, dict):
            return payload
    return None


def edge_payload_value(edge_payload: Optional[Dict[str, Any]], key: str) -> Any:
    if not isinstance(edge_payload, dict):
        return None
    props = edge_payload.get("props")
    if isinstance(props, dict) and key in props:
        return props[key]
    return edge_payload.get(key)


def extract_edge_port_hints(
    concept_hierarchy: Dict[str, Any],
    store: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Optional[str]]]:
    hints: Dict[str, Dict[str, Optional[str]]] = {}

    styling_instantiation = concept_hierarchy.get("styling_instantiation") or {}
    if isinstance(styling_instantiation, dict):
        for key, value in styling_instantiation.items():
            if isinstance(key, str) and isinstance(value, dict):
                start_port = extract_side_from_port(value.get("start"))
                end_port = extract_side_from_port(value.get("end"))
                if start_port or end_port:
                    hints[key] = {
                        "start": start_port,
                        "end": end_port,
                    }

    if store:
        document = store.get("document:document")
        if document and isinstance(document, dict):
            meta = document.get("meta")
            if meta and isinstance(meta, dict):
                edge_data = meta.get("edge_data")
                if edge_data and isinstance(edge_data, dict):
                    for key, value in edge_data.items():
                        if isinstance(key, str) and isinstance(value, dict):
                            start_port = extract_side_from_port(value.get("start"))
                            end_port = extract_side_from_port(value.get("end"))
                            if start_port or end_port:
                                hints[key] = {
                                    "start": start_port,
                                    "end": end_port,
                                }

    return hints


def normalize_routing(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    routing = value.strip().lower()
    if routing == "elbow":
        routing = "elbowed"
    if routing in {"straight", "elbowed", "curved"}:
        return routing
    return None


def edge_endpoints(relation: Dict[str, Any]) -> tuple[str, str]:
    source = relation.get("from") or relation.get("source") or ""
    target = relation.get("to") or relation.get("target") or ""
    return source, target


def collect_relations(concept_hierarchy: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = unwrap_structure_instantiation(concept_hierarchy)

    if "edges" in data and isinstance(data["edges"], list):
        normalized: List[Dict[str, Any]] = []
        for edge in data["edges"]:
            if not isinstance(edge, dict):
                continue
            source, target = edge_endpoints(edge)
            enriched = dict(edge)
            enriched.setdefault("source", source)
            enriched.setdefault("target", target)
            normalized.append(enriched)
        return normalized

    relations = []
    for group in data.get("groups", []):
        relations.extend(group.get("relations", []))
    return relations


__all__ = [
    "audit_sides",
    "collect_edge_payloads",
    "collect_relations",
    "derive_routing_from_sides",
    "edge_endpoints",
    "edge_payload_value",
    "extract_edge_port_hints",
    "extract_side_from_port",
    "find_shape_id",
    "get_edge_center",
    "normalize_port",
    "normalize_routing",
    "relations_from_edge_data",
    "resolve_edge_payload",
    "shape_bbox",
]
