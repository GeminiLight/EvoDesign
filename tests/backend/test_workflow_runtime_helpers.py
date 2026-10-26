from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services import workflow_engine_adapter as adapter
from app.services.diagram_generation_contract import GenerationInputValidationError
from app.services.workflow_runtime.artifacts import (
    FINAL_VERIFICATION_STAGE_DIR,
    LAYOUT_STAGE_DIR,
    REFINER_STAGE_DIR,
    RENDER_STAGE_DIR,
    STRUCTURE_STAGE_DIR,
    STYLING_STAGE_DIR,
    VERIFICATION_STAGE_DIR,
    _final_verification_output_dir,
    _layout_instantiation_path,
    _refiner_output_dir,
    _render_output_dir,
    _request_scoped_stream_dir,
    _stage_artifact_path,
    _structure_instantiation_path,
    _to_plain,
    _verification_output_dir,
    _verifier_report_path,
)
from app.services.workflow_runtime.errors import (
    PUBLIC_REFINER_ERROR_DETAIL,
    PUBLIC_REFINER_ERROR_MESSAGE,
    REFINER_FAILURE_ARTIFACT,
    REFINER_FAILURE_EXECUTION,
    RefinerArtifactError,
    RefinerExecutionStatusError,
    RefinerPipelineError,
    _refine_error_payload,
    _refiner_failure,
    _stage_failure,
)
from app.services.workflow_runtime.event_payloads import (
    REFINE_COMPLETE_STATUSES,
    STREAM_ERROR_STAGE_VALUES,
    STREAM_STAGE_VALUES,
    RefineCompletePayload,
    StageStartPayload,
    StreamErrorPayload,
    StreamResultPayload,
)
from app.services.workflow_runtime import (
    format_workflow_sse,
    refine_completed_completion,
    refine_complete_payload,
    refine_failed_completion,
    refine_skipped_completion,
    refine_unresolved_completion,
    refine_unsupported_canvas_completion,
    refiner_skipped_payload,
    stage_complete_payload,
    stage_start_payload,
)
from app.services.workflow_runtime.stream_errors import (
    GENERATION_STREAM_ERROR_TYPES,
    REWRITE_STREAM_ERROR_TYPES,
    STREAM_GENERATION_ERROR_DETAIL,
    STREAM_INIT_ERROR_DETAIL,
    STREAM_REWRITE_ERROR_DETAIL,
    _format_stream_error_payload,
    _generation_stream_error_payload,
    _rewrite_stream_error_payload,
    _stream_error_payload,
)
from app.services.workflow_runtime.refiner import (
    _is_refiner_canvas_supported,
    _load_refined_manifest,
    _run_iterative_refiner,
    _should_run_refiner,
)
from app.services.workflow_runtime.stage_execution import (
    StageRunResult,
    run_streaming_stage,
)
from app.services.workflow_runtime.stream_pipeline import (
    _StreamingArtifacts,
    _build_runtime_directives,
    _run_final_stream_verification,
    _run_generation_stage,
    _run_render_stage,
    _verification_quality_passed,
    _verification_should_run,
)


ROOT = Path(__file__).resolve().parents[2]


def _edit_outcome(*, applied: bool = True, error: str | None = None):
    """Stand in for an engine EditApplyOutcome row in an iteration log."""
    return SimpleNamespace(edit=None, applied=applied, error=error, raw=None)


def test_workflow_runtime_helpers_preserve_adapter_import_surface():
    """Existing private test imports should continue through the adapter module."""
    assert adapter._stage_failure is _stage_failure
    assert adapter._refine_error_payload is _refine_error_payload
    assert adapter._request_scoped_stream_dir is _request_scoped_stream_dir
    assert adapter._should_run_refiner is _should_run_refiner
    assert adapter._run_iterative_refiner is _run_iterative_refiner
    assert adapter._StreamingArtifacts is _StreamingArtifacts
    assert adapter._build_runtime_directives is _build_runtime_directives
    assert adapter._run_generation_stage is _run_generation_stage
    assert adapter._run_final_stream_verification is _run_final_stream_verification
    assert adapter._verification_quality_passed is _verification_quality_passed
    assert adapter._verification_should_run is _verification_should_run


def test_workflow_runtime_package_exports_public_stage_execution_contract():
    from app.services import workflow_runtime

    assert workflow_runtime.RefineCompletion is not None
    assert workflow_runtime.StageRunResult is StageRunResult
    assert workflow_runtime.format_workflow_sse is format_workflow_sse
    assert workflow_runtime.refine_complete_payload is refine_complete_payload
    assert workflow_runtime.refine_completed_completion is refine_completed_completion
    assert workflow_runtime.refine_failed_completion is refine_failed_completion
    assert workflow_runtime.refine_skipped_completion is refine_skipped_completion
    assert workflow_runtime.refine_unresolved_completion is refine_unresolved_completion
    assert (
        workflow_runtime.refine_unsupported_canvas_completion
        is refine_unsupported_canvas_completion
    )
    assert workflow_runtime.refiner_skipped_payload is refiner_skipped_payload
    assert workflow_runtime.run_streaming_stage is run_streaming_stage
    assert workflow_runtime.stage_complete_payload is stage_complete_payload
    assert workflow_runtime.stage_start_payload is stage_start_payload


def test_workflow_runtime_events_do_not_expose_private_compatibility_aliases():
    from app.services.workflow_runtime import events

    for name in (
        "_RefineCompletion",
        "_sse",
        "_stage_start_payload",
        "_stage_complete_payload",
        "_refine_complete_payload",
        "_refine_completed_completion",
        "_refine_unresolved_completion",
        "_refine_failed_completion",
        "_refine_skipped_completion",
        "_refine_unsupported_canvas_completion",
        "_refiner_skipped_payload",
    ):
        assert not hasattr(events, name)


def test_workflow_runtime_stage_execution_does_not_expose_private_compat_aliases():
    from app.services.workflow_runtime import stage_execution

    assert not hasattr(stage_execution, "_StageRunResult")
    assert not hasattr(stage_execution, "_run_streaming_stage")


def test_workflow_runtime_sanitizes_stage_and_refiner_errors(tmp_path):
    stage_failure = _stage_failure(
        request_id="req-1",
        stage="layout",
        exc=ValueError("private details"),
    )
    assert stage_failure.public_payload() == {
        "stage": "layout",
        "message": "Diagram generation failed",
        "detail": "The diagram generation stage failed.",
    }
    assert stage_failure.log_context() == {
        "request_id": "req-1",
        "stage": "layout",
        "error_type": "ValueError",
    }

    private_error = RefinerPipelineError(
        phase=REFINER_FAILURE_ARTIFACT,
        reason="private details",
    )
    private_error.__cause__ = FileNotFoundError("missing refined manifest")
    refiner_failure = _refiner_failure(request_id="req-2", exc=private_error)

    assert refiner_failure.public_payload() == {
        "message": PUBLIC_REFINER_ERROR_MESSAGE,
        "detail": PUBLIC_REFINER_ERROR_DETAIL,
    }
    assert refiner_failure.log_context() == {
        "request_id": "req-2",
        "stage": "refining",
        "phase": "artifact",
        "error_type": "FileNotFoundError",
    }

    assert _request_scoped_stream_dir(str(tmp_path), "../bad/request id").endswith(
        "/stream_runs/bad_request_id"
    )


def test_workflow_runtime_payload_helpers_are_stable():
    assert stage_start_payload(
        stage="structure",
        stage_index=1,
        total_stages=4,
        message="start",
    ) == {
        "stage": "structure",
        "stage_index": 1,
        "total_stages": 4,
        "message": "start",
    }
    assert stage_complete_payload(
        stage="render",
        stage_index=4,
        total_stages=4,
        duration_ms=12,
    ) == {
        "stage": "render",
        "stage_index": 4,
        "total_stages": 4,
        "message": "Render complete",
        "duration_ms": 12,
    }
    assert _refine_error_payload() == {
        "message": "Refiner failed",
        "detail": "Auto-refinement could not complete.",
    }
    assert refine_complete_payload(
        fixes_applied=2,
        status="completed",
        message="done",
    ) == {
        "fixes_applied": 2,
        "status": "completed",
        "message": "done",
    }
    assert refiner_skipped_payload() == {
        "message": "Automatic refinement is disabled in server settings",
    }


def test_workflow_runtime_payload_models_reject_malformed_events():
    assert StageStartPayload(
        stage="structure",
        stage_index=1,
        total_stages=4,
        message="start",
    ).to_public_dict() == {
        "stage": "structure",
        "stage_index": 1,
        "total_stages": 4,
        "message": "start",
    }
    assert StreamErrorPayload(
        stage="layout",
        message="Diagram generation failed",
        detail="The diagram generation stage failed.",
    ).to_public_dict() == {
        "stage": "layout",
        "message": "Diagram generation failed",
        "detail": "The diagram generation stage failed.",
    }
    assert StreamResultPayload(
        request_id="req_1",
        project_id=None,
        snapshot_id=None,
        schema_blob={"elements": []},
        thought_trace={},
        metrics_scores={"node_count": 0},
        summary="Generated",
    ).to_public_dict()["schema_blob"] == {"elements": []}

    with pytest.raises(ValidationError):
        StageStartPayload(
            stage="unknown",
            stage_index=1,
            total_stages=4,
            message="start",
        )
    with pytest.raises(ValidationError):
        RefineCompletePayload(
            fixes_applied=0,
            status="unknown",
            message="bad",
        )
    with pytest.raises(ValidationError):
        StreamErrorPayload(
            stage="unknown",
            message="bad",
            detail="bad",
        )


def test_workflow_runtime_stream_error_payload_helpers_are_stable():
    public_validation_error = GenerationInputValidationError(
        "Unsupported canvas library: secret-canvas",
        public_detail="Unsupported canvas library",
    )

    assert _stream_error_payload(
        stage="generation",
        message="Public failure",
        detail="Public detail",
    ) == {
        "stage": "generation",
        "message": "Public failure",
        "detail": "Public detail",
    }
    assert _generation_stream_error_payload(
        ValueError("private init failure"),
        emitted_chunk=False,
    ).to_public_dict() == {
        "stage": "init",
        "message": "Diagram generation failed",
        "detail": STREAM_INIT_ERROR_DETAIL,
    }
    assert _generation_stream_error_payload(
        ValueError("private generation failure"),
        emitted_chunk=True,
    ).to_public_dict() == {
        "stage": "generation",
        "message": "Diagram generation failed",
        "detail": STREAM_GENERATION_ERROR_DETAIL,
    }
    assert _generation_stream_error_payload(
        public_validation_error,
        emitted_chunk=True,
    ).to_public_dict() == {
        "stage": "generation",
        "message": "Unsupported canvas library",
        "detail": "Unsupported canvas library",
    }
    assert _rewrite_stream_error_payload(
        ValueError("private rewrite failure")
    ).to_public_dict() == {
        "stage": "rewrite",
        "message": "Diagram generation failed",
        "detail": STREAM_REWRITE_ERROR_DETAIL,
    }
    assert _rewrite_stream_error_payload(public_validation_error).to_public_dict() == {
        "stage": "rewrite",
        "message": "Unsupported canvas library",
        "detail": "Unsupported canvas library",
    }

    chunk = _format_stream_error_payload(
        _rewrite_stream_error_payload(ValueError("private rewrite failure"))
    )
    lines = dict(line.split(": ", 1) for line in chunk.strip().splitlines())
    assert lines["event"] == "error"
    assert json.loads(lines["data"]) == {
        "stage": "rewrite",
        "message": "Diagram generation failed",
        "detail": STREAM_REWRITE_ERROR_DETAIL,
    }

    assert GenerationInputValidationError in GENERATION_STREAM_ERROR_TYPES
    assert GenerationInputValidationError in REWRITE_STREAM_ERROR_TYPES


def test_workflow_runtime_refine_completion_helpers_are_stable():
    assert REFINE_COMPLETE_STATUSES == (
        "completed",
        "skipped",
        "failed",
        "unresolved",
    )
    assert refine_completed_completion(2).public_payload() == {
        "fixes_applied": 2,
        "status": "completed",
        "message": "Auto-fixed 2 visual issue(s)",
    }
    assert refine_unresolved_completion(
        fixes_applied=1,
        termination_reason="max_iterations_exhausted",
    ).public_payload() == {
        "fixes_applied": 1,
        "status": "unresolved",
        "message": (
            "Refiner did not converge (max_iterations_exhausted); "
            "keeping the base diagram."
        ),
    }
    assert refine_unresolved_completion(
        fixes_applied=0,
        termination_reason=None,
    ).public_payload()["message"] == (
        "Refiner did not converge (not_converged); keeping the base diagram."
    )
    assert refine_failed_completion().public_payload() == {
        "fixes_applied": 0,
        "status": "failed",
        "message": "Auto-refinement failed; using base diagram.",
    }
    assert refine_skipped_completion().public_payload() == {
        "fixes_applied": 0,
        "status": "skipped",
        "message": "No auto-refinement needed.",
    }
    assert refine_unsupported_canvas_completion().public_payload() == {
        "fixes_applied": 0,
        "status": "skipped",
        "message": "Auto-refinement is currently available for Excalidraw only.",
    }

    with pytest.raises(ValueError, match="Unknown refiner completion status"):
        refine_complete_payload(
            fixes_applied=0,
            status="unknown",  # type: ignore[arg-type]
            message="bad",
        )


def test_frontend_stream_refine_status_matches_backend_contract():
    frontend_api_types = (ROOT / "frontend" / "src" / "types" / "api.ts").read_text(
        encoding="utf-8"
    )
    frontend_contract_source = (
        ROOT / "frontend" / "src" / "contracts" / "streamEvents.ts"
    ).read_text(encoding="utf-8")
    frontend_guard_source = (
        ROOT / "frontend" / "src" / "services" / "streamEventGuards.ts"
    ).read_text(encoding="utf-8")

    assert "StreamStage" in frontend_api_types
    assert "STREAM_STAGES" in frontend_guard_source
    for stage in STREAM_STAGE_VALUES:
        assert f"'{stage}'" in frontend_contract_source

    assert "StreamErrorStage" in frontend_api_types
    assert "STREAM_ERROR_STAGES" in frontend_guard_source
    for stage in STREAM_ERROR_STAGE_VALUES:
        assert f"'{stage}'" in frontend_contract_source

    assert "StreamRefineStatus" in frontend_api_types
    assert "STREAM_REFINE_STATUSES" in frontend_guard_source
    for status in REFINE_COMPLETE_STATUSES:
        assert f"'{status}'" in frontend_contract_source


def test_workflow_runtime_to_plain_handles_pydantic_like_objects():
    assert _to_plain(None) is None
    assert _to_plain({"a": 1}) == {"a": 1}
    assert _to_plain(SimpleNamespace(model_dump=lambda: {"dumped": True})) == {
        "dumped": True
    }


def test_workflow_runtime_artifact_paths_are_centralized(tmp_path):
    save_dir = str(tmp_path / "run")
    verification_dir = _verification_output_dir(save_dir)

    assert _stage_artifact_path(
        save_dir,
        STRUCTURE_STAGE_DIR,
        "structure_instantiation",
    ) == str(tmp_path / "run" / "1_structure" / "structure_instantiation.json")
    assert _structure_instantiation_path(save_dir) == str(
        tmp_path / "run" / "1_structure" / "structure_instantiation.json"
    )
    assert _layout_instantiation_path(save_dir) == str(
        tmp_path / "run" / "3_layout" / "layout_instantiation.json"
    )
    assert _render_output_dir(save_dir) == str(tmp_path / "run" / "4_render")
    assert verification_dir == str(tmp_path / "run" / "6_verification")
    assert _final_verification_output_dir(save_dir) == str(
        tmp_path / "run" / "8_final_verification"
    )
    assert _verifier_report_path(verification_dir) == str(
        tmp_path / "run" / "6_verification" / "verifier_report.json"
    )
    assert _refiner_output_dir(save_dir) == str(tmp_path / "run" / "7_refiner")
    assert {
        STRUCTURE_STAGE_DIR,
        STYLING_STAGE_DIR,
        LAYOUT_STAGE_DIR,
        RENDER_STAGE_DIR,
        VERIFICATION_STAGE_DIR,
        REFINER_STAGE_DIR,
        FINAL_VERIFICATION_STAGE_DIR,
    } == {
        "1_structure",
        "2_styling",
        "3_layout",
        "4_render",
        "6_verification",
        "7_refiner",
        "8_final_verification",
    }


def test_workflow_runtime_builds_json_runtime_directives():
    directives = _build_runtime_directives(
        locked_nodes=["node-1"],
        current_schema={"label": "测试"},
    )

    assert directives.startswith("=== RUNTIME DIRECTIVES (HIGHEST PRIORITY) ===\n")
    payload = directives.split("\n", 1)[1].strip()
    assert json.loads(payload) == {
        "locked_nodes": ["node-1"],
        "current_schema": {"label": "测试"},
    }
    assert "\\u6d4b" not in directives


def test_workflow_runtime_refiner_decision_helpers():
    class Severity:
        CRITICAL = "critical"
        MAJOR = "major"

    assert _is_refiner_canvas_supported(" Excalidraw ") is True
    assert _is_refiner_canvas_supported("tldraw") is False
    with pytest.raises(ValueError, match="Unsupported canvas library"):
        _is_refiner_canvas_supported("bad-canvas")

    verifier_state = SimpleNamespace(
        objective_findings=[SimpleNamespace(severity=Severity.MAJOR)],
        critique=None,
    )
    assert _should_run_refiner(
        workflow=SimpleNamespace(always_refine=False),
        verifier_state=verifier_state,
        severity_cls=Severity,
        canvas_library="excalidraw",
    ) is True
    assert _should_run_refiner(
        workflow=SimpleNamespace(always_refine=True),
        verifier_state=SimpleNamespace(objective_findings=[], critique=None),
        severity_cls=Severity,
        canvas_library="tldraw",
    ) is False
    assert _should_run_refiner(
        workflow=SimpleNamespace(always_refine=False),
        verifier_state=SimpleNamespace(
            has_blocking_findings=True,
            objective_findings=[],
            critique=None,
        ),
        severity_cls=Severity,
        canvas_library="excalidraw",
    ) is True
    assert _should_run_refiner(
        workflow=SimpleNamespace(always_refine=True),
        verifier_state=SimpleNamespace(
            has_errors=True,
            has_blocking_errors=False,
            blocking_errors=[],
            objective_findings=[],
            critique=None,
        ),
        severity_cls=Severity,
        canvas_library="excalidraw",
    ) is True
    assert _should_run_refiner(
        workflow=SimpleNamespace(always_refine=True),
        verifier_state=SimpleNamespace(
            has_errors=True,
            has_blocking_errors=True,
            blocking_errors=["objective checks failed"],
            objective_findings=[],
            critique=None,
        ),
        severity_cls=Severity,
        canvas_library="excalidraw",
    ) is False


def test_workflow_runtime_verification_quality_fallback_uses_blocking_semantics():
    assert _verification_quality_passed(
        SimpleNamespace(
            has_errors=True,
            has_blocking_errors=False,
            blocking_errors=[],
            has_blocking_findings=False,
            objective_summary={"critical": 0, "major": 0},
            objective_findings=[],
        )
    ) is True
    assert _verification_quality_passed(
        SimpleNamespace(
            has_errors=True,
            has_blocking_errors=True,
            blocking_errors=["objective checks failed"],
            objective_summary={"critical": 0, "major": 0},
            objective_findings=[],
        )
    ) is False
    assert _verification_quality_passed(
        SimpleNamespace(
            has_errors=False,
            has_blocking_errors=False,
            blocking_errors=[],
            objective_summary={"critical": 0, "major": 1},
            objective_findings=[],
        )
    ) is False
    assert _verification_quality_passed(
        SimpleNamespace(
            has_errors=True,
            objective_summary={"critical": 0, "major": 0},
            objective_findings=[],
        )
    ) is False


def test_workflow_runtime_loads_refined_manifest_or_classifies_artifact_errors(
    tmp_path,
):
    refined_manifest = tmp_path / "refined.json"
    refined_manifest.write_text('{"elements": [{"id": "n1"}]}', encoding="utf-8")
    refined_image = tmp_path / "refined.png"
    refined_image.write_bytes(b"png")

    assert _load_refined_manifest(
        SimpleNamespace(
            refined_manifest_path=str(refined_manifest),
            refined_image_path=str(refined_image),
        )
    ) == {"elements": [{"id": "n1"}]}
    assert _load_refined_manifest(
        SimpleNamespace(refined_manifest_path=None, refined_image_path=None)
    ) is None

    with pytest.raises(RefinerArtifactError) as missing_image:
        _load_refined_manifest(
            SimpleNamespace(
                refined_manifest_path=str(refined_manifest),
                refined_image_path=None,
            )
        )
    assert missing_image.value.phase == REFINER_FAILURE_ARTIFACT

    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(RefinerPipelineError) as bad_json:
        _load_refined_manifest(
            SimpleNamespace(
                refined_manifest_path=str(bad_manifest),
                refined_image_path=str(refined_image),
            )
        )
    assert bad_json.value.phase == REFINER_FAILURE_ARTIFACT
    assert type(bad_json.value.__cause__).__name__ == "JSONDecodeError"


@pytest.mark.asyncio
async def test_workflow_runtime_stream_stage_wraps_failures():
    async def ok_handler():
        return None

    success = await run_streaming_stage(
        request_id="req-ok",
        stage="structure",
        handler=ok_handler,
    )
    assert isinstance(success, StageRunResult)
    assert success.succeeded is True
    assert success.duration_ms >= 0

    async def failing_handler():
        raise RuntimeError("private failure")

    failure = await run_streaming_stage(
        request_id="req-fail",
        stage="layout",
        handler=failing_handler,
    )
    assert failure.succeeded is False
    assert failure.failure is not None
    assert failure.failure.public_payload()["detail"] == (
        "The diagram generation stage failed."
    )


@pytest.mark.asyncio
async def test_workflow_runtime_generation_stage_uses_thread_runner_and_syncs_artifacts(
    tmp_path,
):
    calls = []

    pipeline_run = SimpleNamespace()

    class FakeWorkflow:
        def run_generation_stage(self, run_state, stage_name, *, save_dir=None):
            calls.append((run_state, stage_name, save_dir))
            run_state.structure_state = SimpleNamespace(
                conversation_history=[{"role": "assistant"}],
            )
            run_state.structure_instantiation = {"nodes": [{"id": "n1"}]}
            run_state.structure_specification = {"diagram": "flow"}

    async def direct_thread_runner(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    artifacts = _StreamingArtifacts()
    await _run_generation_stage(
        workflow=FakeWorkflow(),
        pipeline_run=pipeline_run,
        stage_name="structure",
        save_dir=str(tmp_path),
        artifacts=artifacts,
        thread_runner=direct_thread_runner,
    )

    assert calls == [(pipeline_run, "structure", str(tmp_path))]
    assert artifacts.structure_instantiation == {"nodes": [{"id": "n1"}]}


@pytest.mark.asyncio
async def test_workflow_runtime_render_stage_uses_thread_runner():
    calls = []

    def fake_render_manifest(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            manifest=SimpleNamespace(model_dump=lambda: {"elements": [{"id": "n1"}]}),
            manifest_path="/tmp/diagram.json",
            png_path="/tmp/diagram.png",
        )

    async def direct_thread_runner(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    artifacts = _StreamingArtifacts(
        structure_instantiation={"nodes": [{"id": "n1"}]},
        layout_instantiation={"blocks": [{"id": "n1"}]},
    )
    await _run_render_stage(
        render_manifest=fake_render_manifest,
        request=SimpleNamespace(canvas_library="excalidraw"),
        save_dir="/tmp/run",
        artifacts=artifacts,
        thread_runner=direct_thread_runner,
    )

    assert calls == [
        {
            "layout_instantiation": {"blocks": [{"id": "n1"}]},
            "structure_instantiation": {"nodes": [{"id": "n1"}]},
            "canvas_library": "excalidraw",
            "output_dir": "/tmp/run/4_render",
        }
    ]
    assert artifacts.diagram_manifest == {"elements": [{"id": "n1"}]}


@pytest.mark.asyncio
async def test_workflow_runtime_iterative_refiner_uses_injected_thread_runner(
    tmp_path,
):
    refined_manifest = tmp_path / "refined.json"
    refined_manifest.write_text('{"elements": [{"id": "fixed"}]}', encoding="utf-8")
    refined_image = tmp_path / "refined.png"
    refined_image.write_bytes(b"png")
    calls = []

    class FakeRefiner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                converged=True,
                termination_reason="resolved",
                refined_manifest_path=str(refined_manifest),
                refined_image_path=str(refined_image),
                iteration_logs=[
                    SimpleNamespace(
                        deterministic_edits=[_edit_outcome(), _edit_outcome()],
                        llm_edits=[_edit_outcome()],
                    )
                ],
            )

    async def direct_thread_runner(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    result = await _run_iterative_refiner(
        iterative_refiner_workflow_cls=FakeRefiner,
        request=SimpleNamespace(canvas_library="excalidraw"),
        save_dir=str(tmp_path / "run"),
        verification_dir=str(tmp_path / "run" / "6_verification"),
        refiner_max_iterations=2,
        artifacts=SimpleNamespace(
            render_result=SimpleNamespace(
                manifest_path=str(tmp_path / "base.json"),
                png_path=str(tmp_path / "base.png"),
            )
        ),
        thread_runner=direct_thread_runner,
    )

    assert result.fixes_applied == 3
    assert result.refined_manifest == {"elements": [{"id": "fixed"}]}
    assert result.refined_manifest_path == str(refined_manifest)
    assert result.refined_image_path == str(refined_image)
    assert result.converged is True
    assert result.termination_reason == "resolved"
    assert calls[0]["max_iterations"] == 2
    assert calls[0]["canvas_library"] == "excalidraw"
    assert calls[0]["output_dir"].endswith("/run/7_refiner")


def test_refinement_report_counts_surviving_derived_repairs_without_double_counting():
    from app.services.workflow_runtime.refiner import _count_surviving_fixes
    def log(*, applied=0, rolled_back=False):
        return SimpleNamespace(deterministic_edits=[_edit_outcome() for _ in range(applied)],
            llm_edits=[], rolled_back=rolled_back,
            rerouted_arrows=[{'arrow_id': 'a'}, {'arrow_id': 'a'}, {'arrow_id': 'b'}])
    assert _count_surviving_fixes([log()]) == 2
    assert _count_surviving_fixes([log(applied=1)]) == 1
    assert _count_surviving_fixes([log(rolled_back=True)]) == 0


@pytest.mark.asyncio
async def test_workflow_runtime_iterative_refiner_counts_only_applied_edits(tmp_path):
    """Rejected proposals are logged now; they must not inflate fixes_applied."""
    refined_manifest = tmp_path / "refined.json"
    refined_manifest.write_text('{"elements": [{"id": "fixed"}]}', encoding="utf-8")
    refined_image = tmp_path / "refined.png"
    refined_image.write_bytes(b"png")

    class FakeRefiner:
        def run(self, **kwargs):
            return SimpleNamespace(
                converged=True,
                termination_reason="resolved",
                refined_manifest_path=str(refined_manifest),
                refined_image_path=str(refined_image),
                iteration_logs=[
                    SimpleNamespace(
                        deterministic_edits=[
                            _edit_outcome(),
                            _edit_outcome(applied=False, error="skipped: no-op"),
                        ],
                        llm_edits=[
                            _edit_outcome(
                                applied=False,
                                error="schema: extra fields not permitted",
                            ),
                            _edit_outcome(applied=False, error="target not found"),
                        ],
                    ),
                    SimpleNamespace(
                        deterministic_edits=[],
                        llm_edits=[_edit_outcome()],
                    ),
                ],
            )

    async def direct_thread_runner(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    result = await _run_iterative_refiner(
        iterative_refiner_workflow_cls=FakeRefiner,
        request=SimpleNamespace(canvas_library="excalidraw"),
        save_dir=str(tmp_path / "run"),
        verification_dir=str(tmp_path / "run" / "6_verification"),
        refiner_max_iterations=2,
        artifacts=SimpleNamespace(
            render_result=SimpleNamespace(
                manifest_path=str(tmp_path / "base.json"),
                png_path=str(tmp_path / "base.png"),
            )
        ),
        thread_runner=direct_thread_runner,
    )

    # Five outcomes were recorded across both iterations; two were applied.
    assert result.fixes_applied == 2


@pytest.mark.asyncio
async def test_workflow_runtime_iterative_refiner_does_not_promote_unconverged_artifacts(
    tmp_path,
):
    refined_manifest = tmp_path / "refined.json"
    refined_manifest.write_text('{"elements": [{"id": "untrusted"}]}', encoding="utf-8")
    refined_image = tmp_path / "refined.png"
    refined_image.write_bytes(b"png")

    class UnconvergedRefiner:
        def run(self, **kwargs):
            return SimpleNamespace(
                status="reported",
                converged=False,
                termination_reason="fixed_point_unresolved",
                refined_manifest_path=str(refined_manifest),
                refined_image_path=str(refined_image),
                iteration_logs=[
                    SimpleNamespace(deterministic_edits=[_edit_outcome()], llm_edits=[])
                ],
            )

    async def direct_thread_runner(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    result = await _run_iterative_refiner(
        iterative_refiner_workflow_cls=UnconvergedRefiner,
        request=SimpleNamespace(canvas_library="excalidraw"),
        save_dir=str(tmp_path / "run"),
        verification_dir=str(tmp_path / "run" / "6_verification"),
        refiner_max_iterations=1,
        artifacts=SimpleNamespace(
            render_result=SimpleNamespace(
                manifest_path=str(tmp_path / "base.json"),
                png_path=str(tmp_path / "base.png"),
            )
        ),
        thread_runner=direct_thread_runner,
    )

    assert result.fixes_applied == 1
    assert result.refined_manifest is None
    assert result.refined_manifest_path is None
    assert result.refined_image_path is None
    assert result.converged is False
    assert result.termination_reason == "fixed_point_unresolved"


@pytest.mark.asyncio
async def test_workflow_runtime_iterative_refiner_preserves_failed_status_phase(
    tmp_path,
):
    class FailedRefiner:
        def run(self, **kwargs):
            return SimpleNamespace(
                status="failed",
                refined_manifest_path=None,
                refined_image_path=None,
                iteration_logs=[],
            )

    async def direct_thread_runner(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    with pytest.raises(RefinerExecutionStatusError) as exc_info:
        await _run_iterative_refiner(
            iterative_refiner_workflow_cls=FailedRefiner,
            request=SimpleNamespace(canvas_library="excalidraw"),
            save_dir=str(tmp_path / "run"),
            verification_dir=str(tmp_path / "run" / "6_verification"),
            refiner_max_iterations=1,
            artifacts=SimpleNamespace(
                render_result=SimpleNamespace(
                    manifest_path=str(tmp_path / "base.json"),
                    png_path=str(tmp_path / "base.png"),
                )
            ),
            thread_runner=direct_thread_runner,
        )

    assert exc_info.value.phase == REFINER_FAILURE_EXECUTION


def test_workflow_runtime_sse_payload_remains_json_encoded():
    chunk = format_workflow_sse("stage_start", {"stage": "structure"})

    lines = dict(line.split(": ", 1) for line in chunk.strip().splitlines())
    assert lines["event"] == "stage_start"
    assert json.loads(lines["data"]) == {"stage": "structure"}
