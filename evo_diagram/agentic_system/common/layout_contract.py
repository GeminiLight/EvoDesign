"""Layout-stage contract checks shared by generation and render boundaries."""

from __future__ import annotations

from typing import Any, Dict, Optional

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    TITLE_SUFFIX,
    companion_id,
)
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation


class LayoutValidationError(ValueError):
    """Raised when Layout output violates cross-stage element contracts."""


VALID_EDGE_SIDES = frozenset({"top", "bottom", "left", "right"})


def validate_layout_instantiation(
    layout_instantiation: Any,
    *,
    structure_instantiation: Optional[Dict[str, Any]] = None,
    styling_instantiation: Optional[Dict[str, Any]] = None,
    require_complete_styling_geometry: bool = True,
) -> Dict[str, Any]:
    """Validate Layout output against Structure ids and Styling render keys.

    Layout is allowed to add geometry and edge routing only. It must not invent
    semantic elements, omit geometry for styled renderable elements, or rewrite
    the Structure edge endpoints.
    """
    if not isinstance(layout_instantiation, dict):
        raise LayoutValidationError(
            "Layout instantiation must be a JSON object; "
            f"got {type(layout_instantiation).__name__}."
        )

    styling = styling_instantiation if isinstance(styling_instantiation, dict) else None
    structure = unwrap_structure_instantiation(structure_instantiation)
    edge_contracts = _collect_edge_contracts(structure)
    structure_edge_ids = set(edge_contracts)
    structure_group_ids = _collect_structure_ids(structure, "groups")

    allowed_layout_ids = _allowed_layout_ids(structure, styling)
    for element_id, element_data in layout_instantiation.items():
        if element_id == "specification":
            raise LayoutValidationError(
                "Layout instantiation must not contain a nested 'specification' key; "
                "unwrap the agent output before validation."
            )
        if not isinstance(element_id, str) or not element_id.strip():
            raise LayoutValidationError(f"Layout element id must be a non-empty string; got {element_id!r}.")

        if _is_rejected_underscore_icon_key(element_id):
            raise LayoutValidationError(
                f"Unsupported underscore icon layout id {element_id!r}; "
                "use the canonical '<node_id>:icon' suffix."
            )

        if _is_icon_key(element_id):
            _validate_known_id(element_id, allowed_layout_ids)
            continue

        if is_layout_edge_entry(element_id, element_data, structure_edge_ids):
            _validate_known_edge_id(element_id, styling, edge_contracts)
            _validate_edge_payload(element_id, element_data, edge_contracts.get(element_id))
            continue

        _validate_known_id(element_id, allowed_layout_ids)
        if _is_group_shell_with_background(element_id, layout_instantiation, structure_group_ids):
            continue
        _validate_geometry(element_id, element_data)

    if require_complete_styling_geometry and styling is not None:
        _validate_all_styled_renderables_have_geometry(
            layout_instantiation,
            styling,
            structure_edge_ids,
            structure_group_ids,
        )

    for edge_id, endpoints in edge_contracts.items():
        edge_payload = layout_instantiation.get(edge_id)
        if edge_payload is None:
            raise LayoutValidationError(f"Missing layout edge entry for Structure edge {edge_id!r}.")
        _validate_edge_payload(edge_id, edge_payload, endpoints)

    return layout_instantiation


def is_layout_edge_entry(
    element_id: Any,
    element_data: Any,
    structure_edge_ids: Optional[set[str]] = None,
) -> bool:
    """Return whether a layout map entry represents an edge."""
    if isinstance(element_id, str):
        if element_id.startswith("edge:"):
            return True
        if structure_edge_ids and element_id in structure_edge_ids:
            return True
    if isinstance(element_data, dict):
        start = element_data.get("start")
        end = element_data.get("end")
        return isinstance(start, dict) and isinstance(end, dict)
    return False


def _collect_edge_contracts(structure_instantiation: Dict[str, Any]) -> Dict[str, tuple[str, str]]:
    contracts: Dict[str, tuple[str, str]] = {}
    for index, edge in enumerate(structure_instantiation.get("edges") or []):
        if not isinstance(edge, dict):
            raise LayoutValidationError(f"Structure edge at index {index} must be an object.")
        edge_id = edge.get("id")
        source = edge.get("source", edge.get("from"))
        target = edge.get("target", edge.get("to"))
        if not all(isinstance(value, str) and value.strip() for value in (edge_id, source, target)):
            raise LayoutValidationError(
                f"Structure edge at index {index} must include non-empty id/source/target fields."
            )
        contracts[edge_id] = (source, target)
    return contracts


def _collect_structure_ids(structure_instantiation: Dict[str, Any], field_name: str) -> set[str]:
    ids: set[str] = set()
    for item in structure_instantiation.get(field_name) or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            ids.add(item["id"])
    return ids


def _allowed_layout_ids(
    structure_instantiation: Dict[str, Any],
    styling_instantiation: Optional[Dict[str, Any]],
) -> set[str]:
    if styling_instantiation:
        return {
            element_id
            for element_id in styling_instantiation
            if isinstance(element_id, str)
        }

    allowed: set[str] = set()
    for node in structure_instantiation.get("nodes") or []:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            node_id = node["id"]
            allowed.add(node_id)
            allowed.add(companion_id(node_id, ICON_SUFFIX))

    for group in structure_instantiation.get("groups") or []:
        if isinstance(group, dict) and isinstance(group.get("id"), str):
            group_id = group["id"]
            allowed.add(group_id)
            allowed.add(companion_id(group_id, BACKGROUND_SUFFIX))
            allowed.add(companion_id(group_id, TITLE_SUFFIX))

    allowed.update(_collect_edge_contracts(structure_instantiation))
    return allowed


def _is_icon_key(element_id: str) -> bool:
    return element_id.endswith(ICON_SUFFIX)


def _is_rejected_underscore_icon_key(element_id: str) -> bool:
    return element_id.endswith("_icon")


def _validate_known_id(element_id: str, allowed_layout_ids: Optional[set[str]]) -> None:
    # ``None`` means "no id set was derivable, skip the check". An *empty* set
    # means the upstream Structure/Styling stages produced no renderable ids at
    # all, so every layout id is unknown by definition — treating the empty set
    # as falsy here let a node-less Structure wave through arbitrary layout ids.
    if allowed_layout_ids is not None and element_id not in allowed_layout_ids:
        raise LayoutValidationError(f"Unknown layout id {element_id!r}; Layout must reuse Styling/Structure ids.")


def _validate_known_edge_id(
    edge_id: str,
    styling_instantiation: Optional[Dict[str, Any]],
    edge_contracts: Dict[str, tuple[str, str]],
) -> None:
    if edge_contracts:
        if edge_id not in edge_contracts:
            raise LayoutValidationError(f"Unknown layout id {edge_id!r}; no matching Structure edge id.")
        return
    if styling_instantiation is not None and edge_id not in styling_instantiation:
        raise LayoutValidationError(f"Unknown layout id {edge_id!r}; Layout must reuse Styling edge ids.")


def _validate_all_styled_renderables_have_geometry(
    layout_instantiation: Dict[str, Any],
    styling_instantiation: Dict[str, Any],
    structure_edge_ids: set[str],
    structure_group_ids: set[str],
) -> None:
    for element_id, element_data in styling_instantiation.items():
        if not isinstance(element_id, str):
            continue
        if element_id.startswith("_") or element_id in {"metadata", "meta", "specification"}:
            continue
        if _is_icon_key(element_id):
            continue
        if is_layout_edge_entry(element_id, element_data, structure_edge_ids):
            continue
        if element_id.startswith("edge:") or element_id in structure_edge_ids:
            continue
        if _is_group_shell_with_background(element_id, layout_instantiation, structure_group_ids):
            continue

        if element_id not in layout_instantiation:
            raise LayoutValidationError(f"Missing layout geometry for styled element {element_id!r}.")
        _validate_geometry(element_id, layout_instantiation[element_id])


def _validate_geometry(element_id: str, element_data: Any) -> None:
    if not isinstance(element_data, dict):
        raise LayoutValidationError(
            f"Missing layout geometry for {element_id!r}; expected object with x, y, w, h."
        )
    missing = [field for field in ("x", "y", "w", "h") if field not in element_data]
    if missing:
        fields = ", ".join(missing)
        raise LayoutValidationError(f"Missing geometry fields for {element_id!r}: {fields}.")

    non_numeric = [
        field
        for field in ("x", "y", "w", "h")
        if not _is_number(element_data.get(field))
    ]
    if non_numeric:
        fields = ", ".join(non_numeric)
        raise LayoutValidationError(f"Geometry fields for {element_id!r} must be numeric: {fields}.")
    if element_data["w"] <= 0 or element_data["h"] <= 0:
        raise LayoutValidationError(f"Geometry fields for {element_id!r} must have positive w and h.")


def _is_group_shell_with_background(
    element_id: str,
    layout_instantiation: Dict[str, Any],
    structure_group_ids: set[str],
) -> bool:
    return (
        element_id in structure_group_ids
        and companion_id(element_id, BACKGROUND_SUFFIX) in layout_instantiation
    )


def _validate_edge_payload(
    edge_id: str,
    element_data: Any,
    expected_endpoints: Optional[tuple[str, str]],
) -> None:
    if not isinstance(element_data, dict):
        raise LayoutValidationError(f"Layout edge {edge_id!r} must be an object with start/end ports.")

    start = element_data.get("start")
    end = element_data.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise LayoutValidationError(f"Layout edge {edge_id!r} must include start and end port objects.")

    start_id = start.get("elementId")
    end_id = end.get("elementId")
    start_side = start.get("side")
    end_side = end.get("side")
    if not isinstance(start_id, str) or not start_id.strip():
        raise LayoutValidationError(f"Layout edge {edge_id!r} start.elementId must be a non-empty string.")
    if not isinstance(end_id, str) or not end_id.strip():
        raise LayoutValidationError(f"Layout edge {edge_id!r} end.elementId must be a non-empty string.")
    if not isinstance(start_side, str) or not start_side.strip():
        raise LayoutValidationError(f"Layout edge {edge_id!r} start.side must be a non-empty string.")
    if not isinstance(end_side, str) or not end_side.strip():
        raise LayoutValidationError(f"Layout edge {edge_id!r} end.side must be a non-empty string.")
    if start_side not in VALID_EDGE_SIDES:
        raise LayoutValidationError(
            f"Layout edge {edge_id!r} start.side must be one of "
            f"{sorted(VALID_EDGE_SIDES)}; got {start_side!r}."
        )
    if end_side not in VALID_EDGE_SIDES:
        raise LayoutValidationError(
            f"Layout edge {edge_id!r} end.side must be one of "
            f"{sorted(VALID_EDGE_SIDES)}; got {end_side!r}."
        )
    if "waypoints" in element_data:
        raise LayoutValidationError(
            f"Layout edge {edge_id!r} must not include waypoints; "
            "renderer computes the path from start/end sides."
        )

    if expected_endpoints is None:
        return

    expected_source, expected_target = expected_endpoints
    if start_id != expected_source or end_id != expected_target:
        raise LayoutValidationError(
            f"Edge endpoint mismatch for {edge_id!r}: expected "
            f"{expected_source!r}->{expected_target!r}, got {start_id!r}->{end_id!r}."
        )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
