"""Load application settings from ``configs/settings.yaml`` with env-var overrides.

Usage::

    from evo_diagram.config.settings import AppSettings

    settings = AppSettings.get_default()
    db_path = settings.design_memory_vector_db_path

Singleton
---------
Use ``AppSettings.get_default()`` to get (or create) the shared instance.
``AppSettings.init(path)`` overrides the default path (e.g. from a CLI
``--settings`` flag) before first access.

Environment variable overrides
------------------------------
Each YAML value can be overridden by its corresponding env var.  The mapping
is defined in ``_ENV_OVERRIDES``.  If the env var is set, it takes precedence
over the YAML value.
"""

from __future__ import annotations

import logging
import os
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_settings_path() -> Path:
    repo_path = _PROJECT_ROOT / "configs" / "settings.yaml"
    if repo_path.exists():
        return repo_path
    return Path(str(resources.files("evo_diagram.config.defaults").joinpath("settings.yaml")))


_DEFAULT_PATH = _default_settings_path()

# YAML dotted-path → env var name.  When the env var is set, it overrides
# the YAML value.  This preserves backward compatibility with the old
# config/env.py approach.
_ENV_OVERRIDES: Dict[str, str] = {
    "experiment.id": "EVO_EXPERIMENT_ID",
    "services.render_url": "RENDER_SERVICE_URL",
    "services.tool_service_url": "TOOL_SERVICE_URL",
    "canvas.library": "CANVAS_LIBRARY",
    "design_memory.vector_db_path": "DESIGN_MEMORY_VECTOR_DB_PATH",
    "design_memory.embedding_model": "DESIGN_MEMORY_EMBEDDING_MODEL",
    "user_preference.memory_path": "USER_PREFERENCE_MEMORY_PATH",
    "user_preference.embedding_model": "USER_PREFERENCE_EMBEDDING_MODEL",
    "generation.mode": "GENERATION_MODE",
    "generation.enable_refiner": "ENABLE_REFINER",
    "generation.use_icons": "USE_ICONS",
    "generation.structure_self_consistency_n": "STRUCTURE_SELF_CONSISTENCY_N",
    "generation.full_domain_knowledge": "FULL_DOMAIN_KNOWLEDGE",
    "render.fix_zorder": "EVODIAGRAM_RENDER_FIX_ZORDER",
    "render.icon_base_url": "ICON_BASE_URL",
}

VALID_GENERATION_MODES = ("multiagent", "oneshot")
MAX_STRUCTURE_SELF_CONSISTENCY_N = 9


def normalize_generation_mode(raw: Any) -> str:
    """Normalize the configured generation mode.

    Only the current public mode names are accepted. Legacy aliases such as
    ``pipeline`` and ``unified`` are intentionally rejected so config errors
    surface at startup instead of being silently mapped.
    """
    value = str(raw).strip().lower()
    if value in VALID_GENERATION_MODES:
        return value
    raise ValueError(
        f"Unknown generation mode: {raw!r}. Use 'multiagent' or 'oneshot'."
    )


class AppSettings:
    """Resolve application settings from ``settings.yaml`` + env vars.

    Parameters
    ----------
    path : str or Path
        Path to the YAML config file. Defaults to
        ``{project_root}/configs/settings.yaml``.
    """

    _instance: Optional["AppSettings"] = None
    _override_path: Optional[Path] = None

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"Settings file not found: {self._path}")
        self._path = self._path.resolve()
        with open(self._path, "r", encoding="utf-8") as f:
            self._raw: Dict[str, Any] = yaml.safe_load(f) or {}

    # ── singleton ────────────────────────────────────────────────────────

    @classmethod
    def init(cls, path: str | Path) -> None:
        """Override the default path (call before ``get_default()``)."""
        cls._override_path = Path(path)
        cls._instance = None  # force reload on next get_default()

    @classmethod
    def get_default(cls) -> "AppSettings":
        """Return the shared instance, creating it on first access."""
        if cls._instance is None:
            cls._instance = cls(cls._override_path or _DEFAULT_PATH)
        return cls._instance

    # ── raw access ──────────────────────────────────────────────────────

    def get_raw(self, dotted_key: str, default: Any = None) -> Any:
        """Access a value by ``section.key`` dotted path.

        Env var override is applied if present.  An env var that is set but
        empty (``USE_ICONS=`` in ``.env``, ``export USE_ICONS=``) is treated as
        "not configured": it falls back to the YAML value instead of forcing an
        empty string onto typed accessors, which would fail as an invalid value.
        """
        env_var = _ENV_OVERRIDES.get(dotted_key)
        if env_var:
            env_val = os.getenv(env_var)
            if env_val is not None:
                if env_val.strip():
                    return env_val
                logger.warning(
                    "Environment variable %s is set but empty; ignoring it and "
                    "using the %s value from %s. Remove the line or give it a "
                    "value to override the config.",
                    env_var,
                    dotted_key,
                    self._path,
                )

        section, _, key = dotted_key.partition(".")
        section_data = self._raw.get(section, {})
        if isinstance(section_data, dict):
            return section_data.get(key, default)
        return default

    # ── typed accessors ─────────────────────────────────────────────────

    @property
    def experiment_id(self) -> str:
        """Experiment identifier. Falls back to date if 'exp' or empty."""
        return str(self.get_raw("experiment.id", "exp"))

    @property
    def render_service_url(self) -> str:
        """URL of the TLDraw/Excalidraw PNG render service."""
        return str(self.get_raw("services.render_url", "http://localhost:3000"))

    @property
    def tool_service_url(self) -> str:
        """Base URL of the tool services (dagre layout, icons, etc.)."""
        return str(self.get_raw("services.tool_service_url", "http://localhost:3000"))

    @property
    def canvas_library(self) -> str:
        """Canvas library: 'excalidraw' or 'tldraw'."""
        return str(self.get_raw("canvas.library", "excalidraw"))

    @property
    def design_memory_vector_db_path(self) -> str:
        return self._resolve_path_setting(
            "design_memory.vector_db_path",
            "../data/knowledge",
        )

    @property
    def design_memory_embedding_model(self) -> str:
        return str(self.get_raw("design_memory.embedding_model", "Qwen/Qwen3-Embedding-0.6B"))

    @property
    def user_preference_memory_path(self) -> str:
        return self._resolve_path_setting(
            "user_preference.memory_path",
            "../data/user_preferences",
        )

    @property
    def user_preference_embedding_model(self) -> str:
        return str(self.get_raw("user_preference.embedding_model", "Qwen/Qwen3-Embedding-0.6B"))

    @property
    def generation_mode(self) -> str:
        """Generation strategy: 'multiagent' or 'oneshot'."""
        raw = self.get_raw("generation.mode", "multiagent")
        try:
            return normalize_generation_mode(raw)
        except ValueError as exc:
            raise ValueError(
                f"Unknown generation.mode: {raw!r}. Use 'multiagent' or 'oneshot'."
            ) from exc

    @property
    def generation_enable_refiner(self) -> bool:
        return self._bool_setting("generation.enable_refiner", True)

    @property
    def generation_use_icons(self) -> bool:
        return self._bool_setting("generation.use_icons", False)

    @property
    def structure_self_consistency_n(self) -> int:
        raw = self.get_raw("generation.structure_self_consistency_n", 1)
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Invalid integer setting generation.structure_self_consistency_n: "
                f"{raw!r}. Use an integer >= 1."
            ) from exc
        if value < 1:
            raise ValueError(
                "Invalid integer setting generation.structure_self_consistency_n: "
                f"{raw!r}. Use an integer >= 1."
            )
        if value > MAX_STRUCTURE_SELF_CONSISTENCY_N:
            raise ValueError(
                "Invalid integer setting generation.structure_self_consistency_n: "
                f"{raw!r}. Use an integer between 1 and "
                f"{MAX_STRUCTURE_SELF_CONSISTENCY_N}."
            )
        return value

    @property
    def full_domain_knowledge(self) -> bool:
        return self._bool_setting("generation.full_domain_knowledge", True)

    @property
    def render_fix_zorder(self) -> bool:
        return self._bool_setting("render.fix_zorder", True)

    @property
    def icon_base_url(self) -> str:
        default = "http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg"
        return str(self.get_raw("render.icon_base_url", default))

    # ── retriever weights ─────────────────────────────────────────────

    @property
    def retriever_utility_weight(self) -> float:
        return float(self.get_raw("retriever.utility_weight", 0.25))

    @property
    def retriever_diversity_weight(self) -> float:
        return float(self.get_raw("retriever.diversity_weight", 0.20))

    @property
    def retriever_exploration_weight(self) -> float:
        return float(self.get_raw("retriever.exploration_weight", 0.10))

    @property
    def evaluation_role(self) -> str:
        """Model role used by evaluation scoring."""
        return str(self.get_raw("evaluation.role", "eval"))

    @property
    def evaluation_default_metrics(self) -> list[str]:
        """Default metric list for evaluation runs."""
        raw = self.get_raw("evaluation.default_metrics", [])
        if isinstance(raw, list):
            return [str(item) for item in raw]
        if isinstance(raw, str):
            return [item.strip() for item in raw.split(",") if item.strip()]
        return []

    @property
    def roles(self) -> Dict[str, str]:
        """Role → model name mapping from ``settings.yaml``."""
        return dict(self._raw.get("roles", {}))

    @property
    def path(self) -> Path:
        return self._path

    def _resolve_path_setting(self, dotted_key: str, default: str) -> str:
        """Resolve filesystem path settings relative to the settings file."""
        raw_path = Path(str(self.get_raw(dotted_key, default))).expanduser()
        if raw_path.is_absolute():
            return str(raw_path)
        return str((self._path.parent / raw_path).resolve())

    def _bool_setting(self, dotted_key: str, default: bool) -> bool:
        raw = self.get_raw(dotted_key, default)
        if isinstance(raw, bool):
            return raw
        val = str(raw).strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
        if val in ("0", "false", "no", "off"):
            return False
        raise ValueError(
            f"Invalid boolean setting {dotted_key}: {raw!r}. "
            "Use true/false, yes/no, on/off, or 1/0."
        )


__all__ = ["AppSettings", "VALID_GENERATION_MODES", "normalize_generation_mode"]
