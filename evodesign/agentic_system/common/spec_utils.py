"""Specification formatting and unwrapping utilities for inter-agent communication."""
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def format_specification_for_prompt(spec_name: str, spec_data: Dict[str, Any]) -> str:
    """Format a specification dict into human-readable prompt text.

    Handles the module-based spec format used by all three workflow specs:
    Structure (4 modules), Styling (4 modules), and Layout (5 modules).
    """
    if not spec_data:
        return ""
    lines = [f"--- {spec_name} ---"]
    for dim_key, dim_value in spec_data.items():
        if isinstance(dim_value, dict):
            lines.append(f"- [{dim_key}]:")
            for sub_key, sub_value in dim_value.items():
                if isinstance(sub_value, str):
                    lines.append(f"    {sub_key}: {sub_value}")
                else:
                    lines.append(f"    {sub_key}: {json.dumps(sub_value, ensure_ascii=False)}")
        elif isinstance(dim_value, list):
            # Array format (e.g., topological_invariants)
            lines.append(f"- [{dim_key}]:")
            for item in dim_value:
                if isinstance(item, str):
                    lines.append(f"    - {item}")
                elif isinstance(item, dict):
                    parts = [f"{k}: {v}" for k, v in item.items()]
                    lines.append(f"    - {', '.join(parts)}")
                else:
                    lines.append(f"    - {item}")
        else:
            lines.append(f"- [{dim_key}] {dim_value}")
    return "\n".join(lines)

def build_assistant_content(
    spec_name: str,
    specification: Optional[Dict[str, Any]],
    instantiation: Any,
) -> str:
    """Build the assistant message content for conversation_history.

    Keep the same JSON contract the next stage is required to emit. A prose
    assistant example caused Layout to copy its headings and fail strict JSON
    parsing, wasting a complete model call on a format-only retry.
    """
    return json.dumps({"specification": specification or {},
                       "instantiation": instantiation}, ensure_ascii=False, separators=(",", ":"))


def build_stage_messages(
    system_prompt: str,
    task: str,
    upstream: List[Tuple[str, Optional[Dict[str, Any]], Any]],
) -> List[Dict[str, str]]:
    """Pass validated artifacts, not obsolete tasks or failed repair attempts.

    The current task already contains source text, user constraints, runtime
    directives and stage knowledge. Preserve upstream specifications in full;
    only discard duplicated instructions, never facts or design decisions.
    """
    messages = [{"role": "system", "content": system_prompt}]
    for stage_name, specification, instantiation in upstream:
        messages.extend([
            {"role": "user", "content": f"Validated {stage_name} result (upstream context):"},
            {"role": "assistant", "content": build_assistant_content(
                stage_name, specification, instantiation)},
        ])
    messages.append({"role": "user", "content": task})
    return messages


def unwrap_agent_output(
    raw_output: Any,
    *,
    stage_name: str = "Agent",
) -> Tuple[Dict[str, Any], Any]:
    """Unwrap agent LLM output into (specification, instantiation).

    Generation-stage agents have one canonical boundary shape:
    ``{"specification": {...}, "instantiation": ...}``.
    """
    if not isinstance(raw_output, dict):
        raise ValueError(
            f"{stage_name} output must be a JSON object with top-level "
            f"'specification' and 'instantiation'; got {type(raw_output).__name__}."
        )

    missing_keys = [
        key for key in ("specification", "instantiation")
        if key not in raw_output
    ]
    if missing_keys:
        missing = ", ".join(repr(key) for key in missing_keys)
        raise ValueError(
            f"{stage_name} output missing top-level key(s): {missing}. "
            "Expected {'specification': {...}, 'instantiation': ...}."
        )

    specification = raw_output["specification"]
    if not isinstance(specification, dict):
        raise ValueError(
            f"{stage_name} specification must be a JSON object; "
            f"got {type(specification).__name__}."
        )

    return specification, raw_output["instantiation"]


def unwrap_structure_instantiation(raw_structure: Any) -> Dict[str, Any]:
    """Return the canonical Structure instantiation dict.

    Stage outputs may reach downstream code either as the flat Structure
    payload or as a persisted wrapper. Centralize that boundary normalization
    here so validators and render audits do not each guess a different shape.
    """
    if not isinstance(raw_structure, dict):
        return {}

    current = raw_structure
    seen: set[int] = set()
    while isinstance(current, dict):
        marker = id(current)
        if marker in seen:
            return current
        seen.add(marker)

        for wrapper_key in ("structure_instantiation", "instantiation"):
            nested = current.get(wrapper_key)
            if isinstance(nested, dict):
                current = nested
                break
        else:
            return current

    return {}


@dataclass(frozen=True)
class StageOutput:
    """Canonical wrapper for one generation-stage LLM output."""

    specification: Dict[str, Any]
    instantiation: Any


def parse_stage_output(
    raw_output: Any,
    *,
    stage_name: str,
    require_instantiation_dict: bool = False,
    require_flat_id_map: bool = False,
    reject_error_key: bool = False,
) -> StageOutput:
    """Parse one canonical generation-stage LLM output.

    This keeps Structure, Styling, and Layout on one output contract:
    ``{"specification": {...}, "instantiation": ...}``.
    """
    specification, instantiation = unwrap_agent_output(
        raw_output,
        stage_name=stage_name,
    )

    if require_instantiation_dict:
        has_error_key = isinstance(instantiation, dict) and "error" in instantiation
        if not isinstance(instantiation, dict) or (reject_error_key and has_error_key):
            raise ValueError(
                f"{stage_name} output is not a valid dict: "
                f"{type(instantiation).__name__}"
            )
        if require_flat_id_map:
            _reject_categorized_instantiation(instantiation, stage_name)

    return StageOutput(
        specification=specification,
        instantiation=instantiation,
    )


def _reject_categorized_instantiation(
    instantiation: Dict[str, Any],
    stage_name: str,
) -> None:
    """Reject Styling/Layout outputs grouped under nodes/edges/groups."""
    category_keys = sorted(
        key for key in ("nodes", "edges", "groups")
        if isinstance(instantiation.get(key), dict)
    )
    if category_keys:
        categories = ", ".join(repr(key) for key in category_keys)
        raise ValueError(
            f"{stage_name} instantiation must be a flat id-keyed map; "
            f"do not nest entries under {categories}."
        )
