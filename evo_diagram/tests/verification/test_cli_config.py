"""Verifier CLI configuration tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from evo_diagram.agentic_system.verification_stage import __main__ as verifier_cli
from evo_diagram.canvas_environment.constants import VALID_CANVAS_LIBRARIES
from evo_diagram.config.settings import AppSettings


@pytest.fixture(autouse=True)
def _reset_settings_singleton(monkeypatch):
    AppSettings._instance = None
    AppSettings._override_path = None
    monkeypatch.delenv("CANVAS_LIBRARY", raising=False)
    yield
    AppSettings._instance = None
    AppSettings._override_path = None


def test_verifier_cli_canvas_arg_defaults_to_settings_resolution():
    args = verifier_cli._parse_args(["--manifest", "manifest.json", "--image", "image.png"])

    assert args.canvas_library is None


def test_resolve_canvas_library_prefers_explicit_cli_value(monkeypatch):
    monkeypatch.setenv("CANVAS_LIBRARY", "excalidraw")

    assert verifier_cli._resolve_canvas_library(" TLDraw ") == "tldraw"


def test_resolve_canvas_library_uses_settings_env_when_cli_omitted(monkeypatch):
    monkeypatch.setenv("CANVAS_LIBRARY", "tldraw")

    assert verifier_cli._resolve_canvas_library(None) == "tldraw"


def test_verifier_cli_canvas_choices_match_canvas_environment():
    parser_args = ["--manifest", "manifest.json", "--image", "image.png"]
    for canvas_library in VALID_CANVAS_LIBRARIES:
        args = verifier_cli._parse_args([
            *parser_args,
            "--canvas-library",
            canvas_library,
        ])
        assert args.canvas_library == canvas_library


def test_resolve_canvas_library_rejects_invalid_explicit_value():
    with pytest.raises(ValueError, match="Unknown canvas_library"):
        verifier_cli._resolve_canvas_library("bad-canvas")


def test_verifier_cli_returns_nonzero_for_blocking_findings(monkeypatch, tmp_path):
    class FakeWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(
                status="reported_with_findings",
                report_path=str(tmp_path / "verifier_report.json"),
                objective_summary={
                    "critical": 0,
                    "major": 1,
                    "minor": 0,
                    "info": 0,
                    "total": 1,
                },
                critique=None,
                errors=[],
                cli_exit_code=1,
            )

    monkeypatch.setattr(verifier_cli, "VerifierWorkflow", FakeWorkflow)

    exit_code = verifier_cli.main([
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--image",
        str(tmp_path / "image.png"),
        "--canvas-library",
        "excalidraw",
        "--no-critic",
    ])

    assert exit_code == 1


def test_verifier_cli_returns_zero_for_nonblocking_findings(monkeypatch, tmp_path):
    class FakeWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(
                status="reported",
                report_path=str(tmp_path / "verifier_report.json"),
                objective_summary={
                    "critical": 0,
                    "major": 0,
                    "minor": 1,
                    "info": 0,
                    "total": 1,
                },
                critique=None,
                errors=[],
                cli_exit_code=0,
            )

    monkeypatch.setattr(verifier_cli, "VerifierWorkflow", FakeWorkflow)

    exit_code = verifier_cli.main([
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--image",
        str(tmp_path / "image.png"),
        "--canvas-library",
        "excalidraw",
        "--no-critic",
    ])

    assert exit_code == 0
