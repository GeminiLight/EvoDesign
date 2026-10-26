"""
Element Shape Estimator

Estimates min_width and min_height for node elements based on their label text
and font size. This provides size hints to the Layout LLM so it can produce
more accurate coordinate assignments.

Padding (20px each side horizontally, 15px each side vertically) is NOT added
here — it is handled exclusively by the shape_size_fitter post-processor. This
avoids double-padding (estimator + fitter each adding their own) and keeps all
padding logic in one place.

IMPORTANT:
- Only estimates elements (nodes), NOT groups, edges, or icon entries.
- Does NOT enforce any positions or sizes — only provides hints.
- Compatible with both Excalidraw and TLDraw styling formats.
"""

import math
from copy import deepcopy
from typing import Any, Dict, Optional, Set

from evo_diagram.agentic_system.common.semantic_ids import ICON_SUFFIX, companion_id
from evo_diagram.agentic_system.common.node_icons import ICON_SIZE, ICON_PADDING, ICON_GAP

# Line height multiplier
_LINE_HEIGHT_FACTOR = 1.25
# Padding constants — kept here for reference only. All padding is handled
# by shape_size_fitter. Do NOT add these to min_width/min_height output.
_PADDING_W = 40
_PADDING_H = 30
# Icon layout constants. Icons are rendered inside the node on the left, so
# their footprint must be reflected in the text-width hint sent to the layout
# model. Boundary padding is still owned by shape_size_fitter.
_ICON_LEFT_PAD = ICON_PADDING
_ICON_TEXT_GAP = ICON_GAP
_ICON_DEFAULT_DIM = ICON_SIZE
_ICON_SIZE_TO_PX = {"s": 36, "m": 48, "l": 58, "xl": 65.2}


def _char_width_factor(text: str) -> float:
    """Character width factor per script.

    Latin baseline is ~0.6× font size. CJK glyphs render near 1.0×, so a
    single CJK code point in the label bumps the whole line to the wider
    factor — matching how a single wide glyph determines line width in
    practice and avoiding Chinese/Japanese labels being estimated too small.
    """
    if any(ord(c) > 0x2E80 for c in text):  # CJK range
        return 1.0
    return 0.6

# TLDraw size token to pixel mapping (used when styling is in TLDraw format)
_TLDRAW_SIZE_TO_PX = {"s": 24, "m": 32, "l": 48, "xl": 60}


def estimate_element_sizes(
    styling_instantiation: Dict[str, Any],
    structure_instantiation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Estimate min_width and min_height for node elements based on their label text.

    Processes semantic node ids from Structure. Groups, edges, icons, and
    metadata keys are left untouched.

    Writes 'min_width' and 'min_height' as integer pixel values into each
    qualifying node entry.

    Args:
        styling_instantiation: The styling JSON from the styling workflow.
        structure_instantiation: The structure JSON containing canonical node ids.
    Returns:
        A new dict with min_width / min_height added to node entries.
        The input dict is NOT mutated.
    """
    result = deepcopy(styling_instantiation)
    node_ids = _structure_node_ids(structure_instantiation)
    for key, value in result.items():
        # --- Only estimate nodes ---
        if not _is_node_key(key, node_ids):
            continue
        if key.endswith(ICON_SUFFIX):
            continue
        if not isinstance(value, dict):
            continue

        text = _extract_text(value)
        if not text:
            continue

        font_size = _extract_font_size(value)
        dims = _estimate_text_dimensions(text, font_size)

        icon_extra_width = 0.0
        if _has_icon_for_node(result, key):
            icon_extra_width = _estimate_icon_extra_width(result, key)

        value["min_width"] = int(math.ceil(dims["width"] + icon_extra_width))
        value["min_height"] = int(math.ceil(dims["height"]))

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _structure_node_ids(structure_instantiation: Optional[Dict[str, Any]]) -> Set[str]:
    if not isinstance(structure_instantiation, dict):
        return set()
    nodes = structure_instantiation.get("nodes")
    if not isinstance(nodes, list):
        return set()
    return {
        node["id"]
        for node in nodes
        if isinstance(node, dict)
        and isinstance(node.get("id"), str)
        and node.get("id")
    }


def _is_node_key(
    key: Any,
    node_ids: Set[str],
) -> bool:
    if not isinstance(key, str):
        return False
    if key.endswith(ICON_SUFFIX):
        return False
    return key in node_ids


def _extract_text(element_data: Dict[str, Any]) -> str:
    """Extract display text from an element, supporting multiple formats."""
    # Excalidraw: label.text
    label = element_data.get("label", {})
    if isinstance(label, dict) and label.get("text"):
        return label["text"]
    # Standalone text element
    if element_data.get("text"):
        return element_data["text"]
    # TLDraw: props.text
    props = element_data.get("props", {})
    if isinstance(props, dict) and props.get("text"):
        return props["text"]
    return ""


def _extract_font_size(element_data: Dict[str, Any]) -> int:
    """Extract font size in pixels from an element, supporting multiple formats."""
    # Excalidraw: label.fontSize
    label = element_data.get("label", {})
    if isinstance(label, dict) and "fontSize" in label:
        return label["fontSize"]
    # Top-level fontSize
    if "fontSize" in element_data:
        return element_data["fontSize"]
    # TLDraw: derive from props.size token
    props = element_data.get("props", {})
    if isinstance(props, dict):
        if "fontSize" in props:
            return props["fontSize"]
        size_token = props.get("size")
        if size_token in _TLDRAW_SIZE_TO_PX:
            return _TLDRAW_SIZE_TO_PX[size_token]
    return 16  # sensible default


def _has_icon_for_node(styling_instantiation: Dict[str, Any], key: str) -> bool:
    """Return True when a node has a canonical companion icon definition."""
    return companion_id(key, ICON_SUFFIX) in styling_instantiation


def _estimate_icon_extra_width(
    styling_instantiation: Dict[str, Any],
    key: str,
) -> float:
    """Estimate the horizontal node budget consumed by a left-aligned icon."""
    icon_data = styling_instantiation.get(companion_id(key, ICON_SUFFIX))
    if not isinstance(icon_data, dict):
        icon_data = {}

    icon_dim = _extract_icon_dimension(icon_data)
    return _ICON_LEFT_PAD + icon_dim + _ICON_TEXT_GAP


def _extract_icon_dimension(icon_data: Dict[str, Any]) -> float:
    """Resolve an icon dimension from styling data, matching converter defaults."""
    icon_size = icon_data.get("size")
    if icon_size in _ICON_SIZE_TO_PX:
        return _ICON_SIZE_TO_PX[icon_size]

    props = icon_data.get("props", {})
    if isinstance(props, dict):
        icon_size = props.get("size")
        if icon_size in _ICON_SIZE_TO_PX:
            return _ICON_SIZE_TO_PX[icon_size]
        w = props.get("w")
        h = props.get("h")
        if isinstance(w, (int, float)) and isinstance(h, (int, float)):
            return min(w, h)
        if isinstance(w, (int, float)):
            return float(w)
        if isinstance(h, (int, float)):
            return float(h)

    return _ICON_DEFAULT_DIM


def _estimate_text_dimensions(text: str, font_size: int) -> Dict[str, float]:
    """
    Estimate the rendered width and height of a text string.

    Uses a simple character-count heuristic. This is intentionally approximate —
    the Layout LLM can adjust sizes based on its own judgement.
    """
    lines = text.split("\n") if text else [""]
    max_line_len = max(len(line) for line in lines)
    width = max_line_len * font_size * _char_width_factor(text)
    height = len(lines) * font_size * _LINE_HEIGHT_FACTOR
    return {
        "width": max(width, 10),
        "height": max(height, font_size * _LINE_HEIGHT_FACTOR),
    }
