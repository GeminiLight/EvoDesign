"""DNA Image Extractor - Extract design rules from a reference image using a VLM.

Given a single design/diagram image, extracts concrete, actionable rules organized
into three cabins: structure, style, and layout.
"""

import base64
import json
import logging
from typing import Optional, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """You are a diagram and visual design expert. Analyze the provided image carefully.

Extract concrete, actionable design rules that this image demonstrates. Organize them into three categories:
- structure: node naming conventions, connection/arrow semantics, hierarchy depth, grouping patterns
- style: color palette, line weights, corner shapes, font choices, icon usage, visual properties
- layout: spacing rhythms, alignment patterns, flow direction, cluster arrangement, positioning

Return ONLY valid JSON with no markdown formatting or extra text:
{
  "rules": [
    {
      "cabin": "structure",
      "title": "Short rule name (max 8 words)",
      "preview": "One concrete sentence describing the rule"
    }
  ]
}

Extract 2-5 rules total across all categories. Only include rules clearly demonstrated in the image.
If a category has no clear patterns, omit it."""


class DnaRuleExtractionError(RuntimeError):
    """Raised when VLM-based DNA rule extraction cannot produce trusted output."""


class DnaImageExtractor:
    """Extract design DNA rules from a single reference image using a VLM."""

    def __init__(self, vlm: Optional[BaseChatModel] = None):
        """Initialize extractor.

        Args:
            vlm: Optional pre-configured VLM instance.
        """
        if vlm is None:
            from evo_diagram.core.llm_factory import LLMFactory
            logger.info("Creating VLM (role=refiner)")
            self.vlm = LLMFactory.create_for_role("refiner")
        else:
            self.vlm = vlm

    def extract_rules(
        self,
        image_bytes: Union[bytes, bytearray],
        mime_type: str = "image/png",
    ) -> list[dict]:
        """Extract design rules from an image.

        Args:
            image_bytes: Raw image bytes (PNG, JPEG, WebP).
            mime_type: MIME type of the image, e.g. "image/png".

        Returns:
            List of dicts with keys: cabin (str), title (str), preview (str).
            Returns [] only when the VLM returns a valid empty rule list.

        Raises:
            DnaRuleExtractionError: If the VLM call fails or returns malformed JSON.
        """
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        message_content = [
            {"type": "text", "text": _EXTRACTION_PROMPT},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{b64}"},
            },
        ]

        try:
            response = self.vlm.invoke([HumanMessage(content=message_content)])
        except Exception as exc:
            logger.error("VLM extraction failed: %s", exc)
            raise DnaRuleExtractionError("DNA rule extraction failed") from exc

        response_content = response.content
        if not isinstance(response_content, str):
            raise DnaRuleExtractionError("DNA extractor returned invalid response")

        rules = self._parse_response(response_content)
        logger.info("DNA extraction completed: %d rules extracted", len(rules))
        return rules

    def _parse_response(self, response: str) -> list[dict]:
        """Parse VLM JSON response into a list of rule dicts."""
        json_str = response.strip()

        # Strip markdown code fences if present
        if json_str.startswith("```"):
            start = json_str.find("{")
            end = json_str.rfind("}") + 1
            if start != -1 and end > start:
                json_str = json_str[start:end]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse VLM response as JSON: %s", exc)
            raise DnaRuleExtractionError("DNA extractor returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise DnaRuleExtractionError("DNA extractor returned invalid JSON")

        rules = data.get("rules", [])
        if not isinstance(rules, list):
            raise DnaRuleExtractionError("DNA extractor returned invalid rules")

        valid = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            cabin = rule.get("cabin", "")
            title = (rule.get("title") or "").strip()
            preview = (rule.get("preview") or "").strip()
            if cabin in ("structure", "style", "layout") and title and preview:
                valid.append({"cabin": cabin, "title": title, "preview": preview})

        if rules and not valid:
            raise DnaRuleExtractionError("DNA extractor returned no valid rules")

        return valid
