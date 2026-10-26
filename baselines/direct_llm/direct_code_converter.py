#!/usr/bin/env python3
"""
Direct LLM Output to Tldraw Snapshot Converter

Converts simplified shape JSON from LLM output to a complete tldraw snapshot format.
This allows the LLM to focus on core shape properties without generating boilerplate.
"""

import json
import random
import string
from typing import Dict, Any, List, Tuple


class DirectCodeConverter:
    """
    A class to convert simplified LLM-generated shape JSON to complete tldraw snapshot.
    """

    def __init__(self):
        """Initialize the converter."""
        pass

    def _generate_random_suffix(self, length: int = 12) -> str:
        """
        Generate a random suffix for shape IDs using base62 characters.

        Args:
            length: The length of the random suffix.

        Returns:
            A random string.
        """
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    def _generate_shape_id(self, element_id: str = None) -> str:
        """
        Generate a unique shape ID.

        Args:
            element_id: Optional element ID prefix.

        Returns:
            A complete shape ID.
        """
        random_suffix = self._generate_random_suffix(12)
        if element_id:
            return f"shape:{element_id}_{random_suffix}"
        return f"shape:{random_suffix}"

    def _calculate_dimensions(self, text: str, size: str) -> Tuple[float, float]:
        """
        Calculate width and height based on text content and size property.

        Args:
            text: Text content.
            size: Size enum (xs, s, m, l, xl).

        Returns:
            A tuple of (width, height).
        """
        size_to_height = {"xs": 40.0, "s": 50.0, "m": 60.0, "l": 80.0, "xl": 100.0}
        size_multiplier = {"xs": 1.0, "s": 1.1, "m": 1.2, "l": 1.4, "xl": 1.6}

        base_width = len(text) * 8.0 + 40.0
        width = base_width * size_multiplier.get(size, 1.2)
        width = max(100.0, min(500.0, width))
        width = round(width / 10.0) * 10.0
        height = size_to_height.get(size, 60.0)

        return float(width), float(height)

    def _complete_shape_props(self, props: Dict[str, Any], shape_type: str) -> Dict[str, Any]:
        """
        Complete shape props with required fields based on shape type.

        Args:
            props: Partial props dictionary from LLM.
            shape_type: Shape type (geo, arrow, etc.).

        Returns:
            Completed props dictionary.
        """
        completed = props.copy()

        if shape_type == "geo":
            # Add default fields for geo shapes
            completed.setdefault("geo", "rectangle")
            completed.setdefault("color", "black")
            completed.setdefault("labelColor", "black")
            completed.setdefault("fill", "none")
            completed.setdefault("dash", "draw")
            completed.setdefault("size", "m")
            completed.setdefault("font", "draw")
            completed.setdefault("text", "")
            completed.setdefault("align", "middle")
            completed.setdefault("verticalAlign", "middle")
            completed.setdefault("growY", 0)
            completed.setdefault("url", "")
            completed.setdefault("scale", 1)

            # Calculate dimensions if not provided
            if "w" not in completed or "h" not in completed:
                text = completed.get("text", "")
                size = completed.get("size", "m")
                w, h = self._calculate_dimensions(text, size)
                completed.setdefault("w", w)
                completed.setdefault("h", h)

        elif shape_type == "arrow":
            # Add default fields for arrow shapes
            completed.setdefault("dash", "draw")
            completed.setdefault("size", "m")
            completed.setdefault("fill", "none")
            completed.setdefault("color", "black")
            completed.setdefault("labelColor", "black")
            completed.setdefault("bend", 0)
            completed.setdefault("arrowheadStart", "none")
            completed.setdefault("arrowheadEnd", "arrow")
            completed.setdefault("text", "")
            completed.setdefault("labelPosition", 0.5)
            completed.setdefault("font", "draw")
            completed.setdefault("scale", 1)

            # Ensure start/end are coordinate objects
            if "start" not in completed:
                completed["start"] = {"x": 0, "y": 0}
            if "end" not in completed:
                completed["end"] = {"x": 100, "y": 0}

        return completed

    def _complete_shape(self, shape_data: Dict[str, Any], index: int) -> Dict[str, Any]:
        """
        Complete a shape object with all required fields.

        Args:
            shape_data: Simplified shape data from LLM.
            index: Sequential index for ordering.

        Returns:
            Complete shape object.
        """
        shape_type = shape_data.get("type", "geo")
        props = shape_data.get("props", {})

        # Generate or use provided ID
        if "id" in shape_data and shape_data["id"].startswith("shape:"):
            shape_id = shape_data["id"]
        else:
            element_id = shape_data.get("id", f"elem{index}")
            shape_id = self._generate_shape_id(element_id)

        # Complete props
        completed_props = self._complete_shape_props(props, shape_type)

        # Build complete shape
        shape = {
            "x": shape_data.get("x", 100.0 + (index % 5) * 200.0),
            "y": shape_data.get("y", 100.0 + (index // 5) * 150.0),
            "rotation": shape_data.get("rotation", 0),
            "isLocked": shape_data.get("isLocked", False),
            "opacity": shape_data.get("opacity", 1),
            "meta": shape_data.get("meta", {}),
            "id": shape_id,
            "type": shape_type,
            "props": completed_props,
            "parentId": shape_data.get("parentId", "page:page"),
            "index": shape_data.get("index", f"a{index + 2}"),  # a1 is reserved for page
            "typeName": "shape"
        }

        return shape

    def _build_document_structure(self) -> Dict[str, Any]:
        """Build document:document and page:page objects."""
        return {
            "document:document": {
                "gridSize": 10,
                "name": "",
                "meta": {},
                "id": "document:document",
                "typeName": "document"
            },
            "page:page": {
                "meta": {},
                "id": "page:page",
                "name": "Page 1",
                "index": "a1",
                "typeName": "page"
            }
        }

    def _build_schema(self) -> Dict[str, Any]:
        """Build the schema object with fixed sequences."""
        return {
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
                "com.tldraw.shape.arrow": 5,
                "com.tldraw.shape.highlight": 1,
                "com.tldraw.shape.embed": 4,
                "com.tldraw.shape.image": 4,
                "com.tldraw.shape.video": 2,
                "com.tldraw.binding.arrow": 0
            }
        }

    def _build_session(self) -> Dict[str, Any]:
        """Build the session object."""
        return {
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
                    "camera": {"x": 0, "y": 0, "z": 1},
                    "selectedShapeIds": [],
                    "focusedGroupId": None
                }
            ]
        }

    def convert(self, simplified_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert simplified shape JSON to complete tldraw snapshot.

        Args:
            simplified_json: Simplified JSON from LLM containing shapes list.
                Expected format:
                {
                    "shapes": [
                        {
                            "id": "node1",
                            "type": "geo",
                            "x": 100,
                            "y": 100,
                            "props": {
                                "text": "Node 1",
                                "geo": "rectangle",
                                "color": "blue"
                            }
                        },
                        ...
                    ]
                }

        Returns:
            Complete tldraw snapshot.
        """
        # Build store with document structure
        store = self._build_document_structure()

        # Process shapes
        shapes = simplified_json.get("shapes", [])
        print(f"[DirectCodeConverter] Converting {len(shapes)} shapes...")

        for i, shape_data in enumerate(shapes):
            complete_shape = self._complete_shape(shape_data, i)
            store[complete_shape["id"]] = complete_shape
            print(f"  - Converted shape {i+1}: {complete_shape['id']}")

        # Build complete snapshot
        snapshot = {
            "document": {
                "store": store,
                "schema": self._build_schema()
            },
            "session": self._build_session()
        }

        total_shapes = len([k for k in store.keys() if k.startswith("shape:")])
        print(f"[DirectCodeConverter] Conversion complete! Generated {total_shapes} shapes")

        return snapshot


def convert_simplified_to_tldraw(simplified_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Helper function to convert simplified JSON to tldraw snapshot.

    Args:
        simplified_json: Simplified JSON from LLM.

    Returns:
        Complete tldraw snapshot.
    """
    converter = DirectCodeConverter()
    return converter.convert(simplified_json)


if __name__ == "__main__":
    # Example usage
    example_input = {
        "shapes": [
            {
                "id": "user",
                "type": "geo",
                "x": 100,
                "y": 100,
                "props": {
                    "text": "User",
                    "geo": "rectangle",
                    "color": "blue",
                    "w": 150,
                    "h": 60
                }
            },
            {
                "id": "system",
                "type": "geo",
                "x": 300,
                "y": 100,
                "props": {
                    "text": "System",
                    "geo": "rectangle",
                    "color": "green",
                    "w": 150,
                    "h": 60
                }
            },
            {
                "id": "arrow1",
                "type": "arrow",
                "x": 250,
                "y": 130,
                "props": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 50, "y": 0}
                }
            }
        ]
    }

    converter = DirectCodeConverter()
    result = converter.convert(example_input)

    print("\nExample output:")
    print(json.dumps(result, indent=2))
