"""JWT-to-user resolution service."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.security import verify_token
from app.models.user import User


TokenVerifier = Callable[..., Mapping[str, Any] | None]


class AuthTokenError(ValueError):
    """Base class for bearer token resolution failures."""


class InvalidAuthTokenError(AuthTokenError):
    """Raised when a JWT cannot be verified."""

    def __init__(self):
        super().__init__("Invalid or expired authentication token")


class InvalidTokenPayloadError(AuthTokenError):
    """Raised when a verified JWT is missing required identity fields."""

    def __init__(self):
        super().__init__("Invalid token payload")


class AuthTokenUserNotFoundError(AuthTokenError):
    """Raised when a verified JWT references a missing user."""

    def __init__(self):
        super().__init__("User not found")


class AuthTokenService:
    """Resolve bearer JWTs to current database users."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Settings | None = None,
        token_verifier: TokenVerifier = verify_token,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.token_verifier = token_verifier

    async def resolve_user(self, token: str) -> User:
        """Verify a JWT and return the current user it identifies."""
        payload = self.token_verifier(token, settings=self.settings)
        if not payload:
            raise InvalidAuthTokenError()

        user_id = payload.get("user_id")
        if not user_id:
            raise InvalidTokenPayloadError()

        result = await self.db.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise AuthTokenUserNotFoundError()

        return user
