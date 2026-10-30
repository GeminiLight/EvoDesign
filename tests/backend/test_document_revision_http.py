"""Exercise the read → edit → conflict contract with the real routes and database."""
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user_id
from app.application import create_app
from app.db.base import Base
from app.db.session import get_db


@pytest.mark.asyncio
async def test_two_initial_editors_cannot_silently_overwrite_each_other():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app(settings=SimpleNamespace(app_name="Revision test", app_version="test",
                     debug=False, cors_origins_list=[]), configure_logs=False, load_env=False)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user_id] = lambda: "local-test-user"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", trust_env=False) as client:
            created = await client.post("/api/v1/projects", json={"title": "Concurrency test"})
            project_id = created.json()["project_id"]
            initial = await client.patch("/api/v1/schema/sync", json={
                "project_id": project_id, "schema_patch": {"elements": [{"id": "initial"}]},
                "editor": "excalidraw", "create_snapshot": True, "version": 1,
            })
            snapshot_id = initial.json()["snapshot_id"]
            projects = (await client.get("/api/v1/projects")).json()["projects"]
            history = (await client.get(f"/api/v1/projects/{project_id}/snapshots")).json()
            assert projects[0]["version"] == history["project_version"] == initial.json()["version"]
            request = {"project_id": project_id, "base_snapshot_id": snapshot_id, "editor": "excalidraw",
                       "schema_patch": {"elements": [{"id": "editor-a"}]}, "version": projects[0]["version"]}
            first = await client.patch("/api/v1/schema/sync", json=request)
            assert first.status_code == 200
            second = await client.patch("/api/v1/schema/sync", json={**request,
                                        "schema_patch": {"elements": [{"id": "editor-b"}]}})
            assert second.status_code == 409
            saved = (await client.get(f"/api/v1/projects/{project_id}")).json()
            assert saved["latest_schema"] == request["schema_patch"]
            assert saved["version"] == first.json()["version"]
    finally:
        await engine.dispose()
