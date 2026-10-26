from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import (
    get_current_auth,
    get_current_user_id,
    get_current_user_id_or_none,
    get_current_user_or_guest,
)
from app.core.security import create_access_token
from app.services.auth_token_service import (
    AuthTokenUserNotFoundError,
    InvalidAuthTokenError,
    InvalidTokenPayloadError,
)


def _settings(**overrides):
    data = {
        "jwt_secret": "test-jwt-secret-for-auth-deps",
        "jwt_algorithm": "HS256",
        "jwt_expires_in": 300,
        "guest_token": "guest-token",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


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
async def test_get_current_auth_rejects_missing_credentials():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_auth(
            credentials=None,
            db=_Db(_user()),
            settings=_settings(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Authentication token not provided"


@pytest.mark.asyncio
async def test_get_current_auth_returns_user_and_bearer_token():
    settings = _settings()
    token = create_access_token({"user_id": "user-1"}, settings=settings)
    db = _Db(_user("user-1"))

    auth_context = await get_current_auth(
        credentials=_credentials(token),
        db=db,
        settings=settings,
    )

    assert auth_context.token == token
    assert auth_context.user.user_id == "user-1"
    assert auth_context.is_guest is False
    assert db.executed is True


@pytest.mark.asyncio
async def test_get_current_auth_rejects_missing_database_user():
    settings = _settings()
    token = create_access_token({"user_id": "missing-user"}, settings=settings)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_auth(
            credentials=_credentials(token),
            db=_Db(None),
            settings=settings,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired authentication token"
    assert isinstance(exc_info.value.__cause__, AuthTokenUserNotFoundError)


@pytest.mark.asyncio
async def test_get_current_auth_hides_invalid_payload_details():
    settings = _settings()
    token = create_access_token({"email": "ada@example.com"}, settings=settings)
    db = _Db(_user())

    with pytest.raises(HTTPException) as exc_info:
        await get_current_auth(
            credentials=_credentials(token),
            db=db,
            settings=settings,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired authentication token"
    assert isinstance(exc_info.value.__cause__, InvalidTokenPayloadError)
    assert db.executed is False


@pytest.mark.asyncio
async def test_get_current_user_or_guest_accepts_configured_guest_token():
    db = _Db(_user())

    current_user = await get_current_user_or_guest(
        credentials=_credentials("guest-token"),
        db=db,
        settings=_settings(),
    )

    assert current_user is None
    assert db.executed is False


@pytest.mark.asyncio
async def test_get_current_user_or_guest_rejects_missing_credentials():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_or_guest(
            credentials=None,
            db=_Db(_user()),
            settings=_settings(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Authentication token not provided"


@pytest.mark.asyncio
async def test_get_current_user_or_guest_rejects_wrong_guest_token_as_invalid_jwt():
    db = _Db(_user())

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_or_guest(
            credentials=_credentials("wrong-guest-token"),
            db=db,
            settings=_settings(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired authentication token"
    assert isinstance(exc_info.value.__cause__, InvalidAuthTokenError)
    assert db.executed is False


@pytest.mark.asyncio
async def test_get_current_user_or_guest_returns_user_for_normal_jwt():
    settings = _settings()
    token = create_access_token({"user_id": "user-1"}, settings=settings)
    db = _Db(_user("user-1"))

    current_user = await get_current_user_or_guest(
        credentials=_credentials(token),
        db=db,
        settings=settings,
    )

    assert current_user.user_id == "user-1"
    assert db.executed is True


@pytest.mark.asyncio
async def test_user_id_dependencies_reuse_resolved_user_objects():
    user = _user("user-1")

    assert await get_current_user_id(user) == "user-1"
    assert await get_current_user_id_or_none(user) == "user-1"
    assert await get_current_user_id_or_none(None) is None
