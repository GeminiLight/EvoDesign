"""Post-layout shape-size fitter for Excalidraw manifests.

The Layout LLM picks each shape's ``width`` / ``height``.  But the
converter independently estimates the bound-text element's width from
its content at its actual ``fontSize``.  When the LLM under-sizes a
shape, the text is wider than the shape — the rendered PNG shows text
overflowing its container (most visible on decision diamonds, which
need a significantly larger bbox than rectangles for the same label).

This tool enforces a minimum shape size derived from the bound text
geometry.  Policy:

- **Only expand, never shrink.**  The LLM's over-sized aesthetic choice
  is preserved.
- **Keep shape center invariant.**  When a shape grows by ``Δw`` we
  shift its origin by ``-Δw/2`` so the center stays at the same
  (x, y) the Layout workflow committed.
- **Shape-type inflate factors** (because text's inscribed bbox differs
  by outer shape):
    * ``rectangle`` → 1.0 (identity)
    * ``diamond``   → 1.4 (rotated square's inscribed rect is ~50% area)
    * ``ellipse``   → 1.2 (ellipse inscribed rect is ~64% area)
- **Sync bound text geometry.**  When the container shape grows, the
  bound text element's origin (and width) is re-centered inside it.
- **Standalone text** (no ``containerId`` — e.g. ``g_svc:title`` group
  titles) is also fitted: width / height expanded to hold the text at
  its own ``fontSize``.

Invocation order: run AFTER ``convert`` (needs a populated manifest)
and BEFORE ``arrows`` (waypoints need final shape bboxes).
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, List, Optional
from evo_diagram.agentic_system.common.node_icons import sync_node_icons

from ...generation_stage.layout.element_shape_estimator import (
    _ICON_LEFT_PAD,
    _ICON_TEXT_GAP,
    _estimate_text_dimensions,
)
from ...common.semantic_ids import (
    BACKGROUND_SUFFIX,
    TITLE_SUFFIX,
    companion_id,
    id_map_from_manifest,
    reverse_id_map,
)


# Per-side padding between text edge and shape boundary (total = 2 × value).
_PAD_W = 20.0
_PAD_H = 15.0

# Shape-type-specific inflate factors (empirical fit between text's
# axis-aligned bbox and the outer shape needed to contain it visually).
SHAPE_INFLATE = {
    "rectangle": 1.0,
    "diamond":   1.4,
    "ellipse":   1.2,
}

# Only these element types can grow to fit bound text.
_CONTAINER_TYPES = frozenset(SHAPE_INFLATE.keys())


def _read_font_size(text_elem: Dict[str, Any]) -> int:
    """Excalidraw text elements always carry a top-level ``fontSize``; fall back to 16."""
    fs = text_elem.get("fontSize")
    if isinstance(fs, (int, float)) and fs > 0:
        return int(fs)
    return 16


def _required_text_bbox(text_elem: Dict[str, Any]) -> Dict[str, float]:
    """Geometry required to hold ``text_elem.text`` at its own ``fontSize``.

    Uses ``_estimate_text_dimensions`` from ``element_shape_estimator`` so
    the layout-side hint and the render-side fit stay in sync (same
    line-height, same CJK/latin char-width factor).
    """
    text = text_elem.get("text") or ""
    fs = _read_font_size(text_elem)
    return _estimate_text_dimensions(text, fs)


def _find_bound_text(shape: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """First ``type=="text"`` entry in ``shape.boundElements``, resolved via ``by_id``."""
    for b in shape.get("boundElements") or []:
        if isinstance(b, dict) and b.get("type") == "text":
            tid = b.get("id")
            if tid and tid in by_id:
                return by_id[tid]
    return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _element_bbox(elem: Dict[str, Any]) -> Dict[str, float]:
    return {
        "x": _num(elem.get("x")),
        "y": _num(elem.get("y")),
        "width": _num(elem.get("width")),
        "height": _num(elem.get("height")),
    }


def _contains_center(container: Dict[str, Any], child: Dict[str, Any], tol: float = 1.0) -> bool:
    cb = _element_bbox(container)
    ib = _element_bbox(child)
    if cb["width"] <= 0 or cb["height"] <= 0 or ib["width"] <= 0 or ib["height"] <= 0:
        return False

    icon_cx = ib["x"] + ib["width"] / 2.0
    icon_cy = ib["y"] + ib["height"] / 2.0
    return (
        cb["x"] - tol <= icon_cx <= cb["x"] + cb["width"] + tol
        and cb["y"] - tol <= icon_cy <= cb["y"] + cb["height"] + tol
    )


def _map_icons_to_containers(elements: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Infer the node container for each rendered icon image by geometry."""
    containers = [
        e for e in elements
        if isinstance(e, dict) and e.get("type") in _CONTAINER_TYPES and e.get("id")
    ]
    icons = [
        e for e in elements
        if isinstance(e, dict) and e.get("type") == "image" and e.get("id")
    ]

    icon_by_container: Dict[str, Dict[str, Any]] = {}
    for icon in icons:
        candidates = [shape for shape in containers if _contains_center(shape, icon)]
        if not candidates:
            continue
        candidates.sort(key=lambda s: _num(s.get("width")) * _num(s.get("height")))
        container = candidates[0]
        icon_by_container.setdefault(container["id"], icon)
    return icon_by_container


def _fit_container_to_text(
    shape: Dict[str, Any],
    text_elem: Dict[str, Any],
    icon_elem: Optional[Dict[str, Any]] = None,
    original_dims: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Expand ``shape`` (in place) so its bbox holds the bound text; re-center text.

    If ``original_dims`` is provided, stores the original geometry of both
    ``shape`` and ``text_elem`` before any mutation so the caller can
    revert overlaps introduced by the expansion.
    """
    shape_type = shape.get("type")
    inflate = SHAPE_INFLATE.get(shape_type, 1.0)

    text_bbox = _required_text_bbox(text_elem)
    icon_w = _num(icon_elem.get("width")) if icon_elem is not None else 0.0
    icon_h = _num(icon_elem.get("height")) if icon_elem is not None else 0.0
    icon_extra_w = (_ICON_LEFT_PAD + icon_w + _ICON_TEXT_GAP) if icon_elem is not None else 0.0

    required_w = text_bbox["width"] * inflate + 2.0 * _PAD_W + icon_extra_w
    required_h = text_bbox["height"] * inflate + 2.0 * _PAD_H

    cur_w = _num(shape.get("width"))
    cur_h = _num(shape.get("height"))
    cur_x = _num(shape.get("x"))
    cur_y = _num(shape.get("y"))

    new_w = max(cur_w, math.ceil(required_w))
    new_h = max(cur_h, math.ceil(required_h))

    resized = new_w != cur_w or new_h != cur_h
    # When the shape already fits we still fall through to re-sync the text
    # geometry (the LLM may have committed a text bbox that isn't centered
    # inside an otherwise big-enough shape) — but nothing is recorded in
    # ``original_dims``.  That map is the caller's "the fitter touched this"
    # signal: recording untouched shapes made every container with bound text
    # eligible for the overlap resolver and the revert pass, which is the
    # opposite of the intended "only undo damage we caused" guarantee.

    # Store originals before mutation so we can revert if expansion
    # introduces overlaps with neighbours.
    if resized and original_dims is not None:
        original_dims[shape["id"]] = {
            "x": cur_x, "y": cur_y,
            "width": cur_w, "height": cur_h,
        }
        original_dims[text_elem["id"]] = {
            "x": text_elem.get("x"),
            "y": text_elem.get("y"),
            "width": text_elem.get("width"),
            "height": text_elem.get("height"),
        }
        if icon_elem is not None:
            original_dims[icon_elem["id"]] = {
                "x": icon_elem.get("x"),
                "y": icon_elem.get("y"),
                "width": icon_elem.get("width"),
                "height": icon_elem.get("height"),
            }

    # Center-invariant growth: shift origin by -Δ/2.
    dw = new_w - cur_w
    dh = new_h - cur_h
    shape["x"] = cur_x - dw / 2.0
    shape["y"] = cur_y - dh / 2.0
    shape["width"] = new_w
    shape["height"] = new_h

    if icon_elem is not None:
        icon_elem["x"] = shape["x"] + _ICON_LEFT_PAD
        icon_elem["y"] = shape["y"] + max(0.0, (shape["height"] - icon_h) / 2.0)

    # Re-center bound text inside the (possibly enlarged) shape.  We
    # keep the text's own required bbox (``text_bbox``) rather than
    # copying the shape's dimensions — a 400×300 rectangle with a
    # 5-character label should NOT have a 400-wide text element,
    # Excalidraw renders that as centered anyway but the extra width
    # confuses the bounding-box math downstream.
    text_w = math.ceil(text_bbox["width"])
    text_h = math.ceil(text_bbox["height"])
    if icon_elem is not None:
        content_left = icon_elem["x"] + icon_w + _ICON_TEXT_GAP
        content_right = shape["x"] + shape["width"] - _PAD_W
        if content_right > content_left:
            shape_center_x = content_left + (content_right - content_left) / 2.0
        else:
            shape_center_x = shape["x"] + shape["width"] / 2.0
    else:
        shape_center_x = shape["x"] + shape["width"] / 2.0
    shape_center_y = shape["y"] + shape["height"] / 2.0
    text_elem["x"] = shape_center_x - text_w / 2.0
    text_elem["y"] = shape_center_y - text_h / 2.0
    text_elem["width"] = text_w
    text_elem["height"] = text_h


def _fit_standalone_text(text_elem: Dict[str, Any]) -> None:
    """Expand a standalone text element's bbox to hold its text.

    Standalone == no ``containerId``.  Group titles (``g_*:title``) land
    here.  We preserve the element's top-left origin (group titles are
    often anchored to a specific corner of a group frame) and only grow
    ``width`` / ``height`` — so the title stays where the LLM asked
    rather than drifting to a fresh center.
    """
    text_bbox = _required_text_bbox(text_elem)
    cur_w = float(text_elem.get("width", 0) or 0)
    cur_h = float(text_elem.get("height", 0) or 0)
    new_w = max(cur_w, math.ceil(text_bbox["width"]))
    new_h = max(cur_h, math.ceil(text_bbox["height"]))
    text_elem["width"] = new_w
    text_elem["height"] = new_h


def _bbox_overlap(
    a: Dict[str, Any],
    b: Dict[str, Any],
    tol: float = 2.0,
) -> bool:
    """Return True if the axis-aligned bboxes of two elements intersect."""
    try:
        ax = float(a.get("x", 0) or 0)
        ay = float(a.get("y", 0) or 0)
        aw = float(a.get("width", 0) or 0)
        ah = float(a.get("height", 0) or 0)
        bx = float(b.get("x", 0) or 0)
        by = float(b.get("y", 0) or 0)
        bw = float(b.get("width", 0) or 0)
        bh = float(b.get("height", 0) or 0)
    except (TypeError, ValueError):
        return False
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return not (
        ax + aw <= bx + tol
        or bx + bw <= ax + tol
        or ay + ah <= by + tol
        or by + bh <= ay + tol
    )


def _is_group_background(eid: str, semantic_id: str = "") -> bool:
    key = semantic_id or eid
    return key.endswith(BACKGROUND_SUFFIX) or key.startswith("group_") or key.startswith("g_")


def _is_group_frame_element(eid: str, semantic_id: str, id_map: Dict[str, str]) -> bool:
    key = semantic_id or eid
    return _is_group_background(eid, semantic_id) or bool(
        key and companion_id(key, TITLE_SUFFIX) in id_map
    )


def _translate_element(elem: Dict[str, Any], dx: float = 0.0, dy: float = 0.0) -> None:
    elem["x"] = _num(elem.get("x")) + dx
    elem["y"] = _num(elem.get("y")) + dy


def _translate_related(
    shape: Dict[str, Any],
    dx: float,
    dy: float,
    by_id: Dict[str, Dict[str, Any]],
    shape_to_text: Dict[str, str],
    shape_to_icon: Dict[str, str],
) -> None:
    _translate_element(shape, dx, dy)
    for related_id in (shape_to_text.get(shape.get("id")), shape_to_icon.get(shape.get("id"))):
        related = by_id.get(related_id) if related_id else None
        if related is not None:
            _translate_element(related, dx, dy)


def _horizontal_overlap_amount(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ax = _num(a.get("x"))
    aw = _num(a.get("width"))
    bx = _num(b.get("x"))
    bw = _num(b.get("width"))
    return min(ax + aw, bx + bw) - max(ax, bx)


def _vertical_overlap_amount(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ay = _num(a.get("y"))
    ah = _num(a.get("height"))
    by = _num(b.get("y"))
    bh = _num(b.get("height"))
    return min(ay + ah, by + bh) - max(ay, by)


def _resolve_container_overlaps(
    candidates: List[Dict[str, Any]],
    original_dims: Dict[str, Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
    shape_to_text: Dict[str, str],
    shape_to_icon: Dict[str, str],
    gap: float = 8.0,
) -> None:
    """Resolve small container overlaps by shifting related geometry.

    The push axis is the one with the *smaller* penetration: two shapes in the
    same row separate horizontally, two stacked in the same column separate
    vertically. Pushing along x unconditionally used the horizontal overlap of
    a vertically-stacked pair — a full node width for column-aligned nodes —
    and shot the lower node out of its column for a 1px vertical touch.
    """
    for _ in range(max(6, 2 * len(candidates))):
        changed = False
        for i, a in enumerate(candidates):
            if a.get("type") not in _CONTAINER_TYPES:
                continue
            for b in candidates[i + 1:]:
                if b.get("type") not in _CONTAINER_TYPES:
                    continue
                if not _bbox_overlap(a, b, tol=0.0):
                    continue

                overlap_x = _horizontal_overlap_amount(a, b)
                overlap_y = _vertical_overlap_amount(a, b)
                if overlap_x <= 0 or overlap_y <= 0:
                    continue

                original_a = original_dims.get(a.get("id"), a)
                original_b = original_dims.get(b.get("id"), b)
                same_row = abs(
                    _num(original_a.get("y")) + _num(original_a.get("height")) / 2
                    - _num(original_b.get("y")) - _num(original_b.get("height")) / 2
                ) < 2.0
                same_column = abs(
                    _num(original_a.get("x")) + _num(original_a.get("width")) / 2
                    - _num(original_b.get("x")) - _num(original_b.get("width")) / 2
                ) < 2.0
                # Text growth must not turn a horizontal process into a
                # staggered one. Prefer the original row/column when clear.
                if same_row or (not same_column and overlap_x <= overlap_y):
                    a_key = _num(original_a.get("x")) + _num(original_a.get("width")) / 2.0
                    b_key = _num(original_b.get("x")) + _num(original_b.get("width")) / 2.0
                    move = overlap_x + gap
                    axis = "x"
                else:
                    a_key = _num(original_a.get("y")) + _num(original_a.get("height")) / 2.0
                    b_key = _num(original_b.get("y")) + _num(original_b.get("height")) / 2.0
                    move = overlap_y + gap
                    axis = "y"

                first, second = (a, b) if a_key <= b_key else (b, a)
                if same_row and axis == "x":
                    original_first = original_dims.get(first.get("id"), first)
                    original_second = original_dims.get(second.get("id"), second)
                    original_gap = _num(original_second.get("x")) - (
                        _num(original_first.get("x")) + _num(original_first.get("width"))
                    )
                    # Icon/text growth must preserve the layout's intended
                    # connector-label room rather than compressing it to 24.
                    move = _num(first.get("x")) + _num(first.get("width")) + max(gap, 24.0, original_gap) - _num(second.get("x"))
                elif same_column and axis == "y":
                    move = _num(first.get("y")) + _num(first.get("height")) + gap - _num(second.get("y"))
                forward = (move, 0.0) if axis == "x" else (0.0, move)
                backward = (-move, 0.0) if axis == "x" else (0.0, -move)

                if second.get("id") in original_dims:
                    _translate_related(second, *forward, by_id, shape_to_text, shape_to_icon)
                    changed = True
                elif first.get("id") in original_dims:
                    _translate_related(first, *backward, by_id, shape_to_text, shape_to_icon)
                    changed = True
        if not changed:
            break


def fit_shape_sizes_to_text(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Enforce shape_width ≥ bound_text_width for every container shape.

    Returns a deep-copied manifest with shape / text elements adjusted
    in place.  Idempotent: running twice produces the same output as
    running once.

    Elements handled:
        - rectangle / diamond / ellipse with a bound text → grow to fit
        - text with ``containerId`` → skipped (the container owns it,
          it is resized as part of ``_fit_container_to_text``)
        - text without ``containerId`` → grown as standalone
        - any other type (arrow, image, line, ...) → passed through

    Safety valve: after all expansions, overlaps introduced by the fitter
    are detected and the involved shapes/texts are reverted to their
    original dimensions.  This prevents a well-intentioned text-fit from
    breaking the layout agent's spacing guarantees.
    """
    manifest = deepcopy(manifest)
    elements: List[Dict[str, Any]] = manifest.get("elements") or []
    by_id: Dict[str, Dict[str, Any]] = {e["id"]: e for e in elements if isinstance(e, dict) and e.get("id")}
    id_map = id_map_from_manifest(manifest)
    semantic_by_render_id = reverse_id_map(id_map)

    # Track original dimensions so we can revert overlaps.
    original_dims: Dict[str, Dict[str, Any]] = {}
    icon_by_container = _map_icons_to_containers(elements)
    shape_to_text: Dict[str, str] = {}
    for e in elements:
        if isinstance(e, dict) and e.get("containerId"):
            shape_to_text[e["containerId"]] = e["id"]
    shape_to_icon: Dict[str, str] = {
        shape_id: icon["id"]
        for shape_id, icon in icon_by_container.items()
        if isinstance(icon, dict) and icon.get("id")
    }

    for e in elements:
        if not isinstance(e, dict):
            continue
        etype = e.get("type")

        if etype in _CONTAINER_TYPES:
            eid = e.get("id", "")
            if _is_group_frame_element(eid, semantic_by_render_id.get(eid, ""), id_map):
                continue
            text_elem = _find_bound_text(e, by_id)
            if text_elem is not None:
                _fit_container_to_text(e, text_elem, icon_by_container.get(e["id"]), original_dims)
            continue

        if etype == "text":
            # Text bound to a container was already resized via
            # _fit_container_to_text above; skip it here.
            if e.get("containerId"):
                continue
            _fit_standalone_text(e)
            continue

        # arrow / image / line / etc. — untouched.

    # ── Safety valve: revert expansions that introduced overlaps ──
    # Build a list of candidate elements (skip arrows, bound text, group bg).
    candidates: List[Dict[str, Any]] = []
    for e in elements:
        if not isinstance(e, dict):
            continue
        etype = e.get("type")
        if etype in ("arrow", "freedraw", "line", "image"):
            continue
        if etype == "text" and e.get("containerId"):
            continue
        eid = e.get("id", "")
        if _is_group_frame_element(eid, semantic_by_render_id.get(eid, ""), id_map):
            continue
        candidates.append(e)

    _resolve_container_overlaps(candidates, original_dims, by_id, shape_to_text, shape_to_icon)

    # Find overlaps where at least one element was modified by the fitter.
    revert_ids: set = set()
    n = len(candidates)
    for i in range(n):
        a = candidates[i]
        for j in range(i + 1, n):
            b = candidates[j]
            if not _bbox_overlap(a, b):
                continue
            a_id = a.get("id", "")
            b_id = b.get("id", "")
            a_modified = a_id in original_dims
            b_modified = b_id in original_dims
            if a_modified or b_modified:
                if a_modified:
                    revert_ids.add(a_id)
                if b_modified:
                    revert_ids.add(b_id)

    if revert_ids:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "shape_size_fitter: %d element(s) reverted to original dims to avoid overlaps: %s",
            len(revert_ids),
            sorted(revert_ids),
        )
        for eid in revert_ids:
            elem = by_id.get(eid)
            if elem is None:
                continue
            orig = original_dims[eid]
            for key, val in orig.items():
                if val is not None:
                    elem[key] = val
            # When a container shape is reverted, also revert its bound text
            # so the text stays centered inside the (now-reduced) shape.
            if eid in shape_to_text:
                text_id = shape_to_text[eid]
                text_elem = by_id.get(text_id)
                text_orig = original_dims.get(text_id)
                if text_elem is not None and text_orig is not None:
                    for key, val in text_orig.items():
                        if val is not None:
                            text_elem[key] = val
            if eid in shape_to_icon:
                icon_id = shape_to_icon[eid]
                icon_elem = by_id.get(icon_id)
                icon_orig = original_dims.get(icon_id)
                if icon_elem is not None and icon_orig is not None:
                    for key, val in icon_orig.items():
                        if val is not None:
                            icon_elem[key] = val

    manifest["elements"] = elements
    sync_node_icons(manifest)
    return manifest
