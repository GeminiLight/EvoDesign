# Metrics module
from .base_metric import BaseMetric, MetricResult
from .content_metrics import ContentDimensionMetric
from .visual_metrics import VisualDimensionMetric
from .cognitive_metrics import CognitiveDimensionMetric, JudgePreferenceMetric

__all__ = [
    # Base
    "BaseMetric",
    "MetricResult",
    # Dimensions
    "ContentDimensionMetric",
    "VisualDimensionMetric",
    "CognitiveDimensionMetric",
    "JudgePreferenceMetric",
]

# Metric factory dictionary
METRIC_CLASSES = {
    # Dimensions
    "content_dimension": ContentDimensionMetric,
    "visual_dimension": VisualDimensionMetric,
    "cognitive_dimension": CognitiveDimensionMetric,
    "judge_preference": JudgePreferenceMetric,
}


def get_metric_class(metric_name: str):
    """Get metric class"""
    if metric_name not in METRIC_CLASSES:
        raise ValueError(f"Unknown metric: {metric_name}")
    return METRIC_CLASSES[metric_name]


def get_all_metric_classes() -> dict:
    """Get all metric classes"""
    return METRIC_CLASSES.copy()
