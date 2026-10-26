"""Refiner runtime helpers for backend workflow streaming."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.core.canvas import canvas_library_supports_refiner
from app.services.workflow_runtime.artifacts import (
    _layout_instantiation_path,
    _refiner_output_dir,
    _structure_instantiation_path,
    _verifier_report_path,
)
from app.services.workflow_runtime.errors import (
    REFINER_FAILURE_ARTIFACT,
    REFINER_FAILURE_EXECUTION,
    RefinerArtifactError,
    RefinerExecutionStatusError,
    _wrap_refiner_error,
)


@dataclass(frozen=True)
class _RefinerRunResult:
    fixes_applied: int
    refined_manifest: dict[str, Any] | None
    refined_manifest_path: str | None
    refined_image_path: str | None
    converged: bool
    termination_reason: str | None


@dataclass(frozen=True)
class _RefinerPreparation:
    workflow: Any
    state: Any
    duration_ms: int


def _count_surviving_fixes(iteration_logs: Any) -> int:
    total = 0
    for log in iteration_logs:
        if getattr(log, "rolled_back", False):
            continue
        applied = sum(outcome.applied for outcome in [*log.deterministic_edits, *log.llm_edits])
        # A sequence can be repaired by rebuilding chronology alone. Report
        # those real changes even when no primitive EditOp was necessary;
        # avoid counting connectors again after a normal node edit.
        derived = {item.get("arrow_id") for item in getattr(log, "rerouted_arrows", [])
                   if item.get("arrow_id")}
        total += applied or len(derived)
    return total


async def _prepare_iterative_refiner(
    *, iterative_refiner_workflow_cls: Any, request: Any, save_dir: str,
    refiner_max_iterations: int, artifacts: Any,
    design_constraints: str = "",
    thread_runner: Any = asyncio.to_thread,
) -> _RefinerPreparation | None:
    """Overlap only deterministic work; the LLM still receives the full critic."""
    started = time.monotonic()
    try:
        refiner = iterative_refiner_workflow_cls()
        state = await thread_runner(
            refiner.prepare,
            manifest_path=artifacts.render_result.manifest_path,
            image_path=artifacts.render_result.png_path,
            structure_path=_structure_instantiation_path(save_dir),
            layout_path=_layout_instantiation_path(save_dir),
            output_dir=_refiner_output_dir(save_dir),
            canvas_library=request.canvas_library,
            max_iterations=refiner_max_iterations,
            emit_markdown=True,
            design_constraints=design_constraints,
        )
        if getattr(state, "status", None) == "failed":
            return None
        return _RefinerPreparation(refiner, state, int((time.monotonic() - started) * 1000))
    except Exception:
        logger.exception("Parallel refiner preparation unavailable; using serial refinement")
        return None


def _is_refiner_canvas_supported(canvas_library: str) -> bool:
    return canvas_library_supports_refiner(canvas_library)


def _has_blocking_verification_errors(verifier_state: Any) -> bool:
    """Return whether verifier failures make refinement unsafe to run."""
    has_blocking_errors = getattr(verifier_state, "has_blocking_errors", None)
    if has_blocking_errors is True:
        return True
    if has_blocking_errors is False:
        return False

    blocking_errors = getattr(verifier_state, "blocking_errors", None)
    if isinstance(blocking_errors, (list, tuple)):
        return bool(blocking_errors)
    if isinstance(blocking_errors, str):
        return bool(blocking_errors)

    return getattr(verifier_state, "has_errors", False) is True


def _should_run_refiner(
    *,
    workflow: Any,
    verifier_state: Any,
    severity_cls: Any,
    canvas_library: str,
) -> bool:
    if not _is_refiner_canvas_supported(canvas_library):
        return False

    if _has_blocking_verification_errors(verifier_state):
        return False

    if getattr(workflow, "always_refine", False):
        return True

    from evo_diagram.agentic_system.quality_policy import should_refine
    return should_refine(verifier_state)



def _load_refined_manifest(refiner_state: Any) -> dict[str, Any] | None:
    refined_manifest_path = getattr(refiner_state, "refined_manifest_path", None)
    refined_image_path = getattr(refiner_state, "refined_image_path", None)

    if refined_manifest_path and refined_image_path:
        try:
            with open(refined_manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise _wrap_refiner_error(
                phase=REFINER_FAILURE_ARTIFACT,
                reason="Refiner artifact load failed",
                exc=exc,
            ) from exc

    if refined_manifest_path:
        raise RefinerArtifactError(
            phase=REFINER_FAILURE_ARTIFACT,
            reason="Refiner produced a refined manifest without an image",
        )
    if refined_image_path:
        raise RefinerArtifactError(
            phase=REFINER_FAILURE_ARTIFACT,
            reason="Refiner produced a refined image without a manifest",
        )
    return None


async def _run_iterative_refiner(
    *,
    iterative_refiner_workflow_cls: Any,
    request: Any,
    save_dir: str,
    verification_dir: str,
    refiner_max_iterations: int,
    artifacts: Any,
    preparation: _RefinerPreparation | None = None,
    design_constraints: str = "",
    thread_runner: Any = asyncio.to_thread,
) -> _RefinerRunResult:
    try:
        if preparation is not None:
            refiner_state = await thread_runner(
                preparation.workflow.run_prepared, preparation.state,
                verifier_report_path=_verifier_report_path(verification_dir),
            )
        else:
            refiner = iterative_refiner_workflow_cls()
            refiner_state = await thread_runner(
                refiner.run,
                manifest_path=artifacts.render_result.manifest_path,
                image_path=artifacts.render_result.png_path,
                structure_path=_structure_instantiation_path(save_dir),
                layout_path=_layout_instantiation_path(save_dir),
                verifier_report_path=_verifier_report_path(verification_dir),
                output_dir=_refiner_output_dir(save_dir),
                canvas_library=request.canvas_library,
                max_iterations=refiner_max_iterations,
                emit_markdown=True,
                design_constraints=design_constraints,
            )
        # Iteration logs record every proposal, including deterministic skips
        # and LLM items rejected by EditOp schema validation. Count surviving
        # applied outcomes or standalone derived repairs, never proposals.
        fixes_applied = _count_surviving_fixes(getattr(refiner_state, "iteration_logs", []))
    except Exception as exc:
        raise _wrap_refiner_error(
            phase=REFINER_FAILURE_EXECUTION,
            reason="Refiner execution failed",
            exc=exc,
        ) from exc

    if getattr(refiner_state, "status", None) == "failed":
        raise RefinerExecutionStatusError(
            phase=REFINER_FAILURE_EXECUTION,
            reason="Refiner returned failed status",
        )

    converged = getattr(refiner_state, "converged", None) is True
    termination_reason = getattr(refiner_state, "termination_reason", None)
    if not converged:
        return _RefinerRunResult(
            fixes_applied=fixes_applied,
            refined_manifest=None,
            refined_manifest_path=None,
            refined_image_path=None,
            converged=False,
            termination_reason=(
                str(termination_reason) if termination_reason is not None else None
            ),
        )

    refined_manifest = _load_refined_manifest(refiner_state)
    refined_manifest_path = getattr(refiner_state, "refined_manifest_path", None)
    refined_image_path = getattr(refiner_state, "refined_image_path", None)
    return _RefinerRunResult(
        fixes_applied=fixes_applied,
        refined_manifest=refined_manifest,
        refined_manifest_path=(
            str(refined_manifest_path) if refined_manifest is not None else None
        ),
        refined_image_path=str(refined_image_path) if refined_manifest is not None else None,
        converged=True,
        termination_reason=(
            str(termination_reason) if termination_reason is not None else None
        ),
    )
