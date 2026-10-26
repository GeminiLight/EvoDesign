import json

from evaluation import path_resolver


def test_mermaid_dataset_outputs_are_grouped_by_sample_id(monkeypatch, tmp_path):
    from baselines.programmic.mermaid import main as mermaid_main

    dataset_path = tmp_path / "data.json"
    dataset_path.write_text(
        json.dumps([{"id": "sample_a", "content": "A to B", "query": "Draw flow"}]),
        encoding="utf-8",
    )

    class FakeAgent:
        def invoke(self, _payload):
            return "graph TD\n  A --> B"

    class FakeRenderer:
        def render(self, _diagram_code, output_path):
            with open(output_path, "wb") as f:
                f.write(b"png")

    monkeypatch.setattr("baselines.programmic.kroki_render.KrokiRender", lambda output_format="png": FakeRenderer())

    output_dir = tmp_path / "out"
    mermaid_main.process_dataset(FakeAgent(), str(dataset_path), str(output_dir), max_concurrent=1)

    sample_dir = output_dir / "sample_a"
    assert (sample_dir / "input.json").exists()
    assert (sample_dir / "diagram.mmd").read_text(encoding="utf-8").startswith("graph TD")
    assert (sample_dir / "render.png").read_bytes() == b"png"
    assert not (output_dir / "sample_a.mmd").exists()


def test_baseline_path_resolver_prefers_sample_directory_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    image_path = (
        tmp_path
        / "experiments"
        / "exp1"
        / "outputs"
        / "baseline"
        / "code_mermaid"
        / "model-x"
        / "sample_a"
        / "render.png"
    )
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")

    resolved, score_dir, reference = path_resolver.parse_method_paths(
        "baselines/code_mermaid/model-x",
        "sample_a",
        exp_id="exp1",
    )

    assert resolved == image_path
    assert score_dir == tmp_path / "experiments" / "exp1" / "scores" / "baseline" / "code_mermaid" / "model-x" / "sample_a"
    assert reference == tmp_path / "dataset" / "images" / "diagrams" / "sample_a.jpg"
