"""Single-shot VLM refiner agent.

One model call per refinement iteration. Receives:
- the current PNG (base64 — never visually inspected by Claude)
- the **remaining** findings (after deterministic pass)
- the original verifier subjective critique (loaded once at start)
- a compact manifest summary
- previous-iteration edit log (so the model doesn't loop)

Returns a List[EditOp]. Schema-violating items are dropped rather than
raising, but never silently: they land in ``last_rejected_edits`` so the
workflow can record them in the iteration log.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..state import EditOp
from .prompts import (
    MAX_MANIFEST_SUMMARY_ELEMENTS,
    REFINER_LLM_SYSTEM_PROMPT,
    build_refiner_user_prompt,
)
from evo_diagram.core.base_agent import (
    _is_provider_quota_exhausted,
    _is_transient_status_code,
    _status_code_from_exception,
)
from evo_diagram.core.llm_factory import LLMFactory
from evo_diagram.utils.io_utils import image_to_data_url
from evo_diagram.utils.llm_output import convert_json_output

logger = logging.getLogger(__name__)


def _coerce_to_edits(
    raw_list: List[Any],
) -> Tuple[List[EditOp], List[Dict[str, Any]]]:
    """Validate each item with the EditOp pydantic model.

    Returns ``(edits, rejections)``. ``EditOp`` is ``extra="forbid"``, so one
    drifted field name (``reason`` instead of ``rationale``) invalidates a whole
    item — and when every item drifts the caller used to receive a bare ``[]``,
    identical to "the model had nothing to propose". Rejections are handed back
    so the workflow can record them in the iteration log instead.
    """
    edits: List[EditOp] = []
    rejections: List[Dict[str, Any]] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            logger.warning("LLM edit %d is not a dict; skip", i)
            rejections.append(
                {
                    "raw": {"value": repr(item)[:200]},
                    "error": f"schema: item {i} is {type(item).__name__}, not an object",
                }
            )
            continue
        # Inject source so audit trail tags it correctly.
        item.setdefault("source", "llm")
        try:
            edit = EditOp.model_validate(item)
        except Exception as exc:  # pydantic ValidationError
            logger.warning(
                "LLM edit %d failed validation: %s; payload=%r", i, exc, item
            )
            rejections.append(
                {
                    "raw": item,
                    "error": f"schema: {str(exc).splitlines()[0][:200]}",
                }
            )
            continue
        edits.append(edit)
    return edits, rejections


def build_manifest_summary(
    manifest: Dict[str, Any],
    *,
    cap: int = MAX_MANIFEST_SUMMARY_ELEMENTS,
    pinned_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Produce a compact element list for the LLM prompt.

    Includes semantic IDs, container membership, and connector endpoints so
    visually similar background frames cannot be confused with nodes.
    ``pinned_ids`` are emitted first so elements tied
    to active verifier findings are not lost when the prompt is capped.

    The arrow exclusion is enforced here, not merely documented: an arrow's
    bbox in the prompt is an invitation to translate it, and translating an
    arrow moves the whole baked polyline away from both shapes it connects.
    ``op_set_position`` / ``op_set_size`` also refuse arrow targets, so the two
    layers agree.
    """
    pinned: List[Dict[str, Any]] = []
    regular: List[Dict[str, Any]] = []
    pinned_set = {value for value in (pinned_ids or []) if isinstance(value, str)}
    seen_ids: set[str] = set()
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return []
    semantic_ids = {
        render_id: semantic_id
        for semantic_id, render_id in (manifest.get("_meta", {}).get("id_map", {})).items()
    }
    bound_texts = {
        elem.get("containerId"): elem.get("text") or elem.get("originalText")
        for elem in elements
        if isinstance(elem, dict) and elem.get("type") == "text" and elem.get("containerId")
    }
    for elem in elements:
        if not isinstance(elem, dict) or elem.get("isDeleted"):
            continue
        if elem.get("type") == "arrow":
            continue
        try:
            x = float(elem.get("x", 0) or 0)
            y = float(elem.get("y", 0) or 0)
            w = float(elem.get("width", 0) or 0)
            h = float(elem.get("height", 0) or 0)
        except (TypeError, ValueError):
            continue
        entry: Dict[str, Any] = {
            "id": elem.get("id"),
            "type": elem.get("type"),
            "bbox": [x, y, w, h],
        }
        element_id = entry.get("id")
        if not isinstance(element_id, str) or not element_id or element_id in seen_ids:
            continue
        text = elem.get("text") or elem.get("originalText") or bound_texts.get(element_id)
        if text:
            entry["text"] = str(text)[:60]
        if element_id in semantic_ids:
            entry["semantic_id"] = semantic_ids[element_id]
        if elem.get("containerId"):
            entry["container_id"] = elem["containerId"]
        metadata = elem.get("meta") or {}
        for key in ("semantic_edge_id", "semantic_arrow_id"):
            if metadata.get(key):
                entry[key] = metadata[key]
        style = {
            key: elem[key]
            for key in ("fontSize", "fontFamily", "strokeColor", "backgroundColor", "strokeWidth", "strokeStyle")
            if key in elem
        }
        if style:
            entry["style"] = style
        if metadata.get("conceptFactAnchor"):
            entry["role"] = "fact_bearing_section_heading_keep_border"
        if elem.get("is_group"):
            entry["role"] = "group_background"
            if metadata.get("memberIds"):
                entry["member_ids"] = metadata["memberIds"]
        if elem.get("type") == "arrow":
            entry["source"] = metadata.get("source")
            entry["target"] = metadata.get("target")
        entry["opacity"] = elem.get("opacity", 100)
        if element_id in pinned_set:
            pinned.append(entry)
        else:
            regular.append(entry)
        seen_ids.add(element_id)
    regular.sort(key=lambda entry: entry.get("opacity", 100) == 0)
    return (pinned + regular)[:cap]


def _is_permanent_http_error(exc: BaseException) -> bool:
    """True for provider HTTP errors that outer retries cannot fix."""
    if _is_provider_quota_exhausted(exc):
        return True
    status_code = _status_code_from_exception(exc)
    if status_code is not None:
        return not _is_transient_status_code(status_code)

    cls_name = type(exc).__name__
    return cls_name in {
        "AuthenticationError",
        "BadRequestError",
        "NotFoundError",
        "PermissionDeniedError",
        "UnprocessableEntityError",
    }


class RefinerLLMAgent:
    """Single-shot VLM call wrapper that emits validated EditOps."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 5.0,
    ) -> None:
        if model is None:
            from evo_diagram.config.model_loader import ModelConfig

            ModelConfig.get_default().require_model_capabilities(
                "refiner", {"vision"}
            )
        self.model = model or LLMFactory.create_for_role("refiner")
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        # Set whenever a propose_edits() call exhausts retries OR exits early
        # on a permanent HTTP error. Workflow reads this to surface the failure
        # in state.errors / refiner_report.json — otherwise a silent empty list
        # looks identical to "LLM had nothing to propose".
        self.last_exhaustion_error: Optional[str] = None
        # Items the model proposed that failed EditOp validation. Same purpose
        # as last_exhaustion_error: an empty edit list must never be able to
        # mean two different things.
        self.last_rejected_edits: List[Dict[str, Any]] = []

    def propose_edits(
        self,
        image_path: str,
        chart_type: Optional[str],
        remaining_findings: List[Dict[str, Any]],
        critique: Optional[Dict[str, Any]],
        manifest_summary: List[Dict[str, Any]],
        previous_attempts: Optional[List[Dict[str, Any]]] = None,
        iteration: int = 1,
        max_iterations: int = 3,
        image_note: Optional[str] = None,
        design_constraints: str = "",
    ) -> List[EditOp]:
        """Run one VLM call; return validated EditOps. Empty list on parse failure."""
        # Reset for this call. Set below when retries exhaust or we exit early
        # on a permanent HTTP error.
        self.last_exhaustion_error = None
        self.last_rejected_edits = []

        data_url = image_to_data_url(image_path)
        user_text = build_refiner_user_prompt(
            chart_type=chart_type,
            remaining_findings=remaining_findings,
            critique=critique,
            manifest_summary=manifest_summary,
            previous_attempts=previous_attempts,
            iteration=iteration,
            max_iterations=max_iterations,
            image_note=image_note,
            design_constraints=design_constraints,
        )
        messages = [
            SystemMessage(content=REFINER_LLM_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                    {"type": "text", "text": user_text},
                ]
            ),
        ]

        delay = self.retry_delay_seconds
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.model.invoke(messages)
                if response is None or not getattr(response, "content", None):
                    raise ValueError("VLM returned empty response")
                raw = response.content
                if isinstance(raw, list):
                    raw = "".join(p.get("text", "") for p in raw if isinstance(p, dict))
                if not isinstance(raw, str):
                    raw = str(raw)

                try:
                    arr = convert_json_output(raw)
                except json.JSONDecodeError:
                    logger.warning(
                        "Could not extract JSON array from VLM response (attempt %d). "
                        "Raw head: %s",
                        attempt,
                        raw[:200],
                    )
                    raise ValueError("no JSON array found")
                if not isinstance(arr, list):
                    logger.warning(
                        "VLM response parsed but is not a JSON array (attempt %d). "
                        "Got type: %s",
                        attempt,
                        type(arr).__name__,
                    )
                    raise ValueError("VLM response is not a JSON array")

                edits, rejections = _coerce_to_edits(arr)
                self.last_rejected_edits = rejections
                logger.info(
                    "VLM proposed %d edits (%d valid after schema check)",
                    len(arr),
                    len(edits),
                )
                return edits

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Refiner LLM attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                # Permanent provider/client errors should stop immediately.
                # Transient 408/409/429/5xx/connection failures still get the
                # outer retry budget so refiner behavior matches BaseAgent.
                if _is_permanent_http_error(exc):
                    logger.warning(
                        "Refiner LLM exiting retry loop early — non-retryable "
                        "provider HTTP error"
                    )
                    break
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2

        # All retries exhausted — return empty list rather than crashing the
        # workflow; deterministic pass result is still valuable. Surface the
        # failure via last_exhaustion_error so the workflow's state.errors
        # captures it (otherwise the empty list looks like "no proposals").
        if last_exc is not None:
            logger.error("Refiner LLM exhausted retries: %s", last_exc)
            self.last_exhaustion_error = f"{type(last_exc).__name__}: {last_exc}"
        return []


def refine_with_llm(
    image_path: str,
    *,
    chart_type: Optional[str] = None,
    remaining_findings: Optional[List[Dict[str, Any]]] = None,
    critique: Optional[Dict[str, Any]] = None,
    manifest_summary: Optional[List[Dict[str, Any]]] = None,
    previous_attempts: Optional[List[Dict[str, Any]]] = None,
    iteration: int = 1,
    max_iterations: int = 3,
    image_note: Optional[str] = None,
    model: Optional[BaseChatModel] = None,
) -> List[EditOp]:
    """Convenience function — single LLM call, validated EditOps out."""
    agent = RefinerLLMAgent(model=model)
    return agent.propose_edits(
        image_path=image_path,
        chart_type=chart_type,
        remaining_findings=remaining_findings or [],
        critique=critique,
        manifest_summary=manifest_summary or [],
        previous_attempts=previous_attempts,
        iteration=iteration,
        max_iterations=max_iterations,
        image_note=image_note,
    )


__all__ = [
    "RefinerLLMAgent",
    "refine_with_llm",
    "build_manifest_summary",
]
