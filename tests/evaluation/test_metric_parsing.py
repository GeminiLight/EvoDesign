"""Contract tests for metric response parsing (1-5 rubric enforcement)."""

from __future__ import annotations

import pytest

from evaluation.metrics.base_metric import BaseMetric, MetricResult
from evaluation.metrics.cognitive_metrics import JudgePreferenceMetric
from evaluation.utils import (
    METRIC_STATUS_ERROR,
    METRIC_STATUS_NOT_APPLICABLE,
    METRIC_STATUS_SCORED,
)


class _StubMetric(BaseMetric):
    def __init__(self):
        super().__init__(
            llm=None,
            metric_name="visual_dimension",
            prompt_template="{context}",
            requires_context=True,
        )


@pytest.fixture()
def metric():
    return _StubMetric()


def test_valid_json_response_is_scored(metric):
    result = metric._parse_response('{"score": 4, "reason": "ok"}')

    assert result.score == 4
    assert result.error is None
    assert result.status == METRIC_STATUS_SCORED


def test_unparseable_response_returns_an_error_not_a_zero(metric):
    """The old fallback returned score=0 with error=None, which then passed the
    success check and entered the averages below the 1-5 floor."""
    result = metric._parse_response("The diagram is quite nice, I think.")

    assert result.score is None
    assert result.error is not None
    assert result.status == METRIC_STATUS_ERROR


def test_truncated_json_before_the_score_returns_an_error(metric):
    result = metric._parse_response('{"details": {"a": 1, "b')

    assert result.score is None
    assert result.error is not None


def test_truncated_json_after_the_score_is_salvaged_but_marked(metric):
    """A response truncated after the score field still carries a genuine score,
    but the salvage is recorded so the sub-score loss is auditable."""
    result = metric._parse_response('{"score": 4, "details": {"a": 1,')

    assert result.score == 4
    assert result.details.get("parsed_by") == "fallback_regex"
    assert result.sub_scores == {}


def test_fallback_regex_extracts_an_in_rubric_score(metric):
    result = metric._parse_response('Overall the answer is "score": 3 for this one')

    assert result.score == 3
    assert result.error is None
    assert result.details.get("parsed_by") == "fallback_regex"


def test_fallback_out_of_rubric_score_is_rejected(metric):
    result = metric._parse_response("I would give Score: 0 here")

    assert result.score is None
    assert result.error is not None


@pytest.mark.parametrize("raw", [0, 6, -1, None, "high", True])
def test_json_scores_outside_the_rubric_are_rejected(metric, raw):
    result = metric._parse_response('{"score": %s}' % _as_json(raw))

    assert result.score is None
    assert result.error is not None


def _as_json(value):
    import json

    return json.dumps(value)


def test_error_result_carries_no_score():
    result = MetricResult.error_result("visual_dimension", "boom")

    assert result.score is None
    assert result.to_dict()["status"] == METRIC_STATUS_ERROR


def test_judge_preference_without_reference_is_not_applicable():
    """The 1-5 anchors are defined as 'A vs B'; without A the scale changes
    meaning, so the metric must report N/A instead of scoring absolutely."""
    metric = JudgePreferenceMetric(llm=None)

    result = metric.evaluate(
        image_base64="Zm9v",
        context_text="text",
        reference_image_base64=None,
    )

    assert result.status == METRIC_STATUS_NOT_APPLICABLE
    assert result.na_reason == "reference_image_missing"
    assert result.score is None
    assert result.error is None
    assert result.to_dict()["na_reason"] == "reference_image_missing"
