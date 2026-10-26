from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import routing as fastapi_routing

from app.application import create_app, warn_obsolete_backend_env_keys
from app.core.exceptions import AppException, ProjectNotFoundException


def _registered_paths(app) -> set[str]:
    """Return every registered route path, across FastAPI versions.

    FastAPI >= 0.141 keeps included routers in ``app.routes`` as lazy
    placeholders that carry no path of their own; ``iter_route_contexts``
    expands them. Older versions flatten at ``include_router`` time.
    """
    iter_route_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    routes = app.routes if iter_route_contexts is None else iter_route_contexts(app.routes)
    return {getattr(route, "path", "") for route in routes}


def _settings():
    return SimpleNamespace(
        app_name="Test EvoDiagram API",
        app_version="test",
        debug=False,
        cors_origins_list=["http://localhost:5175"],
    )


class RecordingLogger:
    def __init__(self):
        self.warning_calls = []

    def warning(self, message: str, *args):
        self.warning_calls.append((message, args))


def test_warn_obsolete_backend_env_keys_logs_names_without_values(monkeypatch):
    logger = RecordingLogger()
    monkeypatch.setattr("app.application.logger", logger)

    warn_obsolete_backend_env_keys(
        {
            "STEPFUN_API_KEY": "sk-secret",
            "ALLOW_STEPFUN_BACKEND_FALLBACK": "true",
        }
    )

    assert logger.warning_calls == [
        (
            "Ignoring obsolete backend environment keys: {}",
            ("ALLOW_STEPFUN_BACKEND_FALLBACK",),
        )
    ]
    assert "sk-secret" not in str(logger.warning_calls)
    assert "true" not in str(logger.warning_calls)


def test_create_app_resolves_settings_before_loading_repository_env(
    monkeypatch,
    tmp_path,
):
    repo_env = tmp_path / ".env"
    repo_env.write_text("JWT_SECRET=root-jwt-secret\n", encoding="utf-8")
    monkeypatch.setattr("app.application._REPO_ENV", repo_env)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    seen_preloaded = []

    def fake_get_settings():
        import os

        seen_preloaded.append("JWT_SECRET" in os.environ)
        return _settings()

    monkeypatch.setattr("app.application.get_settings", fake_get_settings)

    create_app(configure_logs=False)

    assert seen_preloaded == [False]


def test_create_app_registers_core_routes_without_runtime_setup():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    routes = _registered_paths(app)

    assert app.title == "Test EvoDiagram API"
    assert "/health" in routes
    assert "/api/v1/auth/login" in routes
    assert "/api/v1/diagram/generate" in routes
    assert "/api/v1/dna/analyze" in routes
    assert hasattr(app.state, "limiter")


@pytest.mark.asyncio
async def test_create_app_uses_injected_lifecycle_hooks():
    calls: list[str] = []

    async def init_db():
        calls.append("init")

    async def close_db():
        calls.append("close")

    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
        init_db_fn=init_db,
        close_db_fn=close_db,
    )

    async with app.router.lifespan_context(app):
        assert calls == ["init"]

    assert calls == ["init", "close"]


@pytest.mark.asyncio
async def test_app_exception_handler_uses_public_detail_for_domain_errors():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    handler = app.exception_handlers[AppException]

    response = await handler(
        None,
        ProjectNotFoundException("project secret-project-id missing for user-1"),
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {"detail": "Project not found"}
    assert b"secret-project-id" not in response.body
    assert b"user-1" not in response.body


@pytest.mark.asyncio
async def test_base_app_exception_uses_safe_default_public_detail():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    handler = app.exception_handlers[AppException]

    response = await handler(None, AppException("internal secret detail", 418))

    assert response.status_code == 418
    assert json.loads(response.body) == {"detail": "Application error"}
    assert b"secret" not in response.body


@pytest.mark.asyncio
async def test_base_app_exception_allows_explicit_public_detail():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    handler = app.exception_handlers[AppException]

    response = await handler(
        None,
        AppException(
            "internal secret detail",
            418,
            public_detail="custom public error",
        ),
    )

    assert response.status_code == 418
    assert json.loads(response.body) == {"detail": "custom public error"}
    assert b"secret" not in response.body


@pytest.mark.asyncio
async def test_global_exception_handler_hides_unhandled_exception_details():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    handler = app.exception_handlers[Exception]

    response = await handler(None, RuntimeError("provider secret leaked"))

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "Internal server error"}
    assert b"secret" not in response.body
