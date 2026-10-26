"""Atomic edit op handlers — one function per EditOpName.

Every function takes the full manifest plus the EditOp ``id`` and ``payload``
fields, then mutates the manifest in place. Some ops intentionally ignore an
empty payload but keep the shared dispatcher signature. Returns
``(applied: bool, error: str | None)``.

These are intentionally tiny so the dispatcher in ``apply_edits.py`` can
route a single ``EditOp`` with one switch.

Excalidraw conventions used here:
- Elements live in ``manifest["elements"]`` (a list).
- Each element has a unique ``id``. Lookup is O(N), which is acceptable for
  the small edit batches emitted by one refinement iteration.
- ``boundElements`` is a list of ``{"id": ..., "type": ...}`` dicts.
- ``startBinding`` / ``endBinding`` on arrows are dicts with ``elementId``,
  ``focus``, ``gap``.
- Fractional ``index`` strings (e.g. ``"a00003"``) order rendering bottom→top.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from evo_diagram.agentic_system.common.node_icons import sync_node_icons, set_node_icon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_element(elements: List[Dict[str, Any]], element_id: str) -> Optional[Dict[str, Any]]:
    for elem in elements:
        if isinstance(elem, dict) and elem.get("id") == element_id:
            return elem
    return None


def _elements_list(manifest: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    elements = manifest.get("elements")
    if not isinstance(elements, list):
        return None, "manifest has no elements list"
    return elements, None


def _require_element(
    manifest: Dict[str, Any],
    element_id: str,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]], Optional[str]]:
    elements, error = _elements_list(manifest)
    if error:
        return None, None, error
    assert elements is not None
    elem = _find_element(elements, element_id)
    if elem is None:
        return elements, None, f"element {element_id!r} not found"
    return elements, elem, None


def _remove_bound_ref(holder: Dict[str, Any], bound_id: str) -> bool:
    bound = holder.get("boundElements")
    if not isinstance(bound, list):
        return False
    new_bound = [
        item for item in bound
        if not (isinstance(item, dict) and item.get("id") == bound_id)
    ]
    if len(new_bound) == len(bound):
        return False
    holder["boundElements"] = new_bound
    _bump_version(holder)
    return True


def _bump_version(elem: Dict[str, Any]) -> None:
    """Excalidraw uses ``version`` for change tracking. Bumping is harmless
    when missing (renderer treats absent as 1)."""
    try:
        elem["version"] = int(elem.get("version", 1) or 1) + 1
    except (TypeError, ValueError):
        elem["version"] = 2


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bound_text_elements(
    elements: List[Dict[str, Any]],
    container: Dict[str, Any],
) -> List[Dict[str, Any]]:
    by_id = {
        elem.get("id"): elem
        for elem in elements
        if isinstance(elem, dict) and elem.get("id")
    }
    container_id = container.get("id")
    seen: set[str] = set()
    texts: List[Dict[str, Any]] = []

    for bound in container.get("boundElements") or []:
        if not isinstance(bound, dict) or bound.get("type") != "text":
            continue
        text_id = bound.get("id")
        text_elem = by_id.get(text_id)
        if (
            isinstance(text_elem, dict)
            and text_elem.get("type") == "text"
            and text_elem.get("id") not in seen
        ):
            texts.append(text_elem)
            seen.add(text_elem["id"])

    for elem in elements:
        if (
            isinstance(elem, dict)
            and elem.get("type") == "text"
            and elem.get("containerId") == container_id
            and elem.get("id") not in seen
        ):
            texts.append(elem)
            seen.add(elem["id"])

    return texts


def _move_bound_text(
    elements: List[Dict[str, Any]],
    container: Dict[str, Any],
    *,
    dx: float,
    dy: float,
) -> None:
    for text_elem in _bound_text_elements(elements, container):
        text_elem["x"] = _num(text_elem.get("x")) + dx
        text_elem["y"] = _num(text_elem.get("y")) + dy
        _bump_version(text_elem)


def _recenter_bound_text(
    elements: List[Dict[str, Any]],
    container: Dict[str, Any],
) -> None:
    x = _num(container.get("x"))
    y = _num(container.get("y"))
    width = _num(container.get("width"))
    height = _num(container.get("height"))
    for text_elem in _bound_text_elements(elements, container):
        text_width = _num(text_elem.get("width"))
        text_height = _num(text_elem.get("height"))
        text_elem["x"] = x + (width - text_width) / 2.0
        text_elem["y"] = y + (height - text_height) / 2.0
        _bump_version(text_elem)


# ---------------------------------------------------------------------------
# Op handlers
# ---------------------------------------------------------------------------


_ARROW_GEOMETRY_ERROR = (
    "arrow geometry is not directly editable: an Excalidraw arrow's shape is "
    "baked into its absolute x/y/points polyline, so translating or resizing it "
    "detaches it from the shapes it connects. Arrows follow their endpoints "
    "through the arrow re-route pass instead."
)


def op_set_position(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    elements, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elements is not None and elem is not None
    if elem.get("type") == "arrow":
        return False, _ARROW_GEOMETRY_ERROR
    if "x" not in payload or "y" not in payload:
        return False, "set_position requires x and y in payload"
    try:
        old_x = _num(elem.get("x"))
        old_y = _num(elem.get("y"))
        elem["x"] = float(payload["x"])
        elem["y"] = float(payload["y"])
    except (TypeError, ValueError) as exc:
        return False, f"invalid x/y: {exc}"
    _move_bound_text(
        elements,
        elem,
        dx=_num(elem.get("x")) - old_x,
        dy=_num(elem.get("y")) - old_y,
    )
    sync_node_icons(manifest, element_id)
    _bump_version(elem)
    return True, None


def op_set_size(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    elements, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elements is not None and elem is not None
    if elem.get("type") == "arrow":
        return False, _ARROW_GEOMETRY_ERROR
    if "width" not in payload or "height" not in payload:
        return False, "set_size requires width and height in payload"
    try:
        w = float(payload["width"])
        h = float(payload["height"])
    except (TypeError, ValueError) as exc:
        return False, f"invalid w/h: {exc}"
    if w <= 0 or h <= 0:
        return False, f"non-positive width/height (w={w}, h={h})"
    elem["width"] = w
    elem["height"] = h
    _recenter_bound_text(elements, elem)
    sync_node_icons(manifest, element_id)
    _bump_version(elem)
    return True, None


def op_set_style(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    _, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elem is not None

    # Allow only known style keys to avoid accidental free-form mutation.
    style_keys = {
        "backgroundColor",
        "strokeColor",
        "strokeWidth",
        "strokeStyle",
        "fillStyle",
        "roughness",
        "opacity",
        "fontSize",
        "fontFamily",
        "textAlign",
        "verticalAlign",
    }
    unknown_keys = sorted(key for key in payload if key not in style_keys)
    if unknown_keys:
        return False, f"set_style payload has unknown style keys: {unknown_keys}"
    applied_any = False
    for key, value in payload.items():
        elem[key] = value
        applied_any = True
    if not applied_any:
        return False, "set_style payload had no recognised style keys"
    sync_node_icons(manifest, elem.get("containerId") or element_id)
    _bump_version(elem)
    return True, None


def op_set_text(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    _, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elem is not None
    text = payload.get("text")
    if not isinstance(text, str):
        return False, "set_text requires payload.text as a string"
    if elem.get("type") != "text":
        return False, f"set_text targets non-text element type={elem.get('type')!r}"
    elem["text"] = text
    elem["originalText"] = text
    _bump_version(elem)
    return True, None


def op_delete_element(
    manifest: Dict[str, Any],
    element_id: str,
    _payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    elements, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elements is not None and elem is not None

    # --- Safety checks: refuse to delete connected elements ---
    # Idempotent: already deleted is always safe.
    if not elem.get("isDeleted"):
        block_reasons: List[str] = []

        # 1. Bound text/icon inside a container — deleting orphans the label.
        if elem.get("containerId"):
            block_reasons.append(
                f"element is bound to container {elem['containerId']!r}"
            )

        # 2. Has bound children (text labels, arrows attached to it).
        bound = elem.get("boundElements")
        if isinstance(bound, list) and bound:
            bound_ids = [
                b.get("id") for b in bound if isinstance(b, dict)
            ]
            block_reasons.append(
                f"element has {len(bound_ids)} bound element(s): {bound_ids}"
            )

        # 3. Arrows whose start/end point to this element.
        for other in elements:
            if not isinstance(other, dict) or other.get("type") != "arrow":
                continue
            if other.get("isDeleted"):
                continue
            for side in ("start", "end"):
                binding = other.get(f"{side}Binding")
                if (
                    isinstance(binding, dict)
                    and binding.get("elementId") == element_id
                ):
                    block_reasons.append(
                        f"arrow {other.get('id')!r} has {side}Binding "
                        f"pointing to this element"
                    )

        if block_reasons:
            return False, (
                f"refusing to delete connected element {element_id!r}: "
                + "; ".join(block_reasons)
            )

    if elem.get("isDeleted"):
        return False, None

    # --- Proceed with soft-delete ---
    # Excalidraw uses ``isDeleted`` flag rather than physical removal — keeps
    # the element index stable. The validator filters deleted elements when
    # rendering. We also strip back-references so the manifest stays clean.
    elem["isDeleted"] = True
    _bump_version(elem)

    # Remove this id from anyone's boundElements list.
    for other in elements:
        if not isinstance(other, dict):
            continue
        _remove_bound_ref(other, element_id)

    # Clear startBinding/endBinding on arrows that point to this element.
    for other in elements:
        if not isinstance(other, dict) or other.get("type") != "arrow":
            continue
        for side in ("start", "end"):
            binding = other.get(f"{side}Binding")
            if isinstance(binding, dict) and binding.get("elementId") == element_id:
                other[f"{side}Binding"] = None
                _bump_version(other)

    return True, None


def op_clear_arrow_binding(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    elements, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elements is not None and elem is not None
    if elem.get("type") != "arrow":
        return False, f"clear_arrow_binding targets non-arrow type={elem.get('type')!r}"
    side = payload.get("side")
    if side not in ("start", "end"):
        return False, "clear_arrow_binding requires payload.side ∈ {start, end}"
    binding_key = f"{side}Binding"
    if elem.get(binding_key) is None:
        # Already cleared — idempotent no-op.
        return False, None
    target_id = (elem[binding_key] or {}).get("elementId") if isinstance(elem.get(binding_key), dict) else None
    elem[binding_key] = None
    _bump_version(elem)

    # Strip the back-ref on the previously-bound shape, if any.
    if target_id:
        target = _find_element(elements, target_id)
        if target is not None:
            _remove_bound_ref(target, element_id)
    return True, None


def op_clear_container_binding(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    elements, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elements is not None and elem is not None
    if elem.get("type") != "text":
        return False, f"clear_container_binding targets non-text type={elem.get('type')!r}"

    current_container_id = elem.get("containerId")
    if not current_container_id:
        return False, None

    expected_container_id = payload.get("container_id")
    if (
        expected_container_id is not None
        and expected_container_id != current_container_id
    ):
        return False, (
            f"containerId changed from expected {expected_container_id!r} "
            f"to {current_container_id!r}; refusing stale clear"
        )

    elem["containerId"] = None
    _bump_version(elem)

    target = _find_element(elements, current_container_id)
    if target is not None:
        _remove_bound_ref(target, element_id)
    return True, None


def op_append_bound_element(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    elements, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elements is not None and elem is not None
    bound_id = payload.get("bound_id")
    bound_type = payload.get("type", "arrow")
    if not isinstance(bound_id, str) or not bound_id:
        return False, "append_bound_element requires payload.bound_id (str)"
    if bound_type not in ("arrow", "text"):
        return False, "append_bound_element type must be 'arrow' or 'text'"

    # Verify the referenced element exists; otherwise the back-ref is bogus.
    if _find_element(elements, bound_id) is None:
        return False, f"bound_id {bound_id!r} does not exist; refusing to add dangling ref"

    bound = elem.get("boundElements")
    if not isinstance(bound, list):
        bound = []
        elem["boundElements"] = bound

    # Idempotent — skip if already present.
    if any(isinstance(b, dict) and b.get("id") == bound_id for b in bound):
        return False, None

    bound.append({"id": bound_id, "type": bound_type})
    _bump_version(elem)
    return True, None


def op_remove_bound_element(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    _, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elem is not None
    bound_id = payload.get("bound_id")
    if not isinstance(bound_id, str) or not bound_id:
        return False, "remove_bound_element requires payload.bound_id (str)"
    if not isinstance(elem.get("boundElements"), list):
        return False, None
    if _remove_bound_ref(elem, bound_id):
        return True, None
    return False, None


def op_set_index(
    manifest: Dict[str, Any],
    element_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    _, elem, error = _require_element(manifest, element_id)
    if error:
        return False, error
    assert elem is not None
    new_index = payload.get("index")
    if not isinstance(new_index, str) or not new_index:
        return False, "set_index requires payload.index (str fractional index)"
    elem["index"] = new_index
    _bump_version(elem)
    return True, None


# ---------------------------------------------------------------------------
# Dispatch table — used by apply_edits.py
# ---------------------------------------------------------------------------

def op_set_icon(manifest, element_id, payload):
    if set(payload) != {"name"} or not isinstance(payload.get("name"), str):
        return False, "set_icon requires only payload.name (bundled icon name)"
    try:
        return set_node_icon(manifest, element_id, payload["name"]), None
    except ValueError as exc:
        return False, str(exc)


OP_HANDLERS: Dict[str, Any] = {
    "set_icon": op_set_icon,
    "set_position": op_set_position,
    "set_size": op_set_size,
    "set_style": op_set_style,
    "set_text": op_set_text,
    "delete_element": op_delete_element,
    "clear_arrow_binding": op_clear_arrow_binding,
    "clear_container_binding": op_clear_container_binding,
    "append_bound_element": op_append_bound_element,
    "remove_bound_element": op_remove_bound_element,
    "set_index": op_set_index,
}


__all__ = [
    "OP_HANDLERS",
    "op_set_position",
    "op_set_size",
    "op_set_style",
    "op_set_text",
    "op_delete_element",
    "op_clear_arrow_binding",
    "op_clear_container_binding",
    "op_append_bound_element",
    "op_remove_bound_element",
    "op_set_index",
]
