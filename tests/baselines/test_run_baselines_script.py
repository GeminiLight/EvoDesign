"""scripts/run_baselines.sh argument and environment contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_baselines.sh"


def _install_fake_python(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in interpreter that records its argv and the model env var."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "capture.txt"
    fake = bin_dir / "python3"
    fake.write_text(
        """#!/bin/bash
set -euo pipefail
printf 'ELYSIVER_MODEL=%s\\n' "${ELYSIVER_MODEL:-<unset>}" >> "$CAPTURE"
for arg in "$@"; do
  printf 'ARG=%s\\n' "$arg" >> "$CAPTURE"
done
printf -- '---\\n' >> "$CAPTURE"
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, capture


def _run(tmp_path: Path, env_overrides: dict[str, str]):
    bin_dir, capture = _install_fake_python(tmp_path)
    env = os.environ.copy()
    env.update(env_overrides)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CAPTURE"] = str(capture)
    env["PYTHON_BIN"] = "python3"

    # /bin/bash is 3.2 on macOS, where "${arr[@]}" on an empty array is an
    # unbound variable under `set -u`; run it explicitly so the guard is tested.
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
def test_direct_llm_runs_without_start_end(tmp_path):
    result, lines = _run(tmp_path, {"ALGORITHMS": "direct_llm", "MODELS": "m1"})

    assert "unbound variable" not in result.stderr
    assert result.returncode == 0, result.stderr
    assert "ARG=--limit" not in lines
    assert "ARG=--dataset" in lines


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs /bin/bash")
def test_direct_llm_passes_limit_when_a_range_is_requested(tmp_path):
    result, lines = _run(
        tmp_path, {"ALGORITHMS": "direct_llm", "MODELS": "m1", "START": "3", "END": "7"}
    )

    assert result.returncode == 0, result.stderr
    assert "ARG=--limit" in lines
    assert lines[lines.index("ARG=--limit") + 1] == "ARG=5"


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs /bin/bash")
def test_diagramagent_receives_the_model_environment_variable(tmp_path):
    result, lines = _run(tmp_path, {"ALGORITHMS": "diagramagent", "MODELS": "glm-4.7"})

    assert result.returncode == 0, result.stderr
    # --eval-model-name only names the output directory; the agents read the
    # model from ELYSIVER_MODEL.
    assert "ELYSIVER_MODEL=glm-4.7" in lines


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs /bin/bash")
def test_scisketch_receives_the_model_environment_variable(tmp_path):
    result, lines = _run(tmp_path, {"ALGORITHMS": "scisketch", "MODELS": "glm-4.7"})

    assert result.returncode == 0, result.stderr
    assert "ELYSIVER_MODEL=glm-4.7" in lines


def _configured_generator_temperature() -> str:
    """The temperature EvoDiagram's generator role decodes at, from configs."""
    import yaml

    settings = yaml.safe_load(
        (REPO_ROOT / "configs" / "settings.yaml").read_text(encoding="utf-8")
    )
    models = yaml.safe_load(
        (REPO_ROOT / "configs" / "models.yaml").read_text(encoding="utf-8")
    )
    model_name = settings["roles"]["generator"]
    return str(models["models"][model_name]["temperature"])


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs /bin/bash")
@pytest.mark.parametrize("algo", ["mermaid", "direct_llm"])
def test_llm_baselines_decode_at_the_evodiagram_temperature(tmp_path, algo):
    # A repository .env LLM_TEMPERATURE would otherwise win and leave the
    # baseline decoding at a different temperature than EvoDiagram. The
    # expected value tracks configs/models.yaml rather than being hardcoded:
    # kimi k3 only accepts temperature=1, so pinning baselines to 0 would
    # itself be the fairness bug whenever that model is the generator.
    expected = _configured_generator_temperature()
    result, lines = _run(tmp_path, {"ALGORITHMS": algo, "MODELS": "m1"})

    assert result.returncode == 0, result.stderr
    assert "ARG=--temperature" in lines
    assert lines[lines.index("ARG=--temperature") + 1] == f"ARG={expected}"
