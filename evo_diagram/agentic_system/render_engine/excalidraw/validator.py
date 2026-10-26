# -*- coding: utf-8 -*-
"""
Excalidraw manifest compliance checker.

Validates an Excalidraw scene JSON against the required structure.
Counterpart of tldraw_validator.py for the Excalidraw canvas library.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set


REQUIRED_ELEMENT_FIELDS = {"id", "type", "x", "y", "width", "height", "seed", "version", "isDeleted"}

VALID_ELEMENT_TYPES = {
    "rectangle", "ellipse", "diamond", "triangle", "line", "arrow",
    "text", "image", "freedraw", "frame",
}


def _require_fields(label: str, payload: Dict[str, Any], required: Set[str]) -> List[str]:
    missing = [field for field in sorted(required) if field not in payload]
    return [f"{label} missing field: {field}" for field in missing]


def _validate_element(elem: Dict[str, Any], index: int, all_ids: Set[str]) -> tuple[List[str], List[str]]:
    """Validate a single Excalidraw element."""
    errors: List[str] = []
    warnings: List[str] = []
    label = f"elements[{index}]"

    if not isinstance(elem, dict):
        errors.append(f"{label} must be an object")
        return errors, warnings

    eid = elem.get("id", f"<missing-id-{index}>")
    label = f"elements[{index}] (id={eid})"

    # Required fields
    errors += _require_fields(label, elem, REQUIRED_ELEMENT_FIELDS)

    # Type validation
    elem_type = elem.get("type")
    if elem_type and elem_type not in VALID_ELEMENT_TYPES:
        warnings.append(f"{label} uses non-standard type: {elem_type}")

    # Arrow-specific validation
    if elem_type == "arrow":
        points = elem.get("points")
        if not isinstance(points, list) or len(points) < 2:
            errors.append(f"{label} arrow must have points array with at least 2 points")

        for binding_key in ("startBinding", "endBinding"):
            binding = elem.get(binding_key)
            if binding and isinstance(binding, dict):
                ref_id = binding.get("elementId")
                if ref_id and ref_id not in all_ids:
                    errors.append(f"{label} {binding_key} references missing elementId: {ref_id}")

    # Text-specific validation
    if elem_type == "text":
        container_id = elem.get("containerId")
        if container_id and container_id not in all_ids:
            errors.append(f"{label} containerId references missing element: {container_id}")

    # Image-specific validation
    if elem_type == "image":
        if "fileId" not in elem:
            warnings.append(f"{label} image element missing fileId")

    return errors, warnings


def _validate_bound_elements_consistency(elements: List[Dict[str, Any]]) -> List[str]:
    """Check bidirectional consistency of boundElements."""
    warnings: List[str] = []

    # Build map: element_id -> set of bound element IDs
    bound_map: Dict[str, Set[str]] = {}
    for elem in elements:
        eid = elem.get("id", "")
        bound_elems = elem.get("boundElements")
        if isinstance(bound_elems, list):
            bound_map[eid] = {b.get("id", "") for b in bound_elems if isinstance(b, dict)}
        else:
            bound_map[eid] = set()

    # Check text containerId <-> boundElements consistency
    for elem in elements:
        if elem.get("type") == "text":
            container_id = elem.get("containerId")
            text_id = elem.get("id", "")
            if container_id and container_id in bound_map:
                if text_id not in bound_map[container_id]:
                    warnings.append(
                        f"text element {text_id} has containerId={container_id} "
                        f"but container's boundElements does not reference it"
                    )

    return warnings


def validate_excalidraw_manifest(manifest_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate an Excalidraw manifest JSON for structural compliance.

    Args:
        manifest_data: Excalidraw manifest dict (with elements, files, optionally _meta)

    Returns:
        Report dict with is_valid, error_count, warning_count, errors, warnings, counts
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(manifest_data, dict):
        return {
            "is_valid": False,
            "error_count": 1,
            "warning_count": 0,
            "errors": ["Manifest root must be a JSON object."],
            "warnings": [],
            "counts": {},
        }

    # Top-level structure
    elements = manifest_data.get("elements")
    files = manifest_data.get("files")

    if not isinstance(elements, list):
        errors.append("Manifest missing or invalid 'elements' (must be a list)")
    if files is not None and not isinstance(files, dict):
        warnings.append("'files' should be a dict if present")

    if not isinstance(elements, list):
        return {
            "is_valid": False,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
            "counts": {},
        }

    # Collect all IDs for reference checks
    all_ids: Set[str] = set()
    for elem in elements:
        if isinstance(elem, dict) and "id" in elem:
            eid = elem["id"]
            if eid in all_ids:
                errors.append(f"Duplicate element ID: {eid}")
            all_ids.add(eid)

    # Validate each element
    counts: Dict[str, int] = {
        "total_elements": len(elements),
        "shapes": 0,
        "arrows": 0,
        "texts": 0,
        "images": 0,
        "other": 0,
    }

    for i, elem in enumerate(elements):
        elem_errors, elem_warnings = _validate_element(elem, i, all_ids)
        errors += elem_errors
        warnings += elem_warnings

        elem_type = elem.get("type", "") if isinstance(elem, dict) else ""
        if elem_type == "arrow":
            counts["arrows"] += 1
        elif elem_type == "text":
            counts["texts"] += 1
        elif elem_type == "image":
            counts["images"] += 1
        elif elem_type in ("rectangle", "ellipse", "diamond", "triangle", "frame"):
            counts["shapes"] += 1
        else:
            counts["other"] += 1

    # Check boundElements consistency
    warnings += _validate_bound_elements_consistency(elements)

    # Validate files references from image elements
    if isinstance(files, dict):
        for elem in elements:
            if isinstance(elem, dict) and elem.get("type") == "image":
                file_id = elem.get("fileId")
                if file_id and file_id not in files:
                    warnings.append(f"Image element {elem.get('id')} references missing fileId: {file_id}")

    return {
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
    }
