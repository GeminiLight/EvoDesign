import os

from evo_diagram.utils import env_loader


def test_stepfun_key_populates_legacy_llm_defaults(monkeypatch):
    monkeypatch.setattr(env_loader, "_loaded", True)
    monkeypatch.setenv("STEPFUN_API_KEY", "sk-stepfun-test")
    for name in ("LLM_MODEL_PROVIDER", "LLM_MODEL_NAME", "LLM_ENDPOINT_URL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    env_loader.ensure_env_loaded()

    assert os.environ["LLM_MODEL_PROVIDER"] == "openai"
    assert os.environ["LLM_MODEL_NAME"] == "step-3.7-flash"
    assert os.environ["LLM_ENDPOINT_URL"] == "https://api.stepfun.com/v1"
    assert os.environ["LLM_API_KEY"] == "sk-stepfun-test"


def test_stepfun_legacy_defaults_do_not_override_explicit_llm_settings(monkeypatch):
    monkeypatch.setattr(env_loader, "_loaded", True)
    monkeypatch.setenv("STEPFUN_API_KEY", "sk-stepfun-test")
    monkeypatch.setenv("LLM_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL_NAME", "custom-model")
    monkeypatch.setenv("LLM_ENDPOINT_URL", "https://custom.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-explicit-test")

    env_loader.ensure_env_loaded()

    assert os.environ["LLM_MODEL_NAME"] == "custom-model"
    assert os.environ["LLM_ENDPOINT_URL"] == "https://custom.example/v1"
    assert os.environ["LLM_API_KEY"] == "sk-explicit-test"


def test_stepfun_placeholder_key_does_not_populate_legacy_defaults(monkeypatch):
    monkeypatch.setattr(env_loader, "_loaded", True)
    monkeypatch.setenv("STEPFUN_API_KEY", "your_stepfun_api_key_here")
    for name in ("LLM_MODEL_PROVIDER", "LLM_MODEL_NAME", "LLM_ENDPOINT_URL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    env_loader.ensure_env_loaded()

    assert "LLM_API_KEY" not in os.environ
    assert "LLM_MODEL_NAME" not in os.environ
