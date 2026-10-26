"""Experiment directory resolution must stay inside the repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from evo_diagram.core import experiment as experiment_module


def test_experiment_root_stays_under_repository(monkeypatch):
    monkeypatch.setenv("EVO_EXPERIMENT_ID", "exp-1")

    root = experiment_module.get_experiment_root()

    assert root == experiment_module.get_project_root() / "experiments" / "exp-1"


def test_env_experiment_id_cannot_escape_experiments_dir(monkeypatch):
    monkeypatch.setenv("EVO_EXPERIMENT_ID", "../../tmp/x")

    with pytest.raises(ValueError, match="EVO_EXPERIMENT_ID"):
        experiment_module.get_experiment_id()

    with pytest.raises(ValueError, match="experiment id"):
        experiment_module.get_experiment_root()


def test_settings_experiment_id_is_validated(monkeypatch):
    monkeypatch.delenv("EVO_EXPERIMENT_ID", raising=False)
    monkeypatch.setattr(
        experiment_module,
        "_get_config_experiment_id",
        lambda: "../escape",
    )

    with pytest.raises(ValueError, match="settings.yaml experiment.id"):
        experiment_module.get_experiment_id()


def test_explicit_experiment_id_argument_is_validated():
    with pytest.raises(ValueError, match="path segment"):
        experiment_module.get_experiment_root("../../tmp/x")


def test_unsafe_experiment_id_does_not_create_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(experiment_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("EVO_EXPERIMENT_ID", "../outside")

    with pytest.raises(ValueError):
        experiment_module.ensure_experiment_dirs()

    assert not (tmp_path.parent / "outside").exists()


def test_output_dirs_are_derived_from_the_validated_root(monkeypatch, tmp_path):
    monkeypatch.setattr(experiment_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("EVO_EXPERIMENT_ID", "exp-2")

    evodiagram_dir = experiment_module.get_evodiagram_output_dir("evodiagram", "model_a")

    assert Path(evodiagram_dir) == (
        tmp_path / "experiments" / "exp-2" / "outputs" / "evodiagram" / "evodiagram" / "model_a"
    )
