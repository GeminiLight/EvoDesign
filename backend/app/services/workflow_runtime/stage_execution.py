"""Stage execution wrapper for backend workflow streaming."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from loguru import logger as default_logger

from app.services.workflow_runtime.errors import WorkflowStageFailure, _stage_failure


@dataclass(frozen=True)
class StageRunResult:
    """Result of executing one streaming workflow stage."""

    duration_ms: int
    failure: WorkflowStageFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None


async def run_streaming_stage(
    *,
    request_id: str,
    stage: str,
    handler: Callable[[], Awaitable[None]],
    stage_logger: Any = default_logger,
) -> StageRunResult:
    """Run one streaming stage and convert engine failures to safe metadata."""
    t0 = time.monotonic()
    try:
        await handler()
    except Exception as stage_exc:
        failure = _stage_failure(
            request_id=request_id,
            stage=stage,
            exc=stage_exc,
        )
        stage_logger.bind(**failure.log_context()).opt(exception=stage_exc).error(
            "Streaming workflow stage failed"
        )
        return StageRunResult(duration_ms=0, failure=failure)

    return StageRunResult(duration_ms=int((time.monotonic() - t0) * 1000))

__all__ = [
    "StageRunResult",
    "run_streaming_stage",
]
