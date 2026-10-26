from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import EmailAlreadyExistsException
from app.db.base import Base
from app.models import User  # noqa: F401
from app.services.auth_service import AuthService, OAuthAccountLinkRequiredError


def _settings():
    return SimpleNamespace(
        enable_signup_verification=False,
        signup_verification_code="",
        jwt_secret="test-jwt-secret-for-auth-service",
        jwt_algorithm="HS256",
        jwt_expires_in=300,
    )


async def _create_session(database_url: str = "sqlite+aiosqlite:///:memory:"):
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory, session_factory()


@pytest.mark.asyncio
async def test_register_stores_canonical_email_and_default_username():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())

        user = await service.register(" Ada@Example.COM ", "correct-password")

        assert user.email == "ada@example.com"
        assert user.username == "ada"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_login_uses_canonical_email_lookup():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())
        await service.register("ada@example.com", "correct-password")

        user = await service.login(" ADA@Example.COM ", "correct-password")

        assert user.email == "ada@example.com"
        assert user.last_login_at is not None
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_register_rejects_canonical_email_duplicates():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())
        await service.register("ada@example.com", "correct-password")

        with pytest.raises(EmailAlreadyExistsException):
            await service.register(" ADA@Example.COM ", "correct-password")
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_oauth_user_does_not_rebind_existing_email_user():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())
        existing_user = await service.create_user(
            email="ada@example.com",
            username="Ada",
            password="correct-password",
            auth_provider="email",
        )
        original_password_hash = existing_user.password_hash

        with pytest.raises(OAuthAccountLinkRequiredError) as exc_info:
            await service.upsert_oauth_user(
                email="ada@example.com",
                username="Ada OAuth",
                avatar_url="https://example.test/avatar.png",
                auth_provider="google",
                external_id="google-1",
            )

        assert exc_info.value.email == "ada@example.com"
        await session.refresh(existing_user)
        assert existing_user.auth_provider == "email"
        assert existing_user.external_id is None
        assert existing_user.username == "Ada"
        assert existing_user.password_hash == original_password_hash
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_oauth_user_updates_existing_provider_identity():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())
        user = await service.create_user(
            email="ada@example.com",
            username="Ada",
            avatar_url=None,
            auth_provider="google",
            external_id="google-1",
        )

        result = await service.upsert_oauth_user(
            email="changed@example.com",
            username="Ada Lovelace",
            avatar_url="https://example.test/avatar.png",
            auth_provider="google",
            external_id="google-1",
        )

        assert result.user_id == user.user_id
        assert result.email == "ada@example.com"
        assert result.auth_provider == "google"
        assert result.external_id == "google-1"
        assert result.username == "Ada Lovelace"
        assert result.avatar_url == "https://example.test/avatar.png"
        assert result.last_login_at is not None
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_oauth_user_creates_new_provider_identity():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())

        user = await service.upsert_oauth_user(
            email=" Grace@Example.COM ",
            username="Grace",
            avatar_url=None,
            auth_provider="github",
            external_id="github-1",
        )

        assert user.email == "grace@example.com"
        assert user.username == "Grace"
        assert user.auth_provider == "github"
        assert user.external_id == "github-1"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_oauth_user_reports_canonical_email_conflict():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())
        existing_user = await service.create_user(
            email="ada@example.com",
            username="Ada",
            password="correct-password",
            auth_provider="email",
        )

        with pytest.raises(OAuthAccountLinkRequiredError) as exc_info:
            await service.upsert_oauth_user(
                email=" ADA@Example.COM ",
                username="Ada OAuth",
                avatar_url=None,
                auth_provider="google",
                external_id="google-1",
            )

        assert exc_info.value.email == "ada@example.com"
        await session.refresh(existing_user)
        assert existing_user.auth_provider == "email"
        assert existing_user.external_id is None
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_identity_unique_index_rejects_duplicate_users():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())
        await service.create_user(
            email="ada@example.com",
            username="Ada",
            auth_provider="google",
            external_id="google-1",
        )

        with pytest.raises(IntegrityError):
            await service.create_user(
                email="other@example.com",
                username="Other",
                auth_provider="google",
                external_id="google-1",
            )
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_identity_unique_index_allows_email_users_without_external_id():
    engine, _, session = await _create_session()
    try:
        service = AuthService(session, settings=_settings())

        first = await service.create_user(
            email="ada@example.com",
            username="Ada",
            password="correct-password",
            auth_provider="email",
        )
        second = await service.create_user(
            email="grace@example.com",
            username="Grace",
            password="correct-password",
            auth_provider="email",
        )

        assert first.external_id is None
        assert second.external_id is None
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_oauth_user_recovers_provider_identity_race(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'auth-race.db'}"
    engine, session_factory, session = await _create_session(database_url)
    try:
        service = AuthService(session, settings=_settings())

        async def racing_create_user(**kwargs):
            async with session_factory() as other_session:
                other_service = AuthService(other_session, settings=_settings())
                await other_service.create_user(**kwargs)
                await other_session.commit()
            raise IntegrityError("insert user", {}, Exception("duplicate provider identity"))

        service.create_user = racing_create_user

        user = await service.upsert_oauth_user(
            email="grace@example.com",
            username="Grace",
            avatar_url=None,
            auth_provider="github",
            external_id="github-1",
        )

        assert user.email == "grace@example.com"
        assert user.auth_provider == "github"
        assert user.external_id == "github-1"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_register_maps_a_concurrent_email_insert_to_a_conflict(tmp_path):
    """The check-then-insert race must surface as 409, not an unhandled 500."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'register-race.db'}"
    engine, session_factory, session = await _create_session(database_url)
    try:
        service = AuthService(session, settings=_settings())

        async def racing_create_user(**kwargs):
            async with session_factory() as other_session:
                other_service = AuthService(other_session, settings=_settings())
                await other_service.create_user(**kwargs)
                await other_session.commit()
            raise IntegrityError("insert user", {}, Exception("duplicate email"))

        service.create_user = racing_create_user

        with pytest.raises(EmailAlreadyExistsException):
            await service.register("grace@example.com", "correct-password")
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_register_does_not_swallow_unrelated_integrity_errors(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'register-integrity.db'}"
    engine, _, session = await _create_session(database_url)
    try:
        service = AuthService(session, settings=_settings())

        async def failing_create_user(**kwargs):
            raise IntegrityError("insert user", {}, Exception("unrelated constraint"))

        service.create_user = failing_create_user

        with pytest.raises(IntegrityError):
            await service.register("grace@example.com", "correct-password")
    finally:
        await session.close()
        await engine.dispose()
