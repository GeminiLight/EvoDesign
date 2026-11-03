"""Manifest format normalization for TLDraw diagrams.

Converts multiple TLDraw manifest formats to a unified representation
for consistent diff extraction.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from .manifest_validator import (
    ManifestFormat,
    ManifestValidator,
    _get_store,
    _is_shape_entry,
)


@dataclass
class NormalizedShape:
    """Normalized shape representation (format-agnostic)."""

    id: str
    type: str  # "geo", "arrow", "text", "frame"
    x: float
    y: float
    rotation: float
    is_locked: bool
    opacity: float
    props: Dict  # Normalized properties
    meta: Dict  # Metadata
    parent_id: Optional[str]
    index: str  # Fractional index


@dataclass
class NormalizedManifest:
    """Normalized manifest representation."""

    shapes: Dict[str, NormalizedShape]  # id -> shape
    bindings: Dict[str, Dict]  # id -> binding
    assets: Dict[str, Dict]  # id -> asset
    format: ManifestFormat
    warnings: List[str]


class ManifestNormalizer:
    """Converts multiple TLDraw formats to unified representation."""

    def __init__(self):
        self.validator = ManifestValidator()

    def normalize(self, manifest: dict) -> NormalizedManifest:
        """Normalize manifest to unified format."""
        # Step 1: Validate
        validation = self.validator.validate(manifest)

        if validation.format == ManifestFormat.UNKNOWN:
            return NormalizedManifest(
                shapes={},
                bindings={},
                assets={},
                format=ManifestFormat.UNKNOWN,
                warnings=validation.warnings
                + ["Failed to normalize: unknown format"],
            )

        # Step 2: Extract shapes
        shapes = self._extract_shapes(manifest, validation.format)

        # Step 3: Extract bindings
        bindings = self._extract_bindings(manifest, validation.format)

        # Step 4: Extract assets
        assets = self._extract_assets(manifest, validation.format)

        # Step 5: Normalize properties
        for shape in shapes.values():
            self._normalize_shape_props(shape)

        return NormalizedManifest(
            shapes=shapes,
            bindings=bindings,
            assets=assets,
            format=validation.format,
            warnings=validation.warnings,
        )

    def _extract_shapes(
        self, manifest: dict, format_type: ManifestFormat
    ) -> Dict[str, NormalizedShape]:
        """Extract shapes from manifest."""
        shapes = {}

        if format_type in (ManifestFormat.V3_15_STORE, ManifestFormat.HYBRID):
            store = _get_store(manifest, format_type)
            for key, value in store.items():
                if _is_shape_entry(key, value):
                    shapes[key] = self._build_normalized_shape(key, value)

        elif format_type == ManifestFormat.LEGACY_ARRAY:
            for shape in manifest.get("shapes", []):
                shapes[shape["id"]] = self._build_normalized_shape(shape["id"], shape)

        return shapes

    def _build_normalized_shape(self, key: str, value: dict) -> NormalizedShape:
        """Build a NormalizedShape from raw shape data."""
        return NormalizedShape(
            id=value.get("id", key),
            type=value.get("type", "geo"),
            x=float(value.get("x", 0)),
            y=float(value.get("y", 0)),
            rotation=float(value.get("rotation", 0)),
            is_locked=value.get("isLocked", False),
            opacity=float(value.get("opacity", 1.0)),
            props=value.get("props", {}).copy(),
            meta=value.get("meta", {}).copy(),
            parent_id=value.get("parentId"),
            index=value.get("index", "a1"),
        )

    def _extract_bindings(
        self, manifest: dict, format_type: ManifestFormat
    ) -> Dict[str, Dict]:
        """Extract bindings from manifest."""
        bindings = {}
        store = _get_store(manifest, format_type)
        if store:
            for key, value in store.items():
                if isinstance(value, dict) and value.get("typeName") == "binding":
                    bindings[key] = value
        return bindings

    def _extract_assets(
        self, manifest: dict, format_type: ManifestFormat
    ) -> Dict[str, Dict]:
        """Extract assets from manifest."""
        assets = {}
        store = _get_store(manifest, format_type)
        if store:
            for key, value in store.items():
                if isinstance(value, dict) and value.get("typeName") == "asset":
                    assets[key] = value
        elif "assets" in manifest:
            for asset in manifest["assets"]:
                assets[asset["id"]] = asset
        return assets

    def _normalize_shape_props(self, shape: NormalizedShape):
        """Normalize shape properties (format-specific differences)."""
        props = shape.props

        # Rule 1: richText -> text
        if "richText" in props:
            if "text" not in props:
                props["text"] = props["richText"]
            del props["richText"]

        # Rule 2: snap: "none" -> snap: null
        if props.get("snap") == "none":
            props["snap"] = None

        # Rule 3: Integer -> Float (w, h)
        for key in ["w", "h"]:
            if key in props and isinstance(props[key], int):
                props[key] = float(props[key])

        # Rule 4: Nested start/end normalization
        for key in ["start", "end"]:
            if key in props and isinstance(props[key], dict):
                if props[key].get("type") == "point" and "x" in props[key]:
                    props[key]["x"] = float(props[key]["x"])
                    props[key]["y"] = float(props[key]["y"])
