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


def tldraw_arrow_terminals(schema_blob: Any) -> dict[str, dict[str, str]]:
    """Map each TLDraw arrow ID to the shapes its binding records attach it to.

    TLDraw 3 keeps arrow attachments in separate ``binding`` records
    (``fromId`` arrow, ``toId`` shape, ``props.terminal`` start or end).
    """
    if not isinstance(schema_blob, dict):
        return {}
    terminals: dict[str, dict[str, str]] = {}
    for value in _tldraw_records(schema_blob).values():
        if not isinstance(value, dict):
            continue
        if value.get("typeName") != "binding" or value.get("type") != "arrow":
            continue
        props = value.get("props")
        terminal = props.get("terminal") if isinstance(props, dict) else None
        if terminal in {"start", "end"} and value.get("fromId") and value.get("toId"):
            terminals.setdefault(str(value["fromId"]), {})[terminal] = str(value["toId"])
    return terminals


def _tldraw_records(schema_blob: dict[str, Any]) -> dict[str, Any]:
    # The editor's getSnapshot() and the TLDraw converter both save
    # {"document": {"store": ...}}; "records" maps stay readable.
    document = schema_blob.get("document")
    for holder in (document, schema_blob):
        if not isinstance(holder, dict):
            continue
        for key in ("store", "records"):
            records = holder.get(key)
            if isinstance(records, dict):
                return records
    return {}
