"""Styling-stage output contract validation."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    TITLE_SUFFIX,
    companion_base_id,
    companion_id,
)
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.common.tldraw_utils import TLDrawColorValidator, TLDrawFillValidator, TLDrawShapeValidator
from evo_diagram.canvas_runtime import normalize_canvas_library


class StylingValidationError(ValueError):
    """Raised when Styling output violates the Structure-to-Styling contract."""


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_EXCALIDRAW_NATIVE_SHAPES = {"rectangle", "ellipse", "diamond", "triangle"}
_TLDRAW_TEXT_TYPES = {"text"}
_TLDRAW_VALID_COLORS = set(TLDrawColorValidator.VALID_COLORS)
_TLDRAW_VALID_FILLS = set(TLDrawFillValidator.VALID_FILLS)
_TLDRAW_VALID_SHAPES = set(TLDrawShapeValidator.VALID_SHAPES)
_LAYOUT_OWNED_FIELDS = frozenset({
    "x",
    "y",
    "w",
    "h",
    "width",
    "height",
    "min_width",
    "min_height",
})


def validate_styling_instantiation(
    instantiation: Any,
    structure_instantiation: Optional[Dict[str, Any]],
    *,
    canvas_library: str = "excalidraw",
) -> Dict[str, Any]:
    """Validate Styling output against Structure ids and canvas-specific fields."""
    if not isinstance(instantiation, dict):
        raise StylingValidationError(
            "Styling instantiation must be a JSON object; "
            f"got {type(instantiation).__name__}."
        )

    structure = unwrap_structure_instantiation(structure_instantiation)
    node_ids = _collect_ids(structure, "nodes")
    group_ids = _collect_ids(structure, "groups")
    edge_ids = _collect_ids(structure, "edges")
    allowed_ids = _allowed_styling_ids(node_ids, group_ids, edge_ids)
    canvas = _normalise_canvas(canvas_library)
    group_shells: set[str] = set()

    for element_id, element_data in instantiation.items():
        if not isinstance(element_id, str) or not element_id.strip():
            raise StylingValidationError(f"Styling element id must be a non-empty string; got {element_id!r}.")
        if element_id not in allowed_ids:
            raise StylingValidationError(f"Unknown styling id {element_id!r}; Styling must reuse Structure ids.")
        if not isinstance(element_data, dict):
            raise StylingValidationError(f"Styling entry {element_id!r} must be an object.")
        _reject_layout_owned_fields(element_id, element_data)

        if _is_icon_key(element_id):
            _validate_icon_entry(element_id, element_data, node_ids)
        elif element_id in edge_ids:
            _validate_edge_entry(element_id, element_data, canvas)
        elif element_id.endswith(TITLE_SUFFIX):
            _validate_title_entry(element_id, element_data, canvas)
        elif (
            canvas == "excalidraw"
            and element_id in group_ids
            and _entry_type(element_data) is None
            and companion_id(element_id, BACKGROUND_SUFFIX) in instantiation
        ):
            # Some models repeat the logical group beside its actual surface.
            # Validate that surface separately, then omit the non-rendering
            # shell so Layout does not invent a second box for the same group.
            group_shells.add(element_id)
        else:
            _validate_shape_entry(element_id, element_data, canvas, group_surface=element_id in group_ids)

    _validate_required_coverage(instantiation, node_ids, edge_ids, structure)
    if group_shells:
        return {key: value for key, value in instantiation.items() if key not in group_shells}
    return instantiation


def _normalise_canvas(canvas_library: str) -> str:
    try:
        return normalize_canvas_library(canvas_library or "excalidraw")
    except ValueError as exc:
        raise StylingValidationError(
            f"Unknown canvas_library for Styling validation: {canvas_library!r}."
        ) from exc


def _collect_ids(structure_instantiation: Dict[str, Any], field_name: str) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(structure_instantiation.get(field_name) or []):
        if not isinstance(item, dict):
            raise StylingValidationError(f"Structure field {field_name}[{index}] must be an object.")
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id.strip():
            ids.add(item_id)
    return ids


def _allowed_styling_ids(node_ids: set[str], group_ids: set[str], edge_ids: set[str]) -> set[str]:
    allowed = set(node_ids) | set(group_ids) | set(edge_ids)
    for node_id in node_ids:
        allowed.add(companion_id(node_id, ICON_SUFFIX))
    for group_id in group_ids:
        allowed.add(companion_id(group_id, BACKGROUND_SUFFIX))
        allowed.add(companion_id(group_id, TITLE_SUFFIX))
    return allowed


def _validate_required_coverage(
    instantiation: Dict[str, Any],
    node_ids: set[str],
    edge_ids: set[str],
    structure: Dict[str, Any],
) -> None:
    missing_nodes = sorted(node_id for node_id in node_ids if node_id not in instantiation)
    if missing_nodes:
        raise StylingValidationError(
            "Missing styling entries for Structure node ids: " + ", ".join(missing_nodes)
        )

    missing_edges = sorted(edge_id for edge_id in edge_ids if edge_id not in instantiation)
    if missing_edges:
        raise StylingValidationError(
            "Missing styling entries for Structure edge ids: " + ", ".join(missing_edges)
        )

    for group in structure.get("groups") or []:
        if not isinstance(group, dict):
            continue
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id.strip():
            continue
        if group_id not in instantiation and companion_id(group_id, BACKGROUND_SUFFIX) not in instantiation:
            raise StylingValidationError(
                f"Missing styling surface for Structure group id {group_id!r}; "
                "expected group entry or group ':background'."
            )
        label = group.get("label")
        # Sequence lanes are navigation containers, not repeated headings.
        # Their sole participant header already carries the visible label.
        members = group.get("members") or []
        participant_lane = (structure.get("chart_type") == "sequence_diagram"
                            and len(members) == 1 and members[0] in node_ids)
        if participant_lane:
            continue
        if isinstance(label, str) and label.strip() and not _has_group_title(instantiation, group_id):
            raise StylingValidationError(
                f"Missing title styling for labelled Structure group id {group_id!r}."
            )


def _has_group_title(instantiation: Dict[str, Any], group_id: str) -> bool:
    title = instantiation.get(companion_id(group_id, TITLE_SUFFIX))
    if isinstance(title, dict) and _extract_text(title):
        return True
    group_entry = instantiation.get(group_id)
    if isinstance(group_entry, dict) and _entry_type(group_entry) == "text" and _extract_text(group_entry):
        return True
    return False


def _is_icon_key(element_id: str) -> bool:
    return element_id.endswith(ICON_SUFFIX)


def _icon_owner_id(element_id: str) -> str:
    return companion_base_id(element_id) or element_id


def _validate_icon_entry(element_id: str, element_data: Dict[str, Any], node_ids: set[str]) -> None:
    owner_id = _icon_owner_id(element_id)
    if owner_id not in node_ids:
        raise StylingValidationError(f"Icon styling id {element_id!r} must reference a Structure node id.")
    if element_data.get("type") != "icon":
        raise StylingValidationError(f"Icon styling id {element_id!r} must have type='icon'.")
    props = element_data.get("props")
    if not isinstance(props, dict) or not isinstance(props.get("icon"), str) or not props["icon"].strip():
        raise StylingValidationError(f"Icon styling id {element_id!r} must include props.icon.")


def _reject_layout_owned_fields(element_id: str, element_data: Dict[str, Any]) -> None:
    top_level = sorted(set(element_data) & _LAYOUT_OWNED_FIELDS)
    if top_level:
        raise StylingValidationError(
            f"Styling entry {element_id!r} must not include layout-owned fields: "
            + ", ".join(top_level)
            + ". Layout owns geometry."
        )

    props = element_data.get("props")
    if isinstance(props, dict):
        prop_fields = sorted(set(props) & _LAYOUT_OWNED_FIELDS)
        if prop_fields:
            raise StylingValidationError(
                f"Styling entry {element_id!r} props must not include layout-owned fields: "
                + ", ".join(prop_fields)
                + ". Layout owns geometry."
            )


def _validate_edge_entry(element_id: str, element_data: Dict[str, Any], canvas: str) -> None:
    if canvas == "excalidraw":
        allowed_keys = {"strokeColor"}
        extra_keys = sorted(set(element_data) - allowed_keys)
        if extra_keys:
            raise StylingValidationError(
                f"Excalidraw edge styling {element_id!r} must be color-only; unexpected keys: "
                + ", ".join(extra_keys)
            )
        _require_hex_color(element_id, element_data.get("strokeColor"), "strokeColor")
        return

    allowed_keys = {"props"}
    extra_keys = sorted(set(element_data) - allowed_keys)
    if extra_keys:
        raise StylingValidationError(
            f"TLDraw edge styling {element_id!r} must be props.color-only; unexpected keys: "
            + ", ".join(extra_keys)
        )
    props = _require_props(element_id, element_data)
    _require_tldraw_color(element_id, props.get("color"), "props.color")


def _validate_title_entry(element_id: str, element_data: Dict[str, Any], canvas: str) -> None:
    if _entry_type(element_data) != "text":
        raise StylingValidationError(f"Title styling {element_id!r} must be a text entry.")
    if not _extract_text(element_data):
        raise StylingValidationError(f"Title styling {element_id!r} must include non-empty text.")
    if canvas == "excalidraw":
        color = _first_present(
            element_data.get("strokeColor"),
            _label_value(element_data, "strokeColor"),
        )
        _require_hex_color(element_id, color, "strokeColor")
    else:
        props = _require_props(element_id, element_data)
        _require_tldraw_color(element_id, props.get("color"), "props.color")


def _validate_shape_entry(element_id: str, element_data: Dict[str, Any], canvas: str,
                          *, group_surface: bool = False) -> None:
    if canvas == "excalidraw":
        shape = _entry_type(element_data)
        if shape not in _EXCALIDRAW_NATIVE_SHAPES and shape != "text":
            raise StylingValidationError(
                f"Excalidraw styling {element_id!r} has unsupported shape/type {shape!r}."
            )
        if shape == "text":
            if not _extract_text(element_data):
                raise StylingValidationError(f"Text styling {element_id!r} must include non-empty text.")
            color = _first_present(
                element_data.get("strokeColor"),
                _label_value(element_data, "strokeColor"),
            )
            _require_hex_color(element_id, color, "strokeColor")
            return
        is_surface = group_surface or element_id.endswith(BACKGROUND_SUFFIX)
        if not _extract_text(element_data) and not is_surface:
            raise StylingValidationError(f"Shape styling {element_id!r} must include renderable label text.")
        _require_hex_color(element_id, element_data.get("strokeColor"), "strokeColor")
        background = element_data.get("backgroundColor")
        if background == "transparent" and is_surface:
            return
        _require_hex_color(element_id, background, "backgroundColor")
        return

    entry_type = element_data.get("type")
    if entry_type == "text":
        _validate_title_entry(element_id, element_data, canvas)
        return
    if entry_type != "geo":
        raise StylingValidationError(f"TLDraw styling {element_id!r} must have type='geo'.")
    props = _require_props(element_id, element_data)
    geo = props.get("geo")
    if geo not in _TLDRAW_VALID_SHAPES:
        raise StylingValidationError(f"TLDraw styling {element_id!r} has unsupported props.geo {geo!r}.")
    _require_tldraw_color(element_id, props.get("color"), "props.color")
    fill = props.get("fill")
    if fill not in _TLDRAW_VALID_FILLS:
        raise StylingValidationError(f"TLDraw styling {element_id!r} has unsupported props.fill {fill!r}.")
    if not _extract_text(element_data) and not element_id.endswith(BACKGROUND_SUFFIX):
        raise StylingValidationError(f"TLDraw styling {element_id!r} must include props.text or label.text.")


def _entry_type(element_data: Dict[str, Any]) -> Any:
    return element_data.get("shape") or element_data.get("type")


def _extract_text(element_data: Dict[str, Any]) -> str:
    label = element_data.get("label")
    if isinstance(label, dict) and isinstance(label.get("text"), str) and label["text"].strip():
        return label["text"].strip()
    props = element_data.get("props")
    if isinstance(props, dict) and isinstance(props.get("text"), str) and props["text"].strip():
        return props["text"].strip()
    text = element_data.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""


def _label_value(element_data: Dict[str, Any], key: str) -> Any:
    label = element_data.get("label")
    if isinstance(label, dict):
        return label.get(key)
    return None


def _require_props(element_id: str, element_data: Dict[str, Any]) -> Dict[str, Any]:
    props = element_data.get("props")
    if not isinstance(props, dict):
        raise StylingValidationError(f"Styling {element_id!r} must include a props object.")
    return props


def _require_hex_color(element_id: str, value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _HEX_COLOR_RE.match(value):
        raise StylingValidationError(
            f"Styling {element_id!r} field {field_name} must be a #RRGGBB hex color."
        )


def _require_tldraw_color(element_id: str, value: Any, field_name: str) -> None:
    if value not in _TLDRAW_VALID_COLORS:
        raise StylingValidationError(
            f"Styling {element_id!r} field {field_name} must be a valid TLDraw color."
        )


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None
