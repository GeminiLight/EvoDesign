"""SSE event payload helpers for backend workflow streaming."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.core.sse import format_sse_event
from app.services.workflow_runtime.event_payloads import (
    REFINE_COMPLETE_STATUSES,
    RefineCompletePayload,
    RefineCompleteStatus,
    RefinerSkippedPayload,
    StageCompletePayload,
    StageStartPayload,
)
from app.services.workflow_runtime.errors import (
    PUBLIC_REFINER_DEGRADED_MESSAGE,
    PUBLIC_REFINER_NOT_NEEDED_MESSAGE,
    PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE,
    PUBLIC_REFINER_DISABLED_MESSAGE,
)


STREAMING_STAGES = [
    ("structure", "Analyzing document structure..."),
    ("styling", "Designing visual styles..."),
    ("layout", "Computing layout positions..."),
    ("render", "Rendering final diagram..."),
]


@dataclass(frozen=True)
class RefineCompletion:
    """Stable public completion state for the optional refiner stream event."""

    fixes_applied: int
    status: RefineCompleteStatus
    message: str

    def public_payload(self) -> dict[str, Any]:
        return refine_complete_payload(
            fixes_applied=self.fixes_applied,
            status=self.status,
            message=self.message,
        )


def format_workflow_sse(event: str, payload: Mapping[str, Any]) -> str:
    return format_sse_event(event, payload)


def stage_start_payload(
    *,
    stage: str,
    stage_index: int,
    total_stages: int,
    message: str,
) -> dict[str, Any]:
    return StageStartPayload(
        stage=stage,
        stage_index=stage_index,
        total_stages=total_stages,
        message=message,
    ).to_public_dict()


def stage_complete_payload(
    *,
    stage: str,
    stage_index: int,
    total_stages: int,
    duration_ms: int,
    message: str | None = None,
) -> dict[str, Any]:
    return StageCompletePayload(
        stage=stage,
        stage_index=stage_index,
        total_stages=total_stages,
        message=message or f"{stage.capitalize()} complete",
        duration_ms=duration_ms,
    ).to_public_dict()


def refine_complete_payload(
    *,
    fixes_applied: int,
    status: RefineCompleteStatus,
    message: str,
) -> dict[str, Any]:
    if status not in REFINE_COMPLETE_STATUSES:
        raise ValueError(f"Unknown refiner completion status: {status}")
    return RefineCompletePayload(
        fixes_applied=fixes_applied,
        status=status,
        message=message,
    ).to_public_dict()


def refine_completed_completion(fixes_applied: int) -> RefineCompletion:
    return RefineCompletion(
        fixes_applied=fixes_applied,
        status="completed",
        message=f"Auto-fixed {fixes_applied} visual issue(s)",
    )


def refine_unresolved_completion(
    *,
    fixes_applied: int,
    termination_reason: str | None,
) -> RefineCompletion:
    reason = termination_reason or "not_converged"
    return RefineCompletion(
        fixes_applied=fixes_applied,
        status="unresolved",
        message=(
            "Refiner did not converge "
            f"({reason}); keeping the base diagram."
        ),
    )


def refine_failed_completion() -> RefineCompletion:
    return RefineCompletion(
        fixes_applied=0,
        status="failed",
        message=PUBLIC_REFINER_DEGRADED_MESSAGE,
    )


def refine_skipped_completion(
    message: str = PUBLIC_REFINER_NOT_NEEDED_MESSAGE,
) -> RefineCompletion:
    return RefineCompletion(
        fixes_applied=0,
        status="skipped",
        message=message,
    )


def refine_unsupported_canvas_completion() -> RefineCompletion:
    return refine_skipped_completion(PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE)


def refiner_skipped_payload() -> dict[str, str]:
    return RefinerSkippedPayload(message=PUBLIC_REFINER_DISABLED_MESSAGE).to_public_dict()


__all__ = [
    "STREAMING_STAGES",
    "RefineCompletion",
    "format_workflow_sse",
    "refine_complete_payload",
    "refine_completed_completion",
    "refine_failed_completion",
    "refine_skipped_completion",
    "refine_unresolved_completion",
    "refine_unsupported_canvas_completion",
    "refiner_skipped_payload",
    "stage_complete_payload",
    "stage_start_payload",
]
