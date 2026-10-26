from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.db.session import get_db
from app.api.deps import AuthContext, get_current_auth
from app.schemas.auth import LoginRequest, RegisterRequest, AuthResponse, CodeExchangeRequest
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService
from app.services.oauth_session_service import (
    OAUTH_STATE_COOKIE_NAME,
    OAUTH_STATE_COOKIE_PATH,
    OAUTH_STATE_TTL_SECONDS,
    InvalidOAuthCodeError,
    OAuthCallbackError,
    OAuthProvider,
    OAuthProviderNotConfiguredError,
    OAuthSessionService,
    OAuthStateConsumption,
    OAuthStateError,
    OAuthTokenValidationError,
)
from app.config import Settings, get_settings
from app.core.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _oauth_provider_unavailable(
    provider: OAuthProvider,
    exc: OAuthProviderNotConfiguredError,
) -> HTTPException:
    """Return a client-safe error for missing provider configuration."""
    logger.warning("{} OAuth provider is unavailable: {}", provider, exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=exc.public_detail,
    )


def _apply_oauth_state_cookie(
    response: Response,
    consumption: OAuthStateConsumption,
) -> None:
    """Rewrite the pending-state cookie after a callback consumed one state.

    The consumed state is gone (single use), but other tabs' logins survive in
    the re-signed list; the cookie is deleted only once the last state is used.
    """
    if consumption.remaining_state_cookie is None:
        response.delete_cookie(OAUTH_STATE_COOKIE_NAME, path=OAUTH_STATE_COOKIE_PATH)
        return
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        consumption.remaining_state_cookie,
        max_age=OAUTH_STATE_TTL_SECONDS,
        path=OAUTH_STATE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=consumption.state_cookie_secure,
    )


async def _complete_oauth_callback(
    provider: OAuthProvider,
    code: str,
    state: str | None,
    state_cookie: str | None,
    db: AsyncSession,
    settings: Settings,
) -> RedirectResponse:
    """Complete an OAuth provider callback and map expected failures."""
    oauth_service = OAuthSessionService(db, settings=settings)
    try:
        # State is consumed before the code is exchanged, so a forged callback
        # never reaches the provider token endpoint and a matched state can
        # never be replayed.
        consumption = oauth_service.consume_oauth_state(
            provider=provider,
            state=state,
            state_cookie=state_cookie,
        )
    except OAuthStateError as exc:
        # Leave the state cookie untouched: it may still hold pending states
        # for other tabs, and an unmatched callback proved nothing about them.
        logger.warning("{} OAuth callback rejected by state validation: {}", provider, exc)
        return RedirectResponse(
            url=oauth_service.failure_redirect_url(exc.redirect_error)
        )

    try:
        redirect_url = await oauth_service.complete_provider_callback(provider, code)
    except OAuthProviderNotConfiguredError as exc:
        raise _oauth_provider_unavailable(provider, exc) from exc
    except OAuthCallbackError as exc:
        logger.warning("{} OAuth callback failed: {}", provider, exc)
        response = RedirectResponse(
            url=oauth_service.failure_redirect_url(exc.redirect_error)
        )
        _apply_oauth_state_cookie(response, consumption)
        return response

    response = RedirectResponse(url=redirect_url)
    _apply_oauth_state_cookie(response, consumption)
    return response


async def _oauth_login_redirect(
    provider: OAuthProvider,
    settings: Settings,
    existing_state_cookie: str | None,
) -> RedirectResponse:
    """Build an OAuth provider authorization redirect and map expected failures."""
    oauth_service = OAuthSessionService(settings=settings)
    try:
        authorization = await oauth_service.build_authorization_redirect(
            provider,
            existing_state_cookie=existing_state_cookie,
        )
    except OAuthProviderNotConfiguredError as exc:
        raise _oauth_provider_unavailable(provider, exc) from exc

    response = RedirectResponse(url=authorization.authorization_url)
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        authorization.state_cookie,
        max_age=OAUTH_STATE_TTL_SECONDS,
        path=OAUTH_STATE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=authorization.state_cookie_secure,
    )
    return response


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Email/password login"""
    auth_service = AuthService(db, settings=settings)

    user = await auth_service.login(body.email, body.password)
    token = auth_service.generate_user_token(user)

    return AuthResponse(
        token=token,
        user=UserResponse.model_validate(user)
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Email/password registration"""
    auth_service = AuthService(db, settings=settings)

    user = await auth_service.register(
        email=body.email,
        password=body.password,
        username=body.username,
        verification_code=body.verification_code,
    )
    token = auth_service.generate_user_token(user)

    return AuthResponse(
        token=token,
        user=UserResponse.model_validate(user)
    )


@router.get("/me", response_model=AuthResponse)
async def get_current_user_info(
    auth_context: AuthContext = Depends(get_current_auth),
):
    """Get current user info"""
    return AuthResponse(
        token=auth_context.token,
        user=UserResponse.model_validate(auth_context.require_user())
    )


@router.get("/google")
async def google_login(
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
):
    """Google OAuth login"""
    return await _oauth_login_redirect("google", settings, state_cookie)


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str | None = None,
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Google OAuth callback"""
    return await _complete_oauth_callback(
        "google",
        code,
        state,
        state_cookie,
        db,
        settings,
    )


@router.get("/github")
async def github_login(
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
):
    """GitHub OAuth login"""
    return await _oauth_login_redirect("github", settings, state_cookie)


@router.get("/github/callback")
async def github_callback(
    code: str,
    state: str | None = None,
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """GitHub OAuth callback"""
    return await _complete_oauth_callback(
        "github",
        code,
        state,
        state_cookie,
        db,
        settings,
    )


@router.post("/exchange", response_model=AuthResponse)
async def exchange_oauth_code(
    body: CodeExchangeRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Exchange a single-use OAuth code for a JWT token."""
    oauth_service = OAuthSessionService(db, settings=settings)
    try:
        exchange_result = await oauth_service.exchange_code(body.code)
    except InvalidOAuthCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.public_detail,
        ) from exc
    except OAuthTokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.public_detail,
        ) from exc

    return AuthResponse(
        token=exchange_result.token,
        user=UserResponse.model_validate(exchange_result.user),
    )
