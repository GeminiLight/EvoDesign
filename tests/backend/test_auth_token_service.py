from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import DnaRule, OAuthCode, Project, Snapshot, Subscription, User  # noqa: F401
from app.services.auth_token_service import (
    AuthTokenService,
    AuthTokenUserNotFoundError,
    InvalidAuthTokenError,
    InvalidTokenPayloadError,
)


def _settings():
    return SimpleNamespace(
        jwt_secret="test-jwt-secret",
        jwt_algorithm="HS256",
        jwt_expires_in=60,
    )


def _user(user_id: str = "user-1"):
    return SimpleNamespace(
        user_id=user_id,
        email="ada@example.com",
        username="Ada",
        avatar_url=None,
        auth_provider="email",
        created_at=datetime(2026, 1, 1),
    )


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Db:
    def __init__(self, user):
        self.user = user
        self.executed = False

    async def execute(self, statement):
        self.executed = True
        return _Result(self.user)


@pytest.mark.asyncio
async def test_resolve_user_returns_database_user():
    user = _user()
    db = _Db(user)
    service = AuthTokenService(
        db,
        settings=_settings(),
        token_verifier=lambda token, settings: {"user_id": "user-1"},
    )

    resolved = await service.resolve_user("jwt-token")

    assert resolved is user
    assert db.executed is True


@pytest.mark.asyncio
async def test_resolve_user_rejects_invalid_token_without_database_query():
    db = _Db(_user())
    service = AuthTokenService(
        db,
        settings=_settings(),
        token_verifier=lambda token, settings: None,
    )

    with pytest.raises(InvalidAuthTokenError, match="Invalid or expired"):
        await service.resolve_user("jwt-token")

    assert db.executed is False


@pytest.mark.asyncio
async def test_resolve_user_rejects_token_without_user_id():
    db = _Db(_user())
    service = AuthTokenService(
        db,
        settings=_settings(),
        token_verifier=lambda token, settings: {"email": "ada@example.com"},
    )

    with pytest.raises(InvalidTokenPayloadError, match="Invalid token payload"):
        await service.resolve_user("jwt-token")

    assert db.executed is False


@pytest.mark.asyncio
async def test_resolve_user_rejects_missing_database_user():
    db = _Db(None)
    service = AuthTokenService(
        db,
        settings=_settings(),
        token_verifier=lambda token, settings: {"user_id": "missing"},
    )

    with pytest.raises(AuthTokenUserNotFoundError, match="User not found"):
        await service.resolve_user("jwt-token")

    assert db.executed is True


@pytest.mark.asyncio
async def test_resolving_a_bearer_token_does_not_load_projects_or_snapshots():
    """Every authenticated request resolves a user; it must not read the graphs."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        session.add(User(user_id="user-1", email="ada@example.com"))
        session.add(Subscription(user_id="user-1", status="active"))
        session.add(Project(project_id="project-1", user_id="user-1"))
        session.add(
            Snapshot(
                snapshot_id="snap-1",
                project_id="project-1",
                schema_blob={"elements": [{"id": "n1"}]},
                edit_source="AI_GEN",
            )
        )
        await session.commit()
        session.expunge_all()
        statements.clear()

        user = await AuthTokenService(
            session,
            settings=_settings(),
            token_verifier=lambda token, settings: {"user_id": "user-1"},
        ).resolve_user("bearer-token")

        assert user.user_id == "user-1"
        # The billing tier lookup still resolves without a lazy load.
        assert user.subscription is not None
        assert not any("FROM projects" in statement for statement in statements)
        assert not any("FROM snapshots" in statement for statement in statements)
    finally:
        await session.close()
        await engine.dispose()
