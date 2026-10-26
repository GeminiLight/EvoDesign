from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evaluation import path_resolver, run_evaluation


SIGNATURE = {
    "signature_version": 1,
    "judge_role": "eval",
    "judge_model": "step-3.7-flash",
    "judge_temperature": 0,
    "judge_max_tokens": 8000,
    "metrics": ["visual_dimension"],
    "prompt_versions": {"visual_dimension": "abc123abc123"},
}


def _write_result(path, **overrides):
    payload = {
        "status": "success",
        "run_signature": SIGNATURE,
        "images": {
            "diagram.png": {
                "dimensions": {
                    "visual": {
                        "visual_dimension": {
                            "score": 4,
                            "reason": "clear",
                            "status": "scored",
                        }
                    }
                }
            }
        },
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


# ── existing-result reuse ────────────────────────────────────────────────────


def test_existing_evaluation_requires_result_json(tmp_path):
    result_path = tmp_path / "sample.json"

    assert run_evaluation.existing_evaluation_succeeded(
        result_path,
        ["visual_dimension"],
    ) is False


def test_existing_evaluation_rejects_metric_errors(tmp_path):
    result_path = tmp_path / "sample.json"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "images": {
                    "diagram.png": {
                        "dimensions": {
                            "visual": {
                                "visual_dimension": {
                                    "score": 0,
                                    "error": "model failed",
                                }
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert run_evaluation.existing_evaluation_succeeded(
        result_path,
        ["visual_dimension"],
    ) is False


def test_existing_evaluation_accepts_complete_metric_results(tmp_path):
    result_path = tmp_path / "sample.json"
    _write_result(result_path)

    assert run_evaluation.existing_evaluation_succeeded(
        result_path,
        ["visual_dimension"],
    ) is True


def test_out_of_rubric_score_without_error_is_not_reusable(tmp_path):
    """A score of 0 is outside the 1-5 rubric even when no error was recorded."""
    result_path = tmp_path / "sample.json"
    _write_result(
        result_path,
        images={
            "diagram.png": {
                "dimensions": {
                    "visual": {
                        "visual_dimension": {"score": 0, "status": "scored"}
                    }
                }
            }
        },
    )

    assert run_evaluation.existing_evaluation_succeeded(
        result_path, ["visual_dimension"]
    ) is False


def test_not_applicable_metric_is_not_an_error():
    image_results = {
        "dimensions": {
            "cognitive": {
                "judge_preference": {
                    "score": None,
                    "error": None,
                    "status": "not_applicable",
                    "na_reason": "reference_image_missing",
                }
            }
        }
    }

    assert run_evaluation.result_has_metric_errors(
        image_results, ["judge_preference"]
    ) is False


def test_empty_metric_list_counts_as_error():
    assert run_evaluation.result_has_metric_errors({"dimensions": {}}, []) is True


@pytest.mark.parametrize(
    ("overrides", "expected_state"),
    [
        ({}, "reusable"),
        ({"status": "missing_output", "images": {}}, "failed"),
        ({"status": "failed"}, "failed"),
        ({"run_signature": None}, "stale"),
        (
            {"run_signature": dict(SIGNATURE, judge_model="other-model")},
            "stale",
        ),
        (
            {
                "run_signature": dict(
                    SIGNATURE, prompt_versions={"visual_dimension": "deadbeef0000"}
                )
            },
            "stale",
        ),
        (
            {"run_signature": dict(SIGNATURE, judge_temperature=0.3)},
            "stale",
        ),
        (
            {"run_signature": dict(SIGNATURE, metrics=["content_dimension"])},
            "stale",
        ),
    ],
)
def test_classify_existing_result_states(tmp_path, overrides, expected_state):
    result_path = tmp_path / "sample.json"
    _write_result(result_path, **overrides)

    state, _detail = run_evaluation.classify_existing_result(
        result_path, ["visual_dimension"], SIGNATURE
    )
    assert state == expected_state


def test_classify_reports_missing_when_no_file(tmp_path):
    state, _ = run_evaluation.classify_existing_result(
        tmp_path / "absent.json", ["visual_dimension"], SIGNATURE
    )
    assert state == "missing"


def test_superset_metric_result_is_reusable_for_a_subset_run(tmp_path):
    """Running one metric may reuse a result produced by a larger metric set."""
    result_path = tmp_path / "sample.json"
    stored_signature = dict(
        SIGNATURE,
        metrics=["content_dimension", "visual_dimension"],
        prompt_versions={
            "content_dimension": "111111111111",
            "visual_dimension": "abc123abc123",
        },
    )
    _write_result(result_path, run_signature=stored_signature)

    state, _ = run_evaluation.classify_existing_result(
        result_path, ["visual_dimension"], SIGNATURE
    )
    assert state == "reusable"


# ── missing generated output (explicit failure record) ───────────────────────


def test_missing_generated_image_writes_missing_output_record(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    success = run_evaluation.evaluate_single_data_item(
        data_item={"id": "sample_1", "content": "some text", "diagram_type": "flow"},
        evaluator=None,
        metrics=["visual_dimension"],
        method="evodiagram",
        exp_id="exp1",
        run_signature=SIGNATURE,
    )

    assert success is False

    output_dir = (
        tmp_path / "experiments" / "exp1" / "scores" / "evodiagram" / "evodiagram" / "sample_1"
    )
    result_path = output_dir / "sample_1.json"
    assert result_path.exists(), "a missing generated image must still be recorded"

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "missing_output"
    assert payload["generated_image"] is None
    assert "No generated image found" in payload["error"]
    assert payload["run_signature"] == SIGNATURE
    assert (output_dir / "sample_1_report.txt").exists()

    # The directory is no longer an empty shell that hides the failure.
    assert sorted(p.name for p in output_dir.iterdir()) == [
        "sample_1.json",
        "sample_1_report.txt",
    ]


def test_ambiguous_submodel_aborts_the_item_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    image = (
        tmp_path
        / "experiments"
        / "exp1"
        / "outputs"
        / "evodiagram"
        / "evodiagram"
        / "model-a"
        / "sample_1"
        / "rendered_diagram.png"
    )
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")

    success = run_evaluation.evaluate_single_data_item(
        data_item={"id": "sample_1", "content": "text"},
        evaluator=None,
        metrics=["visual_dimension"],
        method="evodiagram",
        exp_id="exp1",
        run_signature=SIGNATURE,
    )

    assert success is False
    scores_root = tmp_path / "experiments" / "exp1" / "scores"
    assert not scores_root.exists()


# ── metric resolution ────────────────────────────────────────────────────────


def test_unknown_metric_names_are_rejected():
    args = SimpleNamespace(metrics=["contnet_dimension"])

    with pytest.raises(ValueError) as exc:
        run_evaluation.get_metrics_to_evaluate(args)

    message = str(exc.value)
    assert "contnet_dimension" in message
    assert "content_dimension" in message


def test_metrics_fall_back_to_settings_default():
    args = SimpleNamespace(metrics=None)
    settings = SimpleNamespace(
        evaluation_default_metrics=["content_dimension", "judge_preference"]
    )

    assert run_evaluation.get_metrics_to_evaluate(args, settings=settings) == [
        "content_dimension",
        "judge_preference",
    ]


def test_metrics_fall_back_to_all_metrics_without_settings():
    args = SimpleNamespace(metrics=None)

    assert run_evaluation.get_metrics_to_evaluate(args) == run_evaluation.ALL_METRICS


def test_legacy_metric_aliases_are_mapped():
    args = SimpleNamespace(metrics=["visual_aesthetics", "cognitive_ease"])

    assert run_evaluation.get_metrics_to_evaluate(args) == [
        "visual_dimension",
        "cognitive_dimension",
    ]


def test_empty_settings_metric_list_falls_back_instead_of_producing_nothing():
    args = SimpleNamespace(metrics=None)
    settings = SimpleNamespace(evaluation_default_metrics=[])

    assert run_evaluation.get_metrics_to_evaluate(args, settings=settings) == (
        run_evaluation.ALL_METRICS
    )


# ── --rerun-failed selection ─────────────────────────────────────────────────


def test_select_items_needing_evaluation(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    scores_root = tmp_path / "experiments" / "exp1" / "scores" / "evodiagram" / "evodiagram"

    good = scores_root / "sample_ok"
    good.mkdir(parents=True)
    _write_result(good / "sample_ok.json")

    stale = scores_root / "sample_stale"
    stale.mkdir(parents=True)
    _write_result(stale / "sample_stale.json", run_signature=dict(SIGNATURE, judge_model="old"))

    failed = scores_root / "sample_failed"
    failed.mkdir(parents=True)
    _write_result(failed / "sample_failed.json", status="missing_output", images={})

    items = [
        {"id": "sample_ok"},
        {"id": "sample_stale"},
        {"id": "sample_failed"},
        {"id": "sample_never_run"},
    ]

    selected = run_evaluation.select_items_needing_evaluation(
        items, "evodiagram", ["visual_dimension"], SIGNATURE, "exp1"
    )

    assert [item["id"] for item in selected] == [
        "sample_stale",
        "sample_failed",
        "sample_never_run",
    ]


# ── main() wiring ────────────────────────────────────────────────────────────


def _patch_main_dependencies(monkeypatch, tmp_path, captured, judge_runs=1):
    from evo_diagram.config.model_loader import ModelConfig
    from evo_diagram.config.settings import AppSettings
    from evo_diagram.core.llm_factory import LLMFactory

    monkeypatch.setattr(
        run_evaluation,
        "parse_args",
        lambda: SimpleNamespace(
            verbose=False,
            method="evodiagram",
            evodiagram_wo_refiner=False,
            input_json=str(tmp_path / "data.json"),
            data_id=None,
            start=None,
            end=None,
            workers=1,
            settings=None,
            model_config=None,
            eval_role=None,
            regeneration=False,
            rerun_failed=False,
            max_tokens=None,
            metrics=None,
            exp_id=None,
            judge_runs=judge_runs,
        ),
    )
    monkeypatch.setattr(
        run_evaluation,
        "load_all_data_items",
        lambda _path: [{"id": "sample_1", "content": "A flow"}],
    )
    def _record_item(**kwargs):
        captured["item_kwargs"] = kwargs
        return False

    monkeypatch.setattr(run_evaluation, "evaluate_single_data_item", _record_item)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr("evo_diagram.utils.env_loader.ensure_env_loaded", lambda: None)
    monkeypatch.setattr(
        AppSettings,
        "get_default",
        classmethod(
            lambda cls: SimpleNamespace(
                evaluation_role="eval",
                evaluation_default_metrics=["visual_dimension"],
            )
        ),
    )
    monkeypatch.setattr(
        ModelConfig,
        "get_default",
        classmethod(
            lambda cls: SimpleNamespace(
                list_roles=lambda: {"eval": "fake-model"},
                get_model_config=lambda role, **kw: {"temperature": 0, "timeout": 600},
            )
        ),
    )

    def _create_for_role(cls, *args, **kwargs):
        captured["create_for_role"] = (args, kwargs)
        return object()

    monkeypatch.setattr(LLMFactory, "create_for_role", classmethod(_create_for_role))

    class FakeMetricScorer:
        def __init__(self, model, metrics_to_use):
            self.model = model
            self.metrics_to_use = metrics_to_use

    monkeypatch.setattr(run_evaluation, "MetricScorer", FakeMetricScorer)


def test_main_exits_nonzero_when_any_item_fails(monkeypatch, tmp_path):
    captured = {}
    _patch_main_dependencies(monkeypatch, tmp_path, captured)

    with pytest.raises(SystemExit) as exc:
        run_evaluation.main()

    assert exc.value.code == 1


def test_main_does_not_override_the_configured_judge_temperature(monkeypatch, tmp_path):
    captured = {}
    _patch_main_dependencies(monkeypatch, tmp_path, captured)

    with pytest.raises(SystemExit):
        run_evaluation.main()

    _args, kwargs = captured["create_for_role"]
    assert "temperature" not in kwargs, (
        "the judge temperature must come from models.yaml, not a hardcoded override"
    )
    assert kwargs["max_tokens"] == run_evaluation.DEFAULT_EVAL_MAX_TOKENS


def test_main_passes_a_run_signature_to_each_item(monkeypatch, tmp_path):
    captured = {}
    _patch_main_dependencies(monkeypatch, tmp_path, captured)

    with pytest.raises(SystemExit):
        run_evaluation.main()

    signature = captured["item_kwargs"]["run_signature"]
    assert signature["judge_model"] == "fake-model"
    assert signature["judge_temperature"] == 0
    assert signature["metrics"] == ["visual_dimension"]
    assert signature["prompt_versions"]["visual_dimension"]
    # Default judge resampling: one run per (sample, metric).
    assert signature["judge_runs"] == 1
    assert captured["item_kwargs"]["judge_runs"] == 1


def test_main_records_judge_runs_in_signature_and_item_kwargs(monkeypatch, tmp_path):
    captured = {}
    _patch_main_dependencies(monkeypatch, tmp_path, captured, judge_runs=3)

    with pytest.raises(SystemExit):
        run_evaluation.main()

    assert captured["item_kwargs"]["judge_runs"] == 3
    assert captured["item_kwargs"]["run_signature"]["judge_runs"] == 3


def test_main_uses_settings_default_metrics(monkeypatch, tmp_path):
    captured = {}
    _patch_main_dependencies(monkeypatch, tmp_path, captured)

    with pytest.raises(SystemExit):
        run_evaluation.main()

    assert captured["item_kwargs"]["metrics"] == ["visual_dimension"]


# ── judge / prompt provenance really blocks reuse ────────────────────────────


def test_a_real_prompt_edit_invalidates_stored_results(tmp_path, monkeypatch):
    """The prompt hash is computed from the live prompt text, so editing a prompt
    makes every stored score stale rather than reusable."""
    from evaluation.prompts import metric_prompts_merged
    from evaluation.utils import build_run_signature

    original = build_run_signature(
        judge_role="eval",
        judge_model="judge-x",
        judge_temperature=0,
        judge_max_tokens=8000,
        metrics=["visual_dimension"],
    )

    result_path = tmp_path / "sample.json"
    _write_result(result_path, run_signature=original)

    assert run_evaluation.classify_existing_result(
        result_path, ["visual_dimension"], original
    )[0] == "reusable"

    monkeypatch.setitem(
        metric_prompts_merged.METRIC_PROMPTS,
        "visual_dimension",
        metric_prompts_merged.METRIC_PROMPTS["visual_dimension"] + "\n- extra rule",
    )
    edited = build_run_signature(
        judge_role="eval",
        judge_model="judge-x",
        judge_temperature=0,
        judge_max_tokens=8000,
        metrics=["visual_dimension"],
    )

    assert edited["prompt_versions"] != original["prompt_versions"]
    state, detail = run_evaluation.classify_existing_result(
        result_path, ["visual_dimension"], edited
    )
    assert state == "stale"
    assert "prompt version" in detail


def test_switching_the_judge_model_invalidates_stored_results(tmp_path):
    """Swapping the judge for a third-party model must force a full re-run."""
    result_path = tmp_path / "sample.json"
    _write_result(result_path, run_signature=dict(SIGNATURE, judge_model="step-3.7-flash"))

    new_judge = dict(SIGNATURE, judge_model="third-party-judge")
    state, detail = run_evaluation.classify_existing_result(
        result_path, ["visual_dimension"], new_judge
    )

    assert state == "stale"
    assert "judge_model" in detail


def test_results_written_before_signatures_existed_are_never_reused(tmp_path):
    result_path = tmp_path / "sample.json"
    payload = json.loads(json.dumps({
        "status": "success",
        "images": {
            "diagram.png": {
                "dimensions": {
                    "visual": {"visual_dimension": {"score": 4, "status": "scored"}}
                }
            }
        },
    }))
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    state, detail = run_evaluation.classify_existing_result(
        result_path, ["visual_dimension"], SIGNATURE
    )

    assert state == "stale"
    assert "no run_signature" in detail
