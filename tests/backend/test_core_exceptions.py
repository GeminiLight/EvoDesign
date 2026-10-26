from __future__ import annotations

from fastapi import status

import app.core.exceptions as exceptions
from app.core.exceptions import (
    AppException,
    EmailAlreadyExistsException,
    InvalidCredentialsException,
    InvalidVerificationCodeException,
    ProjectNotFoundException,
    PublicErrorMixin,
    UserNotFoundException,
)


def test_core_exceptions_exports_current_domain_error_surface():
    assert exceptions.__all__ == (
        "AppException",
        "EmailAlreadyExistsException",
        "InvalidCredentialsException",
        "InvalidVerificationCodeException",
        "ProjectNotFoundException",
        "PublicErrorMixin",
        "UserNotFoundException",
    )
    assert not hasattr(exceptions, "UnauthorizedException")
    assert not hasattr(exceptions, "InvalidTokenException")
    assert not hasattr(exceptions, "OAuthException")


def test_base_app_exception_keeps_internal_message_private_by_default():
    exc = AppException("internal project secret", status.HTTP_418_IM_A_TEAPOT)

    assert str(exc) == "internal project secret"
    assert exc.message == "internal project secret"
    assert exc.status_code == status.HTTP_418_IM_A_TEAPOT
    assert exc.public_detail == "Application error"


def test_public_error_mixin_keeps_internal_message_private():
    class SamplePublicError(PublicErrorMixin, ValueError):
        default_public_detail = "safe public detail"

    exc = SamplePublicError("internal secret context")

    assert str(exc) == "internal secret context"
    assert exc.public_detail == "safe public detail"
    assert "secret" not in exc.public_detail


def test_public_error_mixin_can_override_public_detail():
    class SamplePublicError(PublicErrorMixin, RuntimeError):
        default_public_detail = "safe public detail"

    exc = SamplePublicError(
        "internal secret context",
        public_detail="custom public detail",
    )

    assert str(exc) == "internal secret context"
    assert exc.public_detail == "custom public detail"


def test_base_app_exception_can_set_explicit_public_detail():
    exc = AppException(
        "internal project secret",
        status.HTTP_418_IM_A_TEAPOT,
        public_detail="public contract detail",
    )

    assert str(exc) == "internal project secret"
    assert exc.message == "internal project secret"
    assert exc.public_detail == "public contract detail"


def test_domain_exceptions_keep_default_public_details_with_internal_messages():
    cases = [
        (
            EmailAlreadyExistsException,
            status.HTTP_409_CONFLICT,
            "This email is already registered",
        ),
        (
            InvalidCredentialsException,
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
        ),
        (
            InvalidVerificationCodeException,
            status.HTTP_400_BAD_REQUEST,
            "Incorrect verification code",
        ),
        (ProjectNotFoundException, status.HTTP_404_NOT_FOUND, "Project not found"),
        (UserNotFoundException, status.HTTP_404_NOT_FOUND, "User not found"),
    ]

    for exception_cls, status_code, public_detail in cases:
        exc = exception_cls("internal secret context")
        assert exc.status_code == status_code
        assert exc.message == "internal secret context"
        assert exc.public_detail == public_detail
