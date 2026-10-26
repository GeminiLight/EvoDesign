#!/usr/bin/env python3
"""
Direct LLM Output to Excalidraw Scene Converter

Converts simplified element JSON from LLM output to a complete Excalidraw scene.
"""

import hashlib
import random
import time
from typing import Any, Dict, List, Optional


def _generate_id() -> str:
    h = hashlib.md5(f"{time.time_ns()}{random.random()}".encode()).hexdigest()
    return h[:20]


def _random_seed() -> int:
    return random.randint(1, 2_000_000_000)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _default_fields() -> Dict[str, Any]:
    return {
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": "a0",
        "roundness": None,
        "seed": _random_seed(),
        "version": 2,
        "versionNonce": _random_seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": _now_ms(),
        "link": None,
        "locked": False,
    }


def _estimate_text_size(text: str, font_size: int = 20) -> Dict[str, float]:
    lines = text.split("\n") if text else [""]
    max_len = max(len(line) for line in lines)
    width = max_len * font_size * 0.6
    height = len(lines) * font_size * 1.25
    return {
        "width": max(width, 10),
        "height": max(height, font_size * 1.25),
    }


def _resolve_color(color: Optional[str], default: str) -> str:
    if not color:
        return default
    return color


def _get_bounds(elem: Dict[str, Any]) -> Dict[str, float]:
    return {
        "x": float(elem.get("x", 0)),
        "y": float(elem.get("y", 0)),
        "width": float(elem.get("width", elem.get("w", 160))),
        "height": float(elem.get("height", elem.get("h", 60))),
    }


def _binding_id(binding: Any) -> Optional[str]:
    if isinstance(binding, dict):
        element_id = binding.get("elementId")
        return str(element_id) if element_id else None
    return None


def _center(bounds: Dict[str, float]) -> tuple[float, float]:
    return (
        bounds["x"] + bounds["width"] / 2,
        bounds["y"] + bounds["height"] / 2,
    )


def _connection_points(
    start_bounds: Dict[str, float],
    end_bounds: Dict[str, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Pick side-center endpoints between two rectangular bounds."""
    start_cx, start_cy = _center(start_bounds)
    end_cx, end_cy = _center(end_bounds)
    dx = end_cx - start_cx
    dy = end_cy - start_cy

    if abs(dx) >= abs(dy):
        if dx >= 0:
            start = (start_bounds["x"] + start_bounds["width"], start_cy)
            end = (end_bounds["x"], end_cy)
        else:
            start = (start_bounds["x"], start_cy)
            end = (end_bounds["x"] + end_bounds["width"], end_cy)
    else:
        if dy >= 0:
            start = (start_cx, start_bounds["y"] + start_bounds["height"])
            end = (end_cx, end_bounds["y"])
        else:
            start = (start_cx, start_bounds["y"])
            end = (end_cx, end_bounds["y"] + end_bounds["height"])

    return start, end


def _convert_shape(elem: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a simplified shape node to full Excalidraw elements (shape + bound text)."""
    result = []
    shape_id = elem.get("id") or _generate_id()
    x = int(elem.get("x", 0))
    y = int(elem.get("y", 0))
    width = int(elem.get("width", elem.get("w", 160)))
    height = int(elem.get("height", elem.get("h", 60)))
    text = (elem.get("text") or "").strip()

    shape = {
        **_default_fields(),
        "id": shape_id,
        "type": elem.get("type", "rectangle"),
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "strokeColor": _resolve_color(elem.get("strokeColor"), "#1e1e1e"),
        "backgroundColor": _resolve_color(elem.get("backgroundColor"), "transparent"),
    }

    # Roundness for non-rectangular shapes
    if shape["type"] == "ellipse":
        shape["roundness"] = {"type": 2}
    elif shape["type"] == "diamond":
        shape["roundness"] = {"type": 3}

    # If there's text, create a bound text element
    if text:
        text_id = _generate_id()
        text_size = _estimate_text_size(text, 20)
        text_width = min(text_size["width"], width - 10)
        text_height = min(text_size["height"], height - 10)

        text_elem = {
            **_default_fields(),
            "id": text_id,
            "type": "text",
            "x": x + (width - text_width) / 2,
            "y": y + (height - text_height) / 2,
            "width": text_width,
            "height": text_height,
            "text": text,
            "fontSize": 20,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": 18,
            "containerId": shape_id,
            "originalText": text,
            "lineHeight": 1.25,
        }
        shape["boundElements"] = [{"type": "text", "id": text_id}]
        result.append(shape)
        result.append(text_elem)
    else:
        result.append(shape)

    return result


def _convert_arrow(
    elem: Dict[str, Any],
    element_bounds: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """Convert a simplified arrow to a full Excalidraw arrow element."""
    arrow_id = elem.get("id") or _generate_id()
    text = (elem.get("text") or "").strip()
    start_binding = elem.get("startBinding")
    end_binding = elem.get("endBinding")
    start_id = _binding_id(start_binding)
    end_id = _binding_id(end_binding)

    if (
        "points" not in elem
        and start_id
        and end_id
        and element_bounds
        and start_id in element_bounds
        and end_id in element_bounds
    ):
        start, end = _connection_points(element_bounds[start_id], element_bounds[end_id])
        x = start[0]
        y = start[1]
        width = end[0] - start[0]
        height = end[1] - start[1]
        points = [[0, 0], [width, height]]
    else:
        x = float(elem.get("x", 0))
        y = float(elem.get("y", 0))
        width = float(elem.get("width", elem.get("w", 100)))
        height = float(elem.get("height", elem.get("h", 0)))
        points = elem.get("points", [[0, 0], [width, height]])

    arrow = {
        **_default_fields(),
        "id": arrow_id,
        "type": "arrow",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "points": points,
        "startArrowhead": None,
        "endArrowhead": "arrow",
    }

    if start_binding and isinstance(start_binding, dict):
        arrow["startBinding"] = {
            "elementId": start_binding.get("elementId", ""),
            "focus": start_binding.get("focus", 0),
            "gap": start_binding.get("gap", 4),
        }
    if end_binding and isinstance(end_binding, dict):
        arrow["endBinding"] = {
            "elementId": end_binding.get("elementId", ""),
            "focus": end_binding.get("focus", 0),
            "gap": end_binding.get("gap", 4),
        }

    result = [arrow]

    # Edge label as free-floating text near midpoint
    if text:
        mid_x = x + width / 2
        mid_y = y + height / 2 - 10
        label_size = _estimate_text_size(text, 16)
        label_id = _generate_id()
        label_elem = {
            **_default_fields(),
            "id": label_id,
            "type": "text",
            "x": mid_x - label_size["width"] / 2,
            "y": mid_y,
            "width": label_size["width"],
            "height": label_size["height"],
            "text": text,
            "fontSize": 16,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": 14,
            "originalText": text,
            "lineHeight": 1.25,
            "backgroundColor": "#ffffff",
            "fillStyle": "solid",
        }
        result.append(label_elem)

    return result


def _convert_free_text(elem: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a simplified free text element."""
    text_id = elem.get("id") or _generate_id()
    text = (elem.get("text") or "").strip()
    x = int(elem.get("x", 0))
    y = int(elem.get("y", 0))
    font_size = int(elem.get("fontSize", 20))
    text_size = _estimate_text_size(text, font_size)
    width = int(elem.get("width", elem.get("w", text_size["width"])))
    height = int(elem.get("height", elem.get("h", text_size["height"])))

    return [{
        **_default_fields(),
        "id": text_id,
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "fontSize": font_size,
        "fontFamily": 1,
        "textAlign": elem.get("textAlign", "left"),
        "verticalAlign": elem.get("verticalAlign", "top"),
        "baseline": int(font_size * 0.9),
        "originalText": text,
        "lineHeight": 1.25,
    }]


def _zorder_rank(elem: Dict[str, Any]) -> int:
    elem_type = elem.get("type")
    if elem_type == "text":
        return 30
    if elem_type == "arrow":
        return 20

    has_bound_text = bool(elem.get("boundElements"))
    has_fill = elem.get("backgroundColor") not in (None, "", "transparent")
    if has_fill and not has_bound_text:
        return 0
    return 10


class ExcalidrawDirectCodeConverter:
    """Convert simplified LLM-generated element JSON to a complete Excalidraw scene."""

    def __init__(self):
        pass

    def convert(self, simplified_output: Dict[str, Any]) -> Dict[str, Any]:
        """Convert simplified JSON to complete Excalidraw scene."""
        elements = []
        raw_elements = simplified_output.get("elements", [])

        if not isinstance(raw_elements, list):
            raise ValueError("Input must contain an 'elements' array")

        element_bounds = {
            elem["id"]: _get_bounds(elem)
            for elem in raw_elements
            if isinstance(elem, dict)
            and elem.get("id")
            and elem.get("type", "rectangle") != "arrow"
        }

        for elem in raw_elements:
            elem_type = elem.get("type", "")
            if elem_type in ("rectangle", "diamond", "ellipse"):
                elements.extend(_convert_shape(elem))
            elif elem_type == "arrow":
                elements.extend(_convert_arrow(elem, element_bounds))
            elif elem_type == "text":
                elements.extend(_convert_free_text(elem))
            else:
                # Unknown type — try shape fallback
                elements.extend(_convert_shape(elem))

        elements.sort(key=_zorder_rank)

        # Re-assign indices for z-order
        for idx, elem in enumerate(elements):
            elem["index"] = f"a{idx:04d}"

        return {
            "type": "excalidraw",
            "version": 2,
            "source": "https://excalidraw.com",
            "elements": elements,
            "appState": {
                "gridSize": 20,
                "gridStep": 5,
                "gridModeEnabled": False,
                "viewBackgroundColor": "#ffffff",
            },
            "files": {},
        }
