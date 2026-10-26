"""
Experiment directory management.

Provides centralized path resolution for the experiments/ directory layout:

    experiments/{exp_id}/
        outputs/
            baseline/{algo}/{model}/{sample_id}/render.png
            evodiagram/{variant}/{model}/{sample_id}/rendered_diagram.png
        scores/
            baseline/{algo}/{model}/{sample_id}.json
            evodiagram/{variant}/{model}/{sample_id}.json

Configuration priority (highest first):
    1. Environment variable EVO_EXPERIMENT_ID
    2. settings.yaml -> experiment.id
       - If id is "exp" or empty, fall back to auto-generated date
    3. Auto-generated date (YYYY-MM-DD)
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from evo_diagram.utils.path_manager import safe_join_under, safe_path_segment

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_project_root() -> Path:
    """Return the repository root path."""
    return _PROJECT_ROOT


def _validated_experiment_id(value: str, *, source: str) -> str:
    """Reject experiment ids that would escape or reshape ``experiments/``."""
    try:
        return safe_path_segment(value, field_name="experiment id")
    except ValueError as exc:
        raise ValueError(f"Invalid experiment id from {source}: {exc}") from exc


def get_experiment_id() -> str:
    """Resolve the current experiment ID.

    Priority:
        1. EVO_EXPERIMENT_ID env var
        2. settings.yaml -> experiment.id (if set and != 'exp')
        3. Auto-generated date string YYYY-MM-DD
    """
    # 1. Environment variable
    env_id = os.getenv("EVO_EXPERIMENT_ID", "").strip()
    if env_id:
        return _validated_experiment_id(env_id, source="EVO_EXPERIMENT_ID")

    # 2. Config file
    config_id = _get_config_experiment_id()
    if config_id and config_id.lower() != "exp":
        return _validated_experiment_id(config_id, source="settings.yaml experiment.id")

    # 3. Default date
    return datetime.now().strftime("%Y-%m-%d")


def _get_config_experiment_id() -> Optional[str]:
    """Read experiment.id from settings.yaml if available."""
    try:
        from evo_diagram.config.settings import AppSettings

        settings = AppSettings.get_default()
        val = settings.get_raw("experiment.id", "")
        if val and str(val).strip():
            return str(val).strip()
    except Exception:
        pass
    return None


def get_experiment_root(exp_id: Optional[str] = None) -> Path:
    """Return the experiment root directory.

    ``exp_id`` is joined safely so a caller-supplied or environment-supplied id
    can never place the experiment tree outside ``<repo>/experiments``.
    """
    eid = exp_id or get_experiment_id()
    return safe_join_under(_PROJECT_ROOT / "experiments", eid)


# ═══════════════════════════════════════════════════════════════════════
#  Output paths (algorithm-generated artifacts)
# ═══════════════════════════════════════════════════════════════════════

def get_baseline_output_dir(
    algo: str, model: str, exp_id: Optional[str] = None
) -> Path:
    """Path for baseline algorithm outputs: experiments/{exp}/outputs/baseline/{algo}/{model}/"""
    return get_experiment_root(exp_id) / "outputs" / "baseline" / algo / model


def get_evodiagram_output_dir(
    variant: str, model: str, exp_id: Optional[str] = None
) -> Path:
    """Path for EvoDiagram outputs: experiments/{exp}/outputs/evodiagram/{variant}/{model}/"""
    return get_experiment_root(exp_id) / "outputs" / "evodiagram" / variant / model


# ═══════════════════════════════════════════════════════════════════════
#  Score paths (evaluation results)
# ═══════════════════════════════════════════════════════════════════════

def get_baseline_score_dir(
    algo: str, model: str, exp_id: Optional[str] = None
) -> Path:
    """Path for baseline evaluation scores: experiments/{exp}/scores/baseline/{algo}/{model}/"""
    return get_experiment_root(exp_id) / "scores" / "baseline" / algo / model


def get_evodiagram_score_dir(
    variant: str, model: str, exp_id: Optional[str] = None
) -> Path:
    """Path for EvoDiagram evaluation scores: experiments/{exp}/scores/evodiagram/{variant}/{model}/"""
    return get_experiment_root(exp_id) / "scores" / "evodiagram" / variant / model


# ═══════════════════════════════════════════════════════════════════════
#  Convenience helpers
# ═══════════════════════════════════════════════════════════════════════

def ensure_experiment_dirs(exp_id: Optional[str] = None) -> Dict[str, Path]:
    """Create all experiment subdirectories and return them."""
    root = get_experiment_root(exp_id)
    dirs = {
        "root": root,
        "outputs_baseline": root / "outputs" / "baseline",
        "outputs_evodiagram": root / "outputs" / "evodiagram",
        "scores_baseline": root / "scores" / "baseline",
        "scores_evodiagram": root / "scores" / "evodiagram",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs
