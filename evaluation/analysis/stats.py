"""
Statistics helpers for evaluation aggregation.

Standard-library only. ``scipy`` is not a dependency of this repository and
adding one would touch ``pyproject.toml``, so the paired significance test and
the confidence intervals are implemented here directly.

Everything is deterministic: the bootstrap takes an explicit seed so a reported
interval can be reproduced exactly.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_BOOTSTRAP_RESAMPLES = 10000
DEFAULT_SEED = 12345

# Above this many non-zero differences the exact signed-rank distribution is
# both slow to enumerate and unnecessary; the normal approximation is accurate.
EXACT_WILCOXON_MAX_N = 25


def mean(values: Sequence[float]) -> Optional[float]:
    """Arithmetic mean, or None for an empty sample."""
    if not values:
        return None
    return sum(values) / len(values)


def stdev(values: Sequence[float]) -> Optional[float]:
    """Sample standard deviation (n-1). None when fewer than two observations."""
    if len(values) < 2:
        return None
    mu = sum(values) / len(values)
    variance = sum((v - mu) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def sem(values: Sequence[float]) -> Optional[float]:
    """Standard error of the mean."""
    sd = stdev(values)
    if sd is None:
        return None
    return sd / math.sqrt(len(values))


def bootstrap_ci(
    values: Sequence[float],
    confidence: float = 0.95,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> Optional[Tuple[float, float]]:
    """Percentile bootstrap confidence interval for the mean.

    Returns None when there are fewer than two observations or when *resamples*
    is not positive.
    """
    n = len(values)
    if n < 2 or resamples <= 0:
        return None

    rng = random.Random(seed)
    sample = list(values)
    means: List[float] = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            total += sample[rng.randrange(n)]
        means.append(total / n)

    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo_idx = max(0, min(resamples - 1, int(math.floor(alpha * resamples))))
    hi_idx = max(0, min(resamples - 1, int(math.ceil((1.0 - alpha) * resamples)) - 1))
    return means[lo_idx], means[hi_idx]


def _average_ranks(values: Sequence[float]) -> Tuple[List[float], List[int]]:
    """Return average ranks (1-based) and the sizes of each tie group."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    tie_sizes: List[int] = []

    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        group = order[i:j + 1]
        average_rank = (i + 1 + j + 1) / 2.0
        for idx in group:
            ranks[idx] = average_rank
        tie_sizes.append(len(group))
        i = j + 1

    return ranks, tie_sizes


def _exact_two_sided_p(n: int, w: float) -> float:
    """Exact two-sided p-value of the signed-rank statistic for *n* ranks.

    Counts, by dynamic programming, how many of the ``2**n`` sign assignments
    give a positive-rank sum of at most *w*.
    """
    total_rank_sum = n * (n + 1) // 2
    counts = [0] * (total_rank_sum + 1)
    counts[0] = 1
    for rank in range(1, n + 1):
        for value in range(total_rank_sum, rank - 1, -1):
            counts[value] += counts[value - rank]

    at_most = sum(counts[: int(math.floor(w)) + 1])
    p = 2.0 * at_most / float(2 ** n)
    return min(1.0, p)


def _normal_sf(z: float) -> float:
    """Two-sided tail probability of the standard normal distribution."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def wilcoxon_signed_rank(
    x: Sequence[float],
    y: Sequence[float],
) -> Dict[str, object]:
    """Two-sided Wilcoxon signed-rank test for paired samples.

    Zero differences are dropped (Wilcoxon's original handling). The exact
    distribution is used for small samples without ties in ``|d|``; otherwise a
    tie-corrected normal approximation with continuity correction is applied.

    Returns a dict with ``statistic`` (min of the positive/negative rank sums),
    ``p_value``, ``method``, ``n_pairs`` and ``n_nonzero``.
    """
    if len(x) != len(y):
        raise ValueError("wilcoxon_signed_rank requires equal-length samples")

    diffs = [a - b for a, b in zip(x, y)]
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)

    result: Dict[str, object] = {
        "n_pairs": len(diffs),
        "n_nonzero": n,
        "statistic": None,
        "p_value": None,
        "method": None,
    }

    if n == 0:
        result["method"] = "undefined (all differences are zero)"
        result["p_value"] = 1.0
        result["statistic"] = 0.0
        return result

    abs_diffs = [abs(d) for d in nonzero]
    ranks, tie_sizes = _average_ranks(abs_diffs)

    w_plus = sum(r for d, r in zip(nonzero, ranks) if d > 0)
    w_minus = sum(r for d, r in zip(nonzero, ranks) if d < 0)
    statistic = min(w_plus, w_minus)
    result["statistic"] = statistic

    has_ties = any(size > 1 for size in tie_sizes)

    if n <= EXACT_WILCOXON_MAX_N and not has_ties:
        result["p_value"] = _exact_two_sided_p(n, statistic)
        result["method"] = "exact"
        return result

    mu = n * (n + 1) / 4.0
    tie_correction = sum(size ** 3 - size for size in tie_sizes)
    variance = n * (n + 1) * (2 * n + 1) / 24.0 - tie_correction / 48.0
    if variance <= 0:
        result["p_value"] = 1.0
        result["method"] = "undefined (zero variance)"
        return result

    # Continuity correction toward the mean.
    delta = abs(w_plus - mu)
    z = (delta - 0.5) / math.sqrt(variance)
    if z < 0:
        z = 0.0
    result["p_value"] = min(1.0, _normal_sf(z))
    result["method"] = (
        "normal-approximation-with-tie-correction" if has_ties
        else "normal-approximation"
    )
    return result


def describe(
    values: Sequence[float],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_SEED,
    digits: int = 4,
) -> Dict[str, object]:
    """Return n / mean / std / sem / bootstrap CI for a sample."""
    def _round(value: Optional[float]) -> Optional[float]:
        return None if value is None else round(value, digits)

    ci = bootstrap_ci(values, resamples=resamples, seed=seed)
    return {
        "n": len(values),
        "mean": _round(mean(values)),
        "std": _round(stdev(values)),
        "sem": _round(sem(values)),
        "ci95_bootstrap": None if ci is None else [_round(ci[0]), _round(ci[1])],
    }
