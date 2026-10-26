"""
Cognitive Dimension Metrics

Implementation of Cognitive Dimension Aggregate Metric.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from .base_metric import CognitiveMetricBase, MetricResult
from evaluation.prompts.metric_prompts_merged import (
    COGNITIVE_DIMENSION_PROMPT,
    JUDGE_PREFERENCE_PROMPT,
)


class CognitiveDimensionMetric(CognitiveMetricBase):
    """
    Cognitive Dimension Metric (Aggregate)

    Evaluates:
    1. Cognitive Ease
    2. Comprehension Accuracy
    3. Self-contained Explanation
    """

    def __init__(self, llm: BaseChatModel):
        super().__init__(
            llm=llm,
            metric_name="cognitive_dimension",
            prompt_template=COGNITIVE_DIMENSION_PROMPT,
            requires_context=True,
        )


class JudgePreferenceMetric(CognitiveMetricBase):
    """
    Judge Preference Metric (Comparative)

    Compares the original diagram (A) and the generated diagram (B).
    """

    #: Recorded on the result when the comparison cannot be performed.
    MISSING_REFERENCE_REASON = "reference_image_missing"

    def __init__(self, llm: BaseChatModel):
        super().__init__(
            llm=llm,
            metric_name="judge_preference",
            prompt_template=JUDGE_PREFERENCE_PROMPT,
            requires_context=True,
        )

    def evaluate(
        self,
        image_base64: str,
        image_mime_type: str = "image/png",
        context_text: str = "",
        reference_image_base64: str = None,
        reference_image_mime_type: str = "image/png",
    ) -> MetricResult:
        """
        Override parent method to support reference image (Original Diagram).

        The 1-5 anchors of this metric are defined purely in relative terms
        ("Image A is preferable" ... "Image B is preferable"). Without Image A
        the scale has no meaning, so the metric reports N/A instead of silently
        switching to absolute scoring and contributing a differently-defined
        number to the same average.
        """
        if not reference_image_base64:
            return MetricResult.not_applicable(
                self.metric_name,
                self.MISSING_REFERENCE_REASON,
            )

        try:
            prompt_text = self._build_prompt(context_text)

            content_list = []

            content_list.append({
                "type": "text",
                "text": "Image A: Original Diagram (Ground Truth Reference):",
            })
            content_list.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{reference_image_mime_type};base64,{reference_image_base64}",
                },
            })

            content_list.append({
                "type": "text",
                "text": "Image B: Generated Diagram (Evaluation Target):",
            })
            content_list.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image_mime_type};base64,{image_base64}",
                },
            })

            content_list.append({
                "type": "text",
                "text": prompt_text,
            })

            message = HumanMessage(content=content_list)
            response = self.llm.invoke([message])
            return self._parse_response(response.content)
        except Exception as e:
            return MetricResult.error_result(self.metric_name, str(e))
