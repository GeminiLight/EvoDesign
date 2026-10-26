from pathlib import Path

import pytest

from baselines.direct_llm.excalidraw_converter import ExcalidrawDirectCodeConverter
from baselines.direct_llm.state import WorkflowState


def test_excalidraw_converter_routes_bound_arrow_without_points():
    scene = ExcalidrawDirectCodeConverter().convert({
        "elements": [
            {"id": "a", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50, "text": "A"},
            {"id": "b", "type": "rectangle", "x": 220, "y": 0, "width": 100, "height": 50, "text": "B"},
            {"id": "edge", "type": "arrow", "startBinding": {"elementId": "a"}, "endBinding": {"elementId": "b"}},
        ],
    })

    arrow = next(elem for elem in scene["elements"] if elem["id"] == "edge")
    assert arrow["x"] == 100
    assert arrow["y"] == 25
    assert arrow["width"] == 120
    assert arrow["height"] == 0
    assert arrow["points"] == [[0, 0], [120, 0]]


def test_excalidraw_converter_keeps_unlabelled_filled_container_behind_nodes():
    scene = ExcalidrawDirectCodeConverter().convert({
        "elements": [
            {"id": "node", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50, "text": "Node"},
            {"id": "layer", "type": "rectangle", "x": -20, "y": -20, "width": 140, "height": 90, "backgroundColor": "#e3f2fd"},
        ],
    })

    ids_by_index = [elem["id"] for elem in scene["elements"]]
    assert ids_by_index.index("layer") < ids_by_index.index("node")


def test_process_file_uses_process_text_and_writes_default_output(monkeypatch, tmp_path):
    from baselines.direct_llm import main as direct_main

    input_path = tmp_path / "sample.txt"
    input_path.write_text("Draw A to B", encoding="utf-8")

    def fake_process_text(text, config, output_path=None, render_image=False, user_query="", save_simplified=False):
        assert text == "Draw A to B"
        assert Path(output_path).parts[-4:] == ("output", "unit-test", "sample", "scene.json")
        state = WorkflowState(text_content=text, config=config)
        state.output = {"ok": True}
        state.status = "completed"
        return state

    monkeypatch.setattr(direct_main, "process_text", fake_process_text)
    state = direct_main.process_file(str(input_path), {"model_alias": "unit-test"})

    assert state.is_completed()


def test_process_dataset_outputs_are_grouped_by_sample_id(monkeypatch, tmp_path):
    from baselines.direct_llm import main as direct_main

    dataset_path = tmp_path / "data.json"
    dataset_path.write_text('[{"id": "sample_a", "content": "Draw A to B", "query": "Flow"}]', encoding="utf-8")

    class FakeWorkflow:
        def __init__(self, config):
            self.config = config

        def run(self, text, query):
            state = WorkflowState(text_content=text, config=self.config)
            state.output = {"query": query, "ok": True}
            state.status = "completed"
            return state

    monkeypatch.setattr(direct_main, "BaselineWorkflow", FakeWorkflow)

    output_root = tmp_path / "out"
    results = direct_main.process_datasets(
        str(dataset_path),
        {"model_alias": "unit-test", "output_dir": str(output_root)},
        max_concurrent=1,
    )

    sample_dir = output_root / "unit-test" / "sample_a"
    assert results["sample_a"]["output"] == str(sample_dir / "scene.json")
    assert (sample_dir / "scene.json").exists()
    assert not (output_root / "unit-test" / "sample_a.json").exists()


def test_resolve_named_model_config_uses_public_model_loader(monkeypatch):
    from baselines.direct_llm import main as direct_main
    from evo_diagram.config.model_loader import ModelConfig

    class FakeModelConfig:
        def list_models(self):
            return ["declared-model"]

        def get_named_model_config(self, model_name):
            assert model_name == "declared-model"
            return {
                "model": "provider-model-name",
                "model_provider": "openai",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-test",
                "temperature": 0.2,
                "max_tokens": 4096,
            }

    monkeypatch.setattr(
        ModelConfig,
        "get_default",
        staticmethod(lambda: FakeModelConfig()),
    )

    assert direct_main._resolve_named_model_config("declared-model") == {
        "model_name": "provider-model-name",
        "model_alias": "declared-model",
        "provider": "openai",
        "base_url": "https://api.example.test/v1",
        "api_key": "sk-test",
        "temperature": 0.2,
        "max_tokens": 4096,
    }


def test_resolve_named_model_config_fails_fast_for_broken_declared_model(monkeypatch):
    from baselines.direct_llm import main as direct_main
    from evo_diagram.config.model_loader import ModelConfig

    class FakeModelConfig:
        def list_models(self):
            return ["broken-model"]

        def get_named_model_config(self, model_name):
            raise ValueError("Provider api_key resolves to an example placeholder")

    monkeypatch.setattr(
        ModelConfig,
        "get_default",
        staticmethod(lambda: FakeModelConfig()),
    )

    with pytest.raises(RuntimeError, match="Failed to resolve model config"):
        direct_main._resolve_named_model_config("broken-model")
