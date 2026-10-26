from __future__ import annotations

import httpx
import pytest

from app.services.oauth_profile_service import (
    OAuthProfileError,
    OAuthProfileService,
    normalize_github_profile,
    normalize_google_profile,
)


def test_normalize_google_profile_requires_core_identity_fields():
    profile = normalize_google_profile(
        {
            "email": "ada@example.com",
            "name": "Ada Lovelace",
            "id": "google-123",
            "picture": "https://example.com/avatar.png",
            "verified_email": True,
        }
    )

    assert profile.email == "ada@example.com"
    assert profile.email_verified is True
    assert profile.username == "Ada Lovelace"
    assert profile.provider_id == "google-123"
    assert profile.avatar_url == "https://example.com/avatar.png"


def test_normalize_google_profile_rejects_missing_email():
    with pytest.raises(OAuthProfileError, match="email"):
        normalize_google_profile({"name": "Ada Lovelace", "id": "google-123"})


def test_normalize_google_profile_rejects_unverified_email():
    with pytest.raises(OAuthProfileError, match="not verified"):
        normalize_google_profile(
            {
                "email": "ada@example.com",
                "name": "Ada Lovelace",
                "id": "google-123",
                "verified_email": False,
            }
        )


def test_normalize_github_profile_uses_primary_verified_email():
    profile = normalize_github_profile(
        {
            "id": 42,
            "login": "octo",
            "name": "Octo Cat",
            "email": "public@example.com",
            "avatar_url": "https://example.com/octo.png",
        },
        [
            {"email": "secondary@example.com", "primary": False, "verified": True},
            {"email": "primary@example.com", "primary": True, "verified": True},
        ],
    )

    assert profile.email == "primary@example.com"
    assert profile.email_verified is True
    assert profile.username == "Octo Cat"
    assert profile.provider_id == "42"
    assert profile.avatar_url == "https://example.com/octo.png"


def test_normalize_github_profile_uses_any_verified_email_when_primary_is_unverified():
    profile = normalize_github_profile(
        {"id": 42, "login": "octo", "name": None, "email": None},
        [
            {"email": "primary@example.com", "primary": True, "verified": False},
            {"email": "secondary@example.com", "primary": False, "verified": True},
        ],
    )

    assert profile.email == "secondary@example.com"
    assert profile.username == "octo"


def test_normalize_github_profile_rejects_missing_verified_email():
    with pytest.raises(OAuthProfileError, match="verified email"):
        normalize_github_profile(
            {"id": 42, "login": "octo", "name": "", "email": None},
            [{"email": "primary@example.com", "primary": True, "verified": False}],
        )


def test_normalize_github_profile_rejects_missing_login():
    with pytest.raises(OAuthProfileError, match="login"):
        normalize_github_profile({"id": 42}, [])


class _FakeResponse:
    def __init__(self, *, payload=None, json_error: Exception | None = None):
        self.payload = payload
        self.json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class _SequencedAsyncClient:
    responses = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers):
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_fetch_google_profile_wraps_provider_http_errors(monkeypatch):
    class FailingAsyncClient(_SequencedAsyncClient):
        async def get(self, url, headers):
            raise httpx.ConnectError("provider secret token")

    monkeypatch.setattr(httpx, "AsyncClient", FailingAsyncClient)

    with pytest.raises(OAuthProfileError) as exc_info:
        await OAuthProfileService().fetch_google_profile("access-token")

    assert str(exc_info.value) == "Google profile fetch failed"
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)
    assert "secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_google_profile_wraps_invalid_json(monkeypatch):
    _SequencedAsyncClient.responses = [
        _FakeResponse(json_error=ValueError("provider secret json")),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _SequencedAsyncClient)

    with pytest.raises(OAuthProfileError) as exc_info:
        await OAuthProfileService().fetch_google_profile("access-token")

    assert str(exc_info.value) == "Invalid Google profile payload"
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_github_profile_wraps_provider_http_errors(monkeypatch):
    class FailingAsyncClient(_SequencedAsyncClient):
        async def get(self, url, headers):
            raise httpx.ConnectError("provider secret token")

    monkeypatch.setattr(httpx, "AsyncClient", FailingAsyncClient)

    with pytest.raises(OAuthProfileError) as exc_info:
        await OAuthProfileService().fetch_github_profile("access-token")

    assert str(exc_info.value) == "GitHub profile fetch failed"
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)
    assert "secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_github_profile_wraps_invalid_json(monkeypatch):
    _SequencedAsyncClient.responses = [
        _FakeResponse(
            payload={
                "id": 42,
                "login": "octo",
                "name": "Octo Cat",
                "avatar_url": None,
            }
        ),
        _FakeResponse(json_error=ValueError("provider secret json")),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _SequencedAsyncClient)

    with pytest.raises(OAuthProfileError) as exc_info:
        await OAuthProfileService().fetch_github_profile("access-token")

    assert str(exc_info.value) == "Invalid GitHub profile payload"
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "secret" not in str(exc_info.value)
