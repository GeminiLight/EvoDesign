from evaluation.metric_scorer import MetricScorer
from evaluation.metrics.base_metric import MetricResult
from evaluation.utils import METRIC_STATUS_ERROR, METRIC_STATUS_NOT_APPLICABLE


def test_metric_normalization_preserves_first_seen_order_and_deduplicates():
    scorer = object.__new__(MetricScorer)

    assert scorer._normalize_metrics(
        [
            "visual_aesthetics",
            "content_dimension",
            "visual_dimension",
            "concept_logic",
            "judge_preference",
            "unknown_metric",
        ]
    ) == [
        "visual_dimension",
        "content_dimension",
        "judge_preference",
    ]


def _scorer_with(metric_results):
    """Build a MetricScorer whose metrics return canned results."""
    scorer = object.__new__(MetricScorer)
    scorer.metrics_to_use = list(metric_results)
    scorer.metrics = {
        name: _StubMetric(name, result) for name, result in metric_results.items()
    }
    scorer.model = object()
    return scorer


class _StubMetric:
    def __init__(self, name, result):
        self.metric_name = name
        self._result = result

    def evaluate(self, **_kwargs):
        return self._result


def _evaluate(scorer, tmp_path, reference=None):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    return scorer.evaluate_image(
        str(image),
        "context",
        metrics_to_use=list(scorer.metrics_to_use),
        reference_image_path=reference,
    )


def test_out_of_rubric_score_is_converted_into_a_metric_error(tmp_path):
    """metric_scorer used to skip score<=0 while run_evaluation treated the same
    0 as a valid success. Both now agree: out-of-rubric means error."""
    scorer = _scorer_with(
        {
            "visual_dimension": MetricResult(
                metric_name="visual_dimension", score=0
            ),
            "content_dimension": MetricResult(
                metric_name="content_dimension", score=4
            ),
        }
    )

    results = _evaluate(scorer, tmp_path)

    visual = results["dimensions"]["visual"]["visual_dimension"]
    assert visual["error"]
    assert visual["status"] == METRIC_STATUS_ERROR
    assert results["metric_status"]["visual_dimension"] == METRIC_STATUS_ERROR
    # Only the in-rubric score contributes to the aggregate.
    assert results["average_score"] == 4


def test_not_applicable_metric_is_excluded_from_the_average(tmp_path):
    scorer = _scorer_with(
        {
            "judge_preference": MetricResult.not_applicable(
                "judge_preference", "reference_image_missing"
            ),
            "content_dimension": MetricResult(
                metric_name="content_dimension", score=4
            ),
        }
    )

    results = _evaluate(scorer, tmp_path)

    judge = results["dimensions"]["cognitive"]["judge_preference"]
    assert judge["status"] == METRIC_STATUS_NOT_APPLICABLE
    assert judge["error"] is None
    assert results["scores"]["judge_preference"] is None
    assert results["average_score"] == 4


def test_summary_counts_only_valid_scores():
    summary = MetricScorer.generate_summary(
        {
            "a.png": {
                "average_score": 4.0,
                "scores": {"content_dimension": 4, "judge_preference": None},
            },
            "b.png": {
                "average_score": 2.0,
                "scores": {"content_dimension": 2, "judge_preference": 3},
            },
        }
    )

    assert summary["metric_averages"]["content_dimension"] == 3.0
    assert summary["metric_averages"]["judge_preference"] == 3.0
    assert summary["metric_valid_counts"] == {
        "content_dimension": 2,
        "judge_preference": 1,
    }
    assert summary["metrics_without_scores"] == {"judge_preference": ["a.png"]}
