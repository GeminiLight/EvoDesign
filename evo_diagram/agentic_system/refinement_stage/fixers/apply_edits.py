"""Apply a list of EditOps to a manifest, recording per-op outcomes.

This is the single point of mutation: deterministic fixers and the LLM
agent both produce ``List[EditOp]``, and both go through ``apply_edits``.
That guarantees the iteration log is uniform, and a single bug fix in the
dispatcher fixes both paths.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..state import EditApplyOutcome, EditOp
from .primitives import OP_HANDLERS

logger = logging.getLogger(__name__)


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
