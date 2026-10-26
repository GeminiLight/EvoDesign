"""Semantic sidecar contract for unified one-shot manifests."""

from __future__ import annotations

from typing import Any, Dict

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    companion_base_id,
    companion_id,
)
from evo_diagram.agentic_system.generation_stage.structure.schemas import (
    StructureValidationError,
    validate_structure_instantiation,
)


def _semantic_id_sets(structure: Dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    def collect(field_name: str) -> set[str]:
        return {
            item["id"]
            for item in structure.get(field_name, []) or []
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"].strip()
        }

    return collect("nodes"), collect("groups"), collect("edges")


def validate_semantic_sidecar(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and canonicalize a one-shot manifest semantic sidecar.

    Unified one-shot generation bypasses the separate Structure/Styling/Layout
    handoff files, so ``_meta.structure_instantiation`` and ``_meta.id_map`` are
    the only durable bridge from semantic graph IDs to rendered canvas IDs.
    """
    meta = manifest.get("_meta")
    if not isinstance(meta, dict):
        raise ValueError("UnifiedGenerator output missing required _meta object")

    structure_payload = meta.get("structure_instantiation")
    if not isinstance(structure_payload, dict):
        raise ValueError(
            "UnifiedGenerator output _meta.structure_instantiation must be a JSON object"
        )

    try:
        structure = validate_structure_instantiation(structure_payload)
    except StructureValidationError as exc:
        raise ValueError(
            f"UnifiedGenerator semantic sidecar validation failed: {exc}"
        ) from exc
    meta["structure_instantiation"] = structure

    id_map = meta.get("id_map")
    if not isinstance(id_map, dict) or not id_map:
        raise ValueError("UnifiedGenerator output _meta.id_map must be a non-empty object")
    invalid_id_map = [
        key
        for key, value in id_map.items()
        if not isinstance(key, str) or not key.strip()
        or not isinstance(value, str) or not value.strip()
    ]
    if invalid_id_map:
        sample = ", ".join(repr(key) for key in invalid_id_map[:5])
        raise ValueError(f"UnifiedGenerator output _meta.id_map has invalid entries: {sample}")

    node_ids, group_ids, edge_ids = _semantic_id_sets(structure)
    expected_semantic_ids = node_ids | group_ids | edge_ids
    id_map_keys = set(id_map)
    missing_semantic_ids = sorted((node_ids | edge_ids) - id_map_keys)
    missing_semantic_ids.extend(
        sorted(
            group_id
            for group_id in group_ids
            if group_id not in id_map_keys
            and companion_id(group_id, BACKGROUND_SUFFIX) not in id_map_keys
        )
    )
    if missing_semantic_ids:
        raise ValueError(
            "UnifiedGenerator output _meta.id_map is missing semantic id(s): "
            f"{', '.join(missing_semantic_ids[:5])}"
        )

    unknown_semantic_ids = sorted(
        key
        for key in id_map_keys
        if key not in expected_semantic_ids
        and companion_base_id(key) not in expected_semantic_ids
    )
    if unknown_semantic_ids:
        raise ValueError(
            "UnifiedGenerator output _meta.id_map contains unknown semantic id(s): "
            f"{', '.join(unknown_semantic_ids[:5])}"
        )

    rendered_ids = {
        element.get("id")
        for element in manifest.get("elements", [])
        if isinstance(element, dict) and isinstance(element.get("id"), str)
    }
    missing_render_ids = sorted(
        value
        for value in id_map.values()
        if isinstance(value, str) and value not in rendered_ids
    )
    if missing_render_ids:
        raise ValueError(
            "UnifiedGenerator output _meta.id_map references missing Excalidraw "
            f"element id(s): {', '.join(missing_render_ids[:5])}"
        )

    expected_edge_ids = {
        edge["id"]
        for edge in structure.get("edges", []) or []
        if isinstance(edge, dict) and isinstance(edge.get("id"), str)
    }
    if expected_edge_ids:
        rendered_edge_ids: set[str] = set()
        for element in manifest.get("elements", []) or []:
            if not isinstance(element, dict) or element.get("type") != "arrow":
                continue
            meta_payload = element.get("meta")
            if isinstance(meta_payload, dict) and isinstance(
                meta_payload.get("semantic_edge_id"),
                str,
            ):
                rendered_edge_ids.add(meta_payload["semantic_edge_id"])
        missing_edge_ids = sorted(expected_edge_ids - rendered_edge_ids)
        if missing_edge_ids:
            raise ValueError(
                "UnifiedGenerator output missing arrow meta.semantic_edge_id for "
                f"Structure edge id(s): {', '.join(missing_edge_ids[:5])}"
            )

    return structure


__all__ = ["validate_semantic_sidecar"]
