"""
Tldraw snapshot compliance checker.

Loads a snapshot JSON and validates it against the baseline structure produced
by the render workflow converters (see code_converter.py).
Returns a structured report with errors, warnings, and basic counts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from evo_diagram.agentic_system.common.tldraw_utils import TLDrawColorValidator, TLDrawFillValidator, TLDrawShapeValidator


REQUIRED_SCHEMA_KEYS = {
    "com.tldraw.store",
    "com.tldraw.asset",
    "com.tldraw.document",
    "com.tldraw.page",
    "com.tldraw.shape",
    "com.tldraw.asset.image",
    "com.tldraw.shape.geo",
    "com.tldraw.shape.image",
}

_VALID_COLORS = set(TLDrawColorValidator.VALID_COLORS)
_VALID_FILLS = set(TLDrawFillValidator.VALID_FILLS)
_VALID_GEOS = set(TLDrawShapeValidator.VALID_SHAPES)
_VALID_ARROW_KINDS = {"straight", "elbow", "curved"}


class TldrawValidationInput(BaseModel):
    """Input schema for the validator tool."""

    manifest_path: str = Field(
        ...,
        description="Path to the Tldraw manifest JSON file to validate."
    )


def _load_manifest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _require_fields(label: str, payload: Dict[str, Any], required: List[str]) -> List[str]:
    missing = [field for field in required if field not in payload]
    return [f"{label} missing field: {field}" for field in missing]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_number(label: str, payload: Dict[str, Any], field: str, *, positive: bool = False) -> List[str]:
    if field not in payload:
        return []
    value = payload.get(field)
    if not _is_number(value):
        return [f"{label}.{field} must be a number"]
    if positive and value <= 0:
        return [f"{label}.{field} must be positive"]
    return []


def _validate_enum(label: str, value: Any, valid_values: set[str]) -> List[str]:
    if value not in valid_values:
        allowed = ", ".join(sorted(valid_values))
        return [f"{label} has invalid value {value!r}; expected one of: {allowed}"]
    return []


def _validate_point(label: str, value: Any) -> List[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object with numeric x/y"]
    errors: List[str] = []
    errors += _require_fields(label, value, ["x", "y"])
    errors += _validate_number(label, value, "x")
    errors += _validate_number(label, value, "y")
    return errors


def _validate_asset(key: str, entry: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    errors += _require_fields(key, entry, ["id", "type", "typeName", "props", "meta"])
    props = entry.get("props", {}) if isinstance(entry.get("props", {}), dict) else {}
    if not props:
        errors.append(f"{key} props must be a non-empty object")
    else:
        errors += _require_fields(f"{key}.props", props, ["name", "src", "w", "h", "mimeType", "isAnimated"])
    return errors


def _validate_shape(key: str, entry: Dict[str, Any], store: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    errors += _require_fields(
        key,
        entry,
        ["x", "y", "rotation", "isLocked", "opacity", "meta", "id", "type", "props", "parentId", "index", "typeName"],
    )
    errors += _validate_number(key, entry, "x")
    errors += _validate_number(key, entry, "y")
    errors += _validate_number(key, entry, "rotation")
    errors += _validate_number(key, entry, "opacity")

    shape_type = entry.get("type")
    props = entry.get("props", {}) if isinstance(entry.get("props", {}), dict) else {}
    if not props:
        errors.append(f"{key} props must be a non-empty object")
    else:
        # Arrow shapes in tldraw do not require w/h; text shapes carry only w
        # (height is derived from the content); other shapes need both.
        if shape_type == "text":
            errors += _require_fields(f"{key}.props", props, ["w"])
            errors += _validate_number(f"{key}.props", props, "w", positive=True)
        elif shape_type != "arrow":
            errors += _require_fields(f"{key}.props", props, ["w", "h"])
            errors += _validate_number(f"{key}.props", props, "w", positive=True)
            errors += _validate_number(f"{key}.props", props, "h", positive=True)

        if shape_type == "geo":
            errors += _require_fields(f"{key}.props", props, ["geo", "color", "fill"])
            if "geo" in props:
                errors += _validate_enum(f"{key}.props.geo", props.get("geo"), _VALID_GEOS)
            if "color" in props:
                errors += _validate_enum(f"{key}.props.color", props.get("color"), _VALID_COLORS)
            if "labelColor" in props:
                errors += _validate_enum(f"{key}.props.labelColor", props.get("labelColor"), _VALID_COLORS)
            if "fill" in props:
                errors += _validate_enum(f"{key}.props.fill", props.get("fill"), _VALID_FILLS)

        if shape_type == "text":
            if "color" in props:
                errors += _validate_enum(f"{key}.props.color", props.get("color"), _VALID_COLORS)

        if shape_type == "arrow":
            errors += _require_fields(f"{key}.props", props, ["color", "kind", "start", "end"])
            if "color" in props:
                errors += _validate_enum(f"{key}.props.color", props.get("color"), _VALID_COLORS)
            if "labelColor" in props:
                errors += _validate_enum(f"{key}.props.labelColor", props.get("labelColor"), _VALID_COLORS)
            if "kind" in props:
                errors += _validate_enum(f"{key}.props.kind", props.get("kind"), _VALID_ARROW_KINDS)
            if "start" in props:
                errors += _validate_point(f"{key}.props.start", props.get("start"))
            if "end" in props:
                errors += _validate_point(f"{key}.props.end", props.get("end"))

        if shape_type == "image":
            if "assetId" not in props:
                errors.append(f"{key} image shape is missing props.assetId")
            asset_id = props.get("assetId")
            if asset_id and asset_id not in store:
                errors.append(f"{key} references missing asset {asset_id}")
    parent_id = entry.get("parentId")
    if parent_id and parent_id not in store:
        errors.append(f"{key} parentId {parent_id} not found in store")
    return errors


def _validate_binding(key: str, entry: Dict[str, Any], store: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    # Arrow bindings produced by tldraw often omit handleId; treat it as optional for type==arrow.
    required = ["id", "typeName", "fromId", "toId", "meta"]
    if entry.get("type") != "arrow":
        required.append("handleId")
    errors += _require_fields(key, entry, required)
    for ref_key in ("fromId", "toId"):
        ref = entry.get(ref_key)
        if ref and ref not in store:
            errors.append(f"{key} references missing target {ref_key}={ref}")
    return errors


def _validate_store(store: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if "document:document" not in store:
        errors.append("store missing document:document entry")
    if not any(k.startswith("page:") for k in store):
        errors.append("store missing any page:* entry")

    shape_count = 0
    asset_count = 0
    binding_count = 0

    for key, entry in store.items():
        if not isinstance(entry, dict):
            errors.append(f"store entry {key} must be an object")
            continue

        entry_type = entry.get("typeName")
        if entry.get("id") and entry.get("id") != key:
            warnings.append(f"{key} id mismatch: {entry.get('id')}")

        if entry_type == "asset":
            asset_count += 1
            errors += _validate_asset(key, entry)
        elif entry_type == "shape":
            shape_count += 1
            errors += _validate_shape(key, entry, store)
        elif entry_type == "binding":
            binding_count += 1
            errors += _validate_binding(key, entry, store)
        elif entry_type in {"document", "page"}:
            errors += _require_fields(key, entry, ["id", "typeName", "meta"])
        else:
            warnings.append(f"{key} uses unsupported typeName: {entry_type}")

    return {
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "store_entries": len(store),
            "shapes": shape_count,
            "assets": asset_count,
            "bindings": binding_count,
        },
    }


def _validate_schema(schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    errors += _require_fields("schema", schema, ["schemaVersion", "sequences"])
    sequences = schema.get("sequences", {}) if isinstance(schema.get("sequences", {}), dict) else {}
    missing_keys = REQUIRED_SCHEMA_KEYS - set(sequences.keys())
    for key in sorted(missing_keys):
        errors.append(f"schema.sequences missing key: {key}")
    return errors


def _validate_session(session: Dict[str, Any]) -> List[str]:
    return _require_fields("session", session, ["currentPageId", "pageStates"])


def validate_tldraw_manifest(manifest_path: str = "", manifest_data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Validate a Tldraw manifest JSON against required structure.

    Returns a report dictionary with validity flag, counts, errors, and warnings.
    """

    data: Dict[str, Any]
    path: Path | None = None

    if manifest_data is not None:
        data = manifest_data
    elif manifest_path:
        path = Path(manifest_path)
        data = _load_manifest(path)
    else:
        raise ValueError("Either manifest_path or manifest_data must be provided.")

    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object.")

    document = data.get("document")
    session = data.get("session")

    if not isinstance(document, dict):
        raise ValueError("Manifest missing document section.")
    if not isinstance(session, dict):
        raise ValueError("Manifest missing session section.")

    store = document.get("store", {})
    schema = document.get("schema", {})

    if not isinstance(store, dict):
        raise ValueError("document.store must be an object.")
    if not isinstance(schema, dict):
        raise ValueError("document.schema must be an object.")

    store_report = _validate_store(store)
    errors += store_report["errors"]
    warnings += store_report["warnings"]
    counts = store_report["counts"]

    errors += _validate_schema(schema)
    errors += _validate_session(session)

    return {
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "manifest_path": str(path),
    }


validate_tldraw_manifest_tool = StructuredTool.from_function(
    func=validate_tldraw_manifest,
    name="validate_tldraw_manifest",
    description=(
        "Validate a Tldraw manifest JSON for structural compliance with the standard "
        "format produced by the render workflow converters (code_converter). "
        "Returns a report containing errors, warnings, and basic counts."
    ),
    args_schema=TldrawValidationInput,
    return_direct=False,
)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for validating a Tldraw manifest JSON file."""
    parser = argparse.ArgumentParser(
        description="Validate a Tldraw manifest JSON file.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to the Tldraw manifest JSON file to validate.",
    )
    args = parser.parse_args(argv)

    try:
        report = validate_tldraw_manifest(manifest_path=args.manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report = {
            "is_valid": False,
            "error_count": 1,
            "warning_count": 0,
            "errors": [str(exc)],
            "warnings": [],
            "counts": {},
            "manifest_path": str(args.manifest),
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["is_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
