from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch):
    """Default-setting assertions must not depend on a developer's .env."""
    fields = {name.lower() for name in Settings.model_fields}
    for key in list(os.environ):
        if key.lower() in fields:
            monkeypatch.delenv(key)


def _settings(**overrides) -> Settings:
    data = {
        "jwt_secret": "test-jwt-secret",
        "session_secret": "test-session-secret",
        "_env_file": None,
    }
    data.update(overrides)
    return Settings(**data)


def test_settings_defaults_to_sqlite_without_database_password():
    settings = _settings(db_password=None)

    assert settings.db_type == "sqlite"
    assert settings.database_url == "sqlite+aiosqlite:///evodiagram.db"


def test_web_quality_loop_defaults_and_paths():
    from pathlib import Path
    settings = _settings(design_memory_path="data/web-design-memory")
    assert settings.auto_refine_enabled and settings.design_memory_enabled
    assert settings.auto_refine_max_iterations == 2
    assert settings.design_memory_top_k == 2
    assert Path(settings.design_memory_path).is_absolute()
    assert Path(settings.design_memory_seed_path).is_file()
    assert settings.retain_generation_artifacts is False


@pytest.mark.parametrize("kwargs", [{"auto_refine_max_iterations": 0},
                                    {"auto_refine_max_iterations": 4},
                                    {"design_memory_top_k": 0}])
def test_quality_loop_rejects_unbounded_configuration(kwargs):
    with pytest.raises(ValidationError):
        _settings(**kwargs)


def test_settings_does_not_expose_unused_refiner_runtime_toggles():
    settings = _settings()

    assert not hasattr(settings, "enable_refiner")
    assert not hasattr(settings, "refiner_max_iterations")


def test_settings_cors_origins_list_trims_and_ignores_empty_items():
    settings = _settings(
        cors_origins=" http://localhost:5173, ,http://localhost:5175,",
    )

    assert settings.cors_origins_list == [
        "http://localhost:5173",
        "http://localhost:5175",
    ]


@pytest.mark.parametrize("db_type", ["postgres", " POSTGRES ", "postgresql"])
def test_settings_normalizes_supported_postgres_database_types(db_type):
    settings = _settings(
        db_type=db_type,
        db_host="db.example",
        db_port=6543,
        db_name="evodiagram_prod",
        db_user="evo",
        db_password="secret-password",
    )

    assert settings.db_type == "postgres"
    assert settings.database_url == (
        "postgresql+asyncpg://evo:secret-password"
        "@db.example:6543/evodiagram_prod"
    )


def test_settings_rejects_unknown_database_type():
    with pytest.raises(ValidationError) as exc_info:
        _settings(db_type="mysql")

    assert "db_type" in str(exc_info.value)


@pytest.mark.parametrize("db_password", [None, ""])
def test_settings_requires_password_for_postgres(db_password):
    with pytest.raises(ValidationError) as exc_info:
        _settings(db_type="postgres", db_password=db_password)

    assert "DB_PASSWORD is required when DB_TYPE=postgres" in str(exc_info.value)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("jwt_secret", "your-jwt-secret-here"),
        ("session_secret", "change-me-for-local-dev"),
        ("llm_api_key", "your_api_key_here"),
        ("refiner_llm_api_key", "your_refiner_key_here"),
    ],
)
def test_settings_rejects_placeholder_secrets(field_name, value):
    with pytest.raises(ValidationError) as exc_info:
        _settings(**{field_name: value})

    assert "placeholder" in str(exc_info.value)
