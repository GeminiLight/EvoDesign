from __future__ import annotations

import pytest
from fastapi import status
from fastapi import HTTPException

from app.api.errors import (
    ApiErrorMapping,
    ApiErrorPolicy,
    api_error_to_http_exception,
    is_mapped_api_error,
    public_error_detail,
    raise_api_error,
)
from app.core.exceptions import PublicErrorMixin


class SamplePublicError(PublicErrorMixin, RuntimeError):
    default_public_detail = "safe public detail"


class RecordingLogger:
    def __init__(self):
        self.exception_messages = []

    def exception(self, message: str) -> None:
        self.exception_messages.append(message)


def test_public_error_detail_uses_safe_public_detail():
    exc = SamplePublicError("internal secret context")

    assert public_error_detail(exc, "fallback detail") == "safe public detail"


def test_public_error_detail_falls_back_for_plain_exceptions():
    exc = RuntimeError("internal secret context")

    assert public_error_detail(exc, "fallback detail") == "fallback detail"


def test_public_error_detail_falls_back_for_empty_or_non_string_details():
    class ErrorWithUnsafeDetail(RuntimeError):
        pass

    for unsafe_detail in ("", None, {"detail": "internal secret"}):
        exc = ErrorWithUnsafeDetail("internal secret context")
        exc.public_detail = unsafe_detail

        assert public_error_detail(exc, "fallback detail") == "fallback detail"


def test_is_mapped_api_error_matches_subclasses():
    class DerivedPublicError(SamplePublicError):
        pass

    mappings = (ApiErrorMapping(SamplePublicError, status.HTTP_400_BAD_REQUEST),)

    assert is_mapped_api_error(DerivedPublicError(), mappings) is True


def test_is_mapped_api_error_returns_false_for_unmapped_exceptions():
    mappings = (ApiErrorMapping(SamplePublicError, status.HTTP_400_BAD_REQUEST),)

    assert is_mapped_api_error(RuntimeError("internal secret context"), mappings) is False


def test_api_error_to_http_exception_maps_public_errors_without_leaking_messages():
    exc = SamplePublicError("internal secret context")

    http_exc = api_error_to_http_exception(
        exc,
        mappings=(ApiErrorMapping(SamplePublicError, status.HTTP_409_CONFLICT),),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )

    assert http_exc.status_code == status.HTTP_409_CONFLICT
    assert http_exc.detail == "safe public detail"
    assert "secret" not in http_exc.detail


def test_api_error_to_http_exception_uses_first_matching_mapping():
    class DerivedPublicError(SamplePublicError):
        pass

    http_exc = api_error_to_http_exception(
        DerivedPublicError("internal secret context"),
        mappings=(
            ApiErrorMapping(DerivedPublicError, status.HTTP_404_NOT_FOUND),
            ApiErrorMapping(SamplePublicError, status.HTTP_400_BAD_REQUEST),
        ),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )

    assert http_exc.status_code == status.HTTP_404_NOT_FOUND
    assert http_exc.detail == "safe public detail"


def test_api_error_to_http_exception_uses_fallback_for_unmapped_errors():
    http_exc = api_error_to_http_exception(
        RuntimeError("database password leaked"),
        mappings=(ApiErrorMapping(SamplePublicError, status.HTTP_409_CONFLICT),),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )

    assert http_exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert http_exc.detail == "fallback detail"


def test_api_error_policy_maps_public_errors_without_repeating_fallbacks():
    policy = ApiErrorPolicy(
        mappings=(ApiErrorMapping(SamplePublicError, status.HTTP_409_CONFLICT),),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )
    exc = SamplePublicError("internal secret context")

    http_exc = policy.to_http_exception(exc)

    assert policy.is_mapped(exc) is True
    assert http_exc.status_code == status.HTTP_409_CONFLICT
    assert http_exc.detail == "safe public detail"
    assert "secret" not in http_exc.detail


def test_api_error_policy_uses_first_matching_mapping():
    class DerivedPublicError(SamplePublicError):
        pass

    policy = ApiErrorPolicy(
        mappings=(
            ApiErrorMapping(DerivedPublicError, status.HTTP_404_NOT_FOUND),
            ApiErrorMapping(SamplePublicError, status.HTTP_400_BAD_REQUEST),
        ),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )

    http_exc = policy.to_http_exception(DerivedPublicError("internal secret context"))

    assert http_exc.status_code == status.HTTP_404_NOT_FOUND
    assert http_exc.detail == "safe public detail"


def test_api_error_policy_uses_fallback_for_unmapped_errors():
    policy = ApiErrorPolicy(
        mappings=(ApiErrorMapping(SamplePublicError, status.HTTP_409_CONFLICT),),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )
    exc = RuntimeError("database password leaked")

    http_exc = policy.to_http_exception(exc)

    assert policy.is_mapped(exc) is False
    assert http_exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert http_exc.detail == "fallback detail"


def test_raise_api_error_maps_without_logging_expected_errors():
    policy = ApiErrorPolicy(
        mappings=(ApiErrorMapping(SamplePublicError, status.HTTP_409_CONFLICT),),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )
    logger = RecordingLogger()
    exc = SamplePublicError("internal secret context")

    with pytest.raises(HTTPException) as exc_info:
        raise_api_error(
            exc,
            policy=policy,
            logger=logger,
            log_message="Operation failed",
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "safe public detail"
    assert exc_info.value.__cause__ is exc
    assert logger.exception_messages == []


def test_raise_api_error_logs_unmapped_errors_before_fallback():
    policy = ApiErrorPolicy(
        mappings=(ApiErrorMapping(SamplePublicError, status.HTTP_409_CONFLICT),),
        fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        fallback_detail="fallback detail",
    )
    logger = RecordingLogger()
    exc = RuntimeError("database password leaked")

    with pytest.raises(HTTPException) as exc_info:
        raise_api_error(
            exc,
            policy=policy,
            logger=logger,
            log_message="Operation failed",
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "fallback detail"
    assert exc_info.value.__cause__ is exc
    assert logger.exception_messages == ["Operation failed"]
