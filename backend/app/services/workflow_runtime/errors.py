"""Sanitized workflow error contracts for backend streaming generation."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.workflow_runtime.event_payloads import (
    RefineErrorPayload,
    StreamErrorPayload,
)


PUBLIC_STAGE_ERROR_MESSAGE = "Diagram generation failed"
PUBLIC_STAGE_ERROR_DETAIL = "The diagram generation stage failed."
PUBLIC_REFINER_ERROR_MESSAGE = "Refiner failed"
PUBLIC_REFINER_ERROR_DETAIL = "Auto-refinement could not complete."
PUBLIC_REFINER_DEGRADED_MESSAGE = "Auto-refinement failed; using base diagram."
PUBLIC_REFINER_NOT_NEEDED_MESSAGE = "No auto-refinement needed."
PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE = (
    "Auto-refinement is currently available for Excalidraw only."
)
PUBLIC_REFINER_START_MESSAGE = "Refiner Agent is fixing visual issues..."
PUBLIC_REFINER_COMPLETE_MESSAGE = "Refining complete"
PUBLIC_REFINER_DISABLED_MESSAGE = "Automatic refinement is disabled in server settings"
REFINER_FAILURE_VERIFICATION = "verification"
REFINER_FAILURE_EXECUTION = "execution"
REFINER_FAILURE_ARTIFACT = "artifact"
REFINER_STAGE_INDEX = 7
REFINER_TOTAL_STAGES = 9


@dataclass(frozen=True)
class WorkflowStageFailure:
    """Sanitized failure metadata for a streaming workflow stage."""

    request_id: str
    stage: str
    error_type: str

    def public_payload(self) -> dict[str, str]:
        """Return the client-safe SSE error payload."""
        return StreamErrorPayload(
            stage=self.stage,
            message=PUBLIC_STAGE_ERROR_MESSAGE,
            detail=PUBLIC_STAGE_ERROR_DETAIL,
        ).to_public_dict()

    def log_context(self) -> dict[str, str]:
        """Return structured fields for backend diagnostics."""
        return {
            "request_id": self.request_id,
            "stage": self.stage,
            "error_type": self.error_type,
        }


class RefinerPipelineError(RuntimeError):
    """Internal refiner failure with a sanitized phase for diagnostics."""

    def __init__(self, *, phase: str, reason: str):
        super().__init__(reason)
        self.phase = phase


class RefinerExecutionStatusError(RefinerPipelineError):
    """Refiner completed its call but reported a failed terminal status."""


class RefinerArtifactError(RefinerPipelineError):
    """Refiner produced incomplete or unusable output artifacts."""


@dataclass(frozen=True)
class RefinerFailure:
    """Sanitized failure metadata for the optional refinement pipeline."""

    request_id: str
    phase: str
    error_type: str

    def public_payload(self) -> dict[str, str]:
        """Return the client-safe SSE refiner error payload."""
        return _refine_error_payload()

    def log_context(self) -> dict[str, str]:
        """Return structured fields for backend diagnostics."""
        return {
            "request_id": self.request_id,
            "stage": "refining",
            "phase": self.phase,
            "error_type": self.error_type,
        }


def _stage_failure(
    *,
    request_id: str,
    stage: str,
    exc: Exception,
) -> WorkflowStageFailure:
    return WorkflowStageFailure(
        request_id=request_id,
        stage=stage,
        error_type=type(exc).__name__,
    )


def _refine_error_payload() -> dict[str, str]:
    return RefineErrorPayload(
        message=PUBLIC_REFINER_ERROR_MESSAGE,
        detail=PUBLIC_REFINER_ERROR_DETAIL,
    ).to_public_dict()


def _refiner_failure(
    *,
    request_id: str,
    exc: Exception,
) -> RefinerFailure:
    cause = exc.__cause__ or exc
    phase = (
        exc.phase
        if isinstance(exc, RefinerPipelineError)
        else REFINER_FAILURE_EXECUTION
    )
    return RefinerFailure(
        request_id=request_id,
        phase=phase,
        error_type=type(cause).__name__,
    )


def _wrap_refiner_error(
    *,
    phase: str,
    reason: str,
    exc: Exception,
) -> RefinerPipelineError:
    error = RefinerPipelineError(phase=phase, reason=reason)
    error.__cause__ = exc
    return error
