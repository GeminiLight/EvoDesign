"""Centralized environment variable loader for the EvoDiagram project.

This module loads the repository-root `.env` once at import time.

All other modules should use:
    from evo_diagram.utils.env_loader import ensure_env_loaded
instead of calling load_dotenv() directly.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_loaded = False

_STEPFUN_MODEL_NAME = "step-3.7-flash"
_STEPFUN_BASE_URL = "https://api.stepfun.com/v1"
_PLACEHOLDER_SECRET_VALUES = {
    "your_api_key_here",
    "your_stepfun_api_key_here",
    "your_backend_llm_api_key_here",
    "your_jwt_secret_here",
    "your_session_secret_here",
    "your-jwt-secret-here",
    "your-session-secret-here",
    "change-me-for-local-dev",
    "changeme",
}

# evo_diagram root: parent of utils/
_EVO_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _EVO_ROOT.parent


def _find_env_files() -> list[Path]:
    """Return the single supported .env file.

    Only the repository-root .env is supported. Existing process env vars still
    have the highest priority.
    """
    candidates = [_REPO_ROOT / ".env"]
    return [p for p in candidates if p.is_file()]


def is_placeholder_secret(value: object) -> bool:
    """Return whether a configured secret/key is an example placeholder."""
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    normalized_slug = normalized.replace("-", "_")
    if normalized in _PLACEHOLDER_SECRET_VALUES or normalized_slug in _PLACEHOLDER_SECRET_VALUES:
        return True
    return (
        normalized.startswith("your_")
        or normalized.startswith("your-")
        or normalized.startswith("change-me")
        or normalized.endswith("_here")
        or normalized.endswith("-here")
    )


def ensure_env_loaded() -> None:
    """Load .env files if not already loaded. Safe to call multiple times.

    Loads only the repo-root .env. ``load_dotenv`` does NOT override existing
    vars when ``override=False``, so explicit process environment values win.
    """
    global _loaded
    if _loaded:
        _apply_stepfun_legacy_llm_defaults()
        return

    for env_file in _find_env_files():
        load_dotenv(env_file, override=False)
    _apply_stepfun_legacy_llm_defaults()
    _loaded = True


def _apply_stepfun_legacy_llm_defaults() -> None:
    """Map the canonical StepFun key to legacy LLM_* settings.

    Core EvoDiagram resolves models through configs/models.yaml and
    configs/settings.yaml. Some older baseline and research scripts still read
    LLM_* variables directly; keep those paths on the same default provider
    without requiring users to duplicate their API key in .env.
    """
    stepfun_api_key = os.getenv("STEPFUN_API_KEY")
    if not stepfun_api_key:
        return
    if is_placeholder_secret(stepfun_api_key):
        return

    os.environ.setdefault("LLM_MODEL_PROVIDER", "openai")
    os.environ.setdefault("LLM_MODEL_NAME", _STEPFUN_MODEL_NAME)
    os.environ.setdefault("LLM_ENDPOINT_URL", _STEPFUN_BASE_URL)
    os.environ.setdefault("LLM_API_KEY", stepfun_api_key)


# Auto-load on import
ensure_env_loaded()
