"""Evaluation-artifact writers for the DiagramAgent and SciSketch baselines."""

from __future__ import annotations

import json
import logging
import os

import pytest


# --- 8. Source and destination can be the same file -----------------------

def test_diagramagent_artifacts_survive_an_in_place_output_dir(monkeypatch, tmp_path):
    from baselines.diagramagent import DiagramAgentEvaluator as dae

    out_root = tmp_path / "outputs" / "baseline" / "diagramagent" / "m1"
    monkeypatch.setattr(dae, "get_baseline_output_dir", lambda algo, model, exp_id=None: str(out_root))
    monkeypatch.setattr(dae, "get_experiment_id", lambda: "expX")

    sample_dir = out_root / "s1"
    sample_dir.mkdir(parents=True)
    render = sample_dir / "render.png"
    render.write_bytes(b"png-bytes")

    # The runner passes the very directory this helper resolves to, so the
    # generated PNG and the destination are the same file.
    dae._write_eval_artifacts(
        eval_output_root=str(tmp_path),
        baseline_type="diagramagent",
        model_name="m1",
        data_id="s1",
        query="q",
        content="c",
        generated_png_path=str(render),
        reference_image_path="",
        code_path="",
    )

    assert render.read_bytes() == b"png-bytes"
    assert (sample_dir / "input.json").exists()
    assert (out_root / "mapping.json").exists()


def test_diagramagent_artifacts_still_copy_a_distinct_source(monkeypatch, tmp_path):
    from baselines.diagramagent import DiagramAgentEvaluator as dae

    out_root = tmp_path / "out"
    monkeypatch.setattr(dae, "get_baseline_output_dir", lambda algo, model, exp_id=None: str(out_root))
    monkeypatch.setattr(dae, "get_experiment_id", lambda: "expX")

    source = tmp_path / "elsewhere.png"
    source.write_bytes(b"other")

    dae._write_eval_artifacts(
        eval_output_root=str(tmp_path),
        baseline_type="diagramagent",
        model_name="m1",
        data_id="s2",
        query="q",
        content="c",
        generated_png_path=str(source),
        reference_image_path="",
        code_path="",
    )

    assert (out_root / "s2" / "render.png").read_bytes() == b"other"


# --- 7. SciSketch referenced an undefined _PROJECT_ROOT -------------------

def test_scisketch_project_root_points_at_the_repository():
    from baselines.scisketch.src import custom_main

    assert os.path.isfile(os.path.join(custom_main._PROJECT_ROOT, "pyproject.toml"))
    assert os.path.isdir(os.path.join(custom_main._PROJECT_ROOT, "baselines"))


def test_scisketch_writes_input_and_mapping(monkeypatch, tmp_path):
    from baselines.scisketch.src import custom_main

    out_root = tmp_path / "out"
    monkeypatch.setattr(custom_main, "get_baseline_output_dir", lambda algo, model, exp_id=None: str(out_root))
    monkeypatch.setattr(custom_main, "get_experiment_id", lambda: "expX")

    png = tmp_path / "s1_final.png"
    png.write_bytes(b"png")

    custom_main._write_eval_artifacts(
        data_id="s1",
        query="caption",
        content="paper text",
        generated_png_path=str(png),
        final_diagram_path=str(tmp_path / "s1_final.drawio"),
        baseline_type="scisketch",
        model_name="m1",
        dataset_ref_image_hint="",
    )

    payload = json.loads((out_root / "s1" / "input.json").read_text(encoding="utf-8"))
    assert payload == {"id": "s1", "query": "caption", "content": "paper text"}
    assert (out_root / "mapping.json").exists()
    assert (out_root / "s1" / "render.png").read_bytes() == b"png"


def test_scisketch_reports_artifact_failures_instead_of_swallowing_them(monkeypatch, tmp_path, caplog):
    from baselines.scisketch.src import custom_main

    def boom(**kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(custom_main, "_write_eval_artifacts", boom)
    monkeypatch.setattr(custom_main, "get_candidate_image_list", lambda name: [])
    monkeypatch.setattr(
        custom_main,
        "get_dataset_data",
        lambda *a, **k: [{"paper": "p", "caption": "c", "file": "s1", "ref_image": ""}],
    )

    save_dir = tmp_path / "save"
    sample_dir = save_dir / "s1"
    sample_dir.mkdir(parents=True)
    # Pre-existing outputs so the run takes the "skip regeneration" branch and
    # never calls the LLM.
    (sample_dir / "s1.json").write_text("{}", encoding="utf-8")
    (sample_dir / "s1_final.drawio").write_text("<mxGraphModel/>", encoding="utf-8")
    # This test exercises artifact-write failures, not Docker rendering.
    # A complete cached result keeps it independent of the host's Docker CLI.
    (sample_dir / "s1_final.png").write_bytes(b"png-bytes")

    with caplog.at_level(logging.ERROR, logger=custom_main.__name__):
        summary = custom_main.process_test_data(
            [{"paper": "p", "caption": "c", "file": "s1", "ref_image": ""}],
            {"language": "drawio", "parse_format": "xml", "file_extension": ".drawio"},
            str(save_dir),
            write_eval_artifacts=True,
        )

    assert summary["eval_artifact_failures"] == ["s1"]
    assert "disk on fire" in caplog.text or "eval artifact write failed" in caplog.text
