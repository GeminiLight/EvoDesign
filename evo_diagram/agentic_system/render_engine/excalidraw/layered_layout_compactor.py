"""Compact architecture layer geometry before connector routing."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from evo_diagram.agentic_system.generation_stage.layout.element_shape_estimator import (
    _estimate_text_dimensions,
)
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
_ROW_GAP = 68.0
_LAYER_GAP = 48.0
_SIDE_GAP = 56.0
_SIDE_WIDTH = 360.0
_MIN_CONTENT_WIDTH = 980.0
# Keep the main stack compact while retaining a clear frame margin around the
# widest row.  The minimum content width still prevents narrow diagrams from
# collapsing.
_CONTENT_SIDE_PADDING = 60.0
_ROW_TOLERANCE = 100.0
_MIN_ROW_CENTER_GAP = 128.0
_NODE_FONT_SIZE = 18
_NODE_MIN_WIDTH = 180.0
_NODE_MAX_WIDTH = 300.0
_NODE_MIN_HEIGHT = 60.0
_NODE_MAX_HEIGHT = 84.0
_NODE_HORIZONTAL_PADDING = 44.0
_NODE_VERTICAL_PADDING = 26.0
_NODE_SHAPE_INFLATE = {
    "rectangle": 1.0,
    "ellipse": 1.14,
    "diamond": 1.28,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _element_size(element: Mapping[str, Any]) -> Tuple[float, float]:
    return _number(element.get("width")), _number(element.get("height"))


def _bound_text_for_shape(
    elements_by_id: Mapping[str, Dict[str, Any]],
    shape: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    shape_id = str(shape.get("id", ""))
    for binding in shape.get("boundElements", []) or []:
        if not isinstance(binding, Mapping) or binding.get("type") != "text":
            continue
        text = elements_by_id.get(str(binding.get("id", "")))
        if text is not None:
            return text
    return next(
        (
            element
            for element in elements_by_id.values()
            if element.get("type") == "text"
            and str(element.get("containerId", "")) == shape_id
        ),
        None,
    )


def _normalize_member_size(
    elements_by_id: Mapping[str, Dict[str, Any]],
    id_map: Mapping[str, str],
    semantic_id: str,
) -> None:
    """Fit architecture components to their labels within a compact size band."""
    shape = _shape_for_semantic(elements_by_id, id_map, semantic_id)
    if shape is None or shape.get("type") not in _NODE_SHAPE_INFLATE:
        return
    text = _bound_text_for_shape(elements_by_id, shape)
    if text is None:
        return

    label = str(text.get("originalText") or text.get("text") or "")
    text["fontSize"] = _NODE_FONT_SIZE
    text["lineHeight"] = 1.2
    text_bbox = _estimate_text_dimensions(label, _NODE_FONT_SIZE)
    inflate = _NODE_SHAPE_INFLATE[str(shape.get("type"))]

    icon = elements_by_id.get(id_map.get(f"{semantic_id}{ICON_SUFFIX}", ""))
    icon_extra = 0.0
    if icon is not None:
        icon_extra = _number(icon.get("width")) + 24.0

    target_width = min(
        _NODE_MAX_WIDTH,
        max(
            _NODE_MIN_WIDTH,
            math.ceil(text_bbox["width"] * inflate + _NODE_HORIZONTAL_PADDING + icon_extra),
        ),
    )
    target_height = min(
        _NODE_MAX_HEIGHT,
        max(
            _NODE_MIN_HEIGHT,
            math.ceil(text_bbox["height"] * inflate + _NODE_VERTICAL_PADDING),
        ),
    )
    shape["width"] = target_width
    shape["height"] = target_height

    text_width = min(math.ceil(text_bbox["width"]), target_width - 32.0)
    text_height = min(math.ceil(text_bbox["height"]), target_height - 20.0)
    content_left = _number(shape.get("x"))
    if icon is not None:
        icon["x"] = content_left + 16.0
        icon["y"] = (
            _number(shape.get("y"))
            + (target_height - _number(icon.get("height"))) / 2.0
        )
        content_left = icon["x"] + _number(icon.get("width")) + 12.0
    content_right = _number(shape.get("x")) + target_width - 16.0
    text_center_x = content_left + (content_right - content_left) / 2.0
    text["x"] = text_center_x - text_width / 2.0
    text["y"] = _number(shape.get("y")) + (target_height - text_height) / 2.0
    text["width"] = text_width
    text["height"] = text_height


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


def _merge_crowded_rows(
    rows: Sequence[Sequence[Mapping[str, Any]]],
) -> List[List[Mapping[str, Any]]]:
    """Merge model rows that are too close to leave a usable edge corridor."""
    merged: List[List[Mapping[str, Any]]] = []
    for row in rows:
        current = sorted(row, key=lambda item: _number(item.get("x")))
        if not merged:
            merged.append(current)
            continue
        previous_center = sum(
            _number(item.get("y")) + _number(item.get("height")) / 2.0
            for item in merged[-1]
        ) / len(merged[-1])
        current_center = sum(
            _number(item.get("y")) + _number(item.get("height")) / 2.0
            for item in current
        ) / len(current)
        if current_center - previous_center < _MIN_ROW_CENTER_GAP:
            merged[-1] = sorted(
                [*merged[-1], *current],
                key=lambda item: _number(item.get("x")),
            )
        else:
            merged.append(current)
    return merged


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
    nodes: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    members: List[Dict[str, Any]] = []
    group_id = str(group.get("id", ""))
    member_ids = [
        member_id
        for member_id in group.get("members", []) or []
        if isinstance(member_id, str)
    ]
    if not member_ids:
        # Unified sidecars commonly attach membership to nodes instead of
        # duplicating it in ``group.members``.  Accept both representations.
        member_ids = [
            str(node.get("id"))
            for node in nodes
            if str(node.get("group_id", "")) == group_id and node.get("id")
        ]
    for member_id in member_ids:
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
    if title is None:
        # Unified manifests often use the semantic companion ID directly but
        # omit it from id_map because only the group frame is addressable.
        title = elements_by_id.get(f"{group_id}{TITLE_SUFFIX}")
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


def _order_row_by_predecessors(
    row: Sequence[Mapping[str, Any]],
    id_map: Mapping[str, str],
    predecessor_ids: Mapping[str, Sequence[str]],
    original_center_x: Mapping[str, float],
    original_center_y: Mapping[str, float],
) -> List[Mapping[str, Any]]:
    """Order a fan-in row by upstream barycenter, preserving ordinary rows."""
    ordered = sorted(row, key=lambda element: _number(element.get("x")))
    if len(ordered) < 3:
        return ordered
    semantic_ids = [
        _semantic_for_render_id(id_map, str(element.get("id", "")))
        for element in ordered
    ]
    def upstream_predecessor_count(semantic_id: str) -> int:
        target_y = original_center_y.get(semantic_id)
        if target_y is None:
            return 0
        return sum(
            1
            for source_id in predecessor_ids.get(semantic_id, [])
            if source_id in original_center_y
            and original_center_y[source_id] < target_y - 50.0
        )

    if max((upstream_predecessor_count(item) for item in semantic_ids), default=0) < 2:
        return ordered

    authored_rank = {str(element.get("id", "")): index for index, element in enumerate(ordered)}

    def upstream_center(element: Mapping[str, Any]) -> float:
        semantic_id = _semantic_for_render_id(id_map, str(element.get("id", "")))
        centers = [
            original_center_x[source_id]
            for source_id in predecessor_ids.get(semantic_id, [])
            if source_id in original_center_x
        ]
        if centers:
            return sum(centers) / len(centers)
        return original_center_x.get(
            semantic_id,
            _number(element.get("x")) + _number(element.get("width")) / 2.0,
        )

    return sorted(
        ordered,
        key=lambda element: (
            upstream_center(element),
            authored_rank[str(element.get("id", ""))],
        ),
    )


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
    nodes = [node for node in structure.get("nodes", []) or [] if isinstance(node, dict)]
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
    semantic_node_ids = {
        str(node.get("id"))
        for node in nodes
        if isinstance(node.get("id"), str)
    }
    semantic_node_ids.update(
        member_id
        for group in groups
        for member_id in group.get("members", []) or []
        if isinstance(member_id, str)
    )
    for semantic_id in semantic_node_ids:
        _normalize_member_size(elements_by_id, id_map, semantic_id)

    original_center_x = {
        semantic_id: _number(shape.get("x")) + _number(shape.get("width")) / 2.0
        for semantic_id in semantic_node_ids
        for shape in [_shape_for_semantic(elements_by_id, id_map, semantic_id)]
        if shape is not None
    }
    original_center_y = {
        semantic_id: _number(shape.get("y")) + _number(shape.get("height")) / 2.0
        for semantic_id in semantic_node_ids
        for shape in [_shape_for_semantic(elements_by_id, id_map, semantic_id)]
        if shape is not None
    }

    predecessor_ids: Dict[str, List[str]] = {}
    for edge in structure.get("edges", []) or []:
        if not isinstance(edge, Mapping):
            continue
        source_id = edge.get("source") or edge.get("from")
        target_id = edge.get("target") or edge.get("to")
        if isinstance(source_id, str) and isinstance(target_id, str):
            predecessor_ids.setdefault(target_id, []).append(source_id)

    def _is_side_group(group: Mapping[str, Any]) -> bool:
        group_class = str(group.get("class", "")).lower().replace("-", "_").replace(" ", "_")
        group_id = str(group.get("id", "")).lower()
        return (
            "cross" in group_class
            or "cross" in group_id
            or "governance" in group_class
            or "governance" in group_id
        )

    # Classify cross-cutting/governance groups before the generic ``group_*``
    # fallback.  Real Structure output commonly uses IDs such as
    # ``group_enterprise_governance`` while carrying the decisive
    # ``cross_cutting_zone`` class; checking the ID alone incorrectly inserts
    # the sidebar into the main vertical layer stack.
    side_groups = [group for group in groups if _is_side_group(group)]
    layer_groups = [
        group for group in groups
        if group not in side_groups
        and (
            "architecture_layer" in str(group.get("class", "")).lower().replace("-", "_").replace(" ", "_")
            or str(group.get("id", "")).startswith("group_")
            or bool(group.get("members"))
            or any(
                str(node.get("group_id", "")) == str(group.get("id", ""))
                for node in nodes
            )
        )
    ]

    records: List[Dict[str, Any]] = []
    for group in layer_groups:
        group_id = str(group.get("id", ""))
        frame = _frame_element(elements_by_id, id_map, group_id)
        members = _members_for_group(group, elements_by_id, id_map, nodes)
        if frame is None or not members:
            continue
        rows = _merge_crowded_rows(_cluster_rows(members))
        rows = [
            _order_row_by_predecessors(
                row,
                id_map,
                predecessor_ids,
                original_center_x,
                original_center_y,
            )
            for row in rows
        ]
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

    # Distinct side-by-side layers are an authored horizontal architecture,
    # not an oversized vertical stack. Do not rotate that layout into rows.
    columns = sorted(records, key=lambda record: record["old_x"])
    if len(columns) > 1 and all(
        left["old_x"] + _number(left["frame"].get("width")) <= right["old_x"]
        and max(left["old_y"], right["old_y"]) < min(
            left["old_y"] + _number(left["frame"].get("height")),
            right["old_y"] + _number(right["frame"].get("height")),
        )
        for left, right in zip(columns, columns[1:])
    ):
        return manifest
    records.sort(key=lambda record: (record["old_y"], record["old_x"]))

    def row_gap(row: Sequence[Dict[str, Any]]) -> float:
        """Leave visible shafts and arrowheads around same-row edge labels."""
        row_ids = {_semantic_for_render_id(id_map, str(item.get("id", ""))) for item in row}
        gap = _ROW_GAP
        for edge in structure.get("edges", []) or []:
            if edge.get("source") in row_ids and edge.get("target") in row_ids:
                label = edge.get("label") or ""
                if isinstance(label, str) and label:
                    gap = max(gap, _estimate_text_dimensions(label, 13)["width"] + 48.0)
        return gap

    max_row_width = 0.0
    for record in records:
        for row in record["rows"]:
            max_row_width = max(
                max_row_width,
                sum(_element_size(element)[0] for element in row)
                + row_gap(row) * max(0, len(row) - 1),
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
            gap = row_gap(row)
            row_width = sum(_element_size(element)[0] for element in row) + gap * max(0, len(row) - 1)
            cursor = main_x + (content_width - row_width) / 2.0
            for element in row:
                render_id = str(element.get("id", ""))
                semantic_id = _semantic_for_render_id(id_map, render_id)
                width, _ = _element_size(element)
                _move_semantic_element(elements_by_id, id_map, semantic_id, cursor, row_y)
                cursor += width + gap
            row_centers.append((record["old_y"], row_y + row_height / 2.0))
            row_y += row_height + _ROW_GAP
        record["target_y"] = next_y
        record["target_height"] = frame_height
        next_y += frame_height + _LAYER_GAP

    total_bottom = next_y - _LAYER_GAP
    for group in side_groups:
        group_id = str(group.get("id", ""))
        frame = _frame_element(elements_by_id, id_map, group_id)
        members = _members_for_group(group, elements_by_id, id_map, nodes)
        if frame is None or not members:
            continue
        side_width = max(
            _SIDE_WIDTH,
            max(_element_size(member)[0] for member in members) + 2 * 36.0,
        )
        frame["x"] = main_right + _SIDE_GAP
        frame["y"] = min(record["target_y"] for record in records)
        frame["width"] = side_width
        frame["height"] = total_bottom - frame["y"]
        _set_title_position(elements_by_id, id_map, group_id, frame["x"] + 30.0, frame["y"] + 20.0)
        side_center_x = frame["x"] + frame["width"] / 2.0
        single_member_y = frame["y"] + frame["height"] / 2.0
        for member in members:
            render_id = str(member.get("id", ""))
            semantic_id = _semantic_for_render_id(id_map, render_id)
            if len(members) == 1:
                # A single cross-cutting/governance node is a hub, rather than
                # a layer peer.  Centering it in the sidebar shortens the
                # longest fan-in route and keeps the side channel visually
                # balanced across the main stack.
                nearest_center = single_member_y
            else:
                source_centers = [
                    _number(source_shape.get("y"))
                    + _number(source_shape.get("height")) / 2.0
                    for source_id in predecessor_ids.get(semantic_id, [])
                    for source_shape in [
                        _shape_for_semantic(elements_by_id, id_map, source_id)
                    ]
                    if source_shape is not None
                ]
                if source_centers:
                    desired_center = sum(source_centers) / len(source_centers)
                    nearest_center = min(
                        (pair[1] for pair in row_centers),
                        key=lambda center: abs(center - desired_center),
                    )
                else:
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
