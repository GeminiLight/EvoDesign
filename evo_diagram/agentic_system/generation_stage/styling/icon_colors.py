"""Map a styling colour onto the Material icon asset colour directory.

Icon entries carry ``props.color``, but that value is **not** a render colour.
Every consumer (``icon_assets.color_to_icon_folder`` →
``/icons/material-design-icons/{color}/{icon}.svg``, the TLDraw converter's
``_apply_icon_color_url``, and the Excalidraw converter's
``require_icon_svg_path``) treats it as a *directory key*: the SVG files on disk
are pre-tinted, one directory per colour name.

``color_to_icon_folder`` resolves that key through
``TLDrawColorValidator.normalize_color``, whose enum contains colour *names*
only. On a TLDraw canvas the host node's ``props.color`` is already a name, so
the lookup works. On an Excalidraw canvas the host node's ``strokeColor`` is a
``#RRGGBB`` hex, which is not in the enum, so ``normalize_color`` returned
``"black"`` and every Excalidraw icon rendered in the black directory
regardless of its node's palette colour.

This module closes that gap inside the styling stage: a hex is mapped to the
nearest icon directory name before it is written to ``props.color``, so both
canvases store a directory key and the render side is unchanged.

Nearest-match runs in HLS rather than RGB. Plain RGB distance puts a dark navy
such as ``#003366`` closer to black than to blue, because lightness dominates
the euclidean distance; hue-first matching keeps the family and only uses
lightness to pick between a colour and its ``light-`` variant.
"""

from __future__ import annotations

import colorsys
import re
from typing import Optional

from evo_diagram.agentic_system.common.tldraw_utils import TLDrawColorValidator

_HEX_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")

# Colour directories that actually exist under
# ``tool_services/public/icons/material-design-icons/`` (see manifest.json).
# This is the TLDraw enum minus ``white``, which has no icon directory.
ICON_COLOR_NAMES = tuple(
    name for name in TLDrawColorValidator.VALID_COLORS if name != "white"
)

DEFAULT_ICON_COLOR = "black"

# Hue anchors (degrees) for the chromatic icon directories.
_HUE_ANCHORS: tuple[tuple[float, str], ...] = (
    (0.0, "red"),
    (25.0, "orange"),
    (45.0, "yellow"),
    (145.0, "green"),
    (220.0, "blue"),
    (288.0, "violet"),
)

# Families that ship a lighter directory alongside the base one.
_HAS_LIGHT_VARIANT = frozenset({"red", "green", "blue", "violet"})

# Below this saturation a colour reads as neutral, so hue is meaningless.
_NEUTRAL_SATURATION = 0.15
# Below this lightness a neutral colour is black rather than grey.
_NEUTRAL_DARK_LIGHTNESS = 0.35
# At or above this lightness a chromatic colour takes its ``light-`` variant.
_LIGHT_VARIANT_LIGHTNESS = 0.6


def is_hex_color(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX_RE.match(value.strip()))


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    digits = value.strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return tuple(int(digits[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _hue_distance(left: float, right: float) -> float:
    delta = abs(left - right) % 360.0
    return min(delta, 360.0 - delta)


def hex_to_icon_color_name(value: str) -> str:
    """Return the icon directory name closest to a ``#RRGGBB`` colour."""
    red, green, blue = _hex_to_rgb(value)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    hue_degrees = hue * 360.0

    if saturation < _NEUTRAL_SATURATION:
        return "black" if lightness < _NEUTRAL_DARK_LIGHTNESS else "grey"

    _, family = min(
        ((_hue_distance(hue_degrees, anchor), name) for anchor, name in _HUE_ANCHORS),
        key=lambda item: item[0],
    )
    if family in _HAS_LIGHT_VARIANT and lightness >= _LIGHT_VARIANT_LIGHTNESS:
        return f"light-{family}"
    return family


def resolve_icon_color_name(value: Optional[str]) -> str:
    """Normalise any styling colour into an icon asset directory name.

    Hex values are matched to the nearest directory; colour names keep going
    through the TLDraw enum so TLDraw-canvas behaviour is unchanged.
    """
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_ICON_COLOR
    if is_hex_color(value):
        return hex_to_icon_color_name(value)
    return TLDrawColorValidator.normalize_color(value)


__all__ = [
    "DEFAULT_ICON_COLOR",
    "ICON_COLOR_NAMES",
    "hex_to_icon_color_name",
    "is_hex_color",
    "resolve_icon_color_name",
]
