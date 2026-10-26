from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_evaluation_imports_do_not_inject_real_repo_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    package_root = tmp_path / "packages"
    package_root.mkdir()

    for package_name in ("evaluation", "evo_diagram"):
        target = repo_root / package_name
        link = package_root / package_name
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink setup unavailable: {exc}")

    script = """
import importlib
import os
import sys

repo_root = os.environ["REPO_ROOT"]
assert repo_root not in sys.path
for module_name in (
    "evaluation.path_resolver",
    "evaluation.metric_scorer",
    "evaluation.run_evaluation",
):
    importlib.import_module(module_name)
assert repo_root not in sys.path, sys.path
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_root)
    env["REPO_ROOT"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_path_resolver_import_does_not_load_llm_frameworks(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import sys

import evaluation.path_resolver

loaded = [
    name for name in sys.modules
    if name.startswith(("langchain", "langgraph"))
]
assert loaded == [], loaded[:20]
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
