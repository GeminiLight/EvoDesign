from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from loguru import logger

from app.config import Settings, get_settings

# Password hashing context
# pbkdf2_sha256 is stable across the Python and bcrypt versions used locally and in CI.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Generate password hash"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
    settings: Settings | None = None,
) -> str:
    """Create JWT access token"""
    settings = settings or get_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_expires_in)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def verify_token(token: str, settings: Settings | None = None) -> Optional[dict[str, Any]]:
    """Verify JWT token and return payload"""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError as exc:
        # Expired or malformed tokens are client-driven and must not fill error.log.
        logger.debug("JWT verification failed: {}", exc)
        return None


def generate_token(user: Any, settings: Settings | None = None) -> str:
    """Generate JWT token for a user"""
    token_data = {
        "user_id": user.user_id,
        "email": user.email,
        "auth_provider": user.auth_provider,
    }
    return create_access_token(token_data, settings=settings)
