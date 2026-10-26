"""Judge k-run resampling: median aggregation, failure rules, signature and reuse.

The judge endpoint enforces temperature=1, so repeated scoring of the same
diagram carries sampling variance. ``--judge-runs k`` evaluates each
(sample, metric) pair k independent times and stores the median of the valid
runs. These tests use scripted fake metrics (no model calls) and cover:

* k=1 behaves exactly as before (no ``judge_runs`` field, one call);
* k=3 stores the median plus raw values / mean / std;
* partial failures aggregate over valid scores only, and a minority of valid
  runs (< ceil(k/2)) records an error;
* all-N/A stays ``not_applicable`` (a permanent condition, not a failure);
* ``judge_runs`` is part of the run signature: changing k invalidates stored
  results, while pre-resampling files remain reusable at the default k=1;
* resume reuses a k-matching result and re-runs on k change;
* the aggregator reports within-sample judge variance (retest reliability).
"""

from __future__ import annotations

import json
import sys

import pytest

from evaluation import path_resolver, run_evaluation
from evaluation.analysis.analysis_results import EvaluationAnalyzer
from evaluation.metric_scorer import MetricScorer, aggregate_judge_runs
from evaluation.metrics.base_metric import MetricResult
from evaluation.utils import (
    METRIC_STATUS_ERROR,
    METRIC_STATUS_NOT_APPLICABLE,
    build_run_signature,
)


METRIC = "content_dimension"

BASE_SIGNATURE = {
    "signature_version": 1,
    "judge_role": "eval",
    "judge_model": "kimi-k3",
    "judge_temperature": 1,
    "judge_max_tokens": 8000,
    "metrics": [METRIC],
    "prompt_versions": {METRIC: "abc123abc123"},
}


# ── scripted fake judge ──────────────────────────────────────────────────────


class ScriptedMetric:
    """Returns canned MetricResults (or raises canned exceptions) in order."""

    def __init__(self, name, script):
        self.metric_name = name
        self._script = list(script)
        self.calls = 0

    def evaluate(self, **_kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _scorer(script, metric=METRIC):
    scorer = object.__new__(MetricScorer)
    scorer.metrics_to_use = [metric]
    scorer.metrics = {metric: ScriptedMetric(metric, script)}
    scorer.model = object()
    return scorer


def _score(value, reason="", sub_scores=None):
    return MetricResult(
        metric_name=METRIC, score=value, reason=reason, sub_scores=sub_scores or {}
    )


def _error(message="judge call failed"):
    return MetricResult.error_result(METRIC, message)


def _na():
    return MetricResult.not_applicable(METRIC, "reference_image_missing")


def _evaluate(scorer, tmp_path, judge_runs):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    return scorer.evaluate_image(
        str(image), "context", metrics_to_use=[METRIC], judge_runs=judge_runs
    )


def _metric_entry(results):
    return results["dimensions"]["content"][METRIC]


# ── aggregation semantics ────────────────────────────────────────────────────


def test_single_judge_run_behaves_as_before(tmp_path):
    scorer = _scorer([_score(4)])

    results = _evaluate(scorer, tmp_path, judge_runs=1)

    entry = _metric_entry(results)
    assert entry["score"] == 4
    assert entry["status"] == "scored"
    assert "judge_runs" not in entry, "k=1 output must stay byte-compatible"
    assert results["scores"][METRIC] == 4
    assert results["average_score"] == 4
    assert scorer.metrics[METRIC].calls == 1


def test_three_judge_runs_take_the_median(tmp_path):
    scorer = _scorer([_score(4), _score(5), _score(4)])

    results = _evaluate(scorer, tmp_path, judge_runs=3)

    entry = _metric_entry(results)
    assert entry["score"] == 4
    assert entry["status"] == "scored"
    assert scorer.metrics[METRIC].calls == 3

    runs = entry["judge_runs"]
    assert runs["k"] == 3
    assert runs["values"] == [4, 5, 4]
    assert runs["n_valid"] == 3
    assert runs["median"] == 4
    assert runs["mean"] == pytest.approx(4.3333, abs=1e-3)
    # Sample standard deviation (n-1) of [4, 5, 4].
    assert runs["std"] == pytest.approx(0.5774, abs=1e-3)
    assert results["scores"][METRIC] == 4


def test_even_number_of_valid_runs_uses_the_lower_median(tmp_path):
    # One failed run leaves two valid scores; the lower of the two central
    # values keeps the aggregated score an integer (conservative choice).
    scorer = _scorer([_score(4), _error(), _score(5)])

    results = _evaluate(scorer, tmp_path, judge_runs=3)

    entry = _metric_entry(results)
    assert entry["score"] == 4
    assert entry["status"] == "scored"
    runs = entry["judge_runs"]
    assert runs["values"] == [4, 5]
    assert runs["n_valid"] == 2
    assert runs["n_error"] == 1
    assert runs["median"] == 4


def test_minority_of_valid_runs_records_an_error(tmp_path):
    # 1 valid of 3 < ceil(3/2) = 2 → the whole (sample, metric) is an error.
    scorer = _scorer([_error("boom-1"), _error("boom-2"), _score(5)])

    results = _evaluate(scorer, tmp_path, judge_runs=3)

    entry = _metric_entry(results)
    assert entry["status"] == METRIC_STATUS_ERROR
    assert entry["score"] is None
    assert "1/3" in entry["error"]
    assert results["scores"][METRIC] is None
    # Raw values are still stored for debugging.
    assert entry["judge_runs"]["values"] == [5]
    assert entry["judge_runs"]["n_error"] == 2


def test_exception_during_a_run_counts_as_a_failed_run(tmp_path):
    scorer = _scorer([RuntimeError("connection reset"), _score(4), _score(4)])

    results = _evaluate(scorer, tmp_path, judge_runs=3)

    entry = _metric_entry(results)
    assert entry["score"] == 4
    assert entry["judge_runs"]["n_error"] == 1
    assert "connection reset" in entry["judge_runs"]["errors"][0]
    # A failing run must not abort the remaining runs.
    assert scorer.metrics[METRIC].calls == 3


def test_all_not_applicable_runs_stay_not_applicable(tmp_path):
    scorer = _scorer([_na(), _na(), _na()])

    results = _evaluate(scorer, tmp_path, judge_runs=3)

    entry = _metric_entry(results)
    assert entry["status"] == METRIC_STATUS_NOT_APPLICABLE
    assert entry["score"] is None
    assert not entry.get("error")
    assert entry["judge_runs"]["n_not_applicable"] == 3
    assert entry["judge_runs"]["values"] == []
    # N/A is still not an error for the resume criterion.
    assert run_evaluation.result_has_metric_errors(results, [METRIC]) is False


def test_mixed_na_runs_still_need_a_majority_of_valid_scores(tmp_path):
    # 2 valid of 3 → scored.
    scorer = _scorer([_na(), _score(4), _score(5)])
    entry = _metric_entry(_evaluate(scorer, tmp_path, judge_runs=3))
    assert entry["status"] == "scored"
    assert entry["score"] == 4
    assert entry["judge_runs"]["n_not_applicable"] == 1

    # 1 valid + 2 N/A → below ceil(3/2)=2 → error, not N/A.
    scorer = _scorer([_na(), _na(), _score(4)])
    entry = _metric_entry(_evaluate(scorer, tmp_path, judge_runs=3))
    assert entry["status"] == METRIC_STATUS_ERROR
    assert "1/3" in entry["error"]


def test_representative_reason_matches_the_median_score(tmp_path):
    scorer = _scorer(
        [
            _score(5, reason="five"),
            _score(3, reason="three"),
            _score(3, reason="three-again"),
        ]
    )

    entry = _metric_entry(_evaluate(scorer, tmp_path, judge_runs=3))

    assert entry["score"] == 3
    # reason/sub_scores/details come from the first run hitting the median.
    assert entry["reason"] == "three"


@pytest.mark.parametrize(
    ("k", "n_valid", "expected_status"),
    [
        (1, 1, "scored"),
        (1, 0, METRIC_STATUS_ERROR),
        (2, 1, "scored"),  # ceil(2/2) = 1
        (2, 0, METRIC_STATUS_ERROR),
        (3, 2, "scored"),  # ceil(3/2) = 2
        (3, 1, METRIC_STATUS_ERROR),
        (4, 2, "scored"),  # ceil(4/2) = 2
        (4, 1, METRIC_STATUS_ERROR),
        (5, 3, "scored"),  # ceil(5/2) = 3
        (5, 2, METRIC_STATUS_ERROR),
    ],
)
def test_majority_threshold_is_ceil_half_of_k(k, n_valid, expected_status):
    script = [_score(4)] * n_valid + [_error()] * (k - n_valid)

    aggregated = aggregate_judge_runs(METRIC, script)

    assert aggregated["status"] == expected_status
    assert aggregated["judge_runs"]["n_valid"] == n_valid


# ── run signature ────────────────────────────────────────────────────────────


def _write_result(path, signature):
    payload = {
        "status": "success",
        "run_signature": signature,
        "images": {
            "diagram.png": {
                "dimensions": {
                    "content": {
                        METRIC: {"score": 4, "status": "scored", "error": None}
                    }
                }
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_signature_records_judge_runs():
    signature = build_run_signature(
        judge_role="eval",
        judge_model="kimi-k3",
        judge_temperature=1,
        judge_max_tokens=8000,
        metrics=[METRIC],
        judge_runs=3,
    )
    assert signature["judge_runs"] == 3

    default = build_run_signature(
        judge_role="eval",
        judge_model="kimi-k3",
        judge_temperature=1,
        judge_max_tokens=8000,
        metrics=[METRIC],
    )
    assert default["judge_runs"] == 1


def test_changing_k_invalidates_stored_results(tmp_path):
    result_path = tmp_path / "sample.json"
    _write_result(result_path, dict(BASE_SIGNATURE, judge_runs=1))

    state, detail = run_evaluation.classify_existing_result(
        result_path, [METRIC], dict(BASE_SIGNATURE, judge_runs=3)
    )
    assert state == "stale"
    assert "judge_runs" in detail

    state, _ = run_evaluation.classify_existing_result(
        result_path, [METRIC], dict(BASE_SIGNATURE, judge_runs=1)
    )
    assert state == "reusable"


def test_pre_resampling_results_are_reusable_at_default_k(tmp_path):
    """A stored signature without judge_runs means exactly one judge run."""
    result_path = tmp_path / "sample.json"
    _write_result(result_path, BASE_SIGNATURE)  # no judge_runs field at all

    state, _ = run_evaluation.classify_existing_result(
        result_path, [METRIC], dict(BASE_SIGNATURE, judge_runs=1)
    )
    assert state == "reusable"

    state, detail = run_evaluation.classify_existing_result(
        result_path, [METRIC], dict(BASE_SIGNATURE, judge_runs=2)
    )
    assert state == "stale"
    assert "judge_runs" in detail


def test_judge_runs_argument_must_be_a_positive_integer(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_evaluation.py", "--judge-runs", "0"])
    with pytest.raises(SystemExit):
        run_evaluation.parse_args()

    monkeypatch.setattr(sys, "argv", ["run_evaluation.py", "--judge-runs", "3"])
    assert run_evaluation.parse_args().judge_runs == 3


# ── end-to-end: writer, resume and aggregator ────────────────────────────────


def _make_generated_image(tmp_path):
    image = (
        tmp_path
        / "experiments"
        / "exp1"
        / "outputs"
        / "evodiagram"
        / "evodiagram"
        / "model-a"
        / "s1"
        / "rendered_diagram.png"
    )
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    return image


def _result_path(tmp_path):
    return (
        tmp_path
        / "experiments"
        / "exp1"
        / "scores"
        / "evodiagram"
        / "evodiagram"
        / "model-a"
        / "s1"
        / "s1.json"
    )


class RecordingEvaluator:
    """MetricScorer-shaped evaluator that records the judge_runs it received."""

    generate_summary = staticmethod(MetricScorer.generate_summary)

    def __init__(self, score=4):
        self.score = score
        self.calls = []

    def evaluate_image(
        self,
        image_path,
        context_text,
        metrics_to_use,
        reference_image_path=None,
        judge_runs=1,
    ):
        self.calls.append(judge_runs)
        entry = {
            "metric": METRIC,
            "score": self.score,
            "sub_scores": {},
            "reason": "",
            "details": {},
            "error": None,
            "status": "scored",
        }
        if judge_runs > 1:
            entry["judge_runs"] = {
                "k": judge_runs,
                "n_valid": judge_runs,
                "n_not_applicable": 0,
                "n_error": 0,
                "values": [self.score] * judge_runs,
                "errors": [],
                "mean": float(self.score),
                "std": 0.0,
                "median": self.score,
            }
        return {
            "image": image_path,
            "dimensions": {"content": {METRIC: entry}, "visual": {}, "cognitive": {}},
            "scores": {METRIC: self.score},
            "metric_status": {METRIC: "scored"},
            "average_score": float(self.score),
        }


def _run_item(evaluator, judge_runs, signature):
    return run_evaluation.evaluate_single_data_item(
        data_item={"id": "s1", "content": "text"},
        evaluator=evaluator,
        metrics=[METRIC],
        method="evodiagram/model-a",
        exp_id="exp1",
        run_signature=signature,
        judge_runs=judge_runs,
    )


def test_judge_runs_reach_the_evaluator_and_the_result_file(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)
    _make_generated_image(tmp_path)

    evaluator = RecordingEvaluator(score=4)
    signature = dict(BASE_SIGNATURE, judge_runs=3)

    assert _run_item(evaluator, 3, signature) is True
    assert evaluator.calls == [3]

    payload = json.loads(_result_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["run_signature"]["judge_runs"] == 3
    stored = payload["images"]["rendered_diagram.png"]["dimensions"]["content"][METRIC]
    assert stored["judge_runs"]["k"] == 3
    assert stored["judge_runs"]["values"] == [4, 4, 4]


def test_resume_reuses_matching_k_and_reruns_on_k_change(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)
    _make_generated_image(tmp_path)

    evaluator = RecordingEvaluator(score=4)

    assert _run_item(evaluator, 3, dict(BASE_SIGNATURE, judge_runs=3)) is True
    assert evaluator.calls == [3]

    # Same k → stored result reused, judge not called again.
    assert _run_item(evaluator, 3, dict(BASE_SIGNATURE, judge_runs=3)) is True
    assert evaluator.calls == [3]

    # Different k → signature mismatch forces re-evaluation.
    assert _run_item(evaluator, 5, dict(BASE_SIGNATURE, judge_runs=5)) is True
    assert evaluator.calls == [3, 5]
    payload = json.loads(_result_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["run_signature"]["judge_runs"] == 5


def test_written_median_result_flows_into_the_aggregator(monkeypatch, tmp_path):
    """Full chain: scripted judge → median score on disk → retest variance."""
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)
    _make_generated_image(tmp_path)

    scorer = _scorer([_score(4), _score(5), _score(4)])
    signature = dict(BASE_SIGNATURE, judge_runs=3)

    assert _run_item(scorer, 3, signature) is True

    payload = json.loads(_result_path(tmp_path).read_text(encoding="utf-8"))
    stored = payload["images"]["rendered_diagram.png"]["dimensions"]["content"][METRIC]
    assert stored["score"] == 4
    assert stored["judge_runs"]["median"] == 4

    scores_root = tmp_path / "experiments" / "exp1" / "scores"
    analyzer = EvaluationAnalyzer(bootstrap_resamples=100)
    result = analyzer.analyze_multiple_methods(str(scores_root))[0]

    entry = result["dimension_stats"][METRIC]
    assert entry["mean"] == 4.0
    retest = entry["judge_retest_variance"]
    assert retest["n_samples"] == 1
    assert retest["mean_within_sample_std"] == pytest.approx(0.5774, abs=1e-3)
    assert retest["mean_within_sample_range"] == 1.0


# ── aggregator reporting ─────────────────────────────────────────────────────


def _write_scored_result(method_dir, data_id, score, judge_runs=None):
    sample_dir = method_dir / data_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "metric": METRIC,
        "score": score,
        "sub_scores": {},
        "reason": "",
        "details": {},
        "error": None,
        "status": "scored",
    }
    if judge_runs is not None:
        entry["judge_runs"] = judge_runs
    payload = {
        "data_id": data_id,
        "status": "success",
        "metrics": [METRIC],
        "images": {
            "render.png": {
                "dimensions": {"content": {METRIC: entry}, "visual": {}, "cognitive": {}},
                "scores": {METRIC: score},
                "average_score": float(score),
            }
        },
        "summary": {},
    }
    (sample_dir / f"{data_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_analysis_reports_judge_retest_variance(tmp_path):
    method_dir = tmp_path / "scores" / "evodiagram" / "evodiagram" / "kimi-k3"
    _write_scored_result(
        method_dir,
        "s1",
        4,
        judge_runs={
            "k": 3, "n_valid": 3, "n_error": 0, "n_not_applicable": 0,
            "values": [4, 5, 4], "errors": [],
            "mean": 4.3333, "std": 0.5774, "median": 4,
        },
    )
    _write_scored_result(
        method_dir,
        "s2",
        3,
        judge_runs={
            "k": 3, "n_valid": 3, "n_error": 0, "n_not_applicable": 0,
            "values": [3, 4, 5], "errors": [],
            "mean": 4.0, "std": 1.0, "median": 3,
        },
    )

    analyzer = EvaluationAnalyzer(bootstrap_resamples=100)
    result = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))[0]

    retest = result["dimension_stats"][METRIC]["judge_retest_variance"]
    assert retest["n_samples"] == 2
    # Mean of per-sample stds: the judge retest reliability headline number.
    assert retest["mean_within_sample_std"] == pytest.approx(0.7887, abs=1e-3)
    assert retest["max_within_sample_std"] == pytest.approx(1.0)
    assert retest["mean_within_sample_range"] == pytest.approx(1.5)


def test_analysis_recomputes_std_when_the_field_is_missing(tmp_path):
    method_dir = tmp_path / "scores" / "evodiagram" / "evodiagram" / "kimi-k3"
    _write_scored_result(
        method_dir,
        "s1",
        4,
        judge_runs={"k": 3, "values": [4, 5, 4], "median": 4},  # no std field
    )

    analyzer = EvaluationAnalyzer(bootstrap_resamples=100)
    result = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))[0]

    retest = result["dimension_stats"][METRIC]["judge_retest_variance"]
    assert retest["n_samples"] == 1
    assert retest["mean_within_sample_std"] == pytest.approx(0.5774, abs=1e-3)


def test_analysis_output_is_unchanged_without_judge_runs(tmp_path):
    method_dir = tmp_path / "scores" / "evodiagram" / "evodiagram" / "kimi-k3"
    _write_scored_result(method_dir, "s1", 4)
    _write_scored_result(method_dir, "s2", 5)

    analyzer = EvaluationAnalyzer(bootstrap_resamples=100)
    result = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))[0]

    entry = result["dimension_stats"][METRIC]
    assert "judge_retest_variance" not in entry
    assert entry["mean"] == 4.5
