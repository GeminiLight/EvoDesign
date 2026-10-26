from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps import AuthContext
from app.api.v1.endpoints import auth
from app.api.v1.endpoints.auth import (
    exchange_oauth_code,
    get_current_user_info,
    google_login,
    github_login,
    github_callback,
    google_callback,
)
from app.schemas.auth import CodeExchangeRequest
from app.services.oauth_session_service import (
    OAUTH_STATE_COOKIE_NAME,
    OAUTH_STATE_COOKIE_PATH,
    OAUTH_STATE_TTL_SECONDS,
    InvalidOAuthCodeError,
    OAuthAuthorizationRedirect,
    OAuthCallbackError,
    OAuthProviderNotConfiguredError,
    OAuthStateConsumption,
    OAuthStateError,
    OAuthTokenValidationError,
)


CALLBACK_STATE = "login-state"
CALLBACK_STATE_COOKIE = "login-state.100.signature"


class _AcceptsCallbackState:
    """Callback fakes take the state pair; rejection has dedicated tests."""

    def consume_oauth_state(self, *, provider, state, state_cookie):
        self.consumed_state = (provider, state, state_cookie)
        return OAuthStateConsumption(
            remaining_state_cookie=None,
            state_cookie_secure=False,
        )


async def _call_oauth_callback(handler, **overrides):
    kwargs = {
        "code": "provider-code",
        "state": CALLBACK_STATE,
        "state_cookie": CALLBACK_STATE_COOKIE,
        "db": object(),
        "settings": object(),
    }
    kwargs.update(overrides)
    return await handler(**kwargs)


def _set_cookie_headers(response) -> list[str]:
    return [
        value.decode()
        for key, value in response.raw_headers
        if key.decode().lower() == "set-cookie"
    ]


def _user():
    return SimpleNamespace(
        user_id="user-1",
        email="ada@example.com",
        username="Ada",
        avatar_url=None,
        auth_provider="email",
        created_at=datetime(2026, 1, 1),
    )


@pytest.mark.asyncio
async def test_get_current_user_info_returns_resolved_auth_context_token():
    response = await get_current_user_info(
        auth_context=AuthContext(token="jwt-token", user=_user()),
    )

    assert response.token == "jwt-token"
    assert response.user.user_id == "user-1"
    assert response.user.email == "ada@example.com"


@pytest.mark.asyncio
async def test_google_callback_redirects_to_service_success_url(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def complete_provider_callback(self, provider: str, code: str):
            assert provider == "google"
            assert code == "provider-code"
            return "http://frontend.test/?code=exchange-code"

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    response = await _call_oauth_callback(google_callback)

    assert response.headers["location"] == "http://frontend.test/?code=exchange-code"


@pytest.mark.asyncio
async def test_github_callback_maps_provider_configuration_errors(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def complete_provider_callback(self, provider: str, code: str):
            raise OAuthProviderNotConfiguredError("GitHub OAuth not configured")

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await _call_oauth_callback(github_callback)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "OAuth provider is not configured."
    assert isinstance(exc_info.value.__cause__, OAuthProviderNotConfiguredError)
    assert "GitHub" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_google_login_maps_provider_configuration_errors(monkeypatch):
    class FakeOAuthSessionService:
        def __init__(self, *, settings):
            self.settings = settings

        async def build_authorization_redirect(
            self, provider: str, *, existing_state_cookie=None
        ):
            raise OAuthProviderNotConfiguredError(
                "Google client secret missing from runtime configuration"
            )

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await google_login(state_cookie=None, settings=object())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "OAuth provider is not configured."
    assert isinstance(exc_info.value.__cause__, OAuthProviderNotConfiguredError)
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("login_handler", "expected_provider", "expected_url"),
    [
        (google_login, "google", "https://provider.test/google"),
        (github_login, "github", "https://provider.test/github"),
    ],
)
async def test_oauth_login_redirects_to_provider_authorization_url(
    monkeypatch,
    login_handler,
    expected_provider,
    expected_url,
):
    class FakeOAuthSessionService:
        def __init__(self, *, settings):
            self.settings = settings
            self.existing_state_cookie = "unset"

        async def build_authorization_redirect(
            self, provider: str, *, existing_state_cookie=None
        ):
            assert provider == expected_provider
            self.existing_state_cookie = existing_state_cookie
            return OAuthAuthorizationRedirect(
                authorization_url=expected_url,
                state_cookie="login-state.100.signature",
                state_cookie_secure=False,
            )

    fake_service = FakeOAuthSessionService(settings=object())
    monkeypatch.setattr(
        auth, "OAuthSessionService", lambda *, settings: fake_service
    )

    response = await login_handler(
        state_cookie="pending-states-cookie",
        settings=object(),
    )

    assert response.headers["location"] == expected_url
    # Pending states from other tabs must reach the service for preservation.
    assert fake_service.existing_state_cookie == "pending-states-cookie"


@pytest.mark.asyncio
async def test_github_login_maps_provider_configuration_errors(monkeypatch):
    class FakeOAuthSessionService:
        def __init__(self, *, settings):
            self.settings = settings

        async def build_authorization_redirect(
            self, provider: str, *, existing_state_cookie=None
        ):
            assert provider == "github"
            raise OAuthProviderNotConfiguredError(
                "GitHub client secret missing from runtime configuration"
            )

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await github_login(state_cookie=None, settings=object())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "OAuth provider is not configured."
    assert isinstance(exc_info.value.__cause__, OAuthProviderNotConfiguredError)
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_google_login_uses_provider_error_public_detail(monkeypatch):
    class FakeOAuthSessionService:
        def __init__(self, *, settings):
            self.settings = settings

        async def build_authorization_redirect(
            self, provider: str, *, existing_state_cookie=None
        ):
            raise OAuthProviderNotConfiguredError(
                "Google client secret missing from runtime configuration",
                public_detail="OAuth temporarily unavailable.",
            )

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await google_login(state_cookie=None, settings=object())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "OAuth temporarily unavailable."
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_google_callback_maps_expected_oauth_errors_to_failure_redirect(
    monkeypatch,
):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def complete_provider_callback(self, provider: str, code: str):
            raise OAuthCallbackError("secret provider response")

        def failure_redirect_url(self, error: str = "oauth_failed"):
            return f"http://frontend.test/?error={error}"

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    response = await _call_oauth_callback(google_callback)

    assert response.headers["location"] == "http://frontend.test/?error=oauth_failed"
    assert "secret" not in response.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_preserves_account_link_required_redirect_error(
    monkeypatch,
):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def complete_provider_callback(self, provider: str, code: str):
            raise OAuthCallbackError(
                "Account linking required for this email",
                redirect_error="account_link_required",
            )

        def failure_redirect_url(self, error: str = "oauth_failed"):
            return f"http://frontend.test/?error={error}"

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    response = await _call_oauth_callback(google_callback)

    assert response.headers["location"] == (
        "http://frontend.test/?error=account_link_required"
    )


@pytest.mark.asyncio
async def test_github_callback_does_not_swallow_unexpected_errors(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def complete_provider_callback(self, provider: str, code: str):
            raise RuntimeError("unexpected database failure")

        def failure_redirect_url(self):
            return "http://frontend.test/?error=oauth_failed"

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(RuntimeError, match="unexpected database failure"):
        await _call_oauth_callback(github_callback)


@pytest.mark.asyncio
async def test_oauth_login_sets_signed_state_cookie_for_the_callback(monkeypatch):
    class FakeOAuthSessionService:
        def __init__(self, *, settings):
            self.settings = settings

        async def build_authorization_redirect(
            self, provider: str, *, existing_state_cookie=None
        ):
            return OAuthAuthorizationRedirect(
                authorization_url="https://provider.test/google?state=login-state",
                state_cookie="login-state.100.signature",
                state_cookie_secure=True,
            )

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    response = await google_login(state_cookie=None, settings=object())

    cookie = next(
        value
        for value in _set_cookie_headers(response)
        if value.startswith(f"{OAUTH_STATE_COOKIE_NAME}=")
    )
    assert "login-state.100.signature" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert f"Path={OAUTH_STATE_COOKIE_PATH}" in cookie
    assert f"Max-Age={OAUTH_STATE_TTL_SECONDS}" in cookie


@pytest.mark.asyncio
async def test_google_callback_rejects_state_mismatch_before_provider_exchange(
    monkeypatch,
):
    class FakeOAuthSessionService:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def consume_oauth_state(self, *, provider, state, state_cookie):
            raise OAuthStateError("OAuth state does not match the login request")

        async def complete_provider_callback(self, provider: str, code: str):
            raise AssertionError("state must be verified before the code exchange")

        def failure_redirect_url(self, error: str = "oauth_failed"):
            return f"http://frontend.test/?error={error}"

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    response = await _call_oauth_callback(google_callback, state="attacker-state")

    assert response.headers["location"] == "http://frontend.test/?error=invalid_state"
    # A rejected callback must not touch the cookie: other tabs may still hold
    # valid pending states in it.
    assert not any(
        value.startswith(f"{OAUTH_STATE_COOKIE_NAME}=")
        for value in _set_cookie_headers(response)
    )


@pytest.mark.asyncio
async def test_oauth_callback_clears_the_state_cookie_after_success(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def complete_provider_callback(self, provider: str, code: str):
            return "http://frontend.test/?code=exchange-code"

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    response = await _call_oauth_callback(google_callback)

    cookie = next(
        value
        for value in _set_cookie_headers(response)
        if value.startswith(f"{OAUTH_STATE_COOKIE_NAME}=")
    )
    assert 'Max-Age=0' in cookie
    assert f"Path={OAUTH_STATE_COOKIE_PATH}" in cookie


@pytest.mark.asyncio
async def test_oauth_callback_writes_back_remaining_pending_states(monkeypatch):
    """Consuming one tab's state must preserve the other tabs' pending states."""

    class FakeOAuthSessionService:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings
            self.consumed_state = None

        def consume_oauth_state(self, *, provider, state, state_cookie):
            self.consumed_state = (provider, state, state_cookie)
            return OAuthStateConsumption(
                remaining_state_cookie="remaining-states.100.signature",
                state_cookie_secure=True,
            )

        async def complete_provider_callback(self, provider: str, code: str):
            return "http://frontend.test/?code=exchange-code"

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    response = await _call_oauth_callback(google_callback)

    assert response.headers["location"] == "http://frontend.test/?code=exchange-code"
    cookie = next(
        value
        for value in _set_cookie_headers(response)
        if value.startswith(f"{OAUTH_STATE_COOKIE_NAME}=")
    )
    assert "remaining-states.100.signature" in cookie
    assert f"Max-Age={OAUTH_STATE_TTL_SECONDS}" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert f"Path={OAUTH_STATE_COOKIE_PATH}" in cookie


@pytest.mark.asyncio
async def test_exchange_oauth_code_maps_invalid_code_error(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def exchange_code(self, code: str):
            assert code == "expired-code"
            raise InvalidOAuthCodeError("expired row id=secret-oauth-code")

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await exchange_oauth_code(
            body=CodeExchangeRequest(code="expired-code"),
            db=object(),
            settings=object(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired OAuth code."
    assert isinstance(exc_info.value.__cause__, InvalidOAuthCodeError)
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_exchange_oauth_code_uses_invalid_code_public_detail(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def exchange_code(self, code: str):
            raise InvalidOAuthCodeError(
                "expired row id=secret-oauth-code",
                public_detail="OAuth exchange code is no longer valid.",
            )

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await exchange_oauth_code(
            body=CodeExchangeRequest(code="expired-code"),
            db=object(),
            settings=object(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "OAuth exchange code is no longer valid."
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_exchange_oauth_code_maps_token_validation_error(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def exchange_code(self, code: str):
            assert code == "exchange-code"
            raise OAuthTokenValidationError("User not found: secret-user-id")

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await exchange_oauth_code(
            body=CodeExchangeRequest(code="exchange-code"),
            db=object(),
            settings=object(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "OAuth token validation failed."
    assert isinstance(exc_info.value.__cause__, OAuthTokenValidationError)
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_exchange_oauth_code_uses_token_validation_public_detail(monkeypatch):
    class FakeOAuthSessionService(_AcceptsCallbackState):
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        async def exchange_code(self, code: str):
            raise OAuthTokenValidationError(
                "User not found: secret-user-id",
                public_detail="OAuth session could not be restored.",
            )

    monkeypatch.setattr(auth, "OAuthSessionService", FakeOAuthSessionService)

    with pytest.raises(HTTPException) as exc_info:
        await exchange_oauth_code(
            body=CodeExchangeRequest(code="exchange-code"),
            db=object(),
            settings=object(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "OAuth session could not be restored."
    assert "secret" not in exc_info.value.detail
