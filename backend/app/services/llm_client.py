"""Backend LLM client construction shared by generation and local edit services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import Settings, get_settings
from app.core.evo_imports import ensure_evo_diagram_importable


_DEFAULT_EXPLICIT_MODEL = "gpt-4.1-mini"


class BackendLLMConfigurationError(RuntimeError):
    """Raised when backend LLM settings are incomplete or invalid."""


@dataclass(frozen=True)
class BackendLLMConfig:
    """Resolved chat-model configuration for backend services."""

    model: str
    model_provider: str
    api_key: str
    base_url: str | None
    temperature: float
    max_tokens: int
    reasoning_effort: str | None = None

    def as_factory_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model,
            "model_provider": self.model_provider,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs


def _first_nonempty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value:
            return value
    return None


def _explicit_backend_config(
    *,
    settings: Settings,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> BackendLLMConfig:
    return BackendLLMConfig(
        model=_first_nonempty(
            settings.llm_model_name,
            _DEFAULT_EXPLICIT_MODEL,
        )
        or _DEFAULT_EXPLICIT_MODEL,
        model_provider=settings.llm_model_provider or "openai",
        api_key=api_key,
        base_url=settings.llm_endpoint_url,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=getattr(settings, "llm_reasoning_effort", None),
    )


def resolve_backend_llm_config(
    *,
    settings: Settings | None = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BackendLLMConfig:
    """Resolve the backend chat-model configuration from typed settings."""
    settings = settings or get_settings()
    resolved_temperature = settings.llm_temperature if temperature is None else temperature
    resolved_max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens

    if settings.llm_api_key:
        return _explicit_backend_config(
            settings=settings,
            api_key=settings.llm_api_key,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
        )

    raise BackendLLMConfigurationError(
        "LLM API key is missing. Configure LLM_API_KEY for backend diagram "
        "generation."
    )


def create_backend_llm(
    *,
    settings: Settings | None = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
):
    """Create the backend chat model from the resolved backend settings."""
    config = resolve_backend_llm_config(
        settings=settings,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    ensure_evo_diagram_importable()
    from evo_diagram.core.llm_factory import LLMFactory

    return LLMFactory.create(**config.as_factory_kwargs())
