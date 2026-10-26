"""TiKZ compile/render helpers for the tlkz baseline.

Pipeline: LLM response -> fence-stripped TikZ code -> standalone LaTeX
document -> pdflatex (temp dir, nonstopmode) -> PyMuPDF PDF->PNG.

Two lessons are carried over from baselines/diagramagent:

* ``CodeAgent._extract_code_block``: the fenced-block regex must return the
  *capture group*; feeding ``group(0)`` (backticks included) to pdflatex fails
  on line 1.
* ``CheckAgent._latex_diagnostics``: with ``-interaction=nonstopmode``
  pdflatex reports errors on **stdout** and leaves stderr empty, so stdout is
  the primary diagnostics source.

Rendering resolution matches the diagramagent baseline, which converts PDFs
with ``pdftoppm -png -r 150``. This machine has no pdftoppm, so PyMuPDF
reproduces the same 150 DPI output (zoom = dpi / 72).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional, Union

# Same resolution as diagramagent CheckAgent's `pdftoppm -png -r 150`.
DEFAULT_DPI = 150
DEFAULT_TIMEOUT = 120

# Optional language tag (latex/tikz, any capitalisation), optional spaces,
# then a newline; the body lands in group(1) so fences never reach pdflatex.
_FENCED_CODE_RE = re.compile(
    r"```[ \t]*(?:[Ll][Aa][Tt][Ee][Xx]|[Tt][Ii][Kk][Zz])?[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)
_FULL_DOCUMENT_RE = re.compile(r"\\documentclass.*?\\end{document}", re.DOTALL)


def extract_tikz_code(text: str) -> str:
    """Strip markdown fences / prose from an LLM response, returning raw TikZ.

    Order mirrors ``baselines/diagramagent/CodeAgent.py::_extract_code_block``:
    fenced block (capture group!), then a complete ``\\documentclass``
    document, then the stripped text as a last resort. An unclosed fence
    (truncated response) is handled defensively instead of being handed to
    pdflatex.
    """
    if not text:
        return ""

    match = _FENCED_CODE_RE.search(text)
    if match:
        return match.group(1).strip()

    match = _FULL_DOCUMENT_RE.search(text)
    if match:
        return match.group(0).strip()

    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        body = stripped[first_nl + 1:] if first_nl != -1 else ""
        body = body.rstrip()
        if body.endswith("```"):
            body = body[:-3]
        return body.strip()
    return stripped


def wrap_standalone_document(code: str) -> str:
    """Wrap bare TikZ in a compilable standalone document.

    Preamble is identical to diagramagent ``CheckAgent._ensure_tikz_document``
    so both baselines compile under the same conditions. A response that is
    already a full document is passed through unchanged.
    """
    s = (code or "").strip()
    if not s:
        return s
    if "\\documentclass" in s:
        return s

    has_tikzpicture = "\\begin{tikzpicture}" in s
    body = s if has_tikzpicture else f"\\begin{{tikzpicture}}\n{s}\n\\end{{tikzpicture}}"
    return (
        "\\documentclass[tikz,border=2pt]{standalone}\n"
        "\\usepackage{tikz}\n"
        "\\usetikzlibrary{arrows.meta,positioning,shapes.geometric,calc}\n"
        "\\begin{document}\n"
        f"{body}\n"
        "\\end{document}\n"
    )


def latex_diagnostics(stdout: str, stderr: str, max_chars: int = 4000) -> str:
    """Collect pdflatex diagnostics, stdout first (nonstopmode writes there)."""
    lines = (stdout or "").splitlines()
    picked: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("!") or line.startswith("l.") or "Error" in line:
            picked.extend(lines[i:i + 3])
    text = "\n".join(picked) if picked else "\n".join(lines[-40:])
    if stderr and stderr.strip():
        text = f"{text}\n{stderr.strip()}"
    return text[:max_chars]


@dataclass
class CompileResult:
    success: bool
    pdf_path: Optional[str] = None
    diagnostics: str = ""
    returncode: Optional[int] = None


@dataclass
class RenderResult:
    success: bool
    png_path: Optional[str] = None
    diagnostics: str = ""


def _run_pdflatex(tex_path: str, workdir: str, timeout: int) -> subprocess.CompletedProcess:
    """Single pdflatex pass; separate function so tests can monkeypatch it."""
    return subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-output-directory", workdir, tex_path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def compile_latex(source: str, workdir: Union[str, "os.PathLike[str]"], timeout: int = DEFAULT_TIMEOUT) -> CompileResult:
    """Write *source* to ``workdir/diagram.tex`` and compile it with pdflatex.

    Success requires both a zero exit code and ``diagram.pdf`` on disk, the
    same rule diagramagent CheckAgent applies. Missing pdflatex and timeouts
    are reported as diagnostics instead of raising, so batch workers can
    record per-sample failures.
    """
    workdir = os.fspath(workdir)
    os.makedirs(workdir, exist_ok=True)
    tex_path = os.path.join(workdir, "diagram.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(source)

    try:
        proc = _run_pdflatex(tex_path, workdir, timeout)
    except FileNotFoundError:
        return CompileResult(
            success=False,
            diagnostics="pdflatex not found on PATH; install TeX Live/MacTeX to run the tlkz baseline.",
        )
    except subprocess.TimeoutExpired:
        return CompileResult(success=False, diagnostics=f"pdflatex timed out after {timeout}s")

    pdf_path = os.path.join(workdir, "diagram.pdf")
    success = proc.returncode == 0 and os.path.exists(pdf_path)
    return CompileResult(
        success=success,
        pdf_path=pdf_path if success else None,
        diagnostics="" if success else latex_diagnostics(proc.stdout, proc.stderr),
        returncode=proc.returncode,
    )


def pdf_to_png(pdf_path: str, png_path: str, dpi: int = DEFAULT_DPI) -> None:
    """Render the first PDF page to PNG with PyMuPDF at *dpi*.

    PyMuPDF is imported lazily so ``--help`` and code-extraction tests never
    pay the import cost (and the module stays importable without it).
    """
    try:
        import pymupdf
    except ImportError:  # PyMuPDF < 1.24 exposes only the fitz alias
        import fitz as pymupdf

    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    doc = pymupdf.open(pdf_path)
    try:
        page = doc.load_page(0)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        pix.save(png_path)
    finally:
        doc.close()


def render_tikz_to_png(
    tikz_code: str,
    png_path: str,
    timeout: int = DEFAULT_TIMEOUT,
    dpi: int = DEFAULT_DPI,
) -> RenderResult:
    """Compile TikZ code and rasterise the first PDF page to *png_path*.

    Never raises for expected failure modes (bad LaTeX, missing pdflatex,
    broken PDF): the caller records the returned diagnostics as the sample
    failure reason.
    """
    source = wrap_standalone_document(tikz_code)
    if not source.strip():
        return RenderResult(success=False, diagnostics="empty_tikz_code")

    with tempfile.TemporaryDirectory(prefix="tlkz_render_") as tmpdir:
        result = compile_latex(source, tmpdir, timeout=timeout)
        if not result.success:
            return RenderResult(success=False, diagnostics=result.diagnostics)
        try:
            pdf_to_png(result.pdf_path, png_path, dpi=dpi)
        except Exception as e:  # noqa: BLE001 - any rasteriser failure is a sample failure
            return RenderResult(success=False, diagnostics=f"PDF to PNG conversion failed: {e}")
        return RenderResult(success=True, png_path=png_path)
