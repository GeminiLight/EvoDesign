"""Streaming generation stage helpers for backend workflow runs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from app.services.workflow_runtime.artifacts import (
    _final_verification_output_dir,
    _layout_instantiation_path,
    _render_output_dir,
    _structure_instantiation_path,
    _to_plain,
    _verification_output_dir,
)


@dataclass
class _StreamingArtifacts:
    structure_state: Any = None
    styling_state: Any = None
    structure_instantiation: Any = None
    structure_specification: Any = None
    styling_instantiation: Any = None
    styling_specification: Any = None
    layout_instantiation: Any = None
    layout_specification: Any = None
    render_result: Any = None
    diagram_manifest: dict[str, Any] | None = None
    refined_diagram_manifest: dict[str, Any] | None = None


@dataclass(frozen=True)
class _VerificationResult:
    verification_dir: str
    verifier_state: Any


def _build_runtime_directives(
    locked_nodes: list[str],
    current_schema: dict[str, Any] | None,
) -> str:
    """Build runtime directives for the agentic pipeline."""
    runtime_context = {
        "locked_nodes": locked_nodes,
        "current_schema": current_schema,
    }
    payload = json.dumps(runtime_context, ensure_ascii=False)
    return f"=== RUNTIME DIRECTIVES (HIGHEST PRIORITY) ===\n{payload}\n\n"


def _sync_generation_artifacts(
    artifacts: _StreamingArtifacts,
    pipeline_run: Any,
) -> None:
    artifacts.structure_state = getattr(pipeline_run, "structure_state", None)
    artifacts.styling_state = getattr(pipeline_run, "styling_state", None)
    artifacts.structure_instantiation = getattr(
        pipeline_run,
        "structure_instantiation",
        None,
    )
    artifacts.structure_specification = getattr(
        pipeline_run,
        "structure_specification",
        None,
    )
    artifacts.styling_instantiation = getattr(
        pipeline_run,
        "styling_instantiation",
        None,
    )
    artifacts.styling_specification = getattr(
        pipeline_run,
        "styling_specification",
        None,
    )
    artifacts.layout_instantiation = getattr(pipeline_run, "layout_instantiation", None)
    artifacts.layout_specification = getattr(pipeline_run, "layout_specification", None)


async def _run_generation_stage(
    *,
    workflow: Any,
    pipeline_run: Any,
    stage_name: str,
    save_dir: str,
    artifacts: _StreamingArtifacts,
    thread_runner: Any = asyncio.to_thread,
) -> None:
    await thread_runner(
        workflow.run_generation_stage,
        pipeline_run,
        stage_name,
        save_dir=save_dir,
    )
    _sync_generation_artifacts(artifacts, pipeline_run)


async def _run_render_stage(
    *,
    render_manifest: Any,
    request: Any,
    save_dir: str,
    artifacts: _StreamingArtifacts,
    thread_runner: Any = asyncio.to_thread,
) -> None:
    artifacts.render_result = await thread_runner(
        render_manifest,
        layout_instantiation=artifacts.layout_instantiation,
        structure_instantiation=artifacts.structure_instantiation,
        canvas_library=request.canvas_library,
        output_dir=_render_output_dir(save_dir),
    )
    artifacts.diagram_manifest = _to_plain(artifacts.render_result.manifest) or {}


async def _run_verification(
    *,
    verifier_workflow_cls: Any,
    workflow: Any,
    request: Any,
    save_dir: str,
    artifacts: _StreamingArtifacts,
    verification_dir: str | None = None,
    manifest_path: str | None = None,
    image_path: str | None = None,
    thread_runner: Any = asyncio.to_thread,
) -> _VerificationResult:
    verification_dir = verification_dir or _verification_output_dir(save_dir)
    verifier = verifier_workflow_cls()
    verifier_state = await thread_runner(
        verifier.run,
        manifest_path=manifest_path or artifacts.render_result.manifest_path,
        image_path=image_path or artifacts.render_result.png_path,
        source_text=request.context,
        design_constraints=getattr(workflow, "design_constraints", ""),
        canvas_library=request.canvas_library,
        structure_path=_structure_instantiation_path(save_dir),
        layout_path=_layout_instantiation_path(save_dir),
        output_dir=verification_dir,
        skip_critic=not workflow.enable_critic,
        emit_markdown=True,
    )
    return _VerificationResult(
        verification_dir=verification_dir,
        verifier_state=verifier_state,
    )


def _verification_should_run(workflow: Any) -> bool:
    """Mirror Text2DiagramWorkflow's default verifier-on behavior."""
    return bool(getattr(workflow, "enable_verifier", True))


async def _run_stream_verification(
    *,
    verifier_workflow_cls: Any,
    workflow: Any,
    request: Any,
    save_dir: str,
    artifacts: _StreamingArtifacts,
    thread_runner: Any = asyncio.to_thread,
) -> _VerificationResult | None:
    if not _verification_should_run(workflow):
        return None
    return await _run_verification(
        verifier_workflow_cls=verifier_workflow_cls,
        workflow=workflow,
        request=request,
        save_dir=save_dir,
        artifacts=artifacts,
        thread_runner=thread_runner,
    )


async def _run_final_stream_verification(
    *,
    verifier_workflow_cls: Any,
    workflow: Any,
    request: Any,
    save_dir: str,
    artifacts: _StreamingArtifacts,
    manifest_path: str,
    image_path: str,
    thread_runner: Any = asyncio.to_thread,
) -> _VerificationResult | None:
    if not _verification_should_run(workflow):
        return None
    return await _run_verification(
        verifier_workflow_cls=verifier_workflow_cls,
        workflow=workflow,
        request=request,
        save_dir=save_dir,
        artifacts=artifacts,
        verification_dir=_final_verification_output_dir(save_dir),
        manifest_path=manifest_path,
        image_path=image_path,
        thread_runner=thread_runner,
    )


def _verification_quality_passed(verifier_state: Any) -> bool:
    quality_passed = getattr(verifier_state, "quality_passed", None)
    if isinstance(quality_passed, bool):
        return quality_passed

    has_blocking_errors = getattr(verifier_state, "has_blocking_errors", None)
    if bool(has_blocking_errors):
        return False

    blocking_errors = getattr(verifier_state, "blocking_errors", None)
    if isinstance(blocking_errors, str):
        if blocking_errors:
            return False
    elif blocking_errors:
        return False

    # Older report-like objects may only expose has_errors. Keep those
    # conservative unless they also expose explicit non-blocking semantics.
    if (
        bool(getattr(verifier_state, "has_errors", False))
        and has_blocking_errors is None
        and blocking_errors is None
    ):
        return False
    if bool(getattr(verifier_state, "has_blocking_findings", False)):
        return False

    summary = getattr(verifier_state, "objective_summary", None) or {}
    if int(summary.get("critical", 0) or 0) > 0:
        return False
    if int(summary.get("major", 0) or 0) > 0:
        return False

    for finding in getattr(verifier_state, "objective_findings", None) or []:
        severity = getattr(finding, "severity", finding)
        name = getattr(severity, "name", None)
        value = getattr(severity, "value", severity)
        labels = {str(value).lower(), str(name).lower() if name else ""}
        if labels & {"critical", "major"}:
            return False

    return True
