from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.oauth_code import OAuthCode
from app.services.oauth_profile_service import OAuthProfileError, OAuthUserProfile
from app.services.auth_service import OAuthAccountLinkRequiredError
from app.services.oauth_session_service import (
    INVALID_OAUTH_CODE_DETAIL,
    InvalidOAuthCodeError,
    OAUTH_PROVIDER_UNAVAILABLE_DETAIL,
    OAUTH_STATE_TTL_SECONDS,
    OAUTH_TOKEN_VALIDATION_DETAIL,
    OAuthStateError,
    build_default_oauth_client,
    OAuthAccountLinkCallbackError,
    OAuthCallbackError,
    OAuthEmailNotVerifiedError,
    OAuthProfileFetchError,
    OAuthProviderNotConfiguredError,
    OAuthSessionService,
    OAuthTokenExchangeError,
    OAuthTokenPayloadError,
    OAuthTokenValidationError,
    validate_oauth_provider,
)


def _settings(**overrides):
    data = {
        "google_client_id": "google-client",
        "google_client_secret": "google-secret",
        "google_callback_url": "http://api.test/auth/google/callback",
        "github_client_id": "github-client",
        "github_client_secret": "github-secret",
        "github_callback_url": "http://api.test/auth/github/callback",
        "frontend_url": "http://frontend.test",
        "session_secret": "test-session-secret",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _user(user_id: str = "user-1"):
    return SimpleNamespace(
        user_id=user_id,
        email="ada@example.com",
        username="Ada",
        avatar_url=None,
        auth_provider="google",
        created_at=datetime(2026, 1, 1),
    )


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDb:
    def __init__(self, results=()):
        self.results = list(results)
        self.executed = []
        self.added = []
        self.deleted = []
        self.flush_count = 0
        self.commit_count = 0

    async def execute(self, statement):
        self.executed.append(statement)
        value = self.results.pop(0) if self.results else None
        return _Result(value)

    def add(self, item):
        self.added.append(item)

    async def delete(self, item):
        self.deleted.append(item)

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commit_count += 1


@pytest.mark.parametrize(
    ("exception_cls", "message", "public_detail"),
    [
        (
            OAuthProviderNotConfiguredError,
            "internal provider secret",
            OAUTH_PROVIDER_UNAVAILABLE_DETAIL,
        ),
        (
            InvalidOAuthCodeError,
            "internal code secret",
            INVALID_OAUTH_CODE_DETAIL,
        ),
        (
            OAuthTokenValidationError,
            "internal token secret",
            OAUTH_TOKEN_VALIDATION_DETAIL,
        ),
    ],
)
def test_oauth_http_errors_keep_internal_messages_private(
    exception_cls,
    message,
    public_detail,
):
    exc = exception_cls(message)

    assert str(exc) == message
    assert exc.public_detail == public_detail
    assert "secret" not in exc.public_detail


class _FakeOAuthClient:
    def __init__(self, token_payload=None, token_error: Exception | None = None):
        self.token_payload = (
            {"access_token": "provider-access-token"}
            if token_payload is None
            else token_payload
        )
        self.token_error = token_error
        self.authorization_redirect_uri = None
        self.authorization_state = None
        self.access_token_calls = []

    async def get_authorization_url(
        self,
        redirect_uri: str,
        state: str | None = None,
    ) -> str:
        self.authorization_redirect_uri = redirect_uri
        self.authorization_state = state
        return f"https://provider.test/authorize?redirect_uri={redirect_uri}"

    async def get_access_token(self, code: str, redirect_uri: str):
        self.access_token_calls.append((code, redirect_uri))
        if self.token_error:
            raise self.token_error
        return self.token_payload


class _FakeProfileService:
    def __init__(self, *, error: Exception | None = None, email_verified: bool = True):
        self.error = error
        self.email_verified = email_verified
        self.google_access_token = None
        self.github_access_token = None

    async def fetch_google_profile(self, access_token: str) -> OAuthUserProfile:
        if self.error:
            raise self.error
        self.google_access_token = access_token
        return OAuthUserProfile(
            email="ada@example.com",
            email_verified=self.email_verified,
            username="Ada",
            avatar_url="https://example.test/avatar.png",
            provider_id="google-1",
        )

    async def fetch_github_profile(self, access_token: str) -> OAuthUserProfile:
        if self.error:
            raise self.error
        self.github_access_token = access_token
        return OAuthUserProfile(
            email="octo@example.com",
            email_verified=self.email_verified,
            username="Octo",
            avatar_url=None,
            provider_id="42",
        )


class _FakeAuthService:
    instances = []

    def __init__(self, db, *, settings):
        self.db = db
        self.settings = settings
        self.upsert_calls = []
        self.__class__.instances.append(self)

    async def upsert_oauth_user(self, **kwargs):
        self.upsert_calls.append(kwargs)
        return _user()

    def generate_user_token(self, user):
        return f"jwt-for-{user.user_id}"


class _ConflictingAuthService(_FakeAuthService):
    async def upsert_oauth_user(self, **kwargs):
        self.upsert_calls.append(kwargs)
        raise OAuthAccountLinkRequiredError(kwargs["email"])


class _FailingAuthService(_FakeAuthService):
    async def upsert_oauth_user(self, **kwargs):
        self.upsert_calls.append(kwargs)
        raise RuntimeError("database unavailable")


def test_provider_client_rejects_missing_provider_configuration():
    service = OAuthSessionService(
        settings=_settings(google_client_id=None, google_client_secret=None),
    )

    with pytest.raises(OAuthProviderNotConfiguredError, match="Google OAuth"):
        service.provider_client("google")


def test_validate_oauth_provider_rejects_unknown_providers():
    with pytest.raises(OAuthProviderNotConfiguredError) as exc_info:
        validate_oauth_provider("slack")

    assert "Unsupported OAuth provider" in str(exc_info.value)
    assert exc_info.value.public_detail == OAUTH_PROVIDER_UNAVAILABLE_DETAIL


def test_build_default_oauth_client_rejects_unknown_providers_before_fallback():
    with pytest.raises(OAuthProviderNotConfiguredError, match="Unsupported OAuth provider"):
        build_default_oauth_client("slack", _settings())


def test_provider_config_rejects_unknown_providers_without_github_fallback():
    service = OAuthSessionService(settings=_settings())

    with pytest.raises(OAuthProviderNotConfiguredError, match="Unsupported OAuth provider"):
        service.provider_config("slack")


def test_provider_client_rejects_unknown_providers_without_calling_factory():
    calls = []
    service = OAuthSessionService(
        settings=_settings(),
        client_factory=lambda provider, settings: calls.append(provider),
    )

    with pytest.raises(OAuthProviderNotConfiguredError, match="Unsupported OAuth provider"):
        service.provider_client("slack")

    assert calls == []


@pytest.mark.asyncio
async def test_get_authorization_url_uses_provider_callback_url():
    client = _FakeOAuthClient()
    service = OAuthSessionService(
        settings=_settings(),
        client_factory=lambda provider, settings: client,
    )

    url = await service.get_authorization_url("google")

    assert url == (
        "https://provider.test/authorize"
        "?redirect_uri=http://api.test/auth/google/callback"
    )
    assert client.authorization_redirect_uri == "http://api.test/auth/google/callback"


def _state_service(
    client,
    *,
    clock=lambda: 100.0,
    state_factory=lambda: "login-state",
    **settings_overrides,
):
    return OAuthSessionService(
        settings=_settings(**settings_overrides),
        client_factory=lambda provider, settings: client,
        state_factory=state_factory,
        clock=clock,
    )


def _sequenced_state_factory(*states):
    """Return a state factory yielding the given states in order."""
    values = iter(states)
    return lambda: next(values)


def _cookie_states(cookie: str) -> list[str]:
    """Decode the signed state list carried by a cookie value."""
    signed_payload, _, _signature = cookie.rpartition(".")
    encoded_states, _, _issued_at = signed_payload.rpartition(".")
    padded = encoded_states + "=" * (-len(encoded_states) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _forge_cookie(payload: str, secret: str = "test-session-secret") -> str:
    """Sign an arbitrary payload the way the service signs its state cookies."""
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return f"{payload}.{signature.hexdigest()}"


def _consume(service, *, state, state_cookie, provider="google"):
    return service.consume_oauth_state(
        provider=provider,
        state=state,
        state_cookie=state_cookie,
    )


@pytest.mark.asyncio
async def test_build_authorization_redirect_binds_state_to_url_and_cookie():
    client = _FakeOAuthClient()
    service = _state_service(client)

    redirect = await service.build_authorization_redirect("google")

    assert client.authorization_state == "login-state"
    assert _cookie_states(redirect.state_cookie) == ["login-state"]
    # Cookie-safe characters only: b64url list, integer timestamp, hex HMAC.
    assert re.fullmatch(r"[A-Za-z0-9_-]+\.\d+\.[0-9a-f]+", redirect.state_cookie)
    assert redirect.state_cookie_secure is False


@pytest.mark.asyncio
async def test_build_authorization_redirect_marks_cookie_secure_for_https_callbacks():
    client = _FakeOAuthClient()
    service = _state_service(
        client,
        google_callback_url="https://api.test/auth/google/callback",
    )

    redirect = await service.build_authorization_redirect("google")

    assert redirect.state_cookie_secure is True


@pytest.mark.asyncio
async def test_consume_oauth_state_accepts_the_state_it_issued():
    client = _FakeOAuthClient()
    service = _state_service(client)

    redirect = await service.build_authorization_redirect("google")
    consumption = _consume(
        service,
        state="login-state",
        state_cookie=redirect.state_cookie,
    )

    # The issued state was the only pending one, so the cookie should be dropped.
    assert consumption.remaining_state_cookie is None
    assert consumption.state_cookie_secure is False


@pytest.mark.asyncio
async def test_consume_oauth_state_reports_secure_flag_for_https_callbacks():
    client = _FakeOAuthClient()
    service = _state_service(
        client,
        google_callback_url="https://api.test/auth/google/callback",
    )

    redirect = await service.build_authorization_redirect("google")
    consumption = _consume(
        service,
        state="login-state",
        state_cookie=redirect.state_cookie,
    )

    assert consumption.state_cookie_secure is True


@pytest.mark.asyncio
async def test_concurrent_tab_logins_keep_both_states_valid():
    """Two tabs may log in at once; either callback must be accepted."""
    client = _FakeOAuthClient()
    service = _state_service(
        client,
        state_factory=_sequenced_state_factory("state-one", "state-two"),
    )

    first = await service.build_authorization_redirect("google")
    second = await service.build_authorization_redirect(
        "google",
        existing_state_cookie=first.state_cookie,
    )

    assert _cookie_states(second.state_cookie) == ["state-two", "state-one"]

    # The shared browser cookie is now `second`; tab one's callback still works.
    consumption = _consume(
        service,
        state="state-one",
        state_cookie=second.state_cookie,
    )
    assert consumption.remaining_state_cookie is not None
    assert _cookie_states(consumption.remaining_state_cookie) == ["state-two"]

    # Tab two can still complete afterwards against the rewritten cookie.
    final = _consume(
        service,
        state="state-two",
        state_cookie=consumption.remaining_state_cookie,
    )
    assert final.remaining_state_cookie is None


@pytest.mark.asyncio
async def test_consumed_state_cannot_be_replayed():
    client = _FakeOAuthClient()
    service = _state_service(
        client,
        state_factory=_sequenced_state_factory("state-one", "state-two"),
    )
    first = await service.build_authorization_redirect("google")
    both = await service.build_authorization_redirect(
        "google",
        existing_state_cookie=first.state_cookie,
    )

    consumption = _consume(service, state="state-two", state_cookie=both.state_cookie)
    assert consumption.remaining_state_cookie is not None

    with pytest.raises(OAuthStateError, match="does not match the login request"):
        _consume(
            service,
            state="state-two",
            state_cookie=consumption.remaining_state_cookie,
        )

    # The other tab's state survives the replay rejection.
    remaining = _consume(
        service,
        state="state-one",
        state_cookie=consumption.remaining_state_cookie,
    )
    assert remaining.remaining_state_cookie is None


@pytest.mark.asyncio
async def test_new_login_evicts_the_oldest_state_beyond_the_cap():
    client = _FakeOAuthClient()
    service = _state_service(
        client,
        state_factory=_sequenced_state_factory(
            "state-1", "state-2", "state-3", "state-4"
        ),
    )

    cookie = None
    for _ in range(4):
        redirect = await service.build_authorization_redirect(
            "google",
            existing_state_cookie=cookie,
        )
        cookie = redirect.state_cookie

    assert _cookie_states(cookie) == ["state-4", "state-3", "state-2"]

    with pytest.raises(OAuthStateError, match="does not match the login request"):
        _consume(service, state="state-1", state_cookie=cookie)
    for state in ("state-2", "state-3", "state-4"):
        consumption = _consume(service, state=state, state_cookie=cookie)
        cookie = consumption.remaining_state_cookie
    assert cookie is None


@pytest.mark.asyncio
async def test_login_with_expired_cookie_starts_a_fresh_state_list():
    now = [100.0]
    client = _FakeOAuthClient()
    service = _state_service(
        client,
        clock=lambda: now[0],
        state_factory=_sequenced_state_factory("old-state", "new-state"),
    )

    first = await service.build_authorization_redirect("google")
    now[0] = 100.0 + OAUTH_STATE_TTL_SECONDS + 1
    second = await service.build_authorization_redirect(
        "google",
        existing_state_cookie=first.state_cookie,
    )

    assert _cookie_states(second.state_cookie) == ["new-state"]
    with pytest.raises(OAuthStateError, match="does not match the login request"):
        _consume(service, state="old-state", state_cookie=second.state_cookie)
    assert _consume(service, state="new-state", state_cookie=second.state_cookie)


@pytest.mark.asyncio
async def test_login_with_tampered_cookie_starts_a_fresh_state_list():
    client = _FakeOAuthClient()
    service = _state_service(
        client,
        state_factory=_sequenced_state_factory("old-state", "new-state"),
    )

    first = await service.build_authorization_redirect("google")
    encoded_states, issued_at, signature = first.state_cookie.rsplit(".", 2)
    tampered_char = "A" if encoded_states[0] != "A" else "B"
    tampered = f"{tampered_char}{encoded_states[1:]}.{issued_at}.{signature}"

    second = await service.build_authorization_redirect(
        "google",
        existing_state_cookie=tampered,
    )

    assert _cookie_states(second.state_cookie) == ["new-state"]
    with pytest.raises(OAuthStateError, match="does not match the login request"):
        _consume(service, state="old-state", state_cookie=second.state_cookie)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "cookie"),
    [
        (None, "cookie"),
        ("login-state", None),
        ("", ""),
    ],
)
async def test_consume_oauth_state_rejects_missing_state_pairs(state, cookie):
    service = _state_service(_FakeOAuthClient())

    with pytest.raises(OAuthStateError, match="missing its login state"):
        _consume(service, state=state, state_cookie=cookie)


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_a_state_from_another_browser():
    client = _FakeOAuthClient()
    service = _state_service(client)
    redirect = await service.build_authorization_redirect("google")

    with pytest.raises(OAuthStateError, match="does not match the login request"):
        _consume(
            service,
            state="attacker-state",
            state_cookie=redirect.state_cookie,
        )


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_a_forged_cookie_signature():
    service = _state_service(_FakeOAuthClient())

    with pytest.raises(OAuthStateError, match="signature is invalid"):
        _consume(
            service,
            state="attacker-state",
            state_cookie="attacker-state.100.deadbeef",
        )


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_a_cookie_signed_with_another_secret():
    client = _FakeOAuthClient()
    redirect = await _state_service(
        client,
        session_secret="other-session-secret",
    ).build_authorization_redirect("google")

    with pytest.raises(OAuthStateError, match="signature is invalid"):
        _consume(
            _state_service(client),
            state="login-state",
            state_cookie=redirect.state_cookie,
        )


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_expired_state():
    now = [100.0]
    client = _FakeOAuthClient()
    service = _state_service(client, clock=lambda: now[0])
    redirect = await service.build_authorization_redirect("google")

    now[0] = 100.0 + OAUTH_STATE_TTL_SECONDS + 1

    with pytest.raises(OAuthStateError, match="has expired"):
        _consume(
            service,
            state="login-state",
            state_cookie=redirect.state_cookie,
        )


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_non_ascii_callback_values():
    client = _FakeOAuthClient()
    service = _state_service(client)
    redirect = await service.build_authorization_redirect("google")

    with pytest.raises(OAuthStateError):
        _consume(service, state="状态", state_cookie=redirect.state_cookie)

    with pytest.raises(OAuthStateError):
        _consume(service, state="login-state", state_cookie="登录.100.签名")


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_malformed_cookies():
    service = _state_service(_FakeOAuthClient())

    with pytest.raises(OAuthStateError, match="malformed"):
        _consume(service, state="login-state", state_cookie="login-state")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "encoded_payload",
    [
        base64.urlsafe_b64encode(b"not json").decode().rstrip("="),
        base64.urlsafe_b64encode(b'{"state":"login-state"}').decode().rstrip("="),
        base64.urlsafe_b64encode(b"[]").decode().rstrip("="),
        base64.urlsafe_b64encode(b"[1,2]").decode().rstrip("="),
        base64.urlsafe_b64encode(b'[""]').decode().rstrip("="),
    ],
)
async def test_consume_oauth_state_rejects_signed_but_malformed_state_lists(
    encoded_payload,
):
    service = _state_service(_FakeOAuthClient())

    with pytest.raises(OAuthStateError, match="malformed"):
        _consume(
            service,
            state="login-state",
            state_cookie=_forge_cookie(f"{encoded_payload}.100"),
        )


@pytest.mark.asyncio
async def test_oauth_code_creation_stores_short_lived_exchange_code():
    db = _FakeDb()
    service = OAuthSessionService(
        db,
        settings=_settings(),
        code_factory=lambda: "exchange-code",
        clock=lambda: 100.0,
    )

    code = await service.create_oauth_code("jwt-token")

    assert code == "exchange-code"
    assert len(db.executed) == 1
    assert db.flush_count == 1
    assert db.added[0].code == "exchange-code"
    assert db.added[0].token == "jwt-token"
    assert db.added[0].expires_at == 160.0


@pytest.mark.asyncio
async def test_complete_provider_callback_upserts_user_and_returns_frontend_code_url():
    db = _FakeDb()
    client = _FakeOAuthClient()
    profile_service = _FakeProfileService()
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
        profile_service_factory=lambda: profile_service,
        code_factory=lambda: "exchange code",
        clock=lambda: 100.0,
    )

    redirect_url = await service.complete_provider_callback("google", "provider-code")

    assert redirect_url == "http://frontend.test/?code=exchange%20code"
    assert client.access_token_calls == [
        ("provider-code", "http://api.test/auth/google/callback")
    ]
    assert profile_service.google_access_token == "provider-access-token"
    assert _FakeAuthService.instances[0].upsert_calls == [
        {
            "email": "ada@example.com",
            "username": "Ada",
            "avatar_url": "https://example.test/avatar.png",
            "auth_provider": "google",
            "external_id": "google-1",
        }
    ]
    assert db.added[0].token == "jwt-for-user-1"


@pytest.mark.asyncio
async def test_complete_provider_callback_supports_github_profile_flow():
    db = _FakeDb()
    client = _FakeOAuthClient()
    profile_service = _FakeProfileService()
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
        profile_service_factory=lambda: profile_service,
        code_factory=lambda: "exchange-code",
        clock=lambda: 100.0,
    )

    redirect_url = await service.complete_provider_callback("github", "provider-code")

    assert redirect_url == "http://frontend.test/?code=exchange-code"
    assert client.access_token_calls == [
        ("provider-code", "http://api.test/auth/github/callback")
    ]
    assert profile_service.google_access_token is None
    assert profile_service.github_access_token == "provider-access-token"
    assert _FakeAuthService.instances[0].upsert_calls == [
        {
            "email": "octo@example.com",
            "username": "Octo",
            "avatar_url": None,
            "auth_provider": "github",
            "external_id": "42",
        }
    ]


@pytest.mark.asyncio
async def test_complete_provider_callback_rejects_unknown_provider_before_client_factory():
    db = _FakeDb()
    calls = []
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: calls.append(provider),
        auth_service_factory=_FakeAuthService,
    )

    with pytest.raises(OAuthProviderNotConfiguredError, match="Unsupported OAuth provider"):
        await service.complete_provider_callback("slack", "provider-code")

    assert calls == []
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_validates_provider_before_db_requirement():
    service = OAuthSessionService(settings=_settings())

    with pytest.raises(OAuthProviderNotConfiguredError, match="Unsupported OAuth provider"):
        await service.complete_provider_callback("slack", "provider-code")


@pytest.mark.asyncio
async def test_complete_provider_callback_rejects_unverified_profile_email():
    db = _FakeDb()
    client = _FakeOAuthClient()
    profile_service = _FakeProfileService(email_verified=False)
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
        profile_service_factory=lambda: profile_service,
    )

    with pytest.raises(
        OAuthEmailNotVerifiedError,
        match="verified email required",
    ) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert isinstance(exc_info.value, OAuthCallbackError)
    assert exc_info.value.redirect_error == "oauth_failed"
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_maps_existing_email_conflicts():
    db = _FakeDb()
    client = _FakeOAuthClient()
    profile_service = _FakeProfileService()
    _ConflictingAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_ConflictingAuthService,
        profile_service_factory=lambda: profile_service,
        code_factory=lambda: "exchange-code",
        clock=lambda: 100.0,
    )

    with pytest.raises(OAuthAccountLinkCallbackError) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert str(exc_info.value) == "Account linking required for this email"
    assert exc_info.value.redirect_error == "account_link_required"
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_wraps_token_exchange_failures():
    db = _FakeDb()
    token_error = httpx.ConnectError("provider secret response")
    client = _FakeOAuthClient(token_error=token_error)
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
    )

    with pytest.raises(
        OAuthTokenExchangeError,
        match="token exchange failed",
    ) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert isinstance(exc_info.value, OAuthCallbackError)
    assert exc_info.value.redirect_error == "oauth_failed"
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert exc_info.value.__cause__.__cause__ is token_error
    assert "provider secret" not in str(exc_info.value)
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_wraps_token_coercion_failures():
    db = _FakeDb()
    token_error = ValueError("provider secret expires_in")
    client = _FakeOAuthClient(token_error=token_error)
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
    )

    with pytest.raises(
        OAuthTokenExchangeError,
        match="token exchange failed",
    ) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert isinstance(exc_info.value, OAuthCallbackError)
    assert exc_info.value.redirect_error == "oauth_failed"
    assert exc_info.value.__cause__.__cause__ is token_error
    assert "provider secret" not in str(exc_info.value)
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_rejects_invalid_token_payload():
    db = _FakeDb()
    client = _FakeOAuthClient(token_payload=[])
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
    )

    with pytest.raises(
        OAuthTokenPayloadError,
        match="token payload was invalid",
    ) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert isinstance(exc_info.value, OAuthCallbackError)
    assert exc_info.value.redirect_error == "oauth_failed"
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token_payload",
    [{}, {"access_token": ""}, {"access_token": 42}],
)
async def test_complete_provider_callback_rejects_missing_access_token(token_payload):
    db = _FakeDb()
    client = _FakeOAuthClient(token_payload=token_payload)
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
    )

    with pytest.raises(
        OAuthTokenPayloadError,
        match="access_token missing",
    ) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert isinstance(exc_info.value, OAuthCallbackError)
    assert exc_info.value.redirect_error == "oauth_failed"
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_wraps_profile_failures():
    db = _FakeDb()
    client = _FakeOAuthClient()
    profile_service = _FakeProfileService(
        error=OAuthProfileError("Google profile missing required field: email")
    )
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
        profile_service_factory=lambda: profile_service,
    )

    with pytest.raises(
        OAuthProfileFetchError,
        match="profile fetch failed",
    ) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert isinstance(exc_info.value, OAuthCallbackError)
    assert exc_info.value.redirect_error == "oauth_failed"
    assert isinstance(exc_info.value.__cause__, OAuthProfileError)
    assert "missing required field" not in str(exc_info.value)
    assert "email" not in str(exc_info.value)
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_does_not_wrap_profile_programmer_bugs():
    db = _FakeDb()
    client = _FakeOAuthClient()
    fetch_error = RuntimeError("profile service programmer bug")
    profile_service = _FakeProfileService(error=fetch_error)
    _FakeAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FakeAuthService,
        profile_service_factory=lambda: profile_service,
    )

    with pytest.raises(
        RuntimeError,
        match="profile service programmer bug",
    ) as exc_info:
        await service.complete_provider_callback("google", "provider-code")

    assert exc_info.value is fetch_error
    assert _FakeAuthService.instances == []
    assert db.added == []


@pytest.mark.asyncio
async def test_complete_provider_callback_does_not_wrap_auth_service_failures():
    db = _FakeDb()
    client = _FakeOAuthClient()
    profile_service = _FakeProfileService()
    _FailingAuthService.instances = []
    service = OAuthSessionService(
        db,
        settings=_settings(),
        client_factory=lambda provider, settings: client,
        auth_service_factory=_FailingAuthService,
        profile_service_factory=lambda: profile_service,
        code_factory=lambda: "exchange-code",
        clock=lambda: 100.0,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.complete_provider_callback("google", "provider-code")

    assert _FailingAuthService.instances[0].upsert_calls == [
        {
            "email": "ada@example.com",
            "username": "Ada",
            "avatar_url": "https://example.test/avatar.png",
            "auth_provider": "google",
            "external_id": "google-1",
        }
    ]
    assert db.added == []


@pytest.mark.asyncio
async def test_exchange_code_consumes_code_and_returns_user():
    user = _user()
    db = _FakeDb(results=["jwt-token", user])
    service = OAuthSessionService(
        db,
        settings=_settings(),
        token_verifier=lambda token, settings: {"user_id": "user-1"},
        clock=lambda: 100.0,
    )

    result = await service.exchange_code("exchange-code")

    assert result.token == "jwt-token"
    assert result.user is user
    assert db.deleted == []
    assert db.commit_count == 1
    assert len(db.executed) == 2


@pytest.mark.asyncio
async def test_consume_oauth_code_is_single_use_with_sqlite_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            db.add(
                OAuthCode(
                    code="exchange-code",
                    token="jwt-token",
                    expires_at=200.0,
                )
            )
            await db.commit()

            service = OAuthSessionService(
                db,
                settings=_settings(),
                clock=lambda: 100.0,
            )

            assert await service.consume_oauth_code("exchange-code") == "jwt-token"
            with pytest.raises(InvalidOAuthCodeError):
                await service.consume_oauth_code("exchange-code")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_exchange_code_deletes_expired_code_before_rejecting():
    db = _FakeDb(results=[None])
    service = OAuthSessionService(
        db,
        settings=_settings(),
        clock=lambda: 100.0,
    )

    with pytest.raises(InvalidOAuthCodeError, match="Invalid or expired code"):
        await service.exchange_code("exchange-code")

    assert db.deleted == []
    assert db.commit_count == 1
    assert len(db.executed) == 2


@pytest.mark.asyncio
async def test_exchange_code_rejects_tokens_that_do_not_resolve_to_users():
    db = _FakeDb(results=["jwt-token"])
    service = OAuthSessionService(
        db,
        settings=_settings(),
        token_verifier=lambda token, settings: None,
        clock=lambda: 100.0,
    )

    with pytest.raises(OAuthTokenValidationError, match="Token validation failed"):
        await service.exchange_code("exchange-code")

    assert db.deleted == []
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_exchange_code_hides_missing_user_token_details():
    db = _FakeDb(results=["jwt-token", None])
    service = OAuthSessionService(
        db,
        settings=_settings(),
        token_verifier=lambda token, settings: {"user_id": "secret-user-id"},
        clock=lambda: 100.0,
    )

    with pytest.raises(OAuthTokenValidationError) as exc_info:
        await service.exchange_code("exchange-code")

    assert str(exc_info.value) == "Token validation failed"
    assert "secret-user-id" not in str(exc_info.value)
    assert "User not found" not in str(exc_info.value)
    assert db.deleted == []
    assert db.commit_count == 1
