from __future__ import annotations

import json
from types import SimpleNamespace

from evo_diagram.scripts import regression_render


def test_regression_render_uses_current_canvas_render_facade(
    tmp_path,
    monkeypatch,
):
    sample_dir = tmp_path / "sample"
    structure_dir = sample_dir / "1_structure"
    layout_dir = sample_dir / "3_layout"
    structure_dir.mkdir(parents=True)
    layout_dir.mkdir(parents=True)

    structure_payload = {
        "specification": {"ignored": True},
        "chart_type": "flowchart",
        "nodes": [{"id": "n_start", "label": "Start"}],
        "edges": [{"id": "e1", "source": "n_start", "target": "n_start"}],
        "groups": [],
    }
    layout_payload = {
        "specification": {"layout_self_audit": {"crossings": True}},
        "n_start": {"type": "rectangle", "x": 0, "y": 0, "w": 100, "h": 50},
        "e1": {
            "start": {"elementId": "n_start", "side": "right"},
            "end": {"elementId": "n_start", "side": "left"},
        },
    }
    (structure_dir / "structure_instantiation.json").write_text(
        json.dumps(structure_payload),
        encoding="utf-8",
    )
    (layout_dir / "layout_instantiation.json").write_text(
        json.dumps(layout_payload),
        encoding="utf-8",
    )

    calls = {}

    def fake_layout_audit(layout, structure):
        calls["layout_audit"] = (layout, structure)
        return ["layout ok"]

    def fake_render_manifest(
        *,
        layout_instantiation,
        structure_instantiation,
        canvas_library,
        output_dir,
    ):
        calls["render_manifest"] = {
            "layout_instantiation": layout_instantiation,
            "structure_instantiation": structure_instantiation,
            "canvas_library": canvas_library,
            "output_dir": output_dir,
        }
        return SimpleNamespace(
            manifest={
                "elements": [
                    {"id": "n_start", "type": "rectangle"},
                    {"id": "txt", "type": "text", "text": "Start"},
                    {"id": "e1", "type": "arrow", "strokeColor": "#e03131"},
                ]
            }
        )

    def fake_manifest_audit(manifest, *, structure_instantiation, canvas_library):
        calls["manifest_audit"] = (manifest, structure_instantiation, canvas_library)
        return SimpleNamespace(warnings=["manifest ok"])

    monkeypatch.setattr(regression_render, "audit_layout_instantiation", fake_layout_audit)
    monkeypatch.setattr(regression_render, "render_manifest", fake_render_manifest)
    monkeypatch.setattr(regression_render, "audit_manifest", fake_manifest_audit)

    result = regression_render._audit_sample(sample_dir)

    expected_structure = {
        "chart_type": "flowchart",
        "nodes": [{"id": "n_start", "label": "Start"}],
        "edges": [{"id": "e1", "source": "n_start", "target": "n_start"}],
        "groups": [],
    }
    assert calls["render_manifest"]["structure_instantiation"] == expected_structure
    assert calls["render_manifest"]["layout_instantiation"] == {
        "n_start": {"type": "rectangle", "x": 0, "y": 0, "w": 100, "h": 50},
        "e1": {
            "start": {"elementId": "n_start", "side": "right"},
            "end": {"elementId": "n_start", "side": "left"},
        },
    }
    assert calls["render_manifest"]["canvas_library"] == "excalidraw"
    assert calls["layout_audit"][1] == expected_structure
    assert calls["manifest_audit"][1] == expected_structure
    assert calls["manifest_audit"][2] == "excalidraw"
    assert result["layout_warnings"] == ["layout ok"]
    assert result["manifest_warnings"] == ["manifest ok"]
    assert result["rendered_arrows"] == 1


def test_regression_render_fails_when_requested_samples_are_missing(tmp_path):
    code = regression_render.main(
        [
            "--samples-root",
            str(tmp_path),
            "--samples",
            "missing_sample",
            "--json",
        ]
    )

    assert code == 1


def test_regression_render_resolves_model_layer_under_current_variant_root(tmp_path, monkeypatch):
    variant_root = tmp_path / "experiments" / "exp1" / "outputs" / "evodiagram" / "evodiagram"
    sample_dir = variant_root / "model-x" / "sample"
    (sample_dir / "1_structure").mkdir(parents=True)
    (sample_dir / "3_layout").mkdir(parents=True)
    (sample_dir / "1_structure" / "structure_instantiation.json").write_text(
        json.dumps({"edges": []}),
        encoding="utf-8",
    )
    (sample_dir / "3_layout" / "layout_instantiation.json").write_text(
        json.dumps({}),
        encoding="utf-8",
    )

    monkeypatch.setattr(regression_render, "audit_layout_instantiation", lambda *_args: [])
    monkeypatch.setattr(
        regression_render,
        "render_manifest",
        lambda **_kwargs: SimpleNamespace(manifest={"elements": []}),
    )
    monkeypatch.setattr(
        regression_render,
        "audit_manifest",
        lambda *_args, **_kwargs: SimpleNamespace(warnings=[]),
    )

    code = regression_render.main(
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
