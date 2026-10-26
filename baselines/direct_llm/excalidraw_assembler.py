"""
Excalidraw assembler for the direct_llm baseline.

Converts the SIMPLIFIED JSON emitted by the LLM (see prompts_excalidraw.py)
into a complete Excalidraw scene that the project's renderer can consume.

The assembler is intentionally minimal:
- Each shape becomes one geo element + (if `text`) a bound text element.
- Each arrow becomes one arrow element with start/end bindings to the
  referenced shapes; geometry is derived from the shapes' centres.
- Arrow labels become a separate text element bound to the arrow.

Random ids/seeds are deterministic per call (`random.Random(seed=...)`)
so two runs of the same simplified JSON produce structurally identical
output (useful for diffing).
"""
from __future__ import annotations

import hashlib
import random
import time
from typing import Any, Dict, List, Optional, Tuple


_VALID_SHAPE_TYPES = {"rectangle", "ellipse", "diamond"}
_DEFAULT_STROKE = "#1e1e1e"
_DEFAULT_BG = "#ffffff"
_DEFAULT_FONT_SIZE = 20
_DEFAULT_FONT_FAMILY = 5
_LINE_HEIGHT = 1.25
_CHAR_WIDTH_FACTOR = 0.6


def _new_id(rng: random.Random) -> str:
    raw = f"{rng.random()}{time.time_ns()}".encode()
    return hashlib.md5(raw).hexdigest()[:20]


def _new_seed(rng: random.Random) -> int:
    return rng.randint(1, 2_000_000_000)


def _base_element(rng: random.Random, index: str) -> Dict[str, Any]:
    return {
        "angle": 0,
        "strokeColor": _DEFAULT_STROKE,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": index,
        "roundness": None,
        "seed": _new_seed(rng),
        "version": 2,
        "versionNonce": _new_seed(rng),
        "isDeleted": False,
        "boundElements": [],
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
    }


def _estimate_text_size(text: str, font_size: int = _DEFAULT_FONT_SIZE) -> Tuple[float, float]:
    """Return (width, height) for a text block."""
    lines = text.split("\n") if text else [""]
    longest = max((len(line) for line in lines), default=0)
    width = max(longest * font_size * _CHAR_WIDTH_FACTOR, 10.0)
    height = max(len(lines) * font_size * _LINE_HEIGHT, font_size * _LINE_HEIGHT)
    return width, height


def _bound_text(
    rng: random.Random,
    container_id: str,
    text: str,
    container_x: float,
    container_y: float,
    container_w: float,
    container_h: float,
    index: str,
) -> Dict[str, Any]:
    text_w, text_h = _estimate_text_size(text)
    text_w = min(text_w, container_w)
    base = _base_element(rng, index)
    base.update({
        "id": _new_id(rng),
        "type": "text",
        "x": container_x + (container_w - text_w) / 2,
        "y": container_y + (container_h - text_h) / 2,
        "width": text_w,
        "height": text_h,
        "text": text,
        "fontSize": _DEFAULT_FONT_SIZE,
        "fontFamily": _DEFAULT_FONT_FAMILY,
        "textAlign": "center",
        "verticalAlign": "middle",
        "containerId": container_id,
        "originalText": text,
        "autoResize": True,
        "lineHeight": _LINE_HEIGHT,
    })
    return base


def _shape_element(
    rng: random.Random,
    shape: Dict[str, Any],
    index: str,
) -> Dict[str, Any]:
    shape_type = shape.get("type", "rectangle")
    if shape_type not in _VALID_SHAPE_TYPES:
        shape_type = "rectangle"
    el = _base_element(rng, index)
    el["strokeColor"] = shape.get("strokeColor") or _DEFAULT_STROKE
    el["backgroundColor"] = shape.get("backgroundColor") or _DEFAULT_BG
    el.update({
        "id": _new_id(rng),
        "type": shape_type,
        "x": float(shape.get("x", 0)),
        "y": float(shape.get("y", 0)),
        "width": float(shape.get("width", 160)),
        "height": float(shape.get("height", 60)),
    })
    return el


def _shape_centre(el: Dict[str, Any]) -> Tuple[float, float]:
    return el["x"] + el["width"] / 2.0, el["y"] + el["height"] / 2.0


def _arrow_element(
    rng: random.Random,
    arrow: Dict[str, Any],
    src: Dict[str, Any],
    dst: Dict[str, Any],
    index: str,
) -> Dict[str, Any]:
    sx, sy = _shape_centre(src)
    ex, ey = _shape_centre(dst)
    el = _base_element(rng, index)
    el["strokeColor"] = arrow.get("strokeColor") or _DEFAULT_STROKE
    el["roundness"] = {"type": 2}
    el.update({
        "id": _new_id(rng),
        "type": "arrow",
        "x": sx,
        "y": sy,
        "width": ex - sx,
        "height": ey - sy,
        "points": [[0.0, 0.0], [ex - sx, ey - sy]],
        "startBinding": {"elementId": src["id"], "focus": 0, "gap": 1},
        "endBinding": {"elementId": dst["id"], "focus": 0, "gap": 1},
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "elbowed": False,
        "lastCommittedPoint": None,
    })
    return el


def assemble_excalidraw_scene(simplified: Dict[str, Any], seed: int = 0) -> Dict[str, Any]:
    """Expand simplified JSON into a full Excalidraw clipboard scene.

    Parameters
    ----------
    simplified:
        Dict with optional `shapes` and `arrows` lists, as emitted by the
        LLM under prompts_excalidraw.py.
    seed:
        Seed for the deterministic id/seed generator.

    Returns
    -------
    {"type": "excalidraw/clipboard", "elements": [...], "files": {}, "_meta": {...}}
    """
    rng = random.Random(seed)
    elements: List[Dict[str, Any]] = []
    shape_lookup: Dict[str, Dict[str, Any]] = {}
    index_counter = 0

    def _next_index() -> str:
        nonlocal index_counter
        s = f"a{index_counter}"
        index_counter += 1
        return s

    raw_shapes = simplified.get("shapes") or []
    for shape in raw_shapes:
        if not isinstance(shape, dict):
            continue
        sid = shape.get("id")
        if not sid:
            continue
        el = _shape_element(rng, shape, _next_index())
        elements.append(el)
        shape_lookup[sid] = el

        text = shape.get("text")
        if text:
            text_el = _bound_text(
                rng,
                container_id=el["id"],
                text=str(text),
                container_x=el["x"],
                container_y=el["y"],
                container_w=el["width"],
                container_h=el["height"],
                index=_next_index(),
            )
            el["boundElements"].append({"type": "text", "id": text_el["id"]})
            elements.append(text_el)

    raw_arrows = simplified.get("arrows") or []
    for arrow in raw_arrows:
        if not isinstance(arrow, dict):
            continue
        src = shape_lookup.get(arrow.get("from"))
        dst = shape_lookup.get(arrow.get("to"))
        if not src or not dst:
            continue
        arr_el = _arrow_element(rng, arrow, src, dst, _next_index())
        elements.append(arr_el)

        for endpoint in (src, dst):
            endpoint["boundElements"].append({"type": "arrow", "id": arr_el["id"]})

        label = arrow.get("label")
        if label:
            mid_x, mid_y = (arr_el["x"] + arr_el["width"] / 2,
                             arr_el["y"] + arr_el["height"] / 2)
            tw, th = _estimate_text_size(str(label), font_size=16)
            base = _base_element(rng, _next_index())
            base.update({
                "id": _new_id(rng),
                "type": "text",
                "x": mid_x - tw / 2,
                "y": mid_y - th / 2,
                "width": tw,
                "height": th,
                "text": str(label),
                "fontSize": 16,
                "fontFamily": _DEFAULT_FONT_FAMILY,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": arr_el["id"],
                "originalText": str(label),
                "autoResize": True,
                "lineHeight": _LINE_HEIGHT,
            })
            arr_el["boundElements"].append({"type": "text", "id": base["id"]})
            elements.append(base)

    return {
        "type": "excalidraw/clipboard",
        "elements": elements,
        "files": {},
        "_meta": {
            "source": "baselines.direct_llm.excalidraw",
            "shape_count": len(raw_shapes),
            "arrow_count": len(raw_arrows),
        },
    }
