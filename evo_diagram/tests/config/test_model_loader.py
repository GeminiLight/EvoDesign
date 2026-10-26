"""ModelConfig unit tests.

Run:  python -m pytest tests/config/ -v
"""

import pytest
import yaml

from evo_diagram.config import model_loader
from evo_diagram.config.model_loader import ModelConfig, _DEFAULT_PATH
from evo_diagram.config.settings import AppSettings
from evo_diagram.core.llm_factory import LLMFactory


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset ModelConfig and AppSettings singletons between tests."""
    ModelConfig._instance = None
    AppSettings._instance = None
    yield
    ModelConfig._instance = None
    AppSettings._instance = None


def _make_settings(tmp_path, roles):
    """Create a settings.yaml with roles and initialize AppSettings."""
    data = {"roles": roles}
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.dump(data))
    AppSettings.init(p)
    return p


class TestModelConfig:

    def test_load_default_config(self):
        cfg = ModelConfig(_DEFAULT_PATH)
        assert _DEFAULT_PATH.name == "models.yaml"
        assert _DEFAULT_PATH.parent.name == "configs"
        assert cfg.list_roles()
        assert cfg.list_models()
        assert cfg.list_providers()

    def test_default_path_falls_back_to_packaged_models(self, monkeypatch, tmp_path):
        monkeypatch.setattr(model_loader, "_PROJECT_ROOT", tmp_path)

        path = model_loader._default_models_path()

        assert path.name == "models.yaml"
        assert path.parent.name == "defaults"
        assert path.exists()

    def test_default_generator_role_uses_custom_endpoint(self, monkeypatch):
        # The repo default routes all roles through the `custom` provider,
        # whose base_url/api_key come from LLM_ENDPOINT_URL / LLM_API_KEY in
        # the repository-root .env. The previous default was StepFun.
        monkeypatch.setenv("LLM_MODEL_NAME", "test-vision-model")
        monkeypatch.setenv("LLM_ENDPOINT_URL", "https://api.custom.example/v1")
        monkeypatch.setenv("LLM_API_KEY", "sk-custom-test")

        cfg = ModelConfig(_DEFAULT_PATH)
        params = cfg.get_model_config("generator")

        assert cfg.list_roles()["generator"] == "configured-model"
        assert params["model_provider"] == "openai"
        assert params["model"] == "test-vision-model"
        assert params["base_url"] == "https://api.custom.example/v1"
        assert params["api_key"] == "sk-custom-test"
        assert params["max_tokens"] == 16384

    def test_default_llm_roles_use_custom_endpoint_model(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL_NAME", "test-vision-model")
        monkeypatch.setenv("LLM_ENDPOINT_URL", "https://api.custom.example/v1")
        monkeypatch.setenv("LLM_API_KEY", "sk-custom-test")

        cfg = ModelConfig(_DEFAULT_PATH)

        for role in ("default", "fast", "eval", "generator", "refiner", "verifier", "distiller", "router"):
            params = cfg.get_model_config(role)
            assert cfg.list_roles()[role] == "configured-model"
            assert params["model_provider"] == "openai"
            assert params["model"] == "test-vision-model"
            assert params["base_url"] == "https://api.custom.example/v1"
            assert params["api_key"] == "sk-custom-test"

    def test_default_vlm_roles_declare_vision_capability(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL_NAME", "test-vision-model")
        monkeypatch.setenv("LLM_API_KEY", "sk-custom-test")

        cfg = ModelConfig(_DEFAULT_PATH)

        assert "vision" in cfg.get_model_capabilities("verifier")
        assert "vision" in cfg.get_model_capabilities("refiner")
        assert "capabilities" not in cfg.get_model_config("verifier")

    def test_model_capability_requirements_fail_fast(self, tmp_path):
        models_data = {
            "providers": {
                "test_provider": {
                    "base_url": "https://test.example.com/v1",
                    "api_key": "sk-test-key",
                },
            },
            "models": {
                "text-only": {
                    "provider": "test_provider",
                    "model_name": "text-only",
                },
                "vision-model": {
                    "provider": "test_provider",
                    "model_name": "vision-model",
                    "capabilities": ["text", "vision"],
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"verifier": "text-only", "refiner": "vision-model"})

        cfg = ModelConfig(p)

        assert cfg.get_model_capabilities("verifier") == {"text"}
        with pytest.raises(ValueError, match="lacks required.*vision"):
            cfg.require_model_capabilities("verifier", {"vision"})
        cfg.require_model_capabilities("refiner", {"vision"})

    def test_load_sample_config(self, tmp_path):
        models_data = {
            "providers": {
                "test_provider": {
                    "base_url": "https://test.example.com/v1",
                    "api_key": "sk-test-key",
                },
            },
            "models": {
                "test-model": {
                    "provider": "test_provider",
                    "model_name": "gpt-test",
                    "temperature": 0.5,
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"main": "test-model"})

        cfg = ModelConfig(p)
        assert "main" in cfg.list_roles()
        assert "test-model" in cfg.list_models()

    def test_get_model_config_resolves_chain(self, tmp_path):
        models_data = {
            "providers": {
                "test_provider": {
                    "base_url": "https://test.example.com/v1",
                    "api_key": "sk-test-key",
                },
            },
            "models": {
                "test-model": {
                    "provider": "test_provider",
                    "model_name": "gpt-test",
                    "temperature": 0.5,
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"main": "test-model"})

        cfg = ModelConfig(p)
        params = cfg.get_model_config("main")
        assert params["model"] == "gpt-test"
        assert params["model_provider"] == "test_provider"
        assert params["base_url"] == "https://test.example.com/v1"
        assert params["api_key"] == "sk-test-key"
        assert params["temperature"] == 0.5

    def test_get_named_model_config_resolves_alias_provider(self, tmp_path):
        models_data = {
            "providers": {
                "stepfun": {
                    "provider": "openai",
                    "base_url": "https://api.stepfun.com/v1",
                    "api_key": "sk-stepfun",
                },
                "openai_official": {
                    "provider": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-openai",
                },
            },
            "models": {
                "step-3.7-flash": {
                    "provider": "stepfun",
                    "model_name": "step-3.7-flash",
                },
                "gpt-5.5": {
                    "provider": "openai_official",
                    "model_name": "gpt-5.5",
                    "temperature": 0.1,
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"generator": "step-3.7-flash"})

        cfg = ModelConfig(p)
        params = cfg.get_named_model_config("gpt-5.5", max_tokens=1024)

        assert cfg.has_model("gpt-5.5") is True
        assert cfg.has_model("unlisted-raw-model") is False
        assert params["model"] == "gpt-5.5"
        assert params["model_provider"] == "openai"
        assert params["base_url"] == "https://api.openai.com/v1"
        assert params["api_key"] == "sk-openai"
        assert params["temperature"] == 0.1
        assert params["max_tokens"] == 1024

        raw_override = cfg.get_model_config("generator", model="gpt-5.5")
        assert raw_override["model"] == "gpt-5.5"
        assert raw_override["base_url"] == "https://api.stepfun.com/v1"

    def test_overrides_take_precedence(self, tmp_path):
        models_data = {
            "providers": {
                "test_provider": {
                    "base_url": "https://test.example.com/v1",
                    "api_key": "sk-test-key",
                },
            },
            "models": {
                "test-model": {
                    "provider": "test_provider",
                    "model_name": "gpt-test",
                    "temperature": 0.5,
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"main": "test-model"})

        cfg = ModelConfig(p)
        params = cfg.get_model_config("main", temperature=0.9, max_tokens=1024)
        assert params["temperature"] == 0.9
        assert params["max_tokens"] == 1024

    def test_missing_role_raises(self, tmp_path):
        models_data = {
            "providers": {
                "test_provider": {"base_url": "https://test.example.com/v1", "api_key": "sk-test-key"},
            },
            "models": {
                "test-model": {"provider": "test_provider", "model_name": "gpt-test"},
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"main": "test-model"})

        cfg = ModelConfig(p)
        with pytest.raises(KeyError, match="Role.*not found"):
            cfg.get_model_config("nonexistent")

    def test_missing_model_raises(self, tmp_path):
        data = {
            "providers": {"p": {"base_url": "https://x.com"}},
            "models": {},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "nonexistent-model"})

        cfg = ModelConfig(p)
        with pytest.raises(KeyError, match="Model.*not found"):
            cfg.get_model_config("main")

    def test_missing_provider_raises(self, tmp_path):
        data = {
            "providers": {},
            "models": {"m": {"provider": "missing", "model_name": "x"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})

        cfg = ModelConfig(p)
        with pytest.raises(KeyError, match="Provider.*not found"):
            cfg.get_model_config("main")

    def test_api_key_does_not_use_global_llm_fallback(self, tmp_path, monkeypatch):
        data = {
            "providers": {"myp": {"base_url": "https://x.com"}},
            "models": {"m": {"provider": "myp", "model_name": "x"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})
        monkeypatch.setenv("LLM_API_KEY", "fallback-key")

        cfg = ModelConfig(p)
        params = cfg.get_model_config("main")
        assert params["api_key"] is None

    def test_api_key_requires_explicit_provider_config(self, tmp_path, monkeypatch):
        data = {
            "providers": {"myp": {"base_url": "https://x.com"}},
            "models": {"m": {"provider": "myp", "model_name": "x"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})
        monkeypatch.setenv("MYP_API_KEY", "provider-specific-key")

        cfg = ModelConfig(p)
        params = cfg.get_model_config("main")
        assert params["api_key"] is None

    def test_api_key_placeholder_is_rejected(self, tmp_path, monkeypatch):
        data = {
            "providers": {"myp": {"base_url": "https://x.com", "api_key": "$MYP_API_KEY"}},
            "models": {"m": {"provider": "myp", "model_name": "x"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})
        monkeypatch.setenv("MYP_API_KEY", "your_api_key_here")

        cfg = ModelConfig(p)
        with pytest.raises(ValueError, match="placeholder"):
            cfg.get_model_config("main")

    def test_api_key_placeholder_error_names_provider_and_env_reference(
        self,
        tmp_path,
        monkeypatch,
    ):
        data = {
            "providers": {
                "stepfun": {
                    "base_url": "https://api.stepfun.com/v1",
                    "api_key": "$STEPFUN_API_KEY",
                },
            },
            "models": {"m": {"provider": "stepfun", "model_name": "x"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})
        monkeypatch.setenv("STEPFUN_API_KEY", "your_api_key_here")

        cfg = ModelConfig(p)
        with pytest.raises(ValueError) as excinfo:
            cfg.get_model_config("main")

        message = str(excinfo.value)
        assert "stepfun" in message
        assert "STEPFUN_API_KEY" in message
        assert "$STEPFUN_API_KEY" in message
        # Tell the user what to do when the key is real but trips the heuristic.
        assert "placeholder heuristic" in message

    def test_api_key_placeholder_error_does_not_leak_the_resolved_secret(
        self,
        tmp_path,
        monkeypatch,
    ):
        data = {
            "providers": {"myp": {"base_url": "https://x.com", "api_key": "$MYP_API_KEY"}},
            "models": {"m": {"provider": "myp", "model_name": "x"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})
        monkeypatch.setenv("MYP_API_KEY", "sk-live-secret_here")

        cfg = ModelConfig(p)
        with pytest.raises(ValueError) as excinfo:
            cfg.get_model_config("main")

        assert "sk-live-secret_here" not in str(excinfo.value)

    def test_provider_protocol_mapping(self, tmp_path):
        data = {
            "providers": {
                "custom_openai": {
                    "provider": "openai",
                    "base_url": "https://test.example.com/v1",
                    "api_key": "sk-test-key",
                },
            },
            "models": {
                "m": {"provider": "custom_openai", "model_name": "gpt-test"},
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})

        cfg = ModelConfig(p)
        params = cfg.get_model_config("main")
        assert params["model_provider"] == "openai"

    def test_provider_protocol_falls_back_to_provider_name(self, tmp_path):
        data = {
            "providers": {
                "my_llm": {
                    "base_url": "https://example.com/v1",
                    "api_key": "sk-test-key",
                },
            },
            "models": {
                "m": {"provider": "my_llm", "model_name": "gpt-test"},
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "m"})

        cfg = ModelConfig(p)
        params = cfg.get_model_config("main")
        assert params["model_provider"] == "my_llm"

    def test_role_config_ignores_legacy_role_env_overrides(self, tmp_path, monkeypatch):
        data = {
            "providers": {
                "declared": {
                    "provider": "openai",
                    "base_url": "https://declared.example/v1",
                    "api_key": "sk-declared",
                },
                "env_provider": {
                    "provider": "openai",
                    "base_url": "https://env.example/v1",
                    "api_key": "sk-env",
                },
            },
            "models": {
                "declared-model": {
                    "provider": "declared",
                    "model_name": "declared-model",
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(data))
        _make_settings(tmp_path, {"main": "declared-model"})
        monkeypatch.setenv("EVO_MAIN_MODEL_NAME", "env-model")
        monkeypatch.setenv("EVO_MAIN_PROVIDER", "env_provider")

        cfg = ModelConfig(p)
        params = cfg.get_model_config("main")

        assert params["model"] == "declared-model"
        assert params["base_url"] == "https://declared.example/v1"
        assert params["api_key"] == "sk-declared"

    def test_file_not_found_raises(self, tmp_path):
        _make_settings(tmp_path, {"main": "m"})
        with pytest.raises(FileNotFoundError):
            ModelConfig("/nonexistent/path.yaml")

    def test_list_roles(self, tmp_path):
        models_data = {
            "providers": {
                "test_provider": {"base_url": "https://test.example.com/v1", "api_key": "sk-test-key"},
            },
            "models": {
                "test-model": {"provider": "test_provider", "model_name": "gpt-test"},
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"main": "test-model"})

        cfg = ModelConfig(p)
        assert cfg.list_roles() == {"main": "test-model"}

    def test_path_property(self, tmp_path):
        models_data = {
            "providers": {"p": {"base_url": "https://x.com"}},
            "models": {"m": {"provider": "p", "model_name": "x"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"main": "m"})

        cfg = ModelConfig(p)
        assert cfg.path == p

    def test_initialize_model_uses_named_model_alias_provider(self, tmp_path, monkeypatch):
        from evo_diagram.agentic_system.config import AgenticSystemConfig
        from evo_diagram.agentic_system import main as cli_main

        models_data = {
            "providers": {
                "stepfun": {
                    "provider": "openai",
                    "base_url": "https://api.stepfun.com/v1",
                    "api_key": "sk-stepfun",
                },
                "openai_official": {
                    "provider": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-openai",
                },
            },
            "models": {
                "step-3.7-flash": {
                    "provider": "stepfun",
                    "model_name": "step-3.7-flash",
                },
                "gpt-5.5": {
                    "provider": "openai_official",
                    "model_name": "gpt-5.5",
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"generator": "step-3.7-flash"})
        ModelConfig.init(p)

        created = {}
        sentinel = object()

        def fake_create(**params):
            created["params"] = params
            return sentinel

        def fail_create_for_role(cls, role, **overrides):
            raise AssertionError("named model aliases should use LLMFactory.create")

        monkeypatch.setattr(cli_main.LLMFactory, "create", staticmethod(fake_create))
        monkeypatch.setattr(
            cli_main.LLMFactory,
            "create_for_role",
            classmethod(fail_create_for_role),
        )

        model, resolved_name = cli_main.initialize_model(
            AgenticSystemConfig(role="generator", model_override="gpt-5.5"),
        )

        assert model is sentinel
        assert resolved_name == "gpt-5.5"
        assert created["params"]["model"] == "gpt-5.5"
        assert created["params"]["base_url"] == "https://api.openai.com/v1"
        assert created["params"]["api_key"] == "sk-openai"
        assert created["params"]["max_tokens"] == 16384
        assert created["params"]["max_retries"] == 6

    def test_initialize_model_rejects_unknown_model_alias(self, tmp_path, monkeypatch):
        from evo_diagram.agentic_system.config import AgenticSystemConfig
        from evo_diagram.agentic_system import main as cli_main

        models_data = {
            "providers": {
                "stepfun": {
                    "provider": "openai",
                    "base_url": "https://api.stepfun.com/v1",
                    "api_key": "sk-stepfun",
                },
            },
            "models": {
                "step-3.7-flash": {
                    "provider": "stepfun",
                    "model_name": "step-3.7-flash",
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"generator": "step-3.7-flash"})
        ModelConfig.init(p)

        def fail_create(**params):
            raise AssertionError("unknown aliases must fail before model construction")

        def fake_create_for_role(cls, role, **overrides):
            raise AssertionError("unknown aliases must fail before role construction")

        monkeypatch.setattr(cli_main.LLMFactory, "create", staticmethod(fail_create))
        monkeypatch.setattr(
            cli_main.LLMFactory,
            "create_for_role",
            classmethod(fake_create_for_role),
        )

        with pytest.raises(ValueError, match="Unknown model alias 'unlisted-raw-model'"):
            cli_main.initialize_model(
                AgenticSystemConfig(role="generator", model_override="unlisted-raw-model"),
            )

    def test_initialize_router_model_fails_if_configured_role_fails(self, tmp_path, monkeypatch):
        from evo_diagram.agentic_system import main as cli_main

        models_data = {
            "providers": {
                "stepfun": {
                    "provider": "openai",
                    "base_url": "https://api.stepfun.com/v1",
                    "api_key": "sk-stepfun",
                },
            },
            "models": {
                "step-3.7-flash": {
                    "provider": "stepfun",
                    "model_name": "step-3.7-flash",
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"fast": "step-3.7-flash", "router": "step-3.7-flash"})
        ModelConfig.init(p)

        def fail_create_for_role(role, **overrides):
            raise ValueError(f"{role} auth failed")

        monkeypatch.setattr(
            cli_main.LLMFactory,
            "create_for_role",
            staticmethod(fail_create_for_role),
        )

        with pytest.raises(RuntimeError, match="Router role is configured"):
            cli_main.initialize_router_model()

    def test_initialize_router_model_requires_router_role(
        self, tmp_path, monkeypatch
    ):
        from evo_diagram.agentic_system import main as cli_main

        models_data = {
            "providers": {
                "stepfun": {
                    "provider": "openai",
                    "base_url": "https://api.stepfun.com/v1",
                    "api_key": "sk-stepfun",
                },
            },
            "models": {
                "step-3.7-flash": {
                    "provider": "stepfun",
                    "model_name": "step-3.7-flash",
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(models_data))
        _make_settings(tmp_path, {"fast": "step-3.7-flash"})
        ModelConfig.init(p)

        def fake_create_for_role(role, **overrides):
            raise AssertionError("router initialization should fail before model construction")

        monkeypatch.setattr(
            cli_main.LLMFactory,
            "create_for_role",
            staticmethod(fake_create_for_role),
        )

        with pytest.raises(RuntimeError, match="roles.router.*settings.yaml"):
            cli_main.initialize_router_model()


class TestLLMFactory:
    def test_remote_openai_compatible_endpoint_requires_api_key(self):
        with pytest.raises(ValueError, match="Missing api_key.*api.stepfun.com"):
            LLMFactory.create(
                model="step-3.7-flash",
                model_provider="openai",
                base_url="https://api.stepfun.com/v1",
                api_key=None,
            )

    def test_remote_openai_provider_check_is_case_insensitive(self):
        with pytest.raises(ValueError, match="Missing api_key.*api.stepfun.com"):
            LLMFactory.create(
                model="step-3.7-flash",
                model_provider="OpenAI",
                base_url="https://api.stepfun.com/v1",
                api_key="",
            )

    def test_local_openai_compatible_endpoint_allows_dummy_key(self, monkeypatch):
        captured = {}
        sentinel = object()

        def fake_init_chat_model(**kwargs):
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(
            "evo_diagram.core.llm_factory.init_chat_model",
            fake_init_chat_model,
        )

        model = LLMFactory.create(
            model="local-model",
            model_provider="openai",
            base_url="http://localhost:8000/v1",
            api_key=None,
        )

        assert model is sentinel
        assert captured["api_key"] == "dummy-key-for-local-openai-endpoint"
