"""Compact architecture layer geometry before connector routing."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    TITLE_SUFFIX,
    group_frame_render_id,
    id_map_from_manifest,
)


_ARCHITECTURE_TYPES = {"architecture", "architecture_diagram"}
_FRAME_TOP_PADDING = 74.0
_FRAME_BOTTOM_PADDING = 40.0
_ROW_GAP = 86.0
_LAYER_GAP = 48.0
_SIDE_GAP = 120.0
_SIDE_WIDTH = 500.0
_MIN_CONTENT_WIDTH = 1100.0
_CONTENT_SIDE_PADDING = 150.0
_ROW_TOLERANCE = 100.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _element_size(element: Mapping[str, Any]) -> Tuple[float, float]:
    return _number(element.get("width")), _number(element.get("height"))


def _cluster_rows(elements: Sequence[Mapping[str, Any]]) -> List[List[Mapping[str, Any]]]:
    rows: List[List[Mapping[str, Any]]] = []
    for element in sorted(elements, key=lambda item: (_number(item.get("y")), _number(item.get("x")))):
        y = _number(element.get("y"))
        row = next(
            (candidate for candidate in rows if abs(y - _number(candidate[0].get("y"))) <= _ROW_TOLERANCE),
            None,
        )
        if row is None:
            rows.append([element])
        else:
            row.append(element)
    return [sorted(row, key=lambda item: _number(item.get("x"))) for row in rows]


def _shape_for_semantic(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    semantic_id: str,
) -> Optional[Dict[str, Any]]:
    render_id = id_map.get(semantic_id)
    element = elements_by_id.get(render_id or "")
    if not element or element.get("type") in {"text", "image", "arrow"}:
        return None
    return element


def _members_for_group(
    group: Mapping[str, Any],
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    members: List[Dict[str, Any]] = []
    for member_id in group.get("members", []) or []:
        if not isinstance(member_id, str):
            continue
        shape = _shape_for_semantic(elements_by_id, id_map, member_id)
        if shape is not None:
            members.append(shape)
    return members


def _move_bound_companions(
    elements_by_id: Mapping[str, Dict[str, Any]],
    shape: Mapping[str, Any],
    dx: float,
    dy: float,
) -> None:
    shape_id = shape.get("id")
    for element in elements_by_id.values():
        if element is shape:
            continue
        if element.get("containerId") == shape_id:
            element["x"] = _number(element.get("x")) + dx
            element["y"] = _number(element.get("y")) + dy


def _move_semantic_element(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    semantic_id: str,
    x: float,
    y: float,
) -> None:
    shape = _shape_for_semantic(elements_by_id, id_map, semantic_id)
    if shape is None:
        return
    dx = x - _number(shape.get("x"))
    dy = y - _number(shape.get("y"))
    shape["x"] = x
    shape["y"] = y
    _move_bound_companions(elements_by_id, shape, dx, dy)

    icon = elements_by_id.get(id_map.get(f"{semantic_id}{ICON_SUFFIX}", ""))
    if icon is not None:
        icon["x"] = _number(icon.get("x")) + dx
        icon["y"] = _number(icon.get("y")) + dy


def _set_title_position(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    group_id: str,
    x: float,
    y: float,
) -> None:
    title = elements_by_id.get(id_map.get(f"{group_id}{TITLE_SUFFIX}", ""))
    if title is not None:
        title["x"] = x
        title["y"] = y


def _frame_element(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    group_id: str,
) -> Optional[Dict[str, Any]]:
    frame_id = group_frame_render_id(id_map, group_id)
    frame = elements_by_id.get(frame_id or "")
    if not frame or frame.get("type") == "arrow":
        return None
    return frame


def _semantic_for_render_id(id_map: Mapping[str, str], render_id: str) -> str:
    for semantic_id, mapped_id in id_map.items():
        if mapped_id == render_id and not semantic_id.endswith((BACKGROUND_SUFFIX, TITLE_SUFFIX, ICON_SUFFIX)):
            return semantic_id
    return render_id


def compact_architecture_layout(
    manifest: Dict[str, Any],
    structure_instantiation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pack architecture groups into compact horizontal layers.

    Node dimensions, left-to-right ordering, membership, bound text, and icon
    placement are preserved. Only positions and group frame dimensions change.
    """
    if not isinstance(manifest, dict) or not isinstance(structure_instantiation, dict):
        return manifest
    structure = unwrap_structure_instantiation(structure_instantiation)
    if str(structure.get("chart_type", "")).strip().lower() not in _ARCHITECTURE_TYPES:
        return manifest

    groups = [group for group in structure.get("groups", []) or [] if isinstance(group, dict)]
    if not groups:
        return manifest

    output = deepcopy(manifest)
    elements = [element for element in output.get("elements", []) if isinstance(element, dict)]
    elements_by_id = {
        element["id"]: element
        for element in elements
        if isinstance(element.get("id"), str)
    }
    id_map = id_map_from_manifest(output)

    layer_groups = [
        group for group in groups
        if str(group.get("class", "")).lower() == "architecture_layer"
        or (
            str(group.get("id", "")).startswith("group_")
            and "cross" not in str(group.get("id", "")).lower()
        )
    ]
    side_groups = [
        group for group in groups
        if group not in layer_groups
        and (
            "cross" in str(group.get("class", "")).lower()
            or "cross" in str(group.get("id", "")).lower()
        )
    ]

    records: List[Dict[str, Any]] = []
    for group in layer_groups:
        group_id = str(group.get("id", ""))
        frame = _frame_element(elements_by_id, id_map, group_id)
        members = _members_for_group(group, elements_by_id, id_map)
        if frame is None or not members:
            continue
        rows = _cluster_rows(members)
        if rows:
            records.append({
                "group": group,
                "frame": frame,
                "members": members,
                "rows": rows,
                "old_y": _number(frame.get("y")),
                "old_x": _number(frame.get("x")),
            })
    if not records:
        return manifest
    records.sort(key=lambda record: (record["old_y"], record["old_x"]))

    max_row_width = 0.0
    for record in records:
        for row in record["rows"]:
            max_row_width = max(
                max_row_width,
                sum(_element_size(element)[0] for element in row)
                + _ROW_GAP * max(0, len(row) - 1),
            )
    content_width = max(_MIN_CONTENT_WIDTH, max_row_width + 2 * _CONTENT_SIDE_PADDING)
    main_x = min(record["old_x"] for record in records)
    main_right = main_x + content_width
    next_y = min(record["old_y"] for record in records)
    row_centers: List[Tuple[float, float]] = []

    for record in records:
        group = record["group"]
        group_id = str(group.get("id", ""))
        frame = record["frame"]
        rows = record["rows"]
        row_heights = [max(_element_size(element)[1] for element in row) for row in rows]
        frame_height = (
            _FRAME_TOP_PADDING
            + sum(row_heights)
            + _ROW_GAP * max(0, len(rows) - 1)
            + _FRAME_BOTTOM_PADDING
        )
        frame["x"] = main_x
        frame["y"] = next_y
        frame["width"] = content_width
        frame["height"] = frame_height
        _set_title_position(elements_by_id, id_map, group_id, main_x + 30.0, next_y + 20.0)

        row_y = next_y + _FRAME_TOP_PADDING
        for row, row_height in zip(rows, row_heights):
            row_width = sum(_element_size(element)[0] for element in row) + _ROW_GAP * max(0, len(row) - 1)
            cursor = main_x + (content_width - row_width) / 2.0
            for element in row:
                render_id = str(element.get("id", ""))
                semantic_id = _semantic_for_render_id(id_map, render_id)
                width, _ = _element_size(element)
                _move_semantic_element(elements_by_id, id_map, semantic_id, cursor, row_y)
                cursor += width + _ROW_GAP
            row_centers.append((record["old_y"], row_y + row_height / 2.0))
            row_y += row_height + _ROW_GAP
        record["target_y"] = next_y
        record["target_height"] = frame_height
        next_y += frame_height + _LAYER_GAP

    total_bottom = next_y - _LAYER_GAP
    for group in side_groups:
        group_id = str(group.get("id", ""))
        frame = _frame_element(elements_by_id, id_map, group_id)
        members = _members_for_group(group, elements_by_id, id_map)
        if frame is None or not members:
            continue
        frame["x"] = main_right + _SIDE_GAP
        frame["y"] = min(record["target_y"] for record in records)
        frame["width"] = _SIDE_WIDTH
        frame["height"] = total_bottom - frame["y"]
        _set_title_position(elements_by_id, id_map, group_id, frame["x"] + 30.0, frame["y"] + 20.0)
        side_center_x = frame["x"] + frame["width"] / 2.0
        for member in members:
            render_id = str(member.get("id", ""))
            semantic_id = _semantic_for_render_id(id_map, render_id)
            nearest_center = min(
                row_centers,
                key=lambda pair: abs(pair[0] - _number(member.get("y"))),
            )[1]
            width, height = _element_size(member)
            _move_semantic_element(
                elements_by_id,
                id_map,
                semantic_id,
                side_center_x - width / 2.0,
                nearest_center - height / 2.0,
            )

    output["elements"] = elements
    return output


__all__ = ["compact_architecture_layout"]
