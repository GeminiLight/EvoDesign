from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Optional
from loguru import logger

from app.db.base import utc_now
from app.models.user import User
from app.core.security import hash_password, verify_password, generate_token
from app.config import Settings, get_settings
from app.core.exceptions import (
    EmailAlreadyExistsException,
    InvalidCredentialsException,
    InvalidVerificationCodeException,
)


class OAuthAccountLinkRequiredError(ValueError):
    """Raised when an OAuth identity matches an existing email account."""

    def __init__(self, email: str):
        self.email = email
        super().__init__("Account linking required for this email")


def normalize_email(email: str) -> str:
    """Return the canonical email string used for identity lookups."""
    return email.strip().lower()


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Return a user by email address."""
        normalized_email = normalize_email(email)
        result = await self.db.execute(
            select(User).where(User.email == normalized_email)
        )
        return result.scalar_one_or_none()

    async def get_user_by_provider_id(
        self, auth_provider: str, external_id: str
    ) -> Optional[User]:
        """Return a user by OAuth provider identity."""
        result = await self.db.execute(
            select(User).where(
                User.auth_provider == auth_provider,
                User.external_id == external_id
            )
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
        password: Optional[str] = None,
        auth_provider: str = "email",
        external_id: Optional[str] = None
    ) -> User:
        """Create a new user."""
        normalized_email = normalize_email(email)
        user = User(
            email=normalized_email,
            username=username or normalized_email.split("@")[0],
            avatar_url=avatar_url,
            password_hash=hash_password(password) if password else None,
            auth_provider=auth_provider,
            external_id=external_id,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def upsert_oauth_user(
        self,
        email: str,
        username: str,
        avatar_url: Optional[str],
        auth_provider: str,
        external_id: str
    ) -> User:
        """Create or update a user for a known OAuth provider identity."""
        normalized_email = normalize_email(email)
        user = await self.get_user_by_provider_id(auth_provider, external_id)

        if user:
            user.username = username
            user.avatar_url = avatar_url
            user.last_login_at = utc_now()
            user.updated_at = utc_now()
            await self.db.flush()
            await self.db.refresh(user)
            return user

        existing_email_user = await self.get_user_by_email(normalized_email)
        if existing_email_user:
            raise OAuthAccountLinkRequiredError(normalized_email)

        try:
            return await self.create_user(
                email=normalized_email,
                username=username,
                avatar_url=avatar_url,
                auth_provider=auth_provider,
                external_id=external_id
            )
        except IntegrityError as exc:
            await self.db.rollback()
            raced_provider_user = await self.get_user_by_provider_id(
                auth_provider,
                external_id,
            )
            if raced_provider_user:
                logger.info(
                    "Recovered concurrent OAuth identity creation for provider: {}",
                    auth_provider,
                )
                return raced_provider_user

            raced_email_user = await self.get_user_by_email(normalized_email)
            if raced_email_user:
                raise OAuthAccountLinkRequiredError(normalized_email) from exc
            raise

    async def register(
        self,
        email: str,
        password: str,
        username: Optional[str] = None,
        verification_code: str = "",
    ) -> User:
        """Register a new email/password user."""
        normalized_email = normalize_email(email)
        if (
            self.settings.enable_signup_verification
            and verification_code != self.settings.signup_verification_code
        ):
            raise InvalidVerificationCodeException()

        existing_user = await self.get_user_by_email(normalized_email)
        if existing_user:
            raise EmailAlreadyExistsException()

        try:
            user = await self.create_user(
                email=normalized_email,
                username=username,
                password=password,
                auth_provider="email"
            )
        except IntegrityError as exc:
            await self.db.rollback()
            raced_email_user = await self.get_user_by_email(normalized_email)
            if raced_email_user:
                logger.info(
                    "Rejected concurrent registration for an existing email",
                )
                raise EmailAlreadyExistsException() from exc
            raise

        logger.info("New user registered: {}", normalized_email)
        return user

    async def login(self, email: str, password: str) -> User:
        """Authenticate an email/password user."""
        normalized_email = normalize_email(email)
        user = await self.get_user_by_email(normalized_email)

        if not user or user.auth_provider != "email":
            raise InvalidCredentialsException()

        if not user.password_hash or not verify_password(password, user.password_hash):
            raise InvalidCredentialsException()

        user.last_login_at = utc_now()
        await self.db.flush()

        logger.info("User logged in: {}", normalized_email)
        return user

    def generate_user_token(self, user: User) -> str:
        """Generate an access token for a user."""
        return generate_token(user, settings=self.settings)
