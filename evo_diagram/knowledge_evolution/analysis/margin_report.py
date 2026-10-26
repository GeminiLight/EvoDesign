"""Calibrate ``first_pass_success_margin`` from a real evolution run.

``first_pass_success_margin`` (see :class:`KnowledgeEvolutionConfig`) decides
how far above its baseline a sample's first-pass ``score_before`` must land to
count as a knowledge *success*. The default ``0.0`` means "at least as good as
the baseline". Whether that is the right operating point depends on the actual
spread of ``score_before`` in real runs, which this tool reads back out of a
finished run's output directory and summarises.

What it produces
----------------
1. The distribution of first-pass ``score_before`` (overall and per
   ``(diagram_type, content_area)`` bucket): n / mean / std / min / quartiles /
   max.
2. A table of, for each candidate margin, how many samples would be judged
   success / failure / indeterminate. Judgements are produced by *replaying*
   the engine's exact ``first_pass_vs_history`` baseline logic over the run in
   order (running per-bucket mean, ``pair → diagram_type → global`` fallback,
   ``min_samples`` cold-start gate), so the counts match what the engine would
   do at that margin. See "Replay fidelity" below.
3. A recommended margin.

Inputs
------
``<run_dir>/results/samples.json`` — the list of ``IterationRecord`` dumps
written by ``engine._persist_results``. Only the first iteration of each sample
(``iteration == 0``) carries the generator's first-pass ``evaluation.
score_before``; later iterations are refiner steps and are ignored.

``<run_dir>/results/indeterminate_samples.json`` — optional; the samples the
run itself could not judge. Reported as-run for cross-checking the replay.

Replay fidelity
---------------
The baseline a sample is judged against is reconstructed by replaying the run
from a *cold* baseline (what a first-ever run sees). Two consequences:

- If the analysed run actually started from a persisted cross-run baseline
  (see :class:`FirstPassBaselineStore`), the replay will over-count
  ``indeterminate`` for the first few samples, because it cannot know the
  warm seed the run really had. The per-margin success/failure split of the
  judged samples is unaffected for everything past the cold-start window.
- ``--min-samples`` must match the run's ``first_pass_baseline_min_samples``
  (default 3, the config default) for the indeterminate counts to line up.

Suggestion rule
---------------
The recommended margin is the **largest candidate whose judged success rate
lands inside the 40%–60% band**, where the judged success rate is
``success / (success + failure)`` and indeterminate samples are excluded (they
carry no verdict at any margin, so they must not dilute the rate). The band
targets a criterion that actually discriminates: near 100% success the verdict
rewards nothing, near 0% it condemns everything, and mid-band keeps both
promotion and demotion pressure informative. If no candidate lands inside the
band, the tool falls back to the candidate whose success rate is *closest* to
the band (ties → the larger margin) and flags that the target was not met; if
no candidate has a defined rate at all (nothing was judged), it recommends
nothing.

Usage::

    python -m evo_diagram.knowledge_evolution.analysis.margin_report <run_dir>
    python -m evo_diagram.knowledge_evolution.analysis.margin_report <run_dir> \
        --min-samples 3 --margins 0.0,0.25,0.5,0.75,1.0
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Candidate margins evaluated when the caller does not supply ``--margins``.
DEFAULT_MARGIN_CANDIDATES: Tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
# Matches the ``first_pass_baseline_min_samples`` config default.
DEFAULT_MIN_SAMPLES = 3
# Success-rate band the recommended margin should land inside.
TARGET_BAND_LOW = 0.40
TARGET_BAND_HIGH = 0.60

RESULTS_SUBDIR = "results"
SAMPLES_FNAME = "samples.json"
INDETERMINATE_FNAME = "indeterminate_samples.json"

_ITERATION_SUFFIX_RE = re.compile(r"_iter_\d+$")


# ── Run-artifact loading ─────────────────────────────────────────────────


def _results_path(run_dir: str, fname: str) -> str:
    return os.path.join(run_dir, RESULTS_SUBDIR, fname)


def load_run_results(run_dir: str) -> Tuple[List[Any], List[Any]]:
    """Return ``(samples, as_run_indeterminate)`` from a run output directory."""
    samples_path = _results_path(run_dir, SAMPLES_FNAME)
    if not os.path.isfile(samples_path):
        raise FileNotFoundError(
            f"No {RESULTS_SUBDIR}/{SAMPLES_FNAME} under {run_dir!r}; is this a "
            "knowledge evolution run output directory?"
        )
    with open(samples_path, "r", encoding="utf-8") as f:
        samples = json.load(f)
    if not isinstance(samples, list):
        raise ValueError(
            f"{samples_path} must contain a list of iteration records; got "
            f"{type(samples).__name__}"
        )

    indeterminate: List[Any] = []
    indeterminate_path = _results_path(run_dir, INDETERMINATE_FNAME)
    if os.path.isfile(indeterminate_path):
        try:
            with open(indeterminate_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                indeterminate = loaded
        except (OSError, json.JSONDecodeError):
            # Advisory only — the replay below is self-contained.
            indeterminate = []
    return samples, indeterminate


def _first_tag(value: Any) -> str:
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return ""


def extract_first_pass(records: Iterable[Any]) -> Tuple[List[Dict[str, Any]], int]:
    """First-pass observations in run order, plus a count of unusable records.

    Mirrors ``engine._first_pass_observation``: one entry per sample from its
    ``iteration == 0`` record, carrying ``diagram_type`` (``tags.diagram_type``)
    and ``content_area`` (``tags.domain``) for bucketing.
    """
    observations: List[Dict[str, Any]] = []
    skipped = 0
    for record in records:
        if not isinstance(record, dict) or record.get("iteration") != 0:
            continue
        evaluation = record.get("evaluation")
        evaluation = evaluation if isinstance(evaluation, dict) else {}
        score = evaluation.get("score_before")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            skipped += 1
            continue
        record_id = str(record.get("id", ""))
        sample_id = _ITERATION_SUFFIX_RE.sub("", record_id) or record_id
        tags = record.get("tags") if isinstance(record.get("tags"), dict) else {}
        observations.append(
            {
                "sample_id": sample_id or f"sample_{len(observations)}",
                "diagram_type": _first_tag(tags.get("diagram_type")),
                "content_area": _first_tag(tags.get("domain")),
                "score_before": float(score),
            }
        )
    return observations, skipped


# ── Baseline replay (self-contained mirror of engine.FirstPassBaseline) ──
#
# Kept local so the CLI does not drag in the engine's heavy import chain
# (LLM factory, canvas workflows, ChromaDB). ``engine.FirstPassBaseline``
# remains the authority for live behaviour; this replay implements the same
# bucketing, fallback order and cold-start gate.


class _ReplayBaseline:
    def __init__(self, min_samples: int):
        self.min_samples = max(1, int(min_samples))
        self.pair_stats: Dict[Tuple[str, str], Tuple[int, float]] = {}
        self.type_stats: Dict[str, Tuple[int, float]] = {}
        self.global_stats: Tuple[int, float] = (0, 0.0)

    def lookup(self, diagram_type: str, content_area: str) -> Optional[float]:
        candidates = (
            self.pair_stats.get((diagram_type, content_area)),
            self.type_stats.get(diagram_type),
            self.global_stats,
        )
        for stats in candidates:
            if stats and stats[0] >= self.min_samples:
                return stats[1] / stats[0]
        return None

    def observe(self, diagram_type: str, content_area: str, score: float) -> None:
        def _add(stats):
            count, total = stats or (0, 0.0)
            return count + 1, total + score

        self.pair_stats[(diagram_type, content_area)] = _add(
            self.pair_stats.get((diagram_type, content_area))
        )
        self.type_stats[diagram_type] = _add(self.type_stats.get(diagram_type))
        self.global_stats = _add(self.global_stats)


def replay_judgments(
    observations: Sequence[Dict[str, Any]],
    *,
    min_samples: int,
    margins: Sequence[float],
) -> List[Dict[str, Any]]:
    """Per-margin success/failure/indeterminate counts over the run order.

    The baseline trajectory is identical for every margin (observation happens
    regardless of the verdict), so only the success/failure split moves.
    """
    table: List[Dict[str, Any]] = []
    for margin in margins:
        baseline = _ReplayBaseline(min_samples)
        success = failure = indeterminate = 0
        for obs in observations:
            mean = baseline.lookup(obs["diagram_type"], obs["content_area"])
            if mean is None:
                indeterminate += 1
            elif obs["score_before"] >= mean + margin:
                success += 1
            else:
                failure += 1
            baseline.observe(
                obs["diagram_type"], obs["content_area"], obs["score_before"]
            )
        judged = success + failure
        table.append(
            {
                "margin": float(margin),
                "success": success,
                "failure": failure,
                "indeterminate": indeterminate,
                "judged": judged,
                "success_rate": (success / judged) if judged else None,
            }
        )
    return table


# ── Distribution statistics ──────────────────────────────────────────────


def distribution_stats(scores: Sequence[float]) -> Optional[Dict[str, float]]:
    """n / mean / std / min / p25 / p50 / p75 / max for one score list.

    ``std`` is the sample standard deviation (``statistics.stdev``), reported as
    0.0 for a single point. Quartiles use ``statistics.quantiles(..., n=4,
    method="inclusive")``; for a single point every quantile equals that point.
    Returns ``None`` for an empty list.
    """
    if not scores:
        return None
    ordered = sorted(scores)
    n = len(ordered)
    if n >= 2:
        p25, p50, p75 = statistics.quantiles(ordered, n=4, method="inclusive")
        std = statistics.stdev(ordered)
    else:
        p25 = p50 = p75 = ordered[0]
        std = 0.0
    return {
        "n": n,
        "mean": statistics.fmean(ordered),
        "std": std,
        "min": ordered[0],
        "p25": p25,
        "p50": p50,
        "p75": p75,
        "max": ordered[-1],
    }


def bucket_label(diagram_type: str, content_area: str) -> str:
    return f"{diagram_type}/{content_area}"


# ── Suggestion rule ──────────────────────────────────────────────────────


def _distance_to_band(rate: float) -> float:
    if rate < TARGET_BAND_LOW:
        return TARGET_BAND_LOW - rate
    if rate > TARGET_BAND_HIGH:
        return rate - TARGET_BAND_HIGH
    return 0.0


def recommend_margin(
    table: Sequence[Dict[str, Any]],
) -> Tuple[Optional[float], str]:
    """Largest candidate margin inside the target band; see module docstring."""
    rated = [row for row in table if row["success_rate"] is not None]
    if not rated:
        return None, (
            "no candidate margin judged any sample (all indeterminate); "
            "cannot recommend"
        )

    in_band = [
        row["margin"]
        for row in rated
        if TARGET_BAND_LOW <= row["success_rate"] <= TARGET_BAND_HIGH
    ]
    if in_band:
        return max(in_band), (
            f"largest candidate with judged success rate inside "
            f"{TARGET_BAND_LOW:.0%}-{TARGET_BAND_HIGH:.0%}"
        )

    closest = min(
        rated,
        key=lambda row: (_distance_to_band(row["success_rate"]), -row["margin"]),
    )
    return closest["margin"], (
        f"no candidate landed inside {TARGET_BAND_LOW:.0%}-{TARGET_BAND_HIGH:.0%}; "
        f"closest judged success rate {closest['success_rate']:.3f} at margin "
        f"{closest['margin']:.2f}"
    )


# ── Report assembly ──────────────────────────────────────────────────────


def build_report(
    run_dir: str,
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    margins: Sequence[float] = DEFAULT_MARGIN_CANDIDATES,
) -> Dict[str, Any]:
    samples, as_run_indeterminate = load_run_results(run_dir)
    observations, skipped = extract_first_pass(samples)

    scores = [obs["score_before"] for obs in observations]
    buckets: Dict[str, List[float]] = {}
    for obs in observations:
        label = bucket_label(obs["diagram_type"], obs["content_area"])
        buckets.setdefault(label, []).append(obs["score_before"])

    table = replay_judgments(observations, min_samples=min_samples, margins=margins)
    suggested, reason = recommend_margin(table)

    return {
        "run_dir": str(run_dir),
        "min_samples": int(min_samples),
        "sample_count": len(observations),
        "skipped_records": skipped,
        "as_run_indeterminate": len(as_run_indeterminate),
        "overall": distribution_stats(scores),
        "buckets": {
            label: distribution_stats(values)
            for label, values in sorted(buckets.items())
        },
        "margins": table,
        "suggested_margin": suggested,
        "suggestion_reason": reason,
    }


# ── Text rendering ───────────────────────────────────────────────────────


def _format_stats_row(label: str, stats: Dict[str, float]) -> str:
    return (
        f"{label:<28.28}{stats['n']:>5}{stats['mean']:>9.2f}{stats['std']:>8.2f}"
        f"{stats['min']:>8.2f}{stats['p25']:>8.2f}{stats['p50']:>8.2f}"
        f"{stats['p75']:>8.2f}{stats['max']:>8.2f}"
    )


_STATS_HEADER = (
    f"{'bucket':<28}{'n':>5}{'mean':>9}{'std':>8}{'min':>8}{'p25':>8}"
    f"{'p50':>8}{'p75':>8}{'max':>8}"
)


def format_report(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"Margin calibration report — run: {report['run_dir']}")
    summary = f"First-pass samples: {report['sample_count']}"
    if report["skipped_records"]:
        summary += (
            f" (skipped {report['skipped_records']} iteration-0 records "
            "without score_before)"
        )
    lines.append(summary)
    lines.append(
        f"Baseline replay: min_samples={report['min_samples']}, cold start "
        "(see module docstring for runs seeded from a persisted baseline)"
    )
    lines.append(
        f"Indeterminate samples recorded by the run itself: "
        f"{report['as_run_indeterminate']}"
    )
    lines.append("")

    lines.append("score_before distribution (first pass, iteration 0)")
    lines.append(_STATS_HEADER)
    if report["overall"] is None:
        lines.append("(no first-pass records found)")
    else:
        lines.append(_format_stats_row("overall", report["overall"]))
        for label, stats in report["buckets"].items():
            if stats is not None:
                lines.append(_format_stats_row(label, stats))
    lines.append("")

    lines.append("Margin sensitivity (verdicts replayed in run order)")
    lines.append(
        f"{'margin':>8}{'success':>9}{'failure':>9}{'indeterm.':>11}"
        f"{'judged':>8}{'success_rate':>14}"
    )
    for row in report["margins"]:
        rate = (
            f"{row['success_rate']:.3f}" if row["success_rate"] is not None else "-"
        )
        lines.append(
            f"{row['margin']:>8.2f}{row['success']:>9}{row['failure']:>9}"
            f"{row['indeterminate']:>11}{row['judged']:>8}{rate:>14}"
        )
    lines.append("")

    if report["suggested_margin"] is None:
        lines.append(
            f"Suggested first_pass_success_margin: none ({report['suggestion_reason']})"
        )
    else:
        lines.append(
            f"Suggested first_pass_success_margin: "
            f"{report['suggested_margin']:.2f}"
        )
        lines.append(f"  rule: {report['suggestion_reason']}")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────


def _parse_margins(raw: str) -> Tuple[float, ...]:
    try:
        margins = tuple(float(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--margins must be comma-separated numbers, got {raw!r}"
        ) from exc
    if not margins:
        raise argparse.ArgumentTypeError("--margins must list at least one value")
    return margins


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="margin_report",
        description=(
            "Calibrate first_pass_success_margin from a knowledge evolution "
            "run's score_before distribution."
        ),
    )
    parser.add_argument(
        "run_dir",
        help=(
            "Knowledge evolution run output directory (the one containing "
            "results/samples.json)."
        ),
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=(
            "first_pass_baseline_min_samples the run used; drives the replay's "
            f"cold-start gate (default: {DEFAULT_MIN_SAMPLES})."
        ),
    )
    parser.add_argument(
        "--margins",
        type=_parse_margins,
        default=DEFAULT_MARGIN_CANDIDATES,
        help=(
            "Comma-separated candidate margins "
            "(default: 0.0,0.25,0.5,0.75,1.0)."
        ),
    )
    args = parser.parse_args(argv)

    if args.min_samples < 1:
        parser.error("--min-samples must be >= 1")

    try:
        report = build_report(
            args.run_dir,
            min_samples=args.min_samples,
            margins=args.margins,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        # Clean CLI failure (exit code 2 + message) instead of a traceback.
        parser.error(str(exc))
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
