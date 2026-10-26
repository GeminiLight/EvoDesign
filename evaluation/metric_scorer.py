"""
Metric Scorer

Agent for scoring diagram quality using multiple evaluation metrics.
Inherits from BaseAgent and manages metric-based evaluation.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from evo_diagram.core.base_agent import BaseAgent
from langchain_core.language_models import BaseChatModel

from evaluation.analysis import stats
from evaluation.metrics import METRIC_CLASSES, MetricResult
from evaluation.prompts.metric_prompts_merged import METRIC_METADATA
from evaluation.utils import (
    METRIC_STATUS_ERROR,
    METRIC_STATUS_NOT_APPLICABLE,
    METRIC_STATUS_SCORED,
    SCORE_MAX,
    SCORE_MIN,
    encode_image_to_base64,
    get_image_mime_type,
    is_valid_score,
    load_context,
)

logger = logging.getLogger(__name__)

# Dimension grouping
DIMENSION_METRICS = {
    "content": ["content_dimension"],
    "visual": ["visual_dimension"],
    "cognitive": ["cognitive_dimension", "judge_preference"],
}

# Human-utility weighting for generated diagrams. Content fidelity matters, but
# a diagram that is visually ugly or cognitively harder than text should not win
# by exhaustive coverage alone.
AVERAGE_SCORE_WEIGHTS = {
    "content_dimension": 0.25,
    "visual_dimension": 0.35,
    "cognitive_dimension": 0.40,
}

# Legacy mapping for backward compatibility
LEGACY_TO_DIMENSION = {
    # Content
    "content_fidelity": "content_dimension",
    "concept_logic": "content_dimension",
    "semantic_relevance": "content_dimension",
    # Visual
    "visual_aesthetics": "visual_dimension",
    "styling_consistency": "visual_dimension",
    "flow_coherence": "visual_dimension",
    "space_balance": "visual_dimension",
    # Cognitive
    "cognitive_ease": "cognitive_dimension",
    "comprehension_accuracy": "cognitive_dimension",
    "self_contained_explanation": "cognitive_dimension",
    "judge_preference": "judge_preference",
}


def aggregate_judge_runs(
    metric_name: str,
    run_results: List[MetricResult],
) -> Dict[str, Any]:
    """Aggregate k independent judge evaluations of one (sample, metric) pair.

    The judge endpoint enforces ``temperature=1``, so a single evaluation
    carries sampling noise. When ``--judge-runs k`` (k > 1) requests repeated
    evaluations, the final score is the **median** of the valid run scores:
    more robust than the mean and, unlike it, preserving the integer 1-5
    rubric semantics.

    Aggregation rules (also documented in evaluation/README.md):

    * A run is *valid* when it is ``scored``, carries no error, and its score
      lies inside the 1-5 rubric. Error and N/A runs never contribute a value.
    * The median takes the **lower** of the two central values when the number
      of valid runs is even (``median_low``), so the aggregated score is
      always an integer.
    * When fewer than ``ceil(k/2)`` runs are valid, the whole (sample, metric)
      is recorded as an ``error`` instead of aggregating a thin minority.
    * Exception: when *every* run reported ``not_applicable`` (a permanent
      condition such as judge_preference without a reference image, not
      sampling noise), the aggregate stays ``not_applicable``.
    * ``reason`` / ``sub_scores`` / ``details`` are taken from the first valid
      run whose score equals the median, so the stored explanation is genuine
      judge output consistent with the reported score.
    * The raw per-run values plus mean / std / median are stored under a
      ``judge_runs`` field so the aggregator can report judge retest variance.
    """
    k = len(run_results)
    required = (k + 1) // 2  # ceil(k/2): minimum number of valid runs

    valid_results: List[MetricResult] = []
    na_results: List[MetricResult] = []
    errors: List[str] = []
    for index, result in enumerate(run_results, start=1):
        if result.status == METRIC_STATUS_NOT_APPLICABLE and not result.error:
            na_results.append(result)
        elif (
            result.status == METRIC_STATUS_SCORED
            and not result.error
            and is_valid_score(result.score)
        ):
            valid_results.append(result)
        else:
            errors.append(
                result.error
                or (
                    f"run {index} produced no valid score "
                    f"(status={result.status!r}, score={result.score!r})"
                )
            )

    values = [result.score for result in valid_results]
    mean_value = stats.mean(values)
    std_value = stats.stdev(values)
    judge_runs_payload: Dict[str, Any] = {
        "k": k,
        "n_valid": len(values),
        "n_not_applicable": len(na_results),
        "n_error": len(errors),
        "values": values,
        "errors": errors,
        "mean": None if mean_value is None else round(mean_value, 4),
        "std": None if std_value is None else round(std_value, 4),
        "median": None,
    }

    if len(values) >= required:
        ordered = sorted(values)
        # Lower median: identical to the median for an odd number of valid
        # runs, and integer-preserving (conservative) for an even one.
        median_score = ordered[(len(ordered) - 1) // 2]
        judge_runs_payload["median"] = median_score

        representative = next(
            result for result in valid_results if result.score == median_score
        )
        payload = representative.to_dict()
        payload["score"] = median_score
        payload["status"] = METRIC_STATUS_SCORED
        payload["error"] = None
        payload["judge_runs"] = judge_runs_payload
        return payload

    if not values and len(na_results) == k:
        # Every run reported N/A: a permanent condition, not a failure.
        payload = na_results[-1].to_dict()
        payload["judge_runs"] = judge_runs_payload
        return payload

    error_detail = f" Run errors: {errors}" if errors else ""
    return {
        "metric": metric_name,
        "score": None,
        "sub_scores": {},
        "reason": "",
        "details": {},
        "error": (
            f"Only {len(values)}/{k} judge runs produced a valid score "
            f"(minimum {required} of {k} required).{error_detail}"
        ),
        "status": METRIC_STATUS_ERROR,
        "judge_runs": judge_runs_payload,
    }


class MetricScorer(BaseAgent):
    """
    Metric Scorer - Agent for evaluating diagram quality across multiple metrics.

    This class inherits from BaseAgent and provides evaluation-specific functionality
    for assessing diagram quality across multiple dimensions (content, visual, cognitive).

    Attributes:
        metrics_to_use: List of metrics to evaluate
        metrics: Dictionary of initialized metric instances
    """

    def __init__(
        self,
        model: BaseChatModel,
        system_prompt: Optional[str] = None,
        task_prompt: Optional[str] = None,
        metrics_to_use: Optional[List[str]] = None,
        **kwargs
    ):
        """Initialize the MetricScorer.

        Args:
            model: Pre-configured LLM model (required).
            system_prompt: Optional custom system prompt.
            task_prompt: Optional custom task prompt.
            metrics_to_use: List of metrics to evaluate, if None uses all metrics.
            **kwargs: Additional arguments passed to BaseAgent
        """

        # Default system prompt for metric scoring
        if system_prompt is None:
            system_prompt = """You are a professional diagram evaluation expert with extensive experience in information visualization and design assessment. Your task is to rigorously evaluate diagram quality across multiple dimensions including content fidelity, visual aesthetics, and cognitive effectiveness. Provide detailed, objective assessments with clear justifications for your scores."""

        # Initialize base agent
        super().__init__(
            model,
            system_prompt,
            task_prompt,
            exclude_think=True,
            jsonalize_output=True,
            **kwargs
        )

        # Determine metrics to use
        if metrics_to_use is None:
            self.metrics_to_use = list(METRIC_CLASSES.keys())
        else:
            self.metrics_to_use = self._normalize_metrics(metrics_to_use)

        # Initialize metric instances
        self.metrics = {}
        for metric_name in self.metrics_to_use:
            if metric_name in METRIC_CLASSES:
                metric_class = METRIC_CLASSES[metric_name]
                self.metrics[metric_name] = metric_class(model)
            else:
                logger.warning(f"Unknown metric: {metric_name}")
        logger.info(f"MetricScorer initialized with {len(self.metrics)} metrics")

    def run(self, state):  # noqa: D401
        # MetricScorer is invoked through `score_diagram`/`score_metric`,
        # not the BaseAgent.run lifecycle. This stub satisfies the abstract
        # method on BaseAgent so the class is instantiable.
        return state

    def evaluate_image(
        self,
        image_path: str,
        context_text: str = "",
        metrics_to_use: Optional[List[str]] = None,
        reference_image_path: Optional[str] = None,
        judge_runs: int = 1,
    ) -> Dict[str, Any]:
        """
        Evaluate a single image using all configured metrics.

        Args:
            image_path: Path to the image file to evaluate
            context_text: Source text content for context (optional)
            reference_image_path: Path to reference/original image (optional)
            judge_runs: Number of independent judge evaluations per metric
                (default 1 = single run, identical to the historical
                behaviour). With k > 1 each (sample, metric) pair is evaluated
                k times and the scores are aggregated by
                :func:`aggregate_judge_runs` (median of the valid runs).

        Returns:
            Dictionary containing evaluation results organized by dimension
        """
        # Encode image
        image_base64 = encode_image_to_base64(image_path)
        image_mime_type = get_image_mime_type(image_path)

        # Handle reference image
        ref_img_base64 = None
        ref_img_mime = None

        if reference_image_path:
            try:
                ref_img_base64 = encode_image_to_base64(reference_image_path)
                ref_img_mime = get_image_mime_type(reference_image_path)
                logger.info(f"Loaded reference image: {reference_image_path}")
            except Exception as e:
                logger.warning(f"Failed to load reference image {reference_image_path}: {e}")

        # Organize results by dimension
        results = {
            "image": image_path,
            "timestamp": datetime.now().isoformat(),
            "dimensions": {
                "content": {},
                "visual": {},
                "cognitive": {},
            },
            "scores": {},
            "metric_status": {},
            "average_score": 0,
        }

        active_metrics = self.metrics_to_use
        if metrics_to_use is not None:
            active_metrics = self._normalize_metrics(metrics_to_use)

        # Ensure metrics are initialized
        for metric_name in active_metrics:
            if metric_name not in self.metrics and metric_name in METRIC_CLASSES:
                self.metrics[metric_name] = METRIC_CLASSES[metric_name](self.model)

        # Execute evaluation for each metric
        runs_per_metric = max(1, int(judge_runs))
        for metric_name in active_metrics:
            if metric_name not in self.metrics:
                logger.warning(f"Metric not initialized: {metric_name}")
                continue

            metric = self.metrics[metric_name]
            logger.info(f"Evaluating {metric_name}...")

            # k independent judge runs, executed serially. Each run captures
            # its own exception so one transient failure does not abort the
            # remaining runs; with k=1 this is the historical single-call path.
            run_results: List[MetricResult] = []
            for run_index in range(runs_per_metric):
                if runs_per_metric > 1:
                    logger.info(
                        f"  {metric_name}: judge run "
                        f"{run_index + 1}/{runs_per_metric}"
                    )
                try:
                    # Special handling for judge_preference which needs reference image
                    if metric_name == "judge_preference":
                        result = metric.evaluate(
                            image_base64=image_base64,
                            image_mime_type=image_mime_type,
                            context_text=context_text,
                            reference_image_base64=ref_img_base64,
                            reference_image_mime_type=ref_img_mime,
                        )
                    else:
                        result = metric.evaluate(
                            image_base64=image_base64,
                            image_mime_type=image_mime_type,
                            context_text=context_text,
                        )
                except Exception as e:
                    logger.error(f"Error evaluating {metric_name}: {e}")
                    result = MetricResult.error_result(metric_name, str(e))
                run_results.append(result)

            if runs_per_metric > 1:
                result_dict = aggregate_judge_runs(metric_name, run_results)
            else:
                result_dict = self._finalize_single_run(run_results[0])

            # Get dimension from metadata
            dimension = METRIC_METADATA.get(metric_name, {}).get("dimension", "other")

            status = result_dict.get("status", METRIC_STATUS_SCORED)
            score = result_dict.get("score")

            results["dimensions"][dimension][metric_name] = result_dict
            results["scores"][metric_name] = score
            results["metric_status"][metric_name] = status

            if status == METRIC_STATUS_SCORED:
                if runs_per_metric > 1:
                    logger.info(
                        f"  {metric_name}: {score}/{SCORE_MAX} "
                        f"(median of {result_dict.get('judge_runs', {}).get('values')})"
                    )
                else:
                    logger.info(f"  {metric_name}: {score}/{SCORE_MAX}")
            elif status == METRIC_STATUS_NOT_APPLICABLE:
                logger.info(
                    f"  {metric_name}: N/A ({result_dict.get('na_reason')})"
                )
            else:
                logger.warning(
                    f"  {metric_name}: failed ({result_dict.get('error')})"
                )

        # Calculate a human-utility weighted score. This prevents content
        # coverage from masking poor visual design or high cognitive load.
        # Only in-rubric scores participate; failed and not-applicable metrics
        # are excluded rather than folded in as a 0.
        weighted_sum = 0.0
        total_weight = 0.0
        fallback_scores = []
        for metric_name, score in results["scores"].items():
            if not is_valid_score(score):
                continue
            fallback_scores.append(score)
            weight = AVERAGE_SCORE_WEIGHTS.get(metric_name)
            if weight is None:
                continue
            weighted_sum += score * weight
            total_weight += weight

        if total_weight:
            results["average_score"] = weighted_sum / total_weight
        elif fallback_scores:
            results["average_score"] = sum(fallback_scores) / len(fallback_scores)
        else:
            results["average_score"] = None

        return results

    @staticmethod
    def _finalize_single_run(result: MetricResult) -> Dict[str, Any]:
        """Validate a single judge run exactly like the historical k=1 path.

        A metric that claims to be scored but returned a value outside the
        1-5 rubric is a failure, not a low score. Reject it here so that the
        scorer and every downstream aggregator agree.
        """
        result_dict = result.to_dict()
        status = result_dict.get("status", METRIC_STATUS_SCORED)
        score = result_dict.get("score")

        if (
            status == METRIC_STATUS_SCORED
            and not result_dict.get("error")
            and not is_valid_score(score)
        ):
            result_dict["error"] = (
                f"Score {score!r} is outside the valid "
                f"{SCORE_MIN}-{SCORE_MAX} rubric"
            )
            result_dict["status"] = METRIC_STATUS_ERROR
        elif result_dict.get("error") and status == METRIC_STATUS_SCORED:
            result_dict["status"] = METRIC_STATUS_ERROR
        return result_dict

    def evaluate_single_metric(
        self,
        image_path: str,
        context_text: str,
        metric_name: str,
        reference_image_path: Optional[str] = None,
    ):
        """
        Evaluate an image using a single metric.

        Args:
            image_path: Path to the image file
            context_text: Source text content
            metric_name: Name of the metric to use
            reference_image_path: Path to reference image

        Returns:
            MetricResult object
        """
        target_metric = metric_name
        if metric_name not in self.metrics and metric_name in LEGACY_TO_DIMENSION:
            target_metric = LEGACY_TO_DIMENSION[metric_name]
            logger.info(f"Mapping legacy request '{metric_name}' to '{target_metric}'")

        if target_metric not in self.metrics:
            if target_metric in METRIC_CLASSES:
                self.metrics[target_metric] = METRIC_CLASSES[target_metric](self.model)
            else:
                raise ValueError(f"Metric not initialized: {target_metric}")

        # Encode image
        image_base64 = encode_image_to_base64(image_path)
        image_mime_type = get_image_mime_type(image_path)

        # Handle reference image
        ref_img_base64 = None
        ref_img_mime = None

        if reference_image_path:
            ref_img_base64 = encode_image_to_base64(reference_image_path)
            ref_img_mime = get_image_mime_type(reference_image_path)

        # Execute evaluation
        metric = self.metrics[target_metric]

        if target_metric == "judge_preference":
            return metric.evaluate(
                image_base64=image_base64,
                image_mime_type=image_mime_type,
                context_text=context_text,
                reference_image_base64=ref_img_base64,
                reference_image_mime_type=ref_img_mime,
            )

        return metric.evaluate(
            image_base64=image_base64,
            image_mime_type=image_mime_type,
            context_text=context_text,
        )

    def _normalize_metrics(self, metrics_to_use: List[str]) -> List[str]:
        mapped: List[str] = []
        seen = set()
        for m in metrics_to_use:
            if m in METRIC_CLASSES:
                target = m
            elif m in LEGACY_TO_DIMENSION:
                target = LEGACY_TO_DIMENSION[m]
                logger.info(f"Mapping legacy metric '{m}' to '{target}'")
            else:
                logger.warning(f"Unknown metric ignored: {m}")
                continue
            if target not in seen:
                mapped.append(target)
                seen.add(target)
        return list(mapped)

    @staticmethod
    def generate_summary(image_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate evaluation summary from multiple image results.

        Args:
            image_results: Dictionary mapping image names to their evaluation results

        Returns:
            Summary dictionary with best/worst images and metric averages
        """
        summary = {
            "total_images": len(image_results),
            "best_image": None,
            "best_score": 0,
            "worst_image": None,
            "worst_score": 5,
            "average_scores": {},
            "metric_averages": {},
        }

        collected: Dict[str, List[float]] = {}
        skipped: Dict[str, List[str]] = {}

        # Calculate average score per image
        for image_name, results in image_results.items():
            if "error" in results:
                continue

            avg_score = results.get("average_score")
            summary["average_scores"][image_name] = avg_score

            if isinstance(avg_score, (int, float)):
                if avg_score > summary["best_score"]:
                    summary["best_score"] = avg_score
                    summary["best_image"] = image_name

                if avg_score < summary["worst_score"] and avg_score > 0:
                    summary["worst_score"] = avg_score
                    summary["worst_image"] = image_name

            # Collect scores for each metric. Failed / not-applicable metrics
            # carry no score and are counted separately instead of averaged in.
            for metric_name, score in results.get("scores", {}).items():
                if is_valid_score(score):
                    collected.setdefault(metric_name, []).append(score)
                else:
                    skipped.setdefault(metric_name, []).append(image_name)

        # Calculate average for each metric
        for metric_name, scores in collected.items():
            summary["metric_averages"][metric_name] = sum(scores) / len(scores)

        summary["metric_valid_counts"] = {
            metric_name: len(scores) for metric_name, scores in collected.items()
        }
        if skipped:
            summary["metrics_without_scores"] = {
                metric_name: images for metric_name, images in skipped.items()
            }

        return summary

    def __repr__(self) -> str:
        """String representation of the agent."""
        return f"MetricScorer(metrics={len(self.metrics)})"


if __name__ == "__main__":
    """Test the MetricScorer"""
    import os
    from evo_diagram.utils.env_loader import ensure_env_loaded
    from evo_diagram.core.llm_factory import LLMFactory

    # Load environment variables from project root
    ensure_env_loaded()

    # Create model
    model = LLMFactory.create(
        model=os.getenv("LLM_MODEL_NAME", "qwen3-vl-plus"),
        model_provider=os.getenv("LLM_MODEL_PROVIDER", "openai"),
        base_url=os.getenv("LLM_ENDPOINT_URL", "https://apis.iflow.cn/v1"),
        api_key=os.getenv("LLM_API_KEY"),
        temperature=0,
        max_tokens=8000
    )

    # Initialize scorer
    scorer = MetricScorer(model, metrics_to_use=["visual_dimension"])

    print(f"MetricScorer initialized: {scorer}")
    print(f"Available metrics: {list(METRIC_CLASSES.keys())}")
