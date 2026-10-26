"""OAuth login session orchestration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Protocol, cast
from urllib.parse import quote

import httpx
from httpx_oauth.exceptions import HTTPXOAuthError
from loguru import logger
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import PublicErrorMixin
from app.core.security import verify_token
from app.models.oauth_code import OAuthCode
from app.models.user import User
from app.services.auth_service import AuthService, OAuthAccountLinkRequiredError
from app.services.auth_token_service import (
    AuthTokenError,
    AuthTokenService,
    InvalidAuthTokenError,
    TokenVerifier,
)
from app.services.oauth_profile_service import (
    OAuthProfileError,
    OAuthProfileService,
    OAuthUserProfile,
)


OAuthProvider = Literal["google", "github"]
SUPPORTED_OAUTH_PROVIDERS: tuple[OAuthProvider, ...] = ("google", "github")
OAUTH_CODE_TTL_SECONDS = 60
OAUTH_ACCOUNT_LINK_REQUIRED_MESSAGE = "Account linking required for this email"
OAUTH_PROFILE_FETCH_FAILED_MESSAGE = "OAuth profile fetch failed"
OAUTH_TOKEN_VALIDATION_FAILED_MESSAGE = "Token validation failed"
OAUTH_PROVIDER_UNAVAILABLE_DETAIL = "OAuth provider is not configured."
INVALID_OAUTH_CODE_DETAIL = "Invalid or expired OAuth code."
OAUTH_TOKEN_VALIDATION_DETAIL = "OAuth token validation failed."
OAUTH_STATE_COOKIE_NAME = "evodiagram_oauth_state"
# Matches where the auth router is mounted (/api + /v1 + /auth).
OAUTH_STATE_COOKIE_PATH = "/api/v1/auth"
OAUTH_STATE_TTL_SECONDS = 600
OAUTH_STATE_REDIRECT_ERROR = "invalid_state"
# Multi-tab logins share one cookie jar, so the signed cookie keeps a short
# list of pending states (newest first) instead of a single value; starting a
# login in a second tab must not invalidate the first tab's callback.
OAUTH_STATE_COOKIE_MAX_ENTRIES = 3


class OAuthClient(Protocol):
    async def get_authorization_url(
        self,
        redirect_uri: str,
        state: str | None = None,
    ) -> str:
        """Return the provider authorization URL."""

    async def get_access_token(self, code: str, redirect_uri: str) -> Mapping[str, Any]:
        """Exchange a provider callback code for a token payload."""


class OAuthProviderNotConfiguredError(PublicErrorMixin, RuntimeError):
    """Raised when a requested OAuth provider has no configured credentials."""

    default_public_detail = OAUTH_PROVIDER_UNAVAILABLE_DETAIL


class InvalidOAuthCodeError(PublicErrorMixin, ValueError):
    """Raised when a frontend OAuth exchange code cannot be consumed."""

    default_public_detail = INVALID_OAUTH_CODE_DETAIL


class OAuthTokenValidationError(PublicErrorMixin, ValueError):
    """Raised when a consumed OAuth exchange token does not resolve to a user."""

    default_public_detail = OAUTH_TOKEN_VALIDATION_DETAIL


class OAuthCallbackError(RuntimeError):
    """Raised when a provider callback fails for an expected OAuth reason."""

    def __init__(self, message: str, *, redirect_error: str = "oauth_failed"):
        self.redirect_error = redirect_error
        super().__init__(message)


class OAuthTokenExchangeError(OAuthCallbackError):
    """Raised when a provider authorization code cannot be exchanged."""


class _OAuthProviderTokenExchangeError(RuntimeError):
    """Raised when the provider token endpoint cannot be reached or parsed."""


class OAuthTokenPayloadError(OAuthCallbackError):
    """Raised when a provider token response has an invalid shape."""


class OAuthProfileFetchError(OAuthCallbackError):
    """Raised when a provider profile cannot be fetched or parsed."""


class OAuthEmailNotVerifiedError(OAuthCallbackError):
    """Raised when a provider profile has no verified email address."""


class OAuthAccountLinkCallbackError(OAuthCallbackError):
    """Raised when OAuth login needs explicit account linking."""

    def __init__(self, message: str):
        super().__init__(message, redirect_error="account_link_required")


class OAuthStateError(OAuthCallbackError):
    """Raised when a provider callback fails login CSRF state validation."""

    def __init__(self, message: str):
        super().__init__(message, redirect_error=OAUTH_STATE_REDIRECT_ERROR)


@dataclass(frozen=True)
class OAuthProviderConfig:
    """Runtime configuration for an OAuth provider."""

    name: OAuthProvider
    display_name: str
    callback_url: str


@dataclass(frozen=True)
class OAuthAuthorizationRedirect:
    """Authorization URL plus the signed state cookie that protects it."""

    authorization_url: str
    state_cookie: str
    state_cookie_secure: bool


@dataclass(frozen=True)
class OAuthStateConsumption:
    """Outcome of validating one provider callback against the state cookie.

    ``remaining_state_cookie`` is the re-signed cookie value holding the
    still-pending states (other tabs' logins), or None when the consumed state
    was the last one and the caller should delete the cookie.
    """

    remaining_state_cookie: str | None
    state_cookie_secure: bool


@dataclass(frozen=True)
class OAuthCodeExchangeResult:
    """Token and user resolved from a single-use OAuth exchange code."""

    token: str
    user: User


ClientFactory = Callable[[OAuthProvider, Settings], OAuthClient | None]
AuthServiceFactory = Callable[..., AuthService]
ProfileServiceFactory = Callable[[], OAuthProfileService]
CodeFactory = Callable[[], str]
StateFactory = Callable[[], str]
Clock = Callable[[], float]


def validate_oauth_provider(provider: str) -> OAuthProvider:
    """Return a supported OAuth provider or raise a client-safe domain error."""
    if provider not in SUPPORTED_OAUTH_PROVIDERS:
        raise OAuthProviderNotConfiguredError(f"Unsupported OAuth provider: {provider}")
    return cast(OAuthProvider, provider)


def build_default_oauth_client(
    provider: str,
    settings: Settings,
) -> OAuthClient | None:
    """Build an OAuth provider client when settings are configured."""
    provider = validate_oauth_provider(provider)
    if provider == "google":
        if not settings.google_client_id or not settings.google_client_secret:
            return None
        from httpx_oauth.clients.google import GoogleOAuth2

        return GoogleOAuth2(
            settings.google_client_id,
            settings.google_client_secret,
        )

    if not settings.github_client_id or not settings.github_client_secret:
        return None
    from httpx_oauth.clients.github import GitHubOAuth2

    return GitHubOAuth2(
        settings.github_client_id,
        settings.github_client_secret,
    )


async def exchange_provider_access_token(
    *,
    client: OAuthClient,
    code: str,
    redirect_uri: str,
) -> Mapping[str, Any]:
    """Exchange an OAuth code and normalize provider transport failures."""
    try:
        return await client.get_access_token(
            code=code,
            redirect_uri=redirect_uri,
        )
    except (HTTPXOAuthError, httpx.HTTPError, ValueError, TypeError) as exc:
        raise _OAuthProviderTokenExchangeError(
            "OAuth provider token exchange failed"
        ) from exc


class OAuthSessionService:
    """Manage OAuth provider redirects, callbacks, and code exchange."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        *,
        settings: Settings | None = None,
        client_factory: ClientFactory = build_default_oauth_client,
        auth_service_factory: AuthServiceFactory = AuthService,
        profile_service_factory: ProfileServiceFactory = OAuthProfileService,
        token_verifier: TokenVerifier = verify_token,
        code_factory: CodeFactory | None = None,
        state_factory: StateFactory | None = None,
        clock: Clock = time.time,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.client_factory = client_factory
        self.auth_service_factory = auth_service_factory
        self.profile_service_factory = profile_service_factory
        self.token_verifier = token_verifier
        self.code_factory = code_factory or (lambda: secrets.token_urlsafe(48))
        self.state_factory = state_factory or (lambda: secrets.token_urlsafe(32))
        self.clock = clock

    def provider_config(self, provider: str) -> OAuthProviderConfig:
        """Return callback metadata for a supported provider."""
        provider = validate_oauth_provider(provider)
        if provider == "google":
            return OAuthProviderConfig(
                name="google",
                display_name="Google",
                callback_url=self.settings.google_callback_url,
            )
        return OAuthProviderConfig(
            name="github",
            display_name="GitHub",
            callback_url=self.settings.github_callback_url,
        )

    def provider_client(self, provider: str) -> OAuthClient:
        """Return a configured OAuth client or raise a domain error."""
        config = self.provider_config(provider)
        client = self.client_factory(config.name, self.settings)
        if client is None:
            raise OAuthProviderNotConfiguredError(
                f"{config.display_name} OAuth not configured"
            )
        return client

    async def get_authorization_url(
        self,
        provider: str,
        *,
        state: str | None = None,
    ) -> str:
        """Build an authorization URL for a configured provider."""
        config = self.provider_config(provider)
        client = self.provider_client(config.name)
        return await client.get_authorization_url(
            redirect_uri=config.callback_url,
            state=state,
        )

    async def build_authorization_redirect(
        self,
        provider: str,
        *,
        existing_state_cookie: str | None = None,
    ) -> OAuthAuthorizationRedirect:
        """Build an authorization redirect bound to a single browser session.

        Pending states from earlier tabs survive: the new state is prepended to
        the verified list carried by ``existing_state_cookie`` (truncated to
        the newest OAUTH_STATE_COOKIE_MAX_ENTRIES), so a second login no
        longer invalidates the first tab's callback.
        """
        config = self.provider_config(provider)
        state = self.state_factory()
        authorization_url = await self.get_authorization_url(config.name, state=state)
        states = self._pending_states(existing_state_cookie)
        states.insert(0, state)
        del states[OAUTH_STATE_COOKIE_MAX_ENTRIES:]
        return OAuthAuthorizationRedirect(
            authorization_url=authorization_url,
            state_cookie=self._sign_states(states),
            state_cookie_secure=config.callback_url.lower().startswith("https://"),
        )

    def consume_oauth_state(
        self,
        *,
        provider: str,
        state: str | None,
        state_cookie: str | None,
    ) -> OAuthStateConsumption:
        """Reject provider callbacks that this browser did not start (login CSRF).

        The signed cookie is the only place the expected states live, so a
        callback replayed from another browser has nothing to match against.
        A matched state is removed from the list (single use); the returned
        consumption tells the caller how to rewrite the cookie so other tabs'
        pending logins stay valid.
        """
        config = self.provider_config(provider)
        if not state or not state_cookie:
            raise OAuthStateError("OAuth callback is missing its login state")

        states, _issued_at = self._decode_state_cookie(state_cookie)

        for index, issued_state in enumerate(states):
            # compare_digest rejects non-ASCII str, and both values are client supplied.
            if hmac.compare_digest(
                issued_state.encode("utf-8"),
                state.encode("utf-8"),
            ):
                remaining = states[:index] + states[index + 1 :]
                return OAuthStateConsumption(
                    remaining_state_cookie=(
                        self._sign_states(remaining) if remaining else None
                    ),
                    state_cookie_secure=config.callback_url.lower().startswith(
                        "https://"
                    ),
                )

        raise OAuthStateError("OAuth state does not match the login request")

    def _pending_states(self, state_cookie: str | None) -> list[str]:
        """Return still-pending states from an earlier cookie, if trustworthy.

        Issuing a login must never fail because of a stale cookie, and carrying
        states over from an unverifiable one would defeat the signature, so a
        missing, malformed, tampered, or expired cookie simply starts a fresh
        list.
        """
        if not state_cookie:
            return []
        try:
            states, _issued_at = self._decode_state_cookie(state_cookie)
        except OAuthStateError:
            return []
        return states

    def _decode_state_cookie(self, state_cookie: str) -> tuple[list[str], float]:
        """Verify signature and TTL of a state cookie and decode its state list.

        Cookie layout: ``<b64url(JSON list of states)>.<issued_at>.<signature>``
        where the signature covers the whole ``<states>.<issued_at>`` payload.
        The list shares one issued_at timestamp: the cookie is rewritten (and
        its Max-Age reset) whenever a login is started or a callback consumes
        a state, mirroring the previous single-state TTL semantics.
        """
        signed_payload, _, signature = state_cookie.rpartition(".")
        encoded_states, _, issued_at_raw = signed_payload.rpartition(".")
        if not signature or not encoded_states or not issued_at_raw:
            raise OAuthStateError("OAuth state cookie is malformed")

        # compare_digest rejects non-ASCII str, and both values are client supplied.
        if not hmac.compare_digest(
            signature.encode("utf-8"),
            self._state_signature(signed_payload).encode("utf-8"),
        ):
            raise OAuthStateError("OAuth state cookie signature is invalid")

        try:
            issued_at = float(issued_at_raw)
        except ValueError as exc:
            raise OAuthStateError("OAuth state cookie timestamp is invalid") from exc

        if self.clock() - issued_at > OAUTH_STATE_TTL_SECONDS:
            raise OAuthStateError("OAuth state has expired")

        try:
            decoded = json.loads(
                base64.urlsafe_b64decode(
                    encoded_states + "=" * (-len(encoded_states) % 4)
                )
            )
        except ValueError as exc:
            # binascii.Error and JSONDecodeError are both ValueError subclasses;
            # malformed base64/UTF-8/JSON all mean the cookie is not ours.
            raise OAuthStateError("OAuth state cookie is malformed") from exc

        if (
            not isinstance(decoded, list)
            or not decoded
            or len(decoded) > OAUTH_STATE_COOKIE_MAX_ENTRIES
            or not all(isinstance(item, str) and item for item in decoded)
        ):
            raise OAuthStateError("OAuth state cookie is malformed")

        return decoded, issued_at

    def _sign_states(self, states: list[str]) -> str:
        """Return the cookie value binding a state list to this backend."""
        encoded_states = (
            base64.urlsafe_b64encode(
                json.dumps(states, separators=(",", ":")).encode("utf-8")
            )
            .decode("ascii")
            .rstrip("=")
        )
        payload = f"{encoded_states}.{int(self.clock())}"
        return f"{payload}.{self._state_signature(payload)}"

    def _state_signature(self, payload: str) -> str:
        return hmac.new(
            self.settings.session_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def success_redirect_url(self, code: str) -> str:
        """Build the frontend redirect URL for a successful provider callback."""
        return f"{self.settings.frontend_url}/?code={quote(code)}"

    def failure_redirect_url(self, error: str = "oauth_failed") -> str:
        """Build the frontend redirect URL for a failed provider callback."""
        return f"{self.settings.frontend_url}/?error={quote(error)}"

    async def create_oauth_code(self, token: str) -> str:
        """Create a single-use, short-lived frontend exchange code."""
        db = self._require_db()
        now = self.clock()
        code = self.code_factory()

        await db.execute(sa_delete(OAuthCode).where(OAuthCode.expires_at < now))
        db.add(
            OAuthCode(
                code=code,
                token=token,
                expires_at=now + OAUTH_CODE_TTL_SECONDS,
            )
        )
        await db.flush()
        return code

    async def complete_provider_callback(
        self,
        provider: str,
        code: str,
    ) -> str:
        """Complete provider login and return the frontend success redirect URL."""
        config = self.provider_config(provider)
        provider = config.name
        db = self._require_db()
        client = self.provider_client(provider)

        access_token_payload = await self._exchange_access_token(
            client=client,
            config=config,
            code=code,
        )
        token_value = self._access_token_from_payload(
            config=config,
            payload=access_token_payload,
        )
        profile = await self._fetch_provider_profile(
            provider=provider,
            config=config,
            access_token=token_value,
        )

        if not profile.email_verified:
            raise OAuthEmailNotVerifiedError(
                f"{config.display_name} verified email required"
            )

        auth_service = self.auth_service_factory(db, settings=self.settings)
        try:
            user = await auth_service.upsert_oauth_user(
                email=profile.email,
                username=profile.username,
                avatar_url=profile.avatar_url,
                auth_provider=provider,
                external_id=profile.provider_id,
            )
        except OAuthAccountLinkRequiredError as exc:
            raise OAuthAccountLinkCallbackError(
                OAUTH_ACCOUNT_LINK_REQUIRED_MESSAGE
            ) from exc

        token = auth_service.generate_user_token(user)
        oauth_code = await self.create_oauth_code(token)
        logger.info("User logged in via {}: {}", config.display_name, profile.email)
        return self.success_redirect_url(oauth_code)

    async def _exchange_access_token(
        self,
        *,
        client: OAuthClient,
        config: OAuthProviderConfig,
        code: str,
    ) -> Mapping[str, Any]:
        """Exchange a provider callback code and map expected provider failures."""
        try:
            return await exchange_provider_access_token(
                client=client,
                code=code,
                redirect_uri=config.callback_url,
            )
        except _OAuthProviderTokenExchangeError as exc:
            raise OAuthTokenExchangeError(
                f"{config.display_name} OAuth token exchange failed"
            ) from exc

    def _access_token_from_payload(
        self,
        *,
        config: OAuthProviderConfig,
        payload: object,
    ) -> str:
        """Extract a non-empty access token from a provider token payload."""
        if not isinstance(payload, Mapping):
            raise OAuthTokenPayloadError(
                f"{config.display_name} OAuth token payload was invalid"
            )
        token_value = payload.get("access_token")
        if not isinstance(token_value, str) or not token_value:
            raise OAuthTokenPayloadError(f"{config.display_name} access_token missing")
        return token_value

    async def _fetch_provider_profile(
        self,
        *,
        provider: OAuthProvider,
        config: OAuthProviderConfig,
        access_token: str,
    ) -> OAuthUserProfile:
        """Fetch the normalized provider profile and map expected profile failures."""
        profile_service = self.profile_service_factory()
        try:
            if provider == "google":
                return await profile_service.fetch_google_profile(access_token)
            return await profile_service.fetch_github_profile(access_token)
        except OAuthProfileError as exc:
            raise OAuthProfileFetchError(
                f"{config.display_name} {OAUTH_PROFILE_FETCH_FAILED_MESSAGE}"
            ) from exc

    async def exchange_code(self, code: str) -> OAuthCodeExchangeResult:
        """Consume a frontend OAuth exchange code and resolve the authenticated user."""
        token = await self.consume_oauth_code(code)
        user = await self.resolve_user_from_token(token)

        return OAuthCodeExchangeResult(token=token, user=user)

    async def consume_oauth_code(self, code: str) -> str:
        """Atomically consume a valid frontend OAuth exchange code."""
        db = self._require_db()
        now = self.clock()

        result = await db.execute(
            sa_delete(OAuthCode)
            .where(
                OAuthCode.code == code,
                OAuthCode.expires_at >= now,
            )
            .returning(OAuthCode.token)
        )
        token = result.scalar_one_or_none()
        # Committing here keeps the code single-use: a later failure in the same
        # request rolls the session back, but must not resurrect the used code.
        if token is None:
            await db.execute(sa_delete(OAuthCode).where(OAuthCode.code == code))
            await db.commit()
            raise InvalidOAuthCodeError("Invalid or expired code")

        await db.commit()
        return token

    async def resolve_user_from_token(self, token: str) -> User:
        """Resolve a JWT token to its current database user."""
        db = self._require_db()
        try:
            return await AuthTokenService(
                db,
                settings=self.settings,
                token_verifier=self.token_verifier,
            ).resolve_user(token)
        except InvalidAuthTokenError as exc:
            raise OAuthTokenValidationError(
                OAUTH_TOKEN_VALIDATION_FAILED_MESSAGE
            ) from exc
        except AuthTokenError as exc:
            raise OAuthTokenValidationError(
                OAUTH_TOKEN_VALIDATION_FAILED_MESSAGE
            ) from exc

    def _require_db(self) -> AsyncSession:
        if self.db is None:
            raise RuntimeError("OAuthSessionService requires a database session")
        return self.db
