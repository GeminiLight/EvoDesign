from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from evo_diagram.canvas_environment import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
    CANVAS_MAX_X,
    CANVAS_MAX_Y,
    CanvasAuditIssue,
    CanvasAuditReport,
    CanvasEnvironment,
    CanvasEnvironmentConfig,
    audit_manifest,
    detect_group_frame_ids,
    normalize_manifest,
    repair_manifest_zorder,
    validate_png_file,
)
from evo_diagram.canvas_environment import _render_engine_adapter
from evo_diagram.canvas_environment import rendering
from evo_diagram.canvas_environment import validation


def test_canvas_environment_rejects_unknown_canvas_library():
    with pytest.raises(ValueError, match="Unknown canvas_library"):
        CanvasEnvironment(CanvasEnvironmentConfig(canvas_library="bad")).canvas_library


def test_canvas_environment_normalizes_supported_canvas_library():
    env = CanvasEnvironment(CanvasEnvironmentConfig(canvas_library=" Excalidraw "))

    assert env.canvas_library == "excalidraw"


def test_render_canvas_file_loads_json_normalizes_and_delegates(tmp_path, monkeypatch):
    input_path = tmp_path / "scene.json"
    input_path.write_text('{"elements": [{"id": "n1"}]}', encoding="utf-8")
    seen = {}

    def fake_render_canvas(
        *,
        data,
        output_path,
        canvas_library,
        viewport_width=None,
        viewport_height=None,
    ):
        seen.update(
            data=data,
            output_path=output_path,
            canvas_library=canvas_library,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        return {"output_path": output_path}

    monkeypatch.setattr(rendering, "render_canvas", fake_render_canvas)

    result = rendering.render_canvas_file(
        str(input_path),
        str(tmp_path / "out.png"),
        "Excalidraw",
        viewport_width=123,
    )

    assert result["output_path"].endswith("out.png")
    assert seen["data"]["elements"][0]["id"] == "n1"
    assert seen["canvas_library"] == "excalidraw"
    assert seen["viewport_width"] == 123
    assert seen["viewport_height"] is None


def test_render_canvas_file_reports_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError, match="Canvas JSON file not found"):
        rendering.render_canvas_file(str(tmp_path / "missing.json"), str(tmp_path / "out.png"))


@pytest.mark.parametrize("function_name", ["render_canvas", "render_canvas_file"])
def test_public_raw_render_facade_does_not_accept_arbitrary_kwargs(function_name):
    signature = inspect.signature(getattr(rendering, function_name))
    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def test_public_raw_render_facade_rejects_debug_escape_hatch_kwargs(tmp_path):
    input_path = tmp_path / "scene.json"
    input_path.write_text('{"elements": []}', encoding="utf-8")

    with pytest.raises(TypeError, match="script_path"):
        rendering.render_canvas(
            {"elements": []},
            str(tmp_path / "out.png"),
            script_path="/tmp/render.ts",
        )

    with pytest.raises(TypeError, match="runner"):
        rendering.render_canvas_file(
            str(input_path),
            str(tmp_path / "out.png"),
            runner=["node"],
        )


def test_canvas_constants_are_exported_from_facade():
    assert CANVAS_MAX_X > 0
    assert CANVAS_MAX_Y > 0
    assert CANVAS_DEFAULT_VIEWPORT_WIDTH == 4000
    assert CANVAS_DEFAULT_VIEWPORT_HEIGHT == 4000


def test_render_manifest_uses_runtime_default_viewport(monkeypatch, tmp_path):
    seen = {}

    def fake_render_manifest(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            manifest={"elements": []},
            png_path=str(tmp_path / "diagram.png"),
            manifest_path=str(tmp_path / "diagram.json"),
        )

    monkeypatch.setattr(
        _render_engine_adapter,
        "render_manifest",
        fake_render_manifest,
    )

    rendering.render_manifest(
        layout_instantiation={},
        structure_instantiation={},
        canvas_library="excalidraw",
    )

    assert seen["viewport_width"] == CANVAS_DEFAULT_VIEWPORT_WIDTH
    assert seen["viewport_height"] == CANVAS_DEFAULT_VIEWPORT_HEIGHT


def test_audit_manifest_returns_facade_report(monkeypatch):
    manifest = {"elements": []}
    structure = {"edges": []}
    captured = {}

    class LegacyIssue:
        category = "empty_text"
        message = "missing label"
        element_id = "title-1"
        severity = "MINOR"

    class LegacyReport:
        warnings = ("legacy warning",)
        issues = (LegacyIssue(),)

    def fake_audit_manifest(value, *, structure_instantiation=None):
        captured["manifest"] = value
        captured["structure_instantiation"] = structure_instantiation
        return LegacyReport()

    monkeypatch.setattr(
        _render_engine_adapter,
        "audit_excalidraw_manifest",
        fake_audit_manifest,
    )

    report = audit_manifest(
        manifest,
        structure_instantiation=structure,
        canvas_library=" Excalidraw ",
    )

    assert isinstance(report, CanvasAuditReport)
    assert report.warnings == ["legacy warning"]
    assert report.issues == [
        CanvasAuditIssue(
            category="empty_text",
            message="missing label",
            element_id="title-1",
            severity="MINOR",
        )
    ]
    assert captured == {
        "manifest": manifest,
        "structure_instantiation": structure,
    }


def test_audit_manifest_coerces_mapping_reports(monkeypatch):
    def fake_audit_manifest(value, *, structure_instantiation=None):
        return {
            "warnings": "mapping warning",
            "issues": [
                {
                    "category": "z_order",
                    "message": "covered element",
                    "element_id": "node-1",
                    "severity": "MAJOR",
                }
            ],
        }

    monkeypatch.setattr(
        _render_engine_adapter,
        "audit_tldraw_manifest",
        fake_audit_manifest,
    )

    report = audit_manifest(
        {"document": {}},
        structure_instantiation={"nodes": []},
        canvas_library="tldraw",
    )

    assert report.warnings == ["mapping warning"]
    assert report.issues == [
        CanvasAuditIssue(
            category="z_order",
            message="covered element",
            element_id="node-1",
            severity="MAJOR",
        )
    ]


def test_normalize_manifest_is_explicit_noop_for_tldraw(monkeypatch):
    manifest = {"document": {"id": "doc"}}

    def fail_normalize(_manifest):
        raise AssertionError("tldraw normalize must not load Excalidraw normalizer")

    monkeypatch.setattr(
        _render_engine_adapter,
        "normalize_excalidraw_manifest",
        fail_normalize,
    )

    assert normalize_manifest(manifest, canvas_library="tldraw") is manifest


def test_canvas_validation_rejects_unimplemented_future_canvas(monkeypatch):
    monkeypatch.setattr(validation, "normalize_canvas_library", lambda _canvas: "future")

    with pytest.raises(NotImplementedError, match="normalize_manifest"):
        validation.normalize_manifest({}, canvas_library="future")
    with pytest.raises(NotImplementedError, match="audit_manifest"):
        validation.audit_manifest({}, canvas_library="future")
    with pytest.raises(NotImplementedError, match="repair_manifest_zorder"):
        validation.repair_manifest_zorder({}, canvas_library="future")


def test_canvas_audit_facade_return_annotations_are_stable():
    assert get_type_hints(validation.audit_manifest)["return"] is CanvasAuditReport
    assert get_type_hints(CanvasEnvironment.audit_manifest)["return"] is CanvasAuditReport


def test_repair_manifest_zorder_delegates_for_excalidraw(monkeypatch):
    manifest = {"elements": [{"id": "frame", "index": "a00001"}]}
    calls = []

    class FakeZOrderRepair:
        @staticmethod
        def repair_zorder(value):
            calls.append(value)
            return {"elements": [{"id": "frame", "index": "a00000"}]}

    monkeypatch.setattr(
        _render_engine_adapter,
        "repair_excalidraw_zorder",
        FakeZOrderRepair.repair_zorder,
    )

    repaired = repair_manifest_zorder(manifest, canvas_library=" Excalidraw ")

    assert calls == [manifest]
    assert repaired["elements"][0]["index"] == "a00000"


def test_repair_manifest_zorder_is_noop_for_tldraw(monkeypatch):
    manifest = {"records": [{"id": "shape:1"}]}

    def fail_loader():
        raise AssertionError("tldraw z-order repair should not load Excalidraw")

    monkeypatch.setattr(_render_engine_adapter, "repair_excalidraw_zorder", fail_loader)

    assert repair_manifest_zorder(manifest, canvas_library="tldraw") is manifest


def test_detect_group_frame_ids_delegates_through_private_adapter(monkeypatch):
    captured = {}

    def fake_detect_group_frame_ids(elements, *, structural, id_map):
        captured.update(
            elements=elements,
            structural=structural,
            id_map=id_map,
        )
        return {"frame-1"}

    monkeypatch.setattr(
        _render_engine_adapter,
        "detect_group_frame_ids",
        fake_detect_group_frame_ids,
    )

    elements = [{"id": "frame-1", "type": "rectangle"}]
    result = detect_group_frame_ids(
        elements,
        structural=True,
        id_map={"g_frame": "frame-1"},
    )

    assert result == {"frame-1"}
    assert captured == {
        "elements": elements,
        "structural": True,
        "id_map": {"g_frame": "frame-1"},
    }


def test_validate_png_file_delegates_through_private_adapter(tmp_path, monkeypatch):
    png_path = tmp_path / "diagram.png"
    calls = []

    def fake_validate_png_file(output_file, *, context):
        calls.append((output_file, context))

    monkeypatch.setattr(
        _render_engine_adapter,
        "validate_png_file",
        fake_validate_png_file,
    )

    validate_png_file(png_path, context="verifier input")

    assert calls == [(png_path, "verifier input")]
