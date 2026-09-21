"""Complete mechanical Excalidraw fields without inventing scene geometry."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...render_engine.excalidraw.converter import _excalidraw_defaults


def complete_native_elements(manifest: dict[str, Any]) -> None:
    """Fill omitted native metadata and derive reciprocal binding references."""
    elements = manifest.get("elements")
    if not isinstance(elements, list):
        return
    by_id = {
        element["id"]: element
        for element in elements
        if isinstance(element, dict) and isinstance(element.get("id"), str)
    }
    for element in by_id.values():
        defaults = _excalidraw_defaults(["native", element["id"]])
        # Colours, coordinates, sizes, paths, and semantic IDs remain authored.
        defaults.pop("strokeColor")
        defaults.pop("backgroundColor")
        defaults["roughness"] = 0
        defaults["strokeWidth"] = 1.5
        for key, value in defaults.items():
            element.setdefault(key, deepcopy(value))
        if element.get("type") == "text":
            text_defaults = {
                "fontFamily": 2, "autoResize": True, "lineHeight": 1.25,
                "textAlign": "left", "verticalAlign": "top", "containerId": None,
            }
            if isinstance(element.get("text"), str):
                text_defaults["originalText"] = element["text"]
            for key, value in text_defaults.items():
                element.setdefault(key, value)

    for element in by_id.values():
        owners = []
        if element.get("type") == "text" and element.get("containerId"):
            owners.append(element["containerId"])
        elif element.get("type") == "arrow":
            for side in ("startBinding", "endBinding"):
                binding = element.get(side)
                if isinstance(binding, dict) and binding.get("elementId"):
                    owners.append(binding["elementId"])
        for owner_id in owners:
            owner = by_id.get(owner_id)
            if owner is None:
                continue  # Leave invalid authored references for validation.
            if owner.get("boundElements") is None:
                owner["boundElements"] = []
            bindings = owner.get("boundElements")
            if isinstance(bindings, list) and not any(
                isinstance(binding, dict) and binding.get("id") == element["id"]
                for binding in bindings
            ):
                bindings.append({"id": element["id"], "type": element["type"]})


def complete_native_semantics(manifest: dict[str, Any]) -> None:
    """Project authored semantic mappings into the shared router's metadata."""
    meta = manifest.get("_meta") or {}
    structure = meta.get("structure_instantiation") or {}
    id_map = meta.get("id_map") or {}
    by_id = {element["id"]: element for element in manifest.get("elements", [])}
    nodes = {node["id"]: node for node in structure.get("nodes", [])}
    edge_data = meta.setdefault("edge_data", {})
    for node_id, node in nodes.items():
        shape = by_id.get(id_map.get(node_id))
        if shape is not None:
            shape.setdefault("meta", {}).setdefault("semanticId", node_id)
    for edge in structure.get("edges", []):
        edge_id = edge["id"]
        arrow = by_id.get(id_map.get(edge_id))
        if arrow is None or arrow.get("type") != "arrow":
            raise ValueError(f"Native semantic edge {edge_id!r} must map to its arrow")
        arrow_meta = arrow.setdefault("meta", {})
        if arrow_meta.get("semantic_edge_id") != edge_id:
            raise ValueError(f"Native semantic edge {edge_id!r} has a conflicting arrow mapping")
        if any(arrow_meta.get(key, edge[key]) != edge[key] for key in ("source", "target")):
            raise ValueError(f"Native semantic edge {edge_id!r} has conflicting endpoint metadata")
        arrow_meta.update({"source": edge["source"], "target": edge["target"]})
        payload = {
            "type": "arrow",
            "start": {"elementId": edge["source"]},
            "end": {"elementId": edge["target"]},
            "routing": "elbowed" if arrow.get("elbowed") else "straight",
            **{key: arrow[key] for key in (
                "strokeColor", "strokeWidth", "strokeStyle", "opacity",
                "startArrowhead", "endArrowhead",
            ) if key in arrow},
        }
        label_id = id_map.get(f"{edge_id}:label")
        label = by_id.get(label_id)
        if label is None:
            label = next((element for element in by_id.values()
                          if element.get("type") == "text" and element.get("containerId") == arrow["id"]), None)
        if label is not None:
            if label.get("type") != "text":
                raise ValueError(f"Native semantic edge {edge_id!r} label must map to text")
            label_meta = label.setdefault("meta", {})
            if label_meta.get("semantic_edge_id", edge_id) != edge_id:
                raise ValueError(f"Native semantic edge {edge_id!r} has a conflicting label mapping")
            label_meta.update({"semantic_edge_id": edge_id, "semantic_arrow_id": arrow["id"]})
            id_map[f"{edge_id}:label"] = label["id"]
            payload["label"] = {key: label[key] for key in (
                "text", "fontSize", "fontFamily", "strokeColor", "textAlign", "verticalAlign",
            ) if key in label}
        elif edge.get("label"):
            payload["label"] = edge["label"]
        edge_data[edge_id] = payload
