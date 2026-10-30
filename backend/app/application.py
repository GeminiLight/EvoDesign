"""FastAPI application factory and runtime assembly."""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Mapping

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_router
from app.config import Settings, find_obsolete_backend_env_keys, get_settings
from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from app.db.session import close_db, init_db
from app.schemas.common import HealthResponse


LifecycleHook = Callable[[], Awaitable[None]]

_REPO_ENV = Path(__file__).resolve().parents[2] / ".env"
_LOGGING_CONFIGURED = False


def load_repository_env() -> None:
    """Load repository-level environment variables for runtime integrations."""
    if _REPO_ENV.is_file():
        load_dotenv(_REPO_ENV, override=False)


def warn_obsolete_backend_env_keys(environ: Mapping[str, str] | None = None) -> None:
    """Warn when obsolete backend env keys are present but ignored."""
    obsolete_keys = find_obsolete_backend_env_keys(environ)
    if obsolete_keys:
        logger.warning(
            "Ignoring obsolete backend environment keys: {}",
            ", ".join(obsolete_keys),
        )


def configure_logging(settings: Settings, *, force: bool = False) -> None:
    """Configure Loguru sinks once per process."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED and not force:
        return

    logger.remove()
    logger.add(
        sys.stdout,
        diagnose=False,
        level="DEBUG" if settings.debug else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )
    logger.add(
        "logs/error.log",
        diagnose=False,
        level="ERROR",
        rotation="10 MB",
        retention="7 days",
    )
    logger.add(
        "logs/combined.log",
        diagnose=False,
        level="INFO",
        rotation="10 MB",
        retention="7 days",
    )
    _LOGGING_CONFIGURED = True


def _build_lifespan(
    init_db_fn: LifecycleHook = init_db,
    close_db_fn: LifecycleHook = close_db,
    memory_path: str | None = None,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application startup and shutdown."""
        logger.info("Starting up...")
        await init_db_fn()
        logger.info("Database initialized")
        from app.services.design_learning_jobs import resume_learning
        if memory_path:
            resume_learning(memory_path)

        yield

        logger.info("Shutting down...")
        from app.services.design_learning_jobs import wait_for_learning
        await wait_for_learning()
        await close_db_fn()
        logger.info("Database connection closed")

    return lifespan


def create_app(
    settings: Settings | None = None,
    *,
    configure_logs: bool = True,
    load_env: bool = True,
    init_db_fn: LifecycleHook = init_db,
    close_db_fn: LifecycleHook = close_db,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or get_settings()
    if load_env:
        load_repository_env()
    if configure_logs:
        configure_logging(resolved_settings)
    warn_obsolete_backend_env_keys()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=_build_lifespan(init_db_fn, close_db_fn, getattr(resolved_settings, "design_memory_path", None)),
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(
            "{} {} - {} - {:.3f}s",
            request.method,
            request.url.path,
            response.status_code,
            process_time,
        )
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.opt(exception=exc).error("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        logger.warning("App exception: {}", exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.public_detail},
        )

    from app.services.agent_contract import AgentError

    @app.exception_handler(AgentError)
    async def agent_exception_handler(request: Request, exc: AgentError):
        return JSONResponse(status_code=exc.status_code, content={
            'ok': False, 'protocol_version': 1,
            'error': {'code': exc.code, 'message': exc.message,
                      'retryable': exc.status_code >= 500, **exc.extra},
        })

    app.include_router(api_router, prefix="/api")

    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health_check_root():
        """Health check endpoint for load balancers and uptime probes."""
        return HealthResponse(
            status="ok",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    return app
