"""Public SSE error contract for backend diagram streaming."""

from __future__ import annotations

from loguru import logger

from app.core.exceptions import ProjectNotFoundException
from app.core.sse import format_sse_event
from app.services.diagram_generation_contract import GenerationInputValidationError
from app.services.llm_client import BackendLLMConfigurationError
from app.services.workflow_runtime.event_payloads import (
    StreamErrorPayload,
    StreamErrorStage,
)


GENERIC_GENERATION_ERROR = "Diagram generation failed"
STREAM_INIT_ERROR_DETAIL = "The streaming generation request could not start."
STREAM_GENERATION_ERROR_DETAIL = "The streaming generation request could not complete."
STREAM_REWRITE_ERROR_DETAIL = "The streaming generation result could not be processed."

GENERATION_STREAM_ERROR_TYPES = (
    BackendLLMConfigurationError,
    GenerationInputValidationError,
    ValueError,
)
REWRITE_STREAM_ERROR_TYPES = (
    BackendLLMConfigurationError,
    ProjectNotFoundException,
    GenerationInputValidationError,
    ValueError,
)


class _StreamErrorPayload(StreamErrorPayload):
    """Stable SSE error payload exposed to clients."""


def _stream_error_payload(
    *,
    stage: StreamErrorStage = "init",
    message: str = GENERIC_GENERATION_ERROR,
    detail: str = STREAM_INIT_ERROR_DETAIL,
) -> dict[str, str]:
    """Build the public SSE error payload for streaming failures."""
    return _StreamErrorPayload(
        stage=stage,
        message=message,
        detail=detail,
    ).to_public_dict()


def _generation_error_stage(*, emitted_chunk: bool) -> StreamErrorStage:
    """Return the streaming stage that best describes a generation failure."""
    return "generation" if emitted_chunk else "init"


def _generation_error_detail(*, emitted_chunk: bool) -> str:
    """Return the public detail for a streaming generation failure."""
    return (
        STREAM_GENERATION_ERROR_DETAIL
        if emitted_chunk
        else STREAM_INIT_ERROR_DETAIL
    )


def _generation_stream_error_payload(
    exc: BaseException,
    *,
    emitted_chunk: bool,
) -> _StreamErrorPayload:
    """Map generation exceptions to the stable public SSE error contract."""
    stage = _generation_error_stage(emitted_chunk=emitted_chunk)
    if isinstance(exc, GenerationInputValidationError):
        return _StreamErrorPayload(
            stage=stage,
            message=exc.public_detail,
            detail=exc.public_detail,
        )

    return _StreamErrorPayload(
        stage=stage,
        message=GENERIC_GENERATION_ERROR,
        detail=_generation_error_detail(emitted_chunk=emitted_chunk),
    )


def _rewrite_stream_error_payload(exc: BaseException) -> _StreamErrorPayload:
    """Map rewrite exceptions to the stable public SSE error contract."""
    if isinstance(exc, GenerationInputValidationError):
        return _StreamErrorPayload(
            stage="rewrite",
            message=exc.public_detail,
            detail=exc.public_detail,
        )

    return _StreamErrorPayload(
        stage="rewrite",
        message=GENERIC_GENERATION_ERROR,
        detail=STREAM_REWRITE_ERROR_DETAIL,
    )


def _format_stream_error_payload(payload: _StreamErrorPayload) -> str:
    """Serialize a prepared public streaming error payload."""
    return format_sse_event("error", payload.to_public_dict())


def _log_generation_stream_error(
    exc: BaseException,
    *,
    emitted_chunk: bool,
) -> None:
    """Log generation errors with private diagnostics while preserving public SSE."""
    if isinstance(exc, GenerationInputValidationError):
        logger.warning("Streaming diagram generation rejected: {}", exc)
    elif isinstance(exc, BackendLLMConfigurationError):
        logger.exception("Streaming generation backend LLM configuration is invalid")
    elif isinstance(exc, ValueError):
        logger.exception(
            "Streaming diagram generation failed with internal validation error"
        )
    elif emitted_chunk:
        logger.exception("Streaming diagram generation failed after streaming started")
    else:
        logger.exception("Streaming diagram generation failed before streaming started")


def _log_rewrite_stream_error(exc: BaseException) -> None:
    """Log rewrite errors with private diagnostics while preserving public SSE."""
    if isinstance(exc, GenerationInputValidationError):
        logger.warning("Streaming diagram chunk rewrite rejected: {}", exc)
    elif isinstance(exc, ProjectNotFoundException):
        logger.warning("Streaming chunk rewrite rejected: {}", exc)
    elif isinstance(exc, BackendLLMConfigurationError):
        logger.exception("Streaming chunk rewrite backend LLM configuration is invalid")
    elif isinstance(exc, ValueError):
        logger.exception(
            "Streaming diagram chunk rewrite failed with internal validation error"
        )
    else:
        logger.exception("Streaming diagram chunk rewrite failed")
