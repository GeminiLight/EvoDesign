import os
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Mapping

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from evo_diagram.utils.env_loader import is_placeholder_secret

# Load the repository-root .env first so shared local secrets are available to
# the backend. backend/.env remains supported for service-only overrides.
_REPO_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_BACKEND_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
OBSOLETE_BACKEND_ENV_KEYS = (
    "ALLOW_STEPFUN_BACKEND_FALLBACK",
)
_OBSOLETE_BACKEND_ENV_KEY_LOOKUP = {
    key.upper(): key for key in OBSOLETE_BACKEND_ENV_KEYS
}
DatabaseType = Literal["sqlite", "postgres"]


def find_obsolete_backend_env_keys(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return obsolete backend env keys that should no longer affect runtime."""
    source = os.environ if environ is None else environ
    found = {
        _OBSOLETE_BACKEND_ENV_KEY_LOOKUP[key.upper()]
        for key in source
        if key.upper() in _OBSOLETE_BACKEND_ENV_KEY_LOOKUP
    }
    return tuple(sorted(found))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ENV_FILE), str(_BACKEND_ENV_FILE)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application configuration
    app_name: str = "EvoDesign API"
    app_version: str = "1.0.0"
    debug: bool = False

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 3010

    # Database configuration
    db_type: DatabaseType = "sqlite"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "evodiagram"
    db_user: str = "postgres"
    db_password: str | None = None

    # JWT configuration - no default; must be set in .env
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_in: int = 60 * 60 * 24 * 7  # 7 days, in seconds

    # OAuth - Google
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_callback_url: str = "http://localhost:3010/api/v1/auth/google/callback"

    # OAuth - GitHub
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_callback_url: str = "http://localhost:3010/api/v1/auth/github/callback"

    # Email signup verification code (dev environment can use a fixed code)
    enable_signup_verification: bool = False
    signup_verification_code: str = ""

    # Stripe configuration
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    app_url: str = "http://localhost:5175"

    # CORS configuration
    frontend_url: str = "http://localhost:5175"
    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"

    # Guest token (guest mode, skips JWT auth and DB storage)
    guest_token: str | None = None

    # Session configuration - no default; must be set in .env
    session_secret: str

    # LLM configuration (for diagram generation)
    llm_model_name: str | None = None
    llm_model_provider: str = "openai"
    llm_api_key: str | None = None
    llm_endpoint_url: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 16384
    llm_reasoning_effort: Literal["low", "medium", "high"] | None = None

    # Refiner LLM configuration (optional, for diagram optimization)
    refiner_llm_model_name: str | None = None
    refiner_llm_model_provider: str = "openai"
    refiner_llm_api_key: str | None = None
    refiner_llm_endpoint_url: str | None = None

    # Diagram generation configuration
    canvas_library: str = "excalidraw"  # excalidraw or tldraw
    results_dir: str = "results"
    auto_refine_enabled: bool = True
    auto_refine_max_iterations: int = Field(default=2, ge=1, le=3)
    design_memory_enabled: bool = True
    design_memory_path: str = str(_REPO_ENV_FILE.parent / "data" / "web-design-memory")
    design_memory_seed_path: str = str(_REPO_ENV_FILE.parent / "evo_diagram" / "design_memory" / "seeds" / "web_strategies.json")
    design_memory_model: str = "Qwen/Qwen3-Embedding-0.6B"
    design_memory_top_k: int = Field(default=2, ge=1, le=5)
    design_memory_learning: bool = True
    retain_generation_artifacts: bool = False

    @field_validator("design_memory_path", "design_memory_seed_path", mode="after")
    @classmethod
    def resolve_design_memory_paths(cls, value: str) -> str:
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else _REPO_ENV_FILE.parent / path)

    @field_validator("db_type", mode="before")
    @classmethod
    def normalize_db_type(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "postgresql":
                return "postgres"
            return normalized
        return value

    @field_validator(
        "jwt_secret",
        "session_secret",
        "llm_api_key",
        "refiner_llm_api_key",
    )
    @classmethod
    def reject_placeholder_secrets(cls, value: str | None, info) -> str | None:
        if value is None:
            return value
        if is_placeholder_secret(value):
            raise ValueError(
                f"{info.field_name} is an example placeholder; configure a real secret."
            )
        if info.field_name in {"jwt_secret", "session_secret"} and not value.strip():
            raise ValueError(f"{info.field_name} must not be empty.")
        return value

    @model_validator(mode="after")
    def require_postgres_password(self) -> "Settings":
        if self.db_type == "postgres" and not self.db_password:
            raise ValueError("DB_PASSWORD is required when DB_TYPE=postgres")
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        return [
            origin
            for origin in (item.strip() for item in self.cors_origins.split(","))
            if origin
        ]

    @property
    def database_url(self) -> str:
        if self.db_type == "sqlite":
            return f"sqlite+aiosqlite:///{self.db_name}.db"
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
