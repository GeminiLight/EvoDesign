"""Lossless expansion of flowchart model decisions before canonical validation.

Only repeated serialization moves into code. Models still choose every visual
style, element box and edge port pair; no topology or geometry is inferred.
Persisted artifacts and downstream stages always use the existing full schema.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation


def use_compact_decisions(structure: Any, canvas_library: str) -> bool:
    return (canvas_library == "excalidraw"
            and unwrap_structure_instantiation(structure).get("chart_type") == "flowchart")


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"Compact decisions: {name} must be an object.")
    return value


def _merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def expand_styling_output(output: Any, structure: Any) -> Any:
    """Expand explicitly versioned templates; legacy full maps pass through.

    Edge defaults are an explicit model decision applied to canonical edge IDs.
    Unknown IDs and incomplete coverage remain errors in the existing validator.
    Templates cannot carry text: exact semantic labels are injected separately.
    """
    if not isinstance(output, dict):
        return output
    inst = output.get("instantiation")
    if not isinstance(inst, dict) or not isinstance(inst.get("format"), str):
        return output
    if inst.get("format") != "style_templates_v1":
        raise ValueError("Unknown compact Styling format.")
    if set(inst) - {"format", "styles", "elements", "edge_default"}:
        raise ValueError("Unknown compact Styling fields.")
    styles = _object(inst.get("styles"), "styles")
    elements = _object(inst.get("elements"), "elements")
    for name, style in styles.items():
        _object(style, f"style {name}")
        label = _object(style["label"], f"style {name} label") if "label" in style else {}
        if "text" in label:
            raise ValueError("Style templates must not contain label text.")
    expanded = {}
    for element_id, decision in elements.items():
        if isinstance(decision, str):
            ref, override = decision, {}
        else:
            override = deepcopy(_object(decision, f"element {element_id}"))
            ref = override.pop("style", None)
        if ref is not None and (not isinstance(ref, str) or ref not in styles):
            raise ValueError(f"Unknown style reference for {element_id!r}: {ref!r}.")
        expanded[element_id] = _merge(styles[ref] if ref is not None else {}, override)
    if "edge_default" in inst:
        default = _object(inst["edge_default"], "edge_default")
        if set(default) != {"strokeColor"}:
            raise ValueError("Compact edge_default must contain only strokeColor.")
        for edge in unwrap_structure_instantiation(structure).get("edges", []):
            edge_id = edge["id"]
            expanded[edge_id] = _merge(default, expanded.get(edge_id, {}))
    result = deepcopy(output)
    result["instantiation"] = expanded
    return result


def expand_layout_output(output: Any, structure: Any) -> Any:
    """Expand flat geometry tuples using exact, validated Structure endpoints.

    [x,y,w,h] is a box; [source_side,target_side,options?] is an edge.
    Full objects remain valid for explicit ports/labels or legacy providers.
    Every edge must still be emitted; nothing is supplied for missing entries.
    """
    if not isinstance(output, dict) or not isinstance(output.get("instantiation"), dict):
        return output
    edges = {edge["id"]: edge for edge in
             unwrap_structure_instantiation(structure).get("edges", [])}
    result = deepcopy(output)
    for element_id, value in result["instantiation"].items():
        if not isinstance(value, list):
            continue
        if element_id in edges:
            if len(value) not in (2, 3):
                raise ValueError(f"Compact edge {element_id!r} needs two sides and optional options.")
            options = _object(value[2], "edge options") if len(value) == 3 else {}
            if set(options) - {"routing", "startArrowhead", "endArrowhead", "label"}:
                raise ValueError(f"Unsupported compact edge options for {element_id!r}.")
            edge = edges[element_id]
            expanded = {**options,
                        "start": {"elementId": edge["source"], "side": value[0]},
                        "end": {"elementId": edge["target"], "side": value[1]}}
        else:
            if len(value) != 4:
                raise ValueError(f"Compact box {element_id!r} needs x,y,w,h.")
            expanded = dict(zip(("x", "y", "w", "h"), value))
        result["instantiation"][element_id] = expanded
    return result
