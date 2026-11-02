# -*- coding: utf-8 -*-
"""
Excalidraw Group Fitter - Ensure group background elements contain their children.

Counterpart of group_fitter.py for the Excalidraw canvas library.
"""

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from evo_diagram.agentic_system.common.diagram_types import normalize_diagram_type
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    companion_id,
    group_frame_render_id,
    id_map_from_manifest,
)
from ..shared.normalization import normalize_member_ref

logger = logging.getLogger(__name__)

# Types whose frames are the figure itself (equal quadrants, columns and
# bands, scopes with a title band): shrinking them to their children breaks
# the geometry.
_FIXED_FRAME_TYPES = {
    "quadrant", "layer_stack", "nested", "deployment", "user_journey", "kanban", "story_map",
}


def _get_element_bounds(elem: Dict[str, Any]) -> Dict[str, float]:
    """Get the bounding box of an Excalidraw element."""
    x = elem.get("x", 0)
    y = elem.get("y", 0)
    w = elem.get("width", 0)
    h = elem.get("height", 0)
    return {
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "right": x + w,
        "bottom": y + h,
    }


def _calculate_bounding_box(elements: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Calculate the bounding box that contains all elements."""
    if not elements:
        return None

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for elem in elements:
        bounds = _get_element_bounds(elem)
        min_x = min(min_x, bounds["x"])
        min_y = min(min_y, bounds["y"])
        max_x = max(max_x, bounds["right"])
        max_y = max(max_y, bounds["bottom"])

    return {
        "min_x": min_x,
        "min_y": min_y,
        "max_x": max_x,
        "max_y": max_y,
    }


def fit_excalidraw_groups_to_children(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    padding: int = 20,
) -> Dict[str, Any]:
    """
    Expand group background elements in the Excalidraw manifest as needed to contain all children.
    Preserve the layout stage's intended group footprint when it is already large enough.

    Args:
        manifest: Excalidraw manifest with elements, files, _meta
        structure_instantiation: Semantic graph with group-member relationships
        padding: Padding around children in pixels

    Returns:
        Updated manifest with resized group backgrounds
    """
    manifest = deepcopy(manifest)
    elements = manifest.get("elements", [])
    id_map = id_map_from_manifest(manifest)

    # Build element lookup: excalidraw_id -> element reference
    elem_by_eid: Dict[str, Dict[str, Any]] = {}
    for elem in elements:
        elem_by_eid[elem.get("id", "")] = elem

    data = unwrap_structure_instantiation(structure_instantiation)

    fixed_frames = normalize_diagram_type(str(data.get("chart_type") or "")) in _FIXED_FRAME_TYPES
    groups = data.get("groups", [])
    if not groups:
        logger.info("[ExcalidrawGroupFitter] No groups found in structure_instantiation")
        return manifest

    # Fit inner scopes first so each parent wraps its child frames as fitted.
    parent_of = {g.get("id"): g.get("parent_group_id") for g in groups if g.get("parent_group_id")}
    children_of: Dict[str, List[str]] = {}
    for child, parent in parent_of.items():
        children_of.setdefault(parent, []).append(child)

    def depth(group_id: str) -> int:
        seen = set()
        while group_id in parent_of and group_id not in seen:
            seen.add(group_id)
            group_id = parent_of[group_id]
        return len(seen)

    for group in sorted(groups, key=lambda g: -depth(g.get("id", ""))):
        group_semantic_id = group.get("id", "")
        members = group.get("members", [])

        if not members and not children_of.get(group_semantic_id):
            logger.debug(f"[ExcalidrawGroupFitter] Group {group_semantic_id} has no members, skipping")
            continue

        # Find group background element
        bg_excalidraw_id = group_frame_render_id(id_map, group_semantic_id)
        if not bg_excalidraw_id:
            logger.debug(f"[ExcalidrawGroupFitter] Background ID not found for {group_semantic_id}")
            continue
        uses_companion_frame = fixed_frames or (
            id_map.get(companion_id(group_semantic_id, BACKGROUND_SUFFIX))
            == bg_excalidraw_id
        )

        bg_elem = elem_by_eid.get(bg_excalidraw_id)
        if not bg_elem:
            logger.warning(f"[ExcalidrawGroupFitter] Background element not found: {bg_excalidraw_id}")
            continue

        # Collect shapes to wrap: member nodes only (NOT title).
        # Title is a label that sits on/above the group frame — it must not
        # drive the group background expansion, otherwise the frame creeps
        # upward to engulf the title.
        shapes_to_wrap = []

        for member in members:
            member_id = normalize_member_ref(member)
            if not member_id:
                logger.debug(f"[ExcalidrawGroupFitter] Unrecognized member entry {member!r}")
                continue
            member_excalidraw_id = id_map.get(member_id)
            if member_excalidraw_id:
                member_elem = elem_by_eid.get(member_excalidraw_id)
                if member_elem and member_elem.get("type") not in ("text",):
                    shapes_to_wrap.append(member_elem)
                else:
                    logger.debug(f"[ExcalidrawGroupFitter] Member {member_id} -> {member_excalidraw_id} not found or is text")
            else:
                logger.debug(f"[ExcalidrawGroupFitter] Member {member_id} not in id_map")

        for child_id in children_of.get(group_semantic_id, []):
            child_frame = elem_by_eid.get(group_frame_render_id(id_map, child_id) or "")
            if child_frame:
                shapes_to_wrap.append(child_frame)

        if not shapes_to_wrap:
            logger.warning(f"[ExcalidrawGroupFitter] No valid shapes to wrap for group {group_semantic_id}")
            continue

        bbox = _calculate_bounding_box(shapes_to_wrap)
        if not bbox:
            continue

        if uses_companion_frame:
            # Preserve the layout stage's intended organizer footprint and only
            # expand when children/title would otherwise overflow it. Padding is
            # added only where overflow occurs, so a title placed 16 px from a
            # lane's left edge does not cause the lane to creep leftward and
            # overlap its neighbour.
            bg_bounds = _get_element_bounds(bg_elem)
            needs_left = bbox["min_x"] < bg_bounds["x"]
            needs_top = bbox["min_y"] < bg_bounds["y"]
            needs_right = bbox["max_x"] > bg_bounds["right"]
            needs_bottom = bbox["max_y"] > bg_bounds["bottom"]

            new_x = (
                min(bg_bounds["x"], bbox["min_x"] - padding)
                if needs_left else bg_bounds["x"]
            )
            new_y = (
                min(bg_bounds["y"], bbox["min_y"] - padding)
                if needs_top else bg_bounds["y"]
            )
            new_right = (
                max(bg_bounds["right"], bbox["max_x"] + padding)
                if needs_right else bg_bounds["right"]
            )
            new_bottom = (
                max(bg_bounds["bottom"], bbox["max_y"] + padding)
                if needs_bottom else bg_bounds["bottom"]
            )
        else:
            # Direct group-id mappings do not have a separate companion frame
            # contract, so fit the frame tightly to its children.
            new_x = bbox["min_x"] - padding
            new_y = bbox["min_y"] - padding
            new_right = bbox["max_x"] + padding
            new_bottom = bbox["max_y"] + padding

        new_w = new_right - new_x
        new_h = new_bottom - new_y

        bg_elem["x"] = new_x
        bg_elem["y"] = new_y
        bg_elem["width"] = new_w
        bg_elem["height"] = new_h

        logger.info(
            f"[ExcalidrawGroupFitter] Fitted group {group_semantic_id}: "
            f"x={new_x}, y={new_y}, w={new_w}, h={new_h} "
            f"(wrapped {len(shapes_to_wrap)} shapes)"
        )

    manifest["elements"] = elements
    return manifest
