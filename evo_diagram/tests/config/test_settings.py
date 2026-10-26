"""AppSettings path resolution tests."""

from __future__ import annotations

import pytest
import yaml

from evo_diagram.config import settings as settings_module
from evo_diagram.config.settings import AppSettings


def test_default_path_falls_back_to_packaged_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module, "_PROJECT_ROOT", tmp_path)

    path = settings_module._default_settings_path()

    assert path.name == "settings.yaml"
    assert path.parent.name == "defaults"
    assert path.exists()


def test_path_settings_resolve_relative_to_settings_file(tmp_path):
    settings_dir = tmp_path / "config"
    settings_dir.mkdir()
    settings_path = settings_dir / "settings.yaml"
    settings_path.write_text(
        yaml.dump({
            "design_memory": {"vector_db_path": "../data/knowledge"},
            "user_preference": {"memory_path": "user_preferences"},
        }),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    assert settings.design_memory_vector_db_path == str(tmp_path / "data" / "knowledge")
    assert settings.user_preference_memory_path == str(settings_dir / "user_preferences")


def test_path_settings_keep_absolute_paths(tmp_path):
    absolute_path = tmp_path / "absolute-memory"
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({
            "design_memory": {"vector_db_path": str(absolute_path)},
            "user_preference": {"memory_path": str(absolute_path / "users")},
        }),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    assert settings.design_memory_vector_db_path == str(absolute_path)
    assert settings.user_preference_memory_path == str(absolute_path / "users")


def test_generation_mode_rejects_invalid_values(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"mode": "multi-agent"}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    with pytest.raises(ValueError, match="Unknown generation.mode"):
        _ = settings.generation_mode


@pytest.mark.parametrize("legacy_mode", ["pipeline", "unified"])
def test_generation_mode_rejects_legacy_aliases(tmp_path, legacy_mode):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"mode": legacy_mode}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    with pytest.raises(ValueError, match="Unknown generation.mode"):
        _ = settings.generation_mode


def test_generation_mode_accepts_current_modes(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"mode": " OneShot "}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    assert settings.generation_mode == "oneshot"


def test_boolean_settings_reject_invalid_values(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"enable_refiner": "maybe"}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    with pytest.raises(ValueError, match="Invalid boolean setting"):
        _ = settings.generation_enable_refiner


def test_structure_self_consistency_n_rejects_non_integer(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"structure_self_consistency_n": "many"}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    with pytest.raises(ValueError, match="structure_self_consistency_n"):
        _ = settings.structure_self_consistency_n


def test_structure_self_consistency_n_rejects_less_than_one(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"structure_self_consistency_n": 0}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    with pytest.raises(ValueError, match="integer >= 1"):
        _ = settings.structure_self_consistency_n


def test_structure_self_consistency_n_rejects_too_large(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"structure_self_consistency_n": 10}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    with pytest.raises(ValueError, match="between 1 and 9"):
        _ = settings.structure_self_consistency_n


def test_structure_self_consistency_n_accepts_positive_integer(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"structure_self_consistency_n": "3"}}),
        encoding="utf-8",
    )

    settings = AppSettings(settings_path)

    assert settings.structure_self_consistency_n == 3


def test_empty_env_override_falls_back_to_yaml(tmp_path, monkeypatch):
    """`USE_ICONS=` in .env must not crash startup with 'invalid boolean'."""
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"use_icons": True, "enable_refiner": False}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("USE_ICONS", "")
    monkeypatch.setenv("ENABLE_REFINER", "   ")

    settings = AppSettings(settings_path)

    assert settings.generation_use_icons is True
    assert settings.generation_enable_refiner is False


def test_empty_env_override_does_not_blank_url_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"services": {"render_url": "http://localhost:3000"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RENDER_SERVICE_URL", "")

    settings = AppSettings(settings_path)

    assert settings.render_service_url == "http://localhost:3000"


def test_non_empty_env_override_still_wins(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"services": {"render_url": "http://localhost:3000"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RENDER_SERVICE_URL", "http://renderer:4000")

    settings = AppSettings(settings_path)

    assert settings.render_service_url == "http://renderer:4000"


def test_empty_env_override_is_logged(tmp_path, monkeypatch, caplog):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.dump({"generation": {"use_icons": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("USE_ICONS", "")

    settings = AppSettings(settings_path)
    with caplog.at_level("WARNING", logger=settings_module.logger.name):
        assert settings.generation_use_icons is True

    assert "USE_ICONS" in caplog.text
