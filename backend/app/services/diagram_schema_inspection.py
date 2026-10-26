"""Shared helpers for inspecting persisted diagram schema collections."""

from __future__ import annotations

from typing import Any


NODE_COLLECTION_KEYS = ("elements", "nodes", "shapes", "blocks")
CONNECTOR_COLLECTION_KEYS = ("connectors", "edges", "links", "relations", "arrows")
TL_DRAW_ARROW_TYPES = {"arrow", "line", "edge", "connector"}


def first_schema_collection(schema_blob: Any, keys: tuple[str, ...]) -> list[Any]:
    """Return the first list-valued schema collection among the supported keys."""
    if not isinstance(schema_blob, dict):
        return []
    for key in keys:
        value = schema_blob.get(key)
        if isinstance(value, list):
            return value
    if keys == NODE_COLLECTION_KEYS:
        return tldraw_shape_records(schema_blob, include_arrows=False)
    if keys == CONNECTOR_COLLECTION_KEYS:
        return tldraw_shape_records(schema_blob, include_arrows=True)
    return []


def count_schema_collection(schema_blob: Any, keys: tuple[str, ...]) -> int:
    """Return the number of items in the first matching schema collection."""
    return len(first_schema_collection(schema_blob, keys))


def tldraw_shape_records(
    schema_blob: dict[str, Any],
    *,
    include_arrows: bool,
) -> list[dict[str, Any]]:
    """Return TLDraw shape records from root or document-level records maps."""
    records = _tldraw_records(schema_blob)
    shapes: list[dict[str, Any]] = []
    for value in records.values():
        if not isinstance(value, dict):
            continue
        if value.get("typeName") != "shape":
            continue
        is_arrow = str(value.get("type", "")).lower() in TL_DRAW_ARROW_TYPES
        if is_arrow == include_arrows:
            shapes.append(value)
    return shapes


def _tldraw_records(schema_blob: dict[str, Any]) -> dict[str, Any]:
    document = schema_blob.get("document")
    if isinstance(document, dict) and isinstance(document.get("records"), dict):
        return document["records"]

    records = schema_blob.get("records")
    if isinstance(records, dict):
        return records
    return {}
