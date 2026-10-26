"""
Group Fitter Tool

Adjusts group frames to properly wrap their child nodes based on
structure_instantiation group-member relationships.
"""

import logging
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from ..shared.normalization import normalize_member_ref

logger = logging.getLogger(__name__)


def _get_shape_bounds(shape: Dict[str, Any]) -> Dict[str, float]:
    """
    Get the bounding box of a shape.

    Returns:
        Dict with keys: x, y, w, h, right, bottom
    """
    x = shape.get("x", 0)
    y = shape.get("y", 0)
    props = shape.get("props", {})
    if not isinstance(props, dict):
        props = {}
    meta = shape.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    w = props.get("w", 0)
    # ``text`` shapes have no ``props.h`` in the tldraw schema — the converter
    # parks the layout-committed height in ``meta`` so titles still contribute
    # their real extent to the group bbox.
    h = props.get("h", meta.get("h", 0))

    return {
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "right": x + w,
        "bottom": y + h
    }


def _calculate_bounding_box(shapes: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    Calculate the bounding box that contains all shapes.

    Returns:
        Dict with min_x, min_y, max_x, max_y, or None if no shapes
    """
    if not shapes:
        return None

    min_x = float('inf')
    min_y = float('inf')
    max_x = float('-inf')
    max_y = float('-inf')

    for shape in shapes:
        bounds = _get_shape_bounds(shape)
        min_x = min(min_x, bounds["x"])
        min_y = min(min_y, bounds["y"])
        max_x = max(max_x, bounds["right"])
        max_y = max(max_y, bounds["bottom"])

    return {
        "min_x": min_x,
        "min_y": min_y,
        "max_x": max_x,
        "max_y": max_y
    }


def _dedupe(candidates: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def _iter_shape_id_candidates(semantic_id: str) -> Iterable[str]:
    if not isinstance(semantic_id, str) or not semantic_id:
        return

    yield semantic_id

    if not semantic_id.startswith("shape:"):
        yield f"shape:{semantic_id}"

    if semantic_id.startswith("node:"):
        yield f"shape:{semantic_id}"
    elif not semantic_id.startswith("shape:"):
        yield f"shape:n_{semantic_id}"

    if semantic_id.startswith("n_"):
        yield f"shape:{semantic_id[2:]}"

    if semantic_id.startswith("group:"):
        base = semantic_id[len("group:"):]
        yield f"shape:{semantic_id}:background"
        yield f"shape:{base}:background"
    elif not semantic_id.startswith("shape:") and not semantic_id.endswith(":background"):
        yield f"shape:{semantic_id}:background"
        yield f"shape:group:{semantic_id}:background"


def _iter_group_component_candidates(group_id: str, component: str) -> Iterable[str]:
    if not isinstance(group_id, str) or not group_id:
        return
    suffix = f":{component}"
    if group_id.startswith("group:"):
        base = group_id[len("group:"):]
        yield f"shape:{group_id}{suffix}"
        yield f"shape:{base}{suffix}"
    else:
        yield f"shape:{group_id}{suffix}"
        yield f"shape:group:{group_id}{suffix}"


def _find_first_existing(store: Dict[str, Any], candidates: Iterable[str]) -> Optional[str]:
    for candidate in _dedupe(candidates):
        if candidate in store:
            return candidate
    return None


def _find_shape_id(store: Dict[str, Any], semantic_id: str) -> Optional[str]:
    return _find_first_existing(store, _iter_shape_id_candidates(semantic_id))


def _resolve_group_shape_ids(store: Dict[str, Any], group_id: str) -> Dict[str, Optional[str]]:
    return {
        "background": _find_first_existing(store, _iter_group_component_candidates(group_id, "background")),
        "title": _find_first_existing(store, _iter_group_component_candidates(group_id, "title")),
    }


def _member_ref(member: Any) -> str:
    return normalize_member_ref(member)


def fit_groups_to_children(
    manifest: Dict[str, Any],
    structure_instantiation: Dict[str, Any],
    group_id: Optional[str] = None,
    padding: int = 20
) -> Dict[str, Any]:
    """
    Resize group frame(s) to properly wrap all child nodes AND the group title.

    This function reads the structure_instantiation to understand which nodes belong to
    which groups, then adjusts the group background shapes in the manifest
    to contain all child nodes AND the group title shape with appropriate padding.

    Args:
        manifest: TLDraw manifest JSON
        structure_instantiation: Semantic Topology JSON with group-node relationships
        group_id: Specific group to fit (e.g., 'group:actors'), or None for all
        padding: Padding around children in pixels

    Returns:
        Modified manifest with resized group frames
    """
    manifest = deepcopy(manifest)
    store = manifest.get("document", {}).get("store", {})

    if not store:
        logger.warning("[GroupFitter] No store found in manifest")
        return manifest

    data = unwrap_structure_instantiation(structure_instantiation)

    # Get groups from Semantic Topology
    groups = data.get("groups", [])

    if not groups:
        logger.info("[GroupFitter] No groups found in structure_instantiation")
        return manifest

    # Filter to specific group if requested
    if group_id:
        groups = [g for g in groups if g.get("id") == group_id]

    for group in groups:
        group_semantic_id = group.get("id", "")
        members = group.get("members", [])

        if not members:
            logger.debug(f"[GroupFitter] Group {group_semantic_id} has no members, skipping")
            continue

        # Get group shape IDs
        group_shapes = _resolve_group_shape_ids(store, group_semantic_id)
        background_id = group_shapes["background"]
        title_id = group_shapes["title"]

        # Collect all shapes to be wrapped: member nodes + group title
        shapes_to_wrap = []

        # 1. Add all member shapes
        for member_id in members:
            member_ref = _member_ref(member_id)
            shape_id = _find_shape_id(store, member_ref)
            shape = store.get(shape_id) if shape_id else None
            if shape and isinstance(shape, dict) and shape.get("type") in ("geo", "image"):
                shapes_to_wrap.append(shape)
            else:
                logger.debug(f"[GroupFitter] Member {member_id} -> {shape_id} not found or invalid type")

        # 2. Add group title shape (if exists)
        title_shape = store.get(title_id) if title_id else None
        if title_shape and isinstance(title_shape, dict):
            shapes_to_wrap.append(title_shape)
            logger.debug(f"[GroupFitter] Including title shape {title_id} in bounding box")
        else:
            logger.debug(f"[GroupFitter] Title shape {title_id} not found (may be optional)")

        if not shapes_to_wrap:
            logger.warning(f"[GroupFitter] No valid shapes to wrap for group {group_semantic_id}")
            continue

        # Calculate bounding box of all shapes (members + title)
        bbox = _calculate_bounding_box(shapes_to_wrap)
        if not bbox:
            continue

        # Update background shape to wrap all shapes with padding
        bg_shape = store.get(background_id) if background_id else None
        if bg_shape and isinstance(bg_shape, dict):
            # Calculate new dimensions with padding
            new_x = bbox["min_x"] - padding
            new_y = bbox["min_y"] - padding
            new_w = (bbox["max_x"] - bbox["min_x"]) + 2 * padding
            new_h = (bbox["max_y"] - bbox["min_y"]) + 2 * padding

            # Update background position and size
            bg_shape["x"] = new_x
            bg_shape["y"] = new_y
            if "props" not in bg_shape:
                bg_shape["props"] = {}
            bg_shape["props"]["w"] = new_w
            bg_shape["props"]["h"] = new_h

            logger.info(
                f"[GroupFitter] Fitted group {group_semantic_id}: "
                f"x={new_x}, y={new_y}, w={new_w}, h={new_h} "
                f"(wrapped {len(shapes_to_wrap)} shapes including title)"
            )
        else:
            logger.warning(f"[GroupFitter] Background shape {background_id} not found")

    return manifest
