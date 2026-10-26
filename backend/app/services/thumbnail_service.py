"""Thumbnail generation service.

Generates a lightweight SVG thumbnail from a diagram schema_blob and stores it
as a data URI on the Project record. No external storage is required.
"""
from __future__ import annotations

import base64
import html
import re
from typing import Any

from app.services.diagram_schema_inspection import (
    CONNECTOR_COLLECTION_KEYS,
    NODE_COLLECTION_KEYS,
    TL_DRAW_ARROW_TYPES,
    first_schema_collection,
)

_DEFAULT_FILLS = [
    "#dbeafe", "#e0e7ff", "#fce7f3", "#dcfce7", "#fef9c3", "#ffe4e6",
]
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_W, _H = 400, 300


class ThumbnailGenerationError(RuntimeError):
    """Raised when thumbnail rendering fails for an otherwise saved diagram."""


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalise_elements(schema_blob: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a flat list of node-like dicts regardless of canvas format."""
    return first_schema_collection(schema_blob, NODE_COLLECTION_KEYS)


def _normalise_connectors(schema_blob: dict[str, Any]) -> list[dict[str, Any]]:
    return first_schema_collection(schema_blob, CONNECTOR_COLLECTION_KEYS)


def _is_arrow(el: dict[str, Any]) -> bool:
    t = str(el.get("type", "")).lower()
    return t in TL_DRAW_ARROW_TYPES


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_label(el: dict[str, Any]) -> str:
    """Extract display text from various schema formats."""
    # Excalidraw
    if "text" in el and el["text"]:
        return str(el["text"])
    props = el.get("props")
    if isinstance(props, dict):
        for key in ("text", "label", "name", "title"):
            if props.get(key):
                return str(props[key])
    # Generic label / name fields
    for key in ("label", "name", "title", "content"):
        if el.get(key):
            return str(el[key])
    # Nested label objects  { label: { text: "..." } }
    label_obj = el.get("label")
    if isinstance(label_obj, dict):
        for k in ("text", "value", "content"):
            if label_obj.get(k):
                return str(label_obj[k])
    return ""


def _get_geometry(el: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Return (x, y, w, h) or None."""
    if all(k in el for k in ("x", "y", "width", "height")):
        geometry = (
            _parse_float(el["x"]),
            _parse_float(el["y"]),
            _parse_float(el["width"]),
            _parse_float(el["height"]),
        )
        return _valid_geometry(geometry)

    props = el.get("props")
    if "x" in el and "y" in el and isinstance(props, dict):
        geometry = (
            _parse_float(el["x"]),
            _parse_float(el["y"]),
            _parse_float(props.get("w", props.get("width"))),
            _parse_float(props.get("h", props.get("height"))),
        )
        return _valid_geometry(geometry)

    geo = el.get("geometry") or el.get("position") or el.get("bounds")
    if isinstance(geo, dict):
        geometry = (
            _parse_float(geo.get("x", geo.get("left", 0))),
            _parse_float(geo.get("y", geo.get("top", 0))),
            _parse_float(geo.get("width", geo.get("w", 80))),
            _parse_float(geo.get("height", geo.get("h", 40))),
        )
        return _valid_geometry(geometry)
    return None


def _valid_geometry(
    geometry: tuple[float | None, float | None, float | None, float | None],
) -> tuple[float, float, float, float] | None:
    x, y, w, h = geometry
    if x is None or y is None or w is None or h is None:
        return None
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def _get_fill(el: dict[str, Any], index: int) -> str:
    for key in ("backgroundColor", "fill", "fillColor", "background"):
        val = el.get(key)
        if isinstance(val, str):
            color = val.strip()
            if _HEX_COLOR_RE.fullmatch(color):
                return color
    return _DEFAULT_FILLS[index % len(_DEFAULT_FILLS)]


def generate_svg_thumbnail(
    schema_blob: dict[str, Any],
    canvas_engine: str = "excalidraw",
) -> str:
    """Render schema_blob as a compact SVG data URI."""
    try:
        return _render(schema_blob, canvas_engine)
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ThumbnailGenerationError("thumbnail render failed") from exc


def _render(schema_blob: dict[str, Any], canvas_engine: str) -> str:
    elements = _normalise_elements(schema_blob)
    connectors = _normalise_connectors(schema_blob)

    # Separate node-like elements from arrows embedded in the elements list
    nodes = [e for e in elements if not _is_arrow(e)]
    arrows = [e for e in elements if _is_arrow(e)] + connectors

    if not nodes:
        return _empty_svg()

    # The element travels with its geometry: nodes without valid geometry are
    # dropped here, so positional lookups back into `nodes` would be off by one.
    geometries: list[tuple[str, float, float, float, float, dict[str, Any]]] = []
    for el in nodes:
        geo = _get_geometry(el)
        if geo:
            x, y, w, h = geo
            eid = str(el.get("id", ""))
            geometries.append((eid, x, y, w, h, el))

    if not geometries:
        return _empty_svg()

    min_x = min(g[1] for g in geometries)
    min_y = min(g[2] for g in geometries)
    max_x = max(g[1] + g[3] for g in geometries)
    max_y = max(g[2] + g[4] for g in geometries)

    src_w = max(max_x - min_x, 1.0)
    src_h = max(max_y - min_y, 1.0)

    pad = 12
    scale = min((_W - 2 * pad) / src_w, (_H - 2 * pad) / src_h)

    def tx(x: float) -> float:
        return (x - min_x) * scale + pad

    def ty(y: float) -> float:
        return (y - min_y) * scale + pad

    id_to_centre: dict[str, tuple[float, float]] = {}
    for eid, x, y, w, h, _el in geometries:
        if eid:
            id_to_centre[eid] = (tx(x + w / 2), ty(y + h / 2))

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}" '
        f'viewBox="0 0 {_W} {_H}">'
        '<defs>'
        '<marker id="ah" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">'
        '<path d="M0,0 L6,3 L0,6 Z" fill="#94a3b8"/>'
        '</marker>'
        '</defs>'
        f'<rect width="{_W}" height="{_H}" fill="#f8fafc" rx="8"/>'
    ]

    for arrow in arrows:
        start_id = _get_arrow_endpoint_id(arrow, "start")
        end_id = _get_arrow_endpoint_id(arrow, "end")
        sc = id_to_centre.get(start_id)
        ec = id_to_centre.get(end_id)
        if sc and ec:
            parts.append(
                f'<line x1="{sc[0]:.1f}" y1="{sc[1]:.1f}" '
                f'x2="{ec[0]:.1f}" y2="{ec[1]:.1f}" '
                'stroke="#94a3b8" stroke-width="1.2" '
                'marker-end="url(#ah)" opacity="0.7"/>'
            )

    font_size = _clamp(scale * 12, 7, 13)
    for idx, (eid, x, y, w, h, el) in enumerate(geometries):
        sx, sy = tx(x), ty(y)
        sw, sh = w * scale, h * scale
        fill = _get_fill(el, idx)
        label = _get_label(el)

        parts.append(
            f'<rect x="{sx:.1f}" y="{sy:.1f}" width="{sw:.1f}" height="{sh:.1f}" '
            f'rx="4" fill="{fill}" stroke="#cbd5e1" stroke-width="0.8"/>'
        )

        if label:
            cx = sx + sw / 2
            cy = sy + sh / 2
            max_chars = max(4, int(sw / (font_size * 0.6)))
            display = label if len(label) <= max_chars else label[: max_chars - 1] + "\u2026"
            parts.append(
                f'<text x="{cx:.1f}" y="{cy:.1f}" '
                f'font-size="{font_size:.1f}" font-family="system-ui,sans-serif" '
                'fill="#334155" text-anchor="middle" dominant-baseline="middle" '
                f'font-weight="500">{html.escape(display)}</text>'
            )

    parts.append("</svg>")
    return _svg_data_uri("".join(parts))


def _get_arrow_endpoint_id(arrow: dict[str, Any], endpoint: str) -> str:
    binding_key = "startBinding" if endpoint == "start" else "endBinding"
    node_keys = (
        ("source", "from", "startNodeId")
        if endpoint == "start"
        else ("target", "to", "endNodeId")
    )

    binding = arrow.get(binding_key)
    if isinstance(binding, dict) and binding.get("elementId"):
        return str(binding["elementId"])

    props = arrow.get("props")
    terminal = props.get(endpoint) if isinstance(props, dict) else None
    if isinstance(terminal, dict) and terminal.get("boundShapeId"):
        return str(terminal["boundShapeId"])

    for key in node_keys:
        if arrow.get(key):
            return str(arrow[key])
    return ""


def _empty_svg() -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}">'
        f'<rect width="{_W}" height="{_H}" fill="#f1f5f9" rx="8"/>'
        f'<text x="{_W//2}" y="{_H//2}" font-size="13" font-family="system-ui,sans-serif" '
        f'fill="#94a3b8" text-anchor="middle" dominant-baseline="middle">No preview</text>'
        "</svg>"
    )
    return _svg_data_uri(svg)


def _svg_data_uri(svg: str) -> str:
    b64 = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"
