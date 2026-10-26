from __future__ import annotations

import subprocess
import base64

import pytest

from evo_diagram.agentic_system.render_engine import canvas_render
from evo_diagram.agentic_system.render_engine.canvas_render import ExcalidrawRender, TldrawRender


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_canvas_render_passes_python_side_timeout_to_subprocess(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "wb") as f:
            f.write(_PNG_1X1)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok", stderr=b"")

    renderer = ExcalidrawRender()
    monkeypatch.setattr(canvas_render.subprocess, "run", fake_run)
    monkeypatch.setattr(renderer, "_post_process", lambda _output_file: None)

    renderer.render(
        {"elements": []},
        output_path=str(tmp_path / "out.png"),
        script_path=str(script),
        runner=["node"],
        timeout_ms=1000,
    )

    assert seen["kwargs"]["timeout"] == 6.0
    assert "--timeout" in seen["cmd"]
    assert "1000" in seen["cmd"]


def test_canvas_render_rejects_invalid_render_options_before_subprocess(monkeypatch, tmp_path):
    def fail_run(*args, **kwargs):
        raise AssertionError("invalid render options must not launch subprocess")

    monkeypatch.setattr(canvas_render.subprocess, "run", fail_run)

    renderer = ExcalidrawRender()
    with pytest.raises(ValueError, match="viewport_width"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), viewport_width=0)
    with pytest.raises(ValueError, match="timeout_ms"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), timeout_ms=-1)
    with pytest.raises(ValueError, match="margin"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), margin=-1)
    with pytest.raises(ValueError, match="render_scale"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), render_scale=float("nan"))
    with pytest.raises(ValueError, match="viewport_width.*8000"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), viewport_width=8001)
    with pytest.raises(ValueError, match="viewport_height.*8000"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), viewport_height=8001)
    with pytest.raises(ValueError, match="timeout_ms.*300000"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), timeout_ms=300001)
    with pytest.raises(ValueError, match="margin.*1000"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), margin=1001)
    with pytest.raises(ValueError, match="render_scale.*4.0"):
        renderer.render({"elements": []}, output_path=str(tmp_path / "out.png"), render_scale=4.1)


def test_canvas_render_rejects_non_local_or_wrong_renderer_urls(monkeypatch, tmp_path):
    def fail_run(*args, **kwargs):
        raise AssertionError("invalid renderer URL must not launch subprocess")

    monkeypatch.setattr(canvas_render.subprocess, "run", fail_run)
    renderer = ExcalidrawRender()

    with pytest.raises(ValueError, match="local host"):
        renderer.render(
            {"elements": []},
            output_path=str(tmp_path / "out.png"),
            url="https://example.com/renderers/excalidraw",
        )
    with pytest.raises(ValueError, match="/renderers/excalidraw"):
        renderer.render(
            {"elements": []},
            output_path=str(tmp_path / "out.png"),
            url="http://localhost:3000/renderers/tldraw",
        )


def test_canvas_render_passes_positive_render_options_to_excalidraw_cli(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "wb") as f:
            f.write(_PNG_1X1)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok", stderr=b"")

    renderer = ExcalidrawRender()
    monkeypatch.setattr(canvas_render.subprocess, "run", fake_run)
    monkeypatch.setattr(renderer, "_post_process", lambda _output_file: None)

    renderer.render(
        {"elements": []},
        output_path=str(tmp_path / "out.png"),
        script_path=str(script),
        runner=["node"],
        viewport_width=1,
        viewport_height=2,
        timeout_ms=3,
        margin=0,
        render_scale=1.5,
        url="http://localhost:3000/renderers/excalidraw",
    )

    assert seen["cmd"][seen["cmd"].index("--width") + 1] == "1"
    assert seen["cmd"][seen["cmd"].index("--height") + 1] == "2"
    assert seen["cmd"][seen["cmd"].index("--timeout") + 1] == "3"
    assert seen["cmd"][seen["cmd"].index("--margin") + 1] == "0"
    assert seen["cmd"][seen["cmd"].index("--scale") + 1] == "1.5"
    assert seen["cmd"][seen["cmd"].index("--url") + 1] == "http://localhost:3000/renderers/excalidraw"


def test_tldraw_render_rejects_unsupported_render_scale(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")

    def fail_run(*args, **kwargs):
        raise AssertionError("unsupported TLDraw scale must not launch subprocess")

    renderer = TldrawRender()
    monkeypatch.setattr(canvas_render.subprocess, "run", fail_run)

    with pytest.raises(ValueError, match="render_scale is not supported"):
        renderer.render(
            {"document": {"store": {}}},
            output_path=str(tmp_path / "out.png"),
            script_path=str(script),
            runner=["node"],
            render_scale=2,
        )


def test_render_canvas_normalizes_canvas_library_before_dispatch(monkeypatch, tmp_path):
    seen = {}

    class FakeRenderer:
        def render(self, data, output_path, **kwargs):
            seen["data"] = data
            seen["output_path"] = output_path
            return {"output_path": output_path}

    def fake_get_renderer(canvas_library):
        seen["canvas_library"] = canvas_library
        return FakeRenderer()

    monkeypatch.setattr(canvas_render, "get_renderer", fake_get_renderer)

    result = canvas_render.render_canvas(
        {"document": {"store": {}}},
        output_path=str(tmp_path / "out.png"),
        canvas_library=" TLDraw ",
    )

    assert seen["canvas_library"] == "tldraw"
    assert result == {"output_path": str(tmp_path / "out.png")}


def test_canvas_render_rejects_success_without_output_file(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=b"renderer says ok",
            stderr=b"but wrote nothing",
        )

    renderer = ExcalidrawRender()
    monkeypatch.setattr(canvas_render.subprocess, "run", fake_run)
    monkeypatch.setattr(renderer, "_post_process", lambda _output_file: None)

    with pytest.raises(RuntimeError, match="did not create output file") as exc_info:
        renderer.render(
            {"elements": []},
            output_path=str(tmp_path / "out.png"),
            script_path=str(script),
            runner=["node"],
            timeout_ms=1000,
        )

    message = str(exc_info.value)
    assert "renderer says ok" in message
    assert "but wrote nothing" in message


def test_canvas_render_rejects_success_with_empty_output_file(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        output_path = cmd[cmd.index("--output") + 1]
        open(output_path, "wb").close()
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok", stderr=b"")

    renderer = ExcalidrawRender()
    monkeypatch.setattr(canvas_render.subprocess, "run", fake_run)
    monkeypatch.setattr(renderer, "_post_process", lambda _output_file: None)

    with pytest.raises(RuntimeError, match="empty output file"):
        renderer.render(
            {"elements": []},
            output_path=str(tmp_path / "out.png"),
            script_path=str(script),
            runner=["node"],
            timeout_ms=1000,
        )


def test_canvas_render_rejects_success_with_corrupt_png(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "wb") as f:
            f.write(b"not a png")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok", stderr=b"")

    renderer = ExcalidrawRender()
    monkeypatch.setattr(canvas_render.subprocess, "run", fake_run)
    monkeypatch.setattr(renderer, "_post_process", lambda _output_file: None)

    with pytest.raises(RuntimeError, match="unreadable PNG|corrupt PNG"):
        renderer.render(
            {"elements": []},
            output_path=str(tmp_path / "out.png"),
            script_path=str(script),
            runner=["node"],
            timeout_ms=1000,
        )


def test_canvas_render_timeout_reports_command_and_output_tail(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=kwargs["timeout"],
            output=b"stdout before timeout",
            stderr=b"renderer stuck",
        )

    renderer = ExcalidrawRender()
    monkeypatch.setattr(canvas_render.subprocess, "run", fake_run)
    monkeypatch.setattr(renderer, "_post_process", lambda _output_file: None)

    with pytest.raises(TimeoutError, match="Render subprocess timed out") as exc_info:
        renderer.render(
            {"elements": []},
            output_path=str(tmp_path / "out.png"),
            script_path=str(script),
            runner=["node"],
            timeout_ms=1000,
        )

    message = str(exc_info.value)
    assert "stdout before timeout" in message
    assert "renderer stuck" in message
    assert str(script) in message


# ---------------------------------------------------------------------------
# Analysis render mode: render_scale=1.0 + crop=False
# ---------------------------------------------------------------------------


class _RecordingCrop:
    """Stand-in for the langchain smart_crop tool recording its invocations."""

    def __init__(self):
        self.calls = []

    def invoke(self, input):
        self.calls.append(input)
        return "cropped"


def _fake_run_factory(seen):
    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "wb") as f:
            f.write(_PNG_1X1)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok", stderr=b"")

    return fake_run


def test_excalidraw_render_smart_crops_by_default(monkeypatch, tmp_path):
    """Backward compatibility: omitting the new parameters keeps the
    historical product pipeline (renderer-default scale + smart crop)."""
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")
    seen = {}
    recorder = _RecordingCrop()

    monkeypatch.setattr(canvas_render.subprocess, "run", _fake_run_factory(seen))
    monkeypatch.setattr(canvas_render, "smart_crop", recorder)

    ExcalidrawRender().render(
        {"elements": []},
        output_path=str(tmp_path / "out.png"),
        script_path=str(script),
        runner=["node"],
    )

    assert "--scale" not in seen["cmd"]  # CLI default (4) applies
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["padding"] == 60
    assert recorder.calls[0]["canvas_engine"] == "excalidraw"


def test_excalidraw_analysis_render_passes_scale_one_and_skips_crop(
    monkeypatch, tmp_path
):
    """crop=False + render_scale=1.0: the exported canvas reaches the caller
    untouched (1 image pixel = 1 manifest unit, deterministic framing)."""
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")
    seen = {}
    recorder = _RecordingCrop()
    out_path = tmp_path / "out.png"

    monkeypatch.setattr(canvas_render.subprocess, "run", _fake_run_factory(seen))
    monkeypatch.setattr(canvas_render, "smart_crop", recorder)

    result = ExcalidrawRender().render(
        {"elements": []},
        output_path=str(out_path),
        script_path=str(script),
        runner=["node"],
        render_scale=1.0,
        crop=False,
    )

    assert seen["cmd"][seen["cmd"].index("--scale") + 1] == "1.0"
    assert recorder.calls == []
    assert result["output_path"] == str(out_path)
    assert out_path.read_bytes() == _PNG_1X1  # exactly what the renderer wrote


def test_tldraw_render_crop_false_skips_post_process(monkeypatch, tmp_path):
    script = tmp_path / "render.ts"
    script.write_text("// renderer stub\n", encoding="utf-8")
    recorder = _RecordingCrop()

    monkeypatch.setattr(canvas_render.subprocess, "run", _fake_run_factory({}))
    monkeypatch.setattr(canvas_render, "smart_crop", recorder)

    TldrawRender().render(
        {"document": {"store": {}}},
        output_path=str(tmp_path / "out.png"),
        script_path=str(script),
        runner=["node"],
        crop=False,
    )

    assert recorder.calls == []


def test_render_canvas_forwards_analysis_options_to_renderer(monkeypatch, tmp_path):
    seen = {}

    class FakeRenderer:
        def render(self, data, output_path, **kwargs):
            seen.update(kwargs)
            return {"output_path": output_path}

    monkeypatch.setattr(canvas_render, "get_renderer", lambda _lib: FakeRenderer())

    canvas_render.render_canvas(
        {"elements": []},
        output_path=str(tmp_path / "out.png"),
        canvas_library="excalidraw",
        render_scale=1.0,
        crop=False,
    )

    assert seen["render_scale"] == 1.0
    assert seen["crop"] is False
