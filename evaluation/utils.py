"""
Diagram Evaluation Utilities

Utility functions module providing image encoding, file loading, and result saving functionality.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence, Tuple
from datetime import datetime

# === Score scale ===
# Every metric prompt defines a 1-5 rubric. Anything outside that interval is a
# parsing or generation failure, never a legitimate low score. Keeping the bound
# in one place stops the scorer and the aggregator from disagreeing about it.
SCORE_MIN = 1
SCORE_MAX = 5

# === Metric-level status vocabulary ===
METRIC_STATUS_SCORED = "scored"
METRIC_STATUS_ERROR = "error"
METRIC_STATUS_NOT_APPLICABLE = "not_applicable"

# === Result-file level status vocabulary ===
RESULT_STATUS_SUCCESS = "success"
RESULT_STATUS_FAILED = "failed"
RESULT_STATUS_MISSING_OUTPUT = "missing_output"

# Version of the run-signature schema. Bump when the comparison rules change so
# that older result files are treated as stale instead of silently reused.
RUN_SIGNATURE_VERSION = 1


def is_valid_score(score: Any) -> bool:
    """Return whether *score* lies inside the documented 1-5 rubric."""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return False
    return SCORE_MIN <= score <= SCORE_MAX


def compute_prompt_versions(metrics: Sequence[str]) -> Dict[str, str]:
    """Return a short content hash of the prompt used by each metric.

    The hash lets a later run detect that a stored score was produced with a
    different prompt revision and therefore must not be mixed into the same
    table.
    """
    from evaluation.prompts.metric_prompts_merged import METRIC_PROMPTS

    versions: Dict[str, str] = {}
    for metric in metrics:
        prompt = METRIC_PROMPTS.get(metric)
        if prompt is None:
            continue
        versions[metric] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    return versions


def build_run_signature(
    judge_role: str,
    judge_model: str,
    judge_temperature: Any,
    judge_max_tokens: Any,
    metrics: Sequence[str],
    judge_runs: int = 1,
) -> Dict[str, Any]:
    """Describe the judge configuration that produced a set of scores.

    ``judge_runs`` is the number of independent judge evaluations per
    (sample, metric). It is part of the signature because an aggregated
    median-of-k score is not comparable with a single-run score: changing k
    must invalidate stored results instead of mixing the two regimes.
    """
    return {
        "signature_version": RUN_SIGNATURE_VERSION,
        "judge_role": judge_role,
        "judge_model": judge_model,
        "judge_temperature": judge_temperature,
        "judge_max_tokens": judge_max_tokens,
        "judge_runs": judge_runs,
        "metrics": sorted(metrics),
        "prompt_versions": compute_prompt_versions(metrics),
    }


def effective_judge_runs(signature: Dict[str, Any]) -> int:
    """Judge-run count of a signature, defaulting pre-resampling files to 1.

    Result files written before judge resampling existed carried exactly one
    judge run per (sample, metric) and no ``judge_runs`` field. Treating a
    missing value as the default k=1 keeps those files reusable for default
    runs while any k change still forces a re-run.
    """
    value = signature.get("judge_runs")
    return 1 if value is None else value


def run_signature_matches(
    stored: Optional[Dict[str, Any]],
    expected: Optional[Dict[str, Any]],
    metrics: Sequence[str],
) -> Tuple[bool, str]:
    """Compare a stored run signature against the current one.

    Only the metrics requested by the current run are compared, so re-running a
    subset of metrics can still reuse a superset result file. A missing
    ``judge_runs`` on either side counts as the default k=1 (see
    :func:`effective_judge_runs`). Returns ``(matches, reason)`` where *reason*
    explains the first mismatch found.
    """
    if expected is None:
        return True, ""
    if not isinstance(stored, dict):
        return False, "result file has no run_signature (judge/prompt provenance unknown)"

    if stored.get("signature_version") != expected.get("signature_version"):
        return False, (
            f"run signature version changed "
            f"({stored.get('signature_version')} -> {expected.get('signature_version')})"
        )

    for key in ("judge_model", "judge_role", "judge_temperature"):
        if stored.get(key) != expected.get(key):
            return False, f"{key} changed ({stored.get(key)!r} -> {expected.get(key)!r})"

    stored_runs = effective_judge_runs(stored)
    expected_runs = effective_judge_runs(expected)
    if stored_runs != expected_runs:
        return False, (
            f"judge_runs changed ({stored_runs!r} -> {expected_runs!r})"
        )

    stored_metrics = set(stored.get("metrics") or [])
    missing = [m for m in metrics if m not in stored_metrics]
    if missing:
        return False, f"stored result does not cover requested metrics: {sorted(missing)}"

    stored_prompts = stored.get("prompt_versions") or {}
    expected_prompts = expected.get("prompt_versions") or {}
    for metric in metrics:
        if stored_prompts.get(metric) != expected_prompts.get(metric):
            return False, (
                f"prompt version for {metric} changed "
                f"({stored_prompts.get(metric)!r} -> {expected_prompts.get(metric)!r})"
            )

    return True, ""


def encode_image_to_base64(image_path: str) -> str:
    """
    Encode image file to base64 string

    Args:
        image_path: Image file path

    Returns:
        Base64 encoded string

    Raises:
        FileNotFoundError: If image file does not exist
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    with open(path, "rb") as image_file:
        return base64.standard_b64encode(image_file.read()).decode("utf-8")


def get_image_mime_type(image_path: str) -> str:
    """
    Get MIME type based on file extension

    Args:
        image_path: Image file path

    Returns:
        MIME type string
    """
    ext = Path(image_path).suffix.lower()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_types.get(ext, "image/png")


def load_context(file_path: str) -> str:
    """
    Load text content from file

    Args:
        file_path: Text file path

    Returns:
        Text content
    """
    path = Path(file_path)
    if not path.exists():
        return ""

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error loading context from {file_path}: {e}")
        return ""


def save_results(results: Dict[str, Any], output_path: str) -> None:
    """
    Save evaluation results to JSON file

    Args:
        results: Evaluation results dictionary
        output_path: Output file path
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Results saved to: {output_path}")


def load_results(results_path: str) -> Dict[str, Any]:
    """
    Load evaluation results

    Args:
        results_path: Result file path

    Returns:
        Evaluation results dictionary
    """
    try:
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Results file not found: {results_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {results_path}: {e}")
    except Exception as e:
        raise IOError(f"Failed to read {results_path}: {e}")


def create_evaluation_report(
    results: Dict[str, Any],
    output_path: Optional[str] = None
) -> str:
    """
    Generate human-readable evaluation report

    Args:
        results: Evaluation results dictionary
        output_path: Optional output file path

    Returns:
        Report content string
    """
    lines = []
    lines.append("=" * 80)
    lines.append("DIAGRAM EVALUATION REPORT")
    lines.append("=" * 80)
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if results.get("data_id"):
        lines.append(f"Data ID: {results.get('data_id')}")
    if results.get("method"):
        lines.append(f"Method: {results.get('method')}")
    if results.get("status"):
        lines.append(f"Status: {results.get('status')}")
    if results.get("error"):
        lines.append(f"Error: {results.get('error')}")
    if "reference_image_available" in results:
        lines.append(f"Reference image available: {results.get('reference_image_available')}")
    lines.append("")

    if not results.get("images"):
        lines.append("-" * 80)
        lines.append("No image was evaluated for this data item.")
        lines.append("-" * 80)

    for image_name, image_results in results.get("images", {}).items():
        lines.append("-" * 80)
        lines.append(f"Image: {image_name}")
        lines.append("-" * 80)

        for dimension, metrics in image_results.get("dimensions", {}).items():
            lines.append(f"\n  [{dimension.upper()}]")

            for metric_name, metric_result in metrics.items():
                score = metric_result.get("score")
                status = metric_result.get("status", METRIC_STATUS_SCORED)
                if status == METRIC_STATUS_NOT_APPLICABLE:
                    na_reason = metric_result.get("na_reason", "not applicable")
                    lines.append(f"    {metric_name}: N/A ({na_reason})")
                elif not is_valid_score(score):
                    error = metric_result.get("error") or "no valid score"
                    lines.append(f"    {metric_name}: N/A (error: {error})")
                else:
                    lines.append(f"    {metric_name}: {score}/5")

                # Add sub-scores
                sub_scores = metric_result.get("sub_scores", {})
                for sub_name, sub_score in sub_scores.items():
                    lines.append(f"      - {sub_name}: {sub_score}/5")

                # Judge resampling provenance (only present when k > 1)
                judge_runs = metric_result.get("judge_runs")
                if isinstance(judge_runs, dict) and (judge_runs.get("k") or 1) > 1:
                    lines.append(
                        f"      Judge runs: k={judge_runs.get('k')} "
                        f"valid={judge_runs.get('n_valid')} "
                        f"values={judge_runs.get('values')} "
                        f"mean={judge_runs.get('mean')} "
                        f"std={judge_runs.get('std')} "
                        f"median={judge_runs.get('median')}"
                    )

                # Add brief reason
                reason = metric_result.get("reason", "")
                if reason:
                    # Truncate overly long reasons
                    short_reason = reason[:100] + "..." if len(reason) > 100 else reason
                    lines.append(f"      Reason: {short_reason}")

        avg_score = image_results.get("average_score")
        if isinstance(avg_score, (int, float)):
            lines.append(f"\n  Average Score: {avg_score:.2f}/5")

    lines.append("")
    lines.append("=" * 80)
    lines.append("END OF REPORT")
    lines.append("=" * 80)

    report = "\n".join(lines)

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"Report saved to: {output_path}")
        except Exception as e:
            raise IOError(f"Failed to write report to {output_path}: {e}")

    return report


def list_image_files(directory: str, extensions: List[str] = None) -> List[str]:
    """
    List image files in directory

    Args:
        directory: Directory path
        extensions: Allowed extension list, defaults to ['.png', '.jpg', '.jpeg']

    Returns:
        Image file path list
    """
    if extensions is None:
        extensions = [".png", ".jpg", ".jpeg", ".gif", ".webp"]

    path = Path(directory)
    image_files = []

    for ext in extensions:
        image_files.extend(path.glob(f"*{ext}"))
        image_files.extend(path.glob(f"*{ext.upper()}"))

    # Sort by filename
    return sorted([str(f) for f in image_files])


if __name__ == "__main__":
    # Simple test
    print("Testing utils module...")

    # Test image encoding
    test_image = "1.png"
    if os.path.exists(test_image):
        encoded = encode_image_to_base64(test_image)
        print(f"✓ Image encoded, length: {len(encoded)}")

    # Test context loading
    test_context = "content.txt"
    if os.path.exists(test_context):
        context = load_context(test_context)
        print(f"✓ Context loaded, length: {len(context)}")

    # Test image listing
    images = list_image_files(".")
    print(f"✓ Found {len(images)} images: {images}")

    print("\nAll tests passed!")
