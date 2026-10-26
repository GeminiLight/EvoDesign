import os
from dotenv import dotenv_values
from openai import OpenAI

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.abspath(os.path.join(_BASE_DIR, ".."))

_env_candidates = [
    os.path.join(os.getcwd(), ".env"),
    os.path.join(_ROOT_DIR, ".env"),
    os.path.join(_BASE_DIR, ".env"),
]
_env_path = next((p for p in _env_candidates if os.path.exists(p)), None)
config = dotenv_values(_env_path) if _env_path else {}

def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip("'")


def _normalize_base_url(base_url: str) -> str:
    u = _clean(base_url)
    if not u:
        return ""
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    u = u.rstrip("/")
    if u.endswith("/v1"):
        return u
    if u.endswith("/openai/v1"):
        return u
    return u + "/v1"


def _pick_provider_config() -> tuple[str, str, str]:
    ely_key = _clean(os.getenv("ELYSIVER_API_KEY") or config.get("ELYSIVER_API_KEY") or "")
    ely_base = _normalize_base_url(os.getenv("ELYSIVER_BASE_URL") or config.get("ELYSIVER_BASE_URL") or "")
    ely_model = _clean(os.getenv("ELYSIVER_MODEL") or config.get("ELYSIVER_MODEL") or "")

    openai_key = _clean(os.getenv("OPENAI_API_KEY") or config.get("OPENAI_API_KEY") or "")
    openai_base = _normalize_base_url(os.getenv("OPENAI_BASE_URL") or config.get("OPENAI_BASE_URL") or "")
    openai_model = _clean(os.getenv("OPENAI_MODEL") or config.get("OPENAI_MODEL") or "")

    legacy_key = _clean(os.getenv("API_KEY") or config.get("API_KEY") or "")
    legacy_base = _normalize_base_url(os.getenv("API_BASE") or config.get("API_BASE") or "")
    legacy_model = _clean(os.getenv("API_MODEL") or config.get("API_MODEL") or "")

    if ely_key and ely_base:
        return ely_key, ely_base, (ely_model or openai_model or legacy_model or "gpt-4o-mini")
    if openai_key and openai_base:
        return openai_key, openai_base, (openai_model or legacy_model or "gpt-4o-mini")
    if legacy_key and legacy_base:
        return legacy_key, legacy_base, (legacy_model or openai_model or "gpt-4o-mini")
    return "", "", ""


_API_KEY, _BASE_URL, _DEFAULT_MODEL = _pick_provider_config()

# Parity with the EvoDiagram generator (max_tokens=16384, max_retries=6,
# temperature=0); see evo_diagram/agentic_system/main.py.
_MAX_RETRIES = int(_clean(os.getenv("LLM_MAX_RETRIES") or "") or 6)
_MAX_TOKENS = int(_clean(os.getenv("LLM_MAX_TOKENS") or "") or 16384)

_CLIENT: OpenAI | None = None


def _get_client() -> OpenAI:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not _API_KEY or not _BASE_URL:
        raise RuntimeError(
            "Missing API config: (ELYSIVER_API_KEY/ELYSIVER_BASE_URL) or (OPENAI_API_KEY/OPENAI_BASE_URL) or (API_KEY/API_BASE)"
        )
    _CLIENT = OpenAI(api_key=_API_KEY, base_url=_BASE_URL, max_retries=_MAX_RETRIES)
    return _CLIENT

def call_api(log, engine="gpt-4o-mini"):
    client = _get_client()
    model = _clean(engine) or _DEFAULT_MODEL
    resp = client.chat.completions.create(
        model=model, messages=log, temperature=0, max_tokens=_MAX_TOKENS
    )
    return resp.choices[0].message.content
