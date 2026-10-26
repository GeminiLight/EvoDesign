from __future__ import annotations

import json

from evo_diagram.scripts import ab_compare_modes


def test_ab_compare_modes_returns_nonzero_when_all_artifacts_missing(tmp_path):
    code = ab_compare_modes.main(
        [
            "--samples-root",
            str(tmp_path),
            "--samples",
            "missing_sample",
            "--json",
        ]
    )

    assert code == 1


def test_ab_compare_modes_returns_nonzero_when_any_required_mode_is_missing(tmp_path):
    sample = tmp_path / "sample"
    render_dir = sample / "4_render"
    render_dir.mkdir(parents=True)
    (render_dir / "rendered_diagram.excalidraw").write_text(
        json.dumps({"elements": []}),
        encoding="utf-8",
    )

    code = ab_compare_modes.main(
        [
            "--samples-root",
            str(tmp_path),
            "--samples",
            "sample",
            "--json",
        ]
    )

    assert code == 1


def test_ab_compare_modes_uses_current_oneshot_manifest_path(tmp_path):
    sample = tmp_path / "sample"
    structure_dir = sample / "1_structure"
    render_dir = sample / "4_render"
    unified_dir = sample / "1_unified"
    structure_dir.mkdir(parents=True)
    render_dir.mkdir(parents=True)
    unified_dir.mkdir(parents=True)
    (structure_dir / "structure_instantiation.json").write_text(
        json.dumps({"edges": [{"id": "e1"}]}),
        encoding="utf-8",
    )
    (render_dir / "rendered_diagram.excalidraw").write_text(
        json.dumps({"elements": [{"id": "n1", "type": "rectangle"}]}),
        encoding="utf-8",
    )
    (unified_dir / "diagram_manifest.json").write_text(
        json.dumps({"elements": [{"id": "n1", "type": "rectangle"}]}),
        encoding="utf-8",
    )

    entry = ab_compare_modes._compare_one_sample(
        "sample",
        multiagent_dir=sample,
        oneshot_dir=sample,
    )
    code = ab_compare_modes.main(
        [
            "--samples-root",
            str(tmp_path),
            "--samples",
            "sample",
            "--json",
        ]
    )

    assert entry["paths"]["oneshot"].endswith("1_unified/diagram_manifest.json")
    assert entry["missing_artifacts"] == []
    assert code == 0


def test_ab_compare_modes_resolves_model_layer_under_current_variant_root(tmp_path):
    variant_root = tmp_path / "experiments" / "exp1" / "outputs" / "evodiagram" / "evodiagram"
    sample = variant_root / "model-x" / "sample"
    (sample / "4_render").mkdir(parents=True)
    (sample / "1_unified").mkdir(parents=True)
    (sample / "4_render" / "rendered_diagram.excalidraw").write_text(
        json.dumps({"elements": []}),
        encoding="utf-8",
    )
    (sample / "1_unified" / "diagram_manifest.json").write_text(
        json.dumps({"elements": []}),
        encoding="utf-8",
    )

    code = ab_compare_modes.main(
        [
            "--samples-root",
            str(variant_root),
            "--model",
            "model-x",
            "--samples",
            "sample",
            "--json",
        ]
    )

    assert code == 0
