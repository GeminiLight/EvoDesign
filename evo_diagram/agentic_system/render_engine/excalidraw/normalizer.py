# -*- coding: utf-8 -*-
"""Manifest normalization pass for Excalidraw scenes.

Applies z-order, title dedup, and zero-padded index guarantees to any
Excalidraw manifest — including unified-mode output that bypasses the
converter. Safe to run on pipeline-mode output too (idempotent).

Uses ``shared.normalization`` for frame detection and title dedup.
Keeps its own layer classification for manifest elements (arrows, icons,
pre-computed frame_ids) which the naming-convention-based shared ``layer_for``
cannot handle.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from evo_diagram.agentic_system.render_engine.shared.order_keys import sequential_index
from ..shared.normalization import (
    LAYER_ARROW,
    LAYER_GROUP_FRAME,
    LAYER_ICON,
    LAYER_NODE,
    LAYER_TEXT,
    _elem_id,
    _has_explicit_zindex,
    deduplicate_group_titles,
    detect_group_frame_ids,
)

logger = logging.getLogger(__name__)

_LAYER_GROUP_FRAME = LAYER_GROUP_FRAME
_LAYER_NODE = LAYER_NODE
_LAYER_TEXT = LAYER_TEXT


def _layer_for_element(
    elem: Dict[str, Any],
    frame_ids: Set[str],
) -> int:
    """Classify an already-built Excalidraw element into a z-layer.

    Unlike ``shared.normalization.layer_for`` (which works on
    layout_instantiation entries with naming conventions), this operates
    on manifest elements using the pre-computed ``frame_ids`` set.
    """
    if _has_explicit_zindex(elem):
        return int(elem["zIndex"])

    t = elem.get("type")
    if t == "arrow":
        return LAYER_ARROW
    if t == "text":
        return LAYER_TEXT
    if t == "image":
        return LAYER_ICON

    eid = _elem_id(elem)
    if eid and eid in frame_ids:
        return LAYER_GROUP_FRAME

    return LAYER_NODE


def _reassign_indices(
    elements: list,
    frame_ids: Set[str],
) -> list:
    """Stable-sort by (layer, original_order) and assign zero-padded indices."""
    decorated = [
        (_layer_for_element(elem, frame_ids), orig_idx, elem)
        for orig_idx, elem in enumerate(elements)
    ]
    decorated.sort(key=lambda t: (t[0], t[1]))

    ordered = [t[2] for t in decorated]
    for new_idx, elem in enumerate(ordered):
        elem["index"] = sequential_index(new_idx)
    return ordered


def normalize_excalidraw_manifest(
    manifest: Optional[Dict[str, Any]],
    *,
    dedup_titles: bool = True,
    resort_indices: bool = True,
) -> Optional[Dict[str, Any]]:
    """Apply z-order and dedup guarantees to any Excalidraw manifest.

    Parameters
    ----------
    manifest:
        Excalidraw manifest dict. Mutated in place AND returned.
    dedup_titles:
        Drop bound-text titles that duplicate a standalone title.
    resort_indices:
        Stable-sort elements by z-layer and reassign zero-padded indices.

    Returns
    -------
    The same ``manifest`` dict (or the original input if unmodifiable).
    """
    if not isinstance(manifest, dict):
        return manifest

    elements = manifest.get("elements")
    if not isinstance(elements, list) or not elements:
        return manifest

    # Detect group frames using structural heuristic (unified-mode safe).
    frame_ids = detect_group_frame_ids(elements, structural=True)

    if dedup_titles:
        elements = deduplicate_group_titles(elements, frame_ids)

    if resort_indices:
        elements = _reassign_indices(elements, frame_ids)

    manifest["elements"] = elements
    return manifest


__all__ = [
    "normalize_excalidraw_manifest",
]
