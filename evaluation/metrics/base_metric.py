"""
Base Metric Module

Provides the base abstract class for all evaluation metrics.
"""

import json
import re
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from evaluation.utils import (
    METRIC_STATUS_ERROR,
    METRIC_STATUS_NOT_APPLICABLE,
    METRIC_STATUS_SCORED,
    SCORE_MAX,
    SCORE_MIN,
    is_valid_score,
)

logger = logging.getLogger(__name__)


@dataclass
class MetricResult:
    """Evaluation result data class.

    ``score`` is ``None`` whenever no score was produced (error or N/A). A
    failed metric must never be represented by an in-band ``0``: the rubric is
    1-5, so a 0 would silently drag averages below the scale floor.
    """
    metric_name: str
    score: Optional[int]
    sub_scores: Dict[str, int] = field(default_factory=dict)
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""
    error: Optional[str] = None
    status: str = METRIC_STATUS_SCORED
    na_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        payload = {
            "metric": self.metric_name,
            "score": self.score,
            "sub_scores": self.sub_scores,
            "reason": self.reason,
            "details": self.details,
            "error": self.error,
            "status": self.status,
        }
        if self.na_reason:
            payload["na_reason"] = self.na_reason
        return payload

    @classmethod
    def error_result(cls, metric_name: str, error_msg: str) -> "MetricResult":
        """Create error result"""
        return cls(
            metric_name=metric_name,
            score=None,
            error=error_msg,
            status=METRIC_STATUS_ERROR,
        )

    @classmethod
    def not_applicable(cls, metric_name: str, reason: str) -> "MetricResult":
        """Create a not-applicable result.

        Unlike an error this is an expected, permanent condition (for example a
        comparative metric without its reference image). It carries no score and
        must be excluded from aggregates rather than degraded into one.
        """
        return cls(
            metric_name=metric_name,
            score=None,
            reason=f"Not applicable: {reason}",
            status=METRIC_STATUS_NOT_APPLICABLE,
            na_reason=reason,
        )


class BaseMetric(ABC):
    """
    Base metric class

    All specific metric classes should inherit from this class and implement the corresponding methods.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        metric_name: str,
        prompt_template: str,
        requires_context: bool = True,
    ):
        """
        Initialize metric

        Args:
            llm: LangChain chat model instance
            metric_name: Metric name
            prompt_template: Prompt template
            requires_context: Whether original text content is required
        """
        self.llm = llm
        self.metric_name = metric_name
        self.prompt_template = prompt_template
        self.requires_context = requires_context

    def evaluate(
        self,
        image_base64: str,
        image_mime_type: str = "image/png",
        context_text: str = "",
    ) -> MetricResult:
        """
        Execute evaluation

        Args:
            image_base64: Base64 encoded image
            image_mime_type: Image MIME type
            context_text: Original text content

        Returns:
            MetricResult: Evaluation result
        """
        try:
            # Build prompt
            prompt = self._build_prompt(context_text)

            # Build message (including image)
            message = self._build_message(prompt, image_base64, image_mime_type)

            # Call LLM
            logger.info(f"Evaluating metric: {self.metric_name}")
            response = self.llm.invoke([message])
            raw_response = response.content

            # Debug: Log response details
            logger.debug(f"LLM response type: {type(raw_response)}")
            logger.debug(f"LLM response length: {len(str(raw_response)) if raw_response else 0}")
            logger.debug(f"LLM response preview: {str(raw_response)[:200]}")

            # Parse response
            result = self._parse_response(raw_response)
            result.raw_response = raw_response

            return result

        except Exception as e:
            logger.error(f"Error evaluating {self.metric_name}: {e}")
            logger.exception(f"Full exception traceback for {self.metric_name}:")
            return MetricResult.error_result(self.metric_name, str(e))

    def _build_prompt(self, context_text: str) -> str:
        """Build prompt"""
        if self.requires_context:
            return self.prompt_template.format(context=context_text)
        return self.prompt_template

    def _build_message(
        self,
        prompt: str,
        image_base64: str,
        image_mime_type: str,
    ) -> HumanMessage:
        """Build message containing image"""
        return HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_mime_type};base64,{image_base64}",
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                },
            ]
        )

    def _parse_response(self, response: str) -> MetricResult:
        """
        Parse LLM response

        Attempt to extract JSON-formatted evaluation results from the response
        """
        try:
            # Try to extract JSON block
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to parse entire response directly
                json_str = response

            # Clean potential issues
            json_str = json_str.strip()

            # Parse JSON
            data = json.loads(json_str)

            if not isinstance(data, dict):
                return MetricResult.error_result(
                    self.metric_name,
                    f"Parsed response is {type(data).__name__}, expected a JSON object",
                )

            details = data.get("details", {})
            if not isinstance(details, dict):
                details = {"details": details}

            extras = {
                k: v for k, v in data.items()
                if k not in ["metric", "score", "sub_scores", "reason", "details"]
            }
            if extras:
                details.update(extras)

            score = self._coerce_score(data.get("score"))
            if score is None:
                return MetricResult.error_result(
                    self.metric_name,
                    f"Score {data.get('score')!r} is missing or outside the "
                    f"{SCORE_MIN}-{SCORE_MAX} rubric",
                )

            return MetricResult(
                metric_name=self.metric_name,
                score=score,
                sub_scores=data.get("sub_scores", {}),
                reason=data.get("reason", ""),
                details=details,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            # Try to extract score from non-JSON response
            return self._fallback_parse(response)

    @staticmethod
    def _coerce_score(raw: Any) -> Optional[int]:
        """Return *raw* as an in-rubric integer score, or ``None`` if invalid."""
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            score = int(raw)
        except (TypeError, ValueError):
            return None
        return score if is_valid_score(score) else None

    def _fallback_parse(self, response: str) -> MetricResult:
        """
        Fallback parsing method

        When JSON parsing fails, attempt to extract score from text. A failure to
        extract anything returns an explicit error result: silently emitting a
        score of 0 would inject a value below the 1-5 rubric into the averages
        while still reporting ``status: success``.
        """
        # Try to match patterns like "score": 5
        score_patterns = [
            r'"score"\s*:\s*(\d+)',
            r'Score[：:]\s*(\d+)',
            r'(\d+)\s*[/]\s*5',
        ]

        preview = str(response)[:200]

        for pattern in score_patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                score = self._coerce_score(match.group(1))
                if score is None:
                    return MetricResult.error_result(
                        self.metric_name,
                        f"Fallback parse extracted out-of-rubric score "
                        f"{match.group(1)!r} (expected {SCORE_MIN}-{SCORE_MAX}). "
                        f"Response preview: {preview}",
                    )
                return MetricResult(
                    metric_name=self.metric_name,
                    score=score,
                    reason=f"(Parsed from text) {preview}...",
                    details={"parsed_by": "fallback_regex"},
                )

        return MetricResult.error_result(
            self.metric_name,
            "Response was neither valid JSON nor did it contain a recognizable "
            f"score. Response preview: {preview}",
        )


class ContentMetricBase(BaseMetric):
    """Content dimension metric base class"""
    pass


class VisualMetricBase(BaseMetric):
    """Visual dimension metric base class"""

    def __init__(self, llm: BaseChatModel, metric_name: str, prompt_template: str, requires_context: bool = True):
        # Visual metrics now also require original text to evaluate whether design serves the content
        super().__init__(llm, metric_name, prompt_template, requires_context=requires_context)


class CognitiveMetricBase(BaseMetric):
    """Cognitive dimension metric base class"""
    pass
