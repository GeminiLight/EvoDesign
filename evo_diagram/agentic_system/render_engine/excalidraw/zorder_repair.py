# -*- coding: utf-8 -*-
"""Z-order repair for Excalidraw manifests.

The pre-2026-04 converter assigned fractional indices in dict-insertion order,
so when the layout LLM emitted a group frame AFTER its children the opaque
frame silently occluded them in the rendered PNG. The converter now sorts by
layer band before assigning indices (excalidraw_converter._layer_for), which
fixed the common case. But regressions still slip through: nested group
frames with non-standard semantic ids, post-converter passes that mutate
element order, and LLM outputs that omit the `:background` / `g_` suffix
all leave the audit (render_audit._audit_group_frame_zorder) warning with
no corresponding fix.

This module runs after the converter / arrow-adder / group-fitter pipeline,
reclassifies every element from manifest-level attributes (type + id_map
semantic-id reverse lookup), stable-sorts by (band, original_index), and
reassigns fractional indices sequentially. It is purely geometric — no
chart-type branching — and idempotent (a second run produces byte-identical
output).
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, Set, Tuple

from evo_diagram.agentic_system.render_engine.shared.order_keys import sequential_index
from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    GROUP_TITLE_SUFFIXES,
    id_map_from_manifest,
    reverse_id_map,
    semantic_id_base,
)
from ..shared.normalization import (
    LAYER_ARROW as _LAYER_ARROW,
    LAYER_GROUP_FRAME as _LAYER_GROUP_FRAME,
    LAYER_ICON as _LAYER_ICON,
    LAYER_NODE as _LAYER_NODE,
    LAYER_TEXT as _LAYER_TEXT,
    detect_group_frame_ids,
)

logger = logging.getLogger(__name__)

# 5-digit zero-padded sequential fractional index ("e00000"...) — same format
# the converter uses, so lexicographic sort matches numeric intent up to 100k
# elements. See excalidraw_converter._next_index.


def _titled_semantic_bases(id_map: Dict[str, str]) -> Set[str]:
    """Return semantic ids whose title/label sibling marks them as frames."""
    return {
        base
        for semantic_id in id_map
        if isinstance(semantic_id, str)
        and semantic_id.endswith(GROUP_TITLE_SUFFIXES)
        for base in [semantic_id_base(semantic_id)]
        if base
    }


def _infer_band(
    elem: Dict[str, Any],
    reverse_id_map: Dict[str, str],
    frame_ids: Set[str],
    titled_bases: Set[str],
) -> int:
    """Return the layer band for a manifest element.

    Inference order (first match wins):
      1. Explicit integer ``zIndex`` on the element itself (rare — the
         converter normally already folded LLM zIndex into index spacing,
         but preserve it here for safety).
      2. ``type == "text"`` → text layer.
      3. ``type == "image"`` → icon layer.
      4. ``type == "arrow"`` → arrow layer (above nodes/icons, below text).
      5. Shape elements (rectangle / ellipse / diamond): look up semantic id
         via reverse id_map. Ids ending ``:background``, starting ``g_``, or
         whose entry had ``is_group=True`` map to group-frame band.
      6. Element id in the structural containment set (detect_group_frame_ids
         with ``structural=True``) → group-frame band.  This catches frames
         whose semantic id does not follow naming conventions (e.g.  lanes
         named "User Lane" without ``:background`` suffix).
      7. Default → node band.
    """
    z = elem.get("zIndex")
    if isinstance(z, bool):
        z = None
    if isinstance(z, int):
        return z

    etype = elem.get("type")
    if etype == "text":
        return _LAYER_TEXT
    if etype == "image":
        return _LAYER_ICON
    if etype == "arrow":
        return _LAYER_ARROW

    excalidraw_id = elem.get("id")
    semantic_id = reverse_id_map.get(excalidraw_id) if isinstance(excalidraw_id, str) else None
    if isinstance(semantic_id, str):
        if semantic_id.endswith(BACKGROUND_SUFFIX):
            return _LAYER_GROUP_FRAME
        if semantic_id.startswith("g_"):
            return _LAYER_GROUP_FRAME
        if semantic_id in titled_bases:
            return _LAYER_GROUP_FRAME

    # Structural containment fallback: geometric heuristic that does not
    # depend on naming conventions.  Catches lane frames, cluster frames,
    # and other container shapes that LLM emits without :background / g_.
    if isinstance(excalidraw_id, str) and excalidraw_id in frame_ids:
        return _LAYER_GROUP_FRAME

    return _LAYER_NODE


def repair_zorder(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Reclassify + reassign fractional indices on an Excalidraw manifest.

    Args:
        manifest: Excalidraw manifest with ``elements`` list and optional
            ``_meta.id_map``. Must not be ``None``.

    Returns:
        A deep-copied manifest with ``elements[*].index`` rewritten to
        (band, original-order)-sorted ``e00000``-style strings. Other
        element fields are untouched. Idempotent.
    """
    if not isinstance(manifest, dict):
        return manifest
    elements = manifest.get("elements")
    if not isinstance(elements, list) or not elements:
        return manifest

    manifest = deepcopy(manifest)
    elements = manifest["elements"]
    id_map = id_map_from_manifest(manifest)
    rendered_to_semantic = reverse_id_map(id_map)
    titled_bases = _titled_semantic_bases(id_map)

    # Structural containment heuristic: detect frames that LLM emits without
    # naming-convention suffixes (e.g. "User Lane" instead of "User Lane:background").
    frame_ids = detect_group_frame_ids(elements, structural=True)

    # Annotate each element with (band, original_position) so the sort is
    # stable and the eventual index order is deterministic.
    decorated: list[Tuple[int, int, Dict[str, Any]]] = []
    for position, elem in enumerate(elements):
        if not isinstance(elem, dict):
            # Non-dict entries get pushed to the end at the top layer so they
            # don't interleave with real elements; they likely indicate a
            # malformed manifest, which the validator will flag later.
            decorated.append((_LAYER_TEXT + 1, position, elem))
            continue
        band = _infer_band(elem, rendered_to_semantic, frame_ids, titled_bases)
        decorated.append((band, position, elem))

    decorated.sort(key=lambda t: (t[0], t[1]))

    reassigned = 0
    changed = 0
    for new_position, (_band, _original_position, elem) in enumerate(decorated):
        if not isinstance(elem, dict):
            continue
        new_index = sequential_index(new_position)
        if elem.get("index") != new_index:
            elem["index"] = new_index
            changed += 1
        reassigned += 1

    manifest["elements"] = [elem for _band, _pos, elem in decorated]

    if changed:
        logger.info(
            "[ZOrderRepair] Reassigned fractional indices (%d/%d elements changed).",
            changed,
            reassigned,
        )
    else:
        logger.info(
            "[ZOrderRepair] No reassignment needed (%d elements already in band order).",
            reassigned,
        )

    return manifest


def is_enabled() -> bool:
    """Feature-flag gate: ``render.fix_zorder`` in settings.yaml (default on).

    Set to ``"0"`` / ``"false"`` / ``"no"`` to disable and fall back to the
    converter's first-pass index assignment.
    """
    from evo_diagram.config.settings import AppSettings
    return AppSettings.get_default().render_fix_zorder


__all__ = ["repair_zorder", "is_enabled"]
