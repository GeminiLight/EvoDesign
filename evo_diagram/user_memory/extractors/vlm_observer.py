"""VLM Image Observer - Layer 1 of the preference learning system.

This module uses a Vision-Language Model to analyze before/after diagram images
and understand high-level visual differences BEFORE looking at JSON details.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from evo_diagram.core.llm_factory import LLMFactory
from ..schemas.observation_schemas import (
    CategoryObservation,
    VisualObservation,
)

logger = logging.getLogger(__name__)


class VLMImageObserver:
    """First layer: Use VLM to observe overall visual differences."""

    def __init__(self, vlm: Union[BaseChatModel, None] = None):
        """Initialize VLM observer.

        Args:
            vlm: Optional pre-configured VLM instance.
        """
        if vlm is None:
            from evo_diagram.core.llm_factory import LLMFactory
            logger.info("Creating VLM (role=refiner)")
            self.vlm = LLMFactory.create_for_role("refiner")
        else:
            self.vlm = vlm

    def observe_differences(
        self,
        model_image_path: Union[str, Path],
        user_image_path: Union[str, Path],
        task_description: str,
    ) -> VisualObservation:
        """Observe high-level visual differences between two diagrams.

        Args:
            model_image_path: Path to model-generated diagram image
            user_image_path: Path to user-adjusted diagram image
            task_description: Original task description

        Returns:
            VisualObservation with categorized changes
        """
        logger.info("Starting VLM observation of diagram differences")

        # Build prompt
        prompt = self._build_observation_prompt(task_description)

        # Encode images
        model_image_b64 = self._encode_image(model_image_path)
        user_image_b64 = self._encode_image(user_image_path)

        # Build message with images
        message_content = [
            {"type": "text", "text": prompt},
            {"type": "text", "text": "\n**Model-generated diagram (BEFORE user edit):**"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{model_image_b64}"},
            },
            {"type": "text", "text": "\n**User-adjusted diagram (AFTER user edit):**"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{user_image_b64}"},
            },
        ]

        # Invoke VLM
        response = self.vlm.invoke([HumanMessage(content=message_content)])

        # Parse response
        observation = self._parse_vlm_response(response.content)

        logger.info("VLM observation completed successfully")
        return observation

    def _build_observation_prompt(self, task_description: str) -> str:
        """Build VLM observation prompt."""
        return f"""You are analyzing a diagram that was automatically generated, then manually edited by a user.

**Original Task**: {task_description}

**Your Task**: Compare the two diagram images (BEFORE and AFTER) and describe the high-level differences. Focus on:

1. **Structural Changes**: Did the user add/remove/reorganize nodes or edges?
2. **Styling Changes**: Did the user change colors, shapes, fonts, or other visual properties?
3. **Layout Changes**: Did the user adjust positions, spacing, or overall arrangement?
4. **Semantic Changes**: Did the user modify labels, text content, or diagram semantics?

For each category, provide:
- **description**: Brief description of what changed (or "No significant changes")
- **magnitude**: "minor", "moderate", or "major"
- **affected_properties**: List of properties likely affected (e.g., ["color", "fill"], ["x", "y", "nodesep"], ["node_type", "edges"], ["text", "label"])

**IMPORTANT**: Also infer the **overall_intent** - why did the user make these changes? (e.g., "improve visual hierarchy", "fix overlaps", "clarify relationships", "personal aesthetic preference")

Respond in valid JSON format:
{{
  "structural_changes": {{
    "description": "string",
    "magnitude": "minor|moderate|major",
    "affected_properties": ["property1", "property2", ...]
  }},
  "styling_changes": {{
    "description": "string",
    "magnitude": "minor|moderate|major",
    "affected_properties": ["property1", "property2", ...]
  }},
  "layout_changes": {{
    "description": "string",
    "magnitude": "minor|moderate|major",
    "affected_properties": ["property1", "property2", ...]
  }},
  "semantic_changes": {{
    "description": "string",
    "magnitude": "minor|moderate|major",
    "affected_properties": ["property1", "property2", ...]
  }},
  "overall_intent": "string (infer why user made these changes)"
}}

Ensure your response is valid JSON only, with no markdown code blocks or extra text."""

    def _encode_image(self, image_path: Union[str, Path]) -> str:
        """Encode image to base64."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _parse_vlm_response(self, response: str) -> VisualObservation:
        """Parse VLM response into structured format."""
        # Extract JSON from response (handle markdown code blocks)
        json_str = response.strip()

        # Remove markdown code blocks if present
        if json_str.startswith("```"):
            # Find first { and last }
            json_start = json_str.find("{")
            json_end = json_str.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = json_str[json_start:json_end]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            message = f"Failed to parse VLM response as JSON: {e}"
            logger.error(message)
            logger.error(f"Response: {response}")
            raise ValueError(message) from e

        # Validate and create observation
        try:
            overall_intent = data["overall_intent"]
            if not isinstance(overall_intent, str) or not overall_intent.strip():
                raise ValueError("overall_intent must be a non-empty string")
            return VisualObservation(
                structural_changes=CategoryObservation(**data.get("structural_changes", {})),
                styling_changes=CategoryObservation(**data.get("styling_changes", {})),
                layout_changes=CategoryObservation(**data.get("layout_changes", {})),
                semantic_changes=CategoryObservation(**data.get("semantic_changes", {})),
                overall_intent=overall_intent.strip(),
            )
        except Exception as e:
            message = f"Failed to create VisualObservation from parsed data: {e}"
            logger.error(message)
            logger.error(f"Data: {data}")
            raise ValueError(message) from e
