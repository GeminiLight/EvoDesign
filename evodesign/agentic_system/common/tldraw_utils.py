"""
Common TLDraw Utilities

Shared utilities for working with TLDraw format across all workflows.
This module consolidates common TLDraw operations to avoid code duplication.
"""

import hashlib
import json
from typing import Any, Dict, Optional, Tuple


def json_dumps_stable(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return repr(value)


class TLDrawIDGenerator:
    """Generator for TLDraw-compatible IDs"""

    @staticmethod
    def _stable_suffix(seed: Any) -> str:
        payload = json_dumps_stable(seed)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def generate_shape_id(prefix: str = "shape", *, seed: Any = None) -> str:
        """
        Generate a deterministic TLDraw-compatible shape ID.

        Args:
            prefix: ID prefix (default: "shape")
            seed: Semantic seed for deterministic output.

        Returns:
            Shape ID in format "prefix:suffix"
        """
        if seed is None:
            raise ValueError("TLDraw shape ids require a semantic seed.")
        return f"{prefix}:{TLDrawIDGenerator._stable_suffix([prefix, seed])}"

    @staticmethod
    def generate_asset_id(icon_url: str) -> str:
        """
        Generate unique asset ID from icon URL.

        Args:
            icon_url: Icon URL

        Returns:
            Asset ID in format "asset:hash"
        """
        hash_obj = hashlib.md5(icon_url.encode())
        hash_hex = hash_obj.hexdigest()[:20]
        return f"asset:{hash_hex}"

    @staticmethod
    def generate_binding_id(*, seed: Any = None) -> str:
        """
        Generate a deterministic binding ID.

        Returns:
            Binding ID in format "binding:suffix"
        """
        return TLDrawIDGenerator.generate_shape_id("binding", seed=seed)

    @staticmethod
    def get_next_index(counter: int) -> str:
        """
        Generate TLDraw index.

        Args:
            counter: Current counter value

        Returns:
            Index string (e.g., "a1", "a2")
        """
        return f"a{counter}"

    @staticmethod
    def generate_stable_index(prefix: str = "b", *, seed: Any = None) -> str:
        """
        Generate a deterministic TLDraw index.

        Args:
            prefix: Index prefix (default: "b")
            seed: Semantic seed for deterministic output.

        Returns:
            Index string (e.g., "b123xy")
        """
        if seed is None:
            raise ValueError("TLDraw generated indexes require a semantic seed.")
        return f"{prefix}{TLDrawIDGenerator._stable_suffix([prefix, seed])[:5]}"


class TLDrawSizeMapper:
    """Mapper for TLDraw size enums to pixel values"""

    ICON_SIZE_MAP = {
        "xs": 24,
        "s": 36,
        "m": 48,
        "l": 58,
        "xl": 65.2
    }

    @staticmethod
    def get_icon_size(size: str) -> float:
        """
        Get icon pixel size from size enum.

        Args:
            size: Size enum (xs, s, m, l, xl)

        Returns:
            Pixel size value
        """
        return TLDrawSizeMapper.ICON_SIZE_MAP.get(size, 48)

    @staticmethod
    def calculate_text_dimensions(
        text: str,
        size: str = "m",
        padding_x: float = 20,
    ) -> Tuple[float, float]:
        """
        Calculate text box dimensions based on text content.

        Args:
            text: Text content
            size: Size enum (default: "m")
            padding_x: Horizontal padding (default: 20)

        Returns:
            Tuple of (width, height)
        """
        size_to_height = {"xs": 40.0, "s": 50.0, "m": 60.0, "l": 80.0, "xl": 100.0}
        size_multiplier = {"xs": 1.0, "s": 1.1, "m": 1.2, "l": 1.4, "xl": 1.6}

        # Calculate base width based on text length
        char_width = 8.0
        base_width = len(text) * char_width + padding_x * 2

        # Get height based on size
        height = size_to_height.get(size, 60.0) * size_multiplier.get(size, 1.2)

        return base_width, height


class TLDrawColorValidator:
    """Validator for TLDraw color enums"""

    VALID_COLORS = [
        'black', 'grey', 'light-violet', 'violet', 'blue', 'light-blue',
        'yellow', 'orange', 'green', 'light-green', 'light-red', 'red', 'white'
    ]

    @staticmethod
    def normalize_color(color: str) -> str:
        """
        Normalize color to valid TLDraw color enum.

        Args:
            color: Input color string

        Returns:
            Valid TLDraw color enum
        """
        if not color:
            return 'black'

        color = color.lower().strip()

        # Common color mappings
        color_map = {
            "light-grey": "grey",
            "lightgrey": "grey",
            "gray": "grey",
            "light-gray": "grey",
            "lightgray": "grey",
            "purple": "violet",
            "light-violet": "light-violet", # identity
            "light-purple": "light-violet",
            "pink": "light-red",
            "light-pink": "light-red",
            "cyan": "light-blue",
            "teal": "light-blue",
            "lime": "light-green",
            "navy": "blue",
            "maroon": "red",
            "brown": "orange",
            "gold": "yellow",
            "silver": "grey",
            "dark-grey": "black",
            "dark-gray": "black",
            "dark-blue": "blue",
            "dark-green": "green",
            "dark-red": "red",
        }

        if color in color_map:
            return color_map[color]

        # Return original if already valid
        if color in TLDrawColorValidator.VALID_COLORS:
            return color

        # Default to black for unknown colors
        return 'black'


class TLDrawShapeValidator:
    """Validator for TLDraw shape enums"""

    VALID_SHAPES = [
        "cloud", "rectangle", "ellipse", "triangle", "diamond",
        "pentagon", "hexagon", "octagon", "star", "rhombus",
        "rhombus-2", "oval", "trapezoid", "arrow-right", "arrow-left",
        "arrow-up", "arrow-down", "x-box", "check-box", "heart"
    ]

    @staticmethod
    def normalize_shape(shape: str) -> str:
        """
        Normalize shape to valid TLDraw shape enum.

        Args:
            shape: Input shape string

        Returns:
            Valid TLDraw shape enum
        """
        shape = shape.lower().strip()

        # Common shape mappings
        shape_map = {
            'circle': 'ellipse',
            'square': 'rectangle',
            'box': 'rectangle',
        }

        if shape in shape_map:
            return shape_map[shape]

        # Return original if already valid
        if shape in TLDrawShapeValidator.VALID_SHAPES:
            return shape

        # Default to rectangle for unknown shapes
        return 'rectangle'


class TLDrawFillValidator:
    """Validator for TLDraw fill enums"""

    VALID_FILLS = ['none', 'semi', 'solid', 'pattern']

    @staticmethod
    def normalize_fill(fill: str) -> str:
        """
        Normalize fill to valid TLDraw fill enum.

        Args:
            fill: Input fill string

        Returns:
            Valid TLDraw fill enum
        """
        fill = fill.lower().strip()

        # Common fill mappings
        fill_map = {
            'transparent': 'none',
            'empty': 'none',
            'empty-fill': 'none',
            'outline': 'none',
        }

        if fill in fill_map:
            return fill_map[fill]

        # Return original if already valid
        if fill in TLDrawFillValidator.VALID_FILLS:
            return fill

        # Default to none for unknown fills
        return 'none'


class TLDrawUtils:
    """Convenience class combining all TLDraw utilities"""

    @staticmethod
    def create_asset_entry(
        icon_url: str,
        icon_size: str = "m",
        icon_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a TLDraw asset entry for an icon.

        Args:
            icon_url: Icon URL
            icon_size: Icon size enum (default: "m")
            icon_name: Optional icon name (extracted from URL if not provided)

        Returns:
            Asset entry dictionary
        """
        if icon_name is None:
            icon_name = icon_url.split("/")[-1]

        dimension = TLDrawSizeMapper.get_icon_size(icon_size)
        asset_id = TLDrawIDGenerator.generate_asset_id(icon_url)

        return {
            "id": asset_id,
            "type": "image",
            "typeName": "asset",
            "props": {
                "name": icon_name,
                "src": icon_url,
                "w": dimension,
                "h": dimension,
                "mimeType": "image/svg+xml",
                "isAnimated": False
            },
            "meta": {}
        }

    @staticmethod
    def create_geo_shape(
        element_id: str,
        text: str = "",
        x: float = 500,
        y: float = 200,
        color: str = "black",
        shape: str = "rectangle",
        fill: str = "none",
        size: str = "m",
        parent_id: str = "page:page",
        index: str = "a1"
    ) -> Dict[str, Any]:
        """
        Create a TLDraw geo shape (text box).

        Args:
            element_id: Element ID
            text: Text content
            x: X coordinate
            y: Y coordinate
            color: Color enum
            shape: Shape enum
            fill: Fill enum
            size: Size enum
            parent_id: Parent element ID
            index: TLDraw index

        Returns:
            Geo shape dictionary
        """
        # Normalize enums
        color = TLDrawColorValidator.normalize_color(color)
        shape = TLDrawShapeValidator.normalize_shape(shape)
        fill = TLDrawFillValidator.normalize_fill(fill)

        # Calculate dimensions
        w, h = TLDrawSizeMapper.calculate_text_dimensions(text, size)

        return {
            "x": x,
            "y": y,
            "rotation": 0,
            "isLocked": False,
            "opacity": 1,
            "meta": {},
            "id": f"shape:{element_id}",
            "type": "geo",
            "props": {
                "w": w,
                "h": h,
                "geo": shape,
                "color": color,
                "labelColor": color,
                "fill": fill,
                "dash": "draw",
                "size": size,
                "font": "draw",
                "text": text,
                "align": "middle",
                "verticalAlign": "middle",
                "growY": 0,
                "url": "",
                "scale": 1
            },
            "parentId": parent_id,
            "index": index,
            "typeName": "shape"
        }

    @staticmethod
    def create_image_shape(
        element_id: str,
        asset_id: str,
        x: float = 500,
        y: float = 200,
        icon_size: str = "m",
        parent_id: str = "page:page",
        index: str = "a2"
    ) -> Dict[str, Any]:
        """
        Create a TLDraw image shape (icon).

        Args:
            element_id: Element ID
            asset_id: Linked asset ID
            x: X coordinate
            y: Y coordinate
            icon_size: Icon size enum
            parent_id: Parent element ID
            index: TLDraw index

        Returns:
            Image shape dictionary
        """
        dimension = TLDrawSizeMapper.get_icon_size(icon_size)

        return {
            "x": x,
            "y": y,
            "rotation": 0,
            "isLocked": False,
            "opacity": 1,
            "meta": {},
            "id": f"shape:{element_id}",
            "type": "image",
            "props": {
                "w": dimension,
                "h": dimension,
                "assetId": asset_id,
                "playing": True,
                "url": "",
                "crop": None,
                "flipX": False,
                "flipY": False,
                "altText": element_id
            },
            "parentId": parent_id,
            "index": index,
            "typeName": "shape"
        }

    @staticmethod
    def create_binding(
        from_id: str,
        to_id: str,
        terminal: str = "start",
        anchor: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Create a TLDraw binding.

        Args:
            from_id: Source element ID (arrow)
            to_id: Target element ID (shape)
            terminal: Terminal type ("start" or "end")
            anchor: Normalized anchor coordinates

        Returns:
            Binding dictionary
        """
        if anchor is None:
            anchor = {"x": 0.5, "y": 0.5}

        return {
            'meta': {},
            'id': TLDrawIDGenerator.generate_binding_id(
                seed=[from_id, to_id, terminal, anchor]
            ),
            'type': 'arrow',
            'fromId': from_id,
            'toId': to_id,
            'props': {
                'isPrecise': True,
                'isExact': True,
                'normalizedAnchor': anchor,
                'terminal': terminal
            },
            'typeName': 'binding'
        }


if __name__ == "__main__":
    # Test TLDraw utilities
    print("Testing TLDraw Utilities")

    # Test ID generation
    shape_id = TLDrawIDGenerator.generate_shape_id("test", seed="demo")
    print(f"Shape ID: {shape_id}")

    asset_id = TLDrawIDGenerator.generate_asset_id("http://example.com/icon.svg")
    print(f"Asset ID: {asset_id}")

    # Test size mapping
    icon_size = TLDrawSizeMapper.get_icon_size("m")
    print(f"Icon size for 'm': {icon_size}")

    # Test dimension calculation
    w, h = TLDrawSizeMapper.calculate_text_dimensions("Hello World", "m")
    print(f"Text dimensions for 'Hello World': {w}x{h}")

    # Test color normalization
    normalized_color = TLDrawColorValidator.normalize_color("purple")
    print(f"Normalized 'purple': {normalized_color}")

    # Test shape normalization
    normalized_shape = TLDrawShapeValidator.normalize_shape("circle")
    print(f"Normalized 'circle': {normalized_shape}")

    # Test utility functions
    asset_entry = TLDrawUtils.create_asset_entry(
        "http://example.com/icon.svg",
        "m"
    )
    print(f"Created asset entry: {asset_entry['id']}")

    geo_shape = TLDrawUtils.create_geo_shape(
        "test_node",
        "Test Node",
        100,
        100
    )
    print(f"Created geo shape: {geo_shape['id']}")

    print("\nAll tests passed!")
