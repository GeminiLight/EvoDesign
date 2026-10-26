"""
Content Dimension Metrics

Implementation of Content Dimension Aggregate Metric.
"""

from langchain_core.language_models import BaseChatModel
from .base_metric import ContentMetricBase
from evaluation.prompts.metric_prompts_merged import CONTENT_DIMENSION_PROMPT


class ContentDimensionMetric(ContentMetricBase):
    """
    Content Dimension Metric (Aggregate)

    Evaluates:
    1. Content Fidelity
    2. Concept Logic
    3. Semantic Relevance
    """

    def __init__(self, llm: BaseChatModel):
        super().__init__(
            llm=llm,
            metric_name="content_dimension",
            prompt_template=CONTENT_DIMENSION_PROMPT,
            requires_context=True,
        )
