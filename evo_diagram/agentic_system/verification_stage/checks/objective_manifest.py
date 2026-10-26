"""Canvas-neutral manifest views for objective verification checks.

The objective checks were originally written for Excalidraw manifests.  TLDraw
snapshots carry the same verification facts, but in ``document.store`` records.
This module builds a small read-only Excalidraw-like projection so the existing
geometry and binding checks can stay focused on their domain logic.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    LABEL_SUFFIX,
    TITLE_SUFFIX,
    companion_id,
)
from evo_diagram.canvas_runtime import normalize_canvas_library

from .binding_consistency import DERIVED_BINDINGS_META_KEY


def build_objective_manifest(
    manifest: Dict[str, Any],
    *,
    canvas_library: str = "excalidraw",
    structure: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the manifest shape consumed by objective geometry checks."""
    canvas_library = normalize_canvas_library(canvas_library)
    if canvas_library != "tldraw":
        return manifest
    return _build_tldraw_objective_manifest(manifest, structure=structure)


def _build_tldraw_objective_manifest(
    manifest: Dict[str, Any],
    *,
    structure: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    store = _tldraw_store(manifest)
    if not store:
        return {
            "type": "objective_view",
            "elements": [],
            "_meta": {"id_map": {}, DERIVED_BINDINGS_META_KEY: True},
        }

    elements: list[Dict[str, Any]] = []
    id_map: Dict[str, str] = {}
    element_by_id: Dict[str, Dict[str, Any]] = {}

    for key, record in store.items():
        if not isinstance(record, dict) or record.get("typeName") != "shape":
            continue
        element = _project_shape_record(record, fallback_id=str(key))
        if element is None:
            continue
        elements.append(element)
        element_by_id[element["id"]] = element
        semantic_id = _semantic_id_from_tldraw_shape_id(element["id"])
        if semantic_id:
            id_map[semantic_id] = element["id"]
        semantic_edge_id = element.get("semanticEdgeId")
        if isinstance(semantic_edge_id, str) and semantic_edge_id:
            id_map[semantic_edge_id] = element["id"]

    _add_structure_group_aliases(id_map, structure, element_by_id)
    _project_arrow_bindings(store.values(), element_by_id)

    return {
        "type": "objective_view",
        "elements": elements,
        # The arrow bindings above — including the ``boundElements`` back-refs
        # written onto each target shape — are DERIVED from TLDraw binding
        # records, not read from the snapshot. Flagging that here keeps
        # ``check_arrow_shape_binding`` from grading its own homework and lets
        # it report the back-ref sub-check as "not run" instead of "passed".
        "_meta": {"id_map": id_map, DERIVED_BINDINGS_META_KEY: True},
    }


def _tldraw_store(manifest: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}
    document = manifest.get("document")
    if not isinstance(document, dict):
        return {}
    store = document.get("store")
    return store if isinstance(store, dict) else {}


def _project_shape_record(
    record: Dict[str, Any],
    *,
    fallback_id: str,
) -> Optional[Dict[str, Any]]:
    shape_id = record.get("id") or fallback_id
    if not isinstance(shape_id, str) or not shape_id:
        return None

    props = record.get("props")
    if not isinstance(props, dict):
        props = {}

    shape_type = record.get("type")
    element: Dict[str, Any] = {
        "id": shape_id,
        "type": _project_shape_type(shape_type, props),
        "x": _number(record.get("x"), 0.0),
        "y": _number(record.get("y"), 0.0),
        "width": _number(props.get("w"), 0.0),
        "height": _number(props.get("h"), 0.0),
    }

    text = props.get("text")
    if isinstance(text, str):
        element["text"] = text
        element["originalText"] = text

    if shape_type == "arrow":
        meta = record.get("meta")
        if isinstance(meta, dict):
            element["_meta"] = dict(meta)
            semantic_edge_id = meta.get("semantic_edge_id")
            if isinstance(semantic_edge_id, str) and semantic_edge_id:
                element["semanticEdgeId"] = semantic_edge_id
        start = props.get("start")
        end = props.get("end")
        if isinstance(start, dict) and isinstance(end, dict):
            element["points"] = _project_tldraw_arrow_points(props)
            element["tldrawKind"] = props.get("kind")

    return element


def _project_tldraw_arrow_points(props: Dict[str, Any]) -> list[list[float]]:
    start = props.get("start")
    end = props.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        return []

    sx = _number(start.get("x"), 0.0)
    sy = _number(start.get("y"), 0.0)
    ex = _number(end.get("x"), 0.0)
    ey = _number(end.get("y"), 0.0)
    kind = props.get("kind")

    if kind == "elbow":
        midpoint = _clamp(_number(props.get("elbowMidPoint"), 0.5), 0.0, 1.0)
        if abs(ex - sx) >= abs(ey - sy):
            mx = sx + ((ex - sx) * midpoint)
            return [[sx, sy], [mx, sy], [mx, ey], [ex, ey]]
        my = sy + ((ey - sy) * midpoint)
        return [[sx, sy], [sx, my], [ex, my], [ex, ey]]

    if kind == "curved":
        mx = (sx + ex) / 2.0
        my = (sy + ey) / 2.0
        bend = _number(props.get("bend"), 0.0)
        if bend:
            dx = ex - sx
            dy = ey - sy
            length = max((dx * dx + dy * dy) ** 0.5, 1.0)
            mx += (-dy / length) * bend
            my += (dx / length) * bend
        return [[sx, sy], [mx, my], [ex, ey]]

    return [[sx, sy], [ex, ey]]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _project_shape_type(shape_type: Any, props: Dict[str, Any]) -> str:
    if shape_type == "arrow":
        return "arrow"
    if shape_type == "image":
        return "image"
    if shape_type == "text":
        return "text"
    if shape_type in {"frame", "group"}:
        return "rectangle"
    if shape_type == "geo":
        geo = props.get("geo")
        if geo in {"ellipse", "diamond", "triangle", "rectangle"}:
            return str(geo)
    return "rectangle"


def _semantic_id_from_tldraw_shape_id(shape_id: str) -> Optional[str]:
    if shape_id.startswith("shape:"):
        semantic_id = shape_id[len("shape:"):]
        return semantic_id or None
    return None


def _add_structure_group_aliases(
    id_map: Dict[str, str],
    structure: Optional[Dict[str, Any]],
    element_by_id: Dict[str, Dict[str, Any]],
) -> None:
    if not isinstance(structure, dict):
        return
    for group in structure.get("groups") or []:
        if not isinstance(group, dict):
            continue
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id:
            continue
        for suffix in (BACKGROUND_SUFFIX, TITLE_SUFFIX, LABEL_SUFFIX):
            semantic_id = companion_id(group_id, suffix)
            shape_id = f"shape:{semantic_id}"
            if shape_id in element_by_id:
                id_map.setdefault(semantic_id, shape_id)


def _project_arrow_bindings(
    records: Iterable[Any],
    element_by_id: Dict[str, Dict[str, Any]],
) -> None:
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("typeName") != "binding" or record.get("type") != "arrow":
            continue

        arrow_id = record.get("fromId")
        target_id = record.get("toId")
        if not isinstance(arrow_id, str) or not isinstance(target_id, str):
            continue

        arrow = element_by_id.get(arrow_id)
        if arrow is None or arrow.get("type") != "arrow":
            continue

        props = record.get("props")
        terminal = props.get("terminal") if isinstance(props, dict) else None
        binding_key = (
            "startBinding"
            if terminal == "start"
            else "endBinding"
            if terminal == "end"
            else None
        )
        if binding_key is None:
            continue

        arrow[binding_key] = {"elementId": target_id}
        target = element_by_id.get(target_id)
        if target is None:
            continue
        bound = target.get("boundElements")
        if not isinstance(bound, list):
            bound = []
            target["boundElements"] = bound
        already_bound = any(
            isinstance(item, dict) and item.get("id") == arrow_id
            for item in bound
        )
        if not already_bound:
            bound.append({"id": arrow_id, "type": "arrow"})


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_objective_manifest"]
