"""Tests for the success-margin calibration report tool.

The synthetic run directories use the exact ``results/samples.json`` shape
``engine._persist_results`` writes (``IterationRecord.model_dump()``), trimmed
to the fields the tool reads: ``id``, ``iteration``, ``tags`` and
``evaluation.score_before``.

Run:  python -m pytest evo_diagram/tests/knowledge_evolution/test_margin_report.py -v
"""

from __future__ import annotations

import json
import statistics

import pytest

from evo_diagram.knowledge_evolution.analysis.margin_report import (
    build_report,
    distribution_stats,
    format_report,
    main,
    recommend_margin,
    replay_judgments,
)


# ── Synthetic run builders ───────────────────────────────────────────────


def _record(
    sample_id,
    iteration,
    score_before,
    *,
    diagram_type="flowchart",
    content_area="ops",
):
    return {
        "id": f"{sample_id}_iter_{iteration}",
        "iteration": iteration,
        "tags": {
            "domain": [content_area],
            "diagram_type": [diagram_type],
            "agent": [],
        },
        "text_content": "T",
        "user_query": "Q",
        "diagram": {"representation": "m.json", "manifest_ref": "m.png"},
        "evaluation": {
            "quality": score_before,
            "score_before": score_before,
            "score_after": score_before,
        },
        "feedback": {"LLM_comments": [], "human_comments": []},
        "delta_score": 0.0,
    }


def _write_run(tmp_path, records, indeterminate=None, *, run_name="run"):
    run_dir = tmp_path / run_name
    results = run_dir / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "samples.json").write_text(json.dumps(records), encoding="utf-8")
    if indeterminate is not None:
        (results / "indeterminate_samples.json").write_text(
            json.dumps(indeterminate), encoding="utf-8"
        )
    return str(run_dir)


def _two_sample_run(tmp_path):
    """Minimal run: two fake samples, each with a first-pass and a refined record."""
    records = [
        _record("s1", 0, 6.0),
        _record("s1", 1, 9.5),
        _record("s2", 0, 8.0),
        _record("s2", 1, 9.0),
    ]
    indeterminate = [
        {"sample_id": "s1", "criterion": "first_pass_vs_history", "detail": "cold start"},
        {"sample_id": "s2", "criterion": "first_pass_vs_history", "detail": "cold start"},
    ]
    return _write_run(tmp_path, records, indeterminate)


# Crafted score sequence for a predictable suggestion (all flowchart/ops,
# min_samples=1). Verdicts per margin, replayed in run order:
#   order:  5.0    6.0    5.5    4.0     5.925   5.625
#   m=0.00: indet  succ   succ   fail    succ    succ   → 4/1, rate 0.80
#   m=0.25: indet  succ   fail   fail    succ    succ   → 3/2, rate 0.60
#   m=0.50: indet  succ   fail   fail    succ    fail   → 2/3, rate 0.40
#   m=0.75: indet  succ   fail   fail    succ    fail   → 2/3, rate 0.40
#   m=1.00: indet  succ   fail   fail    fail    fail   → 1/4, rate 0.20
# Band [0.4, 0.6] holds 0.25 / 0.5 / 0.75 → suggested = 0.75 (largest in band).
_CRAFTED_SCORES = [
    ("s1", 5.0),
    ("s2", 6.0),
    ("s3", 5.5),
    ("s4", 4.0),
    ("s5", 5.925),
    ("s6", 5.625),
]


def _crafted_run(tmp_path):
    records = []
    for index, (sample_id, score) in enumerate(_CRAFTED_SCORES):
        records.append(_record(sample_id, 0, score))
        records.append(_record(sample_id, 1, score + 1.0))  # refiner pass, ignored
    return _write_run(tmp_path, records, indeterminate=[])


# ── Distribution statistics ──────────────────────────────────────────────


def test_distribution_stats_matches_statistics_module():
    scores = [4.0, 6.0, 8.0, 5.5, 7.25]

    stats = distribution_stats(scores)

    assert stats["n"] == 5
    assert stats["mean"] == pytest.approx(statistics.fmean(scores))
    assert stats["std"] == pytest.approx(statistics.stdev(scores))
    assert stats["min"] == 4.0
    assert stats["max"] == 8.0
    q25, q50, q75 = statistics.quantiles(sorted(scores), n=4, method="inclusive")
    assert stats["p25"] == pytest.approx(q25)
    assert stats["p50"] == pytest.approx(q50)
    assert stats["p75"] == pytest.approx(q75)


def test_distribution_stats_single_point_and_empty():
    single = distribution_stats([7.0])
    assert single == {
        "n": 1,
        "mean": 7.0,
        "std": 0.0,
        "min": 7.0,
        "p25": 7.0,
        "p50": 7.0,
        "p75": 7.0,
        "max": 7.0,
    }
    assert distribution_stats([]) is None


def test_two_sample_run_reports_distribution_and_no_suggestion(tmp_path):
    """Two fake samples under the default min_samples=3: nothing is judgeable."""
    run_dir = _two_sample_run(tmp_path)

    report = build_report(run_dir)

    assert report["sample_count"] == 2
    assert report["as_run_indeterminate"] == 2
    overall = report["overall"]
    assert overall["n"] == 2
    assert overall["mean"] == pytest.approx(7.0)          # (6.0 + 8.0) / 2
    assert overall["std"] == pytest.approx(statistics.stdev([6.0, 8.0]))
    assert overall["min"] == 6.0 and overall["max"] == 8.0
    assert list(report["buckets"]) == ["flowchart/ops"]

    # Every candidate leaves both samples indeterminate → no rate, no suggestion.
    for row in report["margins"]:
        assert (row["success"], row["failure"], row["indeterminate"]) == (0, 0, 2)
        assert row["success_rate"] is None
    assert report["suggested_margin"] is None
    assert "cannot recommend" in report["suggestion_reason"]

    text = format_report(report)
    assert "flowchart/ops" in text
    assert "Suggested first_pass_success_margin: none" in text


# ── Margin replay and suggestion ─────────────────────────────────────────


def test_margin_table_replays_engine_verdicts_and_suggests_largest_in_band(tmp_path):
    run_dir = _crafted_run(tmp_path)

    report = build_report(run_dir, min_samples=1)

    assert report["sample_count"] == 6
    expected = {
        0.0: (4, 1, 1, 0.8),
        0.25: (3, 2, 1, 0.6),
        0.5: (2, 3, 1, 0.4),
        0.75: (2, 3, 1, 0.4),
        1.0: (1, 4, 1, 0.2),
    }
    for row in report["margins"]:
        success, failure, indeterminate, rate = expected[row["margin"]]
        assert row["success"] == success
        assert row["failure"] == failure
        assert row["indeterminate"] == indeterminate
        assert row["judged"] == success + failure
        assert row["success_rate"] == pytest.approx(rate)

    assert report["suggested_margin"] == 0.75
    assert "largest candidate" in report["suggestion_reason"]

    assert report["overall"]["n"] == 6
    assert report["overall"]["mean"] == pytest.approx(
        statistics.fmean([score for _, score in _CRAFTED_SCORES])
    )


def test_refinement_iterations_do_not_enter_the_distribution(tmp_path):
    """Only ``iteration == 0`` records carry the generator's first pass."""
    run_dir = _crafted_run(tmp_path)

    report = build_report(run_dir, min_samples=1)

    assert report["sample_count"] == len(_CRAFTED_SCORES)
    assert report["overall"]["max"] == 6.0  # the +1.0 refined scores are absent


def test_default_min_samples_gate_produces_cold_start_indeterminates(tmp_path):
    run_dir = _crafted_run(tmp_path)

    report = build_report(run_dir)  # min_samples defaults to 3

    for row in report["margins"]:
        assert row["indeterminate"] == 3  # first three samples warm the bucket
        assert row["judged"] == 3


def test_records_without_score_before_are_skipped_and_counted(tmp_path):
    broken = {"id": "s2_iter_0", "iteration": 0, "tags": {}, "evaluation": {}}
    run_dir = _write_run(tmp_path, [_record("s1", 0, 6.0), broken])

    report = build_report(run_dir, min_samples=1)

    assert report["sample_count"] == 1
    assert report["skipped_records"] == 1


def test_empty_run_is_reported_gracefully(tmp_path):
    run_dir = _write_run(tmp_path, [])

    report = build_report(run_dir)
    text = format_report(report)

    assert report["sample_count"] == 0
    assert report["overall"] is None
    assert report["suggested_margin"] is None
    assert "no first-pass records found" in text


def test_bucket_stats_are_separated_by_diagram_type_and_content_area(tmp_path):
    records = [
        _record("a1", 0, 4.0, diagram_type="flowchart", content_area="ops"),
        _record("a2", 0, 6.0, diagram_type="flowchart", content_area="ops"),
        _record("b1", 0, 9.0, diagram_type="sequence", content_area="finance"),
    ]
    run_dir = _write_run(tmp_path, records)

    report = build_report(run_dir, min_samples=1)

    assert set(report["buckets"]) == {"flowchart/ops", "sequence/finance"}
    assert report["buckets"]["flowchart/ops"]["n"] == 2
    assert report["buckets"]["flowchart/ops"]["mean"] == pytest.approx(5.0)
    assert report["buckets"]["sequence/finance"]["n"] == 1
    assert report["buckets"]["sequence/finance"]["mean"] == pytest.approx(9.0)
    assert report["overall"]["n"] == 3
    assert report["overall"]["mean"] == pytest.approx(
        statistics.fmean([4.0, 6.0, 9.0])
    )


def test_missing_samples_file_raises_a_clear_error(tmp_path):
    run_dir = tmp_path / "not_a_run"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="samples.json"):
        build_report(str(run_dir))


def test_missing_indeterminate_file_is_tolerated(tmp_path):
    run_dir = _write_run(tmp_path, [_record("s1", 0, 6.0)], indeterminate=None)

    report = build_report(run_dir, min_samples=1)

    assert report["as_run_indeterminate"] == 0


def test_replay_never_lets_a_sample_judge_against_itself():
    """First observation sees an empty baseline even with min_samples=1."""
    observations = [
        {
            "sample_id": "s1",
            "diagram_type": "flowchart",
            "content_area": "ops",
            "score_before": 10.0,
        }
    ]

    table = replay_judgments(observations, min_samples=1, margins=(0.0,))

    assert table[0]["indeterminate"] == 1
    assert table[0]["success"] == 0


def test_recommend_margin_falls_back_to_closest_candidate():
    def row(margin, success, failure):
        judged = success + failure
        return {
            "margin": margin,
            "success": success,
            "failure": failure,
            "indeterminate": 0,
            "judged": judged,
            "success_rate": success / judged if judged else None,
        }

    # All rates above the band → the closest one wins (0.7 at margin 0.5).
    suggested, reason = recommend_margin([row(0.0, 10, 0), row(0.5, 7, 3)])
    assert suggested == 0.5
    assert "no candidate landed inside" in reason

    # Equal distance → the larger margin is picked.
    suggested, _ = recommend_margin([row(0.25, 8, 2), row(0.5, 8, 2)])
    assert suggested == 0.5

    # Nothing judged → nothing recommended.
    suggested, reason = recommend_margin(
        [{"margin": 0.0, "success": 0, "failure": 0, "indeterminate": 5,
          "judged": 0, "success_rate": None}]
    )
    assert suggested is None
    assert "cannot recommend" in reason


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_prints_report_for_run_dir(tmp_path, capsys):
    run_dir = _crafted_run(tmp_path)

    exit_code = main([run_dir, "--min-samples", "1"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "score_before distribution" in captured.out
    assert "Margin sensitivity" in captured.out
    assert "Suggested first_pass_success_margin: 0.75" in captured.out
    assert "flowchart/ops" in captured.out


def test_cli_accepts_custom_margin_candidates(tmp_path, capsys):
    run_dir = _crafted_run(tmp_path)

    main([run_dir, "--min-samples", "1", "--margins", "0,0.5"])
    captured = capsys.readouterr()

    lines = [line for line in captured.out.splitlines() if line.strip().startswith(("0.00", "0.50", "0.25"))]
    assert len(lines) == 2  # only the two requested candidates are tabulated


def test_cli_rejects_invalid_arguments(tmp_path):
    run_dir = _crafted_run(tmp_path)

    with pytest.raises(SystemExit):
        main([run_dir, "--min-samples", "0"])
    with pytest.raises(SystemExit):
        main([run_dir, "--margins", "abc"])
    with pytest.raises(SystemExit):
        main([str(tmp_path / "missing_run")])
