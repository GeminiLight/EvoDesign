# -*- coding: utf-8 -*-
"""
Excalidraw Converter - Convert layout_instantiation to Excalidraw scene format.

Pure Python logic implementation (no LLM calls).
Counterpart of code_tool.py (InstantiationToTldrawConverter) for the Excalidraw canvas library.
"""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from evo_diagram.agentic_system.common.icon_assets import (
    icon_filename,
    require_icon_svg_path,
)
from evo_diagram.agentic_system.common.layout_contract import validate_layout_instantiation
from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    TITLE_SUFFIX,
    companion_base_id,
    companion_id,
)

# Size mapping (same as TLDraw converter)
SIZE_DICT = {
    "s": 36,
    "m": 48,
    "l": 58,
    "xl": 65.2,
}

# Approximate character width per font size unit (for estimating text dimensions)
_CHAR_WIDTH_FACTOR = 0.6
_STABLE_EXCALIDRAW_UPDATED_MS = 1


def _stable_payload(value: Any) -> str:
    """Serialize a value for deterministic hashes."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return repr(value)


def _stable_digest(namespace: str, value: Any) -> str:
    payload = f"{namespace}:{_stable_payload(value)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _generate_excalidraw_id(seed: Any) -> str:
    """Generate a stable Excalidraw-compatible ID from semantic input."""
    return _stable_digest("excalidraw-id", seed)[:20]


def _stable_seed(seed: Any) -> int:
    value = int(_stable_digest("excalidraw-seed", seed)[:12], 16)
    return (value % 2_000_000_000) + 1


def _excalidraw_defaults(seed: Any) -> Dict[str, Any]:
    """Return the standard boilerplate fields every Excalidraw element needs."""
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
        "seed": _stable_seed(["seed", seed]),
        "version": 2,
        "versionNonce": _stable_seed(["versionNonce", seed]),
        "isDeleted": False,
        "boundElements": [],
        "updated": _STABLE_EXCALIDRAW_UPDATED_MS,
        "link": None,
        "locked": False,
    }


def _estimate_text_dimensions(text: str, font_size: int) -> Dict[str, float]:
    """Estimate text width/height based on character count and font size."""
    lines = text.split("\n") if text else [""]
    max_line_len = max(len(line) for line in lines)
    width = max_line_len * font_size * _CHAR_WIDTH_FACTOR
    height = len(lines) * font_size * 1.25  # lineHeight = 1.25
    return {"width": max(width, 10), "height": max(height, font_size * 1.25)}


def _resolve_numeric_dimension(*values: Any, default: float) -> float:
    """Return the first positive numeric dimension value, otherwise the default."""
    for value in values:
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return float(default)


def _resolve_element_dimensions(
    element_data: Dict[str, Any],
    *,
    default_width: float,
    default_height: float,
) -> Tuple[float, float]:
    """Resolve width/height from Excalidraw or layout-style w/h fields."""
    props = element_data.get("props", {})
    if not isinstance(props, dict):
        props = {}

    width = _resolve_numeric_dimension(
        element_data.get("width"),
        element_data.get("w"),
        props.get("w"),
        default=default_width,
    )
    height = _resolve_numeric_dimension(
        element_data.get("height"),
        element_data.get("h"),
        props.get("h"),
        default=default_height,
    )
    return width, height


def _extract_icon_url(icon_data: Dict[str, Any]) -> str:
    """Extract icon URL from current and persisted icon asset shapes."""
    icon_url = icon_data.get("src", "")
    if icon_url:
        return icon_url
    props = icon_data.get("props", {})
    if isinstance(props, dict):
        return props.get("url", "") or props.get("src", "")
    return ""


def _extract_icon_filename(icon_data: Dict[str, Any], icon_url: str) -> str:
    filename = icon_url.split("/")[-1] if icon_url else ""
    if filename.endswith(".svg"):
        return filename

    props = icon_data.get("props", {})
    if isinstance(props, dict):
        icon_name = props.get("icon")
        if isinstance(icon_name, str) and icon_name.strip():
            return icon_filename(icon_name.strip())
    return ""


def _extract_icon_dimension(icon_data: Dict[str, Any]) -> float:
    """Resolve icon dimension from size or explicit width/height."""
    icon_size = icon_data.get("size")
    if icon_size in SIZE_DICT:
        return SIZE_DICT[icon_size]
    props = icon_data.get("props", {})
    if isinstance(props, dict):
        w = props.get("w")
        h = props.get("h")
        if isinstance(w, (int, float)) and isinstance(h, (int, float)):
            return min(w, h)
        if isinstance(w, (int, float)):
            return w
        if isinstance(h, (int, float)):
            return h
    return 48


def _read_svg_as_data_uri(svg_path: Path) -> str:
    """Read an SVG file and return it as a data URI string."""
    raw = svg_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _svg_text_to_data_uri(svg_text: str) -> str:
    """Convert inline SVG text into a base64 data URI string."""
    b64 = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _icon_to_data_url(
    icon_data: Dict[str, Any],
    *,
    element_id: Optional[str] = None,
) -> str:
    """Resolve icon data into a base64 data URL string."""
    icon_url = _extract_icon_url(icon_data)

    if icon_url.startswith("data:image/"):
        return icon_url

    if icon_url.lstrip().startswith("<svg"):
        return _svg_text_to_data_uri(icon_url)

    props = icon_data.get("props", {})
    icon_color = props.get("color") if isinstance(props, dict) else None
    filename = _extract_icon_filename(icon_data, icon_url)
    svg_path = require_icon_svg_path(
        filename,
        icon_color=icon_color,
        icon_url=icon_url,
        element_id=element_id,
    )
    return _read_svg_as_data_uri(svg_path)

from ..shared.edge_routing import is_layout_edge_entry
from ..shared.normalization import (
    LAYER_GROUP_FRAME,
    base_id,
    is_group_frame,
    layer_for,
)


class InstantiationToExcalidrawConverter:
    """Convert layout_instantiation (with positions) to Excalidraw scene format."""

    def __init__(
        self,
        layout_instantiation: Dict[str, Any],
        structure_instantiation: Optional[Dict[str, Any]] = None,
    ):
        self.layout_instantiation = layout_instantiation
        self.structure_instantiation = structure_instantiation or {}
        self.id_map: Dict[str, str] = {}  # semantic ID -> excalidraw ID
        self._index_counter = 0
        # Pre-build a label lookup from structure for O(1) fallback.
        self._structure_labels: Dict[str, str] = {}
        for node in self.structure_instantiation.get("nodes") or []:
            if isinstance(node, dict) and node.get("id") and node.get("label"):
                self._structure_labels[str(node["id"])] = node["label"]
        for group in self.structure_instantiation.get("groups") or []:
            if isinstance(group, dict) and group.get("id") and group.get("label"):
                self._structure_labels[str(group["id"])] = group["label"]
        for edge in self.structure_instantiation.get("edges") or []:
            if isinstance(edge, dict) and edge.get("id") and edge.get("label"):
                self._structure_labels[str(edge["id"])] = edge["label"]

    def _next_index(self) -> str:
        # Zero-pad so lexicographic comparison matches numeric intent.
        # Excalidraw sorts elements by ``index`` using string comparison
        # (fractional indexing), so ``a10`` would lex-sort BEFORE ``a2``
        # without padding — breaking z-order whenever a diagram has >9
        # elements of the same layer. 5 digits supports 100k elements,
        # well above any realistic diagram size.
        idx = f"a{self._index_counter:05d}"
        self._index_counter += 1
        return idx

    def _make_id(self, semantic_id: str) -> str:
        """Create or retrieve an Excalidraw ID for a semantic ID."""
        if semantic_id not in self.id_map:
            self.id_map[semantic_id] = _generate_excalidraw_id(["semantic", semantic_id])
        return self.id_map[semantic_id]

    def _lookup_label(self, semantic_id: str, element_data: Dict[str, Any]) -> str:
        """Resolve label text: layout_instantiation first, structure fallback."""
        # 1. Check layout_instantiation (label.text / props.text / top-level text)
        label_data = element_data.get("label", {})
        if isinstance(label_data, dict) and label_data.get("text"):
            return label_data["text"]
        props = element_data.get("props", {})
        if isinstance(props, dict) and props.get("text"):
            return props["text"]
        if element_data.get("text"):
            return element_data["text"]
        # 2. Fallback to structure_instantiation
        return self._structure_labels.get(semantic_id, "")

    def _position_icon_in_node(self, icon_data: Dict[str, Any], node_data: Dict[str, Any]) -> Dict[str, float]:
        """Compute icon position inside a node, left-aligned and vertically centered."""
        node_x = node_data.get("x", 0)
        node_y = node_data.get("y", 0)
        node_w, node_h = _resolve_element_dimensions(
            node_data,
            default_width=186,
            default_height=62,
        )

        base_dim = _extract_icon_dimension(icon_data)
        target_dim = node_h * 0.6
        max_dim = node_h * 0.8
        icon_dim = max(base_dim, target_dim)
        icon_dim = min(icon_dim, max_dim)

        padding = 16
        icon_x = node_x + padding
        icon_y = node_y + max(0, (node_h - icon_dim) / 2)

        return {"x": icon_x, "y": icon_y, "dim": icon_dim}

    def _create_shape_element(
        self,
        semantic_id: str,
        element_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create an Excalidraw shape element.

        Excalidraw natively supports only: rectangle, ellipse, diamond, triangle.
        All other geo values (pentagon, hexagon, octagon, star, cloud, arrow*, etc.)
        are rendered as rectangle — this is Excalidraw's native behavior, not a fallback.
        """
        eid = self._make_id(semantic_id)

        elem_type = element_data.get("type") or element_data.get("shape") or "rectangle"

        # Handle TLDraw-style geo field
        if elem_type == "geo":
            props = element_data.get("props", {})
            geo = props.get("geo", "rectangle")
            # Excalidraw supports exactly 4 native shapes
            geo_to_excalidraw = {
                "rectangle": "rectangle",
                "ellipse": "ellipse",
                "diamond": "diamond",
                "triangle": "triangle",
                # All others → rectangle (Excalidraw's actual behavior)
                "pentagon": "rectangle",
                "hexagon": "rectangle",
                "octagon": "rectangle",
                "star": "rectangle",
                "cloud": "rectangle",
                "arrowLeft": "rectangle",
                "arrowRight": "rectangle",
                "arrowUp": "rectangle",
                "arrowDown": "rectangle",
            }
            elem_type = geo_to_excalidraw.get(geo, "rectangle")

        x = element_data.get("x", 0)
        y = element_data.get("y", 0)
        width, height = _resolve_element_dimensions(
            element_data,
            default_width=186,
            default_height=62,
        )

        shape = {
            **_excalidraw_defaults(["shape", semantic_id]),
            "id": eid,
            "type": elem_type,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "index": self._next_index(),
        }

        # Apply Excalidraw-native styling if present
        for key in ("strokeColor", "backgroundColor", "fillStyle", "strokeWidth",
                     "strokeStyle", "roughness", "opacity", "roundness"):
            if key in element_data:
                shape[key] = element_data[key]

        # Accept TLDraw-style props at this renderer boundary.
        props = element_data.get("props", {})
        if isinstance(props, dict):
            if "color" in props and "strokeColor" not in element_data:
                shape["strokeColor"] = props["color"]
            if "fill" in props and "fillStyle" not in element_data:
                fill_map = {"none": "solid", "solid": "solid", "pattern": "cross-hatch"}
                shape["fillStyle"] = fill_map.get(props["fill"], "solid")
                if props["fill"] == "none":
                    shape["backgroundColor"] = "transparent"
                elif props["fill"] == "semi":
                    # TLDraw "semi" = semi-transparent solid fill.
                    # In Excalidraw: keep fillStyle=solid (not hachure),
                    # reduce opacity to simulate transparency.
                    shape["fillStyle"] = "solid"
                    shape["opacity"] = 60

        # Safety cap: group frame / lane backgrounds should never be fully
        # opaque, or they will completely obscure actors / nested nodes.
        # Cap at 40 so even if the LLM emits opacity=100, lanes remain
        # translucent and actors stay visible through them.
        if is_group_frame(semantic_id, element_data):
            current_opacity = shape.get("opacity", 100)
            if current_opacity >= 40:
                shape["opacity"] = 40

        return shape

    def _create_standalone_text_element(
        self,
        semantic_id: str,
        element_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a standalone Excalidraw text element (not bound to any container).

        Used for group titles and other free-standing text. Resolves text and
        font attributes via a three-tier fallback (label.* > props.* > top-level)
        so the styling stage can emit {"type":"text","label":{"text":"Marketing"}}
        without the title going blank in the rendered scene.
        """
        eid = self._make_id(semantic_id)

        label_data = element_data.get("label", {})
        if not isinstance(label_data, dict):
            label_data = {}
        props = element_data.get("props", {})
        if not isinstance(props, dict):
            props = {}

        text = self._lookup_label(semantic_id, element_data)
        font_size = (
            label_data.get("fontSize")
            or props.get("fontSize")
            or element_data.get("fontSize", 20)
        )
        font_family = (
            label_data.get("fontFamily")
            or props.get("fontFamily")
            or element_data.get("fontFamily", 2)
        )
        text_align = (
            label_data.get("textAlign")
            or props.get("textAlign")
            or element_data.get("textAlign", "left")
        )
        vertical_align = (
            label_data.get("verticalAlign")
            or props.get("verticalAlign")
            or element_data.get("verticalAlign", "top")
        )

        x = element_data.get("x", 0)
        y = element_data.get("y", 0)

        # Estimate text dimensions if not explicitly provided
        dims = _estimate_text_dimensions(text, font_size)
        width, height = _resolve_element_dimensions(
            element_data,
            default_width=dims["width"],
            default_height=dims["height"],
        )

        text_elem = {
            **_excalidraw_defaults(["standalone_text", semantic_id]),
            "id": eid,
            "type": "text",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "index": self._next_index(),
            "text": text,
            "fontSize": font_size,
            "fontFamily": font_family,
            "textAlign": text_align,
            "verticalAlign": vertical_align,
            "containerId": None,
            "originalText": text,
            "autoResize": True,
            "lineHeight": 1.25,
        }

        # Apply stroke color if specified. Styling layer emits text color at
        # top-level ``color`` (TLDraw-style) or inside ``label.strokeColor``;
        # fall through to native ``strokeColor`` last.
        resolved_color = (
            label_data.get("strokeColor")
            or element_data.get("strokeColor")
            or element_data.get("color")
            or props.get("color")
        )
        if resolved_color:
            text_elem["strokeColor"] = resolved_color

        return text_elem

    def _create_bound_text_element(
        self,
        text: str,
        container_id: str,
        container_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a text element bound to a container shape (rectangle/diamond/arrow)."""
        text_id = _generate_excalidraw_id(["bound_text", container_id, text])

        x = container_data.get("x", 0)
        y = container_data.get("y", 0)
        container_w, container_h = _resolve_element_dimensions(
            container_data,
            default_width=186,
            default_height=62,
        )

        # Get font properties from label or props
        label_data = container_data.get("label", {})
        if not isinstance(label_data, dict):
            label_data = {}
        props = container_data.get("props", {})
        if not isinstance(props, dict):
            props = {}

        font_size = label_data.get("fontSize", props.get("fontSize", 20))
        font_family = label_data.get("fontFamily", props.get("fontFamily", 5))
        text_align = label_data.get("textAlign", props.get("textAlign", "center"))
        vertical_align = label_data.get("verticalAlign", props.get("verticalAlign", "middle"))

        # Estimate actual text dimensions (not container dimensions)
        dims = _estimate_text_dimensions(text, font_size)

        text_elem = {
            **_excalidraw_defaults(["bound_text", container_id, text]),
            "id": text_id,
            "type": "text",
            "x": x + (container_w - dims["width"]) / 2,
            "y": y + (container_h - dims["height"]) / 2,
            "width": dims["width"],
            "height": dims["height"],
            "index": self._next_index(),
            "text": text,
            "fontSize": font_size,
            "fontFamily": font_family,
            "textAlign": text_align,
            "verticalAlign": vertical_align,
            "containerId": container_id,
            "originalText": text,
            "autoResize": True,
            "lineHeight": 1.25,
        }

        # Apply text color from label or container
        label_color = (
            label_data.get("strokeColor")
            or container_data.get("labelColor")
            or props.get("labelColor")
        )
        if label_color:
            text_elem["strokeColor"] = label_color

        return text_elem

    def _create_image_element(
        self,
        semantic_id: str,
        position: Dict[str, float],
        file_id: str,
    ) -> Dict[str, Any]:
        """Create an Excalidraw image element for an icon."""
        eid = self._make_id(semantic_id)
        dim = position["dim"]

        image_elem = {
            **_excalidraw_defaults(["image", semantic_id, file_id]),
            "id": eid,
            "type": "image",
            "x": position["x"],
            "y": position["y"],
            "width": dim,
            "height": dim,
            "index": self._next_index(),
            "fileId": file_id,
            "status": "saved",
            "scale": [1, 1],
            "crop": None,
        }
        return image_elem

    def convert(self) -> Dict[str, Any]:
        """
        Convert layout_instantiation to Excalidraw clipboard format.

        Returns:
            Dict with keys: type, elements, files, _meta
        """
        if self.structure_instantiation:
            validate_layout_instantiation(
                self.layout_instantiation,
                structure_instantiation=self.structure_instantiation,
                require_complete_styling_geometry=False,
            )

        elements: List[Dict[str, Any]] = []
        files: Dict[str, Any] = {}
        edge_data: Dict[str, Any] = {}

        # Classify elements
        icon_elements: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        regular_elements: Dict[str, Dict[str, Any]] = {}

        for element_id, element_data in self.layout_instantiation.items():
            if is_layout_edge_entry(element_id, element_data):
                edge_data[element_id] = element_data
            elif element_id.endswith(ICON_SUFFIX):
                icon_base = companion_base_id(element_id) or element_id
                icon_elements[icon_base] = (element_id, element_data)
            else:
                regular_elements[element_id] = element_data

        # Group frames whose ``:title`` sibling already provides the label.
        # For these, we MUST NOT also emit an auto-generated bound-text title
        # on the frame — else each group ends up with two identical labels
        # (one centered bound text, one standalone top-left text). This is
        # the second half of the 2026-04 z-order bug: the Excalidraw
        # converter treated group rectangles the same as regular nodes.
        titled_bases = {
            base_id(eid)
            for eid in regular_elements
            if isinstance(eid, str) and eid.endswith(TITLE_SUFFIX)
        }

        # Sort by z-layer so group frames never occlude their children
        # regardless of the order the layout LLM chose. Python's sorted() is
        # stable, so same-layer elements preserve dict insertion order as a
        # natural tie-breaker.
        def _regular_layer(kv: Tuple[str, Dict[str, Any]]) -> int:
            element_id, element_data = kv
            if (
                isinstance(element_id, str)
                and not element_id.endswith(TITLE_SUFFIX)
                and base_id(element_id) in titled_bases
            ):
                return LAYER_GROUP_FRAME
            return layer_for(element_id, element_data)

        sorted_regular = sorted(
            regular_elements.items(),
            key=_regular_layer,
        )

        # Process regular elements
        for element_id, element_data in sorted_regular:
            if "type" not in element_data and "shape" not in element_data:
                continue
            # Skip arrow elements - handled by arrow adder
            if element_data.get("type") == "arrow" or element_data.get("shape") == "arrow":
                continue

            # Skip parent group elements that have :background/:title siblings
            # but no coordinates themselves. The converter would create ghost
            # rectangles at (0,0) for these. The :background and :title
            # sub-elements carry the actual geometry.
            if (
                isinstance(element_id, str)
                and not element_id.endswith(BACKGROUND_SUFFIX)
                and not element_id.endswith(TITLE_SUFFIX)
                and "x" not in element_data
                and "y" not in element_data
                and companion_id(element_id, BACKGROUND_SUFFIX) in regular_elements
            ):
                continue

            # --- Standalone text elements (e.g. group titles) ---
            if element_data.get("type") == "text" or element_data.get("shape") == "text":
                text_elem = self._create_standalone_text_element(element_id, element_data)
                elements.append(text_elem)
                continue

            # --- Shape elements (rectangle, ellipse, diamond, etc.) ---
            if (
                isinstance(element_id, str)
                and not element_id.endswith(TITLE_SUFFIX)
                and base_id(element_id) in titled_bases
            ):
                element_data = dict(element_data)
                element_data["is_group"] = True

            shape = self._create_shape_element(element_id, element_data)
            shape_eid = shape["id"]

            # Group frames with an explicit ``:title`` sibling should render
            # as a bare backdrop — the sibling already carries the visible
            # label. Skip bound-text generation so we don't stack two copies
            # of the group name on top of each other.
            frame_has_title_sibling = (
                isinstance(element_id, str) and base_id(element_id) in titled_bases
            )

            # Extract label text: layout_instantiation first, structure fallback
            text = ""
            if not frame_has_title_sibling:
                text = self._lookup_label(element_id, element_data)

            if text:
                text_elem = self._create_bound_text_element(text, shape_eid, element_data)
                shape["boundElements"] = list(shape.get("boundElements", []))
                shape["boundElements"].append({"type": "text", "id": text_elem["id"]})
                elements.append(shape)
                elements.append(text_elem)
            else:
                elements.append(shape)

            # Handle icon for this element
            icon_entry = icon_elements.get(element_id)
            if icon_entry:
                icon_element_id, icon_element_data = icon_entry
                data_url = _icon_to_data_url(
                    icon_element_data,
                    element_id=icon_element_id,
                )
                position = self._position_icon_in_node(icon_element_data, element_data)
                file_id = hashlib.md5(data_url.encode()).hexdigest()[:20]
                files[file_id] = {
                    "mimeType": "image/svg+xml",
                    "id": file_id,
                    "dataURL": data_url,
                    "created": _STABLE_EXCALIDRAW_UPDATED_MS,
                    "lastRetrieved": _STABLE_EXCALIDRAW_UPDATED_MS,
                    "status": "saved",
                }

                image_elem = self._create_image_element(
                    icon_element_id, position, file_id
                )
                elements.append(image_elem)

        return {
            "type": "excalidraw/clipboard",
            "elements": elements,
            "files": files,
            "_meta": {
                "id_map": dict(self.id_map),
                "edge_data": edge_data,
            },
        }
