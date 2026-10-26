#!/usr/bin/env python3
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, Tuple

# Determine project root relative to this script
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Default Input: resources/icons/material-design-icons/filled
DEFAULT_INPUT_DIR = os.path.join(
    PROJECT_ROOT,
    "resources", "icons", "material-design-icons", "filled"
)

# Default Output: resources/icons/material-design-icons
DEFAULT_OUTPUT_DIR = os.path.join(
    PROJECT_ROOT,
    "resources", "icons", "material-design-icons"
)

COLOR_MAP = [
    ("black", "#1d1d1d"),
    ("grey", "#737373"),
    ("light_violet", "#9e86c8"),
    ("violet", "#5b2245"),
    ("blue", "#2f80ed"),
    ("light_blue", "#56ccf2"),
    ("yellow", "#ffc114"),
    ("orange", "#f2994a"),
    ("green", "#27ae60"),
    ("light_green", "#6fcf97"),
    ("light_red", "#ff8f8f"),
    ("red", "#eb5757"),
]

STYLE_FILL_RE = re.compile(r"(^|;)\s*fill\s*:\s*([^;]+)", re.IGNORECASE)
STYLE_STROKE_RE = re.compile(r"(^|;)\s*stroke\s*:\s*([^;]+)", re.IGNORECASE)


FILL_TAGS = {"path", "rect", "circle", "ellipse", "polygon"}
STROKE_TAGS = {"line", "polyline"}


def _should_replace(value: str) -> bool:
    v = value.strip().lower()
    return v not in {"none", "transparent"}


def _replace_style(style: str, color: str) -> str:
    def _sub_fill(match: re.Match) -> str:
        prefix, val = match.group(1), match.group(2)
        return f"{prefix}fill:{color}" if _should_replace(val) else match.group(0)

    def _sub_stroke(match: re.Match) -> str:
        prefix, val = match.group(1), match.group(2)
        return f"{prefix}stroke:{color}" if _should_replace(val) else match.group(0)

    style = STYLE_FILL_RE.sub(_sub_fill, style)
    style = STYLE_STROKE_RE.sub(_sub_stroke, style)
    return style


def _apply_color(svg_path: str, out_path: str, color: str) -> None:
    try:
        tree = ET.parse(svg_path)
    except ET.ParseError:
        # Fallback: copy raw content if parse fails
        with open(svg_path, "rb") as f_in, open(out_path, "wb") as f_out:
            f_out.write(f_in.read())
        return

    root = tree.getroot()
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]

        fill = elem.get("fill")
        if fill is not None:
            if _should_replace(fill):
                elem.set("fill", color)
        elif tag in FILL_TAGS:
            elem.set("fill", color)

        stroke = elem.get("stroke")
        if stroke is not None:
            if _should_replace(stroke):
                elem.set("stroke", color)
        elif tag in STROKE_TAGS:
            elem.set("stroke", color)

        style = elem.get("style")
        if style:
            elem.set("style", _replace_style(style, color))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=False)


def _iter_svg_files(src_dir: str) -> Iterable[str]:
    for root, _, files in os.walk(src_dir):
        for name in files:
            if name.lower().endswith(".svg"):
                yield os.path.join(root, name)


def _relative_path(path: str, base: str) -> str:
    return os.path.relpath(path, base)


def _ensure_output_dir(base_out: str, color_key: str) -> str:
    out_dir = os.path.join(base_out, color_key)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _colorize_all(src_dir: str, base_out: str, colors: Iterable[Tuple[str, str]]) -> Dict[str, int]:
    results: Dict[str, int] = {}
    svg_files = list(_iter_svg_files(src_dir))

    for key, hex_color in colors:
        count = 0
        out_dir = _ensure_output_dir(base_out, key)
        for svg_file in svg_files:
            rel = _relative_path(svg_file, src_dir)
            out_path = os.path.join(out_dir, rel)
            _apply_color(svg_file, out_path, hex_color)
            count += 1
        results[key] = count

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch recolor Material Icons SVGs into folders by color.")
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help=f"Source SVG directory (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output base directory (default: {DEFAULT_OUTPUT_DIR})",
    )

    args = parser.parse_args()
    if not os.path.isdir(args.input_dir):
        print(f"Source dir not found: {args.input_dir}", file=sys.stderr)
        return 1

    results = _colorize_all(args.input_dir, args.output_dir, COLOR_MAP)
    for key, count in results.items():
        print(f"{key}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
