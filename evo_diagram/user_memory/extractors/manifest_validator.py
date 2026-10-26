"""Manifest format detection and validation for TLDraw diagrams."""

from dataclasses import dataclass
from enum import Enum
from typing import List


class ManifestFormat(Enum):
    """Supported TLDraw manifest formats."""

    V3_15_STORE = "v3.15_store"  # document.store dict (current TLDraw format)
    LEGACY_ARRAY = "legacy_array"  # shapes array (older format)
    HYBRID = "hybrid"  # Both present
    UNKNOWN = "unknown"  # Cannot detect format


@dataclass
class ValidationResult:
    """Manifest validation result."""

    format: ManifestFormat
    is_valid: bool
    warnings: List[str]
    shape_count: int
    has_bindings: bool
    has_assets: bool


def _is_shape_entry(key: str, value) -> bool:
    """Check if a store entry is a shape."""
    return isinstance(value, dict) and (
        value.get("typeName") == "shape"
        or (key.startswith("shape:") and "type" in value)
    )


def _get_store(manifest: dict, format_type: ManifestFormat) -> dict:
    """Get the store dict from a manifest, or empty dict if not applicable."""
    if format_type in (ManifestFormat.V3_15_STORE, ManifestFormat.HYBRID):
        document = manifest.get("document") if isinstance(manifest, dict) else None
        store = document.get("store") if isinstance(document, dict) else None
        return store if isinstance(store, dict) else {}
    return {}


class ManifestValidator:
    """Validates and detects TLDraw manifest formats."""

    def validate(self, manifest: dict) -> ValidationResult:
        """Detect format and validate structure."""
        warnings = []

        # Detect format
        document = manifest.get("document") if isinstance(manifest, dict) else None
        store = document.get("store") if isinstance(document, dict) else None
        has_document = isinstance(manifest, dict) and "document" in manifest
        has_store = isinstance(store, dict)
        has_shapes_array = (
            isinstance(manifest, dict)
            and "shapes" in manifest
            and isinstance(manifest["shapes"], list)
        )
        if has_document and not has_store:
            warnings.append("document.store is missing or not an object")

        if has_store and has_shapes_array:
            format_type = ManifestFormat.HYBRID
            warnings.append(
                "Both document.store and shapes[] present - preferring document.store"
            )
        elif has_store:
            format_type = ManifestFormat.V3_15_STORE
        elif has_shapes_array:
            format_type = ManifestFormat.LEGACY_ARRAY
        else:
            format_type = ManifestFormat.UNKNOWN
            warnings.append("No shapes found in manifest")

        # Count shapes
        shape_count = self._count_shapes(manifest, format_type)

        # Check for bindings and assets
        has_bindings = self._has_bindings(manifest, format_type)
        has_assets = self._has_assets(manifest, format_type)

        # Validate structure
        is_valid = format_type != ManifestFormat.UNKNOWN

        return ValidationResult(
            format=format_type,
            is_valid=is_valid,
            warnings=warnings,
            shape_count=shape_count,
            has_bindings=has_bindings,
            has_assets=has_assets,
        )

    def _count_shapes(self, manifest: dict, format_type: ManifestFormat) -> int:
        """Count shapes in manifest."""
        if format_type in (ManifestFormat.V3_15_STORE, ManifestFormat.HYBRID):
            store = _get_store(manifest, format_type)
            return sum(1 for k, v in store.items() if _is_shape_entry(k, v))
        elif format_type == ManifestFormat.LEGACY_ARRAY:
            return len(manifest.get("shapes", []))
        return 0

    def _has_bindings(self, manifest: dict, format_type: ManifestFormat) -> bool:
        """Check if manifest has bindings."""
        store = _get_store(manifest, format_type)
        if store:
            return any(
                v.get("typeName") == "binding"
                for v in store.values()
                if isinstance(v, dict)
            )
        return False

    def _has_assets(self, manifest: dict, format_type: ManifestFormat) -> bool:
        """Check if manifest has assets."""
        store = _get_store(manifest, format_type)
        if store:
            return any(
                v.get("typeName") == "asset"
                for v in store.values()
                if isinstance(v, dict)
            )
        if not isinstance(manifest, dict):
            return False
        assets = manifest.get("assets")
        return isinstance(assets, (dict, list)) and len(assets) > 0
