"""Fail-closed resolution of the LLM endpoint used by baseline runners."""

from __future__ import annotations

import os
from typing import Optional


class MissingLLMEndpointError(RuntimeError):
    """Raised when no LLM endpoint is configured."""


def require_llm_endpoint(*explicit: Optional[str], env_var: str = "LLM_ENDPOINT_URL") -> str:
    """Return the first configured endpoint, else ``$env_var``; never a built-in default.

    Baselines send prompts (and API keys) to this URL, so a missing setting is
    an error rather than a silent fallback to a third-party service.
    """
    for candidate in (*explicit, os.getenv(env_var)):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    raise MissingLLMEndpointError(
        f"No LLM endpoint configured. Set {env_var} (e.g. in the repository .env) "
        "to your OpenAI-compatible base URL, or pass it explicitly."
    )
