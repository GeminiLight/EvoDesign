"""Apply a list of EditOps to a manifest, recording per-op outcomes.

This is the single point of mutation: deterministic fixers and the LLM
agent both produce ``List[EditOp]``, and both go through ``apply_edits``.
That guarantees the iteration log is uniform, and a single bug fix in the
dispatcher fixes both paths.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from evodesign.canvas_environment import color_contrast_ratio
from evodesign.agentic_system.common.node_icons import ICON_KEY, sync_node_icons

from ..state import EditApplyOutcome, EditOp
from .primitives import OP_HANDLERS

logger = logging.getLogger(__name__)


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _same_label_content(element: Dict[str, Any], new_text: str) -> bool:
    """True when *new_text* only re-wraps the label (whitespace/line breaks).

    Visual refinement may re-flow a semantic label to fix overflow, but must
    not reword, abbreviate or translate it: the words are source facts.
    """
    candidate = _collapse_whitespace(new_text)
    return any(
        isinstance(current, str) and _collapse_whitespace(current) == candidate
        for current in (element.get("originalText"), element.get("text"))
    )


def _semantic_edit_error(manifest: Dict[str, Any], edit: EditOp) -> str | None:
    """Prevent visual cleanup from erasing source facts."""
    if edit.source != "llm":
        return None
    elements = {element.get("id"): element for element in manifest.get("elements", [])}
    element = elements.get(edit.id, {})
    is_node_icon = bool((element.get("customData") or {}).get(ICON_KEY))
    if is_node_icon and edit.op in {"set_position", "set_size", "delete_element"}:
        return "generated icons follow their host node; edit the host geometry instead of detaching its icon"
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
    if edit.op == "set_text":
        new_text = edit.payload.get("text", "")
        if not str(new_text).strip():
            return "semantic labels cannot be erased during visual refinement"
        if not _same_label_content(element, str(new_text)):
            return (
                "semantic label content is fixed during visual refinement; "
                "set_text may only re-wrap it (whitespace/line breaks)"
            )
    if edit.op == "set_style":
        if metadata.get("conceptFactAnchor") and (
            float(edit.payload.get("strokeWidth", 1)) <= 0
            or edit.payload.get("strokeColor") in {"transparent", "none"}
        ):
            return "fact-bearing section headings need a visible connector boundary"
        if metadata.get("conceptFactAnchor"):
            stroke = edit.payload.get("strokeColor", element.get("strokeColor"))
            fill = edit.payload.get("backgroundColor", element.get("backgroundColor"))
            contrast = color_contrast_ratio(stroke, fill)
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
    *,
    allow_icons: bool = True,
) -> Tuple[Dict[str, Any], List[EditApplyOutcome]]:
    """Apply ``edits`` in order, mutating ``manifest`` in place.

    Returns the same manifest reference (for chaining) plus a per-edit
    outcome list. Unknown ids / invalid payloads / unknown ops never raise:
    they record a failed outcome and the loop continues.
    """
    outcomes: List[EditApplyOutcome] = []

    for edit in edits:
        if edit.op == "set_icon" and not allow_icons:
            outcomes.append(EditApplyOutcome(edit=edit, applied=False,
                                            error="Icons are disabled by the user."))
            continue
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

    sync_node_icons(manifest)
    return manifest, outcomes


__all__ = ["apply_edits"]
