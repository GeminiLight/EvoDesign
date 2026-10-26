#!/usr/bin/env python3
"""
Evaluation Results Analysis Program

Aggregates evaluation result JSON files into per-method scores.

Reporting contract
------------------
Every reported mean is accompanied by the sample counts it was computed over:

* ``full_set_n``  — size of the evaluated set (the ``--dataset`` test set when
  given, otherwise the union of data ids found on disk).
* ``valid_n``     — samples that actually contributed a 1-5 score for a metric.
* the reasons for every excluded sample (missing generated output, evaluation
  error, metric not applicable, or no result file at all) plus the missing rate.

Missing samples are handled according to ``--missing-policy``:

* ``exclude`` (default) — a method's mean is computed over the samples it scored,
  and the missing rate is reported next to it. This keeps every reported number
  inside the 1-5 rubric.
* ``zero``             — samples where the method produced no diagram are scored
  0 before averaging, treating a failure to generate as the worst possible
  outcome.

``exclude`` is the default because 0 lies outside the 1-5 rubric that every
prompt defines, so a zero-filled mean is not comparable with a rubric score.
Both numbers are always reported, so neither reading is hidden.

When results were produced with ``--judge-runs k`` (k > 1 independent judge
evaluations per sample and metric, aggregated by median), each
``dimension_stats`` entry additionally carries a ``judge_retest_variance``
block: the mean/max of the per-sample standard deviation across the k judge
runs. That is the judge retest reliability number for the paper.
"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence
import argparse

# Keep direct `python evaluation/analysis/analysis_results.py` execution working
# without mutating sys.path when the module is imported as part of the package.
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.analysis import stats
from evaluation.utils import (
    METRIC_STATUS_NOT_APPLICABLE,
    RESULT_STATUS_FAILED,
    RESULT_STATUS_MISSING_OUTPUT,
    is_valid_score,
)

MISSING_POLICIES = ("exclude", "zero")
DEFAULT_MISSING_POLICY = "exclude"

# Why a sample contributed no score for a metric.
REASON_MISSING_OUTPUT = "missing_output"      # the method produced no diagram
REASON_EVAL_ERROR = "evaluation_error"        # the judge failed on this sample
REASON_NOT_APPLICABLE = "not_applicable"      # metric undefined for this sample
REASON_NO_RESULT_FILE = "no_result_file"      # never evaluated
REASON_METRIC_ABSENT = "metric_absent"        # result file does not carry it

# Only a failure to produce a diagram is attributable to the method itself, so it
# is the only exclusion reason that the ``zero`` policy penalises.
ZERO_FILLABLE_REASONS = (REASON_MISSING_OUTPUT,)


class EvaluationAnalyzer:
    """Evaluation Results Analyzer"""

    def __init__(
        self,
        missing_policy: str = DEFAULT_MISSING_POLICY,
        bootstrap_resamples: int = stats.DEFAULT_BOOTSTRAP_RESAMPLES,
        seed: int = stats.DEFAULT_SEED,
    ):
        self.metrics = [
            "content_dimension",
            "visual_dimension",
            "cognitive_dimension",
            "judge_preference",
        ]
        if missing_policy not in MISSING_POLICIES:
            raise ValueError(
                f"Unknown missing policy {missing_policy!r}. "
                f"Expected one of {list(MISSING_POLICIES)}"
            )
        self.missing_policy = missing_policy
        self.bootstrap_resamples = bootstrap_resamples
        self.seed = seed
        self.warnings: List[str] = []

    # ── discovery ────────────────────────────────────────────────────────

    def find_json_files(self, root_dir: str) -> List[str]:
        """Recursively find all JSON evaluation files"""
        json_files = []
        for root, dirs, files in os.walk(root_dir):
            for file in files:
                if file.endswith('.json') and not file.startswith('.'):
                    json_files.append(os.path.join(root, file))
        return sorted(json_files)

    def _is_sample_directory(self, directory: str) -> bool:
        """A sample directory holds the result JSON of a single data item."""
        try:
            items = os.listdir(directory)
        except (PermissionError, OSError):
            return False
        return any(
            item.endswith('.json') and not item.startswith('.') for item in items
        )

    def _is_method_directory(self, directory: str) -> bool:
        """A method directory is a directory whose children are sample directories.

        The rule is deterministic: no result JSON directly inside, and at least
        one immediate subdirectory that holds a result JSON. The previous
        heuristic required >=80% of subdirectories to contain exactly one JSON,
        so a method with a high failure rate was dropped from the report
        entirely and without warning.
        """
        if self._is_sample_directory(directory):
            return False
        try:
            subdirs = [
                d for d in sorted(os.listdir(directory))
                if os.path.isdir(os.path.join(directory, d)) and not d.startswith('.')
            ]
        except (PermissionError, OSError):
            return False
        if not subdirs:
            return False
        return any(
            self._is_sample_directory(os.path.join(directory, d)) for d in subdirs
        )

    def discover_method_directories(self, base_directory: str) -> List[str]:
        """Return every method directory under *base_directory*.

        Directories that are neither method directories nor containers of method
        directories are recorded in ``self.warnings`` instead of being silently
        dropped.
        """
        found: List[str] = []

        def _walk(directory: str) -> bool:
            """Return True when *directory* or a descendant is a method dir."""
            if self._is_method_directory(directory):
                found.append(directory)
                return True

            try:
                subdirs = [
                    os.path.join(directory, d)
                    for d in sorted(os.listdir(directory))
                    if os.path.isdir(os.path.join(directory, d)) and not d.startswith('.')
                ]
            except (PermissionError, OSError) as exc:
                self.warnings.append(f"Could not read directory {directory}: {exc}")
                return False

            matched = False
            for subdir in subdirs:
                if _walk(subdir):
                    matched = True
            if not matched and not subdirs:
                self.warnings.append(
                    f"Skipped {directory}: no evaluation result JSON found"
                )
            return matched

        if not os.path.isdir(base_directory):
            self.warnings.append(f"Not a directory: {base_directory}")
            return found

        if not _walk(base_directory) and not found:
            self.warnings.append(
                f"No method directory found under {base_directory}. A method "
                f"directory is one whose subdirectories contain result JSON files."
            )
        return found

    # ── per-sample extraction ────────────────────────────────────────────

    def extract_sample(self, json_file: str) -> Optional[Dict[str, Any]]:
        """Extract one sample's metric outcomes from a result JSON file.

        Returns ``None`` when the file is not an evaluation result file.
        """
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as exc:
            self.warnings.append(f"Error reading {json_file}: {exc}")
            return None

        if not isinstance(data, dict) or "data_id" not in data:
            return None

        data_id = str(data.get("data_id"))
        status = data.get("status")

        sample: Dict[str, Any] = {
            "data_id": data_id,
            "file": json_file,
            "status": status,
            "reference_image_available": data.get("reference_image_available"),
            "scores": {},
            "exclusions": {},
            "sub_scores": defaultdict(list),
            # Per-metric judge retest statistics, present only for metrics
            # whose result carries a ``judge_runs`` payload (k > 1 runs).
            "judge_retest": {},
        }

        if status == RESULT_STATUS_MISSING_OUTPUT:
            for metric in self.metrics:
                sample["exclusions"][metric] = REASON_MISSING_OUTPUT
            return sample

        images = data.get("images") or {}
        if not images:
            for metric in self.metrics:
                sample["exclusions"][metric] = REASON_EVAL_ERROR
            return sample

        for image_data in images.values():
            if not isinstance(image_data, dict) or image_data.get("error"):
                for metric in self.metrics:
                    sample["exclusions"].setdefault(metric, REASON_EVAL_ERROR)
                continue

            dimensions = image_data.get("dimensions") or {}
            flat: Dict[str, Dict[str, Any]] = {}
            for dimension_data in dimensions.values():
                if isinstance(dimension_data, dict):
                    for metric_key, metric_data in dimension_data.items():
                        if isinstance(metric_data, dict):
                            flat[metric_key] = metric_data

            for metric in self.metrics:
                metric_data = flat.get(metric)
                if metric_data is None:
                    if metric in (data.get("metrics") or self.metrics):
                        sample["exclusions"].setdefault(metric, REASON_METRIC_ABSENT)
                    continue

                # A metric is excluded per-metric, not per-sample: one failed
                # metric must not delete the other three scores of that sample.
                if metric_data.get("status") == METRIC_STATUS_NOT_APPLICABLE:
                    sample["exclusions"][metric] = REASON_NOT_APPLICABLE
                    continue
                if metric_data.get("error"):
                    sample["exclusions"][metric] = REASON_EVAL_ERROR
                    continue

                score = metric_data.get("score")
                if not is_valid_score(score):
                    sample["exclusions"][metric] = REASON_EVAL_ERROR
                    continue

                sample["scores"][metric] = score

                # Judge resampling provenance (written only when k > 1): used
                # to report within-sample judge variance ("retest variance").
                judge_runs_data = metric_data.get("judge_runs")
                if isinstance(judge_runs_data, dict):
                    sample["judge_retest"][metric] = self._summarize_judge_runs(
                        judge_runs_data
                    )

                sub_scores = metric_data.get("sub_scores") or {}
                if isinstance(sub_scores, dict):
                    for sub_metric, sub_score in sub_scores.items():
                        if is_valid_score(sub_score):
                            sample["sub_scores"][f"{metric}_{sub_metric}"].append(sub_score)

        if status == RESULT_STATUS_FAILED:
            for metric in self.metrics:
                if metric not in sample["scores"]:
                    sample["exclusions"].setdefault(metric, REASON_EVAL_ERROR)

        sample["sub_scores"] = dict(sample["sub_scores"])
        return sample

    @staticmethod
    def _summarize_judge_runs(judge_runs_data: Dict[str, Any]) -> Dict[str, Any]:
        """Reduce one metric's stored judge-resampling payload to retest stats.

        ``std`` prefers the value written by the scorer and falls back to
        recomputing the sample standard deviation (n-1) from the raw values,
        so hand-edited or older payloads still contribute.
        """
        values = [
            value
            for value in (judge_runs_data.get("values") or [])
            if is_valid_score(value)
        ]
        std = judge_runs_data.get("std")
        if isinstance(std, bool) or not isinstance(std, (int, float)):
            std = stats.stdev(values)
        return {
            "k": judge_runs_data.get("k"),
            "n_valid": len(values),
            "std": std,
            "range": (max(values) - min(values)) if len(values) >= 2 else None,
        }

    # ── per-method aggregation ───────────────────────────────────────────

    def analyze_directory(
        self,
        directory: str,
        dataset_ids: Optional[Sequence[str]] = None,
        root_directory: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Aggregate one method directory into a report entry."""
        json_files = self.find_json_files(directory)
        samples: Dict[str, Dict[str, Any]] = {}

        for json_file in json_files:
            sample = self.extract_sample(json_file)
            if sample is None:
                continue
            if sample["data_id"] in samples:
                self.warnings.append(
                    f"Duplicate result for data_id {sample['data_id']} in {directory}; "
                    f"keeping {samples[sample['data_id']]['file']}"
                )
                continue
            samples[sample["data_id"]] = sample

        if not samples:
            self.warnings.append(f"No parseable evaluation results in {directory}")
            return None

        if dataset_ids is not None:
            full_ids: List[str] = list(dataset_ids)
            unexpected = sorted(set(samples) - set(full_ids))
            if unexpected:
                self.warnings.append(
                    f"{directory}: {len(unexpected)} result file(s) are not in the "
                    f"dataset and are excluded: {unexpected[:5]}"
                    + ("..." if len(unexpected) > 5 else "")
                )
        else:
            full_ids = sorted(samples)

        full_n = len(full_ids)

        status_counts = {
            "result_files": len(samples),
            "success": 0,
            "failed": 0,
            "missing_output": 0,
            "no_result_file": 0,
        }
        missing_output_ids: List[str] = []
        absent_ids: List[str] = []

        for data_id in full_ids:
            sample = samples.get(data_id)
            if sample is None:
                status_counts["no_result_file"] += 1
                absent_ids.append(data_id)
            elif sample["status"] == RESULT_STATUS_MISSING_OUTPUT:
                status_counts["missing_output"] += 1
                missing_output_ids.append(data_id)
            elif sample["status"] == RESULT_STATUS_FAILED:
                status_counts["failed"] += 1
            else:
                status_counts["success"] += 1

        produced_n = full_n - status_counts["missing_output"] - status_counts["no_result_file"]
        missing_rate = (
            (status_counts["missing_output"] + status_counts["no_result_file"]) / full_n
            if full_n
            else 0.0
        )

        dimension_stats: Dict[str, Any] = {}
        dimension_scores: Dict[str, float] = {}
        per_sample_scores: Dict[str, Dict[str, float]] = {}

        for metric in self.metrics:
            values: List[float] = []
            reasons: Dict[str, int] = defaultdict(int)
            metric_series: Dict[str, float] = {}

            for data_id in full_ids:
                sample = samples.get(data_id)
                if sample is None:
                    reasons[REASON_NO_RESULT_FILE] += 1
                    continue
                if metric in sample["scores"]:
                    value = sample["scores"][metric]
                    values.append(value)
                    metric_series[data_id] = value
                else:
                    reasons[sample["exclusions"].get(metric, REASON_METRIC_ABSENT)] += 1

            if not values and not reasons:
                continue

            per_sample_scores[metric] = metric_series

            zero_fill = sum(reasons.get(reason, 0) for reason in ZERO_FILLABLE_REASONS)
            values_with_zeros = values + [0.0] * zero_fill

            entry = stats.describe(
                values,
                resamples=self.bootstrap_resamples,
                seed=self.seed,
            )
            entry["full_set_n"] = full_n
            entry["valid_n"] = len(values)
            entry["excluded_n"] = full_n - len(values)
            entry["excluded_reasons"] = dict(reasons)
            entry["mean_missing_as_zero"] = (
                round(sum(values_with_zeros) / len(values_with_zeros), 4)
                if values_with_zeros
                else None
            )
            entry["zero_filled_n"] = zero_fill

            # Judge retest variance: how much a single (sample, metric) score
            # moves across repeated judge calls at temperature=1. Reported per
            # metric so the paper can quantify judge retest reliability. Only
            # present when the stored results carry judge_runs payloads (k>1).
            retest_items: List[Dict[str, Any]] = []
            for data_id in full_ids:
                sample = samples.get(data_id)
                if sample is None:
                    continue
                retest = sample["judge_retest"].get(metric)
                if retest:
                    retest_items.append(retest)
            if retest_items:
                stds = [
                    item["std"]
                    for item in retest_items
                    if isinstance(item["std"], (int, float))
                    and not isinstance(item["std"], bool)
                ]
                ranges = [
                    item["range"] for item in retest_items
                    if item["range"] is not None
                ]
                entry["judge_retest_variance"] = {
                    "n_samples": len(retest_items),
                    "mean_within_sample_std": (
                        round(sum(stds) / len(stds), 4) if stds else None
                    ),
                    "max_within_sample_std": (
                        round(max(stds), 4) if stds else None
                    ),
                    "mean_within_sample_range": (
                        round(sum(ranges) / len(ranges), 4) if ranges else None
                    ),
                }

            dimension_stats[metric] = entry

            headline = (
                entry["mean_missing_as_zero"]
                if self.missing_policy == "zero"
                else entry["mean"]
            )
            if headline is not None:
                dimension_scores[metric] = headline

        sub_scores_collection: Dict[str, List[float]] = defaultdict(list)
        for data_id in full_ids:
            sample = samples.get(data_id)
            if sample is None:
                continue
            for key, values in sample.get("sub_scores", {}).items():
                sub_scores_collection[key].extend(values)

        sub_scores_averages: Dict[str, float] = {}
        sub_scores_stats: Dict[str, Any] = {}
        for key, values in sorted(sub_scores_collection.items()):
            if not values:
                continue
            sub_scores_averages[key] = round(sum(values) / len(values), 4)
            sub_scores_stats[key] = stats.describe(
                values,
                resamples=self.bootstrap_resamples,
                seed=self.seed,
            )

        if not dimension_scores and not sub_scores_averages:
            return None

        return {
            "algorithm_name": self._extract_algorithm_name(directory, root_directory),
            "directory": directory,
            "missing_policy": self.missing_policy,
            "sample_counts": {
                "full_set_n": full_n,
                "full_set_source": "dataset" if dataset_ids is not None else "result files on disk",
                "result_files_n": status_counts["result_files"],
                "produced_output_n": produced_n,
                "success_n": status_counts["success"],
                "failed_n": status_counts["failed"],
                "missing_output_n": status_counts["missing_output"],
                "no_result_file_n": status_counts["no_result_file"],
                "missing_rate": round(missing_rate, 4),
            },
            "missing_output_data_ids": missing_output_ids,
            "no_result_file_data_ids": absent_ids,
            "dimension_scores": dimension_scores,
            "dimension_stats": dimension_stats,
            "sub_scores": sub_scores_averages,
            "sub_score_stats": sub_scores_stats,
            "_per_sample_scores": per_sample_scores,
        }

    def _extract_algorithm_name(
        self,
        directory: str,
        root_directory: Optional[str] = None,
    ) -> str:
        """Extract a stable, readable algorithm name from a directory path."""
        if root_directory:
            try:
                relative = os.path.relpath(directory, root_directory)
            except ValueError:
                relative = ""
            if relative and relative != os.curdir and not relative.startswith(os.pardir):
                return Path(relative).as_posix()

        parts = Path(directory).parts
        for anchor in ("scores", "evaluations"):
            if anchor in parts:
                remaining = parts[parts.index(anchor) + 1:]
                if remaining:
                    return '/'.join(remaining)
        return Path(directory).name

    def analyze_multiple_methods(
        self,
        base_directory: str,
        dataset_ids: Optional[Sequence[str]] = None,
        method_directories: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate every requested (or discovered) method directory."""
        if method_directories:
            directories = []
            for candidate in method_directories:
                path = candidate if os.path.isabs(candidate) else os.path.join(base_directory, candidate)
                if not os.path.isdir(path):
                    self.warnings.append(f"Requested method directory not found: {path}")
                    continue
                directories.append(path)
        else:
            directories = self.discover_method_directories(base_directory)

        results = []
        for directory in directories:
            result = self.analyze_directory(
                directory,
                dataset_ids=dataset_ids,
                root_directory=base_directory,
            )
            if result:
                results.append(result)
            else:
                self.warnings.append(f"No usable scores in {directory}")
        return results

    # ── comparisons ──────────────────────────────────────────────────────

    def compare_methods(
        self,
        results: List[Dict[str, Any]],
        reference_name: str,
    ) -> List[Dict[str, Any]]:
        """Paired Wilcoxon signed-rank tests against a reference method."""
        by_name = {r["algorithm_name"]: r for r in results}
        reference = by_name.get(reference_name)
        if reference is None:
            self.warnings.append(
                f"--compare-to {reference_name!r} not found. "
                f"Available: {sorted(by_name)}"
            )
            return []

        comparisons = []
        for result in results:
            if result["algorithm_name"] == reference_name:
                continue
            for metric in self.metrics:
                ref_series = reference.get("_per_sample_scores", {}).get(metric, {})
                cand_series = result.get("_per_sample_scores", {}).get(metric, {})
                shared = sorted(set(ref_series) & set(cand_series))
                if len(shared) < 2:
                    continue

                candidate_values = [cand_series[i] for i in shared]
                reference_values = [ref_series[i] for i in shared]
                differences = [c - r for c, r in zip(candidate_values, reference_values)]

                test = stats.wilcoxon_signed_rank(candidate_values, reference_values)
                ci = stats.bootstrap_ci(
                    differences,
                    resamples=self.bootstrap_resamples,
                    seed=self.seed,
                )
                comparisons.append({
                    "algorithm_name": result["algorithm_name"],
                    "reference": reference_name,
                    "metric": metric,
                    "n_pairs": len(shared),
                    "mean_difference": round(sum(differences) / len(differences), 4),
                    "wilcoxon": test,
                    "bootstrap_ci95_of_mean_difference": (
                        None if ci is None else [round(ci[0], 4), round(ci[1], 4)]
                    ),
                    "bootstrap_resamples": self.bootstrap_resamples,
                    "bootstrap_seed": self.seed,
                })
        return comparisons

    def generate_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate summary statistics across methods."""
        if not results:
            return {}

        summary: Dict[str, Any] = {
            "total_algorithms": len(results),
            "missing_policy": self.missing_policy,
            "dimension_averages": {},
            "sub_scores_averages": {},
            "coverage": {},
        }

        all_dimension_scores = defaultdict(list)
        all_sub_scores = defaultdict(list)

        for result in results:
            for metric, score in result.get('dimension_scores', {}).items():
                all_dimension_scores[metric].append(score)
            for sub_metric, score in result.get('sub_scores', {}).items():
                all_sub_scores[sub_metric].append(score)
            counts = result.get("sample_counts", {})
            summary["coverage"][result["algorithm_name"]] = {
                "full_set_n": counts.get("full_set_n"),
                "missing_rate": counts.get("missing_rate"),
                "valid_n_by_metric": {
                    metric: entry.get("valid_n")
                    for metric, entry in result.get("dimension_stats", {}).items()
                },
            }

        for metric, scores in all_dimension_scores.items():
            if scores:
                summary["dimension_averages"][metric] = round(sum(scores) / len(scores), 4)

        for sub_metric, scores in all_sub_scores.items():
            if scores:
                summary["sub_scores_averages"][sub_metric] = round(sum(scores) / len(scores), 4)

        return summary


def load_dataset_ids(dataset_path: str) -> List[str]:
    """Load the ordered data ids of the evaluated test set."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    ids = []
    for item in data:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.append(str(item["id"]))
    if not ids:
        raise ValueError(f"No data ids found in dataset: {dataset_path}")
    return ids


def main():
    parser = argparse.ArgumentParser(
        description='Analyze evaluation result JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Analyze a single method directory
  python analysis_results.py experiments/2026-05-06/scores/baseline/pixel/flux-2-flex

  # Analyze every method under a tree, aligned to the full test set
  python analysis_results.py experiments/2026-05-06/scores \\
      --dataset dataset/test/data.json --summary

  # Score missing generations as 0 instead of excluding them
  python analysis_results.py experiments/2026-05-06/scores \\
      --dataset dataset/test/data.json --missing-policy zero

  # Paired Wilcoxon signed-rank tests against EvoDiagram
  python analysis_results.py experiments/2026-05-06/scores \\
      --dataset dataset/test/data.json --compare-to evodiagram/evodiagram/gpt-5.2

  # Restrict to explicit method directories (no discovery)
  python analysis_results.py experiments/2026-05-06/scores \\
      --method baseline/code_mermaid/gpt-5.2 --method evodiagram/evodiagram/gpt-5.2
        '''
    )

    parser.add_argument('directory', help='Evaluation results directory path')
    parser.add_argument('--output', '-o', help='Output JSON file path (optional)')
    parser.add_argument('--indent', type=int, default=2, help='JSON output indentation (default 2)')
    parser.add_argument('--summary', '-s', action='store_true', help='Generate summary statistics')
    parser.add_argument(
        '--dataset',
        help=(
            'Path to the evaluated test set JSON. Aligns every method to the '
            'same full sample set so that missing samples are visible instead '
            'of shrinking the denominator.'
        ),
    )
    parser.add_argument(
        '--missing-policy',
        choices=MISSING_POLICIES,
        default=DEFAULT_MISSING_POLICY,
        help=(
            'How to treat samples where the method produced no diagram. '
            '"exclude" (default) averages over scored samples and reports the '
            'missing rate; "zero" scores them 0. Both means are always present '
            'in dimension_stats.'
        ),
    )
    parser.add_argument(
        '--method',
        action='append',
        dest='methods',
        help=(
            'Explicit method directory (relative to DIRECTORY or absolute). '
            'Repeatable. Disables directory discovery.'
        ),
    )
    parser.add_argument(
        '--compare-to',
        help='Algorithm name to use as the reference of paired significance tests',
    )
    parser.add_argument(
        '--bootstrap',
        type=int,
        default=stats.DEFAULT_BOOTSTRAP_RESAMPLES,
        help=f'Bootstrap resamples (default {stats.DEFAULT_BOOTSTRAP_RESAMPLES}; 0 disables)',
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=stats.DEFAULT_SEED,
        help=f'Bootstrap seed (default {stats.DEFAULT_SEED})',
    )

    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: Directory not found: {args.directory}", file=sys.stderr)
        sys.exit(1)

    dataset_ids = None
    if args.dataset:
        try:
            dataset_ids = load_dataset_ids(args.dataset)
        except Exception as exc:
            print(f"Error: could not load dataset {args.dataset}: {exc}", file=sys.stderr)
            sys.exit(1)

    analyzer = EvaluationAnalyzer(
        missing_policy=args.missing_policy,
        bootstrap_resamples=args.bootstrap,
        seed=args.seed,
    )

    results = analyzer.analyze_multiple_methods(
        args.directory,
        dataset_ids=dataset_ids,
        method_directories=args.methods,
    )

    if not results:
        for warning in analyzer.warnings:
            print(f"[WARN] {warning}", file=sys.stderr)
        print("No evaluation result files found", file=sys.stderr)
        sys.exit(1)

    comparisons = []
    if args.compare_to:
        comparisons = analyzer.compare_methods(results, args.compare_to)

    # Per-sample series are an implementation detail of the paired tests.
    public_results = [
        {k: v for k, v in result.items() if not k.startswith("_")}
        for result in results
    ]

    output_data = {
        "analysis_directory": args.directory,
        "dataset": args.dataset,
        "missing_policy": args.missing_policy,
        "bootstrap_resamples": args.bootstrap,
        "bootstrap_seed": args.seed,
        "total_algorithms": len(public_results),
        "algorithms": public_results,
    }

    if comparisons:
        output_data["comparisons"] = comparisons

    if args.summary:
        output_data["summary"] = analyzer.generate_summary(results)

    if analyzer.warnings:
        output_data["warnings"] = analyzer.warnings
        for warning in analyzer.warnings:
            print(f"[WARN] {warning}", file=sys.stderr)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=args.indent)
        print(f"Results saved to: {args.output}", file=sys.stderr)
    else:
        print(json.dumps(output_data, ensure_ascii=False, indent=args.indent))


if __name__ == "__main__":
    main()
