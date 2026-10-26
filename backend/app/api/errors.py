"""Helpers for translating domain errors into public HTTP responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, Protocol

from fastapi import HTTPException


class ApiErrorLogger(Protocol):
    """Logger interface needed by the public API error boundary."""

    def exception(self, message: str) -> None:
        """Record an unexpected exception at the API boundary."""


@dataclass(frozen=True)
class ApiErrorMapping:
    """HTTP status mapping for a domain exception type."""

    error_type: type[BaseException]
    status_code: int


@dataclass(frozen=True)
class ApiErrorPolicy:
    """Public HTTP response policy for a bounded API operation."""

    mappings: tuple[ApiErrorMapping, ...]
    fallback_status_code: int
    fallback_detail: str

    def is_mapped(self, exc: BaseException) -> bool:
        """Return whether an exception has an explicit API mapping."""
        return is_mapped_api_error(exc, self.mappings)

    def to_http_exception(self, exc: BaseException) -> HTTPException:
        """Build a public HTTPException for this operation."""
        return api_error_to_http_exception(
            exc,
            mappings=self.mappings,
            fallback_status_code=self.fallback_status_code,
            fallback_detail=self.fallback_detail,
        )


def public_error_detail(exc: BaseException, fallback_detail: str) -> str:
    """Return a safe public detail from a domain error."""
    detail = getattr(exc, "public_detail", None)
    if isinstance(detail, str) and detail:
        return detail
    return fallback_detail


def is_mapped_api_error(
    exc: BaseException,
    mappings: tuple[ApiErrorMapping, ...],
) -> bool:
    """Return whether an exception has an explicit API mapping."""
    return any(isinstance(exc, mapping.error_type) for mapping in mappings)


def api_error_to_http_exception(
    exc: BaseException,
    *,
    mappings: tuple[ApiErrorMapping, ...],
    fallback_status_code: int,
    fallback_detail: str,
) -> HTTPException:
    """Build an HTTPException without leaking internal exception messages."""
    for mapping in mappings:
        if isinstance(exc, mapping.error_type):
            return HTTPException(
                status_code=mapping.status_code,
                detail=public_error_detail(exc, fallback_detail),
            )

    return HTTPException(
        status_code=fallback_status_code,
        detail=fallback_detail,
    )


def raise_api_error(
    exc: BaseException,
    *,
    policy: ApiErrorPolicy,
    logger: ApiErrorLogger,
    log_message: str,
) -> NoReturn:
    """Raise a public HTTPException and log only unmapped API failures."""
    if not policy.is_mapped(exc):
        logger.exception(log_message)
    raise policy.to_http_exception(exc) from exc
