from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-workflow-service-12345")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-workflow-service-123")

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.diagram_generation_contract import GenerationInputValidationError
from app.services.workflow_generate_service import WorkflowGenerateService
from app.services.workflow_engine_adapter import (
    PUBLIC_REFINER_COMPLETE_MESSAGE,
    PUBLIC_REFINER_DEGRADED_MESSAGE,
    PUBLIC_REFINER_START_MESSAGE,
    PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE,
    PUBLIC_REFINER_DISABLED_MESSAGE,
    REFINER_FAILURE_ARTIFACT,
    REFINER_FAILURE_EXECUTION,
    REFINER_FAILURE_VERIFICATION,
    REFINER_STAGE_INDEX,
    REFINER_TOTAL_STAGES,
    StreamingEngineDependencies,
    WorkflowEngineAdapter,
    WorkflowRunRequest,
    _build_workflow_execution_context,
    _refine_error_payload,
    _request_scoped_stream_dir,
    _should_run_refiner,
    _build_workflow_result,
    _stage_failure,
    _verification_should_run,
)
from app.services.workflow_runtime import (
    refine_complete_payload,
    refiner_skipped_payload,
    stage_complete_payload,
    stage_start_payload,
)
from app.services.workflow_runtime.stage_execution import (
    run_streaming_stage,
)


@pytest.fixture(autouse=True)
def isolated_workflow_settings(monkeypatch, tmp_path):
    """Unit workflows must not download models or touch a developer's store."""
    from app.config import Settings
    settings = Settings(
        _env_file=None, jwt_secret="test-workflow-jwt", session_secret="test-workflow-session",
        results_dir=str(tmp_path), design_memory_enabled=False,
    )
    monkeypatch.setattr("app.services.workflow_generate_service.get_settings", lambda: settings)


def _applied_edit_outcome():
    """Stand in for an engine EditApplyOutcome row that reached the manifest."""
    return SimpleNamespace(edit=None, applied=True, error=None, raw=None)


class _FakeStage:
    def __init__(self, result):
        self.result = result

    def run(self, state):
        if callable(self.result):
            return self.result(state)
        return self.result


class _FakePipelineGeneratorMixin:
    canvas_library = "excalidraw"

    def resolve_generation_context(self, text_content, user_query, diagram_type=None):
        return diagram_type or "flowchart", "blush_sage"

    def build_stage_context(self, stage_name, diagram_type):
        return f"{stage_name}:{diagram_type}"

    def begin_pipeline_run(
        self,
        text_content,
        user_query,
        *,
        design_expertise="",
        runtime_directives="",
        diagram_type=None,
        content_area=None,
    ):
        effective_diagram_type, palette_key = self.resolve_generation_context(
            text_content,
            user_query,
            diagram_type,
        )
        return SimpleNamespace(
            text_content=text_content,
            user_query=user_query,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            effective_diagram_type=effective_diagram_type,
            palette_key=palette_key,
            structure_state=None,
            styling_state=None,
            layout_state=None,
            structure_instantiation=None,
            structure_specification=None,
            styling_instantiation=None,
            styling_specification=None,
            layout_instantiation=None,
            layout_specification=None,
            content_area=content_area,
        )

    def run_pipeline_stage(self, run_state, stage_name, *, save_dir=None):
        if stage_name == "structure":
            state = SimpleNamespace(
                text_content=run_state.text_content,
                user_query=run_state.user_query,
                canvas_library=self.canvas_library,
                stage_knowledge=self.build_stage_context(
                    "Structure",
                    run_state.effective_diagram_type,
                ),
                design_expertise=run_state.design_expertise,
                runtime_directives=run_state.runtime_directives,
                diagram_type=run_state.effective_diagram_type,
            )
            stage_state = self.structure.run(state)
            run_state.structure_state = stage_state
            run_state.structure_instantiation = stage_state.structure_instantiation
            run_state.structure_specification = stage_state.structure_specification
            if isinstance(run_state.structure_instantiation, dict):
                chart_type = run_state.structure_instantiation.get("chart_type")
                if isinstance(chart_type, str) and chart_type.strip():
                    run_state.effective_diagram_type = chart_type
            _write_fake_stage_artifacts(
                save_dir,
                "1_structure",
                "structure",
                run_state.structure_instantiation,
                run_state.structure_specification,
            )
            return

        if stage_name == "styling":
            state = SimpleNamespace(
                text_content=run_state.text_content,
                user_query=run_state.user_query,
                canvas_library=self.canvas_library,
                structure_instantiation=run_state.structure_instantiation,
                structure_specification=run_state.structure_specification,
                stage_knowledge=self.build_stage_context(
                    "Styling",
                    run_state.effective_diagram_type,
                ),
                design_expertise=run_state.design_expertise,
                runtime_directives=run_state.runtime_directives,
                diagram_type=run_state.effective_diagram_type,
                conversation_history=list(
                    getattr(run_state.structure_state, "conversation_history", []),
                ),
                palette_key=run_state.palette_key,
            )
            stage_state = self.styling.run(state)
            run_state.styling_state = stage_state
            run_state.styling_instantiation = stage_state.styling_instantiation
            run_state.styling_specification = stage_state.styling_specification
            _write_fake_stage_artifacts(
                save_dir,
                "2_styling",
                "styling",
                run_state.styling_instantiation,
                run_state.styling_specification,
            )
            return

        if stage_name == "layout":
            state = SimpleNamespace(
                text_content=run_state.text_content,
                user_query=run_state.user_query,
                structure_instantiation=run_state.structure_instantiation,
                styling_instantiation=run_state.styling_instantiation,
                structure_specification=run_state.structure_specification,
                styling_specification=run_state.styling_specification,
                stage_knowledge=self.build_stage_context(
                    "Layout",
                    run_state.effective_diagram_type,
                ),
                design_expertise=run_state.design_expertise,
                runtime_directives=run_state.runtime_directives,
                diagram_type=run_state.effective_diagram_type,
                canvas_library=self.canvas_library,
                conversation_history=list(
                    getattr(run_state.styling_state, "conversation_history", []),
                ),
            )
            stage_state = self.layout.run(state)
            run_state.layout_state = stage_state
            run_state.layout_instantiation = stage_state.layout_instantiation
            run_state.layout_specification = stage_state.layout_specification
            _write_fake_stage_artifacts(
                save_dir,
                "3_layout",
                "layout",
                run_state.layout_instantiation,
                run_state.layout_specification,
            )
            return

        raise ValueError(f"Unknown stage: {stage_name}")


class _FakeWorkflowStepwiseMixin:
    def begin_generation_run(
        self,
        text_content,
        user_query,
        *,
        design_expertise="",
        runtime_directives="",
        diagram_type=None,
        content_area=None,
    ):
        return self.generator.begin_pipeline_run(
            text_content,
            user_query,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=diagram_type,
            content_area=content_area,
        )

    def run_generation_stage(self, run_state, stage_name, *, save_dir=None):
        self.generator.run_pipeline_stage(
            run_state,
            stage_name,
            save_dir=save_dir,
        )


def _write_fake_stage_artifacts(
    save_dir,
    stage_dir_name,
    artifact_name,
    instantiation,
    specification,
):
    if not save_dir:
        return
    stage_dir = Path(save_dir) / stage_dir_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / f"{artifact_name}_instantiation.json").write_text(
        json.dumps(instantiation),
        encoding="utf-8",
    )
    (stage_dir / f"{artifact_name}_specification.json").write_text(
        json.dumps(specification),
        encoding="utf-8",
    )


def _data_from_sse(chunk: str) -> dict:
    data_line = next(line for line in chunk.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


def _event_from_sse(chunk: str) -> str:
    event_line = next(line for line in chunk.splitlines() if line.startswith("event: "))
    return event_line.removeprefix("event: ")


def _runtime_directives_payload(runtime_directives: str) -> dict:
    return json.loads(runtime_directives.splitlines()[1])


class _RecordingWorkflowLogger:
    def __init__(self):
        self.bind_calls = []
        self.opt_calls = []
        self.warning_messages = []
        self.error_messages = []

    def bind(self, **kwargs):
        self.bind_calls.append(kwargs)
        return self

    def opt(self, **kwargs):
        self.opt_calls.append(kwargs)
        return self

    def warning(self, message):
        self.warning_messages.append(message)

    def error(self, message):
        self.error_messages.append(message)


def test_request_scoped_stream_dir_sanitizes_request_id(tmp_path):
    stream_dir = _request_scoped_stream_dir(str(tmp_path), "../bad/request id")

    assert stream_dir == str(tmp_path / "stream_runs" / "bad_request_id")


def test_workflow_execution_context_is_shared_sync_stream_contract():
    request = WorkflowRunRequest(
        context="A to B",
        requirements="",
        locked_nodes=["node-1"],
        current_schema={"elements": [{"id": "node-1"}]},
        canvas_library="excalidraw",
        user_tier="pro",
        request_id="req_contract",
    )

    context = _build_workflow_execution_context(request)

    assert context.user_query == "Generate diagram schema"
    assert context.refiner_requested is True
    assert context.refiner_max_iterations == 2
    assert _runtime_directives_payload(context.runtime_directives) == {
        "locked_nodes": ["node-1"],
        "current_schema": {"elements": [{"id": "node-1"}]},
    }


def test_workflow_execution_context_enables_refiner_for_all_tiers():
    request = WorkflowRunRequest(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier="enterprise",
        request_id="req_contract",
    )

    context = _build_workflow_execution_context(request)

    assert context.refiner_requested is True
    assert context.refiner_max_iterations == 2


async def _direct_to_thread(func, /, *args, **kwargs):
    return func(*args, **kwargs)


def _refiner_streaming_dependency_loader(
    tmp_path,
    *,
    verifier_workflow_cls,
    iterative_refiner_workflow_cls,
    always_refine=True,
    enable_critic=False,
):
    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={"nodes": [{"id": "n1"}]},
                    structure_specification={"diagram": "flow"},
                    conversation_history=[{"role": "assistant", "content": "structure"}],
                )
            )
            self.styling = _FakeStage(
                SimpleNamespace(
                    styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                    styling_specification={"visual": "simple"},
                    conversation_history=[{"role": "assistant", "content": "styling"}],
                )
            )
            self.layout = _FakeStage(
                SimpleNamespace(
                    layout_instantiation={"blocks": [{"id": "n1"}]},
                    layout_specification={"anchors": []},
                )
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type or "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = enable_critic
            self.always_refine = always_refine

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    class FakeSeverity:
        CRITICAL = "critical"
        MAJOR = "major"

    def fake_render_manifest(**kwargs):
        return SimpleNamespace(
            manifest={"elements": [{"id": "base"}], "edges": []},
            png_path=str(tmp_path / "diagram.png"),
            manifest_path=str(tmp_path / "diagram.json"),
        )

    def load_streaming_dependencies():
        return StreamingEngineDependencies(
            workflow_cls=FakeWorkflow,
            verifier_workflow_cls=verifier_workflow_cls,
            iterative_refiner_workflow_cls=iterative_refiner_workflow_cls,
            severity_cls=FakeSeverity,
            render_manifest=fake_render_manifest,
        )

    return load_streaming_dependencies


async def _collect_refiner_stream_chunks(adapter, *, canvas_library="excalidraw"):
    chunks = []
    async for chunk in adapter.stream_without_render(
        model="fake-model",
        request=WorkflowRunRequest(
            context="A to B",
            requirements="draw",
            locked_nodes=[],
            current_schema=None,
            canvas_library=canvas_library,
            user_tier="pro",
            request_id="req_refiner_test",
        ),
    ):
        chunks.append(chunk)
    return chunks


@pytest.mark.asyncio
async def test_parallel_preparation_waits_for_complete_critic_before_model(tmp_path):
    from threading import Event

    preparing, reviewing, reviewed = Event(), Event(), Event()

    class Verifier:
        def run(self, **kwargs):
            if not reviewed.is_set():
                reviewing.set()
                assert preparing.wait(3), "preparation did not overlap the critic"
                reviewed.set()
            return SimpleNamespace(critique=SimpleNamespace(overall_score=8),
                objective_summary={}, has_blocking_errors=False, has_blocking_findings=False)

    class Refiner:
        def prepare(self, **kwargs):
            preparing.set()
            assert reviewing.wait(3), "critic did not overlap preparation"
            return SimpleNamespace(status="prepared", output_dir=kwargs["output_dir"])

        def run_prepared(self, state, **kwargs):
            assert reviewed.is_set(), "model started before the full critic was ready"
            out = Path(state.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "refined.json").write_text('{"elements":[{"id":"refined"}]}')
            (out / "refined.png").write_bytes(b"png")
            return SimpleNamespace(status="reported", converged=True, termination_reason="resolved",
                iteration_logs=[], refined_manifest_path=str(out / "refined.json"),
                refined_image_path=str(out / "refined.png"))

        def run(self, **kwargs):
            pytest.fail("prepared work was discarded and rerun")

    adapter = WorkflowEngineAdapter(str(tmp_path), streaming_dependency_loader=
        _refiner_streaming_dependency_loader(tmp_path, verifier_workflow_cls=Verifier,
            iterative_refiner_workflow_cls=Refiner, enable_critic=True))
    chunks = await _collect_refiner_stream_chunks(adapter)
    assert not any(_event_from_sse(c) in {"error", "refine_error"} for c in chunks)
    result = _data_from_sse(next(c for c in chunks if _event_from_sse(c) == "result"))
    assert result["schema_blob"]["elements"][0]["id"] == "refined"
    assert "parallel_preparation_ms" in result["metrics_scores"]["generation"]["optimizations"]


@pytest.mark.asyncio
async def test_disconnecting_joins_preparation_before_cleanup(tmp_path):
    import asyncio
    from threading import Event

    entered, release, finished = Event(), Event(), Event()

    class Verifier:
        def run(self, **kwargs):
            assert entered.wait(3)
            return SimpleNamespace(critique=SimpleNamespace(overall_score=8), objective_summary={})

    class Refiner:
        def prepare(self, **kwargs):
            entered.set()
            assert release.wait(3)
            Path(kwargs["output_dir"]).mkdir(parents=True, exist_ok=True)
            finished.set()
            return SimpleNamespace(status="prepared")

    adapter = WorkflowEngineAdapter(str(tmp_path), streaming_dependency_loader=
        _refiner_streaming_dependency_loader(tmp_path, verifier_workflow_cls=Verifier,
            iterative_refiner_workflow_cls=Refiner, enable_critic=True))
    request = WorkflowRunRequest(context="test", requirements=None, locked_nodes=[],
        current_schema=None, canvas_library="excalidraw", user_tier=None, request_id="disconnect")
    stream = adapter.stream_without_render(model="fake", request=request)
    try:
        async for chunk in stream:
            if _event_from_sse(chunk) == "stage_complete" and _data_from_sse(chunk)["stage"] == "verification":
                closing = asyncio.create_task(stream.aclose())
                await asyncio.sleep(0)
                assert not closing.done()
                release.set()
                await closing
                break
        assert finished.is_set()
        assert not (tmp_path / "stream_runs" / "disconnect").exists()
    finally:
        release.set()
        await stream.aclose()


def _assert_degraded_refiner_public_contract(chunks):
    refine_error_chunk = next(
        chunk for chunk in chunks if chunk.startswith("event: refine_error\n")
    )
    assert _data_from_sse(refine_error_chunk) == {
        "message": "Refiner failed",
        "detail": "Auto-refinement could not complete.",
    }

    refine_complete_chunk = next(
        chunk for chunk in chunks if chunk.startswith("event: refine_complete\n")
    )
    assert _data_from_sse(refine_complete_chunk) == {
        "fixes_applied": 0,
        "status": "failed",
        "message": "Auto-refinement failed; using base diagram.",
    }

    result_chunk = next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    result = _data_from_sse(result_chunk)
    assert result["schema_blob"]["elements"][0]["id"] == "base"


def _assert_stream_verification_failure_contract(chunks):
    error_chunk = next(chunk for chunk in chunks if chunk.startswith("event: error\n"))
    assert _data_from_sse(error_chunk) == {
        "stage": "verification",
        "message": "Diagram generation failed",
        "detail": "The diagram generation stage failed.",
    }
    assert "secret" not in error_chunk
    assert not any(_event_from_sse(chunk) == "result" for chunk in chunks)
    assert not any(_event_from_sse(chunk) == "refine_error" for chunk in chunks)
    assert not any(_event_from_sse(chunk) == "refine_complete" for chunk in chunks)


def test_sync_generation_prefers_final_manifest(monkeypatch):
    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self, **kwargs):
            return SimpleNamespace(
                diagram_manifest={"elements": [{"id": "base"}]},
                refined_diagram_manifest={"elements": [{"id": "refined"}]},
                final_diagram_manifest={"elements": [{"id": "final"}]},
                structure_instantiation={"nodes": [{"id": "n1"}]},
                styling_instantiation={"styles": {"n1": {}}},
                layout_instantiation={"blocks": [{"id": "n1"}]},
            )

    monkeypatch.setattr("evo_diagram.agentic_system.workflow.Text2DiagramWorkflow", FakeWorkflow)

    service = WorkflowGenerateService()
    monkeypatch.setattr(service, "_create_llm", lambda: object())

    result = service._run_workflow_without_render_sync(
        context="A to B",
        requirements=None,
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        request_id="req_test",
        user_tier="pro",
    )

    assert result["schema_blob"] == {"elements": [{"id": "final"}]}
    assert result["metrics_scores"] == {"node_count": 1, "edge_count": 0}
    assert result["thought_trace"]["structure_instantiation"]["nodes"][0]["id"] == "n1"


def test_build_workflow_result_counts_shared_schema_collection_aliases():
    result = _build_workflow_result(
        request_id="req_test",
        schema_blob={
            "blocks": [{"id": "node-1"}],
            "arrows": [{"id": "edge-1"}],
        },
        structure_instantiation={},
        styling_instantiation={},
        layout_instantiation={},
        summary="Generated",
    )

    assert result["metrics_scores"]["node_count"] == 1
    assert result["metrics_scores"]["edge_count"] == 1
    assert "generation" not in result["metrics_scores"]


def test_sync_generation_delegates_to_injected_engine_adapter(monkeypatch):
    seen = {}

    class FakeEngineAdapter:
        def run_without_render_sync(self, *, model, request: WorkflowRunRequest):
            seen["model"] = model
            seen["request"] = request
            return {"schema_blob": {"elements": []}}

    service = WorkflowGenerateService(engine_adapter=FakeEngineAdapter())
    monkeypatch.setattr(service, "_create_llm", lambda: "fake-model")

    result = service._run_workflow_without_render_sync(
        context="A to B",
        requirements="draw",
        locked_nodes=["n1"],
        current_schema={"elements": []},
        canvas_library="tldraw",
        request_id="req_test",
        user_tier="enterprise",
    )

    assert result == {"schema_blob": {"elements": []}}
    assert seen["model"] == "fake-model"
    assert seen["request"].context == "A to B"
    assert seen["request"].canvas_library == "tldraw"
    assert seen["request"].user_tier == "enterprise"


def test_run_request_normalizes_canvas_library_before_engine_execution(monkeypatch):
    seen = {}

    class FakeEngineAdapter:
        def run_without_render_sync(self, *, model, request: WorkflowRunRequest):
            seen["request"] = request
            return {"schema_blob": {"elements": []}}

    service = WorkflowGenerateService(engine_adapter=FakeEngineAdapter())
    monkeypatch.setattr(service, "_create_llm", lambda: "fake-model")

    service._run_workflow_without_render_sync(
        context="A to B",
        requirements=None,
        locked_nodes=[],
        current_schema=None,
        canvas_library=" TLDraw ",
        request_id="req_test",
        user_tier=None,
        use_icons=True,
    )

    assert seen["request"].canvas_library == "tldraw"
    assert seen["request"].use_icons is True


def test_run_request_rejects_unknown_canvas_library_before_engine_execution(monkeypatch):
    class FakeEngineAdapter:
        def run_without_render_sync(self, *, model, request: WorkflowRunRequest):
            raise AssertionError("engine adapter should not run for invalid input")

    service = WorkflowGenerateService(engine_adapter=FakeEngineAdapter())
    monkeypatch.setattr(
        service,
        "_create_llm",
        lambda: (_ for _ in ()).throw(
            AssertionError("LLM should not be created for invalid input")
        ),
    )

    with pytest.raises(GenerationInputValidationError) as exc_info:
        service._run_workflow_without_render_sync(
            context="A to B",
            requirements=None,
            locked_nodes=[],
            current_schema=None,
            canvas_library="unknown",
            request_id="req_test",
            user_tier=None,
        )

    assert exc_info.value.public_detail == "Unsupported canvas library"


def test_engine_adapter_uses_injected_sync_workflow_loader(tmp_path):
    loaded = []
    constructed = []
    run_seen = []

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def run(self, **kwargs):
            run_seen.append(kwargs)
            return SimpleNamespace(
                diagram_manifest={"elements": [{"id": "base"}]},
                refined_diagram_manifest=None,
                structure_instantiation={"nodes": [{"id": "n1"}]},
                styling_instantiation={"styles": {"n1": {}}},
                layout_instantiation={"blocks": [{"id": "n1"}]},
            )

    def load_workflow_cls():
        loaded.append(True)
        return FakeWorkflow

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        workflow_cls_loader=load_workflow_cls,
    )

    result = adapter.run_without_render_sync(
        model="fake-model",
        request=WorkflowRunRequest(
            context="A to B",
            requirements="",
            locked_nodes=["n1"],
            current_schema={"elements": [{"id": "n1"}]},
            canvas_library="excalidraw",
            user_tier="pro",
            request_id="req_test",
        ),
    )

    assert loaded == [True]
    assert constructed[0]["model"] == "fake-model"
    assert constructed[0]["router_model"] == "fake-model"
    assert constructed[0]["save_dir"] == str(tmp_path)
    assert constructed[0]["enable_refiner"] is True
    assert constructed[0]["refiner_max_iterations"] == 2
    assert run_seen[0]["user_query"] == "Generate diagram schema"
    assert _runtime_directives_payload(run_seen[0]["runtime_directives"]) == {
        "locked_nodes": ["n1"],
        "current_schema": {"elements": [{"id": "n1"}]},
    }
    assert result["schema_blob"] == {"elements": [{"id": "base"}]}


def test_sync_generation_skips_refiner_for_unsupported_canvas(tmp_path):
    constructed = []

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def run(self, **kwargs):
            return SimpleNamespace(
                diagram_manifest={"document": {"store": {}}},
                refined_diagram_manifest=None,
                final_diagram_manifest=None,
                structure_instantiation={},
                styling_instantiation={},
                layout_instantiation={},
            )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        workflow_cls_loader=lambda: FakeWorkflow,
    )

    result = adapter.run_without_render_sync(
        model="fake-model",
        request=WorkflowRunRequest(
            context="A to B",
            requirements="draw",
            locked_nodes=[],
            current_schema=None,
            canvas_library="tldraw",
            user_tier="pro",
            request_id="req_test",
        ),
    )

    assert constructed[0]["canvas_library"] == "tldraw"
    assert constructed[0]["enable_refiner"] is False
    assert constructed[0]["refiner_max_iterations"] == 2
    assert result["schema_blob"] == {"document": {"store": {}}}


def test_engine_adapter_uses_injected_engine_port_for_sync_workflow(tmp_path):
    calls = []
    constructed = []

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def run(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                diagram_manifest={"elements": [{"id": "from-port"}]},
                refined_diagram_manifest=None,
                structure_instantiation={},
                styling_instantiation={},
                layout_instantiation={},
            )

    class FakeEnginePort:
        def load_text_workflow_cls(self):
            calls.append("load_text_workflow_cls")
            return FakeWorkflow

        def load_streaming_dependencies(self):
            raise AssertionError("sync workflow should not load streaming dependencies")

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        engine_port=FakeEnginePort(),
    )

    result = adapter.run_without_render_sync(
        model="fake-model",
        request=WorkflowRunRequest(
            context="A to B",
            requirements="draw",
            locked_nodes=[],
            current_schema=None,
            canvas_library="excalidraw",
            user_tier=None,
            request_id="req_port",
        ),
    )

    assert calls[0] == "load_text_workflow_cls"
    assert calls[1]["user_query"] == "draw"
    assert constructed[0]["canvas_library"] == "excalidraw"
    assert result["schema_blob"] == {"elements": [{"id": "from-port"}]}


def test_stage_failure_separates_public_payload_from_log_context():
    failure = _stage_failure(
        request_id="req-secret",
        stage="render",
        exc=RuntimeError("provider token leaked"),
    )

    assert failure.public_payload() == {
        "stage": "render",
        "message": "Diagram generation failed",
        "detail": "The diagram generation stage failed.",
    }
    assert failure.log_context() == {
        "request_id": "req-secret",
        "stage": "render",
        "error_type": "RuntimeError",
    }
    assert "provider token" not in json.dumps(failure.public_payload())


@pytest.mark.asyncio
async def test_run_streaming_stage_converts_exceptions_to_safe_failure():
    logger = _RecordingWorkflowLogger()

    stage_exc = RuntimeError("provider token leaked")

    async def fail_stage():
        raise stage_exc

    result = await run_streaming_stage(
        request_id="req-secret",
        stage="layout",
        handler=fail_stage,
        stage_logger=logger,
    )

    assert result.succeeded is False
    assert result.duration_ms == 0
    assert result.failure is not None
    assert result.failure.public_payload() == {
        "stage": "layout",
        "message": "Diagram generation failed",
        "detail": "The diagram generation stage failed.",
    }
    assert "provider token" not in json.dumps(result.failure.public_payload())
    assert logger.bind_calls == [
        {
            "request_id": "req-secret",
            "stage": "layout",
            "error_type": "RuntimeError",
        }
    ]
    assert logger.error_messages == ["Streaming workflow stage failed"]
    assert len(logger.opt_calls) == 1
    assert logger.opt_calls[0]["exception"] is stage_exc


@pytest.mark.asyncio
async def test_run_streaming_stage_returns_success_duration(monkeypatch):
    times = [10.0, 10.25]

    def fake_monotonic():
        if times:
            return times.pop(0)
        return 10.25

    monkeypatch.setattr(
        "app.services.workflow_runtime.stage_execution.time.monotonic",
        fake_monotonic,
    )

    calls = []

    async def run_stage():
        calls.append("ran")

    result = await run_streaming_stage(
        request_id="req-ok",
        stage="structure",
        handler=run_stage,
    )

    assert calls == ["ran"]
    assert result.succeeded is True
    assert result.failure is None
    assert result.duration_ms == 250


def test_streaming_stage_payload_helpers_keep_public_contract_stable():
    assert stage_start_payload(
        stage="structure",
        stage_index=1,
        total_stages=4,
        message="Analyzing document structure...",
    ) == {
        "stage": "structure",
        "stage_index": 1,
        "total_stages": 4,
        "message": "Analyzing document structure...",
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


def test_streaming_refiner_payload_helpers_keep_public_contract_stable():
    assert stage_start_payload(
        stage="refining",
        stage_index=REFINER_STAGE_INDEX,
        total_stages=REFINER_TOTAL_STAGES,
        message=PUBLIC_REFINER_START_MESSAGE,
    ) == {
        "stage": "refining",
        "stage_index": 7,
        "total_stages": 9,
        "message": "Refiner Agent is fixing visual issues...",
    }
    assert stage_complete_payload(
        stage="refining",
        stage_index=REFINER_STAGE_INDEX,
        total_stages=REFINER_TOTAL_STAGES,
        duration_ms=8,
        message=PUBLIC_REFINER_COMPLETE_MESSAGE,
    ) == {
        "stage": "refining",
        "stage_index": 7,
        "total_stages": 9,
        "message": "Refining complete",
        "duration_ms": 8,
    }
    assert _refine_error_payload() == {
        "message": "Refiner failed",
        "detail": "Auto-refinement could not complete.",
    }
    assert refine_complete_payload(
        fixes_applied=0,
        status="failed",
        message=PUBLIC_REFINER_DEGRADED_MESSAGE,
    ) == {
        "fixes_applied": 0,
        "status": "failed",
        "message": "Auto-refinement failed; using base diagram.",
    }
    assert refiner_skipped_payload() == {"message": PUBLIC_REFINER_DISABLED_MESSAGE}


def test_should_run_refiner_rejects_non_excalidraw_canvas_even_when_forced():
    class Severity:
        CRITICAL = "critical"
        MAJOR = "major"

    workflow = SimpleNamespace(always_refine=True)
    verifier_state = SimpleNamespace(objective_findings=[], critique=None)

    assert _should_run_refiner(
        workflow=workflow,
        verifier_state=verifier_state,
        severity_cls=Severity,
        canvas_library="tldraw",
    ) is False
    assert _should_run_refiner(
        workflow=workflow,
        verifier_state=verifier_state,
        severity_cls=Severity,
        canvas_library=" Excalidraw ",
    ) is True
    assert _should_run_refiner(
        workflow=workflow,
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
        workflow=workflow,
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
    with pytest.raises(ValueError, match="Unsupported canvas library"):
        _should_run_refiner(
            workflow=workflow,
            verifier_state=verifier_state,
            severity_cls=Severity,
            canvas_library="bad-canvas",
        )


def test_stream_verification_defaults_on_and_honors_workflow_disable():
    assert _verification_should_run(SimpleNamespace()) is True
    assert _verification_should_run(SimpleNamespace(enable_verifier=True)) is True
    assert _verification_should_run(SimpleNamespace(enable_verifier=False)) is False


@pytest.mark.asyncio
async def test_streaming_generation_skips_refiner_for_tldraw_even_when_forced(
    monkeypatch,
    tmp_path,
):
    verifier_calls = []

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            verifier_calls.append(kwargs)
            return SimpleNamespace(objective_findings=[], critique=None)

    class UnexpectedIterativeRefinerWorkflow:
        def run(self, **kwargs):
            raise AssertionError("TLDraw must not enter the Excalidraw-only refiner")

    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        _direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_refiner_streaming_dependency_loader(
            tmp_path,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=UnexpectedIterativeRefinerWorkflow,
            always_refine=True,
        ),
    )

    chunks = await _collect_refiner_stream_chunks(adapter, canvas_library="tldraw")

    assert not any(chunk.startswith("event: refine_error\n") for chunk in chunks)
    assert not any(
        _event_from_sse(chunk) == "stage_start"
        and _data_from_sse(chunk).get("stage") == "refining"
        for chunk in chunks
    )
    refine_complete_chunk = next(
        chunk for chunk in chunks if chunk.startswith("event: refine_complete\n")
    )
    assert _data_from_sse(refine_complete_chunk) == {
        "fixes_applied": 0,
        "status": "skipped",
        "message": PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE,
    }
    result_chunk = next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    result = _data_from_sse(result_chunk)
    assert result["schema_blob"]["elements"][0]["id"] == "base"
    stage_events = [
        (_event_from_sse(chunk), _data_from_sse(chunk))
        for chunk in chunks if _event_from_sse(chunk) in {"stage_start", "stage_complete"}
    ]
    assert [data["stage"] for event, data in stage_events if event == "stage_start"] == [
        "memory", "structure", "styling", "layout", "render", "verification",
    ]
    assert [event for event, data in stage_events if data["stage"] == "verification"] == [
        "stage_start", "stage_complete",
    ]
    assert all(data["total_stages"] == 9 for _, data in stage_events)
    assert len(verifier_calls) == 1
    assert verifier_calls[0]["source_text"] == "A to B"
    assert verifier_calls[0]["canvas_library"] == "tldraw"
    assert "/stream_runs/req_refiner_test/" in verifier_calls[0]["output_dir"]


@pytest.mark.asyncio
async def test_streaming_generation_reports_unconverged_refiner_without_promoting_manifest(
    monkeypatch,
    tmp_path,
):
    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(objective_findings=[], critique=None)

    class UnconvergedIterativeRefinerWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(
                status="reported",
                converged=False,
                termination_reason="max_iterations_exhausted",
                refined_manifest_path=str(tmp_path / "refined_manifest.json"),
                refined_image_path=str(tmp_path / "refined_diagram.png"),
                iteration_logs=[
                    SimpleNamespace(
                        deterministic_edits=[_applied_edit_outcome()],
                        llm_edits=[],
                    ),
                ],
            )

    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        _direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_refiner_streaming_dependency_loader(
            tmp_path,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=UnconvergedIterativeRefinerWorkflow,
            always_refine=True,
        ),
    )

    chunks = await _collect_refiner_stream_chunks(adapter)

    refine_complete = _data_from_sse(
        next(chunk for chunk in chunks if chunk.startswith("event: refine_complete\n"))
    )
    assert refine_complete == {
        "fixes_applied": 0,
        "status": "unresolved",
        "message": (
            "Refiner did not converge (max_iterations_exhausted); "
            "keeping the base diagram."
        ),
    }

    result = _data_from_sse(
        next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    )
    assert result["schema_blob"]["elements"][0]["id"] == "base"


@pytest.mark.asyncio
async def test_streaming_generation_rejects_refined_artifact_that_fails_final_verification(
    monkeypatch,
    tmp_path,
):
    verifier_calls = []

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            verifier_calls.append(kwargs)
            if len(verifier_calls) == 1:
                return SimpleNamespace(objective_findings=[], critique=None)
            return SimpleNamespace(
                objective_findings=[],
                objective_summary={"critical": 1},
                critique=None,
            )

    class ConvergedIterativeRefinerWorkflow:
        def run(self, **kwargs):
            refined_path = tmp_path / "refined_manifest.json"
            refined_path.write_text(
                json.dumps({"elements": [{"id": "refined"}], "edges": []}),
                encoding="utf-8",
            )
            refined_image = tmp_path / "refined_diagram.png"
            refined_image.write_bytes(b"png")
            return SimpleNamespace(
                status="reported",
                converged=True,
                termination_reason="resolved",
                refined_manifest_path=str(refined_path),
                refined_image_path=str(refined_image),
                iteration_logs=[
                    SimpleNamespace(
                        deterministic_edits=[_applied_edit_outcome()],
                        llm_edits=[],
                    ),
                ],
            )

    logger = _RecordingWorkflowLogger()
    monkeypatch.setattr("app.services.workflow_engine_adapter.logger", logger)
    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        _direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_refiner_streaming_dependency_loader(
            tmp_path,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=ConvergedIterativeRefinerWorkflow,
            always_refine=True,
        ),
    )

    chunks = await _collect_refiner_stream_chunks(adapter)

    assert len(verifier_calls) == 2
    assert verifier_calls[0]["source_text"] == "A to B"
    assert verifier_calls[1]["source_text"] == "A to B"
    assert verifier_calls[0]["output_dir"].endswith("/6_verification")
    assert verifier_calls[1]["manifest_path"] == str(
        tmp_path / "refined_manifest.json"
    )
    assert verifier_calls[1]["image_path"] == str(tmp_path / "refined_diagram.png")
    assert verifier_calls[1]["output_dir"].endswith("/8_final_verification")

    refine_error = _data_from_sse(
        next(chunk for chunk in chunks if chunk.startswith("event: refine_error\n"))
    )
    assert refine_error == {
        "message": "Refiner failed",
        "detail": "Auto-refinement could not complete.",
    }
    refine_complete = _data_from_sse(
        next(chunk for chunk in chunks if chunk.startswith("event: refine_complete\n"))
    )
    assert refine_complete == {
        "fixes_applied": 0,
        "status": "failed",
        "message": "Auto-refinement failed; using base diagram.",
    }
    result = _data_from_sse(
        next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    )
    assert result["schema_blob"]["elements"][0]["id"] == "base"
    assert logger.bind_calls[-1] == {
        "request_id": "req_refiner_test",
        "stage": "refining",
        "phase": REFINER_FAILURE_VERIFICATION,
        "error_type": "RefinerPipelineError",
    }


@pytest.mark.asyncio
async def test_streaming_generation_uses_injected_engine_dependencies(
    monkeypatch,
    tmp_path,
):
    loaded = []
    constructed = []
    stage_states = {}
    verifier_seen = {}
    render_seen = {}

    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                lambda state: (
                    stage_states.setdefault("structure", state),
                    SimpleNamespace(
                        structure_instantiation={"nodes": [{"id": "n1"}]},
                        structure_specification={"diagram": "flow"},
                        conversation_history=[],
                    ),
                )[1]
            )
            self.styling = _FakeStage(
                lambda state: (
                    stage_states.setdefault("styling", state),
                    SimpleNamespace(
                        styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                        styling_specification={"visual": "simple"},
                        conversation_history=[],
                    ),
                )[1]
            )
            self.layout = _FakeStage(
                lambda state: (
                    stage_states.setdefault("layout", state),
                    SimpleNamespace(
                        layout_instantiation={"blocks": [{"id": "n1"}]},
                        layout_specification={"anchors": []},
                    ),
                )[1]
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type or "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            constructed.append(kwargs)
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = False

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    def fake_render_manifest(**kwargs):
        render_seen.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return SimpleNamespace(
            manifest={"elements": [{"id": "shape_1"}]},
            png_path=str(output_dir / "diagram.png"),
            manifest_path=str(output_dir / "diagram.json"),
        )

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            verifier_seen.update(kwargs)
            return SimpleNamespace(objective_findings=[], critique=None)

    class UnusedSeverity:
        CRITICAL = "critical"
        MAJOR = "major"

    def load_streaming_dependencies():
        loaded.append(True)
        return StreamingEngineDependencies(
            workflow_cls=FakeWorkflow,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=lambda: pytest.fail("refiner should not run"),
            severity_cls=UnusedSeverity,
            render_manifest=fake_render_manifest,
        )

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.services.workflow_engine_adapter.asyncio.to_thread", direct_to_thread)

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=load_streaming_dependencies,
    )

    chunks = []
    async for chunk in adapter.stream_without_render(
        model="fake-model",
        request=WorkflowRunRequest(
            context="A to B",
            requirements="",
            locked_nodes=["n1"],
            current_schema={"elements": [{"id": "n1"}]},
            canvas_library="excalidraw",
            user_tier=None,
            request_id="req_test",
        ),
    ):
        chunks.append(chunk)

    result_chunk = next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    result = _data_from_sse(result_chunk)
    assert loaded == [True]
    assert constructed[0]["model"] == "fake-model"
    assert constructed[0]["router_model"] == "fake-model"
    assert constructed[0]["save_dir"].endswith("/stream_runs/req_test")
    assert stage_states["structure"].user_query == "Generate diagram schema"
    assert stage_states["styling"].user_query == "Generate diagram schema"
    assert stage_states["layout"].user_query == "Generate diagram schema"
    assert _runtime_directives_payload(stage_states["structure"].runtime_directives) == {
        "locked_nodes": ["n1"],
        "current_schema": {"elements": [{"id": "n1"}]},
    }
    assert render_seen["output_dir"].endswith("/stream_runs/req_test/4_render")
    assert verifier_seen["output_dir"].endswith("/stream_runs/req_test/6_verification")
    assert verifier_seen["structure_path"].endswith(
        "/stream_runs/req_test/1_structure/structure_instantiation.json"
    )
    assert verifier_seen["layout_path"].endswith(
        "/stream_runs/req_test/3_layout/layout_instantiation.json"
    )
    assert result["schema_blob"]["elements"][0]["id"] == "shape_1"
    assert any(chunk.startswith("event: refine_complete\n") for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_generation_honors_structure_chart_type_for_downstream_stages(
    monkeypatch,
    tmp_path,
):
    observed_diagram_types = {}

    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={
                        "chart_type": "timeline",
                        "nodes": [{"id": "n1"}],
                    },
                    structure_specification={"diagram": "timeline"},
                    conversation_history=[],
                )
            )
            self.styling = _FakeStage(
                lambda state: (
                    observed_diagram_types.setdefault("styling", state.diagram_type),
                    SimpleNamespace(
                        styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                        styling_specification={"visual": "simple"},
                        conversation_history=[],
                    ),
                )[1]
            )
            self.layout = _FakeStage(
                lambda state: (
                    observed_diagram_types.setdefault("layout", state.diagram_type),
                    SimpleNamespace(
                        layout_instantiation={"blocks": [{"id": "n1"}]},
                        layout_specification={"anchors": []},
                    ),
                )[1]
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type, "blush_sage"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = False

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(objective_findings=[], critique=None)

    class UnusedSeverity:
        CRITICAL = "critical"
        MAJOR = "major"

    def fake_render_manifest(**kwargs):
        return SimpleNamespace(
            manifest={"elements": [{"id": "shape_1"}], "edges": []},
            png_path=str(tmp_path / "diagram.png"),
            manifest_path=str(tmp_path / "diagram.json"),
        )

    def load_streaming_dependencies():
        return StreamingEngineDependencies(
            workflow_cls=FakeWorkflow,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=lambda: pytest.fail("refiner should not run"),
            severity_cls=UnusedSeverity,
            render_manifest=fake_render_manifest,
        )

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=load_streaming_dependencies,
    )

    chunks = []
    async for chunk in adapter.stream_without_render(
        model="fake-model",
        request=WorkflowRunRequest(
            context="A to B",
            requirements="draw",
            locked_nodes=[],
            current_schema=None,
            canvas_library="excalidraw",
            user_tier=None,
            request_id="req_chart_type",
        ),
    ):
        chunks.append(chunk)

    assert not any(chunk.startswith("event: error\n") for chunk in chunks)
    assert observed_diagram_types == {
        "styling": "timeline",
        "layout": "timeline",
    }


@pytest.mark.asyncio
async def test_streaming_generation_uses_current_pipeline_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODEL_NAME", "offline-test-model")
    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={"nodes": [{"id": "n1"}]},
                    structure_specification={"diagram": "flow"},
                    conversation_history=[{"role": "assistant", "content": "structure"}],
                )
            )
            self.styling = _FakeStage(
                SimpleNamespace(
                    styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                    styling_specification={"visual": "simple"},
                    conversation_history=[{"role": "assistant", "content": "styling"}],
                )
            )
            self.layout = _FakeStage(
                SimpleNamespace(
                    layout_instantiation={"blocks": [{"id": "n1"}]},
                    layout_specification={"anchors": []},
                )
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type or "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = False
            self.provider_config = None

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    def fake_render_manifest(**kwargs):
        return SimpleNamespace(
            manifest={"elements": [{"id": "shape_1"}], "edges": [{"id": "edge_1"}]},
            png_path=str(tmp_path / "diagram.png"),
            manifest_path=str(tmp_path / "diagram.json"),
        )

    monkeypatch.setattr("evo_diagram.agentic_system.workflow.Text2DiagramWorkflow", FakeWorkflow)
    monkeypatch.setattr("evo_diagram.canvas_environment.render_manifest", fake_render_manifest)

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    service = WorkflowGenerateService()
    monkeypatch.setattr(service, "_create_llm", lambda: object())
    monkeypatch.setattr(service.settings, "results_dir", str(tmp_path))
    monkeypatch.setattr("app.services.workflow_engine_adapter.asyncio.to_thread", direct_to_thread)

    chunks = []
    async for chunk in service.generate_without_render_streaming(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier=None,
    ):
        chunks.append(chunk)

    assert not any(chunk.startswith("event: error\n") for chunk in chunks)
    result_chunk = next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    result = _data_from_sse(result_chunk)
    assert result["schema_blob"]["elements"][0]["id"] == "shape_1"
    assert result["metrics_scores"]["node_count"] == 1
    assert result["metrics_scores"]["edge_count"] == 1
    assert result["metrics_scores"]["generation"]["total_duration_ms"] >= 0
    assert any(chunk.startswith("event: refine_complete\n") for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_generation_refiner_uses_current_workflow(monkeypatch, tmp_path):
    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={"nodes": [{"id": "n1"}]},
                    structure_specification={"diagram": "flow"},
                    conversation_history=[{"role": "assistant", "content": "structure"}],
                )
            )
            self.styling = _FakeStage(
                SimpleNamespace(
                    styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                    styling_specification={"visual": "simple"},
                    conversation_history=[{"role": "assistant", "content": "styling"}],
                )
            )
            self.layout = _FakeStage(
                SimpleNamespace(
                    layout_instantiation={"blocks": [{"id": "n1"}]},
                    layout_specification={"anchors": []},
                )
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type or "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = True

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    verifier_calls = []

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            verifier_calls.append(kwargs)
            return SimpleNamespace(objective_findings=[], critique=None)

    refiner_seen = {}

    class FakeIterativeRefinerWorkflow:
        def run(self, **kwargs):
            refiner_seen.update(kwargs)
            refined_path = tmp_path / "refined.json"
            refined_path.write_text(
                json.dumps({"elements": [{"id": "refined"}], "edges": []}),
                encoding="utf-8",
            )
            return SimpleNamespace(
                converged=True,
                termination_reason="resolved",
                refined_manifest_path=str(refined_path),
                refined_image_path=str(tmp_path / "refined.png"),
                iteration_logs=[],
            )

    def fake_render_manifest(**kwargs):
        return SimpleNamespace(
            manifest={"elements": [{"id": "base"}], "edges": []},
            png_path=str(tmp_path / "diagram.png"),
            manifest_path=str(tmp_path / "diagram.json"),
        )

    monkeypatch.setattr("evo_diagram.agentic_system.workflow.Text2DiagramWorkflow", FakeWorkflow)
    monkeypatch.setattr("evo_diagram.canvas_environment.render_manifest", fake_render_manifest)
    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.workflow.VerifierWorkflow",
        FakeVerifierWorkflow,
    )
    monkeypatch.setattr(
        "evo_diagram.agentic_system.iterative_workflow.IterativeRefinerWorkflow",
        FakeIterativeRefinerWorkflow,
    )

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    service = WorkflowGenerateService()
    monkeypatch.setattr(service, "_create_llm", lambda: object())
    monkeypatch.setattr("app.services.workflow_engine_adapter.asyncio.to_thread", direct_to_thread)

    chunks = []
    async for chunk in service.generate_without_render_streaming(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier="pro",
    ):
        chunks.append(chunk)

    assert not any(chunk.startswith("event: error\n") for chunk in chunks)
    result_chunk = next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    result = _data_from_sse(result_chunk)
    assert result["schema_blob"]["elements"][0]["id"] == "refined"

    assert len(verifier_calls) == 2
    base_verification = verifier_calls[0]
    final_verification = verifier_calls[1]
    assert base_verification["canvas_library"] == "excalidraw"
    assert base_verification["source_text"] == "A to B"
    assert base_verification["manifest_path"] == str(tmp_path / "diagram.json")
    assert base_verification["image_path"] == str(tmp_path / "diagram.png")
    assert base_verification["structure_path"].endswith(
        "/1_structure/structure_instantiation.json"
    )
    assert base_verification["layout_path"].endswith("/3_layout/layout_instantiation.json")
    assert base_verification["output_dir"].endswith("/6_verification")
    assert base_verification["skip_critic"] is True
    assert base_verification["emit_markdown"] is True

    assert final_verification["canvas_library"] == "excalidraw"
    assert final_verification["source_text"] == "A to B"
    assert final_verification["manifest_path"] == str(tmp_path / "refined.json")
    assert final_verification["image_path"] == str(tmp_path / "refined.png")
    assert final_verification["structure_path"] == base_verification["structure_path"]
    assert final_verification["layout_path"] == base_verification["layout_path"]
    assert final_verification["output_dir"].endswith("/8_final_verification")
    assert final_verification["skip_critic"] is True
    assert final_verification["emit_markdown"] is True

    assert refiner_seen["canvas_library"] == "excalidraw"
    assert refiner_seen["structure_path"] == base_verification["structure_path"]
    assert refiner_seen["layout_path"] == base_verification["layout_path"]
    assert refiner_seen["verifier_report_path"].endswith(
        "/6_verification/verifier_report.json"
    )
    assert refiner_seen["output_dir"].endswith("/7_refiner")
    assert refiner_seen["max_iterations"] == 2
    assert refiner_seen["emit_markdown"] is True
    assert set(refiner_seen) == {
        "manifest_path",
        "image_path",
        "structure_path",
        "layout_path",
        "verifier_report_path",
        "output_dir",
        "canvas_library",
        "max_iterations",
        "emit_markdown",
        "design_constraints",
    }

    events = [(_event_from_sse(chunk), _data_from_sse(chunk)) for chunk in chunks]
    refining_start_index = next(
        index
        for index, (event, payload) in enumerate(events)
        if event == "stage_start" and payload.get("stage") == "refining"
    )
    refining_complete_index = next(
        index
        for index, (event, payload) in enumerate(events)
        if event == "stage_complete" and payload.get("stage") == "refining"
    )
    refine_complete_index = next(
        index for index, (event, _) in enumerate(events) if event == "refine_complete"
    )
    result_index = next(
        index for index, (event, _) in enumerate(events) if event == "result"
    )

    assert (
        refining_start_index
        < refining_complete_index
        < refine_complete_index
        < result_index
    )
    assert events[refining_start_index][1] == {
        "stage": "refining",
        "stage_index": 7,
        "total_stages": 9,
        "message": "Refiner Agent is fixing visual issues...",
    }
    refining_complete = events[refining_complete_index][1]
    assert refining_complete["stage"] == "refining"
    assert refining_complete["stage_index"] == 7
    assert refining_complete["total_stages"] == 9
    assert refining_complete["message"] == "Refining complete"
    assert isinstance(refining_complete["duration_ms"], int)
    assert events[refine_complete_index][1] == {
        "fixes_applied": 0,
        "status": "completed",
        "message": "Auto-fixed 0 visual issue(s)",
    }


@pytest.mark.asyncio
async def test_streaming_generation_skips_refiner_when_verification_passes(
    monkeypatch,
    tmp_path,
):
    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={"nodes": [{"id": "n1"}]},
                    structure_specification={"diagram": "flow"},
                    conversation_history=[{"role": "assistant", "content": "structure"}],
                )
            )
            self.styling = _FakeStage(
                SimpleNamespace(
                    styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                    styling_specification={"visual": "simple"},
                    conversation_history=[{"role": "assistant", "content": "styling"}],
                )
            )
            self.layout = _FakeStage(
                SimpleNamespace(
                    layout_instantiation={"blocks": [{"id": "n1"}]},
                    layout_specification={"anchors": []},
                )
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type or "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = False

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(objective_findings=[], critique=None)

    class UnexpectedIterativeRefinerWorkflow:
        def run(self, **kwargs):
            raise AssertionError("Refiner should not run when verification passes")

    def fake_render_manifest(**kwargs):
        return SimpleNamespace(
            manifest={"elements": [{"id": "base"}], "edges": []},
            png_path=str(tmp_path / "diagram.png"),
            manifest_path=str(tmp_path / "diagram.json"),
        )

    monkeypatch.setattr("evo_diagram.agentic_system.workflow.Text2DiagramWorkflow", FakeWorkflow)
    monkeypatch.setattr("evo_diagram.canvas_environment.render_manifest", fake_render_manifest)
    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.workflow.VerifierWorkflow",
        FakeVerifierWorkflow,
    )
    monkeypatch.setattr(
        "evo_diagram.agentic_system.iterative_workflow.IterativeRefinerWorkflow",
        UnexpectedIterativeRefinerWorkflow,
    )

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    service = WorkflowGenerateService()
    monkeypatch.setattr(service, "_create_llm", lambda: object())
    monkeypatch.setattr("app.services.workflow_engine_adapter.asyncio.to_thread", direct_to_thread)

    chunks = []
    async for chunk in service.generate_without_render_streaming(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier="pro",
    ):
        chunks.append(chunk)

    assert not any(
        _event_from_sse(chunk) == "stage_start"
        and _data_from_sse(chunk).get("stage") == "refining"
        for chunk in chunks
    )
    refine_complete_chunk = next(
        chunk for chunk in chunks if chunk.startswith("event: refine_complete\n")
    )
    assert _data_from_sse(refine_complete_chunk) == {
        "fixes_applied": 0,
        "status": "skipped",
        "message": "No auto-refinement needed.",
    }
    result_chunk = next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    result = _data_from_sse(result_chunk)
    assert result["schema_blob"]["elements"][0]["id"] == "base"


@pytest.mark.asyncio
async def test_streaming_generation_reports_refiner_failure_as_degraded_terminal_state(
    monkeypatch,
    tmp_path,
):
    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={"nodes": [{"id": "n1"}]},
                    structure_specification={"diagram": "flow"},
                    conversation_history=[{"role": "assistant", "content": "structure"}],
                )
            )
            self.styling = _FakeStage(
                SimpleNamespace(
                    styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                    styling_specification={"visual": "simple"},
                    conversation_history=[{"role": "assistant", "content": "styling"}],
                )
            )
            self.layout = _FakeStage(
                SimpleNamespace(
                    layout_instantiation={"blocks": [{"id": "n1"}]},
                    layout_specification={"anchors": []},
                )
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type or "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = True

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(objective_findings=[], critique=None)

    class FailingIterativeRefinerWorkflow:
        def run(self, **kwargs):
            raise RuntimeError("secret refiner implementation detail")

    def fake_render_manifest(**kwargs):
        return SimpleNamespace(
            manifest={"elements": [{"id": "base"}], "edges": []},
            png_path=str(tmp_path / "diagram.png"),
            manifest_path=str(tmp_path / "diagram.json"),
        )

    monkeypatch.setattr("evo_diagram.agentic_system.workflow.Text2DiagramWorkflow", FakeWorkflow)
    monkeypatch.setattr("evo_diagram.canvas_environment.render_manifest", fake_render_manifest)
    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.workflow.VerifierWorkflow",
        FakeVerifierWorkflow,
    )
    monkeypatch.setattr(
        "evo_diagram.agentic_system.iterative_workflow.IterativeRefinerWorkflow",
        FailingIterativeRefinerWorkflow,
    )

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    service = WorkflowGenerateService()
    monkeypatch.setattr(service, "_create_llm", lambda: object())
    monkeypatch.setattr("app.services.workflow_engine_adapter.asyncio.to_thread", direct_to_thread)

    chunks = []
    async for chunk in service.generate_without_render_streaming(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier="pro",
    ):
        chunks.append(chunk)

    refine_error_chunk = next(
        chunk for chunk in chunks if chunk.startswith("event: refine_error\n")
    )
    refine_error = _data_from_sse(refine_error_chunk)
    assert refine_error == {
        "message": "Refiner failed",
        "detail": "Auto-refinement could not complete.",
    }
    assert "secret" not in refine_error_chunk

    refine_complete_chunk = next(
        chunk for chunk in chunks if chunk.startswith("event: refine_complete\n")
    )
    refine_complete = _data_from_sse(refine_complete_chunk)
    assert refine_complete == {
        "fixes_applied": 0,
        "status": "failed",
        "message": "Auto-refinement failed; using base diagram.",
    }

    refining_stage_completions = [
        _data_from_sse(chunk)
        for chunk in chunks
        if _event_from_sse(chunk) == "stage_complete"
        and _data_from_sse(chunk).get("stage") == "refining"
    ]
    assert refining_stage_completions == []

    result_chunk = next(chunk for chunk in chunks if chunk.startswith("event: result\n"))
    result = _data_from_sse(result_chunk)
    assert result["schema_blob"]["elements"][0]["id"] == "base"


@pytest.mark.asyncio
async def test_streaming_generation_classifies_verification_failure(
    monkeypatch,
    tmp_path,
):
    class FailingVerifierWorkflow:
        def run(self, **kwargs):
            raise RuntimeError("secret verifier implementation detail")

    class UnexpectedIterativeRefinerWorkflow:
        def run(self, **kwargs):
            raise AssertionError("Refiner should not run after verification failure")

    logger = _RecordingWorkflowLogger()
    monkeypatch.setattr("app.services.workflow_engine_adapter.logger", logger)
    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        _direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_refiner_streaming_dependency_loader(
            tmp_path,
            verifier_workflow_cls=FailingVerifierWorkflow,
            iterative_refiner_workflow_cls=UnexpectedIterativeRefinerWorkflow,
        ),
    )

    chunks = await _collect_refiner_stream_chunks(adapter)

    _assert_stream_verification_failure_contract(chunks)
    verification_events = [
        _event_from_sse(chunk) for chunk in chunks
        if _data_from_sse(chunk).get("stage") == "verification"
    ]
    assert verification_events == ["stage_start", "error"]
    assert "secret" not in "".join(chunks)
    assert not any(
        _event_from_sse(chunk) == "stage_start"
        and _data_from_sse(chunk).get("stage") == "refining"
        for chunk in chunks
    )
    assert logger.error_messages == ["Streaming verification failed"]
    assert logger.bind_calls[-1] == {
        "request_id": "req_refiner_test",
        "stage": "verification",
        "error_type": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_streaming_generation_stops_when_non_refiner_verification_fails(
    monkeypatch,
    tmp_path,
):
    class FailingVerifierWorkflow:
        def run(self, **kwargs):
            raise RuntimeError("secret verifier implementation detail")

    class UnexpectedIterativeRefinerWorkflow:
        def run(self, **kwargs):
            raise AssertionError("Refiner should not run without a refiner request")

    logger = _RecordingWorkflowLogger()
    monkeypatch.setattr("app.services.workflow_engine_adapter.logger", logger)
    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        _direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_refiner_streaming_dependency_loader(
            tmp_path,
            verifier_workflow_cls=FailingVerifierWorkflow,
            iterative_refiner_workflow_cls=UnexpectedIterativeRefinerWorkflow,
        ),
    )

    chunks = []
    async for chunk in adapter.stream_without_render(
        model="fake-model",
        request=WorkflowRunRequest(
            context="A to B",
            requirements="draw",
            locked_nodes=[],
            current_schema=None,
            canvas_library="excalidraw",
            user_tier=None,
            request_id="req_verifier_failure",
        ),
    ):
        chunks.append(chunk)

    _assert_stream_verification_failure_contract(chunks)
    assert "secret" not in "".join(chunks)
    assert logger.error_messages == ["Streaming verification failed"]
    assert logger.bind_calls[-1] == {
        "request_id": "req_verifier_failure",
        "stage": "verification",
        "error_type": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_streaming_generation_classifies_refiner_failed_status(
    monkeypatch,
    tmp_path,
):
    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(objective_findings=[], critique=None)

    class FailedStatusIterativeRefinerWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(
                status="failed",
                errors=["secret refiner status detail"],
                refined_manifest_path=None,
                refined_image_path=None,
                iteration_logs=[],
            )

    logger = _RecordingWorkflowLogger()
    monkeypatch.setattr("app.services.workflow_engine_adapter.logger", logger)
    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        _direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_refiner_streaming_dependency_loader(
            tmp_path,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=FailedStatusIterativeRefinerWorkflow,
        ),
    )

    chunks = await _collect_refiner_stream_chunks(adapter)

    _assert_degraded_refiner_public_contract(chunks)
    assert "secret" not in "".join(chunks)
    assert any(
        _event_from_sse(chunk) == "stage_start"
        and _data_from_sse(chunk).get("stage") == "refining"
        for chunk in chunks
    )
    assert not any(
        _event_from_sse(chunk) == "stage_complete"
        and _data_from_sse(chunk).get("stage") == "refining"
        for chunk in chunks
    )
    assert logger.bind_calls[-1] == {
        "request_id": "req_refiner_test",
        "stage": "refining",
        "phase": REFINER_FAILURE_EXECUTION,
        "error_type": "RefinerExecutionStatusError",
    }


@pytest.mark.asyncio
async def test_streaming_generation_classifies_invalid_refined_artifact(
    monkeypatch,
    tmp_path,
):
    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(objective_findings=[], critique=None)

    class InvalidArtifactIterativeRefinerWorkflow:
        def run(self, **kwargs):
            refined_path = tmp_path / "refined.json"
            refined_path.write_text("{not-json", encoding="utf-8")
            return SimpleNamespace(
                converged=True,
                termination_reason="resolved",
                refined_manifest_path=str(refined_path),
                refined_image_path=str(tmp_path / "refined.png"),
                iteration_logs=[],
            )

    logger = _RecordingWorkflowLogger()
    monkeypatch.setattr("app.services.workflow_engine_adapter.logger", logger)
    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        _direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_refiner_streaming_dependency_loader(
            tmp_path,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=InvalidArtifactIterativeRefinerWorkflow,
        ),
    )

    chunks = await _collect_refiner_stream_chunks(adapter)

    _assert_degraded_refiner_public_contract(chunks)
    assert not any(
        _event_from_sse(chunk) == "stage_complete"
        and _data_from_sse(chunk).get("stage") == "refining"
        for chunk in chunks
    )
    assert logger.bind_calls[-1] == {
        "request_id": "req_refiner_test",
        "stage": "refining",
        "phase": REFINER_FAILURE_ARTIFACT,
        "error_type": "JSONDecodeError",
    }


@pytest.mark.asyncio
async def test_streaming_generation_hides_stage_exception_details(monkeypatch, tmp_path):
    def fail_structure(state):
        raise RuntimeError("secret provider token leaked in stack")

    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(fail_structure)
            self.styling = _FakeStage(None)
            self.layout = _FakeStage(None)

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = False

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("evo_diagram.agentic_system.workflow.Text2DiagramWorkflow", FakeWorkflow)
    monkeypatch.setattr("app.services.workflow_engine_adapter.asyncio.to_thread", direct_to_thread)

    service = WorkflowGenerateService()
    monkeypatch.setattr(service, "_create_llm", lambda: object())
    monkeypatch.setattr(service.settings, "results_dir", str(tmp_path))

    chunks = []
    async for chunk in service.generate_without_render_streaming(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier=None,
    ):
        chunks.append(chunk)

    error_chunk = next(chunk for chunk in chunks if chunk.startswith("event: error\n"))
    error = _data_from_sse(error_chunk)

    assert error["stage"] == "structure"
    assert error["message"] == "Diagram generation failed"
    assert error["detail"] == "The diagram generation stage failed."
    assert "secret" not in error_chunk


@pytest.mark.asyncio
async def test_streaming_generation_reports_render_stage_failures(monkeypatch, tmp_path):
    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={"nodes": [{"id": "n1"}]},
                    structure_specification={"diagram": "flow"},
                    conversation_history=[{"role": "assistant", "content": "structure"}],
                )
            )
            self.styling = _FakeStage(
                SimpleNamespace(
                    styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                    styling_specification={"visual": "simple"},
                    conversation_history=[{"role": "assistant", "content": "styling"}],
                )
            )
            self.layout = _FakeStage(
                SimpleNamespace(
                    layout_instantiation={"blocks": [{"id": "n1"}]},
                    layout_specification={"anchors": []},
                )
            )

        def resolve_generation_context(self, text_content, user_query, diagram_type=None):
            return diagram_type or "flowchart", "blush_sage"

        def build_stage_context(self, stage_name, diagram_type):
            return f"{stage_name}:{diagram_type}"

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = False

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    def fail_render_manifest(**kwargs):
        raise RuntimeError("secret render token leaked")

    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("evo_diagram.agentic_system.workflow.Text2DiagramWorkflow", FakeWorkflow)
    monkeypatch.setattr("evo_diagram.canvas_environment.render_manifest", fail_render_manifest)
    monkeypatch.setattr("app.services.workflow_engine_adapter.asyncio.to_thread", direct_to_thread)

    service = WorkflowGenerateService()
    monkeypatch.setattr(service, "_create_llm", lambda: object())
    monkeypatch.setattr(service.settings, "results_dir", str(tmp_path))

    chunks = []
    async for chunk in service.generate_without_render_streaming(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier=None,
    ):
        chunks.append(chunk)

    error_chunk = next(chunk for chunk in chunks if chunk.startswith("event: error\n"))
    error = _data_from_sse(error_chunk)

    assert error["stage"] == "render"
    assert error["message"] == "Diagram generation failed"
    assert "secret" not in error_chunk
    assert not any(
        _event_from_sse(chunk) == "stage_complete"
        and _data_from_sse(chunk).get("stage") == "render"
        for chunk in chunks
    )


def _cleanup_streaming_dependency_loader():
    """Minimal streaming engine fakes that write into the request workdir."""

    class FakeGenerator(_FakePipelineGeneratorMixin):
        def __init__(self):
            self.structure = _FakeStage(
                SimpleNamespace(
                    structure_instantiation={"nodes": [{"id": "n1"}]},
                    structure_specification={"diagram": "flow"},
                    conversation_history=[],
                )
            )
            self.styling = _FakeStage(
                SimpleNamespace(
                    styling_instantiation={"styles": {"n1": {"fill": "#fff"}}},
                    styling_specification={"visual": "simple"},
                    conversation_history=[],
                )
            )
            self.layout = _FakeStage(
                SimpleNamespace(
                    layout_instantiation={"blocks": [{"id": "n1"}]},
                    layout_specification={"anchors": []},
                )
            )

    class FakeWorkflow(_FakeWorkflowStepwiseMixin):
        def __init__(self, **kwargs):
            Path(kwargs["save_dir"]).mkdir(parents=True, exist_ok=True)
            self.generator = FakeGenerator()
            self.enable_critic = False
            self.always_refine = False

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **kwargs):
            return design_expertise

    def fake_render_manifest(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "diagram.png").write_bytes(b"png-bytes")
        return SimpleNamespace(
            manifest={"elements": [{"id": "shape_1"}]},
            png_path=str(output_dir / "diagram.png"),
            manifest_path=str(output_dir / "diagram.json"),
        )

    class FakeVerifierWorkflow:
        def run(self, **kwargs):
            return SimpleNamespace(objective_findings=[], critique=None)

    class UnusedSeverity:
        CRITICAL = "critical"
        MAJOR = "major"

    def load_streaming_dependencies():
        return StreamingEngineDependencies(
            workflow_cls=FakeWorkflow,
            verifier_workflow_cls=FakeVerifierWorkflow,
            iterative_refiner_workflow_cls=lambda: pytest.fail("refiner should not run"),
            severity_cls=UnusedSeverity,
            render_manifest=fake_render_manifest,
        )

    return load_streaming_dependencies


def _cleanup_stream_request(request_id: str) -> WorkflowRunRequest:
    return WorkflowRunRequest(
        context="A to B",
        requirements="draw",
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier=None,
        request_id=request_id,
    )


@pytest.mark.asyncio
async def test_streaming_generation_removes_its_request_scoped_workdir(
    monkeypatch,
    tmp_path,
):
    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_cleanup_streaming_dependency_loader(),
    )
    stream_dir = Path(_request_scoped_stream_dir(str(tmp_path), "req_cleanup"))

    chunks = []
    async for chunk in adapter.stream_without_render(
        model="fake-model",
        request=_cleanup_stream_request("req_cleanup"),
    ):
        chunks.append(chunk)

    assert any(chunk.startswith("event: result\n") for chunk in chunks)
    assert not stream_dir.exists()


@pytest.mark.asyncio
async def test_streaming_generation_removes_its_workdir_when_the_client_leaves(
    monkeypatch,
    tmp_path,
):
    async def direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.workflow_engine_adapter.asyncio.to_thread",
        direct_to_thread,
    )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=_cleanup_streaming_dependency_loader(),
    )
    stream_dir = Path(_request_scoped_stream_dir(str(tmp_path), "req_abandoned"))

    stream = adapter.stream_without_render(
        model="fake-model",
        request=_cleanup_stream_request("req_abandoned"),
    )
    async for chunk in stream:
        if '"stage": "structure"' in chunk:
            break

    assert stream_dir.exists()

    await stream.aclose()

    assert not stream_dir.exists()
