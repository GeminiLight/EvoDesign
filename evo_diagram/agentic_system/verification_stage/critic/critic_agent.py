"""Single-shot VLM critic agent.

This module deliberately stays small: build one multimodal HumanMessage,
invoke the model once, parse the JSON, return a Critique. No tool-calling,
no iteration — that's what refinement_stage is for.

The PNG is read as raw bytes (``open(path, "rb").read()``) and base64-
encoded for the API's ``image_url`` payload. We do NOT use any image-
display tool here — Claude Code never visually inspects the PNG; only the
remote VLM does.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from .prompts import VERIFIER_CRITIC_SYSTEM_PROMPT, build_user_prompt
from evo_diagram.core.base_agent import _is_provider_quota_exhausted
from evo_diagram.core.llm_factory import LLMFactory
from evo_diagram.utils.io_utils import image_to_data_url
from evo_diagram.utils.llm_output import convert_json_output
from ..state import Critique, DimensionCritique

logger = logging.getLogger(__name__)


def review_image_edge_limit(image_path: str, manifest: dict | None) -> int | None:
    """Reduce oversampled exports, keeping the smallest visible text >=16px.

    Dense or imported scenes with unknown text geometry keep full resolution.
    This policy changes only qualitative critic input, never refiner coordinates.
    """
    from PIL import Image

    with Image.open(image_path) as image:
        width, height = image.size
    if max(width, height) <= 3072:
        return 3072
    elements = [e for e in (manifest or {}).get("elements", [])
                if not e.get("isDeleted") and e.get("opacity", 100) > 0]
    labels = [e for e in elements if e.get("type") == "text" and e.get("text", "").strip()]
    if not labels:
        return None
    try:
        min_font = min(float(e["fontSize"]) for e in labels)
        left = min(float(e["x"]) for e in elements)
        top = min(float(e["y"]) for e in elements)
        right = max(float(e["x"]) + abs(float(e["width"])) for e in elements)
        bottom = max(float(e["y"]) + abs(float(e["height"])) for e in elements)
        scale = min(width / (right - left), height / (bottom - top))
        font_pixels = min_font * scale
        if not math.isfinite(font_pixels) or font_pixels <= 0:
            return None
        return max(3072, math.ceil(max(width, height) * 16 / font_pixels))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _coerce_dimension(payload: Any) -> DimensionCritique:
    """Be defensive: clamp scores, default missing arrays to []."""
    if not isinstance(payload, dict):
        return DimensionCritique(score=0.0)
    try:
        score = float(payload.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(10.0, score))

    def _as_str_list(key: str) -> list[str]:
        raw = payload.get(key)
        if isinstance(raw, list):
            return [str(x) for x in raw if x is not None]
        if isinstance(raw, str):
            return [raw]
        return []

    return DimensionCritique(
        score=score,
        strengths=_as_str_list("strengths"),
        weaknesses=_as_str_list("weaknesses"),
        suggestions=_as_str_list("suggestions"),
    )


def _coerce_critique(data: Dict[str, Any], raw: Optional[str]) -> Critique:
    """Turn the parsed dict into a strict Critique pydantic model."""
    structure = _coerce_dimension(data.get("structure"))
    styling = _coerce_dimension(data.get("styling"))
    layout = _coerce_dimension(data.get("layout"))

    overall: float
    try:
        overall = float(data.get("overall_score", 0.0))
    except (TypeError, ValueError):
        overall = 0.0
    if overall <= 0.0:
        # Reasonable fallback if the model omits overall — average the three.
        overall = (structure.score + styling.score + layout.score) / 3
    overall = max(0.0, min(10.0, overall))

    summary = data.get("summary", "") or ""
    if not isinstance(summary, str):
        summary = str(summary)

    return Critique(
        structure=structure,
        styling=styling,
        layout=layout,
        overall_score=overall,
        summary=summary,
        constraint_violations=(
            [str(value) for value in data.get("constraint_violations", []) if value]
            if isinstance(data.get("constraint_violations", []), list)
            else [str(data["constraint_violations"])]
        ),
        raw_response=raw,
    )


class VerifierCriticAgent:
    """Wraps the VLM for the verifier's single subjective-critic call."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 5.0,
        max_image_edge: int | None = 3072,
    ) -> None:
        if model is None:
            from evo_diagram.config.model_loader import ModelConfig

            ModelConfig.get_default().require_model_capabilities(
                "verifier", {"vision"}
            )
        self.model = model or LLMFactory.create_for_role("verifier")
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.max_image_edge = max_image_edge

    def _build_messages(
        self,
        image_path: str,
        chart_type: Optional[str],
        source_text: Optional[str],
        objective_summary: Optional[Dict[str, Any]],
    ) -> list:
        data_url = image_to_data_url(image_path, max_edge=self.max_image_edge)
        user_text = build_user_prompt(
            chart_type=chart_type,
            source_text=source_text,
            objective_summary=objective_summary,
        )
        human = HumanMessage(
            content=[
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                {"type": "text", "text": user_text},
            ]
        )
        return [SystemMessage(content=VERIFIER_CRITIC_SYSTEM_PROMPT), human]

    def critique(
        self,
        image_path: str,
        chart_type: Optional[str] = None,
        source_text: Optional[str] = None,
        objective_summary: Optional[Dict[str, Any]] = None,
    ) -> Critique:
        """Run one VLM call → Critique. Errors raise; caller decides recovery."""
        started = time.monotonic()
        messages = self._build_messages(
            image_path, chart_type, source_text, objective_summary
        )

        last_error: Optional[Exception] = None
        delay = self.retry_delay_seconds
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.model.invoke(messages)
                if response is None or not getattr(response, "content", None):
                    raise ValueError("VLM returned an empty response")
                raw = response.content
                if isinstance(raw, list):
                    # Some langchain backends wrap multimodal as parts list.
                    raw = "".join(
                        part.get("text", "")
                        for part in raw
                        if isinstance(part, dict)
                    )
                if not isinstance(raw, str):
                    raw = str(raw)

                try:
                    data = convert_json_output(raw)
                except json.JSONDecodeError:
                    raise ValueError("Could not extract JSON object from VLM response")
                if not isinstance(data, dict):
                    raise ValueError("VLM response is not a JSON object")
                critique = _coerce_critique(data, raw)
                critique.call_metrics = {
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "attempts": attempt,
                    "max_image_edge": self.max_image_edge,
                    "usage": getattr(response, "usage_metadata", None) or {},
                }
                return critique

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "VLM critique attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                if _is_provider_quota_exhausted(exc):
                    break
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2

        assert last_error is not None
        raise last_error


__all__ = ["VerifierCriticAgent"]
