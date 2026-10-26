from fastapi import status

LOWERCASE_PROJECT_NOT_FOUND_DETAIL = "project not found"


__all__ = (
    "AppException",
    "EmailAlreadyExistsException",
    "InvalidCredentialsException",
    "InvalidVerificationCodeException",
    "ProjectNotFoundException",
    "PublicErrorMixin",
    "UserNotFoundException",
)


class PublicErrorMixin:
    """Mixin for domain errors that expose a safe client-facing detail."""

    default_public_detail = "Application error"

    def __init__(
        self,
        message: str | None = None,
        *,
        public_detail: str | None = None,
    ):
        self.public_detail = public_detail or self.default_public_detail
        super().__init__(message or self.public_detail)


class AppException(Exception):
    """Base class for domain failures that can cross API boundaries."""

    default_public_detail: str | None = None

    def __init__(
        self,
        message: str | None = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        *,
        public_detail: str | None = None,
    ):
        resolved_message = (
            message
            or public_detail
            or self.default_public_detail
            or "Application error"
        )
        self.message = resolved_message
        self.status_code = status_code
        self.public_detail = (
            public_detail
            if public_detail is not None
            else self.default_public_detail or "Application error"
        )
        super().__init__(self.message)


class UserNotFoundException(AppException):
    """Raised when a user lookup misses."""

    default_public_detail = "User not found"

    def __init__(self, message: str | None = None):
        super().__init__(message, status.HTTP_404_NOT_FOUND)


class ProjectNotFoundException(AppException):
    """Raised when a project lookup misses or is not owned by the user."""

    default_public_detail = "Project not found"

    def __init__(
        self,
        message: str | None = None,
        *,
        public_detail: str | None = None,
    ):
        super().__init__(
            message,
            status.HTTP_404_NOT_FOUND,
            public_detail=public_detail,
        )


class EmailAlreadyExistsException(AppException):
    """Raised when an email registration would violate uniqueness."""

    default_public_detail = "This email is already registered"

    def __init__(self, message: str | None = None):
        super().__init__(message, status.HTTP_409_CONFLICT)


class InvalidCredentialsException(AppException):
    """Raised when email/password authentication fails."""

    default_public_detail = "Incorrect email or password"

    def __init__(self, message: str | None = None):
        super().__init__(message, status.HTTP_401_UNAUTHORIZED)


class InvalidVerificationCodeException(AppException):
    """Raised when signup verification fails."""

    default_public_detail = "Incorrect verification code"

    def __init__(self, message: str | None = None):
        super().__init__(message, status.HTTP_400_BAD_REQUEST)
