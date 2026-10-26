import argparse
import json
import logging
from copy import deepcopy
from typing import Any, Dict, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.common.tldraw_utils import TLDrawColorValidator, TLDrawIDGenerator
from evo_diagram.agentic_system.render_engine.shared.edge_routing import (
    audit_sides,
    collect_edge_payloads,
    collect_relations,
    derive_routing_from_sides,
    edge_payload_value,
    extract_edge_port_hints,
    extract_side_from_port,
    find_shape_id,
    get_edge_center,
    normalize_routing,
    relations_from_edge_data,
    resolve_edge_payload,
)

logger = logging.getLogger(__name__)


_TLDRAW_COLOR_RGB = {
    "black": (30, 30, 30),
    "grey": (147, 147, 147),
    "light-violet": (226, 217, 255),
    "violet": (126, 87, 194),
    "blue": (25, 118, 210),
    "light-blue": (165, 216, 255),
    "yellow": (255, 212, 59),
    "orange": (245, 124, 0),
    "green": (46, 125, 50),
    "light-green": (183, 235, 143),
    "light-red": (255, 201, 201),
    "red": (224, 49, 49),
    "white": (255, 255, 255),
}


def _hex_to_rgb(value: str) -> Optional[tuple[int, int, int]]:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(char * 2 for char in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return None


def _nearest_tldraw_color(hex_color: str) -> str:
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return TLDrawColorValidator.normalize_color(hex_color)

    def _distance(candidate: tuple[int, int, int]) -> int:
        return sum((component - target) ** 2 for component, target in zip(rgb, candidate))

    return min(_TLDRAW_COLOR_RGB, key=lambda color: _distance(_TLDRAW_COLOR_RGB[color]))


def _resolve_edge_color(edge_payload: Optional[Dict[str, Any]]) -> str:
    raw_color = (
        edge_payload_value(edge_payload, "color")
        or edge_payload_value(edge_payload, "strokeColor")
    )
    if isinstance(raw_color, str) and raw_color.strip().startswith("#"):
        return _nearest_tldraw_color(raw_color)
    return TLDrawColorValidator.normalize_color(raw_color)


def _routing_to_tldraw_kind(routing: str) -> str:
    if routing == "straight":
        return "straight"
    if routing == "curved":
        return "curved"
    return "elbow"


def _resolve_arrowhead(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _make_normalized_anchor(point: Dict[str, float], target: Dict[str, Any]):
    tx = target.get('x', 0)
    ty = target.get('y', 0)
    tprops = target.get('props', {}) or {}
    tw = tprops.get('w', 100)
    th = tprops.get('h', 100)
    if tw == 0:
        tw = 1
    if th == 0:
        th = 1
    nx = (point['x'] - tx) / tw
    ny = (point['y'] - ty) / th
    nx = max(0.0, min(1.0, nx))
    ny = max(0.0, min(1.0, ny))
    return {'x': nx, 'y': ny}


def _edge_data_from_store(store: Dict[str, Any]) -> Dict[str, Any]:
    document = store.get("document:document")
    meta = document.get("meta") if isinstance(document, dict) else None
    if not isinstance(meta, dict):
        return {}
    edge_data = meta.get("edge_data")
    return edge_data if isinstance(edge_data, dict) else {}


def add_arrows(store: Dict[str, Any], concept_hierarchy: Dict[str, Any]) -> Dict[str, Any]:
    """Generate TLDraw arrow shapes and bindings for the provided store."""
    new_store_items: Dict[str, Any] = {}
    edge_data = _edge_data_from_store(store)
    layout_relations = relations_from_edge_data(edge_data) if edge_data else []
    if layout_relations:
        relations = layout_relations
        logger.info(
            "[TLDraw ArrowAdder] Using %d edges from document.meta.edge_data",
            len(relations),
        )
    else:
        relations = collect_relations(concept_hierarchy)
        logger.info(
            "[TLDraw ArrowAdder] edge_data empty - falling back to structure.edges (%d edges)",
            len(relations),
        )
    edge_payloads = collect_edge_payloads(concept_hierarchy, store)
    port_hints = extract_edge_port_hints(concept_hierarchy, store)

    # Extract chart_type for diagram-type-aware routing fallback
    chart_type = unwrap_structure_instantiation(concept_hierarchy).get("chart_type")

    for rel in relations:
        # ``collect_relations`` tolerates loose payloads: the edges path does
        # not guarantee an ``id``, and a structure without top-level edges can
        # yield plain strings. Mirrors the Excalidraw arrow adder's ``.get``
        # access so a malformed relation is skipped, not fatal.
        if not isinstance(rel, dict):
            logger.warning("Skipping non-dict relation %r", rel)
            continue
        source_ref = rel.get("source", "")
        target_ref = rel.get("target", "")

        source_id = find_shape_id(store, source_ref, concept_hierarchy)
        target_id = find_shape_id(store, target_ref, concept_hierarchy)

        if not (source_id and target_id):
            logger.warning(
                "Could not find shapes for relation source %r -> target %r",
                source_ref,
                target_ref,
            )
            continue

        source_shape = store[source_id]
        target_shape = store[target_id]

        edge_key = rel.get("id", "")
        edge_payload = resolve_edge_payload(edge_payloads, edge_key)
        hinted = port_hints.get(edge_key)

        if not hinted and isinstance(rel, dict):
            start_hint = extract_side_from_port(rel.get("start"))
            end_hint = extract_side_from_port(rel.get("end"))
            if start_hint or end_hint:
                hinted = {"start": start_hint, "end": end_hint}

        if not hinted and edge_payload:
            start_hint = extract_side_from_port(edge_payload.get("start"))
            end_hint = extract_side_from_port(edge_payload.get("end"))
            if start_hint or end_hint:
                hinted = {"start": start_hint, "end": end_hint}

        # Audit the LLM/Structure hint against shape geometry. If a hint is
        # missing or in the wrong half-plane (e.g. target_side="top" when the
        # source is clearly below the target), override that side with the
        # geometric ground truth. Each side is audited independently.
        start_edge, end_edge = audit_sides(hinted, source_shape, target_shape)
        start_center = get_edge_center(source_shape, start_edge)
        end_center = get_edge_center(target_shape, end_edge)

        ax = min(start_center['x'], end_center['x'])
        ay = min(start_center['y'], end_center['y'])
        aw = end_center['x'] - start_center['x']
        ah = end_center['y'] - start_center['y']

        if aw == 0:
            aw = 1
        if ah == 0:
            ah = 1

        start_rel_x = start_center['x'] - ax
        start_rel_y = start_center['y'] - ay
        end_rel_x = end_center['x'] - ax
        end_rel_y = end_center['y'] - ay

        # Resolve routing: prefer layout edge payload, then relation, then diagram type.
        _routing = normalize_routing(edge_payload_value(edge_payload, "routing"))
        if _routing is None and isinstance(rel, dict):
            _routing = normalize_routing(rel.get("routing"))
        if _routing is None:
            _routing = derive_routing_from_sides(start_edge, end_edge, chart_type)
        _kind = _routing_to_tldraw_kind(_routing)
        edge_color = _resolve_edge_color(edge_payload)
        label_color = TLDrawColorValidator.normalize_color(
            edge_payload_value(edge_payload, "labelColor") or edge_color
        )
        start_arrowhead = _resolve_arrowhead(
            edge_payload_value(edge_payload, "arrowheadStart")
            or edge_payload_value(edge_payload, "startArrowhead"),
            "none",
        )
        end_arrowhead = _resolve_arrowhead(
            edge_payload_value(edge_payload, "arrowheadEnd")
            or edge_payload_value(edge_payload, "endArrowhead"),
            "arrow",
        )

        edge_seed = [
            "edge",
            edge_key or f"{source_ref}->{target_ref}",
            source_ref,
            target_ref,
            start_edge,
            end_edge,
        ]
        arrow_id = TLDrawIDGenerator.generate_shape_id("shape", seed=edge_seed)
        new_store_items[arrow_id] = {
            "x": ax,
            "y": ay,
            "rotation": 0,
            "isLocked": False,
            "opacity": 1,
            "meta": {
                "semantic_edge_id": edge_key,
                "source": source_ref,
                "target": target_ref,
            },
            "id": arrow_id,
            "type": "arrow",
            "parentId": store[source_id]["parentId"],
            "index": TLDrawIDGenerator.generate_stable_index("b", seed=edge_seed),
            "typeName": "shape",
            "props": {
                "dash": "draw",
                "size": "m",
                "fill": "none",
                "color": edge_color,
                "labelColor": label_color,
                "kind": _kind,
                "elbowMidPoint": 0.5,
                "bend": 0,
                "start": {"x": start_rel_x, "y": start_rel_y},
                "end": {"x": end_rel_x, "y": end_rel_y},
                "arrowheadStart": start_arrowhead,
                "arrowheadEnd": end_arrowhead,
                "text": "",
                "labelPosition": 0.5,
                "font": "draw",
                "scale": 1,
            },
        }

        binding_start_id = TLDrawIDGenerator.generate_binding_id(
            seed=[*edge_seed, "start_binding"]
        )
        new_store_items[binding_start_id] = {
            'meta': {},
            'id': binding_start_id,
            'type': 'arrow',
            'fromId': arrow_id,
            'toId': source_id,
            'props': {
                'isPrecise': True,
                'isExact': True,
                'normalizedAnchor': _make_normalized_anchor(start_center, source_shape),
                'terminal': 'start',
                'snap': None
            },
            'typeName': 'binding'
        }

        binding_end_id = TLDrawIDGenerator.generate_binding_id(
            seed=[*edge_seed, "end_binding"]
        )
        new_store_items[binding_end_id] = {
            'meta': {},
            'id': binding_end_id,
            'type': 'arrow',
            'fromId': arrow_id,
            'toId': target_id,
            'props': {
                'isPrecise': True,
                'isExact': True,
                'normalizedAnchor': _make_normalized_anchor(end_center, target_shape),
                'terminal': 'end'
            },
            'typeName': 'binding'
        }

    return new_store_items


class ArrowToolInput(BaseModel):
    manifest_json: Dict[str, Any] = Field(..., description="Original manifest.json data")
    concept_json: Dict[str, Any] = Field(..., description="concept_hierarchy.json data")
    output_path: Optional[str] = Field(None, description="Optional: output path for the updated manifest file")


def _arrow_tool_impl(
    manifest_json: Dict[str, Any],
    concept_json: Dict[str, Any],
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate arrows for the manifest based on concept relationships and return the updated JSON."""
    manifest = deepcopy(manifest_json)
    store = manifest.get("document", {}).get("store")
    if store is None:
        raise ValueError("manifest_json is missing document.store field")

    new_items = add_arrows(store, concept_json)
    store.update(new_items)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    return manifest


def make_arrow_adder_tool() -> StructuredTool:
    """Create an instance of the arrow adder tool."""
    return StructuredTool.from_function(
        func=_arrow_tool_impl,
        name="arrow_store_enricher",
        description="Add TLDraw arrow elements to manifest.json based on concept_hierarchy relationships",
        args_schema=ArrowToolInput,
    )


arrow_store_enricher = StructuredTool.from_function(
    func=_arrow_tool_impl,
    name="arrow_store_enricher",
    description="Add TLDraw arrow elements to manifest.json based on concept_hierarchy relationships",
    args_schema=ArrowToolInput,
)


def main():
    parser = argparse.ArgumentParser(description="Automatically generate arrow elements for manifest.json")
    parser.add_argument(
        "--manifest",
        type=str,
        default="manifest.json",
        help="Path to original manifest.json",
    )
    parser.add_argument(
        "--concept",
        type=str,
        default="concept_hierarchy.json",
        help="Path to concept_hierarchy.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="manifest_with_arrows.json",
        help="Output path",
    )

    args = parser.parse_args()

    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest_json = json.load(f)
    with open(args.concept, "r", encoding="utf-8") as f:
        concept_json = json.load(f)

    result = arrow_store_enricher.invoke(
        {
            "manifest_json": manifest_json,
            "concept_json": concept_json,
            "output_path": args.output,
        }
    )

    print(
        f"Generated {len(result.get('document', {}).get('store', {}))} store items "
        f"and wrote output to {args.output}."
    )


if __name__ == "__main__":
    main()
