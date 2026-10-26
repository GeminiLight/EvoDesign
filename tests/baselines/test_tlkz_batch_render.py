"""tlkz (TiKZ) baseline: code extraction, rendering, batch artifacts, script wiring."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from baselines.programmic.tlkz import tikz_render
from baselines.programmic.tlkz.tikz_render import CompileResult, RenderResult

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_baselines.sh"

MINIMAL_TIKZ = (
    "\\begin{tikzpicture}\n"
    "  \\node (a) at (0,0) [rectangle] {A};\n"
    "  \\node (b) at (2,0) [rectangle] {B};\n"
    "  \\draw[->] (a) -- (b);\n"
    "\\end{tikzpicture}"
)

_HAS_PDFLATEX = shutil.which("pdflatex") is not None
_HAS_PYMUPDF = (
    importlib.util.find_spec("pymupdf") is not None
    or importlib.util.find_spec("fitz") is not None
)


# --- 1. Code extraction must never feed fences to pdflatex -----------------

@pytest.mark.parametrize(
    "response",
    [
        f"```latex\n{MINIMAL_TIKZ}\n```",
        f"```tikz\n{MINIMAL_TIKZ}\n```",
        f"```\n{MINIMAL_TIKZ}\n```",
        f"```LaTeX\n{MINIMAL_TIKZ}\n```",
        f"Here is the diagram:\n```latex\n{MINIMAL_TIKZ}\n```\nHope this helps!",
    ],
)
def test_extract_tikz_code_strips_fences(response):
    extracted = tikz_render.extract_tikz_code(response)

    assert "```" not in extracted
    assert extracted.startswith("\\begin{tikzpicture}")
    assert extracted.endswith("\\end{tikzpicture}")


def test_extract_tikz_code_keeps_a_full_document():
    doc = tikz_render.wrap_standalone_document(MINIMAL_TIKZ)
    response = f"```latex\n{doc}\n```"

    extracted = tikz_render.extract_tikz_code(response)

    assert extracted.startswith("\\documentclass")
    assert extracted.endswith("\\end{document}")
    assert "```" not in extracted


def test_extract_tikz_code_handles_unclosed_fence():
    # Truncated responses leave the opening fence without a closing one; the
    # fence line must still not reach pdflatex.
    extracted = tikz_render.extract_tikz_code(f"```latex\n{MINIMAL_TIKZ}")

    assert "```" not in extracted
    assert extracted.startswith("\\begin{tikzpicture}")


def test_extract_tikz_code_plain_text_passthrough():
    assert tikz_render.extract_tikz_code(MINIMAL_TIKZ) == MINIMAL_TIKZ
    assert tikz_render.extract_tikz_code("") == ""


def test_wrap_standalone_document_wraps_bare_tikz_and_keeps_full_documents():
    wrapped = tikz_render.wrap_standalone_document(MINIMAL_TIKZ)
    assert wrapped.startswith("\\documentclass[tikz,border=2pt]{standalone}")
    assert "\\begin{document}" in wrapped
    assert wrapped.endswith("\\end{document}\n")

    # Idempotent: a full document is passed through without a second wrapper
    # (the shared strip() drops the trailing newline, hence the .strip()).
    rewrapped = tikz_render.wrap_standalone_document(wrapped)
    assert rewrapped.strip() == wrapped.strip()
    assert rewrapped.count("\\documentclass") == 1


# --- 2. Diagnostics come from stdout (nonstopmode leaves stderr empty) ------

def test_latex_diagnostics_reads_stdout():
    stdout = (
        "This is pdfTeX\n"
        "! Undefined control sequence.\n"
        "l.42   \\node (a) at (0,0) [ellipse] {A};\n"
        "Output written on diagram.pdf\n"
    )

    diagnostics = tikz_render.latex_diagnostics(stdout, "")

    assert "! Undefined control sequence." in diagnostics
    assert "l.42" in diagnostics


def test_compile_latex_reports_failure_without_raising(monkeypatch, tmp_path):
    def fake_pdflatex(tex_path, workdir, timeout):
        return subprocess.CompletedProcess(
            args=["pdflatex"], returncode=1, stdout="! Emergency stop.\nl.3 x\n", stderr=""
        )

    monkeypatch.setattr(tikz_render, "_run_pdflatex", fake_pdflatex)

    result = tikz_render.compile_latex("\\documentclass{standalone}\\begin{document}x", tmp_path)

    assert not result.success
    assert result.pdf_path is None
    assert "Emergency stop" in result.diagnostics


def test_compile_latex_reports_missing_pdflatex(monkeypatch, tmp_path):
    def fake_pdflatex(tex_path, workdir, timeout):
        raise FileNotFoundError("pdflatex")

    monkeypatch.setattr(tikz_render, "_run_pdflatex", fake_pdflatex)

    result = tikz_render.compile_latex("x", tmp_path)

    assert not result.success
    assert "pdflatex not found" in result.diagnostics


def test_render_tikz_to_png_converts_first_page(monkeypatch, tmp_path):
    captured = {}

    def fake_compile(source, workdir, timeout=tikz_render.DEFAULT_TIMEOUT):
        captured["source"] = source
        pdf = Path(workdir) / "diagram.pdf"
        pdf.write_bytes(b"%PDF-fake")
        return CompileResult(True, str(pdf))

    def fake_pdf_to_png(pdf_path, png_path, dpi=tikz_render.DEFAULT_DPI):
        captured["dpi"] = dpi
        with open(png_path, "wb") as f:
            f.write(b"\x89PNG fake")

    monkeypatch.setattr(tikz_render, "compile_latex", fake_compile)
    monkeypatch.setattr(tikz_render, "pdf_to_png", fake_pdf_to_png)

    png = tmp_path / "render.png"
    result = tikz_render.render_tikz_to_png(MINIMAL_TIKZ, str(png))

    assert result.success
    assert png.read_bytes() == b"\x89PNG fake"
    # The document handed to pdflatex is wrapped and fence-free.
    assert captured["source"].startswith("\\documentclass")
    assert "```" not in captured["source"]
    # Resolution matches diagramagent's `pdftoppm -png -r 150`.
    assert captured["dpi"] == 150


def test_render_tikz_to_png_propagates_compile_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tikz_render,
        "compile_latex",
        lambda source, workdir, timeout=tikz_render.DEFAULT_TIMEOUT: CompileResult(
            False, None, diagnostics="! LaTeX Error: boom"
        ),
    )

    result = tikz_render.render_tikz_to_png(MINIMAL_TIKZ, str(tmp_path / "render.png"))

    assert not result.success
    assert "boom" in result.diagnostics
    assert not (tmp_path / "render.png").exists()


# --- 3. Batch mode writes the evaluation artifact contract ------------------

class FakeAgent:
    """Stands in for TlkzAgent; returns a canned fenced response."""

    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return self.response


class FakeFixAgent:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return self.response


def _fake_render_ok(code, png_path, timeout=None):
    Path(png_path).write_bytes(b"\x89PNG")
    return RenderResult(True, png_path)


@pytest.fixture()
def dataset_file(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps([
            {"id": "sample_a", "content": "A then B", "query": "Draw the flow"},
            {"id": "sample_b", "content": "C then D", "query": "Draw the other flow"},
        ]),
        encoding="utf-8",
    )
    return str(path)


def test_process_dataset_writes_eval_artifacts(monkeypatch, tmp_path, dataset_file):
    from baselines.programmic.tlkz import main as tlkz_main

    monkeypatch.setattr(tlkz_main, "render_tikz_to_png", _fake_render_ok)
    output_dir = tmp_path / "out"

    tlkz_main.process_dataset(
        FakeAgent(f"```latex\n{MINIMAL_TIKZ}\n```"),
        dataset_file,
        str(output_dir),
        max_concurrent=2,
        fix_agent=FakeFixAgent("unused"),
    )

    for sample_id in ("sample_a", "sample_b"):
        sample_dir = output_dir / sample_id
        payload = json.loads((sample_dir / "input.json").read_text(encoding="utf-8"))
        assert payload["id"] == sample_id
        assert payload["query"]
        assert payload["content"]
        # The saved code is fence-free (never the raw ```latex response).
        tex = (sample_dir / "diagram.tex").read_text(encoding="utf-8")
        assert "```" not in tex
        assert tex.startswith("\\begin{tikzpicture}")
        assert (sample_dir / "render.png").read_bytes() == b"\x89PNG"
        assert not (sample_dir / "failed.json").exists()

    mapping = json.loads((output_dir / "mapping.json").read_text(encoding="utf-8"))
    assert isinstance(mapping, list)
    assert {m["id"] for m in mapping} == {"sample_a", "sample_b"}
    for entry in mapping:
        # Field set mirrors diagramagent _write_eval_artifacts.
        assert set(entry) == {
            "id",
            "query",
            "content_path",
            "reference_image_path",
            "generated_image_path",
            "code_path",
        }
        assert entry["generated_image_path"].endswith(os.path.join(entry["id"], "render.png"))
        assert entry["code_path"].endswith(os.path.join(entry["id"], "diagram.tex"))
        assert Path(entry["content_path"]).exists()


def test_batch_output_layout_is_readable_by_the_path_resolver(
    monkeypatch, tmp_path, dataset_file
):
    from baselines.programmic.tlkz import main as tlkz_main
    from evaluation import path_resolver

    monkeypatch.setattr(tlkz_main, "render_tikz_to_png", _fake_render_ok)
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    # Exactly the directory run_baselines.sh passes:
    # experiments/{exp}/outputs/baseline/code_tlkz/{model}
    output_dir = tmp_path / "experiments" / "exp1" / "outputs" / "baseline" / "code_tlkz" / "model-x"
    tlkz_main.process_dataset(
        FakeAgent(MINIMAL_TIKZ), dataset_file, str(output_dir), max_concurrent=1
    )

    resolved, score_dir, _ = path_resolver.parse_method_paths(
        "baselines/code_tlkz/model-x", "sample_a", exp_id="exp1"
    )
    assert resolved == output_dir / "sample_a" / "render.png"
    assert resolved.exists()
    assert score_dir == (
        tmp_path / "experiments" / "exp1" / "scores" / "baseline" / "code_tlkz" / "model-x" / "sample_a"
    )


def test_failed_sample_writes_missing_output_record(monkeypatch, tmp_path, dataset_file):
    from baselines.programmic.tlkz import main as tlkz_main

    attempts = {"n": 0}

    def always_fail(code, png_path, timeout=None):
        attempts["n"] += 1
        return RenderResult(False, None, "! LaTeX Error: still broken")

    monkeypatch.setattr(tlkz_main, "render_tikz_to_png", always_fail)
    output_dir = tmp_path / "out"
    # The repair must return DIFFERENT code, otherwise _render_with_repair
    # short-circuits and never re-compiles.
    fix_agent = FakeFixAgent(
        "```latex\n" + MINIMAL_TIKZ.replace("{A}", "{A repaired}") + "\n```"
    )

    tlkz_main.process_dataset(
        FakeAgent(MINIMAL_TIKZ), dataset_file, str(output_dir),
        max_concurrent=1, fix_agent=fix_agent,
    )

    for sample_id in ("sample_a", "sample_b"):
        sample_dir = output_dir / sample_id
        record = json.loads((sample_dir / "failed.json").read_text(encoding="utf-8"))
        # Mirrors evaluation/run_evaluation.py write_missing_output_record.
        assert record["status"] == "missing_output"
        assert record["id"] == sample_id
        assert "still broken" in record["error"]
        assert record["expected_image_path"] == str(sample_dir / "render.png")
        assert not (sample_dir / "render.png").exists()

    # Two render attempts per sample: initial + one diagnostic repair retry.
    assert attempts["n"] == 4
    assert len(fix_agent.calls) == 2
    assert not (output_dir / "mapping.json").exists()


def test_compile_failure_triggers_exactly_one_diagnostic_repair(
    monkeypatch, tmp_path, dataset_file
):
    from baselines.programmic.tlkz import main as tlkz_main

    results = [
        RenderResult(False, None, "! Undefined control sequence.\nl.3 \\node [ellipse]"),
        RenderResult(True, "PNG"),
    ]
    calls = []

    def flaky_render(code, png_path, timeout=None):
        calls.append(code)
        outcome = results[min(len(calls) - 1, len(results) - 1)]
        if outcome.success:
            Path(png_path).write_bytes(b"\x89PNG")
        return outcome

    monkeypatch.setattr(tlkz_main, "render_tikz_to_png", flaky_render)

    repaired = MINIMAL_TIKZ.replace("{A}", "{A fixed}")
    fix_agent = FakeFixAgent(f"```latex\n{repaired}\n```")
    output_dir = tmp_path / "out"

    tlkz_main.process_dataset(
        FakeAgent(MINIMAL_TIKZ), dataset_file, str(output_dir),
        max_concurrent=1, fix_agent=fix_agent,
    )

    # Only the first sample hits the flaky path deterministically; both
    # samples must end up ok (second sample succeeds on the first attempt).
    assert (output_dir / "sample_a" / "render.png").exists()
    assert len(fix_agent.calls) >= 1
    repair_payload = fix_agent.calls[0]
    # The pdflatex diagnostics (stdout-collected) are fed back to the model.
    assert "Undefined control sequence" in repair_payload["errors"]
    assert repair_payload["code"] == MINIMAL_TIKZ

    sample_dir = output_dir / "sample_a"
    # diagram.tex holds the code that produced the final artifact; the first
    # attempt stays on disk for debugging.
    assert "A fixed" in (sample_dir / "diagram.tex").read_text(encoding="utf-8")
    assert (sample_dir / "diagram_attempt1.tex").read_text(encoding="utf-8") == MINIMAL_TIKZ
    mapping = json.loads((output_dir / "mapping.json").read_text(encoding="utf-8"))
    assert {m["id"] for m in mapping} == {"sample_a", "sample_b"}


def test_empty_tikz_code_is_recorded_as_failure(monkeypatch, tmp_path, dataset_file):
    from baselines.programmic.tlkz import main as tlkz_main

    render_calls = []
    monkeypatch.setattr(
        tlkz_main,
        "render_tikz_to_png",
        lambda *a, **k: render_calls.append(a) or RenderResult(True, "PNG"),
    )
    output_dir = tmp_path / "out"

    tlkz_main.process_dataset(
        FakeAgent("```latex\n\n```"), dataset_file, str(output_dir), max_concurrent=1
    )

    assert not render_calls
    for sample_id in ("sample_a", "sample_b"):
        record = json.loads((output_dir / sample_id / "failed.json").read_text(encoding="utf-8"))
        assert record["status"] == "missing_output"
        assert "Empty TiKZ code" in record["error"]


def test_process_dataset_honours_start_end_slice(tmp_path, monkeypatch):
    from baselines.programmic.tlkz import main as tlkz_main

    dataset_path = tmp_path / "data.json"
    items = [{"id": f"s{i}", "content": f"c{i}", "query": "q"} for i in range(5)]
    dataset_path.write_text(json.dumps(items), encoding="utf-8")
    seen = []

    def spy(idx, item, agent, fix_agent, output_dir, start, total):
        seen.append((idx, item["id"], start, total))
        return idx, item["id"], "ok", 1

    monkeypatch.setattr(tlkz_main, "_process_one_item", spy)
    tlkz_main.process_dataset(
        FakeAgent(MINIMAL_TIKZ), str(dataset_path), str(tmp_path / "out"),
        start=1, end=3, max_concurrent=1,
    )

    # 0-based start, exclusive end: items s1 and s2 only.
    assert sorted(row[1] for row in seen) == ["s1", "s2"]
    assert all(row[2] == 1 and row[3] == 2 for row in seen)


# --- 4. run_baselines.sh wiring ---------------------------------------------

def _install_fake_python(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "capture.txt"
    fake = bin_dir / "python3"
    fake.write_text(
        """#!/bin/bash
set -euo pipefail
for arg in "$@"; do
  printf 'ARG=%s\\n' "$arg" >> "$CAPTURE"
done
printf -- '---\\n' >> "$CAPTURE"
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, capture


def _run_script(tmp_path: Path, env_overrides: dict[str, str]):
    bin_dir, capture = _install_fake_python(tmp_path)
    env = os.environ.copy()
    env.update(env_overrides)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CAPTURE"] = str(capture)
    env["PYTHON_BIN"] = "python3"
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    lines = capture.read_text(encoding="utf-8").splitlines() if capture.exists() else []
    return result, lines


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs /bin/bash")
def test_run_tlkz_converts_ranges_and_targets_code_tlkz_dir(tmp_path):
    dataset_path = tmp_path / "subset.json"
    dataset_path.write_text("[]", encoding="utf-8")

    result, lines = _run_script(
        tmp_path,
        {
            "DATASET": str(dataset_path),
            "MODELS": "m1",
            "ALGORITHMS": "tlkz",
            "START": "2",
            "END": "5",
            "MAX_CONCURRENT": "7",
            "EVO_EXPERIMENT_ID": "unit-exp",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "ARG=-u" in lines
    assert "ARG=baselines.programmic.tlkz.main" in lines
    # 1-based inclusive START/END -> 0-based exclusive --start/--end
    assert lines[lines.index("ARG=--start") + 1] == "ARG=1"
    assert lines[lines.index("ARG=--end") + 1] == "ARG=5"
    assert lines[lines.index("ARG=--max-concurrent") + 1] == "ARG=7"
    out_dir = lines[lines.index("ARG=--output-dir") + 1].removeprefix("ARG=")
    assert out_dir == str(
        REPO_ROOT / "experiments" / "unit-exp" / "outputs" / "baseline" / "code_tlkz" / "m1"
    )
    # Temperature parity with the other LLM baselines.
    assert "ARG=--temperature" in lines


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs /bin/bash")
def test_run_tlkz_omits_end_without_a_range(tmp_path):
    dataset_path = tmp_path / "subset.json"
    dataset_path.write_text("[]", encoding="utf-8")

    result, lines = _run_script(
        tmp_path,
        {
            "DATASET": str(dataset_path),
            "MODELS": "m1",
            "ALGORITHMS": "tlkz",
            "EVO_EXPERIMENT_ID": "unit-exp",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "ARG=--start" in lines
    assert "ARG=--end" not in lines


def test_tlkz_is_opt_in_and_no_longer_refused():
    run_baselines = SCRIPT.read_text(encoding="utf-8")

    # Still opt-in: the default algorithm list must not grow tlkz (it needs a
    # local pdflatex).
    assert 'ALGORITHMS_CSV="${ALGORITHMS:-mermaid,direct_llm}"' in run_baselines
    # The refusal guard is gone; the batch entrypoint is wired instead.
    assert "Refusing ALGORITHMS=tlkz" not in run_baselines
    assert "TiKZ has no dataset batch CLI yet" not in run_baselines
    assert '"$PYTHON_BIN" -u -m baselines.programmic.tlkz.main' in run_baselines
    assert 'code_tlkz/$model' in run_baselines


# --- 5. Real pdflatex smoke test (opt-in via environment) -------------------

@pytest.mark.skipif(not _HAS_PDFLATEX, reason="pdflatex not installed")
@pytest.mark.skipif(not _HAS_PYMUPDF, reason="PyMuPDF not installed")
def test_real_pdflatex_renders_minimal_tikz_to_png(tmp_path):
    png = tmp_path / "render.png"

    result = tikz_render.render_tikz_to_png(MINIMAL_TIKZ, str(png), timeout=180)

    assert result.success, result.diagnostics
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert png.stat().st_size > 0
