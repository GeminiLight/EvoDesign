# -*- coding: utf-8 -*-
"""
Excalidraw Group Fitter - Ensure group background elements contain their children.

Counterpart of group_fitter.py for the Excalidraw canvas library.
"""

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from evodesign.agentic_system.common.diagram_types import normalize_diagram_type
from evodesign.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evodesign.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    GROUP_TITLE_SUFFIXES,
    companion_id,
    group_frame_render_id,
    id_map_from_manifest,
)
from ..shared.normalization import normalize_member_ref

logger = logging.getLogger(__name__)

# Types whose frames are the figure itself (equal quadrants, columns and
# bands): shrinking them to their children breaks the geometry.
_FIXED_FRAME_TYPES = {"quadrant", "layer_stack", "user_journey", "kanban", "story_map"}
# Containment types: each scope is sized from its contents, innermost first,
# with a title band on top. Frames drawn larger than their contents would
# otherwise stay large and leave the figure sparse.
_CONTAINMENT_TYPES = {"nested", "deployment"}
_SCOPE_SIDE_PADDING = 24.0
_SCOPE_TITLE_GAP = 12.0


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


def _shared_edges(bounds: Dict[str, float], others: List[Dict[str, Any]], tolerance: float = 24.0) -> set:
    """Return the sides of *bounds* that a sibling frame abuts or overlaps."""
    blocked = set()
    for other in others:
        o = _get_element_bounds(other)
        overlap_y = min(bounds["bottom"], o["bottom"]) - max(bounds["y"], o["y"]) > 0
        overlap_x = min(bounds["right"], o["right"]) - max(bounds["x"], o["x"]) > 0
        if overlap_y and abs(o["x"] - bounds["right"]) <= tolerance:
            blocked.add("right")
        if overlap_y and abs(o["right"] - bounds["x"]) <= tolerance:
            blocked.add("left")
        if overlap_x and abs(o["y"] - bounds["bottom"]) <= tolerance:
            blocked.add("bottom")
        if overlap_x and abs(o["bottom"] - bounds["y"]) <= tolerance:
            blocked.add("top")
    return blocked


def _group_title(
    elem_by_eid: Dict[str, Dict[str, Any]], id_map: Dict[str, Any], group_id: str
) -> Optional[Dict[str, Any]]:
    for suffix in GROUP_TITLE_SUFFIXES:
        title = elem_by_eid.get(str(id_map.get(companion_id(group_id, suffix)) or ""))
        if title is not None and title.get("type") == "text":
            return title
    return None


def _fit_scope(
    frame: Dict[str, Any], bbox: Dict[str, float], title: Optional[Dict[str, Any]]
) -> None:
    """Wrap a containment scope tightly around its contents, title band on top.

    The title keeps its inset from the frame corner (clamped to a sane range)
    and moves with the frame, so a shrunken scope does not leave its title
    floating where the old frame edge used to be.
    """
    side = _SCOPE_SIDE_PADDING
    inset_x = inset_y = 0.0
    title_w = title_h = 0.0
    if title is not None:
        bounds = _get_element_bounds(frame)
        inset_x = min(max(float(title.get("x", 0)) - bounds["x"], 8.0), side)
        inset_y = min(max(float(title.get("y", 0)) - bounds["y"], 8.0), 16.0)
        title_w = float(title.get("width") or 0)
        title_h = float(title.get("height") or 0)
    top = inset_y + title_h + _SCOPE_TITLE_GAP if title is not None else side
    x = bbox["min_x"] - side
    y = bbox["min_y"] - top
    right = max(bbox["max_x"] + side, x + inset_x + title_w + side)
    bottom = bbox["max_y"] + side
    frame.update({"x": x, "y": y, "width": right - x, "height": bottom - y})
    if title is not None:
        title.update({"x": x + inset_x, "y": y + inset_y})


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

    chart_type = normalize_diagram_type(str(data.get("chart_type") or ""))
    fixed_frames = chart_type in _FIXED_FRAME_TYPES
    containment = chart_type in _CONTAINMENT_TYPES
    groups = data.get("groups", [])
    if not groups:
        logger.info("[ExcalidrawGroupFitter] No groups found in structure_instantiation")
        return manifest

    # Fit inner scopes first so each parent wraps its child frames as fitted.
    # A scope may name its parent with ``parent_group_id`` or be listed among
    # the parent's members; the structure validator accepts both.
    group_ids = {g.get("id") for g in groups if g.get("id")}
    parent_of: Dict[str, str] = {}
    for g in groups:
        if g.get("parent_group_id") in group_ids:
            parent_of[g["id"]] = g["parent_group_id"]
        for member in g.get("members", []) or []:
            member_id = normalize_member_ref(member)
            if member_id in group_ids and member_id != g.get("id"):
                parent_of.setdefault(member_id, g["id"])
    children_of: Dict[str, List[str]] = {}
    for child, parent in parent_of.items():
        children_of.setdefault(parent, []).append(child)

    def depth(group_id: str) -> int:
        seen = set()
        while group_id in parent_of and group_id not in seen:
            seen.add(group_id)
            group_id = parent_of[group_id]
        return len(seen)

    def frame_of(group_id: Any) -> Optional[Dict[str, Any]]:
        return elem_by_eid.get(group_frame_render_id(id_map, group_id) or "")

    for group in sorted(groups, key=lambda g: -depth(g.get("id", ""))):
        group_semantic_id = group.get("id", "")
        members = group.get("members", [])
        child_scopes = children_of.get(group_semantic_id, [])

        if not members and not child_scopes:
            logger.debug(f"[ExcalidrawGroupFitter] Group {group_semantic_id} has no members, skipping")
            continue

        # Find group background element
        bg_excalidraw_id = group_frame_render_id(id_map, group_semantic_id)
        if not bg_excalidraw_id:
            logger.debug(f"[ExcalidrawGroupFitter] Background ID not found for {group_semantic_id}")
            continue
        # A parent scope keeps the footprint the layout gave it (title room
        # included) and only grows to hold its child frames.
        uses_companion_frame = fixed_frames or bool(child_scopes) or (
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
            if not member_id or member_id in group_ids:
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

        for child_id in child_scopes:
            child_frame = frame_of(child_id)
            if child_frame is not None and child_frame is not bg_elem:
                shapes_to_wrap.append(child_frame)

        if not shapes_to_wrap:
            logger.warning(f"[ExcalidrawGroupFitter] No valid shapes to wrap for group {group_semantic_id}")
            continue

        bbox = _calculate_bounding_box(shapes_to_wrap)
        if not bbox:
            continue

        if containment:
            _fit_scope(bg_elem, bbox, _group_title(elem_by_eid, id_map, group_semantic_id))
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
            if fixed_frames:
                # Equal cells, columns and bands share edges with their
                # siblings; growing across a shared edge would overlap the
                # neighbour, so only the figure's outer edges may grow.
                siblings = [
                    frame_of(g.get("id")) for g in groups
                    if g.get("id") != group_semantic_id
                    and parent_of.get(g.get("id")) == parent_of.get(group_semantic_id)
                ]
                blocked = _shared_edges(bg_bounds, [f for f in siblings if f is not None and f is not bg_elem])
                needs_left = needs_left and "left" not in blocked
                needs_top = needs_top and "top" not in blocked
                needs_right = needs_right and "right" not in blocked
                needs_bottom = needs_bottom and "bottom" not in blocked

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
