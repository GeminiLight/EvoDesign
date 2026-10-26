from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import (
    LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    ProjectNotFoundException,
)
from app.db.base import Base
from app.models import DnaRule, OAuthCode, Project, Snapshot, Subscription, User  # noqa: F401
from app.services.schema_service import (
    BaseSnapshotNotFoundError,
    BaseSnapshotRequiredError,
    InvalidSchemaEditorError,
    InvalidProjectSchemaError,
    InvalidSchemaPatchError,
    ProjectUpdateFailedError,
    SchemaService,
    SchemaSyncError,
    VersionConflictError,
)


async def _create_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory()


async def _create_project(session, **overrides) -> Project:
    data = {
        "user_id": "user-1",
        "title": "Project",
        "diagram_type": "automated",
        "canvas_engine": "excalidraw",
        "source_text": "A flows to B",
        "latest_schema": {"elements": []},
        "version": 1,
    }
    data.update(overrides)
    project = Project(**data)
    session.add(project)
    await session.flush()
    return project


@pytest.mark.parametrize(
    ("exception_cls", "public_detail"),
    [
        (SchemaSyncError, "schema sync failed"),
        (InvalidSchemaPatchError, "schema_patch must be an object"),
        (InvalidProjectSchemaError, "project latest_schema is invalid"),
        (InvalidSchemaEditorError, "unsupported editor"),
        (BaseSnapshotRequiredError, "base snapshot id required for overwrite"),
        (BaseSnapshotNotFoundError, "base snapshot not found"),
        (ProjectUpdateFailedError, "project update failed"),
        (VersionConflictError, "version conflict"),
    ],
)
def test_schema_sync_errors_keep_internal_messages_private(
    exception_cls,
    public_detail,
):
    exc = exception_cls("internal schema secret")

    assert str(exc) == "internal schema secret"
    assert exc.public_detail == public_detail
    assert "secret" not in exc.public_detail


def test_schema_project_not_found_uses_core_project_exception_family():
    exc = ProjectNotFoundException(
        "project secret-id missing for user-1",
        public_detail=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
    )

    assert exc.public_detail == LOWERCASE_PROJECT_NOT_FOUND_DETAIL
    assert "secret-id" not in exc.public_detail
    assert "user-1" not in exc.public_detail


@pytest.mark.asyncio
async def test_sync_schema_create_snapshot_replaces_editor_schema_and_bumps_version():
    engine, session = await _create_session()
    try:
        project = await _create_project(session)
        service = SchemaService(session)

        updated_project, snapshot = await service.sync_schema(
            user_id="user-1",
            project_id=project.project_id,
            schema_patch={"elements": [{"id": "n1"}]},
            editor="excalidraw",
            create_snapshot=True,
            version=1,
        )

        assert updated_project.version == 2
        assert updated_project.latest_schema == {"elements": [{"id": "n1"}]}
        assert snapshot.schema_blob == {"elements": [{"id": "n1"}]}
        assert snapshot.parent_id is None
        assert json.loads(snapshot.thought_trace) == {
            "editor": "excalidraw",
            "action": "schema_sync",
            "mode": "create",
        }
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("create_snapshot", [False, True])
async def test_edit_marks_generation_assessment_stale_without_losing_provenance(create_snapshot):
    engine, session = await _create_session()
    try:
        project = await _create_project(session)
        metrics = {"generation": {"quality_status": "passed", "after": {"score": 9},
                                  "total_duration_ms": 12000}}
        original = Snapshot(project_id=project.project_id, schema_blob=project.latest_schema,
                            edit_source="AI_GEN", metrics_scores=metrics, thought_trace="{}")
        session.add(original)
        await session.flush()
        _, snapshot = await SchemaService(session).sync_schema(
            "user-1", project.project_id, {"elements": [{"id": "edited"}]},
            editor="excalidraw", base_snapshot_id=original.snapshot_id, version=1,
            create_snapshot=create_snapshot,
        )
        assert snapshot.metrics_scores["generation"]["quality_status"] == "edited"
        assert snapshot.metrics_scores["generation"]["after"]["score"] == 9
        assert metrics["generation"]["quality_status"] == "passed"
        if create_snapshot:
            assert snapshot.parent_id == original.snapshot_id
            assert original.metrics_scores["generation"]["quality_status"] == "passed"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_replace_editor_updates_project_canvas_engine():
    engine, session = await _create_session()
    try:
        project = await _create_project(
            session,
            canvas_engine="excalidraw",
            latest_schema={"elements": []},
        )
        service = SchemaService(session)

        updated_project, snapshot = await service.sync_schema(
            user_id="user-1",
            project_id=project.project_id,
            schema_patch={"document": {"id": "page:1"}, "records": {}},
            editor="tldraw",
            create_snapshot=True,
            version=1,
        )

        assert updated_project.canvas_engine == "tldraw"
        assert updated_project.latest_schema == {
            "document": {"id": "page:1"},
            "records": {},
        }
        assert snapshot.schema_blob == updated_project.latest_schema
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_overwrite_applies_json_merge_patch_to_base_snapshot():
    engine, session = await _create_session()
    try:
        project = await _create_project(
            session,
            latest_schema={"a": 1, "b": {"c": 2, "d": 3}},
        )
        base_snapshot = Snapshot(
            project_id=project.project_id,
            schema_blob=project.latest_schema,
            edit_source="AI_GEN",
            thought_trace="{}",
            metrics_scores={},
        )
        session.add(base_snapshot)
        await session.flush()

        service = SchemaService(session)
        updated_project, updated_snapshot = await service.sync_schema(
            user_id="user-1",
            project_id=project.project_id,
            schema_patch={"b": {"c": None}, "e": 4},
            editor="manual",
            base_snapshot_id=base_snapshot.snapshot_id,
            create_snapshot=False,
            version=1,
        )

        assert updated_project.version == 2
        assert updated_project.latest_schema == {"a": 1, "b": {"d": 3}, "e": 4}
        assert updated_project.canvas_engine == "excalidraw"
        assert updated_snapshot.snapshot_id == base_snapshot.snapshot_id
        assert updated_snapshot.schema_blob == {"a": 1, "b": {"d": 3}, "e": 4}
        assert json.loads(updated_snapshot.thought_trace)["mode"] == "overwrite"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_rejects_unknown_editor_before_project_lookup():
    service = SchemaService(db=object())

    with pytest.raises(InvalidSchemaEditorError, match="unsupported editor"):
        await service.sync_schema(
            user_id="user-1",
            project_id="project-1",
            schema_patch={"records": {"shape:1": {"id": "shape:1"}}},
            editor="legacy-editor",
            create_snapshot=True,
        )


@pytest.mark.asyncio
async def test_sync_schema_manual_patch_keeps_records_key_as_merge_patch():
    engine, session = await _create_session()
    try:
        project = await _create_project(
            session,
            latest_schema={
                "records": {"shape:old": {"id": "shape:old"}},
                "metadata": {"keep": True},
            },
        )
        base_snapshot = Snapshot(
            project_id=project.project_id,
            schema_blob=project.latest_schema,
            edit_source="AI_GEN",
            thought_trace="{}",
            metrics_scores={},
        )
        session.add(base_snapshot)
        await session.flush()

        service = SchemaService(session)
        updated_project, updated_snapshot = await service.sync_schema(
            user_id="user-1",
            project_id=project.project_id,
            schema_patch={"records": {"shape:new": {"id": "shape:new"}}},
            editor="manual",
            base_snapshot_id=base_snapshot.snapshot_id,
            create_snapshot=False,
            version=1,
        )

        assert updated_project.latest_schema == {
            "records": {
                "shape:old": {"id": "shape:old"},
                "shape:new": {"id": "shape:new"},
            },
            "metadata": {"keep": True},
        }
        assert updated_snapshot.schema_blob == updated_project.latest_schema
        assert json.loads(updated_snapshot.thought_trace) == {
            "editor": "manual",
            "action": "schema_sync",
            "mode": "overwrite",
        }
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_rejects_project_owned_by_another_user():
    engine, session = await _create_session()
    try:
        project = await _create_project(session, user_id="other-user")
        service = SchemaService(session)

        with pytest.raises(
            ProjectNotFoundException,
            match=LOWERCASE_PROJECT_NOT_FOUND_DETAIL,
        ):
            await service.sync_schema(
                user_id="user-1",
                project_id=project.project_id,
                schema_patch={"elements": []},
                create_snapshot=True,
            )
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_rejects_non_object_patch():
    engine, session = await _create_session()
    try:
        project = await _create_project(session)
        service = SchemaService(session)

        with pytest.raises(InvalidSchemaPatchError, match="schema_patch must be an object"):
            await service.sync_schema(
                user_id="user-1",
                project_id=project.project_id,
                schema_patch=["not", "an", "object"],
                create_snapshot=True,
            )
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_requires_base_snapshot_for_overwrite_mode():
    engine, session = await _create_session()
    try:
        project = await _create_project(session)
        service = SchemaService(session)

        with pytest.raises(BaseSnapshotRequiredError, match="base snapshot id required"):
            await service.sync_schema(
                user_id="user-1",
                project_id=project.project_id,
                schema_patch={"elements": []},
                create_snapshot=False,
            )
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_rejects_base_snapshot_outside_project():
    engine, session = await _create_session()
    try:
        project = await _create_project(session)
        service = SchemaService(session)

        with pytest.raises(BaseSnapshotNotFoundError, match="base snapshot not found"):
            await service.sync_schema(
                user_id="user-1",
                project_id=project.project_id,
                schema_patch={"elements": []},
                base_snapshot_id="missing-snapshot",
                create_snapshot=False,
            )
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_schema_raises_typed_version_conflict():
    engine, session = await _create_session()
    try:
        project = await _create_project(session, version=3)
        service = SchemaService(session)

        with pytest.raises(VersionConflictError, match="expected 2"):
            await service.sync_schema(
                user_id="user-1",
                project_id=project.project_id,
                schema_patch={"elements": [{"id": "n1"}]},
                editor="excalidraw",
                create_snapshot=True,
                version=2,
            )
    finally:
        await session.close()
        await engine.dispose()
