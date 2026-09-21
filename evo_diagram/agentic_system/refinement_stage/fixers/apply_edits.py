"""Apply a list of EditOps to a manifest, recording per-op outcomes.

This is the single point of mutation: deterministic fixers and the LLM
agent both produce ``List[EditOp]``, and both go through ``apply_edits``.
That guarantees the iteration log is uniform, and a single bug fix in the
dispatcher fixes both paths.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from evo_diagram.agentic_system.render_engine.shared.render_audit import _contrast_ratio

from ..state import EditApplyOutcome, EditOp
from .primitives import OP_HANDLERS

logger = logging.getLogger(__name__)


def _semantic_edit_error(manifest: Dict[str, Any], edit: EditOp) -> str | None:
    """Prevent visual cleanup from erasing source facts."""
    if edit.source != "llm":
        return None
    elements = {element.get("id"): element for element in manifest.get("elements", [])}
    element = elements.get(edit.id, {})
    semantic_ids = set((manifest.get("_meta", {}).get("id_map", {})).values())
    metadata = element.get("meta") or {}
    semantic = (
        edit.id in semantic_ids
        or element.get("containerId") in semantic_ids
        or bool(metadata.get("semantic_edge_id"))
    ) and not element.get("is_group")
    if not semantic:
        return None
    if element.get("opacity", 100) == 0:
        if element.get("type") == "arrow" and edit.op == "set_style" and float(edit.payload.get("opacity", 0)) > 0:
            return "organizer connectors already encoded by containment must remain hidden"
        return None
    if edit.op == "delete_element":
        return "semantic content cannot be deleted during visual refinement"
    if edit.op == "set_text" and not str(edit.payload.get("text", "")).strip():
        return "semantic labels cannot be erased during visual refinement"
    if edit.op == "set_style":
        if metadata.get("conceptFactAnchor") and (
            float(edit.payload.get("strokeWidth", 1)) <= 0
            or edit.payload.get("strokeColor") in {"transparent", "none"}
        ):
            return "fact-bearing section headings need a visible connector boundary"
        if metadata.get("conceptFactAnchor"):
            stroke = edit.payload.get("strokeColor", element.get("strokeColor"))
            fill = edit.payload.get("backgroundColor", element.get("backgroundColor"))
            contrast = _contrast_ratio(stroke, fill)
            if contrast is not None and contrast < 1.5:
                return "fact-bearing heading border must remain distinguishable from its fill"
        if float(edit.payload.get("opacity", 100)) < 25:
            return "semantic content must remain visible"
        if element.get("type") == "arrow" and (
            float(edit.payload.get("strokeWidth", 1)) <= 0
            or edit.payload.get("strokeColor") in {"transparent", "none"}
        ):
            return "semantic connectors must remain visible"
    return None


def apply_edits(
    manifest: Dict[str, Any],
    edits: List[EditOp],
) -> Tuple[Dict[str, Any], List[EditApplyOutcome]]:
    """Apply ``edits`` in order, mutating ``manifest`` in place.

    Returns the same manifest reference (for chaining) plus a per-edit
    outcome list. Unknown ids / invalid payloads / unknown ops never raise:
    they record a failed outcome and the loop continues.
    """
    outcomes: List[EditApplyOutcome] = []

    for edit in edits:
        handler = OP_HANDLERS.get(edit.op)
        if handler is None:
            outcomes.append(
                EditApplyOutcome(
                    edit=edit,
                    applied=False,
                    error=f"unknown op {edit.op!r}",
                )
            )
            continue

        try:
            error = _semantic_edit_error(manifest, edit)
            applied = False
            if error is None:
                applied, error = handler(manifest, edit.id, edit.payload)
        except Exception as exc:  # noqa: BLE001 — defensive: never let a fixer crash the workflow
            logger.exception("EditOp handler raised", extra={"op": edit.op, "id": edit.id})
            outcomes.append(
                EditApplyOutcome(
                    edit=edit,
                    applied=False,
                    error=f"handler raised {type(exc).__name__}: {exc}",
                )
            )
            continue

        outcomes.append(
            EditApplyOutcome(edit=edit, applied=applied, error=error)
        )

    return manifest, outcomes


__all__ = ["apply_edits"]
