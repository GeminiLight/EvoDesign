from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.rate_limit import bind_rate_limit_identity
from app.db.session import get_db
from app.models.user import User
from app.services.auth_token_service import AuthTokenError, AuthTokenService

security = HTTPBearer(auto_error=False)
AUTH_TOKEN_NOT_PROVIDED_DETAIL = "Authentication token not provided"
INVALID_AUTH_TOKEN_DETAIL = "Invalid or expired authentication token"


@dataclass(frozen=True)
class AuthContext:
    """Resolved bearer-token authentication context for request handlers."""

    token: str
    user: User | None
    is_guest: bool = False

    def require_user(self) -> User:
        """Return the authenticated user or raise the standard login-required error."""
        if self.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_TOKEN_NOT_PROVIDED_DETAIL,
            )
        return self.user


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _get_token(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials:
        raise _unauthorized(AUTH_TOKEN_NOT_PROVIDED_DETAIL)
    return credentials.credentials


async def _load_user_from_token(
    *,
    token: str,
    db: AsyncSession,
    settings: Settings,
) -> User:
    try:
        return await AuthTokenService(db, settings=settings).resolve_user(token)
    except AuthTokenError as exc:
        raise _unauthorized(INVALID_AUTH_TOKEN_DETAIL) from exc


async def _resolve_auth_context(
    *,
    credentials: Optional[HTTPAuthorizationCredentials],
    db: AsyncSession,
    settings: Settings,
    allow_guest: bool,
) -> AuthContext:
    token = _get_token(credentials)

    if allow_guest and settings.guest_token and token == settings.guest_token:
        return AuthContext(token=token, user=None, is_guest=True)

    user = await _load_user_from_token(token=token, db=db, settings=settings)
    return AuthContext(token=token, user=user)


async def get_current_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    """Return the resolved auth context for authenticated-only routes."""
    return await _resolve_auth_context(
        credentials=credentials,
        db=db,
        settings=settings,
        allow_guest=False,
    )


async def get_current_user(
    auth_context: AuthContext = Depends(get_current_auth),
) -> User:
    """Return the authenticated user for routes that require login."""
    return auth_context.require_user()


async def get_current_user_id(
    current_user: User = Depends(get_current_user),
) -> str:
    """Return the authenticated user's ID string."""
    return current_user.user_id


async def get_current_user_or_guest(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Optional[User]:
    """Return a User for bearer JWTs, or None for the configured guest token."""
    auth_context = await _resolve_auth_context(
        credentials=credentials,
        db=db,
        settings=settings,
        allow_guest=True,
    )
    return auth_context.user


async def get_current_user_id_or_none(
    current_user: User | None = Depends(get_current_user_or_guest),
) -> str | None:
    """Return user_id for authenticated users, or None for guests."""
    return current_user.user_id if current_user else None


async def get_rate_limited_user_or_guest(
    request: Request,
    current_user: User | None = Depends(get_current_user_or_guest),
) -> User | None:
    """Resolve user-or-guest and key per-minute limits by account when signed in."""
    if current_user is not None:
        bind_rate_limit_identity(request, current_user.user_id)
    return current_user


async def get_rate_limited_user_id(
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> str:
    """Resolve the signed-in user and key per-minute limits by account."""
    bind_rate_limit_identity(request, user_id)
    return user_id


async def release_db_connection(db: AsyncSession) -> None:
    """Commit the auth transaction so no pooled connection is held during long work.

    The session stays usable afterwards; it checks out a fresh connection on
    its next query. Loaded objects stay readable because sessions are created
    with expire_on_commit=False.
    """
    await db.commit()
