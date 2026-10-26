"""End-to-end contract between the evaluation writer and the aggregator.

A sample without a generated image must reach the aggregator as an explicit
failure, so the reported mean is computed over the full evaluated set instead of
over whichever samples happened to succeed.
"""

from __future__ import annotations

import json

from evaluation import path_resolver, run_evaluation
from evaluation.analysis.analysis_results import EvaluationAnalyzer
from evaluation.metric_scorer import MetricScorer


SIGNATURE = {
    "signature_version": 1,
    "judge_role": "eval",
    "judge_model": "step-3.7-flash",
    "judge_temperature": 0,
    "judge_max_tokens": 8000,
    "metrics": ["content_dimension"],
    "prompt_versions": {"content_dimension": "aaaaaaaaaaaa"},
}


class FakeEvaluator:
    """Returns a MetricScorer-shaped result without calling any model."""

    generate_summary = staticmethod(MetricScorer.generate_summary)

    def __init__(self, score):
        self.score = score

    def evaluate_image(
        self,
        image_path,
        context_text,
        metrics_to_use,
        reference_image_path,
        judge_runs=1,
    ):
        return {
            "image": image_path,
            "dimensions": {
                "content": {
                    "content_dimension": {
                        "metric": "content_dimension",
                        "score": self.score,
                        "sub_scores": {"content_fidelity": self.score},
                        "reason": "",
                        "details": {},
                        "error": None,
                        "status": "scored",
                    }
                },
                "visual": {},
                "cognitive": {},
            },
            "scores": {"content_dimension": self.score},
            "metric_status": {"content_dimension": "scored"},
            "average_score": float(self.score),
        }


def test_failed_sample_is_visible_in_the_aggregate(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

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

    evaluator = FakeEvaluator(score=4)

    assert run_evaluation.evaluate_single_data_item(
        data_item={"id": "s1", "content": "text"},
        evaluator=evaluator,
        metrics=["content_dimension"],
        method="evodiagram/model-a",
        exp_id="exp1",
        run_signature=SIGNATURE,
    ) is True

    # s2 has no generated image at all.
    assert run_evaluation.evaluate_single_data_item(
        data_item={"id": "s2", "content": "text"},
        evaluator=evaluator,
        metrics=["content_dimension"],
        method="evodiagram/model-a",
        exp_id="exp1",
        run_signature=SIGNATURE,
    ) is False

    scores_root = tmp_path / "experiments" / "exp1" / "scores"
    dataset_ids = ["s1", "s2"]

    analyzer = EvaluationAnalyzer(bootstrap_resamples=200)
    result = analyzer.analyze_multiple_methods(
        str(scores_root), dataset_ids=dataset_ids
    )[0]

    counts = result["sample_counts"]
    assert counts["full_set_n"] == 2
    assert counts["success_n"] == 1
    assert counts["missing_output_n"] == 1
    assert counts["missing_rate"] == 0.5
    assert result["missing_output_data_ids"] == ["s2"]

    entry = result["dimension_stats"]["content_dimension"]
    assert entry["valid_n"] == 1
    assert entry["mean"] == 4.0
    assert entry["mean_missing_as_zero"] == 2.0


def test_second_run_reuses_only_a_signature_matching_result(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

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

    def _run(score, signature):
        return run_evaluation.evaluate_single_data_item(
            data_item={"id": "s1", "content": "text"},
            evaluator=FakeEvaluator(score=score),
            metrics=["content_dimension"],
            method="evodiagram/model-a",
            exp_id="exp1",
            run_signature=signature,
        )

    result_path = (
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

    _run(4, SIGNATURE)
    assert json.loads(result_path.read_text())["images"]["rendered_diagram.png"]["scores"] == {
        "content_dimension": 4
    }

    # Same judge: reused, score untouched.
    _run(2, SIGNATURE)
    assert json.loads(result_path.read_text())["images"]["rendered_diagram.png"]["scores"] == {
        "content_dimension": 4
    }

    # Different judge model: re-evaluated instead of silently reusing.
    other_judge = dict(SIGNATURE, judge_model="another-model")
    _run(2, other_judge)
    payload = json.loads(result_path.read_text())
    assert payload["images"]["rendered_diagram.png"]["scores"] == {"content_dimension": 2}
    assert payload["run_signature"]["judge_model"] == "another-model"
