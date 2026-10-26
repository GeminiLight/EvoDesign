"""Typed public payloads for backend workflow SSE events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


STREAM_STAGE_VALUES = ("memory", "structure", "styling", "layout", "render", "verification", "refining", "final_verification", "learning")
STREAM_ERROR_STAGE_VALUES = (
    *STREAM_STAGE_VALUES,
    "init",
    "generation",
    "rewrite",
)
REFINE_COMPLETE_STATUSES = ("completed", "skipped", "failed", "unresolved")
STREAM_EVENT_TYPES = (
    "stage_start",
    "stage_complete",
    "refine_complete",
    "refine_error",
    "refiner_skipped",
    "result",
    "error",
)

StreamStage = Literal["memory", "structure", "styling", "layout", "render", "verification", "refining", "final_verification", "learning"]
StreamErrorStage = Literal[
    "memory", "final_verification", "learning",
    "structure",
    "styling",
    "layout",
    "render",
    "refining",
    "init",
    "generation",
    "verification",
    "rewrite",
]
RefineCompleteStatus = Literal["completed", "skipped", "failed", "unresolved"]


class PublicSsePayload(BaseModel):
    """Base model for payloads serialized to the public SSE stream."""

    model_config = ConfigDict(extra="forbid", strict=True)

    def to_public_dict(self) -> dict[str, Any]:
        """Return the stable JSON object emitted as SSE data."""
        return self.model_dump()


class StageStartPayload(PublicSsePayload):
    stage: StreamStage
    stage_index: int
    total_stages: int
    message: str


class StageCompletePayload(StageStartPayload):
    duration_ms: int


class RefineCompletePayload(PublicSsePayload):
    """Refiner outcome reported to the client.

    ``fixes_applied`` counts edits that actually landed on the manifest, not
    edits the refiner proposed: rejected and skipped proposals are excluded.
    """

    fixes_applied: int
    status: RefineCompleteStatus
    message: str


class RefineErrorPayload(PublicSsePayload):
    message: str
    detail: str


class RefinerSkippedPayload(PublicSsePayload):
    message: str


class StreamErrorPayload(PublicSsePayload):
    stage: StreamErrorStage
    message: str
    detail: str


class StreamResultPayload(PublicSsePayload):
    request_id: str
    project_id: str | None
    snapshot_id: str | None
    schema_blob: dict[str, Any]
    thought_trace: dict[str, Any] | None = None
    metrics_scores: dict[str, Any] | None = None
    summary: str
    thumbnail_url: str | None = None
    persist_error: bool | None = None
    persist_error_message: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Return the public result payload without absent persistence fields."""
        payload = self.model_dump()
        for key in ("thumbnail_url", "persist_error", "persist_error_message"):
            if payload[key] is None:
                del payload[key]
        return payload
