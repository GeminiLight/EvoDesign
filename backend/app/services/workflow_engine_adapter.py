"""Backend adapter for the EvoDiagram workflow engine port."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

from loguru import logger

from app.services.workflow_runtime.quality import (
    build_design_constraints, quality_summary, quality_status, refinement_rejection,
)

from app.services.diagram_schema_inspection import (
    CONNECTOR_COLLECTION_KEYS,
    NODE_COLLECTION_KEYS,
    count_schema_collection,
)
from app.services.workflow_engine_port import (
    EvoDiagramWorkflowEnginePort,
    StreamingEngineDependencies,
    WorkflowEnginePort,
)
from app.services.workflow_runtime.artifacts import (
    _cleanup_stream_dir,
    _request_scoped_stream_dir,
    _to_plain,
    _save_json,
)
from app.services.workflow_runtime.errors import (
    PUBLIC_REFINER_COMPLETE_MESSAGE,
    PUBLIC_REFINER_DEGRADED_MESSAGE,
    PUBLIC_REFINER_ERROR_DETAIL,
    PUBLIC_REFINER_ERROR_MESSAGE,
    PUBLIC_REFINER_NOT_NEEDED_MESSAGE,
    PUBLIC_REFINER_START_MESSAGE,
    PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE,
    PUBLIC_REFINER_DISABLED_MESSAGE,
    PUBLIC_STAGE_ERROR_DETAIL,
    PUBLIC_STAGE_ERROR_MESSAGE,
    REFINER_FAILURE_ARTIFACT,
    REFINER_FAILURE_EXECUTION,
    REFINER_FAILURE_VERIFICATION,
    REFINER_STAGE_INDEX,
    REFINER_TOTAL_STAGES,
    RefinerArtifactError,
    RefinerExecutionStatusError,
    RefinerFailure,
    RefinerPipelineError,
    WorkflowStageFailure,
    _refine_error_payload,
    _refiner_failure,
    _stage_failure,
    _wrap_refiner_error,
)
from app.services.workflow_runtime.event_payloads import StreamResultPayload
from app.services.workflow_runtime.events import (
    STREAMING_STAGES,
    format_workflow_sse,
    refine_completed_completion,
    refine_failed_completion,
    refine_skipped_completion,
    refine_unresolved_completion,
    refine_unsupported_canvas_completion,
    refiner_skipped_payload,
    stage_complete_payload,
    stage_start_payload,
)
from app.services.workflow_runtime.stage_execution import (
    StageRunResult,
    run_streaming_stage as _run_runtime_streaming_stage,
)
from app.services.workflow_runtime.stream_pipeline import (
    _StreamingArtifacts,
    _VerificationResult,
    _build_runtime_directives,
    _run_generation_stage,
    _run_final_stream_verification,
    _run_render_stage,
    _run_stream_verification,
    _run_verification,
    _verification_quality_passed,
    _verification_should_run,
)
from app.services.workflow_runtime.refiner import (
    _RefinerRunResult,
    _is_refiner_canvas_supported,
    _load_refined_manifest,
    _run_iterative_refiner,
    _prepare_iterative_refiner,
    _should_run_refiner,
)


@dataclass(frozen=True)
class WorkflowRunRequest:
    """Input contract for an EvoDiagram generation run."""

    context: str
    requirements: str | None
    locked_nodes: list[str]
    current_schema: dict[str, Any] | None
    canvas_library: str
    user_tier: str | None
    request_id: str
    # Caller-provided design expertise (e.g. the user's DNA rules formatted
    # by app.services.dna_design_expertise). It is handed to the engine as
    # the first build_design_expertise argument, the highest-priority slot.
    design_expertise: str = ""
    enable_refiner: bool = True
    refiner_max_iterations: int = 2
    enable_design_memory: bool = False
    design_memory_path: str = ""
    design_memory_seed_path: str = ""
    design_memory_model: str = "Qwen/Qwen3-Embedding-0.6B"
    design_memory_top_k: int = 2
    learn_design_memory: bool = False
    retain_artifacts: bool = False
    use_icons: bool = False
    diagram_type: str | None = None


@dataclass(frozen=True)
class _WorkflowExecutionContext:
    """Derived execution settings shared by sync and streaming runs."""

    refiner_requested: bool
    refiner_max_iterations: int
    runtime_directives: str
    user_query: str


WorkflowClassLoader = Callable[[], Any]
StreamingDependencyLoader = Callable[[], StreamingEngineDependencies]

_DEFAULT_ENGINE_PORT = EvoDiagramWorkflowEnginePort()


def _load_text_workflow_cls() -> Any:
    """Load the engine workflow class behind the backend import boundary."""
    return _DEFAULT_ENGINE_PORT.load_text_workflow_cls()


def _load_streaming_engine_dependencies() -> StreamingEngineDependencies:
    """Load engine internals required for streaming generation."""
    return _DEFAULT_ENGINE_PORT.load_streaming_dependencies()


async def _run_adapter_streaming_stage(
    *,
    request_id: str,
    stage: str,
    handler: Callable[[], Awaitable[None]],
    stage_logger: Any = None,
) -> StageRunResult:
    """Run one streaming stage using the adapter logger import surface."""
    return await _run_runtime_streaming_stage(
        request_id=request_id,
        stage=stage,
        handler=handler,
        stage_logger=stage_logger or logger,
    )


def _build_workflow_result(
    request_id: str,
    schema_blob: Any,
    structure_instantiation: Any,
    styling_instantiation: Any,
    layout_instantiation: Any,
    summary: str,
    generation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema_blob = _to_plain(schema_blob) or {}
    thought_trace = {
        "structure_instantiation": _to_plain(structure_instantiation) or {},
        "styling_instantiation": _to_plain(styling_instantiation) or {},
        "layout_instantiation": _to_plain(layout_instantiation) or {},
    }
    metrics_scores = {
        "node_count": count_schema_collection(schema_blob, NODE_COLLECTION_KEYS),
        "edge_count": count_schema_collection(schema_blob, CONNECTOR_COLLECTION_KEYS),
    }
    if generation_report is not None:
        metrics_scores["generation"] = generation_report
    return StreamResultPayload(
        request_id=request_id,
        project_id=None,
        snapshot_id=None,
        schema_blob=schema_blob,
        thought_trace=thought_trace,
        metrics_scores=metrics_scores,
        summary=summary,
    ).to_public_dict()


def _build_workflow_execution_context(
    request: WorkflowRunRequest,
) -> _WorkflowExecutionContext:
    """Build the shared per-run context derived from backend request fields."""
    refiner_requested = request.enable_refiner
    refiner_max_iterations = max(1, min(3, request.refiner_max_iterations))
    runtime_directives = _build_runtime_directives(
        request.locked_nodes,
        request.current_schema,
    )
    user_query = request.requirements or "Generate diagram schema"
    return _WorkflowExecutionContext(
        refiner_requested=refiner_requested,
        refiner_max_iterations=refiner_max_iterations,
        runtime_directives=runtime_directives,
        user_query=user_query,
    )


def _design_memory_options(request: WorkflowRunRequest) -> dict[str, Any]:
    if not request.enable_design_memory:
        return {}
    return {
        "enable_design_memory": True,
        "design_memory_db_path": request.design_memory_path,
        "design_memory_embedding_model": request.design_memory_model,
        "design_memory_top_k": request.design_memory_top_k,
    }


class WorkflowEngineAdapter:
    """Adapter that owns direct calls into EvoDiagram engine internals."""

    def __init__(
        self,
        results_dir: str,
        *,
        engine_port: WorkflowEnginePort | None = None,
        workflow_cls_loader: WorkflowClassLoader | None = None,
        streaming_dependency_loader: StreamingDependencyLoader | None = None,
    ):
        self.results_dir = results_dir
        engine_port = engine_port or _DEFAULT_ENGINE_PORT
        self.workflow_cls_loader = (
            workflow_cls_loader or engine_port.load_text_workflow_cls
        )
        self.streaming_dependency_loader = (
            streaming_dependency_loader or engine_port.load_streaming_dependencies
        )

    async def stream_without_render(
        self,
        *,
        model: Any,
        request: WorkflowRunRequest,
    ) -> AsyncGenerator[str, None]:
        """Stream SSE events for each EvoDiagram workflow stage."""
        started = time.monotonic()
        engine = await asyncio.to_thread(self.streaming_dependency_loader)

        run_context = _build_workflow_execution_context(request)
        refiner_supported = _is_refiner_canvas_supported(request.canvas_library)
        enable_refiner = run_context.refiner_requested and refiner_supported
        save_dir = _request_scoped_stream_dir(self.results_dir, request.request_id)
        timings: dict[str, int] = {}
        memory_report: dict[str, Any] = {"status": "disabled", "retrieved_count": 0, "retrieved_items": []}
        refinement_report: dict[str, Any] = {"status": "skipped", "fixes_applied": 0}
        learning_report: dict[str, Any] = {"status": "skipped", "saved_count": 0}
        before_quality: dict[str, Any] = {}
        after_quality: dict[str, Any] = {}
        total_stages = 9
        preparation_task = None
        optimizations: dict[str, Any] = {}
        try:
            yield format_workflow_sse("stage_start", stage_start_payload(
                stage="memory", stage_index=1, total_stages=total_stages,
                message="Preparing design knowledge...",
            ))
            if request.enable_design_memory and engine.prepare_design_memory is not None:
                try:
                    await asyncio.to_thread(engine.prepare_design_memory,
                        request.design_memory_path, request.design_memory_model,
                        request.design_memory_seed_path)
                except Exception:
                    logger.exception("Design memory preparation unavailable")
                    memory_report["status"] = "unavailable"
            # Workflow construction and the first pipeline calls reach into engine
            # agents and the router LLM, so they run off the event loop like the
            # later stages do.
            workflow = await asyncio.to_thread(
                engine.workflow_cls,
                model=model,
                save_dir=save_dir,
                enable_refiner=enable_refiner,
                refiner_max_iterations=run_context.refiner_max_iterations,
                canvas_library=request.canvas_library,
                use_icons=request.use_icons,
                router_model=model,
                **_design_memory_options(request),
            )
            if not all(
                hasattr(workflow, attr)
                for attr in ("begin_generation_run", "run_generation_stage")
            ):
                yield format_workflow_sse(
                    "error",
                    {
                        "stage": "init",
                        "message": "UnsupportedWorkflowMode",
                        "detail": "Streaming generation currently supports pipeline mode only.",
                    },
                )
                return

            stages = STREAMING_STAGES
            verification_enabled = _verification_should_run(workflow)

            artifacts = _StreamingArtifacts()
            workflow.design_constraints = build_design_constraints(
                source_text=request.context, requirements=run_context.user_query,
                design_expertise=request.design_expertise, diagram_type=request.diagram_type,
                use_icons=request.use_icons, locked_nodes=request.locked_nodes,
            )
            pipeline_run = await asyncio.to_thread(
                workflow.begin_generation_run, request.context, run_context.user_query,
                design_expertise=request.design_expertise,
                runtime_directives=run_context.runtime_directives,
                **({"diagram_type": request.diagram_type} if request.diagram_type else {}),
            )
            routing_finished = time.monotonic()
            full_design_expertise = await asyncio.to_thread(
                workflow.build_design_expertise, request.design_expertise,
                getattr(pipeline_run, "effective_diagram_type", None), None,
                user_query=run_context.user_query, retrieval_query=request.context,
            )
            optimizations["memory_retrieval_ms"] = int((time.monotonic() - routing_finished) * 1000)
            optimizations["initialization_and_routing_ms"] = int((routing_finished - started) * 1000)
            optimizations["router_skipped"] = bool(request.diagram_type)
            pipeline_run.design_expertise = full_design_expertise
            items = getattr(workflow, "design_memory_retrieved_items", []) or []
            if request.enable_design_memory:
                memory_report.update(
                    status=("unavailable" if getattr(workflow, "design_memory_degraded", False)
                            or memory_report["status"] == "unavailable"
                            else "used" if items else "empty"),
                    retrieved_count=len(items), retrieved_items=items,
                )
            timings["memory"] = int((time.monotonic() - started) * 1000)
            yield format_workflow_sse("stage_complete", stage_complete_payload(
                stage="memory", stage_index=1, total_stages=total_stages,
                duration_ms=timings["memory"],
                message=f"Design knowledge: {len(items)} references loaded",
            ))
            stage_handlers = {
                stage_name: (
                    lambda stage_name=stage_name: _run_generation_stage(
                        workflow=workflow,
                        pipeline_run=pipeline_run,
                        stage_name=stage_name,
                        save_dir=save_dir,
                        artifacts=artifacts,
                        thread_runner=asyncio.to_thread,
                    )
                )
                for stage_name in ("structure", "styling", "layout")
            }
            stage_handlers["render"] = lambda: _run_render_stage(
                render_manifest=engine.render_manifest,
                request=request,
                save_dir=save_dir,
                artifacts=artifacts,
                thread_runner=asyncio.to_thread,
            )

            for stage_index, (stage_name, stage_message) in enumerate(stages, start=2):
                yield format_workflow_sse(
                    "stage_start",
                    stage_start_payload(
                        stage=stage_name,
                        stage_index=stage_index,
                        total_stages=total_stages,
                        message=stage_message,
                    ),
                )

                stage_result = await _run_adapter_streaming_stage(
                    request_id=request.request_id,
                    stage=stage_name,
                    handler=stage_handlers[stage_name],
                )
                if stage_result.failure is not None:
                    yield format_workflow_sse("error", stage_result.failure.public_payload())
                    return

                timings[stage_name] = stage_result.duration_ms
                yield format_workflow_sse(
                    "stage_complete",
                    stage_complete_payload(
                        stage=stage_name,
                        stage_index=stage_index,
                        total_stages=total_stages,
                        duration_ms=stage_result.duration_ms,
                    ),
                )

            verification: _VerificationResult | None = None
            verification_started = time.monotonic()
            if (enable_refiner and verification_enabled and workflow.enable_critic
                    and callable(getattr(engine.iterative_refiner_workflow_cls, "prepare", None))):
                preparation_task = asyncio.create_task(_prepare_iterative_refiner(
                    iterative_refiner_workflow_cls=engine.iterative_refiner_workflow_cls,
                    request=request, save_dir=save_dir,
                    refiner_max_iterations=run_context.refiner_max_iterations,
                    artifacts=artifacts,
                    design_constraints=workflow.design_constraints,
                ))
            if verification_enabled:
                yield format_workflow_sse(
                    "stage_start",
                    stage_start_payload(
                        stage="verification",
                        stage_index=len(stages) + 2,
                        total_stages=total_stages,
                        message="Checking diagram quality...",
                    ),
                )
            try:
                verification = await _run_stream_verification(
                    verifier_workflow_cls=engine.verifier_workflow_cls,
                    workflow=workflow,
                    request=request,
                    save_dir=save_dir,
                    artifacts=artifacts,
                    thread_runner=asyncio.to_thread,
                )
            except Exception as verification_exc:
                failure = _stage_failure(
                    request_id=request.request_id,
                    stage="verification",
                    exc=verification_exc,
                )
                logger.bind(**failure.log_context()).opt(exception=verification_exc).error(
                    "Streaming verification failed"
                )
                yield format_workflow_sse("error", failure.public_payload())
                return

            if verification_enabled:
                before_quality = quality_summary(verification.verifier_state)
                after_quality = before_quality
                timings["verification"] = int((time.monotonic() - verification_started) * 1000)
                yield format_workflow_sse(
                    "stage_complete",
                    stage_complete_payload(
                        stage="verification",
                        stage_index=len(stages) + 2,
                        total_stages=total_stages,
                        duration_ms=int((time.monotonic() - verification_started) * 1000),
                    ),
                )

            if enable_refiner:
                refine_completion = refine_completed_completion(fixes_applied=0)
                should_refine = False
                try:
                    if verification is None:
                        raise RefinerPipelineError(
                            phase=REFINER_FAILURE_VERIFICATION,
                            reason="Refiner verification did not produce a report",
                        )
                    should_refine = _should_run_refiner(
                        workflow=workflow,
                        verifier_state=verification.verifier_state,
                        severity_cls=engine.severity_cls,
                        canvas_library=request.canvas_library,
                    )

                    if should_refine:
                        yield format_workflow_sse(
                            "stage_start",
                            stage_start_payload(
                                stage="refining",
                                stage_index=REFINER_STAGE_INDEX,
                                total_stages=REFINER_TOTAL_STAGES,
                                message=PUBLIC_REFINER_START_MESSAGE,
                            ),
                        )

                        t0 = time.monotonic()
                        final_check_started = None
                        preparation = await asyncio.shield(preparation_task) if preparation_task is not None else None
                        if preparation is not None:
                            optimizations["parallel_preparation_ms"] = preparation.duration_ms
                        refiner_result = await _run_iterative_refiner(
                            iterative_refiner_workflow_cls=(
                                engine.iterative_refiner_workflow_cls
                            ),
                            request=request,
                            save_dir=save_dir,
                            verification_dir=verification.verification_dir,
                            refiner_max_iterations=run_context.refiner_max_iterations,
                            artifacts=artifacts,
                            preparation=preparation,
                            design_constraints=workflow.design_constraints,
                            thread_runner=asyncio.to_thread,
                        )
                        timings["refining"] = int((time.monotonic() - t0) * 1000)
                        yield format_workflow_sse("stage_complete", stage_complete_payload(
                            stage="refining", stage_index=REFINER_STAGE_INDEX,
                            total_stages=total_stages, duration_ms=timings["refining"],
                            message=PUBLIC_REFINER_COMPLETE_MESSAGE,
                        ))
                        if (
                            refiner_result.converged
                            and refiner_result.refined_manifest is not None
                        ):
                            if (
                                refiner_result.refined_manifest_path is None
                                or refiner_result.refined_image_path is None
                            ):
                                raise RefinerPipelineError(
                                    phase=REFINER_FAILURE_ARTIFACT,
                                    reason="Refiner produced an incomplete final artifact",
                                )
                            yield format_workflow_sse("stage_start", stage_start_payload(
                                stage="final_verification", stage_index=8, total_stages=total_stages,
                                message="Checking the refined diagram...",
                            ))
                            final_check_started = time.monotonic()
                            try:
                                final_verification = await _run_final_stream_verification(
                                    verifier_workflow_cls=engine.verifier_workflow_cls,
                                    workflow=workflow,
                                    request=request,
                                    save_dir=save_dir,
                                    artifacts=artifacts,
                                    manifest_path=refiner_result.refined_manifest_path,
                                    image_path=refiner_result.refined_image_path,
                                    thread_runner=asyncio.to_thread,
                                )
                            except Exception as final_verification_exc:
                                raise _wrap_refiner_error(
                                    phase=REFINER_FAILURE_VERIFICATION,
                                    reason="Refined artifact final verification failed",
                                    exc=final_verification_exc,
                                ) from final_verification_exc
                            if (
                                final_verification is not None
                                and not _verification_quality_passed(
                                    final_verification.verifier_state
                                )
                            ):
                                raise RefinerPipelineError(
                                    phase=REFINER_FAILURE_VERIFICATION,
                                    reason="Refined artifact failed final verification",
                                )
                            candidate_quality = quality_summary(final_verification.verifier_state)
                            if refinement_rejection(verification.verifier_state, final_verification.verifier_state):
                                raise RefinerPipelineError(
                                    phase=REFINER_FAILURE_VERIFICATION,
                                    reason="Refined artifact quality regressed",
                                )
                            after_quality = candidate_quality
                            timings["final_verification"] = int((time.monotonic() - final_check_started) * 1000)
                            yield format_workflow_sse("stage_complete", stage_complete_payload(
                                stage="final_verification", stage_index=8, total_stages=total_stages,
                                duration_ms=timings["final_verification"],
                            ))
                        refine_completion = (
                            refine_unresolved_completion(
                                fixes_applied=refiner_result.fixes_applied,
                                termination_reason=refiner_result.termination_reason,
                            )
                            if not refiner_result.converged
                            else refine_completed_completion(
                                fixes_applied=refiner_result.fixes_applied
                            )
                        )
                        artifacts.refined_diagram_manifest = refiner_result.refined_manifest

                    else:
                        refine_completion = refine_skipped_completion()
                        artifacts.refined_diagram_manifest = None
                except RefinerPipelineError as refine_exc:
                    if should_refine:
                        if final_check_started is not None:
                            timings["final_verification"] = int((time.monotonic() - final_check_started) * 1000)
                        else:
                            timings["refining"] = int((time.monotonic() - t0) * 1000)
                    refine_completion = refine_failed_completion()
                    failure = _refiner_failure(
                        request_id=request.request_id,
                        exc=refine_exc,
                    )
                    logger.bind(**failure.log_context()).opt(
                        exception=refine_exc
                    ).warning(
                        "Refiner failed; degrading to base diagram"
                    )
                    yield format_workflow_sse("refine_error", failure.public_payload())

                refinement_report = refine_completion.public_payload()
                if refine_completion.status != "completed":
                    refinement_report["fixes_applied"] = 0
                yield format_workflow_sse(
                    "refine_complete",
                    refinement_report,
                )

            if run_context.refiner_requested and not refiner_supported:
                refinement_report["status"] = "unsupported"
                yield format_workflow_sse(
                    "refine_complete",
                    refine_unsupported_canvas_completion().public_payload(),
                )

            if not run_context.refiner_requested:
                refinement_report["status"] = "disabled"
                yield format_workflow_sse("refiner_skipped", refiner_skipped_payload())

            if (request.learn_design_memory and artifacts.refined_diagram_manifest
                    and engine.learn_design_memory is not None
                    and getattr(workflow, "design_memory_retriever", None) is not None):
                try:
                    from app.services.design_learning_jobs import enqueue_learning
                    learning_report = enqueue_learning(
                        memory_path=request.design_memory_path,
                        embedding_model=request.design_memory_model,
                        report_path=f"{save_dir}/7_refiner/refiner_report.json",
                        request_id=request.request_id,
                        diagram_type=(artifacts.structure_instantiation or {}).get("chart_type", "general"),
                        before=before_quality, after=after_quality, model=model,
                        retriever=workflow.design_memory_retriever, learner=engine.learn_design_memory,
                    )
                except Exception:
                    logger.exception("Could not queue design learning; keeping verified diagram")
                    learning_report = {"status": "unavailable", "saved_count": 0}
            report = {"quality_status": quality_status(after_quality), "memory": memory_report, "refinement": refinement_report,
                      "learning": learning_report, "before": before_quality, "after": after_quality,
                      "timings_ms": timings, "optimizations": optimizations,
                      "total_duration_ms": int((time.monotonic() - started) * 1000)}
            result = _build_workflow_result(
                request_id=request.request_id,
                schema_blob=artifacts.refined_diagram_manifest
                or artifacts.diagram_manifest
                or {},
                structure_instantiation=artifacts.structure_instantiation,
                styling_instantiation=artifacts.styling_instantiation,
                layout_instantiation=artifacts.layout_instantiation,
                summary=" ".join(request.context.split())[:80] or "Generated diagram",
                generation_report=report,
            )

            if request.retain_artifacts:
                _save_json(f"{save_dir}/generation_result.json", result)
            yield format_workflow_sse("result", result)
        finally:
            # to_thread work cannot be stopped by cancelling its awaiter. Join
            # it before deleting the request directory, including on disconnect.
            if preparation_task is not None:
                await asyncio.shield(preparation_task)
            if not request.retain_artifacts:
                _cleanup_stream_dir(save_dir)

    def run_without_render_sync(
        self,
        *,
        model: Any,
        request: WorkflowRunRequest,
    ) -> dict[str, Any]:
        """Run the EvoDiagram workflow without serving rendered assets."""
        workflow_cls = self.workflow_cls_loader()

        run_context = _build_workflow_execution_context(request)
        refiner_supported = _is_refiner_canvas_supported(request.canvas_library)
        enable_refiner = run_context.refiner_requested and refiner_supported

        if request.enable_design_memory:
            deps = self.streaming_dependency_loader()
            if deps.prepare_design_memory is not None:
                try:
                    deps.prepare_design_memory(request.design_memory_path, request.design_memory_model, request.design_memory_seed_path)
                except Exception:
                    logger.exception("Design memory preparation unavailable")
        workflow = workflow_cls(
            model=model,
            save_dir=self.results_dir,
            enable_refiner=enable_refiner,
            refiner_max_iterations=run_context.refiner_max_iterations,
            canvas_library=request.canvas_library,
            use_icons=request.use_icons,
            router_model=model,
            **_design_memory_options(request),
        )

        state = workflow.run(
            text_content=request.context,
            user_query=run_context.user_query,
            runtime_directives=run_context.runtime_directives,
            save_dir=None,
            design_expertise=request.design_expertise,
            **({"diagram_type": request.diagram_type} if request.diagram_type else {}),
        )

        schema_blob = (
            _to_plain(
                getattr(state, "final_diagram_manifest", None)
                or state.refined_diagram_manifest
                or state.diagram_manifest
            )
            or {}
        )
        structure_instantiation = _to_plain(getattr(state, "structure_instantiation", None)) or {}
        styling_instantiation = _to_plain(getattr(state, "styling_instantiation", None)) or {}
        layout_instantiation = _to_plain(getattr(state, "layout_instantiation", None)) or {}

        return _build_workflow_result(
            request_id=request.request_id,
            schema_blob=schema_blob,
            structure_instantiation=structure_instantiation,
            styling_instantiation=styling_instantiation,
            layout_instantiation=layout_instantiation,
            summary=" ".join(request.context.split())[:80] or "Generated diagram",
        )
