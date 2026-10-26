"""Load model/provider configuration from ``configs/models.yaml`` and roles from settings.

Usage::

    from evo_diagram.config.model_loader import ModelConfig

    cfg = ModelConfig()                       # loads configs/models.yaml + settings roles
    params = cfg.get_model_config("generator")    # → dict ready for LLMFactory.create()
    model  = LLMFactory.create_from_config(cfg, role="generator")
"""

from __future__ import annotations

import logging
import os
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from evo_diagram.utils.env_loader import is_placeholder_secret

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_models_path() -> Path:
    repo_path = _PROJECT_ROOT / "configs" / "models.yaml"
    if repo_path.exists():
        return repo_path
    return Path(str(resources.files("evo_diagram.config.defaults").joinpath("models.yaml")))


_DEFAULT_PATH = _default_models_path()

# YAML model keys that map directly to LLMFactory.create() params.
_MODEL_TO_FACTORY = {
    "model_name": "model",
    "provider": "model_provider",
    "temperature": "temperature",
    "max_tokens": "max_tokens",
    "timeout": "timeout",
    "max_retries": "max_retries",
    "reasoning_effort": "reasoning_effort",
}

# YAML provider keys that map to LLMFactory.create() params.
_PROVIDER_TO_FACTORY = {
    "base_url": "base_url",
    "api_key": "api_key",
}


def _ensure_project_env_loaded() -> None:
    """Load repository-root .env before resolving provider api_key entries."""
    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()


class ModelConfig:
    """Resolve role → model → provider chains from ``models.yaml`` + ``settings.yaml``.

    Providers and models are defined in ``models.yaml``.  Roles (which model
    powers which pipeline stage) are defined in ``settings.yaml`` under the
    ``roles`` section.

    Parameters
    ----------
    path : str or Path
        Path to the models YAML config file. Defaults to
        ``{project_root}/configs/models.yaml``.

    Singleton
    ---------
    Use ``ModelConfig.get_default()`` to get (or create) the shared
    instance.  ``ModelConfig.init(path)`` overrides the default path
    (e.g. from a CLI ``--model-config`` flag) before first access.
    """

    _instance: Optional["ModelConfig"] = None
    _override_path: Optional[Path] = None

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        from .settings import AppSettings  # avoid circular import

        _ensure_project_env_loaded()

        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"Model config not found: {self._path}")
        with open(self._path, "r", encoding="utf-8") as f:
            self._raw: Dict[str, Any] = yaml.safe_load(f) or {}

        self._providers: Dict[str, Dict] = self._raw.get("providers", {})
        self._models: Dict[str, Dict] = self._raw.get("models", {})
        # Roles live in settings.yaml, not models.yaml
        settings = AppSettings.get_default()
        self._roles: Dict[str, str] = settings.roles

    # ── singleton ────────────────────────────────────────────────────────

    @classmethod
    def init(cls, path: str | Path) -> None:
        """Override the default path (call before ``get_default()``)."""
        cls._override_path = Path(path)
        cls._instance = None  # force reload on next get_default()

    @classmethod
    def get_default(cls) -> "ModelConfig":
        """Return the shared instance, creating it on first access."""
        if cls._instance is None:
            cls._instance = cls(cls._override_path or _DEFAULT_PATH)
        return cls._instance

    # ── public API ──────────────────────────────────────────────────────

    def get_model_config(self, role: str, **overrides: Any) -> Dict[str, Any]:
        """Resolve *role* to a flat dict ready for ``LLMFactory.create()``.

        Resolution chain (highest to lowest precedence):
        1. ``**overrides`` — CLI flags (e.g. ``temperature=0.7``)
        2. ``settings.yaml`` roles → ``models.yaml`` models → providers

        Any ``**overrides`` take highest precedence (e.g. ``temperature=0.7``).
        """
        if role not in self._roles:
            raise KeyError(
                f"Role {role!r} not found in settings.yaml (roles section). "
                f"Available roles: {list(self._roles.keys())}"
            )

        # ── resolve YAML chain first (role → model → provider) ──
        yaml_model_name = self._roles[role]
        model_cfg = self._get_model(yaml_model_name)
        provider_name = model_cfg.get("provider")
        provider_cfg = self._get_provider(provider_name) if provider_name else {}

        return self._resolve_model_config(
            model_cfg,
            provider_name=provider_name,
            provider_cfg=provider_cfg,
            **overrides,
        )

    def get_named_model_config(self, model_alias: str, **overrides: Any) -> Dict[str, Any]:
        """Resolve a concrete model alias from ``models.yaml``.

        CLI callers that pass an alias from ``models.yaml`` need the alias's
        own provider/base_url/api_key as well.
        """
        model_cfg = self._get_model(model_alias)
        provider_name = model_cfg.get("provider")
        provider_cfg = self._get_provider(provider_name) if provider_name else {}
        return self._resolve_model_config(
            model_cfg,
            provider_name=provider_name,
            provider_cfg=provider_cfg,
            **overrides,
        )

    def has_model(self, model_alias: str) -> bool:
        """Return whether ``model_alias`` is a declared ``models.yaml`` key."""
        return model_alias in self._models

    def list_roles(self) -> Dict[str, str]:
        """Return ``{role_name: model_name}`` mapping."""
        return dict(self._roles)

    def list_models(self) -> list[str]:
        """Return available model names."""
        return list(self._models.keys())

    def list_providers(self) -> list[str]:
        """Return available provider names."""
        return list(self._providers.keys())

    def get_model_capabilities(self, role: str) -> set[str]:
        """Return declared capabilities for the model assigned to ``role``.

        Capabilities are local validation metadata only; they are not forwarded
        to ``LLMFactory.create()``. Models default to ``{"text"}`` when the
        field is omitted.
        """
        if role not in self._roles:
            raise KeyError(
                f"Role {role!r} not found in settings.yaml (roles section). "
                f"Available roles: {list(self._roles.keys())}"
            )
        model_alias = self._roles[role]
        model_cfg = self._get_model(model_alias)
        raw = model_cfg.get("capabilities", ["text"])
        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, list):
            values = raw
        else:
            raise ValueError(
                f"Model {model_alias!r} capabilities must be a string or list."
            )
        capabilities = {
            str(value).strip().lower()
            for value in values
            if str(value).strip()
        }
        return capabilities or {"text"}

    def require_model_capabilities(self, role: str, required: set[str]) -> None:
        """Fail fast when ``role`` lacks any required model capability."""
        capabilities = self.get_model_capabilities(role)
        missing = {capability.lower() for capability in required} - capabilities
        if missing:
            model_alias = self._roles.get(role, "<unknown>")
            raise ValueError(
                f"Model role {role!r} uses {model_alias!r}, which lacks required "
                f"capabilities: {sorted(missing)}. Declared capabilities: "
                f"{sorted(capabilities)}."
            )

    @property
    def path(self) -> Path:
        return self._path

    # ── internals ───────────────────────────────────────────────────────

    def _get_model(self, name: str) -> Dict[str, Any]:
        if name not in self._models:
            raise KeyError(
                f"Model {name!r} not found in {self._path}. "
                f"Available models: {list(self._models.keys())}"
            )
        return dict(self._models[name])

    def _get_provider(self, name: str) -> Dict[str, Any]:
        if not name:
            return {}
        if name not in self._providers:
            raise KeyError(
                f"Provider {name!r} not found in {self._path}. "
                f"Available providers: {list(self._providers.keys())}"
            )
        return dict(self._providers[name])

    def _resolve_model_config(
        self,
        model_cfg: Dict[str, Any],
        *,
        provider_name: Optional[str],
        provider_cfg: Dict[str, Any],
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Flatten a model/provider pair into ``LLMFactory.create`` kwargs."""
        result: Dict[str, Any] = {}

        # Provider-level keys (base_url, api_key)
        for yaml_key, factory_key in _PROVIDER_TO_FACTORY.items():
            if yaml_key == "api_key":
                continue  # handled separately below
            val = provider_cfg.get(yaml_key)
            if val is not None:
                result[factory_key] = self._resolve_value(val)

        # api_key must be declared by the provider config. Env references such
        # as ``$STEPFUN_API_KEY`` are resolved explicitly by _resolve_value().
        result["api_key"] = self._resolve_api_key(
            provider_cfg,
            provider_name=provider_name,
        )

        # Model-level keys (model_name→model, temperature, timeout, etc.)
        # Note: "provider" is handled specially below (→ protocol mapping).
        for yaml_key, factory_key in _MODEL_TO_FACTORY.items():
            if yaml_key == "provider":
                continue  # handled specially via protocol
            val = model_cfg.get(yaml_key)
            if val is not None:
                resolved = overrides.get(factory_key, self._resolve_value(val) if yaml_key == "model_name" else val)
                if yaml_key == "model_name" and (not isinstance(resolved, str) or not resolved.strip()):
                    raise ValueError("Model name is empty; set LLM_MODEL_NAME (or the model_name environment reference in models.yaml).")
                result[factory_key] = resolved

        # Resolve model_provider: use the provider's `provider` field (the
        # langchain protocol) if available, otherwise fall back to the
        # provider name itself.  This lets custom names like "proxyA" map
        # to "openai" for langchain.
        langchain_provider = provider_cfg.get("provider")
        if langchain_provider:
            result["model_provider"] = langchain_provider
        elif provider_name:
            result["model_provider"] = provider_name

        # Overrides (CLI flags, etc.) take highest precedence
        result.update(overrides)

        # Remove incidental None values so LLMFactory defaults kick in. Keep
        # api_key explicit because callers use it to distinguish "no provider
        # key configured" from "global LLM_API_KEY was silently applied".
        return {
            k: v
            for k, v in result.items()
            if v is not None or k == "api_key"
        }

    @staticmethod
    def _resolve_value(raw: Any) -> Any:
        """Resolve a YAML value that may reference an environment variable.

        Supported formats:
          - ``env:VAR_NAME`` → reads ``os.environ["VAR_NAME"]``
          - ``$VAR_NAME``    → reads ``os.environ["VAR_NAME"]``
          - ``${VAR_NAME}``  → reads ``os.environ["VAR_NAME"]``
          - anything else → returned as-is (plain string / number / etc.)

        Returns ``None`` if the env var is not set.
        """
        if not isinstance(raw, str):
            return raw

        env_var = None
        if raw.startswith("env:"):
            env_var = raw[4:].strip()
        elif raw.startswith("${") and raw.endswith("}"):
            env_var = raw[2:-1].strip()
        elif raw.startswith("$"):
            env_var = raw[1:].strip()

        if env_var is not None:
            val = os.getenv(env_var)
            if val is None:
                logger.warning(
                    "models.yaml references env var %s which is not set",
                    env_var,
                )
            return val
        return raw

    @staticmethod
    def _env_var_reference(raw: Any) -> Optional[str]:
        """Return the env var name a YAML api_key entry points at, if any."""
        if not isinstance(raw, str):
            return None
        if raw.startswith("env:"):
            return raw[4:].strip() or None
        if raw.startswith("${") and raw.endswith("}"):
            return raw[2:-1].strip() or None
        if raw.startswith("$"):
            return raw[1:].strip() or None
        return None

    def _describe_api_key_source(self, raw: Any) -> str:
        """Describe where a provider api_key came from, without leaking secrets."""
        env_var = self._env_var_reference(raw)
        if env_var:
            return (
                f"environment variable {env_var} "
                f"(referenced from {self._path} as {raw!r})"
            )
        return f"an inline api_key literal in {self._path}"

    def _resolve_api_key(
        self,
        provider_cfg: Dict[str, Any],
        *,
        provider_name: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve api_key with env-var support.

        Priority:
        1. YAML value with ``env:VAR`` syntax → read from env
        2. YAML plain string → use directly
        """
        raw = provider_cfg.get("api_key")
        if raw is not None:
            val = self._resolve_value(raw)
            if val is not None:
                if isinstance(val, str) and not val.strip():
                    return None
                if is_placeholder_secret(val):
                    provider_label = provider_name or "<unnamed>"
                    raise ValueError(
                        f"Provider {provider_label!r} api_key resolves to an example "
                        f"placeholder. Source: {self._describe_api_key_source(raw)}. "
                        "Set a real API key there. If this already is your real key, "
                        "it matched the placeholder heuristic in "
                        "evo_diagram/utils/env_loader.py (values starting with "
                        "'your_'/'your-'/'change-me' or ending with '_here'/'-here'); "
                        "re-issue or rename the key so it no longer matches."
                    )
                return val
        return None


__all__ = ["ModelConfig"]
