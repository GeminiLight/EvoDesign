#!/usr/bin/env python3
"""
Run Diagram Evaluation

Main entry script for running diagram evaluation.

Default configuration:
    - exp_name: example_exp
    - method_name: example_method

Default paths (constructed based on exp_name and method_name):
    - Input JSON: {PROJECT_ROOT}/dataset/train/.example.json
    - Generated images directory: {PROJECT_ROOT}/experiments/{exp_id}/outputs/{method_name}/...
    - Output directory: {PROJECT_ROOT}/experiments/{exp_id}/scores/{method_name}

Output file naming:
    - {exp_name}_{method_name}_{data_id}.json
    - {exp_name}_{method_name}_{data_id}_report.txt

Usage:
    # Evaluate all data items in input JSON
    python run_evaluation.py

    # Evaluate only data item with specific ID
    python run_evaluation.py --data-id example_001

    # Specify custom input JSON and method path
    python -m evaluation.run_evaluation --input-json dataset/train/my_example.json --method evodiagram/gpt-5.2 --exp-id 2026-05-06

    # Evaluate only specific metrics (dimension-level)
    python run_evaluation.py --metrics content_dimension visual_dimension

    # Use concurrent workers for parallel evaluation
    python run_evaluation.py --workers 4

    # Judge resampling: evaluate each (sample, metric) k independent times and
    # store the median (raw values/mean/std are kept in a judge_runs field)
    python run_evaluation.py --method evodiagram --judge-runs 3

    # Skip already evaluated items (default behavior)
    python run_evaluation.py --method baselines/mermaid/gpt-5.5

    # Force re-evaluation even if a matching result exists
    python run_evaluation.py --method baselines/direct_llm/gpt-5.5 --regeneration

    # Re-run only the data items whose stored result is missing/failed/stale
    python run_evaluation.py --method baselines/direct_llm/gpt-5.5 --rerun-failed

    # Combine with other options
    python run_evaluation.py --method baselines/mermaid/gpt-5.5 --workers 8 --start 1 --end 100

    # Show verbose logs
    python run_evaluation.py --verbose
"""

import sys
import argparse
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Keep direct `python evaluation/run_evaluation.py` execution working without
# mutating sys.path when the module is imported as part of the package.
if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

from evaluation.metric_scorer import (
    DIMENSION_METRICS,
    LEGACY_TO_DIMENSION,
    MetricScorer,
)
from evaluation.utils import (
    METRIC_STATUS_NOT_APPLICABLE,
    RESULT_STATUS_FAILED,
    RESULT_STATUS_MISSING_OUTPUT,
    RESULT_STATUS_SUCCESS,
    build_run_signature,
    create_evaluation_report,
    is_valid_score,
    run_signature_matches,
    save_results,
)
from evaluation.path_resolver import (
    AmbiguousSubmodelError,
    get_reference_image_path,
    parse_method_paths,
)

logger = logging.getLogger(__name__)

# === Default configuration ===
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])

# Default method name
DEFAULT_METHOD = "evodiagram"

# Default paths
DEFAULT_INPUT_JSON = str(Path(__file__).resolve().parents[1] / "dataset" / "test" / "data.json")

# Fallback response budget for the judge when models.yaml declares no
# ``max_tokens`` for the evaluation role. The content_dimension prompt asks for a
# nested ``details`` block with ~25 fields plus issue lists and a rationale
# paragraph; combined with models that emit reasoning tokens, 4000 was tight
# enough that truncation produced unparseable JSON. Truncated JSON now surfaces
# as an explicit metric error (see metrics/base_metric.py), so the only cost of a
# larger budget is tokens, while the cost of a smaller one is lost samples.
DEFAULT_EVAL_MAX_TOKENS = 8000

# === All available metrics ===
ALL_METRICS = []
for dim_metrics in DIMENSION_METRICS.values():
    ALL_METRICS.extend(dim_metrics)


def positive_int(value: str) -> int:
    """argparse type validator: an int >= 1."""
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}")
    if ivalue < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {ivalue}")
    return ivalue


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Diagram Evaluation Tool - Evaluate diagram quality using multimodal VLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Evaluate all data items in input JSON
  python run_evaluation.py

  # Evaluate only data item with specific ID
  python run_evaluation.py --data-id example_001

  # Specify input data and experiment paths
  python -m evaluation.run_evaluation --input-json dataset/train/my.json --method evodiagram/gpt-5.2 --exp-id 2026-05-06

  # Use explicit YAML configs
  python -m evaluation.run_evaluation --settings configs/settings.yaml --model-config configs/models.yaml

  # Evaluate only specific metrics (dimension-level)
  python run_evaluation.py --metrics content_dimension visual_dimension

  # Use concurrent workers for parallel evaluation
  python run_evaluation.py --workers 4

  # Judge resampling: k independent judge runs per (sample, metric), median wins
  python run_evaluation.py --method evodiagram --judge-runs 3

  # Evaluate the Mermaid baseline (stored under code_mermaid)
  python run_evaluation.py --method baselines/mermaid/gpt-5.5

  # Force direct LLM baseline re-evaluation even if report exists
  python run_evaluation.py --method baselines/direct_llm/gpt-5.5 --regeneration

  # Combine with other options
  python run_evaluation.py --method baselines/mermaid/gpt-5.5 --workers 8 --start 1 --end 100

Available metrics:
  Content:   {', '.join(DIMENSION_METRICS.get('content', []))}
  Visual:    {', '.join(DIMENSION_METRICS.get('visual', []))}
  Cognitive: {', '.join(DIMENSION_METRICS.get('cognitive', []))}
        """
    )

    # === Data path parameters ===
    parser.add_argument(
        "--input-json",
        default=DEFAULT_INPUT_JSON,
        help=f"Input JSON file path containing data array (default: {DEFAULT_INPUT_JSON})",
    )

    parser.add_argument(
        "--data-id",
        default=None,
        help="Data item ID to evaluate. If not specified, all data items will be evaluated",
    )

    parser.add_argument(
        "--method",
        default=DEFAULT_METHOD,
        help=f"Method name for path resolution. Format: 'evodiagram' OR 'baselines/<type>/<model>' (e.g., baselines/mermaid/gpt-5.5, baselines/direct_llm/gpt-5.5) OR 'baselines_<type>_<model>' (default: {DEFAULT_METHOD})",
    )

    parser.add_argument(
        "--exp-id",
        default=None,
        help="Experiment ID for experiments/ directory. Overrides EVO_EXPERIMENT_ID env var and settings.yaml.",
    )

    parser.add_argument(
        "--settings",
        default=None,
        help="Path to settings YAML (default: configs/settings.yaml)",
    )

    parser.add_argument(
        "--model-config",
        default=None,
        help="Path to models YAML (default: configs/models.yaml)",
    )

    parser.add_argument(
        "--eval-role",
        default=None,
        help="Model role for evaluation scoring (default: evaluation.role from settings.yaml, then 'eval')",
    )

    parser.add_argument(
        "--evodiagram_wo_refiner",
        action="store_true",
        help="Use evodiagram without refiner (reads from evodiagram_wo_refiner outputs, writes scores to evodiagram_wo_refiner/)",
    )

    # === Evaluation configuration parameters ===
    parser.add_argument(
        "--metrics",
        nargs="+",
        default=None,
        help=(
            "List of metrics to evaluate. If not specified, "
            "evaluation.default_metrics from settings.yaml is used, then the "
            "built-in full list. Unknown names are an error, not a warning."
        ),
    )

    # === Output parameters ===
    # Output dir will be auto-computed based on method, no longer user-specified

    # === Range parameters ===
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="Start index (1-based) for batch processing. Process from this data item onwards.",
    )

    parser.add_argument(
        "--end",
        type=int,
        default=None,
        help="End index (1-based, inclusive) for batch processing. Process up to and including this data item.",
    )

    # === Logging parameters ===
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose logs",
    )

    # === Concurrency parameters ===
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent workers for parallel evaluation (default: 1, no concurrency)",
    )

    # === Regeneration parameters ===
    parser.add_argument(
        "--regeneration",
        action="store_true",
        help="Regenerate evaluation even if a matching result already exists (default: False, reuse existing)",
    )

    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help=(
            "Restrict this run to data items whose stored result is not reusable "
            "(missing, failed, missing_output, or produced by a different "
            "judge/prompt). Items with a reusable result are not re-evaluated."
        ),
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help=(
            "Max response tokens for the judge model. Defaults to models.yaml "
            f"max_tokens for the evaluation role, then {DEFAULT_EVAL_MAX_TOKENS}."
        ),
    )

    # === Judge resampling ===
    parser.add_argument(
        "--judge-runs",
        type=positive_int,
        default=1,
        help=(
            "Number of independent judge evaluations per (sample, metric). "
            "The final score is the median of the valid runs; the raw values, "
            "mean, std and median are stored in a 'judge_runs' field of each "
            "metric result. k is part of the run signature, so changing it "
            "invalidates stored results. (default: 1, single judge run)"
        ),
    )

    return parser.parse_args()


def get_metrics_to_evaluate(args, settings=None) -> list:
    """Determine metrics to evaluate.

    Precedence: ``--metrics`` → ``evaluation.default_metrics`` in settings.yaml →
    the built-in full metric list.

    Raises:
        ValueError: when any requested name is unknown, or when the resolved list
            is empty. Silently dropping a mistyped metric used to produce result
            files marked ``success`` that contained no scores at all.
    """
    if args.metrics:
        requested = list(args.metrics)
        source = "--metrics"
    else:
        configured = list(getattr(settings, "evaluation_default_metrics", None) or [])
        if configured:
            requested = configured
            source = "settings.yaml evaluation.default_metrics"
        else:
            requested = list(ALL_METRICS)
            source = "built-in default metric list"

    resolved: List[str] = []
    unknown: List[str] = []
    for name in requested:
        target = name if name in ALL_METRICS else LEGACY_TO_DIMENSION.get(name)
        if target not in ALL_METRICS:
            unknown.append(name)
            continue
        if target not in resolved:
            resolved.append(target)

    if unknown:
        raise ValueError(
            f"Unknown metric name(s) from {source}: {unknown}. "
            f"Available metrics: {ALL_METRICS}. "
            f"Legacy aliases: {sorted(LEGACY_TO_DIMENSION)}"
        )
    if not resolved:
        raise ValueError(
            f"No metrics resolved from {source}. Available metrics: {ALL_METRICS}"
        )

    logger.info("Metrics resolved from %s: %s", source, resolved)
    return resolved


def result_has_metric_errors(image_results: Dict[str, Any], metrics: List[str]) -> bool:
    """Return True when any requested metric failed instead of producing a score.

    A metric explicitly marked ``not_applicable`` (for example judge_preference
    without its reference image) is *not* an error: it is an expected, permanent
    condition that the aggregator excludes rather than a run that should be
    retried. A metric that claims to be scored but carries a value outside the
    1-5 rubric is an error.
    """
    if not metrics:
        # An empty metric list means nothing was actually measured.
        return True

    for metric_name in metrics:
        found = False
        for dimension_results in image_results.get("dimensions", {}).values():
            metric_result = dimension_results.get(metric_name)
            if metric_result is None:
                continue
            found = True
            if metric_result.get("error"):
                return True
            if metric_result.get("status") == METRIC_STATUS_NOT_APPLICABLE:
                continue
            if not is_valid_score(metric_result.get("score")):
                return True
        if not found:
            return True
    return False


def load_existing_result(result_path: Path) -> Optional[Dict[str, Any]]:
    """Load a stored result JSON, returning None when unreadable."""
    if not result_path.exists():
        return None
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not read existing result %s: %s", result_path, exc)
        return None


def existing_evaluation_succeeded(
    result_path: Path,
    metrics: List[str],
    run_signature: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether an existing result JSON is a reusable successful evaluation."""
    state, _ = classify_existing_result(result_path, metrics, run_signature)
    return state == "reusable"


def classify_existing_result(
    result_path: Path,
    metrics: List[str],
    run_signature: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Classify a stored result file.

    Returns ``(state, detail)`` where *state* is one of:
        ``"missing"``    — no result file on disk
        ``"unreadable"`` — file exists but could not be parsed
        ``"failed"``     — the stored run did not produce all requested scores
        ``"stale"``      — scores exist but came from a different judge model,
                           judge temperature, metric set, or prompt revision
        ``"reusable"``   — safe to skip re-evaluation

    Only ``"reusable"`` may be skipped. Everything else must be re-evaluated:
    reusing a *stale* file silently mixes two judges into one table, and
    "skipping" a *failed* file leaves a partial result on disk forever.
    """
    if not result_path.exists():
        return "missing", "no stored result"

    result = load_existing_result(result_path)
    if result is None:
        return "unreadable", "stored result could not be parsed"

    status = result.get("status")
    if status in (RESULT_STATUS_FAILED, RESULT_STATUS_MISSING_OUTPUT):
        return "failed", f"stored status is {status!r}"

    images = result.get("images", {})
    if not images:
        return "failed", "stored result contains no evaluated image"

    for image_results in images.values():
        if not isinstance(image_results, dict):
            return "failed", "stored image result is malformed"
        if "error" in image_results:
            return "failed", f"stored image error: {image_results.get('error')}"
        if result_has_metric_errors(image_results, metrics):
            return "failed", "stored result is missing or errored for a requested metric"

    matches, reason = run_signature_matches(
        result.get("run_signature"), run_signature, metrics
    )
    if not matches:
        return "stale", reason

    return "reusable", ""


def find_generated_image_by_method(method: str, data_id: str, exp_id: str = None) -> Optional[str]:
    """
    Find generated image for data ID using method-based path resolution.

    Args:
        method: Method name (e.g., "evodiagram", "baselines_code_mermaid_deepseek-r1")
        data_id: Data item ID
        exp_id: Optional experiment ID override

    Returns:
        Found image path, returns None if not found
    """
    try:
        image_path, _, _ = parse_method_paths(method, data_id, exp_id=exp_id)

        if image_path.exists():
            logger.info(f"Found image for {data_id} using method '{method}': {image_path}")
            return str(image_path)

        logger.warning(f"No image found for data_id: {data_id} at {image_path}")
        return None

    except AmbiguousSubmodelError:
        # Never downgrade this to "image not found": it is a configuration error
        # that would otherwise be silently resolved by picking another model's
        # output.
        raise
    except ValueError as e:
        logger.error(f"Error parsing method '{method}': {e}")
        return None


def load_all_data_items(input_json_path: str) -> List[Dict[str, Any]]:
    """
    Load all data items from input JSON file

    Args:
        input_json_path: JSON file path

    Returns:
        Data items list
    """
    path = Path(input_json_path)
    if not path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {input_json_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Ensure it's in list format
    if isinstance(data, list):
        if len(data) == 0:
            raise ValueError(f"Input JSON is empty: {input_json_path}")
        return data
    else:
        # If it's a single object, wrap it in a list
        return [data]


def filter_data_items(data_items: List[Dict], data_id: str = None) -> List[Dict]:
    """
    Filter data items by data_id

    Args:
        data_items: All data items
        data_id: ID to filter by, returns all items if None

    Returns:
        Filtered data items list
    """
    if data_id is None:
        return data_items

    filtered = [item for item in data_items if item.get("id") == data_id]
    if not filtered:
        available_ids = [item.get("id", "unknown") for item in data_items]
        raise ValueError(f"Data ID '{data_id}' not found. Available IDs: {available_ids}")

    return filtered


def print_results_summary(results: dict):
    """Print results summary"""
    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)

    summary = results.get("summary", {})

    print(f"\nTotal images evaluated: {summary.get('total_images', 0)}")

    if summary.get("best_image"):
        print(f"Best image: {summary['best_image']} (avg: {summary['best_score']:.2f}/5)")

    if summary.get("worst_image"):
        print(f"Worst image: {summary['worst_image']} (avg: {summary['worst_score']:.2f}/5)")

    print("\n--- Scores by Image ---")
    for image_name, avg_score in summary.get("average_scores", {}).items():
        if isinstance(avg_score, (int, float)):
            print(f"  {image_name}: {avg_score:.2f}/5")
        else:
            print(f"  {image_name}: N/A (no valid metric score)")

    print("\n--- Average Scores by Metric ---")
    for metric_name, avg_score in summary.get("metric_averages", {}).items():
        print(f"  {metric_name}: {avg_score:.2f}/5")

    for metric_name in summary.get("metrics_without_scores", {}):
        print(f"  {metric_name}: N/A (excluded, no valid score)")

    print("\n" + "=" * 80)


def resolve_reference_image_path(data_id: str) -> Optional[str]:
    """
    Resolve reference image path for data ID.

    Looks for: ./dataset/images/diagrams/{data_id}.jpg

    Args:
        data_id: Data item ID

    Returns:
        Absolute path to reference image, returns None if not found
    """
    reference_path = get_reference_image_path(data_id)

    if reference_path.exists():
        logger.info(f"Found reference image for {data_id}")
        return str(reference_path)

    logger.info(f"No reference image found for {data_id} (optional)")
    return None


def build_result_skeleton(
    data_item: Dict,
    method: str,
    metrics: List[str],
    generated_image: Optional[str],
    reference_image: Optional[str],
    run_signature: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the common result envelope shared by success and failure records."""
    context = data_item.get("content", "")
    return {
        "timestamp": datetime.now().isoformat(),
        "data_id": data_item.get("id", "unknown"),
        "method": method,
        "diagram_type": data_item.get("diagram_type", "unknown"),
        "generated_image": generated_image,
        "reference_image": reference_image,
        # Recorded explicitly so the aggregator can tell a genuinely comparative
        # judgement apart from one made without the reference diagram.
        "reference_image_available": reference_image is not None,
        "metrics": metrics,
        "run_signature": run_signature,
        "context_preview": context[:200] + "..." if len(context) > 200 else context,
        "images": {},
        "summary": {},
    }


def write_missing_output_record(
    data_item: Dict,
    method: str,
    metrics: List[str],
    reference_image: Optional[str],
    expected_image_path: Optional[str],
    output_path: Path,
    report_path: Path,
    run_signature: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist an explicit failure record for a sample with no generated image.

    Returning without writing anything (the previous behaviour) made a failed
    sample indistinguishable from a sample that was never part of the run, so
    aggregate means were computed over whichever samples happened to succeed.
    """
    data_id = data_item.get("id", "unknown")
    results = build_result_skeleton(
        data_item,
        method,
        metrics,
        generated_image=None,
        reference_image=reference_image,
        run_signature=run_signature,
    )
    results["status"] = RESULT_STATUS_MISSING_OUTPUT
    results["error"] = (
        f"No generated image found for data_id '{data_id}' using method "
        f"'{method}'. Expected: {expected_image_path}"
    )
    results["expected_image_path"] = expected_image_path

    save_results(results, str(output_path))
    create_evaluation_report(results, str(report_path))


def evaluate_single_data_item(
    data_item: Dict,
    evaluator: MetricScorer,
    metrics: List[str],
    method: str,
    item_index: int = None,
    total_items: int = None,
    regeneration: bool = False,
    exp_id: str = None,
    run_signature: Optional[Dict[str, Any]] = None,
    judge_runs: int = 1,
) -> bool:
    """
    Evaluate a single data item using method-based path resolution.

    Args:
        data_item: Data item dictionary
        evaluator: MetricScorer instance
        metrics: List of metrics to evaluate
        method: Method name
        item_index: Current item index (for logging)
        total_items: Total number of items (for logging)
        regeneration: Whether to regenerate evaluation even if a reusable result exists
        exp_id: Optional experiment ID override
        run_signature: Judge/prompt provenance recorded with the result and used
            to decide whether a stored result may be reused
        judge_runs: Number of independent judge evaluations per (sample,
            metric); the scorer aggregates them into a median score

    Returns:
        bool: Whether the data item ends up with a usable evaluation result
    """

    data_id = data_item.get("id", "unknown")
    context = data_item.get("content", "")
    diagram_type = data_item.get("diagram_type", "unknown")

    progress_prefix = f"[{item_index}/{total_items}] " if item_index and total_items else ""

    # Resolve paths using method
    reference_image = resolve_reference_image_path(data_id)
    try:
        generated_image = find_generated_image_by_method(method, data_id, exp_id=exp_id)
        expected_image_path, output_dir, _ = parse_method_paths(
            method, data_id, exp_id=exp_id
        )
    except AmbiguousSubmodelError as exc:
        print(f"\n{progress_prefix}{'!'*80}")
        print(f"! Cannot resolve outputs for data_id '{data_id}' with method '{method}'")
        print(f"! {exc}")
        print(f"{'!'*80}\n")
        logger.error("Ambiguous sub-model for %s: %s", data_id, exc)
        return False

    # NOTE: the output directory is intentionally *not* created here. Creating it
    # before the generated-image check left behind empty directories that hid
    # failures from the aggregator.
    report_filename = f"{data_id}_report.txt"
    report_path = output_dir / report_filename
    output_filename = f"{data_id}.json"
    output_path = output_dir / output_filename

    if not regeneration:
        state, detail = classify_existing_result(output_path, metrics, run_signature)
        if state == "reusable":
            print(f"\n{progress_prefix}{'#'*80}")
            print(f"# Skipping Data ID: {data_id} (reusable result already exists)")
            print(f"{'#'*80}")
            print(f"  - Result: {output_path}")
            print(f"  - Use --regeneration to force re-evaluation")
            return True
        if state != "missing":
            print(
                f"\n{progress_prefix}Re-evaluating {data_id}: "
                f"existing result is {state} ({detail})"
            )

    print(f"\n{progress_prefix}{'#'*80}")
    print(f"# Evaluating Data ID: {data_id}")
    print(f"{'#'*80}")
    print(f"  - Method: {method}")
    print(f"  - Diagram type: {diagram_type}")
    print(f"  - Content: {len(context)} chars")
    if judge_runs > 1:
        print(f"  - Judge runs per metric: {judge_runs} (median aggregation)")
    if generated_image:
        print(f"  - Generated image: {generated_image}")
    else:
        print(f"\n{'*'*80}")
        print(f"************* MISSING OUTPUT: No generated image found for data_id '{data_id}' using method '{method}'")
        print(f"************* Expected: {expected_image_path}")
        print(f"************* Writing an explicit missing_output record so this sample")
        print(f"************* is counted instead of silently dropped from the averages.")
        print(f"{'*'*80}\n")
        write_missing_output_record(
            data_item,
            method,
            metrics,
            reference_image=reference_image,
            expected_image_path=str(expected_image_path),
            output_path=output_path,
            report_path=report_path,
            run_signature=run_signature,
        )
        return False

    # Check reference original image
    if reference_image:
        if Path(reference_image).exists():
            print(f"  - Reference image: {reference_image}")
        else:
            print(f"  ⚠️  Warning: Reference image not found: {reference_image}")
            reference_image = None  # Set to None, comparative metrics report N/A
    else:
        print(f"  - Reference image: (not found; comparative metrics report N/A)")

    # Initialize result structure
    results = build_result_skeleton(
        data_item,
        method,
        metrics,
        generated_image=generated_image,
        reference_image=reference_image,
        run_signature=run_signature,
    )

    # Evaluate generated image
    image_name = Path(generated_image).name
    print(f"\n  Evaluating: {image_name}")

    try:
        image_results = evaluator.evaluate_image(
            generated_image,
            context,
            metrics_to_use=metrics,
            reference_image_path=reference_image,
            judge_runs=judge_runs,
        )
        results["images"][image_name] = image_results
    except Exception as e:
        logger.error(f"Failed to evaluate {image_name}: {e}")
        results["images"][image_name] = {"error": str(e)}

    # Generate summary
    results["summary"] = evaluator.generate_summary(results["images"])

    image_results = results["images"].get(image_name, {})
    metric_failed = "error" in image_results or result_has_metric_errors(image_results, metrics)
    results["status"] = RESULT_STATUS_FAILED if metric_failed else RESULT_STATUS_SUCCESS
    if metric_failed:
        results["error"] = "One or more requested metrics failed. See image metric errors for details."

    # Save results
    save_results(results, str(output_path))
    create_evaluation_report(results, str(report_path))

    # Print summary
    print_results_summary(results)

    print(f"\n  Results saved to: {output_path}")
    print(f"  Report saved to: {report_path}")

    if metric_failed:
        print("\n  Evaluation failed for one or more metrics; saved error details for debugging.")
        return False

    return True


def select_items_needing_evaluation(
    data_items: List[Dict],
    method: str,
    metrics: List[str],
    run_signature: Optional[Dict[str, Any]],
    exp_id: Optional[str],
) -> List[Dict]:
    """Return only the data items whose stored result is not reusable."""
    selected: List[Dict] = []
    for item in data_items:
        data_id = item.get("id", "unknown")
        try:
            _, output_dir, _ = parse_method_paths(method, data_id, exp_id=exp_id)
        except ValueError as exc:
            logger.warning("Could not resolve output path for %s: %s", data_id, exc)
            selected.append(item)
            continue
        state, detail = classify_existing_result(
            output_dir / f"{data_id}.json", metrics, run_signature
        )
        if state != "reusable":
            selected.append(item)
            logger.info("Selected %s for re-run (%s: %s)", data_id, state, detail)
    return selected


def main():
    """Main function"""
    args = parse_args()

    # Set log level
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("=" * 80)
    print("DIAGRAM EVALUATION TOOL")
    print("=" * 80)

    # Handle evodiagram_wo_refiner flag
    method = args.method
    if args.evodiagram_wo_refiner:
        if method != "evodiagram":
            print(f"Warning: --evodiagram_wo_refiner flag only works with --method evodiagram, ignoring flag")
        else:
            method = "evodiagram_wo_refiner"
            print("\nUsing evodiagram without refiner (evodiagram_wo_refiner outputs)")

    print(f"\nMethod: {method}")

    # Load input JSON file
    print(f"\nLoading input JSON: {args.input_json}")
    try:
        all_data_items = load_all_data_items(args.input_json)
        print(f"  - Found {len(all_data_items)} data items")

        # Filter by data_id
        data_items = filter_data_items(all_data_items, args.data_id)
        if args.data_id:
            print(f"  - Filtering by data_id: {args.data_id}")

        # Apply start/end range
        if args.start is not None or args.end is not None:
            start_idx = (args.start - 1) if args.start else 0  # Convert to 0-based
            end_idx = args.end if args.end else len(data_items)  # Inclusive end

            # Validate range
            if start_idx < 0:
                raise ValueError(f"Start index must be >= 1, got {args.start}")
            if start_idx >= len(data_items):
                raise ValueError(f"Start index {args.start} exceeds dataset size {len(data_items)}")
            if end_idx > len(data_items):
                logger.warning(f"End index {args.end} exceeds dataset size {len(data_items)}, using {len(data_items)}")
                end_idx = len(data_items)
            if start_idx >= end_idx:
                raise ValueError(f"Start index {args.start} must be < end index {args.end}")

            data_items = data_items[start_idx:end_idx]
            print(f"  - Processing items {start_idx + 1} to {end_idx} ({len(data_items)} items)")

        print(f"  - Will evaluate {len(data_items)} data items")

    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Load configuration before resolving metrics so that
    # settings.yaml `evaluation.default_metrics` is actually honoured.
    try:
        from dotenv import load_dotenv
        from evo_diagram.utils.env_loader import ensure_env_loaded
        from evo_diagram.config.settings import AppSettings
        from evo_diagram.config.model_loader import ModelConfig
        from evo_diagram.core.llm_factory import LLMFactory

        if args.settings:
            AppSettings.init(args.settings)
        if args.model_config:
            ModelConfig.init(args.model_config)

        # Load environment variables for API keys. Model selection comes from YAML roles.
        ensure_env_loaded()
        load_dotenv(Path(PROJECT_ROOT) / ".env-evaluation", override=True)

        settings = AppSettings.get_default()
    except Exception as e:
        print(f"Error loading evaluation configuration: {e}")
        sys.exit(1)

    # Get metrics to evaluate
    try:
        metrics = get_metrics_to_evaluate(args, settings=settings)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"\nMetrics to evaluate ({len(metrics)}): {metrics}")

    # Create scorer
    print("\nInitializing scorer...")
    try:
        eval_role = args.eval_role or settings.evaluation_role
        model_config = ModelConfig.get_default()
        resolved_model = model_config.list_roles().get(eval_role, "unknown")

        # Judge sampling parameters come from models.yaml, never from a hardcoded
        # override. A hardcoded temperature=0.3 silently beat the configured
        # temperature: 0, which made repeated runs over the same images produce
        # different scores.
        try:
            role_params = model_config.get_model_config(eval_role)
        except Exception as exc:  # role missing / provider unresolved
            logger.warning("Could not read model params for role %r: %s", eval_role, exc)
            role_params = {}

        judge_temperature = role_params.get("temperature", 0)
        if args.max_tokens is not None:
            judge_max_tokens = args.max_tokens
        else:
            judge_max_tokens = role_params.get("max_tokens") or DEFAULT_EVAL_MAX_TOKENS

        model = LLMFactory.create_for_role(
            eval_role,
            max_tokens=judge_max_tokens,
        )
        print(f"  Using evaluation role: {eval_role} ({resolved_model})")
        print(f"  Judge temperature: {judge_temperature} (from model config)")
        print(f"  Judge max_tokens: {judge_max_tokens}")
        judge_runs = int(args.judge_runs)
        if judge_runs > 1:
            print(
                f"  Judge runs per (sample, metric): {judge_runs} "
                f"(median aggregation)"
            )
        evaluator = MetricScorer(model, metrics_to_use=metrics)
    except Exception as e:
        print(f"Error initializing scorer: {e}")
        sys.exit(1)

    # Provenance recorded with every result and used as part of the skip
    # decision, so that changing the judge model, its temperature, the metric
    # set, the judge-run count, or a prompt invalidates previously stored
    # scores instead of silently mixing them into the same table.
    run_signature = build_run_signature(
        judge_role=eval_role,
        judge_model=resolved_model,
        judge_temperature=judge_temperature,
        judge_max_tokens=judge_max_tokens,
        metrics=metrics,
        judge_runs=judge_runs,
    )
    print(f"  Run signature: {json.dumps(run_signature, sort_keys=True)}")

    if args.rerun_failed:
        before = len(data_items)
        data_items = select_items_needing_evaluation(
            data_items, method, metrics, run_signature, args.exp_id
        )
        print(
            f"\n--rerun-failed: {len(data_items)} of {before} data items need "
            f"re-evaluation (reusable results are left untouched)"
        )
        if not data_items:
            print("Nothing to re-run. Exiting.")
            return

    # Evaluate each data item
    print(f"\n{'='*80}")
    print(f"Starting evaluation of {len(data_items)} data items...")
    if args.workers > 1:
        print(f"Using {args.workers} concurrent workers")
    print(f"{'='*80}")

    successful_count = 0
    unsuccessful_count = 0

    if args.workers > 1:
        # Concurrent evaluation
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            # Submit all tasks
            future_to_item = {}
            for i, data_item in enumerate(data_items, 1):
                future = executor.submit(
                    evaluate_single_data_item,
                    data_item=data_item,
                    evaluator=evaluator,
                    metrics=metrics,
                    method=method,
                    item_index=i,
                    total_items=len(data_items),
                    regeneration=args.regeneration,
                    exp_id=args.exp_id,
                    run_signature=run_signature,
                    judge_runs=judge_runs,
                )
                future_to_item[future] = (i, data_item)

            # Process results as they complete
            for future in as_completed(future_to_item):
                i, data_item = future_to_item[future]
                try:
                    success = future.result()
                    if success:
                        successful_count += 1
                    else:
                        unsuccessful_count += 1
                except Exception as e:
                    data_id = data_item.get("id", "unknown")
                    logger.error(f"Error evaluating {data_id}: {e}")
                    unsuccessful_count += 1
    else:
        # Sequential evaluation
        for i, data_item in enumerate(data_items, 1):
            success = evaluate_single_data_item(
                data_item=data_item,
                evaluator=evaluator,
                metrics=metrics,
                method=method,
                item_index=i,
                total_items=len(data_items),
                regeneration=args.regeneration,
                exp_id=args.exp_id,
                run_signature=run_signature,
                judge_runs=judge_runs,
            )
            if success:
                successful_count += 1
            else:
                unsuccessful_count += 1

    print(f"\n{'='*80}")
    if unsuccessful_count:
        print("Evaluation completed with failures.")
    else:
        print("Evaluation completed successfully.")
    print(f"   Method: {method}")
    print(f"   Total data items: {len(data_items)}")
    print(f"   Successfully evaluated: {successful_count}")
    if unsuccessful_count > 0:
        print(f"   ⚠️  Skipped or failed: {unsuccessful_count}")
    print(f"{'='*80}")
    if unsuccessful_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
