# -*- coding: utf-8 -*-
"""Analysis-render option plumbing: facade → adapter → service → renderer.

The refiner's VLM-facing re-render requests ``render_scale=1.0, crop=False``
through ``canvas_environment.render_png_result``; these tests pin that the
options survive every hop (and that omitting them reproduces the historical
product render defaults).
"""

from __future__ import annotations

import base64
from pathlib import Path

from evo_diagram.agentic_system.render_engine import service
from evo_diagram.canvas_environment import ANALYSIS_RENDER_SCALE
from evo_diagram.canvas_environment import render_png_result as facade_render_png_result


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _patch_render_canvas(monkeypatch):
    seen = {}

    def fake_render_canvas(**kwargs):
        seen.update(kwargs)
        Path(kwargs["output_path"]).write_bytes(_PNG_1X1)
        return {"output_path": kwargs["output_path"]}

    monkeypatch.setattr(service, "render_canvas", fake_render_canvas)
    return seen


def test_analysis_render_scale_constant_is_one():
    assert ANALYSIS_RENDER_SCALE == 1.0


def test_service_forwards_analysis_options_to_render_canvas(monkeypatch, tmp_path):
    seen = _patch_render_canvas(monkeypatch)

    result = service.render_png_result(
        {"elements": []},
        str(tmp_path / "out.png"),
        render_scale=ANALYSIS_RENDER_SCALE,
        crop=False,
    )

    assert result.ok is True
    assert seen["render_scale"] == 1.0
    assert seen["crop"] is False


def test_service_defaults_reproduce_product_render(monkeypatch, tmp_path):
    seen = _patch_render_canvas(monkeypatch)

    result = service.render_png_result({"elements": []}, str(tmp_path / "out.png"))

    assert result.ok is True
    assert seen["render_scale"] is None  # renderer CLI default (4) applies
    assert seen["crop"] is True          # smart crop stays on


def test_facade_forwards_analysis_options_through_adapter(monkeypatch, tmp_path):
    seen = _patch_render_canvas(monkeypatch)

    result = facade_render_png_result(
        {"elements": []},
        str(tmp_path / "out.png"),
        canvas_library="excalidraw",
        render_scale=ANALYSIS_RENDER_SCALE,
        crop=False,
    )

    assert result.ok is True
    assert seen["render_scale"] == 1.0
    assert seen["crop"] is False


def test_facade_defaults_reproduce_product_render(monkeypatch, tmp_path):
    seen = _patch_render_canvas(monkeypatch)

    result = facade_render_png_result(
        {"elements": []},
        str(tmp_path / "out.png"),
    )

    assert result.ok is True
    assert seen["render_scale"] is None
    assert seen["crop"] is True
