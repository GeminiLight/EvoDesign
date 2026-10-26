"""Contract tests for the evaluation aggregator."""

from __future__ import annotations

import json

import pytest

from evaluation.analysis.analysis_results import EvaluationAnalyzer, load_dataset_ids


DIMENSION_OF = {
    "content_dimension": "content",
    "visual_dimension": "visual",
    "cognitive_dimension": "cognitive",
    "judge_preference": "cognitive",
}


def write_result(method_dir, data_id, scores, status="success", na=(), errors=()):
    """Write one sample result file under ``method_dir/data_id/data_id.json``."""
    sample_dir = method_dir / data_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    dimensions = {"content": {}, "visual": {}, "cognitive": {}}
    flat_scores = {}
    for metric, score in scores.items():
        dimensions[DIMENSION_OF[metric]][metric] = {
            "metric": metric,
            "score": score,
            "sub_scores": {"detail": score},
            "reason": "",
            "details": {},
            "error": None,
            "status": "scored",
        }
        flat_scores[metric] = score
    for metric in na:
        dimensions[DIMENSION_OF[metric]][metric] = {
            "metric": metric,
            "score": None,
            "sub_scores": {},
            "reason": "",
            "details": {},
            "error": None,
            "status": "not_applicable",
            "na_reason": "reference_image_missing",
        }
        flat_scores[metric] = None
    for metric in errors:
        dimensions[DIMENSION_OF[metric]][metric] = {
            "metric": metric,
            "score": None,
            "sub_scores": {},
            "reason": "",
            "details": {},
            "error": "judge failed",
            "status": "error",
        }
        flat_scores[metric] = None

    payload = {
        "data_id": data_id,
        "method": method_dir.name,
        "status": status,
        "metrics": list(DIMENSION_OF),
        "reference_image_available": not na,
        "images": {
            "render.png": {
                "dimensions": dimensions,
                "scores": flat_scores,
                "average_score": 3,
            }
        },
        "summary": {},
    }
    (sample_dir / f"{data_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def write_missing_output(method_dir, data_id):
    sample_dir = method_dir / data_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "data_id": data_id,
        "method": method_dir.name,
        "status": "missing_output",
        "error": "No generated image found",
        "metrics": list(DIMENSION_OF),
        "generated_image": None,
        "images": {},
        "summary": {},
    }
    (sample_dir / f"{data_id}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def scores_root(tmp_path):
    root = tmp_path / "scores"
    good = root / "baseline" / "mermaid" / "gpt-x"
    for index in range(1, 11):
        data_id = f"s{index}"
        if index <= 4:
            # 40% failure rate: the old >=80%-sample-directory heuristic dropped
            # such a method from the report entirely.
            write_missing_output(good, data_id)
        else:
            write_result(good, data_id, {m: 2 for m in DIMENSION_OF})
    return root


@pytest.fixture()
def dataset(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps([{"id": f"s{i}", "content": "c"} for i in range(1, 11)]),
        encoding="utf-8",
    )
    return path


# ── discovery ────────────────────────────────────────────────────────────────


def test_method_with_high_failure_rate_is_still_reported(scores_root, dataset):
    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    results = analyzer.analyze_multiple_methods(
        str(scores_root), dataset_ids=load_dataset_ids(str(dataset))
    )

    assert [r["algorithm_name"] for r in results] == ["baseline/mermaid/gpt-x"]
    assert results[0]["sample_counts"]["missing_output_n"] == 4


def test_empty_sample_directories_do_not_hide_the_method(tmp_path):
    """Leftover empty sample directories used to push a method below the 80%
    threshold and remove its entire row from --summary without a warning."""
    method_dir = tmp_path / "scores" / "baseline" / "mermaid" / "gpt-x"
    for index in range(1, 6):
        write_result(method_dir, f"s{index}", {m: 3 for m in DIMENSION_OF})
    for index in range(6, 11):
        (method_dir / f"s{index}").mkdir(parents=True)

    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    results = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))

    assert len(results) == 1
    assert results[0]["sample_counts"]["result_files_n"] == 5


def test_explicit_method_paths_skip_discovery(scores_root, dataset):
    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    results = analyzer.analyze_multiple_methods(
        str(scores_root),
        dataset_ids=load_dataset_ids(str(dataset)),
        method_directories=["baseline/mermaid/gpt-x"],
    )

    assert len(results) == 1
    assert results[0]["algorithm_name"] == "baseline/mermaid/gpt-x"


def test_unknown_explicit_method_path_warns(scores_root):
    analyzer = EvaluationAnalyzer()
    results = analyzer.analyze_multiple_methods(
        str(scores_root), method_directories=["baseline/nope/gpt-x"]
    )

    assert results == []
    assert any("not found" in w for w in analyzer.warnings)


# ── full-set alignment and missing policy ────────────────────────────────────


def test_counts_distinguish_full_set_from_valid_n(scores_root, dataset):
    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    result = analyzer.analyze_multiple_methods(
        str(scores_root), dataset_ids=load_dataset_ids(str(dataset))
    )[0]

    counts = result["sample_counts"]
    assert counts["full_set_n"] == 10
    assert counts["result_files_n"] == 10
    assert counts["success_n"] == 6
    assert counts["missing_output_n"] == 4
    assert counts["missing_rate"] == 0.4

    entry = result["dimension_stats"]["content_dimension"]
    assert entry["full_set_n"] == 10
    assert entry["valid_n"] == 6
    assert entry["excluded_reasons"] == {"missing_output": 4}


def test_samples_absent_from_disk_are_counted_against_the_dataset(tmp_path, dataset):
    method_dir = tmp_path / "scores" / "baseline" / "mermaid" / "gpt-x"
    for index in range(1, 4):
        write_result(method_dir, f"s{index}", {m: 5 for m in DIMENSION_OF})

    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    result = analyzer.analyze_multiple_methods(
        str(tmp_path / "scores"), dataset_ids=load_dataset_ids(str(dataset))
    )[0]

    counts = result["sample_counts"]
    assert counts["full_set_n"] == 10
    assert counts["result_files_n"] == 3
    assert counts["no_result_file_n"] == 7
    assert counts["missing_rate"] == 0.7
    assert result["dimension_stats"]["content_dimension"]["valid_n"] == 3


def test_missing_policy_zero_penalises_failed_generations(scores_root, dataset):
    ids = load_dataset_ids(str(dataset))

    excluded = EvaluationAnalyzer(missing_policy="exclude", bootstrap_resamples=200)
    zeroed = EvaluationAnalyzer(missing_policy="zero", bootstrap_resamples=200)

    excluded_result = excluded.analyze_multiple_methods(str(scores_root), dataset_ids=ids)[0]
    zeroed_result = zeroed.analyze_multiple_methods(str(scores_root), dataset_ids=ids)[0]

    # 6 samples scored 2, 4 samples produced no diagram.
    assert excluded_result["dimension_scores"]["content_dimension"] == 2.0
    assert zeroed_result["dimension_scores"]["content_dimension"] == pytest.approx(1.2)

    # Both readings are present regardless of the selected policy.
    for result in (excluded_result, zeroed_result):
        entry = result["dimension_stats"]["content_dimension"]
        assert entry["mean"] == 2.0
        assert entry["mean_missing_as_zero"] == pytest.approx(1.2)


def test_unknown_missing_policy_is_rejected():
    with pytest.raises(ValueError):
        EvaluationAnalyzer(missing_policy="ignore")


# ── per-metric exclusion ─────────────────────────────────────────────────────


def test_not_applicable_metric_is_excluded_only_for_that_metric(tmp_path):
    method_dir = tmp_path / "scores" / "evodiagram" / "evodiagram" / "gpt-x"
    write_result(
        method_dir,
        "s1",
        {"content_dimension": 4, "visual_dimension": 4, "cognitive_dimension": 4},
        na=("judge_preference",),
    )
    write_result(method_dir, "s2", {m: 4 for m in DIMENSION_OF})

    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    result = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))[0]

    assert result["dimension_stats"]["content_dimension"]["valid_n"] == 2
    judge = result["dimension_stats"]["judge_preference"]
    assert judge["valid_n"] == 1
    assert judge["excluded_reasons"] == {"not_applicable": 1}
    # A not-applicable comparative metric is never zero-filled: it is an
    # evaluation limitation, not a failure of the method.
    assert judge["zero_filled_n"] == 0
    assert judge["mean"] == judge["mean_missing_as_zero"] == 4.0


def test_metric_error_does_not_delete_the_other_metrics_of_that_sample(tmp_path):
    method_dir = tmp_path / "scores" / "baseline" / "mermaid" / "gpt-x"
    write_result(
        method_dir,
        "s1",
        {"content_dimension": 3, "visual_dimension": 3, "cognitive_dimension": 3},
        errors=("judge_preference",),
        status="failed",
    )
    write_result(method_dir, "s2", {m: 3 for m in DIMENSION_OF})

    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    result = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))[0]

    assert result["dimension_stats"]["content_dimension"]["valid_n"] == 2
    assert result["dimension_stats"]["judge_preference"]["valid_n"] == 1
    assert result["dimension_stats"]["judge_preference"]["excluded_reasons"] == {
        "evaluation_error": 1
    }


def test_out_of_rubric_stored_score_is_excluded(tmp_path):
    method_dir = tmp_path / "scores" / "baseline" / "mermaid" / "gpt-x"
    write_result(method_dir, "s1", {m: 0 for m in DIMENSION_OF})
    write_result(method_dir, "s2", {m: 4 for m in DIMENSION_OF})

    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    result = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))[0]

    entry = result["dimension_stats"]["content_dimension"]
    assert entry["valid_n"] == 1
    assert entry["mean"] == 4.0


# ── dispersion and significance ──────────────────────────────────────────────


def test_dimension_stats_report_std_and_confidence_interval(tmp_path):
    method_dir = tmp_path / "scores" / "baseline" / "mermaid" / "gpt-x"
    for index, score in enumerate([1, 2, 3, 4, 5], start=1):
        write_result(method_dir, f"s{index}", {m: score for m in DIMENSION_OF})

    analyzer = EvaluationAnalyzer(bootstrap_resamples=500, seed=11)
    result = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))[0]

    entry = result["dimension_stats"]["content_dimension"]
    assert entry["mean"] == 3.0
    assert entry["std"] == pytest.approx(1.5811, abs=1e-3)
    assert entry["sem"] is not None
    low, high = entry["ci95_bootstrap"]
    assert low <= 3.0 <= high


def test_paired_comparison_reports_wilcoxon_and_bootstrap_ci(tmp_path):
    baseline_dir = tmp_path / "scores" / "baseline" / "mermaid" / "gpt-x"
    evo_dir = tmp_path / "scores" / "evodiagram" / "evodiagram" / "gpt-x"
    for index in range(1, 13):
        write_result(baseline_dir, f"s{index}", {m: 2 for m in DIMENSION_OF})
        write_result(evo_dir, f"s{index}", {m: 4 for m in DIMENSION_OF})

    analyzer = EvaluationAnalyzer(bootstrap_resamples=500, seed=5)
    results = analyzer.analyze_multiple_methods(str(tmp_path / "scores"))
    comparisons = analyzer.compare_methods(results, "evodiagram/evodiagram/gpt-x")

    content = [c for c in comparisons if c["metric"] == "content_dimension"]
    assert len(content) == 1
    entry = content[0]
    assert entry["algorithm_name"] == "baseline/mermaid/gpt-x"
    assert entry["n_pairs"] == 12
    assert entry["mean_difference"] == -2.0
    assert entry["wilcoxon"]["p_value"] < 0.05
    assert entry["bootstrap_ci95_of_mean_difference"] == [-2.0, -2.0]


def test_comparison_reference_must_exist(tmp_path, scores_root):
    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    results = analyzer.analyze_multiple_methods(str(scores_root))

    assert analyzer.compare_methods(results, "nope") == []
    assert any("not found" in w for w in analyzer.warnings)


def test_summary_exposes_coverage_per_method(scores_root, dataset):
    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    results = analyzer.analyze_multiple_methods(
        str(scores_root), dataset_ids=load_dataset_ids(str(dataset))
    )
    summary = analyzer.generate_summary(results)

    coverage = summary["coverage"]["baseline/mermaid/gpt-x"]
    assert coverage["full_set_n"] == 10
    assert coverage["missing_rate"] == 0.4
    assert coverage["valid_n_by_metric"]["content_dimension"] == 6
