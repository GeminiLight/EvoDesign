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


@pytest.mark.parametrize(
    "raw,expected",
    [
        (4, 4),
        (4.0, 4),
        (4.4, 4),
        (4.5, 5),  # half-up, not banker's rounding
        (4.7, 5),  # previously truncated to 4 by int()
        ("4", 4),
        (" 4.5 ", 5),
        ("4.7", 5),
        (1, 1),
        (5.0, 5),
    ],
)
def test_coerce_score_rounds_numbers_and_numeric_strings_consistently(raw, expected):
    assert BaseMetric._coerce_score(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, True, False, 0, 0.6, 5.4, 6, "0", "5.5", "four", "4/5", "", float("nan"), float("inf"), [4]],
)
def test_coerce_score_rejects_out_of_rubric_or_non_numeric(raw):
    assert BaseMetric._coerce_score(raw) is None


def test_json_float_score_is_rounded_not_truncated(metric):
    result = metric._parse_response('{"score": 4.7, "reason": "ok"}')

    assert result.score == 5
    assert result.status == METRIC_STATUS_SCORED


def test_fallback_prefers_labelled_overall_score_over_first_fraction(metric):
    text = "Layout: 2/5. Colour: 3/5.\nOverall score: 4 out of 5"

    result = metric._parse_response(text)

    assert result.score == 4
    assert result.details == {"parsed_by": "fallback_regex"}


def test_fallback_rejects_conflicting_unlabelled_fractions(metric):
    result = metric._parse_response("Layout 2/5, colour 4/5.")

    assert result.score is None
    assert result.status == METRIC_STATUS_ERROR
    assert "conflicting" in result.error


def test_fallback_accepts_a_single_unlabelled_fraction(metric):
    result = metric._parse_response("I would rate this 3/5 overall-ish.")

    assert result.score == 3


def test_list_content_blocks_are_flattened_to_text(metric):
    blocks = [
        {"type": "text", "text": '{"score": 3, '},
        {"type": "text", "text": '"reason": "fine"}'},
    ]

    result = metric._parse_response(blocks)

    assert result.score == 3
    assert result.status == METRIC_STATUS_SCORED


def test_evaluate_handles_list_content_from_the_llm():
    class _Response:
        content = [{"type": "text", "text": '{"score": 2, "reason": "x"}'}]

    class _LLM:
        def invoke(self, _messages):
            return _Response()

    metric = _StubMetric()
    metric.llm = _LLM()

    result = metric.evaluate(image_base64="AA==", image_mime_type="image/png", context_text="c")

    assert result.score == 2
    assert result.raw_response == '{"score": 2, "reason": "x"}'
