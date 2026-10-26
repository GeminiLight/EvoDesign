# -*- coding: utf-8 -*-
"""Shared normalization logic for diagram manifests.

Provides z-order layering, group-frame detection, title deduplication,
and zero-padded index assignment. Used by both TLDraw and Excalidraw
converters (pipeline mode) and the Excalidraw normalizer (unified mode).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from evo_diagram.agentic_system.render_engine.shared.order_keys import sequential_index
from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    GROUP_TITLE_SUFFIXES,
    ICON_SUFFIX,
    TITLE_SUFFIX,
    group_frame_render_id,
    semantic_id_base,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Z-order layer constants
# ---------------------------------------------------------------------------
# Smaller value = painted first = visually behind.

LAYER_GROUP_FRAME = 100   # group / container backdrops (g_*, <name>:background)
LAYER_NODE = 200          # ordinary shape nodes
LAYER_ICON = 220          # icons should sit above nodes and below connectors/text
LAYER_ARROW = 240         # connectors should sit above nodes, below labels
LAYER_TEXT = 300          # standalone text: group titles, annotations


_SHAPE_TYPES = {"rectangle", "ellipse", "diamond", "triangle"}


def normalize_member_ref(member: Any) -> str:
    """Return the node id of a group member, whatever shape it arrives in.

    The renderer adapter boundary tolerates both canonical member id strings
    and the nested ``{"kind": "node", "node": {...}}`` objects that persisted
    Structure payloads carry (see ``shared.edge_routing.iter_concept_nodes``).
    Using a member directly as a dict key raises ``TypeError: unhashable type:
    'dict'`` when a historical payload is replayed.
    """
    if isinstance(member, str):
        return member
    if isinstance(member, dict):
        node = member.get("node")
        if isinstance(node, dict):
            return str(node.get("id") or node.get("node_id") or "")
        return str(member.get("id") or member.get("node_id") or "")
    return ""


def _has_explicit_zindex(element_data: Any) -> bool:
    """True when an element carries an intentional integer zIndex override."""
    if not isinstance(element_data, dict):
        return False
    z = element_data.get("zIndex")
    return isinstance(z, int) and not isinstance(z, bool)


# ---------------------------------------------------------------------------
# Naming-convention helpers (shared by both converters)
# ---------------------------------------------------------------------------


def layer_for(element_id: Any, element_data: Any) -> int:
    """Return the z-layer for a ``layout_instantiation`` entry.

    Priority order:
      1. Explicit integer ``element_data['zIndex']`` — always wins.
      2. Id ending with ``:title`` → text layer.
      3. Id starting with ``g_`` OR ending ``:background`` OR
         ``element_data['is_group'] is True`` → group frame.
      4. ``type`` / ``shape`` == ``text`` → text layer.
      5. Default → node layer.
    """
    if _has_explicit_zindex(element_data):
        return int(element_data["zIndex"])

    if isinstance(element_id, str):
        if element_id.endswith(TITLE_SUFFIX):
            return LAYER_TEXT
        if element_id.endswith(BACKGROUND_SUFFIX):
            return LAYER_GROUP_FRAME
        if element_id.startswith("g_"):
            return LAYER_GROUP_FRAME

    if isinstance(element_data, dict):
        if element_data.get("is_group") is True:
            return LAYER_GROUP_FRAME
        if element_data.get("type") == "text" or element_data.get("shape") == "text":
            return LAYER_TEXT

    return LAYER_NODE


def base_id(element_id: str) -> str:
    """Strip title/background suffixes so companion entries
    (``g_X`` vs ``g_X:title``) share the same base id."""
    if not isinstance(element_id, str):
        return element_id
    for suffix in (TITLE_SUFFIX, BACKGROUND_SUFFIX):
        if element_id.endswith(suffix):
            return element_id[: -len(suffix)]
    return element_id


def is_group_frame(element_id: Any, element_data: Any) -> bool:
    """True if this layout_instantiation entry is a group frame."""
    return layer_for(element_id, element_data) == LAYER_GROUP_FRAME


# ---------------------------------------------------------------------------
# Manifest-level helpers (used by normalizer for unified-mode manifests)
# ---------------------------------------------------------------------------


def _bbox(elem: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """Return ``(x, y, right, bottom)`` for an Excalidraw element."""
    x = float(elem.get("x", 0) or 0)
    y = float(elem.get("y", 0) or 0)
    w = elem.get("width") if elem.get("width") is not None else elem.get("w", 0)
    h = elem.get("height") if elem.get("height") is not None else elem.get("h", 0)
    w = float(w or 0)
    h = float(h or 0)
    return (x, y, x + w, y + h)


def _bbox_contains(
    outer: Tuple[float, float, float, float],
    inner: Tuple[float, float, float, float],
    tol: float = 1.0,
) -> bool:
    ox, oy, or_, ob = outer
    ix, iy, ir, ib = inner
    return (
        ox - tol <= ix
        and oy - tol <= iy
        and or_ + tol >= ir
        and ob + tol >= ib
    )


def _elem_id(elem: Dict[str, Any]) -> Optional[str]:
    eid = elem.get("id")
    return eid if isinstance(eid, str) else None


def _explicit_frame_signal(elem: Dict[str, Any]) -> bool:
    """True when the element is unambiguously a group frame by naming / flag."""
    if elem.get("is_group") is True:
        return True
    eid = _elem_id(elem)
    if eid is None:
        return False
    if eid.endswith(TITLE_SUFFIX):
        return False
    if eid.endswith(BACKGROUND_SUFFIX):
        return True
    if eid.startswith("g_"):
        return True
    return False


def _frame_ids_from_id_map(id_map: Optional[Mapping[str, Any]]) -> Set[str]:
    frame_ids: Set[str] = set()
    if not isinstance(id_map, Mapping):
        return frame_ids

    non_frame_suffixes = (*GROUP_TITLE_SUFFIXES, ICON_SUFFIX)
    for semantic_id, render_id in id_map.items():
        if not isinstance(semantic_id, str) or not isinstance(render_id, str):
            continue
        if semantic_id.endswith(BACKGROUND_SUFFIX):
            frame_ids.add(render_id)
            continue
        if semantic_id.startswith("g_") and not semantic_id.endswith(
            non_frame_suffixes
        ):
            frame_ids.add(render_id)

    return frame_ids


def _title_marked_frame_candidates(
    elements: List[Dict[str, Any]],
    id_map: Optional[Mapping[str, Any]],
) -> Set[str]:
    candidate_ids: Set[str] = set()
    if isinstance(id_map, Mapping):
        titled_bases = {
            base
            for semantic_id in id_map
            if isinstance(semantic_id, str)
            and semantic_id.endswith(GROUP_TITLE_SUFFIXES)
            for base in [semantic_id_base(semantic_id)]
            if base
        }
    else:
        titled_bases = set()

    for base_id in titled_bases:
        frame_id = group_frame_render_id(id_map, base_id)
        if frame_id:
            candidate_ids.add(frame_id)

    element_ids = {
        elem.get("id")
        for elem in elements
        if isinstance(elem, dict) and isinstance(elem.get("id"), str)
    }
    for elem_id in element_ids:
        if not isinstance(elem_id, str):
            continue
        if any(
            f"{elem_id}{suffix}" in element_ids
            for suffix in GROUP_TITLE_SUFFIXES
        ):
            candidate_ids.add(elem_id)

    return candidate_ids


def _is_structural_frame_candidate(
    candidate_id: str,
    elements: List[Dict[str, Any]],
) -> bool:
    candidate = next(
        (elem for elem in elements if _elem_id(elem) == candidate_id),
        None,
    )
    if not candidate or candidate.get("type") not in _SHAPE_TYPES:
        return False

    candidate_bbox = _bbox(candidate)
    contained = 0
    for elem in elements:
        if elem is candidate or elem.get("isDeleted"):
            continue
        child_id = _elem_id(elem)
        if not child_id:
            continue
        if any(
            child_id == f"{candidate_id}{suffix}"
            for suffix in GROUP_TITLE_SUFFIXES
        ):
            continue
        if elem.get("type") == "arrow":
            continue
        if (
            elem.get("type") == "text"
            and elem.get("containerId") == candidate_id
        ):
            continue
        if _bbox_contains(candidate_bbox, _bbox(elem)):
            contained += 1
            if contained >= 2:
                return True

    return False


def detect_group_frame_ids(
    elements: List[Dict[str, Any]],
    structural: bool = False,
    id_map: Optional[Mapping[str, Any]] = None,
) -> Set[str]:
    """Return element IDs classified as group frames.

    Args:
        elements: list of manifest element dicts.
        structural: when True, also apply bbox+groupIds containment heuristic
            (for unified-mode manifests that lack naming conventions).
        id_map: optional semantic-id to rendered-id map. Explicit background
            and ``g_`` semantic ids are treated as frames. Direct ids marked by
            ``:title`` / ``:label`` companions are only promoted when structural
            containment confirms they are frame-like.
    """
    frame_ids: Set[str] = _frame_ids_from_id_map(id_map)
    if not elements:
        return frame_ids

    # Pass 1: naming convention + explicit flags.
    for elem in elements:
        if elem.get("type") not in _SHAPE_TYPES:
            continue
        if _explicit_frame_signal(elem):
            eid = _elem_id(elem)
            if eid:
                frame_ids.add(eid)

    if not structural:
        return frame_ids

    for candidate_id in _title_marked_frame_candidates(elements, id_map):
        if candidate_id not in frame_ids and _is_structural_frame_candidate(
            candidate_id,
            elements,
        ):
            frame_ids.add(candidate_id)

    # Pass 2: containment heuristic for unified-mode manifests.
    for elem in elements:
        if elem.get("type") not in _SHAPE_TYPES:
            continue
        eid = _elem_id(elem)
        if not eid or eid in frame_ids:
            continue

        e_groups = set(elem.get("groupIds") or [])
        if not e_groups:
            continue

        e_bb = _bbox(elem)
        contained = 0
        for other in elements:
            if other is elem:
                continue
            oid = _elem_id(other)
            if oid == eid:
                continue
            if other.get("type") == "arrow":
                continue
            if other.get("type") == "text" and other.get("containerId") == eid:
                continue

            other_groups = set(other.get("groupIds") or [])
            if not (e_groups & other_groups):
                continue
            if _bbox_contains(e_bb, _bbox(other)):
                contained += 1
                if contained >= 2:
                    frame_ids.add(eid)
                    break

    return frame_ids


def deduplicate_group_titles(
    elements: List[Dict[str, Any]],
    frame_ids: Set[str],
) -> List[Dict[str, Any]]:
    """Remove bound-text titles that duplicate a standalone title.

    Returns a filtered element list. Also strips dangling ``boundElements``
    references to removed ids.
    """
    if not frame_ids or not elements:
        return elements

    by_id: Dict[str, Dict[str, Any]] = {}
    for elem in elements:
        eid = _elem_id(elem)
        if eid:
            by_id[eid] = elem

    to_remove: Set[str] = set()

    for frame_id in frame_ids:
        frame = by_id.get(frame_id)
        if not frame:
            continue

        frame_bbox = _bbox(frame)
        frame_groups = set(frame.get("groupIds") or [])

        bound_on_frame = [
            e for e in elements
            if e.get("type") == "text"
            and e.get("containerId") == frame_id
            and _elem_id(e) is not None
        ]
        if not bound_on_frame:
            continue

        for bt in bound_on_frame:
            bt_text = str(bt.get("text") or "").strip()
            if not bt_text:
                continue

            bt_id = _elem_id(bt)
            for other in elements:
                if other is bt:
                    continue
                if other.get("type") != "text":
                    continue
                if other.get("containerId"):
                    continue
                if str(other.get("text") or "").strip() != bt_text:
                    continue

                other_groups = set(other.get("groupIds") or [])
                shares_group = bool(frame_groups & other_groups)
                inside_frame = _bbox_contains(frame_bbox, _bbox(other))
                if shares_group or inside_frame:
                    to_remove.add(bt_id)
                    break

    if not to_remove:
        return elements

    filtered = [e for e in elements if _elem_id(e) not in to_remove]

    # Strip dangling boundElements references.
    for elem in filtered:
        bound = elem.get("boundElements")
        if isinstance(bound, list) and bound:
            elem["boundElements"] = [
                b for b in bound
                if not (isinstance(b, dict) and b.get("id") in to_remove)
            ]

    logger.info(
        "[normalization] removed %d duplicate bound-text title(s): %s",
        len(to_remove),
        sorted(to_remove),
    )
    return filtered


def sort_and_reindex(
    elements: List[Dict[str, Any]],
    index_counter: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Stable-sort elements by z-layer and assign zero-padded indices.

    Args:
        elements: manifest element list.
        index_counter: starting counter value for index generation.

    Returns:
        ``(sorted_elements, next_counter)`` — elements are reordered and
        each element's ``index`` field is mutated in place.
    """
    decorated = [
        (layer_for(elem.get("id"), elem), orig_idx, elem)
        for orig_idx, elem in enumerate(elements)
    ]
    decorated.sort(key=lambda t: (t[0], t[1]))

    ordered = [t[2] for t in decorated]
    counter = index_counter
    for elem in ordered:
        elem["index"] = sequential_index(counter)
        counter += 1

    return ordered, counter
