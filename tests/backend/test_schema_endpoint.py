from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints import schema as schema_endpoint
from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
)
from app.schemas.schema import SchemaSyncRequest
from app.services.schema_service import (
    BaseSnapshotRequiredError,
    SchemaSyncError,
    VersionConflictError,
)


def _request() -> SchemaSyncRequest:
    return SchemaSyncRequest(
        project_id="project-1",
        schema_patch={"elements": []},
        create_snapshot=True,
    )


def test_schema_sync_request_rejects_unknown_editor():
    with pytest.raises(ValidationError):
        SchemaSyncRequest(
            project_id="project-1",
            schema_patch={"records": {}},
            editor="legacy-editor",
            create_snapshot=True,
        )


@pytest.mark.asyncio
async def test_sync_schema_endpoint_delegates_request_contract(monkeypatch):
    calls = []

    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            calls.append((self.db, kwargs))
            return (
                SimpleNamespace(
                    project_id="project-1",
                    latest_schema={"elements": [{"id": "node-1"}]},
                    version=8,
                ),
                SimpleNamespace(snapshot_id="snapshot-1"),
            )

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    request = SchemaSyncRequest(
        project_id="project-1",
        schema_patch={"elements": [{"id": "node-1"}]},
        editor="tldraw",
        base_snapshot_id="snapshot-base",
        create_snapshot=False,
        version=7,
    )

    response = await schema_endpoint.sync_schema(request, user_id="user-1", db="db")

    assert calls == [
        (
            "db",
            {
                "user_id": "user-1",
                "project_id": "project-1",
                "schema_patch": {"elements": [{"id": "node-1"}]},
                "editor": "tldraw",
                "base_snapshot_id": "snapshot-base",
                "create_snapshot": False,
                "version": 7,
            },
        )
    ]
    assert response.project_id == "project-1"
    assert response.snapshot_id == "snapshot-1"
    assert response.latest_schema == {"elements": [{"id": "node-1"}]}
    assert response.edit_source == "HUMAN"
    assert response.version == 8


def test_schema_sync_error_mappings_include_project_not_found_and_base_errors():
    error_types = tuple(
        mapping.error_type
        for mapping in schema_endpoint.SCHEMA_SYNC_ERROR_POLICY.mappings
    )

    assert ProjectNotFoundException in error_types
    assert SchemaSyncError in error_types


@pytest.mark.asyncio
async def test_sync_schema_endpoint_maps_project_not_found_to_404(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise ProjectNotFoundException(
                public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            )

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == LOWERCASE_PROJECT_NOT_FOUND_DETAIL


@pytest.mark.asyncio
async def test_sync_schema_endpoint_hides_project_not_found_details(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise ProjectNotFoundException(
                "project secret-id missing for user-1",
                public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
            )

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == LOWERCASE_PROJECT_NOT_FOUND_DETAIL
    assert "secret-id" not in exc_info.value.detail
    assert "user-1" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_sync_schema_endpoint_maps_version_conflict_to_409(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise VersionConflictError("version conflict")

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "version conflict"


@pytest.mark.asyncio
async def test_sync_schema_endpoint_hides_version_conflict_details(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise VersionConflictError("version conflict for secret-snapshot")

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "version conflict"
    assert "secret-snapshot" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_sync_schema_endpoint_maps_schema_sync_errors_to_400(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise BaseSnapshotRequiredError()

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "base snapshot id required for overwrite"


@pytest.mark.asyncio
async def test_sync_schema_endpoint_uses_instance_public_detail(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise SchemaSyncError(
                "internal schema secret",
                public_detail="public schema issue",
            )

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "public schema issue"
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_sync_schema_endpoint_hides_base_schema_sync_error_details(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise SchemaSyncError("internal schema secret")

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "schema sync failed"
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_sync_schema_endpoint_hides_unexpected_error_details(monkeypatch):
    class FakeSchemaService:
        def __init__(self, db):
            self.db = db

        async def sync_schema(self, **kwargs):
            raise RuntimeError("database password leaked")

    monkeypatch.setattr(schema_endpoint, "SchemaService", FakeSchemaService)

    with pytest.raises(HTTPException) as exc_info:
        await schema_endpoint.sync_schema(_request(), user_id="user-1", db=object())

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "schema sync failed"
    assert "password" not in exc_info.value.detail
