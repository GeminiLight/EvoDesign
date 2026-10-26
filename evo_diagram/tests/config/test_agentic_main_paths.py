"""Agentic CLI path resolution tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path


def test_default_dataset_path_is_independent_of_cwd(tmp_path, monkeypatch):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.utils.path_manager import DEFAULT_TEST_DATASET

    fixture_path = tmp_path / "provided-dataset.json"
    fixture_path.write_text(json.dumps([{"id": "synthetic-test", "content": "A to B"}]))
    monkeypatch.setattr(main_module, "DEFAULT_TEST_DATASET", fixture_path)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    dataset, resolved_path = main_module.load_dataset(None)

    assert Path(resolved_path) == fixture_path
    assert isinstance(dataset, list)
    assert dataset


def test_non_eval_output_dir_uses_configured_examples_root(tmp_path, monkeypatch):
    from evo_diagram.agentic_system import main as main_module

    examples_dir = tmp_path / "examples"
    monkeypatch.setattr(main_module, "EXAMPLES_DIR", examples_dir)

    output_dir = main_module.get_output_dir(
        item_id="sample_1",
        dataset_path="datasets/train.json",
        model_name="model",
        tag=None,
        variant="evodiagram",
    )

    assert Path(output_dir) == examples_dir / "model" / "sample_1"
    assert (examples_dir / "model" / "sample_1").is_dir()


def test_non_eval_output_dir_separates_models_and_tags(tmp_path, monkeypatch):
    from evo_diagram.agentic_system import main as main_module

    examples_dir = tmp_path / "examples"
    monkeypatch.setattr(main_module, "EXAMPLES_DIR", examples_dir)

    first = main_module.get_output_dir(
        item_id="sample_1",
        dataset_path="datasets/train.json",
        model_name="openai/gpt:5",
        tag="v1",
        variant="evodiagram",
    )
    second = main_module.get_output_dir(
        item_id="sample_1",
        dataset_path="datasets/train.json",
        model_name="anthropic/claude",
        tag="v2",
        variant="evodiagram",
    )

    assert Path(first) == examples_dir / "openai_gpt_5" / "sample_1_v1"
    assert Path(second) == examples_dir / "anthropic_claude" / "sample_1_v2"
    assert first != second


def test_non_eval_output_dir_rejects_unsafe_output_tag(tmp_path, monkeypatch):
    import pytest

    from evo_diagram.agentic_system import main as main_module

    monkeypatch.setattr(main_module, "EXAMPLES_DIR", tmp_path / "examples")

    with pytest.raises(ValueError, match="output tag"):
        main_module.get_output_dir(
            item_id="sample_1",
            dataset_path="datasets/train.json",
            model_name="model",
            tag="../escape",
            variant="evodiagram",
        )


def test_output_dir_does_not_infer_eval_from_substring_dataset_name(tmp_path, monkeypatch):
    from evo_diagram.agentic_system import main as main_module

    examples_dir = tmp_path / "examples"
    monkeypatch.setattr(main_module, "EXAMPLES_DIR", examples_dir)

    output_dir = main_module.get_output_dir(
        item_id="sample_1",
        dataset_path=str(tmp_path / "contest_data.json"),
        model_name="model",
        tag=None,
        variant="evodiagram",
    )

    assert Path(output_dir) == examples_dir / "model" / "sample_1"


def test_output_dir_rejects_unsafe_dataset_item_id(tmp_path, monkeypatch):
    import pytest

    from evo_diagram.agentic_system import main as main_module

    monkeypatch.setattr(main_module, "EXAMPLES_DIR", tmp_path / "examples")

    with pytest.raises(ValueError, match="dataset item id"):
        main_module.get_output_dir(
            item_id="../escape",
            dataset_path="datasets/train.json",
            model_name="model",
            tag=None,
            variant="evodiagram",
        )


def test_eval_output_dir_rejects_unsafe_output_tag(tmp_path, monkeypatch):
    import pytest

    from evo_diagram.agentic_system import main as main_module

    monkeypatch.setattr(main_module, "get_experiment_id", lambda: "exp_test")
    monkeypatch.setattr(
        main_module,
        "get_evodiagram_output_dir",
        lambda variant, model_id, exp_id: tmp_path / variant / model_id / exp_id,
    )

    with pytest.raises(ValueError, match="output tag"):
        main_module.get_output_dir(
            item_id="sample_1",
            dataset_path="dataset/test/data.json",
            model_name="model",
            tag="../escape",
            variant="evodiagram",
        )


def test_eval_output_dir_uses_safe_experiment_tree(tmp_path, monkeypatch):
    from evo_diagram.agentic_system import main as main_module

    monkeypatch.setattr(main_module, "get_experiment_id", lambda: "exp-1")
    monkeypatch.setattr(
        main_module,
        "get_evodiagram_output_dir",
        lambda variant, model_id, exp_id: tmp_path / exp_id / "outputs" / variant / model_id,
    )

    output_dir = main_module.get_output_dir(
        item_id="sample_1",
        dataset_path="dataset/test/data.json",
        model_name="openai/gpt:5",
        tag="ab",
        variant="evodiagram",
    )

    assert Path(output_dir) == (
        tmp_path
        / "exp-1"
        / "outputs"
        / "evodiagram"
        / "openai_gpt_5"
        / "sample_1_ab"
    )
    assert Path(output_dir).is_dir()


def _main_args(**overrides):
    values = {
        "dataset_path": "dataset.json",
        "ids": None,
        "example": 1,
        "start": None,
        "end": None,
        "all": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_determine_items_all_processes_complete_dataset():
    from evo_diagram.agentic_system import main as main_module

    dataset = [{"id": "item-1"}, {"id": "item-2"}]
    args = _main_args(all=True, example=None)

    assert main_module.determine_items(dataset, args) == [(1, dataset[0]), (2, dataset[1])]


def test_validate_config_accepts_all_and_rejects_combined_selection_modes():
    import pytest

    from evo_diagram.agentic_system import main as main_module

    config = SimpleNamespace(learn_from_edit=False)

    main_module.validate_config(config, _main_args(all=True, example=None))

    with pytest.raises(ValueError, match="Cannot combine"):
        main_module.validate_config(config, _main_args(all=True, example=1))

    with pytest.raises(ValueError, match="Cannot combine"):
        main_module.validate_config(config, _main_args(all=True, example=None, start=1, end=2))


def test_main_returns_nonzero_when_single_item_fails(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    args = _main_args()
    config = AgenticSystemConfig(memory_db_path=str(tmp_path / "memory"))

    monkeypatch.setattr(main_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(main_module, "build_config", lambda parsed: config)
    monkeypatch.setattr(main_module, "validate_config", lambda cfg, parsed: None)
    monkeypatch.setattr(main_module, "load_dataset", lambda path: ([{"id": "item-1"}], path))
    monkeypatch.setattr(main_module, "determine_items", lambda dataset, parsed: [(1, dataset[0])])
    monkeypatch.setattr(main_module, "initialize_model", lambda cfg: (object(), "model"))
    monkeypatch.setattr(main_module, "initialize_router_model", lambda: object())
    monkeypatch.setattr(main_module, "get_output_dir", lambda *args, **kwargs: str(tmp_path / "out"))
    monkeypatch.setattr(
        main_module,
        "process_example",
        lambda *args, **kwargs: {
            "example_num": 1,
            "item_id": "item-1",
            "error": "boom",
            "success": False,
        },
    )

    assert main_module.main() == 1


def test_main_returns_zero_when_all_items_succeed(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    args = _main_args(start=1, end=2, example=None)
    config = AgenticSystemConfig(memory_db_path=str(tmp_path / "memory"))
    dataset = [{"id": "item-1"}, {"id": "item-2"}]

    monkeypatch.setattr(main_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(main_module, "build_config", lambda parsed: config)
    monkeypatch.setattr(main_module, "validate_config", lambda cfg, parsed: None)
    monkeypatch.setattr(main_module, "load_dataset", lambda path: (dataset, path))
    monkeypatch.setattr(
        main_module,
        "determine_items",
        lambda loaded_dataset, parsed: list(enumerate(loaded_dataset, start=1)),
    )
    monkeypatch.setattr(main_module, "initialize_model", lambda cfg: (object(), "model"))
    monkeypatch.setattr(main_module, "initialize_router_model", lambda: object())
    monkeypatch.setattr(main_module, "get_output_dir", lambda *args, **kwargs: str(tmp_path / "out"))
    monkeypatch.setattr(
        main_module,
        "process_example",
        lambda example_num, item, *args, **kwargs: {
            "example_num": example_num,
            "item_id": item["id"],
            "success": True,
        },
    )

    assert main_module.main() == 0


def test_main_skips_router_when_selected_items_have_explicit_diagram_type(
    monkeypatch,
    tmp_path,
):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    args = _main_args()
    config = AgenticSystemConfig(memory_db_path=str(tmp_path / "memory"))
    dataset = [{"id": "item-1", "diagram_type": "flowchart"}]
    seen_router_models = []

    monkeypatch.setattr(main_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(main_module, "build_config", lambda parsed: config)
    monkeypatch.setattr(main_module, "validate_config", lambda cfg, parsed: None)
    monkeypatch.setattr(main_module, "load_dataset", lambda path: (dataset, path))
    monkeypatch.setattr(main_module, "determine_items", lambda loaded, parsed: [(1, loaded[0])])
    monkeypatch.setattr(main_module, "initialize_model", lambda cfg: (object(), "model"))
    monkeypatch.setattr(
        main_module,
        "initialize_router_model",
        lambda: (_ for _ in ()).throw(AssertionError("router should not initialize")),
    )
    monkeypatch.setattr(main_module, "get_output_dir", lambda *args, **kwargs: str(tmp_path / "out"))

    def fake_process_example(example_num, item, _model, _config, output_dir, router_model=None):
        seen_router_models.append(router_model)
        return {
            "example_num": example_num,
            "item_id": item["id"],
            "success": True,
        }

    monkeypatch.setattr(main_module, "process_example", fake_process_example)

    assert main_module.main() == 0
    assert seen_router_models == [None]


def test_main_routes_only_items_without_explicit_diagram_type(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    args = _main_args(start=1, end=2, example=None)
    config = AgenticSystemConfig(memory_db_path=str(tmp_path / "memory"))
    dataset = [
        {"id": "typed", "diagram_type": "flowchart"},
        {"id": "auto"},
    ]
    seen_router_models = []

    monkeypatch.setattr(main_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(main_module, "build_config", lambda parsed: config)
    monkeypatch.setattr(main_module, "validate_config", lambda cfg, parsed: None)
    monkeypatch.setattr(main_module, "load_dataset", lambda path: (dataset, path))
    monkeypatch.setattr(
        main_module,
        "determine_items",
        lambda loaded, parsed: list(enumerate(loaded, start=1)),
    )
    monkeypatch.setattr(main_module, "initialize_model", lambda cfg: (object(), "model"))
    monkeypatch.setattr(main_module, "initialize_router_model", lambda: "router-model")
    monkeypatch.setattr(main_module, "get_output_dir", lambda *args, **kwargs: str(tmp_path / "out"))

    def fake_process_example(example_num, item, _model, _config, output_dir, router_model=None):
        seen_router_models.append((item["id"], router_model))
        return {
            "example_num": example_num,
            "item_id": item["id"],
            "success": True,
        }

    monkeypatch.setattr(main_module, "process_example", fake_process_example)

    assert main_module.main() == 0
    assert seen_router_models == [("typed", None), ("auto", "router-model")]


def test_main_records_output_dir_resolution_failure_and_continues(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    args = _main_args(start=1, end=2, example=None)
    config = AgenticSystemConfig(memory_db_path=str(tmp_path / "memory"))
    dataset = [{"id": "../bad"}, {"id": "good"}]
    calls = []

    monkeypatch.setattr(main_module, "EXAMPLES_DIR", tmp_path / "examples")
    monkeypatch.setattr(main_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(main_module, "build_config", lambda parsed: config)
    monkeypatch.setattr(main_module, "validate_config", lambda cfg, parsed: None)
    monkeypatch.setattr(main_module, "load_dataset", lambda path: (dataset, "datasets/train.json"))
    monkeypatch.setattr(
        main_module,
        "determine_items",
        lambda loaded_dataset, parsed: list(enumerate(loaded_dataset, start=1)),
    )
    monkeypatch.setattr(main_module, "initialize_model", lambda cfg: (object(), "model"))
    monkeypatch.setattr(main_module, "initialize_router_model", lambda: object())

    def fake_process_example(example_num, item, _model, _config, output_dir, router_model=None):
        calls.append((example_num, item["id"], output_dir))
        return {
            "example_num": example_num,
            "item_id": item["id"],
            "success": True,
        }

    monkeypatch.setattr(main_module, "process_example", fake_process_example)

    assert main_module.main() == 1
    assert calls == [(2, "good", str(tmp_path / "examples" / "model" / "good"))]

    failure_path = (
        tmp_path / "examples" / "model" / "example_1_invalid_output_path" / "failure.json"
    )
    payload = json.loads(failure_path.read_text(encoding="utf-8"))
    assert payload["item_id"] == "../bad"
    assert payload["error_type"] == "ValueError"
    assert "dataset item id" in payload["error"]


def test_process_example_writes_failure_artifact(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    class FailingWorkflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            raise RuntimeError("generation contract failed")

    output_dir = tmp_path / "out"
    monkeypatch.setattr(main_module, "Text2DiagramWorkflow", FailingWorkflow)

    result = main_module.process_example(
        1,
        {"id": "item-1", "content": "A", "query": "draw"},
        object(),
        AgenticSystemConfig(memory_db_path=str(tmp_path / "memory")),
        str(output_dir),
    )

    failure_path = output_dir / "failure.json"
    payload = json.loads(failure_path.read_text(encoding="utf-8"))

    assert result["success"] is False
    assert result["failure_path"] == str(failure_path)
    assert payload["success"] is False
    assert payload["item_id"] == "item-1"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error"] == "generation contract failed"
    assert any("generation contract failed" in line for line in payload["traceback"])


def test_process_example_marks_verification_quality_failure(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    class FailedVerificationWorkflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            return SimpleNamespace(
                final_png_path=str(tmp_path / "diagram.png"),
                final_manifest_path=str(tmp_path / "diagram.json"),
                verification_quality_passed=False,
                verification_status="reported",
                verification_objective_summary={"critical": 0, "major": 1},
                refiner_degraded=False,
                refiner_status=None,
            )

    output_dir = tmp_path / "out"
    monkeypatch.setattr(main_module, "Text2DiagramWorkflow", FailedVerificationWorkflow)

    result = main_module.process_example(
        1,
        {"id": "item-1", "content": "A", "query": "draw"},
        object(),
        AgenticSystemConfig(memory_db_path=str(tmp_path / "memory")),
        str(output_dir),
    )

    failure_path = output_dir / "failure.json"
    payload = json.loads(failure_path.read_text(encoding="utf-8"))

    assert result["success"] is False
    assert result["error_type"] == "VerificationQualityError"
    assert result["verification_quality_passed"] is False
    assert result["verification_status"] == "reported"
    assert result["verification_objective_summary"] == {"critical": 0, "major": 1}
    assert result["failure_path"] == str(failure_path)
    assert payload["error_type"] == "VerificationQualityError"
    assert "verification did not pass" in payload["error"]
    assert payload["manifest_path"] == str(tmp_path / "diagram.json")
    assert payload["verification_status"] == "reported"
    assert payload["verification_objective_summary"] == {"critical": 0, "major": 1}


def test_process_example_marks_verification_stage_failure_without_quality_flag(
    monkeypatch,
    tmp_path,
):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    class FailedVerificationWorkflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            return SimpleNamespace(
                final_png_path=str(tmp_path / "diagram.png"),
                final_manifest_path=str(tmp_path / "diagram.json"),
                verification_quality_passed=None,
                verification_status="failed",
                verification_cli_exit_code=2,
                verification_errors=["boom"],
                verification_report_path=str(tmp_path / "verification.json"),
                refiner_degraded=False,
                refiner_status=None,
            )

    output_dir = tmp_path / "out"
    monkeypatch.setattr(main_module, "Text2DiagramWorkflow", FailedVerificationWorkflow)

    result = main_module.process_example(
        1,
        {"id": "item-1", "content": "A", "query": "draw"},
        object(),
        AgenticSystemConfig(memory_db_path=str(tmp_path / "memory")),
        str(output_dir),
    )

    payload = json.loads((output_dir / "failure.json").read_text(encoding="utf-8"))

    assert result["success"] is False
    assert result["error_type"] == "VerificationQualityError"
    assert result["verification_status"] == "failed"
    assert result["verification_cli_exit_code"] == 2
    assert result["verification_errors"] == ["boom"]
    assert "verification stage failed" in result["error"]
    assert payload["verification_status"] == "failed"
    assert payload["verification_cli_exit_code"] == 2
    assert payload["verification_errors"] == ["boom"]
    assert payload["verification_report_path"] == str(tmp_path / "verification.json")


def test_process_example_allows_missing_verification_metadata(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    class NoVerificationWorkflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            return SimpleNamespace(
                final_png_path=str(tmp_path / "diagram.png"),
                final_manifest_path=str(tmp_path / "diagram.json"),
                refiner_degraded=False,
                refiner_status=None,
            )

    monkeypatch.setattr(main_module, "Text2DiagramWorkflow", NoVerificationWorkflow)

    result = main_module.process_example(
        1,
        {"id": "item-1", "content": "A", "query": "draw"},
        object(),
        AgenticSystemConfig(memory_db_path=str(tmp_path / "memory")),
        str(tmp_path / "out"),
    )

    assert result["success"] is True
    assert result["verification_quality_passed"] is None
    assert result["verification_status"] is None


def test_process_example_keeps_verification_warnings_nonfatal(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    class WarningVerificationWorkflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            return SimpleNamespace(
                final_png_path=str(tmp_path / "diagram.png"),
                final_manifest_path=str(tmp_path / "diagram.json"),
                verification_quality_passed=True,
                verification_status="reported_with_warnings",
                verification_cli_exit_code=0,
                verification_errors=["subjective critic failed: model unavailable"],
                verification_objective_summary={"critical": 0, "major": 0},
                refiner_degraded=False,
                refiner_status=None,
            )

    output_dir = tmp_path / "out"
    monkeypatch.setattr(main_module, "Text2DiagramWorkflow", WarningVerificationWorkflow)

    result = main_module.process_example(
        1,
        {"id": "item-1", "content": "A", "query": "draw"},
        object(),
        AgenticSystemConfig(memory_db_path=str(tmp_path / "memory")),
        str(output_dir),
    )

    assert result["success"] is True
    assert result["verification_status"] == "reported_with_warnings"
    assert result["verification_errors"] == [
        "subjective critic failed: model unavailable"
    ]
    assert not (output_dir / "failure.json").exists()


def test_process_example_keeps_legacy_warning_status_nonfatal(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    class WarningVerificationWorkflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            return SimpleNamespace(
                final_png_path=str(tmp_path / "diagram.png"),
                final_manifest_path=str(tmp_path / "diagram.json"),
                verification_quality_passed=None,
                verification_status="reported_with_warnings",
                verification_cli_exit_code=0,
                verification_errors=["subjective critic failed: model unavailable"],
                refiner_degraded=False,
                refiner_status=None,
            )

    output_dir = tmp_path / "out"
    monkeypatch.setattr(main_module, "Text2DiagramWorkflow", WarningVerificationWorkflow)

    result = main_module.process_example(
        1,
        {"id": "item-1", "content": "A", "query": "draw"},
        object(),
        AgenticSystemConfig(memory_db_path=str(tmp_path / "memory")),
        str(output_dir),
    )

    assert result["success"] is True
    assert result["verification_quality_passed"] is None
    assert result["verification_status"] == "reported_with_warnings"
    assert result["verification_cli_exit_code"] == 0
    assert not (output_dir / "failure.json").exists()


def test_process_example_success_returns_quality_metadata(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    class PassingWorkflow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            return SimpleNamespace(
                final_png_path=str(tmp_path / "diagram.png"),
                final_manifest_path=str(tmp_path / "diagram.json"),
                verification_quality_passed=True,
                verification_status="reported",
                refiner_degraded=True,
                refiner_status="reported_degraded",
            )

    monkeypatch.setattr(main_module, "Text2DiagramWorkflow", PassingWorkflow)

    result = main_module.process_example(
        1,
        {"id": "item-1", "content": "A", "query": "draw"},
        object(),
        AgenticSystemConfig(memory_db_path=str(tmp_path / "memory")),
        str(tmp_path / "out"),
    )

    assert result["success"] is True
    assert result["verification_quality_passed"] is True
    assert result["verification_status"] == "reported"
    assert result["degraded"] is True
    assert result["refiner_status"] == "reported_degraded"


def test_main_learn_from_edit_returns_zero(monkeypatch, tmp_path):
    from evo_diagram.agentic_system import main as main_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    args = _main_args(example=None)
    config = AgenticSystemConfig(
        learn_from_edit=True,
        task_json="task.json",
        model_manifest="model.json",
        model_image="model.png",
        user_manifest="user.json",
        user_image="user.png",
        memory_db_path=str(tmp_path / "memory"),
    )
    called = []

    monkeypatch.setattr(main_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(main_module, "build_config", lambda parsed: config)
    monkeypatch.setattr(main_module, "validate_config", lambda cfg, parsed: None)
    monkeypatch.setattr(main_module, "learn_from_user_edit", lambda cfg: called.append(cfg))

    assert main_module.main() == 0
    assert called == [config]
