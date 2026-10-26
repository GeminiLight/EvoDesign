"""Validate model edits against the selected canvas records before applying them."""
from copy import deepcopy
from math import isfinite
from typing import Any


class LocalEditResponseError(RuntimeError):
    """The model returned an invalid or out-of-scope canvas delta."""


def _merge(original: dict, patch: dict) -> dict:
    result = deepcopy(original)
    for key, value in patch.items():
        result[key] = (_merge(result[key], value)
                       if isinstance(value, dict) and isinstance(result.get(key), dict)
                       else deepcopy(value))
    return result


def normalize_local_edit(delta: dict, selected: dict, schema: dict, canvas: str) -> dict:
    """Omission means unchanged; deletion must name an explicitly selected ID.

    Existing unselected IDs cannot be updated, even if a model guesses them.
    Partial updates preserve the original record's canvas metadata and labels.
    """
    excalidraw = canvas == "excalidraw"
    key = "elements" if excalidraw else "records"
    original = ({item["id"]: item for item in selected[key]}
                if excalidraw else selected[key])
    if excalidraw:
        existing = {item.get("id") for item in schema.get("elements", []) if isinstance(item, dict)}
        updates = [(None, item) for item in delta[key]]
    else:
        document = schema.get("document") if isinstance(schema.get("document"), dict) else {}
        existing = set(document.get("store") or document.get("records")
                       or schema.get("store") or schema.get("records") or {})
        updates = list(delta[key].items())
    deleted = delta.get("deleted_ids", [])
    if not isinstance(deleted, list) or any(not isinstance(item, str) for item in deleted):
        raise LocalEditResponseError("deleted_ids must be an array of selected IDs")
    deleted = set(deleted)
    if not deleted <= original.keys():
        raise LocalEditResponseError("Local edit cannot delete unselected nodes")
    result: dict[str, Any] = {}
    seen: set[str] = set()
    for record_key, item in updates:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise LocalEditResponseError("Each edited node must have a nonempty ID")
        node_id = item["id"]
        if node_id in seen or (not excalidraw and node_id != record_key):
            raise LocalEditResponseError("Duplicate or inconsistent edited node ID")
        seen.add(node_id)
        if node_id in existing and node_id not in original:
            raise LocalEditResponseError("Local edit cannot change unselected nodes")
        if item.get("isDeleted") is True:
            if node_id not in original:
                raise LocalEditResponseError("Local edit cannot delete unselected nodes")
            deleted.add(node_id)
            continue
        if node_id in deleted:
            raise LocalEditResponseError("A node cannot be both updated and deleted")
        prior = original.get(node_id, {})
        for field in ("type", "typeName"):
            if field in prior and field in item and item[field] != prior[field]:
                raise LocalEditResponseError("Local edits must preserve the canvas record type")
        merged = _merge(prior, item)
        for field in ("x", "y", "width", "height", "angle", "rotation"):
            if field in merged and (isinstance(merged[field], bool)
                                    or not isinstance(merged[field], (int, float))
                                    or not isfinite(merged[field])):
                raise LocalEditResponseError("Edited geometry must contain finite numbers")
        result[node_id] = merged
    return {key: list(result.values()) if excalidraw else result,
            **({"deleted_ids": sorted(deleted)} if deleted else {})}
