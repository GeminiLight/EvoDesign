from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import bootstrap as db_bootstrap


async def _project_columns(engine) -> list[str]:
    async with engine.connect() as connection:
        result = await connection.execute(text("PRAGMA table_info(projects)"))
        return [row[1] for row in result]


async def _sqlite_index_sql(engine, index_name: str) -> str | None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND name = :index_name"
            ),
            {"index_name": index_name},
        )
        return result.scalar_one_or_none()


async def _create_minimal_users_table(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE users ("
                "user_id VARCHAR(36) PRIMARY KEY, "
                "email VARCHAR(255) NOT NULL, "
                "auth_provider VARCHAR(50) NOT NULL DEFAULT 'email', "
                "external_id VARCHAR(255)"
                ")"
            )
        )


@pytest.mark.asyncio
async def test_ensure_project_version_column_adds_missing_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE projects (project_id VARCHAR(36) PRIMARY KEY)")
            )
            await connection.execute(
                text("INSERT INTO projects (project_id) VALUES ('project-1')")
            )

        await db_bootstrap.ensure_project_version_column(engine)

        assert "version" in await _project_columns(engine)
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT version FROM projects WHERE project_id = 'project-1'")
            )
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_user_provider_identity_index_adds_missing_index():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await _create_minimal_users_table(engine)

        await db_bootstrap.ensure_user_provider_identity_index(engine)

        index_sql = await _sqlite_index_sql(
            engine,
            db_bootstrap.USER_PROVIDER_IDENTITY_INDEX,
        )
        assert index_sql is not None
        assert "UNIQUE INDEX" in index_sql
        assert "auth_provider, external_id" in index_sql
        assert "WHERE external_id IS NOT NULL" in index_sql
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_user_provider_identity_index_rejects_duplicate_provider_ids():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await _create_minimal_users_table(engine)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (user_id, email, auth_provider, external_id) "
                    "VALUES "
                    "('user-1', 'ada@example.com', 'google', 'google-1'), "
                    "('user-2', 'other@example.com', 'google', 'google-1')"
                )
            )

        with pytest.raises(RuntimeError, match="duplicate users"):
            await db_bootstrap.ensure_user_provider_identity_index(engine)

        assert await _sqlite_index_sql(
            engine,
            db_bootstrap.USER_PROVIDER_IDENTITY_INDEX,
        ) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_project_version_column_preserves_existing_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE projects ("
                    "project_id VARCHAR(36) PRIMARY KEY, "
                    "version INTEGER NOT NULL DEFAULT 7"
                    ")"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (project_id, version) "
                    "VALUES ('project-1', 5)"
                )
            )

        await db_bootstrap.ensure_project_version_column(engine)

        assert "version" in await _project_columns(engine)
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT version FROM projects WHERE project_id = 'project-1'")
            )
            assert result.scalar_one() == 5
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_project_version_column_does_not_mask_introspection_errors(
    monkeypatch,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    def fail_column_check(*args, **kwargs):
        raise RuntimeError("introspection failed")

    monkeypatch.setattr(db_bootstrap, "_has_table_column", fail_column_check)
    try:
        with pytest.raises(RuntimeError, match="introspection failed"):
            await db_bootstrap.ensure_project_version_column(engine)
    finally:
        await engine.dispose()
