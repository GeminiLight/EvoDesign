"""Anchor figure captions (axis names, stated rules) to the figure they describe.

Quadrant axis names and layer-stack rule captions are ``class: "axis"`` nodes.
The layout agent places them by eye, so they drift away from the figure and
keep whatever small font it guessed. Once the group frames are final, this
pass sizes each caption like the items it describes and places it where the
type pattern says: the horizontal axis centred below the quadrant block, the
vertical axis left of it, and rule captions right of the layer stack.
"""

from __future__ import annotations

import math
import textwrap
from statistics import median
from typing import Any, Dict, List, Mapping, Optional

from evodesign.agentic_system.common.semantic_ids import group_frame_render_id
from evodesign.agentic_system.generation_stage.layout.element_shape_estimator import (
    _estimate_text_dimensions,
)

CAPTION_TYPES = {"quadrant", "layer_stack"}
_GAP = 24.0
_STACK_GAP = 32.0
_MIN_FONT = 16
_PAD_X = 8.0
_PAD_Y = 4.0
_WRAP = 28
_HORIZONTAL = set("→←↔⟶⟵")
_VERTICAL = set("↑↓↕")


def is_caption(node: Mapping[str, Any]) -> bool:
    return str(node.get("class") or "").strip().lower() == "axis"


def _bound_text(elements: List[Dict[str, Any]], host: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    return next((e for e in elements if e.get("type") == "text" and e.get("containerId") == host.get("id")), None)


def _box(elements: List[Mapping[str, Any]]) -> Optional[Dict[str, float]]:
    if not elements:
        return None
    xs = [float(e["x"]) for e in elements] + [float(e["x"]) + float(e["width"]) for e in elements]
    ys = [float(e["y"]) for e in elements] + [float(e["y"]) + float(e["height"]) for e in elements]
    return {"left": min(xs), "top": min(ys), "right": max(xs), "bottom": max(ys)}


def _balanced_lines(raw: str) -> List[str]:
    """Wrap into as few lines as the limit allows, with lines of similar length."""
    count = math.ceil(len(raw) / _WRAP)
    for width in range(math.ceil(len(raw) / count), _WRAP + 1):
        lines = textwrap.wrap(raw, width)
        if len(lines) <= count:
            return lines
    return textwrap.wrap(raw, _WRAP)


def _resize(host: Dict[str, Any], text: Dict[str, Any], font: int, wrap: bool) -> None:
    raw = str(text.get("originalText") or text.get("text") or "")
    shown = raw
    if wrap and len(raw) > _WRAP:
        shown = "\n".join(_balanced_lines(raw))
    size = _estimate_text_dimensions(shown, font)
    text.update(fontSize=font, text=shown, originalText=raw,
                width=size["width"], height=size["height"])
    host.update(width=size["width"] + 2 * _PAD_X, height=size["height"] + 2 * _PAD_Y)


def _move(host: Dict[str, Any], text: Dict[str, Any], x: float, y: float, align: str = "center") -> None:
    """Place the caption; the text hugs the side that faces the figure."""
    host.update(x=x, y=y)
    width, text_w = float(host["width"]), float(text["width"])
    offset = {"left": _PAD_X, "right": width - text_w - _PAD_X}.get(align, (width - text_w) / 2)
    text.update(x=x + offset, y=y + (float(host["height"]) - float(text["height"])) / 2,
                textAlign=align, verticalAlign="middle")


def _is_horizontal(label: str, host: Mapping[str, Any], block: Mapping[str, float], index: int) -> bool:
    if any(ch in _HORIZONTAL for ch in label):
        return True
    if any(ch in _VERTICAL for ch in label):
        return False
    cx = float(host["x"]) + float(host["width"]) / 2
    cy = float(host["y"]) + float(host["height"]) / 2
    if cy > block["bottom"]:
        return True
    if cx < block["left"]:
        return False
    return index == 0


def place_captions(chart_type: str, structure: Mapping[str, Any],
                   elements: List[Dict[str, Any]], id_map: Mapping[str, str]) -> int:
    """Size and anchor caption nodes in place; return how many were placed."""
    if chart_type not in CAPTION_TYPES:
        return 0
    by_eid = {e.get("id"): e for e in elements}
    frames = [by_eid.get(group_frame_render_id(id_map, g.get("id")) or "")
              for g in structure.get("groups") or [] if isinstance(g, dict)]
    block = _box([f for f in frames if f])
    if block is None:
        return 0

    captions, item_fonts = [], []
    for node in structure.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        host = by_eid.get(id_map.get(str(node.get("id")), ""))
        text = _bound_text(elements, host) if host else None
        if not host or not text:
            continue
        if is_caption(node):
            captions.append((str(node.get("label") or text.get("text") or ""), host, text))
        elif text.get("fontSize"):
            item_fonts.append(float(text["fontSize"]))
    if not captions:
        return 0
    font = max(_MIN_FONT, int(median(item_fonts)) if item_fonts else _MIN_FONT)

    if chart_type == "quadrant":
        for index, (label, host, text) in enumerate(captions):
            horizontal = _is_horizontal(label, host, block, index)
            _resize(host, text, font, wrap=False)
            if horizontal:
                x = (block["left"] + block["right"] - float(host["width"])) / 2
                _move(host, text, x, block["bottom"] + _GAP)
            else:
                y = (block["top"] + block["bottom"] - float(host["height"])) / 2
                _move(host, text, block["left"] - _GAP - float(host["width"]), y, align="right")
        return len(captions)

    # layer_stack: rule captions stacked right of the bands, centred on them.
    for _, host, text in captions:
        _resize(host, text, font, wrap=True)
    total = sum(float(h["height"]) for _, h, _ in captions) + _GAP * (len(captions) - 1)
    y = (block["top"] + block["bottom"] - total) / 2
    for _, host, text in captions:
        _move(host, text, block["right"] + _STACK_GAP, y, align="left")
        y += float(host["height"]) + _GAP
    return len(captions)
