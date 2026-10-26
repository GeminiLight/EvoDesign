#!/usr/bin/env python3
"""Unified Canvas Rendering Module."""

from __future__ import annotations

import abc
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from evo_diagram.canvas_runtime import normalize_canvas_library

from .shared.png_validation import validate_png_file

try:
    from .shared.image_cropper import smart_crop
except ImportError:
    smart_crop = None

SnapshotDict = Dict[str, Any]
SceneDict = Dict[str, Any]
DataDict = Union[SnapshotDict, SceneDict]


DEFAULT_RENDER_TIMEOUT_MS = 60_000
SUBPROCESS_TIMEOUT_GRACE_SECONDS = 5.0
MAX_RENDERER_VIEWPORT_WIDTH = 8_000
MAX_RENDERER_VIEWPORT_HEIGHT = 8_000
MAX_RENDER_TIMEOUT_MS = 300_000
MAX_RENDER_MARGIN = 1_000
MAX_EXCALIDRAW_RENDER_SCALE = 4.0
LOCAL_RENDERER_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _decode_process_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _tail(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def _subprocess_timeout_seconds(timeout_ms: Optional[int]) -> float:
    effective_timeout_ms = timeout_ms if timeout_ms is not None else DEFAULT_RENDER_TIMEOUT_MS
    return max(1.0, (int(effective_timeout_ms) / 1000.0) + SUBPROCESS_TIMEOUT_GRACE_SECONDS)


def _validate_positive_int(
    name: str,
    value: Optional[int],
    *,
    max_value: Optional[int] = None,
) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer; got {value!r}.")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer; got {value!r}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}; got {value!r}.")
    return value


def _validate_non_negative_int(
    name: str,
    value: Optional[int],
    *,
    max_value: Optional[int] = None,
) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative integer; got {value!r}.")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer; got {value!r}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}; got {value!r}.")
    return value


def _validate_positive_number(
    name: str,
    value: Optional[float],
    *,
    max_value: Optional[float] = None,
) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive number; got {value!r}.")
    numeric = float(value)
    if numeric <= 0 or numeric != numeric or numeric in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be a positive finite number; got {value!r}.")
    if max_value is not None and numeric > max_value:
        raise ValueError(f"{name} must be <= {max_value}; got {value!r}.")
    return numeric


def _normalize_pathname(pathname: str) -> str:
    if pathname == "/":
        return pathname
    return pathname.rstrip("/")


def _validate_renderer_url(url: Optional[str], expected_pathname: str) -> Optional[str]:
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Renderer URL must use http or https.")
    if parsed.hostname not in LOCAL_RENDERER_HOSTS:
        raise ValueError("Renderer URL must point to a local host.")
    if _normalize_pathname(parsed.path) != _normalize_pathname(expected_pathname):
        raise ValueError(f"Renderer URL must point to {expected_pathname}.")
    return url


def _validate_render_options(
    *,
    viewport_width: Optional[int],
    viewport_height: Optional[int],
    timeout_ms: Optional[int],
    margin: Optional[int],
    render_scale: Optional[float],
) -> Dict[str, Any]:
    return {
        "viewport_width": _validate_positive_int(
            "viewport_width",
            viewport_width,
            max_value=MAX_RENDERER_VIEWPORT_WIDTH,
        ),
        "viewport_height": _validate_positive_int(
            "viewport_height",
            viewport_height,
            max_value=MAX_RENDERER_VIEWPORT_HEIGHT,
        ),
        "timeout_ms": _validate_positive_int(
            "timeout_ms",
            timeout_ms,
            max_value=MAX_RENDER_TIMEOUT_MS,
        ),
        "margin": _validate_non_negative_int(
            "margin",
            margin,
            max_value=MAX_RENDER_MARGIN,
        ),
        "render_scale": _validate_positive_number(
            "render_scale",
            render_scale,
            max_value=MAX_EXCALIDRAW_RENDER_SCALE,
        ),
    }


def _ensure_rendered_output(
    output_file: Path,
    completed: subprocess.CompletedProcess[bytes],
    *,
    phase: str,
) -> None:
    """Fail fast when a renderer reports success without a usable image."""
    try:
        validate_png_file(output_file, context=f"Render after {phase}")
        return
    except RuntimeError as exc:
        validation_error = exc

    stdout = _tail(_decode_process_output(completed.stdout))
    stderr = _tail(_decode_process_output(completed.stderr))
    if not output_file.exists():
        problem = "did not create output file"
    elif output_file.stat().st_size <= 0:
        problem = "created an empty output file"
    else:
        problem = "created an unusable output file"
    raise RuntimeError(
        f"Render {problem} after {phase}: {output_file}; "
        f"stdout_tail={stdout!r}; stderr_tail={stderr!r}; "
        f"validation_error={validation_error}"
    ) from validation_error


class CanvasRenderBase(abc.ABC):
    """Abstract base class for Canvas renders (Tldraw, Excalidraw, etc.)."""

    def __init__(
        self,
        script_path: str,
        default_runner: List[str] = None,
        renderer_path: str = "",
    ):
        self.script_path = script_path
        self.default_runner = default_runner or ["npx", "tsx"]
        self.renderer_path = renderer_path

    def _resolve_script_path(self, override_path: Optional[str], working_dir: Optional[str]) -> Path:
        script_target = override_path or self.script_path
        base_dir = Path(working_dir).resolve() if working_dir else Path(__file__).resolve().parent
        candidate = Path(script_target)
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()

        if not candidate.exists():
            raise FileNotFoundError(f"Renderer script not found at: {candidate}")

        return candidate

    def render(
        self,
        data: DataDict,
        output_path: str = "output.png",
        *,
        script_path: Optional[str] = None,
        runner: Optional[List[str]] = None,
        url: Optional[str] = None,
        viewport_width: Optional[int] = None,
        viewport_height: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        margin: Optional[int] = None,
        render_scale: Optional[float] = None,
        crop: bool = True,
        working_dir: Optional[str] = None,
        ensure_ascii: bool = False,
        capture_output: bool = False,
    ) -> Dict[str, str]:
        """Render ``data`` to a PNG at ``output_path``.

        ``render_scale`` sets the renderer export scale in image pixels per
        manifest unit (Excalidraw only; TLDraw rejects it). ``crop=False``
        skips the post-render smart crop and keeps the renderer's full
        exported canvas. ``render_scale=1.0`` together with ``crop=False``
        is the **analysis render** mode used for VLM refinement/verification
        input: one image pixel equals one manifest unit and the framing is
        the renderer's deterministic content bounds plus margin, so it no
        longer drifts with pixel-content detection between rounds. The
        defaults reproduce the historical product render exactly.
        """
        self._validate_data(data)
        options = _validate_render_options(
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            timeout_ms=timeout_ms,
            margin=margin,
            render_scale=render_scale,
        )
        viewport_width = options["viewport_width"]
        viewport_height = options["viewport_height"]
        timeout_ms = options["timeout_ms"]
        margin = options["margin"]
        render_scale = options["render_scale"]
        url = _validate_renderer_url(url, self.renderer_path) if self.renderer_path else url

        # Path Resolution
        script = self._resolve_script_path(script_path, working_dir)
        workdir = Path(working_dir).resolve() if working_dir else script.parent.parent

        output_file = Path(output_path)
        if not output_file.is_absolute():
            output_file = Path.cwd() / output_file
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # CLI Build
        cmd = (runner or self.default_runner) + [str(script)]
        cmd = self._append_cli_args(
            cmd,
            output_file,
            url,
            viewport_width,
            viewport_height,
            timeout_ms,
            margin,
            render_scale,
        )

        # Execution
        payload = json.dumps(data, ensure_ascii=ensure_ascii)
        python_timeout = _subprocess_timeout_seconds(timeout_ms)
        try:
            completed = subprocess.run(
                cmd,
                input=payload.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                cwd=str(workdir),
                timeout=python_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _tail(_decode_process_output(exc.output))
            stderr = _tail(_decode_process_output(exc.stderr))
            raise TimeoutError(
                "Render subprocess timed out "
                f"after {python_timeout:.1f}s; cwd={workdir}; "
                f"command={' '.join(cmd)}; stdout_tail={stdout!r}; "
                f"stderr_tail={stderr!r}"
            ) from exc

        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Render failed (code {completed.returncode}): {stderr}")

        _ensure_rendered_output(output_file, completed, phase="subprocess")

        result: Dict[str, str] = {"output_path": str(output_file)}
        if capture_output:
            result["stdout"] = completed.stdout.decode("utf-8", errors="replace")
            result["stderr"] = completed.stderr.decode("utf-8", errors="replace")

        if crop:
            self._post_process(output_file)
        _ensure_rendered_output(output_file, completed, phase="post-process")

        return result

    @abc.abstractmethod
    def _validate_data(self, data: DataDict):
        """Validate input data structure."""
        pass

    @abc.abstractmethod
    def _append_cli_args(
        self,
        base_cmd: List[str],
        output_file: Path,
        url: Optional[str],
        width: Optional[int],
        height: Optional[int],
        timeout: Optional[int],
        margin: Optional[int],
        render_scale: Optional[float],
    ) -> List[str]:
        """Append renderer-specific CLI arguments."""
        pass

    def _post_process(self, output_file: Path):
        """Optional post-processing (e.g. smart crop).

        Skipped entirely when ``render()`` is called with ``crop=False``
        (analysis renders keep the renderer's full exported canvas).
        """
        pass


class TldrawRender(CanvasRenderBase):
    def __init__(self):
        super().__init__(
            script_path="../tool_services/scripts/render-tldraw.ts",
            renderer_path="/renderers/tldraw",
        )

    def _validate_data(self, data: DataDict):
        if "document" not in data:
            raise ValueError("Tldraw manifest must include a top-level 'document' key.")

    def _append_cli_args(self, cmd, output_file, url, width, height, timeout, margin, render_scale):
        if render_scale is not None:
            raise ValueError("render_scale is not supported by the TLDraw renderer.")
        cmd.extend(["--snapshot", "-", "--output", str(output_file)])
        if url:
             cmd.extend(["--url", url])
        if width is not None:
            cmd.extend(["--width", str(int(width))])
        if height is not None:
            cmd.extend(["--height", str(int(height))])
        if timeout is not None:
            cmd.extend(["--timeout", str(int(timeout))])
        if margin is not None:
             cmd.extend(["--margin", str(int(margin))])
        return cmd

    def _post_process(self, output_file: Path):
        if smart_crop:
             smart_crop.invoke(input={
                "image_path": str(output_file),
                "output_path": str(output_file),
                "padding": 0,
                "canvas_engine": "tldraw",
            })

class ExcalidrawRender(CanvasRenderBase):
    def __init__(self):
        super().__init__(
            script_path="../tool_services/scripts/render-excalidraw.ts",
            renderer_path="/renderers/excalidraw",
        )

    def render(self, data: DataDict, *args, **kwargs) -> Dict[str, str]:
        # Strip _meta for Excalidraw to match previous behavior and avoid potential renderer issues
        if isinstance(data, dict) and "_meta" in data:
            # Shallow copy to avoid mutating original state
            data = {k: v for k, v in data.items() if k != "_meta"}
        return super().render(data, *args, **kwargs)

    def _validate_data(self, data: DataDict):
        if "elements" not in data or not isinstance(data.get("elements"), list):
            raise ValueError("Excalidraw manifest must include an 'elements' list.")

    def _append_cli_args(self, cmd, output_file, url, width, height, timeout, margin, render_scale):
        cmd.extend(["--scene", "-", "--output", str(output_file)])
        if url:
             cmd.extend(["--url", url])
        if width is not None:
            cmd.extend(["--width", str(int(width))])
        if height is not None:
            cmd.extend(["--height", str(int(height))])
        if timeout is not None:
            cmd.extend(["--timeout", str(int(timeout))])
        if margin is not None:
             cmd.extend(["--margin", str(int(margin))])
        if render_scale is not None:
             cmd.extend(["--scale", str(float(render_scale))])
        return cmd

    def _post_process(self, output_file: Path):
        """Apply smart crop to remove white space and watermarks from Excalidraw renders."""
        if smart_crop:
             smart_crop.invoke(input={
                "image_path": str(output_file),
                "output_path": str(output_file),
                "padding": 60,
                "canvas_engine": "excalidraw",
            })


def get_renderer(canvas_library: str) -> CanvasRenderBase:
    canvas_library = normalize_canvas_library(canvas_library)
    if canvas_library == "tldraw":
        return TldrawRender()
    elif canvas_library == "excalidraw":
        return ExcalidrawRender()
    else:
        raise ValueError(f"Unknown canvas library: {canvas_library}")

def render_canvas(
    data: Union[Dict, List],
    output_path: str = "output.png",
    canvas_library: str = "excalidraw",
    **kwargs
) -> Dict[str, str]:
    """Unified entry point for rendering diagram data."""
    canvas_library = normalize_canvas_library(canvas_library)

    # Pre-normalization for Excalidraw lists
    if canvas_library == "excalidraw" and isinstance(data, list):
        data = {"elements": data}

    renderer = get_renderer(canvas_library)
    return renderer.render(data, output_path, **kwargs)
