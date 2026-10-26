"""Tests for the stdlib statistics helpers used by the aggregator."""

from __future__ import annotations

import pytest

from evaluation.analysis import stats


def test_mean_and_stdev():
    values = [1, 2, 3, 4, 5]
    assert stats.mean(values) == 3
    assert stats.stdev(values) == pytest.approx(1.5811388, rel=1e-6)
    assert stats.mean([]) is None
    assert stats.stdev([4]) is None


def test_bootstrap_ci_is_deterministic_and_brackets_the_mean():
    values = [3, 4, 4, 5, 2, 3, 4, 5, 1, 3]

    first = stats.bootstrap_ci(values, resamples=2000, seed=7)
    second = stats.bootstrap_ci(values, resamples=2000, seed=7)

    assert first == second
    assert first[0] <= stats.mean(values) <= first[1]


def test_bootstrap_ci_requires_two_observations():
    assert stats.bootstrap_ci([4], resamples=100) is None
    assert stats.bootstrap_ci([4, 5], resamples=0) is None


def test_wilcoxon_matches_the_reference_example():
    """Classic worked example; scipy reports statistic=5.0, p=0.0390625."""
    x = [1.83, 0.50, 1.62, 2.48, 1.68, 1.88, 1.55, 3.06, 1.30]
    y = [0.878, 0.647, 0.598, 2.05, 1.06, 1.29, 1.06, 3.14, 1.29]

    result = stats.wilcoxon_signed_rank(x, y)

    assert result["statistic"] == pytest.approx(5.0)
    assert result["p_value"] == pytest.approx(0.0390625, rel=1e-9)
    assert result["method"] == "exact"


def test_wilcoxon_handles_ties_with_the_normal_approximation():
    x = [4, 4, 4, 5, 5, 5, 3, 4, 5, 4]
    y = [2, 2, 2, 3, 3, 3, 2, 2, 3, 2]

    result = stats.wilcoxon_signed_rank(x, y)

    assert result["method"] == "normal-approximation-with-tie-correction"
    assert 0.0 <= result["p_value"] <= 1.0
    assert result["n_nonzero"] == 10


def test_wilcoxon_with_no_differences():
    result = stats.wilcoxon_signed_rank([3, 3, 3], [3, 3, 3])

    assert result["n_nonzero"] == 0
    assert result["p_value"] == 1.0


def test_wilcoxon_rejects_unequal_lengths():
    with pytest.raises(ValueError):
        stats.wilcoxon_signed_rank([1, 2], [1])


def test_describe_reports_n_mean_std_and_ci():
    described = stats.describe([2, 3, 4, 5], resamples=500, seed=3)

    assert described["n"] == 4
    assert described["mean"] == 3.5
    assert described["std"] is not None
    assert described["ci95_bootstrap"] is not None
