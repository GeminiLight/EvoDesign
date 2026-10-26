"""LLMFactory config-dict entry points."""

from __future__ import annotations

import pytest

from evo_diagram.core.llm_factory import LLMFactory


@pytest.fixture
def captured_create(monkeypatch):
    calls = {}

    def fake_create(**kwargs):
        calls.update(kwargs)
        return "llm"

    monkeypatch.setattr(LLMFactory, "create", staticmethod(fake_create))
    return calls


def test_from_config_accepts_model_loader_key_names(captured_create):
    """``ModelConfig`` emits model/model_provider, not model_name/provider."""
    assert LLMFactory.from_config(
        {
            "model": "step-3.7-flash",
            "model_provider": "openai",
            "base_url": "https://api.stepfun.com/v1",
            "api_key": "sk-test",
            "temperature": 0.2,
        }
    ) == "llm"

    assert captured_create == {
        "model": "step-3.7-flash",
        "model_provider": "openai",
        "base_url": "https://api.stepfun.com/v1",
        "api_key": "sk-test",
        "temperature": 0.2,
    }


def test_from_config_still_accepts_legacy_key_names(captured_create):
    LLMFactory.from_config({"model_name": "gpt-x", "provider": "openai"})

    assert captured_create["model"] == "gpt-x"
    assert captured_create["model_provider"] == "openai"
    assert "model_name" not in captured_create
    assert "provider" not in captured_create


def test_from_config_does_not_forward_duplicate_aliases(captured_create):
    LLMFactory.from_config(
        {
            "model": "primary",
            "model_name": "legacy",
            "model_provider": "openai",
            "provider": "anthropic",
        }
    )

    assert captured_create["model"] == "primary"
    assert captured_create["model_provider"] == "openai"
    assert "model_name" not in captured_create
    assert "provider" not in captured_create


def test_from_config_rejects_unsupported_config_types():
    with pytest.raises(ValueError, match="Unsupported config type"):
        LLMFactory.from_config(object())
