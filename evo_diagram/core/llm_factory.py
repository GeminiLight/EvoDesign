import logging
import os
from typing import Optional, Union, Dict
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel
from langchain.chat_models import init_chat_model
from omegaconf import OmegaConf, DictConfig

logger = logging.getLogger(__name__)


class LLMFactory:
    @staticmethod
    def _is_local_openai_endpoint(base_url: Optional[str]) -> bool:
        if not base_url:
            return False
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

    @staticmethod
    def _normalize_openai_base_url(
        base_url: Optional[str],
        model_provider: Optional[str],
        kwargs: Dict,
    ) -> Optional[str]:
        """Normalize OpenAI-compatible endpoints and opt into Responses API when requested."""
        if not base_url or not isinstance(model_provider, str):
            return base_url

        if model_provider.lower() != "openai":
            return base_url

        normalized = base_url.rstrip("/")

        if normalized.endswith("/chat/completions"):
            # Caller pinned chat/completions — make sure langchain's agent path
            # doesn't silently switch to Responses API for reasoning models.
            kwargs.setdefault("use_responses_api", False)
            return normalized.rsplit("/chat/completions", 1)[0]

        if normalized.endswith("/responses"):
            kwargs.setdefault("use_responses_api", True)
            return normalized.rsplit("/responses", 1)[0]

        # Generic /v1 endpoint — langchain-openai's create_agent path defaults
        # to the Responses API for newer reasoning models, which breaks proxy
        # gateways that only implement chat/completions. Force the classic
        # path unless the caller explicitly opted in.
        kwargs.setdefault("use_responses_api", False)
        return normalized

    @staticmethod
    def create(
        model: Optional[str] = None,
        model_provider: Optional[str] = None,
        temperature: float = 0,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = 1200,  # Default 20 minutes timeout for slow reasoning models
        max_retries: int = 2,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> BaseChatModel:
        """Initialize LLM client with model parameters.

        Args:
            model: Model name (e.g., 'gpt-4', 'claude-3-5-sonnet-20241022')
            model_provider: Provider name (e.g., 'openai', 'anthropic', 'nvidia')
            temperature: Temperature for model responses (default: 0)
            base_url: Custom base URL for API endpoint
            api_key: Custom API key
            timeout: Request timeout in seconds (default: 120)
            max_retries: Max retries for API calls (default: 3)
            max_tokens: Maximum tokens in response
            **kwargs: Additional parameters passed to init_chat_model
                      (e.g., streaming=True, top_p=0.95)

        Raises:
            ValueError: If neither llm nor model is provided
        """
        if model is None:
            model = "claude-3-5-sonnet-20241022"
            model_provider = model_provider or "anthropic"

        # NVIDIA endpoints are OpenAI-compatible; just remap the provider.
        # Streaming is needed because NVIDIA's gateway returns 504 on long
        # non-streaming requests (>300 s) for reasoning models like minimax-m2.1.
        provider_key = model_provider.lower() if isinstance(model_provider, str) else None

        if provider_key == "nvidia":
            model_provider = "openai"
            provider_key = "openai"
            base_url = base_url or "https://integrate.api.nvidia.com/v1"
            kwargs.setdefault("streaming", True)

        base_url = LLMFactory._normalize_openai_base_url(base_url, model_provider, kwargs)

        # Enable streaming by default to avoid Cloudflare/proxy 524 gateway
        # timeouts that occur when the server holds a connection silently.
        kwargs.setdefault("streaming", True)

        # Identify the application: some gateways reject the SDK's default User-Agent.
        if provider_key == "openai":
            kwargs.setdefault(
                "default_headers",
                {"User-Agent": "EvoDiagram/diagnostic"},
            )

        config_kwargs = {
            "model": model,
            "model_provider": model_provider,
            "temperature": temperature,
            "timeout": timeout,
            "max_retries": max_retries,
            **kwargs
        }

        if base_url is not None:
            config_kwargs["base_url"] = base_url

        if api_key is not None and str(api_key).strip():
            config_kwargs["api_key"] = api_key
        elif base_url is not None and provider_key == "openai":
            if LLMFactory._is_local_openai_endpoint(base_url):
                config_kwargs["api_key"] = "dummy-key-for-local-openai-endpoint"
            else:
                raise ValueError(
                    "Missing api_key for remote OpenAI-compatible endpoint "
                    f"{base_url!r}. Configure provider api_key in models.yaml "
                    "or set the referenced API key environment variable."
                )

        if max_tokens is not None:
            config_kwargs["max_tokens"] = max_tokens

        # Initialize the model
        logger.debug(f"Initializing LLM: model={model}, provider={model_provider}, timeout={timeout}")
        llm = init_chat_model(**config_kwargs)
        return llm

    @classmethod
    def from_config(cls, config: Union[Dict, DictConfig, object]) -> BaseChatModel:
        """Initialize LLM client from WorkflowConfig.

        This is a convenience method that extracts LLM parameters from
        WorkflowConfig and creates an LLMFactory instance.
        """
        # Normalize the incoming config into a plain dict so .pop is safe.
        # Support already-dict configs, OmegaConf objects, and plain Python objects.
        if isinstance(config, dict):
            llm_config = dict(config)
        elif isinstance(config, DictConfig):
            llm_config = OmegaConf.to_container(config, resolve=True)
            assert isinstance(llm_config, dict)
        else:
            raise ValueError("Unsupported config type for LLMFactory.from_config")

        # Accept both key styles: ModelConfig._resolve_model_config() emits
        # "model"/"model_provider" (LLMFactory.create kwargs), while older
        # WorkflowConfig-style dicts use "model_name"/"provider". Pop both so a
        # leftover alias is never forwarded as a duplicate keyword argument.
        model = llm_config.pop("model", None)
        legacy_model = llm_config.pop("model_name", None)
        model_provider = llm_config.pop("model_provider", None)
        legacy_model_provider = llm_config.pop("provider", None)

        return cls.create(
            model=model if model is not None else legacy_model,
            model_provider=(
                model_provider if model_provider is not None else legacy_model_provider
            ),
            base_url=llm_config.pop("base_url", None),
            api_key=llm_config.pop("api_key", None),
            **llm_config,
        )

    @classmethod
    def create_for_role(
        cls,
        role: str,
        **overrides,
    ) -> BaseChatModel:
        """Create a model for *role* using the default ``ModelConfig``.

        This is the recommended entry point.  It resolves the role through
        ``ModelConfig.get_default()`` (which auto-loads
        ``configs/models.yaml`` unless overridden via ``ModelConfig.init()``).

        Args:
            role: Role name (e.g. ``"generator"``, ``"refiner"``, ``"fast"``).
            **overrides: Extra keyword arguments forwarded to ``cls.create()``,
                taking highest precedence over YAML values.

        Returns:
            BaseChatModel: Configured chat model instance.
        """
        from evo_diagram.config.model_loader import ModelConfig
        config = ModelConfig.get_default()
        params = config.get_model_config(role, **overrides)
        return cls.create(**params)

    @classmethod
    def create_from_config(
        cls,
        config: "ModelConfig",
        role: str = "generator",
        **overrides,
    ) -> BaseChatModel:
        """Create a model by resolving *role* through a ``ModelConfig``.

        Prefer ``create_for_role()`` which uses the default singleton.
        This method is for callers that already hold an explicit config instance.

        Args:
            config: A ``ModelConfig`` instance.
            role: Role name in the YAML (e.g. ``"generator"``, ``"refiner"``).
            **overrides: Extra keyword arguments forwarded to ``cls.create()``.

        Returns:
            BaseChatModel: Configured chat model instance.
        """
        params = config.get_model_config(role, **overrides)
        return cls.create(**params)

    @classmethod
    def create_default(
        cls,
        provider_config: "ModelConfig" = None,
        temperature: float = 0,
        **kwargs,
    ) -> BaseChatModel:
        """Create LLM from the ``default`` role.

        Uses the provided *provider_config* or the singleton
        ``ModelConfig.get_default()``.
        """
        from evo_diagram.config.model_loader import ModelConfig

        config = provider_config or ModelConfig.get_default()
        params = config.get_model_config("default", temperature=temperature, **kwargs)
        logger.info("Creating default LLM: model=%s", params.get("model"))
        return cls.create(**params)

    @classmethod
    def create_fast(
        cls,
        provider_config: "ModelConfig" = None,
        temperature: float = 0,
        **kwargs,
    ) -> BaseChatModel:
        """Fast-tier LLM for per-element fill tasks.

        Uses the ``"fast"`` role from the provided *provider_config* or
        the singleton ``ModelConfig.get_default()``.
        """
        from evo_diagram.config.model_loader import ModelConfig

        config = provider_config or ModelConfig.get_default()
        params = config.get_model_config("fast", temperature=temperature, **kwargs)
        logger.info("Creating fast-tier LLM: model=%s", params.get("model"))
        return cls.create(**params)


if __name__ == "__main__":
    # Test LLMFactory
    # python -m core.llm_factory
    from dotenv import load_dotenv
    load_dotenv(".env")

    llm = LLMFactory.create_for_role("generator")
    response = llm.invoke("Hello, world!")
    print("LLM Response:", response.content)
