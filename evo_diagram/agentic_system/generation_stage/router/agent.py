"""RouterAgent — lightweight classifier for diagram_type + palette_key.

Uses a small system prompt (~300 tokens) and task prompt (~200 tokens) to
classify the input text into two routing variables before the main pipeline
runs. This replaces the full EvoDiagram system prompt with a focused
classifier prompt, keeping cost low (~500-1500 tokens total per call).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.agentic_system.common.diagram_types import (
    DiagramTypeValidationError,
    normalize_supported_diagram_type,
)
from evo_diagram.core.base_agent import BaseAgent
from .prompts import get_router_system_prompt, get_router_task_prompt

logger = logging.getLogger(__name__)

# Default palette used when the router is intentionally disabled.
DEFAULT_PALETTE_KEY = "blush_sage"


class RouterClassificationError(RuntimeError):
    """Raised when an enabled router cannot produce a valid routing result."""


class RouterAgent(BaseAgent):
    """Classify input text into diagram_type, palette_key, and retrieval_query.

    Input: text_content + user_query
    Output: dict with diagram_type, palette_key, reasoning, retrieval_query

    This agent intentionally does NOT use the full EvoDiagram system prompt.
    It has its own small system prompt focused on classification.
    """

    def __init__(
        self,
        model: BaseChatModel,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            system_prompt=get_router_system_prompt(),
            task_prompt=get_router_task_prompt(),
            tools=[],
            exclude_think=kwargs.get("exclude_think", True),
            jsonalize_output=True,
            json_retry_attempts=3,
            strict_json_output=True,
        )

    def run(self, text_content: str, user_query: str) -> Dict[str, str]:
        """Run the router classifier.

        Args:
            text_content: The source text being diagrammed.
            user_query: The user's intent string.

        Returns:
            Dict with keys: diagram_type, palette_key, reasoning, retrieval_query.

        Raises:
            RouterClassificationError: If the model call fails or returns an
                invalid routing payload. Router failures are quality-critical
                and should not be converted into plausible diagram defaults.
        """
        from evo_diagram.agentic_system.generation_stage.styling.colorful import PALETTE_KEYS

        try:
            result = self.invoke({
                "text_content": text_content or "",
                "user_query": user_query or "N/A",
            })
        except Exception as exc:
            raise RouterClassificationError("Router classification failed") from exc

        if not isinstance(result, dict):
            raise RouterClassificationError(
                f"Router returned {type(result).__name__}; expected a JSON object"
            )

        diagram_type = str(result.get("diagram_type") or "").strip()
        try:
            diagram_type = normalize_supported_diagram_type(diagram_type)
        except DiagramTypeValidationError as exc:
            if not diagram_type:
                raise RouterClassificationError("Router output missing diagram_type") from exc
            raise RouterClassificationError(str(exc)) from exc

        palette_key = str(result.get("palette_key") or "").strip()
        if palette_key not in PALETTE_KEYS:
            raise RouterClassificationError(
                f"Router output palette_key={palette_key!r} is not in the palette catalog"
            )

        reasoning = str(result.get("reasoning") or "")
        retrieval_query = str(result.get("retrieval_query") or "")

        logger.info(
            "[RouterAgent] Classified: diagram_type=%s, palette_key=%s",
            diagram_type, palette_key,
        )

        return {
            "diagram_type": diagram_type,
            "palette_key": palette_key,
            "reasoning": reasoning,
            "retrieval_query": retrieval_query,
        }


__all__ = ["RouterAgent", "RouterClassificationError", "DEFAULT_PALETTE_KEY"]
