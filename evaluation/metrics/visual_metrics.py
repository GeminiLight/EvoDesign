"""
Visual Dimension Metrics

Implementation of Visual Dimension Aggregate Metric.
"""

from langchain_core.language_models import BaseChatModel
from .base_metric import VisualMetricBase
from evaluation.prompts.metric_prompts_merged import VISUAL_DIMENSION_PROMPT


class VisualDimensionMetric(VisualMetricBase):
    """
    Visual Dimension Metric (Aggregate)

    Evaluates:
    1. Visual Aesthetics
    2. Styling Consistency
    3. Flow Coherence
    4. Space Balance
    """

    def __init__(self, llm: BaseChatModel):
        super().__init__(
            llm=llm,
            metric_name="visual_dimension",
            prompt_template=VISUAL_DIMENSION_PROMPT,
        )
