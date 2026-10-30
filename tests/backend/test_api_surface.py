from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from fastapi import routing as fastapi_routing
from fastapi.routing import APIRoute

from app.application import create_app
from app.core.rate_limit import limiter

AUTH_DEPENDENCY_MODULES = {"app.api.deps", "app.api.agent_deps"}


@dataclass(frozen=True)
class RouteContract:
    method: str
    path: str
    tag: str
    handler: str
    response_model: str | None
    status_code: int
    auth_dependency: str | None
    rate_limit: str | None

    @property
    def http_key(self) -> tuple[str, str]:
        return (self.method, self.path)


R = RouteContract
EXPECTED_V1_ROUTES: tuple[RouteContract, ...] = (
    R('GET', '/api/v1/projects/{project_id}/document/preview', 'Agent collaboration', 'document_preview', None, 200, 'get_agent_actor', '20 per 1 minute'),
    R('POST', '/api/v1/agent/connections', 'Agent collaboration', 'start_connection', None, 201, None, '10 per 1 minute'),
    R('POST', '/api/v1/agent/connections/{connection_id}/claim', 'Agent collaboration', 'claim', None, 200, None, '30 per 1 minute'),
    R('GET', '/api/v1/agent/connections', 'Agent collaboration', 'connections', None, 200, 'get_current_user_id', None),
    R('GET', '/api/v1/agent/connections/{connection_id}', 'Agent collaboration', 'connection_status', None, 200, 'get_agent_actor', None),
    R('POST', '/api/v1/agent/connections/{connection_id}/approve', 'Agent collaboration', 'approve', None, 200, 'get_current_user_id', None),
    R('DELETE', '/api/v1/agent/connections/{connection_id}', 'Agent collaboration', 'revoke', None, 200, 'get_agent_actor', None),
    R('PUT', '/api/v1/agent/connections/{connection_id}/context', 'Agent collaboration', 'publish_context', None, 200, 'get_current_user_id', None),
    R('GET', '/api/v1/projects/{project_id}/document/head', 'Agent collaboration', 'document_head', None, 200, 'get_agent_actor', None),
    R('GET', '/api/v1/projects/{project_id}/document', 'Agent collaboration', 'document', None, 200, 'get_agent_actor', None),
    R('GET', '/api/v1/projects/{project_id}/agent-context', 'Agent collaboration', 'context', None, 200, 'get_agent_actor', None),
    R('GET', '/api/v1/projects/{project_id}/agent-history', 'Agent collaboration', 'history', None, 200, 'get_agent_actor', None),
    R('POST', '/api/v1/projects/{project_id}/agent-proposals', 'Agent collaboration', 'propose', None, 202, 'get_agent_actor', None),
    R('GET', '/api/v1/projects/{project_id}/agent-proposals', 'Agent collaboration', 'proposals', None, 200, 'get_agent_actor', None),
    R('GET', '/api/v1/projects/{project_id}/agent-proposals/{proposal_id}', 'Agent collaboration', 'proposal_status', None, 200, 'get_agent_actor', None),
    R('GET', '/api/v1/projects/{project_id}/agent-proposals/{proposal_id}/preview', 'Agent collaboration', 'preview', None, 200, 'get_agent_actor', None),
    R('POST', '/api/v1/projects/{project_id}/agent-proposals/{proposal_id}/commit', 'Agent collaboration', 'commit', None, 200, 'get_agent_actor', None),
    R('POST', '/api/v1/projects/{project_id}/agent-proposals/{proposal_id}/reject', 'Agent collaboration', 'reject', None, 200, 'get_agent_actor', None),
    R('POST', '/api/v1/projects/{project_id}/restore-proposals', 'Agent collaboration', 'restore', None, 202, 'get_agent_actor', None),

    R("GET", "/api/v1/health", "Health", "health_check", "HealthResponse", 200, None, None),
    R("POST", "/api/v1/auth/login", "Authentication", "login", "AuthResponse", 200, None, "5 per 1 minute"),
    R("POST", "/api/v1/auth/register", "Authentication", "register", "AuthResponse", 201, None, "3 per 1 minute"),
    R("GET", "/api/v1/auth/me", "Authentication", "get_current_user_info", "AuthResponse", 200, "get_current_auth", None),
    R("GET", "/api/v1/auth/google", "Authentication", "google_login", None, 200, None, None),
    R("GET", "/api/v1/auth/google/callback", "Authentication", "google_callback", None, 200, None, None),
    R("GET", "/api/v1/auth/github", "Authentication", "github_login", None, 200, None, None),
    R("GET", "/api/v1/auth/github/callback", "Authentication", "github_callback", None, 200, None, None),
    R("POST", "/api/v1/auth/exchange", "Authentication", "exchange_oauth_code", "AuthResponse", 200, None, None),
    R("GET", "/api/v1/users/subscription", "Users", "get_subscription", "SubscriptionStatus", 200, "get_current_user_id", None),
    R("PUT", "/api/v1/users/profile", "Users", "update_profile", "UserResponse", 200, "get_current_user_id", None),
    R("POST", "/api/v1/diagram/generate", "Diagram Workflow", "generate_diagram", "DiagramGenerateResponse", 201, "get_current_user_or_guest", "10 per 1 minute"),
    R("POST", "/api/v1/diagram/generate/stream", "Diagram Workflow", "generate_diagram_stream", None, 200, "get_current_user_or_guest", "10 per 1 minute"),
    R("GET", "/api/v1/diagram/learning/{job_id}", "Diagram Workflow", "get_design_learning_status", None, 200, "get_current_user_or_guest", None),
    R("POST", "/api/v1/diagram/edit-local", "Diagram Workflow", "edit_diagram_local", "DiagramLocalEditResponse", 200, "get_current_user_or_guest", "20 per 1 minute"),
    R("PATCH", "/api/v1/schema/sync", "Schema", "sync_schema", "SchemaSyncResponse", 200, "get_current_user_id", None),
    R("GET", "/api/v1/projects", "Project", "list_projects", "ProjectListResponse", 200, "get_current_user_id", None),
    R("POST", "/api/v1/projects", "Project", "create_project", "ProjectCreateResponse", 201, "get_current_user_id", None),
    R("GET", "/api/v1/projects/{project_id}/snapshots", "Project", "get_project_snapshots", "ProjectSnapshotListResponse", 200, "get_current_user_id", None),
    R("GET", "/api/v1/projects/{project_id}", "Project", "get_project", "ProjectDetailResponse", 200, "get_current_user_id", None),
    R("PUT", "/api/v1/projects/{project_id}", "Project", "update_project", "ProjectUpdateResponse", 200, "get_current_user_id", None),
    R("DELETE", "/api/v1/projects/{project_id}", "Project", "delete_project", None, 204, "get_current_user_id", None),
    R("POST", "/api/v1/dna/analyze", "DNA", "analyze_dna_image", "DnaAnalyzeResponse", 200, "get_current_user_id", "10 per 1 minute"),
    R("GET", "/api/v1/dna/rules", "DNA", "get_dna_rules", "DnaRulesPayload", 200, "get_current_user_id", None),
    R("PUT", "/api/v1/dna/rules", "DNA", "save_dna_rules", "DnaRulesPayload", 200, "get_current_user_id", None),
)


def _settings():
    return SimpleNamespace(
        app_name="Test EvoDiagram API",
        app_version="test",
        debug=False,
        cors_origins_list=["http://localhost:5175"],
    )


def _route_views(app) -> list[Any]:
    """Return one flattened view per registered route.

    FastAPI >= 0.141 keeps included routers in ``app.routes`` as lazy
    placeholders and expands them through ``iter_route_contexts``; earlier
    versions flatten at ``include_router`` time, so their route objects already
    are the flattened view. Both shapes expose ``path``/``methods``/``tags``/
    ``name``/``response_model``/``status_code``/``dependant``.
    """
    iter_route_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    if iter_route_contexts is None:
        return list(app.routes)
    return list(iter_route_contexts(app.routes))


def _as_api_route_view(route_view: Any) -> Any | None:
    """Return the view when it describes an APIRoute, else None."""
    original_route = getattr(route_view, "original_route", route_view)
    return route_view if isinstance(original_route, APIRoute) else None


def _http_routes(app, *, prefix: str | None = None) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for route in _route_views(app):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not path or methods is None:
            continue
        if prefix is not None and not path.startswith(prefix):
            continue
        for method in methods:
            if method not in {"HEAD", "OPTIONS"}:
                routes.add((method, path))
    return routes


def _response_model_name(route: Any) -> str | None:
    response_model = getattr(route, "response_model", None)
    if response_model is None:
        return None
    return getattr(response_model, "__name__", str(response_model))


def _auth_dependency_name(route: Any) -> str | None:
    """Return the auth dependency the endpoint declares, if any.

    Only top-level ``Depends`` calls defined in ``app.api.deps`` count, so this
    names the entry point (``get_current_user_id``, ``get_current_user_or_guest``,
    ...) rather than the whole resolution chain behind it.
    """
    names = sorted(
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if getattr(dependency.call, "__module__", "") in AUTH_DEPENDENCY_MODULES
    )
    return "+".join(names) or None


def _rate_limit(route: Any) -> str | None:
    """Return the slowapi limit registered for the endpoint, if any.

    slowapi keys its registry by ``module.function`` of the undecorated
    endpoint and normalises ``@limiter.limit("10/minute")`` to
    ``"10 per 1 minute"``.
    """
    endpoint = route.endpoint
    registry = getattr(limiter, "_route_limits", {})
    limits = registry.get(f"{endpoint.__module__}.{endpoint.__name__}") or []
    return str(limits[0].limit) if limits else None


def _route_contracts(app, *, prefix: str) -> dict[tuple[str, str], RouteContract]:
    contracts: dict[tuple[str, str], RouteContract] = {}
    for route_view in _route_views(app):
        route = _as_api_route_view(route_view)
        if route is None:
            continue
        if not route.path.startswith(prefix):
            continue
        for method in route.methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            contract = RouteContract(
                method=method,
                path=route.path,
                tag=route.tags[0] if route.tags else "",
                handler=route.name,
                response_model=_response_model_name(route),
                status_code=route.status_code or 200,
                auth_dependency=_auth_dependency_name(route),
                rate_limit=_rate_limit(route),
            )
            contracts[contract.http_key] = contract
    return contracts


def test_backend_v1_api_surface_is_explicit():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )

    assert _http_routes(app, prefix="/api/v1") == {
        contract.http_key for contract in EXPECTED_V1_ROUTES
    }


def test_backend_v1_route_metadata_matches_contract():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )

    assert _route_contracts(app, prefix="/api/v1") == {
        contract.http_key: contract for contract in EXPECTED_V1_ROUTES
    }


def test_backend_v1_router_group_counts_are_explicit():
    counts: dict[str, int] = {}
    for contract in EXPECTED_V1_ROUTES:
        counts[contract.tag] = counts.get(contract.tag, 0) + 1

    assert counts == {
        "Agent collaboration": 19,
        "Authentication": 8,
        "DNA": 3,
        "Diagram Workflow": 4,
        "Health": 1,
        "Project": 6,
        "Schema": 1,
        "Users": 2,
    }


def test_route_views_fall_back_to_app_routes_without_iter_route_contexts(monkeypatch):
    """FastAPI < 0.141 has no iter_route_contexts and app.routes is already flat."""
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    monkeypatch.delattr(fastapi_routing, "iter_route_contexts", raising=False)

    assert _route_views(app) == list(app.routes)


def test_route_contracts_read_directly_registered_routes():
    """Routes added straight on the app are plain APIRoutes, not router contexts."""
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )

    assert _route_contracts(app, prefix="/health") == {
        ("GET", "/health"): RouteContract(
            method="GET",
            path="/health",
            tag="Health",
            handler="health_check_root",
            response_model="HealthResponse",
            status_code=200,
            auth_dependency=None,
            rate_limit=None,
        )
    }


def test_backend_non_api_routes_are_limited_to_health_and_docs():
    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )

    assert _http_routes(app) - _http_routes(app, prefix="/api/v1") == {
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/health"),
        ("GET", "/openapi.json"),
        ("GET", "/redoc"),
    }
