# -*- coding: utf-8 -*-
"""
Code Tool - Convert styling.json to Tldraw snapshot format

Pure Python logic implementation (no LLM calls)
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from evo_diagram.agentic_system.common.icon_assets import (
    format_icon_url,
    icon_filename,
    icon_name_from_filename,
    require_icon_svg_path,
)
from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    TITLE_SUFFIX,
    companion_base_id,
    companion_id,
)
from evo_diagram.agentic_system.common.tldraw_utils import (
    TLDrawIDGenerator,
    TLDrawSizeMapper,
    TLDrawColorValidator,
    TLDrawShapeValidator,
)
from evo_diagram.agentic_system.common.layout_contract import validate_layout_instantiation

from ..shared.edge_routing import is_layout_edge_entry
from ..shared.normalization import (
    LAYER_ICON,
    base_id,
    is_group_frame,
    layer_for,
)

logger = logging.getLogger(__name__)


def _has_title_sibling(element_id: str, titled_bases: set[str]) -> bool:
    return (
        isinstance(element_id, str)
        and not element_id.endswith(TITLE_SUFFIX)
        and base_id(element_id) in titled_bases
    )


def _layer_data(element_id: str, element_data: Dict[str, Any], titled_bases: set[str]) -> Dict[str, Any]:
    """Treat frames with a title sibling as group frames even without a g_ prefix."""
    if _has_title_sibling(element_id, titled_bases):
        data = dict(element_data)
        data["is_group"] = True
        return data
    return element_data


def _is_geometryless_group_shell(
    element_id: str,
    element_data: Dict[str, Any],
    regular_elements: Dict[str, Dict[str, Any]],
) -> bool:
    """Return True for group shell entries whose background sibling owns geometry.

    Structure/styling contracts allow a bare group id such as ``g_lane`` to
    carry the semantic label while ``g_lane:background`` carries the drawable
    rectangle. Rendering the shell itself would create a default-sized ghost
    rectangle because TLDraw requires geometry on every geo shape.
    """
    return (
        isinstance(element_id, str)
        and isinstance(element_data, dict)
        and not element_id.endswith((BACKGROUND_SUFFIX, TITLE_SUFFIX))
        and "x" not in element_data
        and "y" not in element_data
        and companion_id(element_id, BACKGROUND_SUFFIX) in regular_elements
    )


class InstantiationToTldrawConverter:
    """Convert layout_instantiation.json (with positions) to TLDraw snapshot format."""

    DEFAULT_X = 500
    DEFAULT_Y = 200
    DEFAULT_SPACING_X = 400
    DEFAULT_SPACING_Y = 150

    def __init__(
        self,
        layout_instantiation_json_path: str = "experiments/layout_instantiation.json",
        layout_instantiation: Dict[str, Any] | None = None,
        structure_instantiation: Dict[str, Any] | None = None,
    ):
        self.layout_instantiation_path = layout_instantiation_json_path
        self.layout_instantiation: Dict[str, Any] | None = layout_instantiation
        self.store: Dict[str, Any] = {}
        self.asset_counter = 0
        self.shape_counter = 0
        self.index_counter = 1
        self.structure_instantiation = structure_instantiation or {}
        # Pre-build label lookup from structure for fallback.
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

    def load_layout_instantiation(self) -> Dict[str, Any]:
        if self.layout_instantiation is not None:
            return self.layout_instantiation
        with open(self.layout_instantiation_path, "r", encoding="utf-8") as f:
            self.layout_instantiation = json.load(f)
        return self.layout_instantiation

    def _generate_asset_id(self, icon_url: str) -> str:
        return TLDrawIDGenerator.generate_asset_id(icon_url)

    def _generate_shape_id(self, element_id: str) -> str:
        """Map semantic ids to stable TLDraw shape ids."""
        return f"shape:{element_id}"

    def _generate_index(self) -> str:
        # Zero-pad so lexicographic string comparison matches numeric intent
        # (TLDraw also sorts by ``index`` lexicographically). Without padding
        # ``a10`` lex-sorts before ``a2`` and z-order breaks whenever a
        # diagram has >9 elements. Keep 5 digits to support 100k shapes.
        index = f"a{self.index_counter:05d}"
        self.index_counter += 1
        return index

    def _validate_geo_type(self, geo_type: str) -> str:
        """Validate and normalize geo type to a valid tldraw value."""
        return TLDrawShapeValidator.normalize_shape(geo_type)

    def _map_text_align(self, align: str) -> str:
        mapping = {
            "left": "start",
            "center": "middle",
            "right": "end",
            "start": "start",
            "middle": "middle",
            "end": "end",
        }
        return mapping.get(str(align or "").lower(), "middle")

    def _map_vertical_align(self, align: str) -> str:
        mapping = {
            "top": "start",
            "middle": "middle",
            "center": "middle",
            "bottom": "end",
            "start": "start",
            "end": "end",
        }
        return mapping.get(str(align or "").lower(), "middle")

    def _extract_shape_text(self, element_data: Dict[str, Any], props: Dict[str, Any], semantic_id: str = "") -> str:
        label_data = element_data.get("label", {})
        if isinstance(label_data, dict):
            label_text = label_data.get("text", "")
            if isinstance(label_text, str) and label_text:
                return label_text

        props_text = props.get("text", "") if isinstance(props, dict) else ""
        if isinstance(props_text, str) and props_text:
            return props_text

        top_text = element_data.get("text", "")
        if isinstance(top_text, str) and top_text:
            return top_text

        # Fallback to structure_instantiation labels
        if semantic_id:
            struct_label = self._structure_labels.get(semantic_id, "")
            if struct_label:
                return struct_label
        return ""

    def _extract_icon_filename(self, icon_data: Dict[str, Any]) -> str:
        icon_url = self._extract_icon_url(icon_data)
        filename = icon_url.split("/")[-1] if icon_url else ""
        if filename.endswith(".svg"):
            return filename
        props = icon_data.get("props", {})
        if isinstance(props, dict):
            icon_name = props.get("icon")
            if isinstance(icon_name, str) and icon_name.strip():
                return icon_filename(icon_name.strip())
        return ""

    def _extract_icon_color(self, icon_data: Dict[str, Any], node_color: str) -> str:
        props = icon_data.get("props", {})
        icon_color = props.get("color") if isinstance(props, dict) else None
        color_source = icon_color or node_color or "black"
        return TLDrawColorValidator.normalize_color(color_source)

    def _extract_icon_url(self, icon_data: Dict[str, Any]) -> str:
        """Extract icon URL from current and persisted icon asset shapes."""
        icon_url = icon_data.get("src", "")
        if icon_url:
            return icon_url
        props = icon_data.get("props", {})
        if isinstance(props, dict):
            return props.get("url", "") or props.get("src", "")
        return ""

    def _extract_icon_dimension(self, icon_data: Dict[str, Any]) -> float:
        """Resolve icon dimension from size or explicit width/height."""
        icon_size = icon_data.get("size")
        if icon_size in TLDrawSizeMapper.ICON_SIZE_MAP:
            return TLDrawSizeMapper.get_icon_size(icon_size)
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

    def _position_icon_in_node(self, icon_data: Dict[str, Any], node_data: Dict[str, Any]) -> Dict[str, Any]:
        """Place icon inside node, left-aligned with padding and vertically centered."""
        node_x = node_data.get("x", self.DEFAULT_X)
        node_y = node_data.get("y", self.DEFAULT_Y)
        node_props = node_data.get("props", {})
        if not isinstance(node_props, dict):
            node_props = {}
        # The layout contract carries geometry at the top level; ``props`` is
        # the styling-side mirror. Read props first, then fall back — same
        # order as ``_create_geo_shape``. Reading props alone made every node
        # sized at the top level fall back to the 61.7 default, so a 140px-tall
        # node got its icon pinned 7px from the top instead of centered.
        node_w = node_props.get("w", node_data.get("w", 186))
        node_h = node_props.get("h", node_data.get("h", 61.7))

        base_dim = self._extract_icon_dimension(icon_data)
        target_dim = node_h * 0.6
        max_dim = node_h * 0.8
        icon_dim = max(base_dim, target_dim)
        icon_dim = min(icon_dim, max_dim)
        props = icon_data.get("props", {})
        if not isinstance(props, dict):
            props = {}

        padding = 16
        # Never let the icon outgrow the node it sits in (degenerate wide-icon
        # / narrow-node layouts); inert for ordinary node aspect ratios.
        icon_dim = min(icon_dim, max(1.0, node_w - 2 * padding))
        icon_x = node_x + padding
        icon_y = node_y + max(0, (node_h - icon_dim) / 2)

        props["w"] = icon_dim
        props["h"] = icon_dim
        icon_data["x"] = icon_x
        icon_data["y"] = icon_y
        icon_data["props"] = props
        return icon_data

    def _apply_icon_color_url(self, icon_data: Dict[str, Any], node_color: str) -> Dict[str, Any]:
        """Apply icon color priority and rewrite URL to color directory.

        Priority: icon.props.color > node_color > black.
        """
        props = icon_data.get("props", {})
        if not isinstance(props, dict):
            props = {}

        filename = self._extract_icon_filename(icon_data)
        if not filename:
            return icon_data

        resolved_color = self._extract_icon_color(icon_data, node_color)

        from evo_diagram.config.settings import AppSettings

        new_url = format_icon_url(
            icon_name_from_filename(filename),
            resolved_color,
            AppSettings.get_default().icon_base_url,
        )

        if "src" in icon_data:
            icon_data["src"] = new_url
        props["url"] = new_url
        props["color"] = resolved_color
        icon_data["props"] = props
        return icon_data

    def _require_icon_file_exists(
        self,
        icon_data: Dict[str, Any],
        *,
        element_id: str,
    ) -> None:
        """Fail fast when an icon entry cannot be backed by a local SVG."""
        filename = self._extract_icon_filename(icon_data)
        props = icon_data.get("props", {})
        color_value = props.get("color") if isinstance(props, dict) else None
        require_icon_svg_path(
            filename,
            icon_color=color_value,
            icon_url=self._extract_icon_url(icon_data),
            element_id=element_id,
        )

    def _create_asset_entry(self, icon_data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        icon_url = self._extract_icon_url(icon_data)
        icon_dimension = self._extract_icon_dimension(icon_data)
        asset_id = self._generate_asset_id(icon_url)
        icon_name = icon_url.split("/")[-1]
        asset_entry = {
            "id": asset_id,
            "type": "image",
            "typeName": "asset",
            "props": {
                "name": icon_name,
                "src": icon_url,
                "w": icon_dimension,
                "h": icon_dimension,
                "mimeType": "image/svg+xml",
                "isAnimated": False,
            },
            "meta": {},
        }
        return asset_id, asset_entry

    def _create_geo_shape(
        self,
        element_id: str,
        element_data: Dict[str, Any],
        parent_id: str = "page:page",
    ) -> Tuple[str, Dict[str, Any]]:
        shape_id = self._generate_shape_id(element_id)
        props = element_data.get("props", {})
        if not isinstance(props, dict):
            props = {}
        label_data = element_data.get("label", {})
        if not isinstance(label_data, dict):
            label_data = {}

        shape_text = self._extract_shape_text(element_data, props, semantic_id=element_id)
        stroke_color = (
            props.get("color")
            or element_data.get("strokeColor")
            or ""
        )
        label_color = (
            props.get("labelColor")
            or label_data.get("strokeColor")
            or element_data.get("strokeColor")
            or ""
        )

        fill_style = props.get("fill")
        if not fill_style:
            fill_map = {
                "solid": "solid",
                "semi": "semi",
                "hachure": "semi",
                "cross-hatch": "pattern",
                "none": "none",
            }
            fill_style = fill_map.get(str(element_data.get("fillStyle", "")).lower(), "none")

        dash_style = props.get("dash")
        if not dash_style:
            dash_map = {
                "solid": "draw",
                "dashed": "dashed",
                "dotted": "dotted",
                "draw": "draw",
            }
            dash_style = dash_map.get(str(element_data.get("strokeStyle", "")).lower(), "draw")

        text_align = (
            props.get("align")
            or self._map_text_align(label_data.get("textAlign", ""))
            or self._map_text_align(element_data.get("textAlign", ""))
        )
        vertical_align = (
            props.get("verticalAlign")
            or self._map_vertical_align(label_data.get("verticalAlign", ""))
            or self._map_vertical_align(element_data.get("verticalAlign", ""))
        )

        x = element_data.get("x", self.DEFAULT_X)
        y = element_data.get("y", self.DEFAULT_Y)
        w = props.get("w", element_data.get("w", 186))
        h = props.get("h", element_data.get("h", 61.7))
        geo_type = props.get("geo") or element_data.get("geo") or element_data.get("type", "rectangle")
        shape_entry = {
            "x": x,
            "y": y,
            "rotation": element_data.get("rotation", 0),
            "isLocked": False,
            "opacity": element_data.get("opacity", 1),
            "meta": {},
            "id": shape_id,
            "type": "geo",
            "props": {
                "w": w,
                "h": h,
                "geo": self._validate_geo_type(geo_type),
                "color": TLDrawColorValidator.normalize_color(stroke_color),
                "labelColor": TLDrawColorValidator.normalize_color(label_color),
                "fill": fill_style,
                "dash": dash_style,
                "size": props.get("size", "m"),
                "font": props.get("font", "draw"),
                "text": shape_text,
                "align": text_align,
                "verticalAlign": vertical_align,
                "growY": 0,
                "url": "",
                "scale": 1,
            },
            "parentId": parent_id,
            "index": self._generate_index(),
            "typeName": "shape",
        }
        return shape_id, shape_entry

    def _create_text_shape(
        self,
        element_id: str,
        element_data: Dict[str, Any],
        parent_id: str = "page:page",
    ) -> Tuple[str, Dict[str, Any]]:
        """Build a native ``type: "text"`` tldraw shape.

        Standalone text (group titles, annotations) has no ``geo`` counterpart:
        routing it through ``_create_geo_shape`` produced a geo whose ``geo``
        prop normalized to ``"rectangle"``, so every group title rendered as a
        stroked box around the label. Mirrors the Excalidraw converter's
        ``_create_standalone_text_element`` branch.

        Prop set matches ``com.tldraw.shape.text`` v2 as declared in the
        snapshot schema (``color``/``size``/``font``/``align``/``w``/``text``/
        ``autoSize``/``scale``); tldraw rejects unknown props, so the layout
        height is carried in ``meta`` instead of ``props``.
        """
        shape_id = self._generate_shape_id(element_id)
        props = element_data.get("props", {})
        if not isinstance(props, dict):
            props = {}
        label_data = element_data.get("label", {})
        if not isinstance(label_data, dict):
            label_data = {}

        text = self._extract_shape_text(element_data, props, semantic_id=element_id)
        color = (
            props.get("color")
            or label_data.get("strokeColor")
            or element_data.get("strokeColor")
            or ""
        )
        text_align = (
            props.get("align")
            or self._map_text_align(label_data.get("textAlign", ""))
            or self._map_text_align(element_data.get("textAlign", ""))
        )

        w = props.get("w", element_data.get("w", 186))
        h = props.get("h", element_data.get("h", 32))

        shape_entry = {
            "x": element_data.get("x", self.DEFAULT_X),
            "y": element_data.get("y", self.DEFAULT_Y),
            "rotation": element_data.get("rotation", 0),
            "isLocked": False,
            "opacity": element_data.get("opacity", 1),
            # ``h`` is not part of the text shape schema (tldraw derives it
            # from the content) but downstream group fitting needs the
            # layout-committed height.
            "meta": {"h": h},
            "id": shape_id,
            "type": "text",
            "props": {
                "w": w,
                "color": TLDrawColorValidator.normalize_color(color),
                "size": props.get("size", "m"),
                "font": props.get("font", "draw"),
                "text": text,
                "align": text_align,
                "autoSize": bool(props.get("autoSize", True)),
                "scale": 1,
            },
            "parentId": parent_id,
            "index": self._generate_index(),
            "typeName": "shape",
        }
        return shape_id, shape_entry

    def _create_image_shape(
        self,
        element_id: str,
        asset_id: str,
        icon_element_data: Dict[str, Any],
        parent_id: str = "page:page",
    ) -> Tuple[str, Dict[str, Any]]:
        icon_dimension = self._extract_icon_dimension(icon_element_data)
        x = icon_element_data.get("x", self.DEFAULT_X)
        y = icon_element_data.get("y", self.DEFAULT_Y)
        props = icon_element_data.get("props", {})
        w = props.get("w", icon_dimension)
        h = props.get("h", icon_dimension)
        image_shape_id = self._generate_shape_id(element_id)
        icon_url = self._extract_icon_url(icon_element_data)
        icon_name = icon_url.split("/")[-1].replace(".svg", "") if icon_url else str(props.get("icon", ""))
        shape_entry = {
            "x": x,
            "y": y,
            "rotation": 0,
            "isLocked": False,
            "opacity": 1,
            "meta": {},
            "id": image_shape_id,
            "type": "image",
            "props": {
                "w": w,
                "h": h,
                "assetId": asset_id,
                "playing": True,
                "url": "",
                "crop": None,
                "flipX": False,
                "flipY": False,
                "altText": icon_name,
            },
            "parentId": parent_id,
            "typeName": "shape",
        }
        return image_shape_id, shape_entry

    def convert(self) -> Dict[str, Any]:
        if self.layout_instantiation is None:
            self.load_layout_instantiation()

        if self.structure_instantiation:
            validate_layout_instantiation(
                self.layout_instantiation,
                structure_instantiation=self.structure_instantiation,
                require_complete_styling_geometry=False,
            )

        self.store = {}

        self.store["document:document"] = {
            "gridSize": 10,
            "name": "",
            "meta": {},
            "id": "document:document",
            "typeName": "document",
        }

        self.store["page:page"] = {
            "meta": {},
            "id": "page:page",
            "name": "Page 1",
            "index": "a1",
            "typeName": "page",
        }

        self.index_counter = 2
        asset_map: Dict[str, str] = {}
        icon_elements: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        regular_elements: Dict[str, Dict[str, Any]] = {}
        edge_data: Dict[str, Any] = {}
        pending_icon_shapes: List[Tuple[str, Dict[str, Any]]] = []

        def flush_pending_icons() -> None:
            for image_shape_id, image_shape in pending_icon_shapes:
                image_shape["index"] = self._generate_index()
                self.store[image_shape_id] = image_shape
            pending_icon_shapes.clear()

        for element_id, element_data in self.layout_instantiation.items():
            if is_layout_edge_entry(element_id, element_data):
                edge_data[element_id] = element_data
            elif element_id.endswith(ICON_SUFFIX):
                icon_owner_id = companion_base_id(element_id) or element_id
                icon_elements[icon_owner_id] = (element_id, element_data)
            else:
                regular_elements[element_id] = element_data
        # Inject layout-derived edge data so arrows resolve in the same id space
        # as the rendered shapes.
        self.store["document:document"]["meta"]["edge_data"] = edge_data

        # Group frames whose ``:title`` sibling already carries the label.
        # For these we clear the geo's ``props.text`` so the frame doesn't
        # display the group name a second time (mirrors the excalidraw
        # converter's bound-text skip — see shared.normalization.base_id).
        titled_bases = {
            base_id(eid)
            for eid in regular_elements
            if isinstance(eid, str) and eid.endswith(TITLE_SUFFIX)
        }

        # Sort by z-layer so group frames paint behind their children even
        # when the layout LLM emits them last in the dict. Stable sort keeps
        # same-layer insertion order.
        sorted_regular = sorted(
            regular_elements.items(),
            key=lambda kv: layer_for(kv[0], _layer_data(kv[0], kv[1], titled_bases)),
        )

        for element_id, element_data in sorted_regular:
            if "type" not in element_data:
                continue

            # Skip arrow elements - they are handled by ArrowAdderTool
            if element_data.get("type") == "arrow":
                continue

            if _is_geometryless_group_shell(element_id, element_data, regular_elements):
                continue

            data_for_layer = _layer_data(element_id, element_data, titled_bases)
            if layer_for(element_id, data_for_layer) > LAYER_ICON:
                flush_pending_icons()

            if element_data.get("type") == "text":
                text_shape_id, text_shape = self._create_text_shape(
                    element_id,
                    data_for_layer,
                )
                self.store[text_shape_id] = text_shape
                continue

            geo_shape_id, geo_shape = self._create_geo_shape(
                element_id,
                data_for_layer,
            )

            # Suppress the geo's own label when a ``:title`` sibling will
            # render the group name as a separate text shape.
            if is_group_frame(element_id, data_for_layer) and base_id(element_id) in titled_bases:
                geo_shape.setdefault("props", {})["text"] = ""

            self.store[geo_shape_id] = geo_shape

            icon_entry = icon_elements.get(element_id)
            if icon_entry:
                icon_element_id, icon_element_data = icon_entry
                icon_element_data = self._position_icon_in_node(icon_element_data, element_data)
                node_color = (element_data.get("props", {}) or {}).get("color", "")
                icon_element_data = self._apply_icon_color_url(icon_element_data, node_color)
                self._require_icon_file_exists(
                    icon_element_data,
                    element_id=icon_element_id,
                )
                icon_url = self._extract_icon_url(icon_element_data)

                if icon_url and icon_url not in asset_map:
                    asset_id, asset_entry = self._create_asset_entry(icon_element_data)
                    self.store[asset_id] = asset_entry
                    asset_map[icon_url] = asset_id
                elif icon_url:
                    asset_id = asset_map[icon_url]
                else:
                    continue

                image_shape_id, image_shape = self._create_image_shape(
                    icon_element_id,
                    asset_id,
                    icon_element_data,
                )
                pending_icon_shapes.append((image_shape_id, image_shape))

        flush_pending_icons()

        snapshot = {
            "document": {
                "store": self.store,
                "schema": {
                    "schemaVersion": 2,
                    "sequences": {
                        "com.tldraw.store": 4,
                        "com.tldraw.asset": 1,
                        "com.tldraw.camera": 1,
                        "com.tldraw.document": 2,
                        "com.tldraw.instance": 25,
                        "com.tldraw.instance_page_state": 5,
                        "com.tldraw.page": 1,
                        "com.tldraw.instance_presence": 6,
                        "com.tldraw.pointer": 1,
                        "com.tldraw.shape": 4,
                        "com.tldraw.asset.bookmark": 2,
                        "com.tldraw.asset.image": 5,
                        "com.tldraw.asset.video": 5,
                        "com.tldraw.shape.group": 0,
                        "com.tldraw.shape.text": 2,
                        "com.tldraw.shape.bookmark": 2,
                        "com.tldraw.shape.draw": 2,
                        "com.tldraw.shape.geo": 9,
                        "com.tldraw.shape.note": 8,
                        "com.tldraw.shape.line": 5,
                        "com.tldraw.shape.frame": 0,
                        "com.tldraw.shape.arrow": 6,
                        "com.tldraw.shape.highlight": 1,
                        "com.tldraw.shape.embed": 4,
                        "com.tldraw.shape.image": 4,
                        "com.tldraw.shape.video": 2,
                        "com.tldraw.binding.arrow": 0,
                    },
                },
            },
            "session": {
                "version": 0,
                "currentPageId": "page:page",
                "exportBackground": True,
                "isFocusMode": False,
                "isDebugMode": False,
                "isToolLocked": False,
                "isGridMode": False,
                "pageStates": [
                    {
                        "pageId": "page:page",
                        "camera": {
                            "x": 0,
                            "y": 0,
                            "z": 1,
                        },
                        "selectedShapeIds": [],
                        "focusedGroupId": None,
                    }
                ],
            },
        }

        return snapshot

    def save_snapshot(self, output_path: str = "experiments/manifest_converted.json"):
        snapshot = self.convert()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        assets = [k for k in self.store.keys() if k.startswith("asset:")]
        geo_shapes = [k for k in self.store.keys() if k.startswith("shape:") and self.store[k].get("type") == "geo"]
        image_shapes = [k for k in self.store.keys() if k.startswith("shape:") and self.store[k].get("type") == "image"]
        logger.info("Snapshot saved to: %s", output_path)
        logger.info("  - Total elements: %d", len(self.layout_instantiation))
        logger.info("  - Store entries: %d", len(self.store))
        logger.info("  - Assets: %d", len(assets))
        logger.info("  - Geo shapes: %d", len(geo_shapes))
        logger.info("  - Image shapes: %d", len(image_shapes))
        return snapshot


def main():
    print("InstantiationToTldrawConverter converts positioning-aware layout instantiation JSON to TLDraw snapshot.")
    input_path = "experiments/layout_instantiation.json"
    output_path = "experiments/manifest_converted.json"
    if not Path(input_path).exists():
        print(f"Input file not found: {input_path}")
        return
    converter = InstantiationToTldrawConverter(layout_instantiation_json_path=input_path)
    converter.save_snapshot(output_path=output_path)


if __name__ == "__main__":
    main()
