from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.config import Settings, find_obsolete_backend_env_keys
from app.services import llm_client
from app.services.llm_client import (
    BackendLLMConfigurationError,
    create_backend_llm,
    resolve_backend_llm_config,
)


def _settings(**overrides):
    data = {
        "llm_api_key": None,
        "llm_endpoint_url": None,
        "llm_model_name": None,
        "llm_model_provider": "openai",
        "llm_temperature": 0.0,
        "llm_max_tokens": 16384,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_settings_do_not_expose_backend_stepfun_fallback():
    settings = Settings(
        jwt_secret="test-secret",
        session_secret="test-secret",
        _env_file=None,
    )

    assert not hasattr(settings, "allow_stepfun_backend_fallback")
    assert not hasattr(settings, "stepfun_api_key")


def test_obsolete_backend_env_keys_detect_removed_stepfun_fallback_flag():
    obsolete_keys = find_obsolete_backend_env_keys(
        {
            "allow_stepfun_backend_fallback": "true",
            "STEPFUN_API_KEY": "sk-secret",
            "LLM_API_KEY": "sk-current",
        }
    )

    assert obsolete_keys == ("ALLOW_STEPFUN_BACKEND_FALLBACK",)


def test_settings_env_files_allow_backend_env_to_override_root_env(
    tmp_path,
    monkeypatch,
):
    for key in ("JWT_SECRET", "SESSION_SECRET", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    repo_env = tmp_path / "repo.env"
    backend_env = tmp_path / "backend.env"
    repo_env.write_text(
        "\n".join(
            [
                "JWT_SECRET=root-jwt-secret",
                "SESSION_SECRET=root-session-secret",
                "LLM_API_KEY=sk-root",
            ]
        ),
        encoding="utf-8",
    )
    backend_env.write_text(
        "\n".join(
            [
                "JWT_SECRET=backend-jwt-secret",
                "SESSION_SECRET=backend-session-secret",
                "LLM_API_KEY=sk-backend",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=(repo_env, backend_env))

    assert settings.jwt_secret == "backend-jwt-secret"
    assert settings.session_secret == "backend-session-secret"
    assert settings.llm_api_key == "sk-backend"


def test_resolve_backend_llm_rejects_stepfun_only_settings():
    with pytest.raises(
        BackendLLMConfigurationError,
        match="LLM API key is missing",
    ):
        resolve_backend_llm_config(
            settings=_settings(
                stepfun_api_key="sk-stepfun-test",
                allow_stepfun_backend_fallback=True,
            ),
        )


def test_resolve_backend_llm_prefers_explicit_provider_settings():
    config = resolve_backend_llm_config(
        settings=_settings(
            llm_api_key="sk-explicit-test",
            llm_endpoint_url="https://custom.example/v1",
            llm_model_name="custom-model",
            llm_model_provider="openai",
        ),
        temperature=0.2,
        max_tokens=4096,
    )

    assert config.api_key == "sk-explicit-test"
    assert config.base_url == "https://custom.example/v1"
    assert config.model == "custom-model"
    assert config.temperature == 0.2
    assert config.max_tokens == 4096


def test_backend_llm_config_factory_kwargs_include_only_provider_inputs():
    config = resolve_backend_llm_config(
        settings=_settings(llm_api_key="sk-explicit-test"),
    )

    kwargs = config.as_factory_kwargs()

    assert "source" not in kwargs
    assert kwargs["api_key"] == "sk-explicit-test"


def test_resolve_backend_llm_requires_a_configured_api_key():
    with pytest.raises(
        BackendLLMConfigurationError,
        match="LLM API key is missing",
    ):
        resolve_backend_llm_config(settings=_settings())


def test_create_backend_llm_prepares_engine_imports_lazily(monkeypatch):
    ensure_calls = []
    create_calls = []

    class FakeLLMFactory:
        @staticmethod
        def create(**kwargs):
            create_calls.append(kwargs)
            return "fake-model"

    core_module = ModuleType("evo_diagram.core")
    factory_module = ModuleType("evo_diagram.core.llm_factory")
    factory_module.LLMFactory = FakeLLMFactory

    monkeypatch.setitem(sys.modules, "evo_diagram.core", core_module)
    monkeypatch.setitem(sys.modules, "evo_diagram.core.llm_factory", factory_module)
    monkeypatch.setattr(
        llm_client,
        "ensure_evo_diagram_importable",
        lambda: ensure_calls.append(True),
    )

    model = create_backend_llm(settings=_settings(llm_api_key="sk-test"))

    assert model == "fake-model"
    assert ensure_calls == [True]
    assert create_calls[0]["api_key"] == "sk-test"


def test_create_backend_llm_missing_api_key_fails_before_engine_import(monkeypatch):
    ensure_calls = []
    monkeypatch.setattr(
        llm_client,
        "ensure_evo_diagram_importable",
        lambda: ensure_calls.append(True),
    )

    with pytest.raises(
        BackendLLMConfigurationError,
        match="LLM API key is missing",
    ):
        create_backend_llm(settings=_settings())

    assert ensure_calls == []


def test_reasoning_effort_is_only_sent_when_configured():
    config = resolve_backend_llm_config(settings=_settings(llm_api_key='sk-test'))
    assert 'reasoning_effort' not in config.as_factory_kwargs()
    config = resolve_backend_llm_config(settings=_settings(llm_api_key='sk-test', llm_reasoning_effort='low'))
    assert config.as_factory_kwargs()['reasoning_effort'] == 'low'
