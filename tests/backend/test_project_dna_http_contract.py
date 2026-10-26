from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id
from app.api.v1.endpoints import dna, project
from app.application import create_app
from app.db.session import get_db


def _settings():
    return SimpleNamespace(
        app_name="Test EvoDiagram API",
        app_version="test",
        debug=False,
        cors_origins_list=["http://localhost:5175"],
    )


async def _user_id():
    return "user-1"


async def _db_session():
    yield object()


class _ForbiddenProjectService:
    def __init__(self, _db):
        pass

    async def create_project(self, *_args, **_kwargs):
        raise AssertionError("project service should not run for invalid bodies")

    async def update_project(self, *_args, **_kwargs):
        raise AssertionError("project service should not run for invalid bodies")


class _ForbiddenDnaRuleService:
    def __init__(self, _db):
        pass

    async def replace_rules(self, *_args, **_kwargs):
        raise AssertionError("DNA rule service should not run for invalid bodies")


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(project, "ProjectService", _ForbiddenProjectService)
    monkeypatch.setattr(dna, "DnaRuleService", _ForbiddenDnaRuleService)

    app = create_app(
        settings=_settings(),
        configure_logs=False,
        load_env=False,
    )
    app.dependency_overrides[get_current_user_id] = _user_id
    app.dependency_overrides[get_db] = _db_session
    return TestClient(app)


def _validation_locations(response_json: dict[str, Any]) -> set[tuple[str, ...]]:
    return {
        tuple(str(part) for part in item.get("loc", ()))
        for item in response_json.get("detail", [])
        if isinstance(item, dict)
    }


def _assert_rejected_location(response_json: dict[str, Any], *loc: str) -> None:
    assert tuple(loc) in _validation_locations(response_json)


def test_project_create_rejects_unknown_body_fields_before_service(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Architecture map",
            "canvas_library": "excalidraw",
            "unexpected": "ignored-before-this-fix",
        },
    )

    assert response.status_code == 422
    _assert_rejected_location(response.json(), "body", "unexpected")


def test_project_update_rejects_unknown_body_fields_before_service(monkeypatch):
    client = _client(monkeypatch)

    response = client.put(
        "/api/v1/projects/project-1",
        json={
            "title": "Architecture map",
            "canvas_engine": "tldraw",
            "unexpected": "ignored-before-this-fix",
        },
    )

    assert response.status_code == 422
    _assert_rejected_location(response.json(), "body", "unexpected")


def test_dna_rules_rejects_unknown_top_level_fields_before_service(monkeypatch):
    client = _client(monkeypatch)

    response = client.put(
        "/api/v1/dna/rules",
        json={
            "structure": [],
            "style": [],
            "layout": [],
            "project_id": None,
            "unexpected": "ignored-before-this-fix",
        },
    )

    assert response.status_code == 422
    _assert_rejected_location(response.json(), "body", "unexpected")


def test_dna_rules_rejects_unknown_nested_rule_fields_before_service(monkeypatch):
    client = _client(monkeypatch)

    response = client.put(
        "/api/v1/dna/rules",
        json={
            "structure": [
                {
                    "rule_id": "rule-1",
                    "cabin_id": "structure",
                    "title": "Layered groups",
                    "preview": "Group related nodes into tiers.",
                    "source": "manual",
                    "enabled": True,
                    "pinned": False,
                    "usage_count": 0,
                    "updated_at": "2026-01-01T00:00:00Z",
                    "unexpected": "ignored-before-this-fix",
                }
            ],
        },
    )

    assert response.status_code == 422
    _assert_rejected_location(response.json(), "body", "structure", "0", "unexpected")
