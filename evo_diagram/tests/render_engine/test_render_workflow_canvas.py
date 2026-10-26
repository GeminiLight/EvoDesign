"""Canvas-library contract tests for the render workflow boundary."""

from __future__ import annotations

import base64

import pytest


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_render_workflow_normalizes_and_rejects_canvas_library():
    from evo_diagram.agentic_system.render_engine.workflow import RenderWorkflow

    workflow = RenderWorkflow(canvas_library=" Excalidraw ")
    assert workflow.canvas_library == "excalidraw"
    assert not hasattr(workflow, "_results_dir")

    with pytest.raises(ValueError, match="Unknown canvas_library"):
        RenderWorkflow(canvas_library="bad-canvas")


def test_render_workflow_run_invokes_graph_and_returns_state():
    from evo_diagram.agentic_system.render_engine.state import WorkflowState
    from evo_diagram.agentic_system.render_engine.workflow import RenderWorkflow

    class FakeGraph:
        def invoke(self, state):
            return {
                **state.model_dump(),
                "current_stage": "validate",
                "diagram_manifest": {"document": {"id": "doc"}},
            }

    workflow = RenderWorkflow(canvas_library="tldraw")
    workflow.graph = FakeGraph()

    result = workflow.run(WorkflowState(layout_instantiation={}, structure_instantiation={}))

    assert isinstance(result, WorkflowState)
    assert result.current_stage == "validate"
    assert result.diagram_manifest == {"document": {"id": "doc"}}


def test_render_service_passes_normalized_canvas_to_workflow_state(monkeypatch, tmp_path):
    from evo_diagram.agentic_system.render_engine import service

    seen = {}

    class FakeRenderWorkflow:
        def __init__(self, canvas_library):
            seen["workflow_canvas"] = canvas_library

        def run(self, state):
            seen["state_canvas"] = state.canvas_library
            state.diagram_manifest = {"document": {"id": "doc"}}
            return state

    def fake_render_canvas(*, data, output_path, canvas_library, **kwargs):
        seen["render_canvas"] = canvas_library
        seen["render_data"] = data
        seen["render_output_path"] = output_path
        with open(output_path, "wb") as f:
            f.write(_PNG_1X1)
        return {"output_path": output_path}

    monkeypatch.setattr(service, "RenderWorkflow", FakeRenderWorkflow)
    monkeypatch.setattr(service, "render_canvas", fake_render_canvas)

    result = service.render_manifest(
        layout_instantiation={},
        structure_instantiation={},
        canvas_library=" TLDraw ",
        output_dir=str(tmp_path),
    )

    assert seen["workflow_canvas"] == "tldraw"
    assert seen["state_canvas"] == "tldraw"
    assert seen["render_canvas"] == "tldraw"
    assert seen["render_data"] == {"document": {"id": "doc"}}
    assert result.manifest == {"document": {"id": "doc"}}
    assert result.png_path == str(tmp_path / "diagram_manifest.png")


def test_render_service_uses_unique_temp_dir_when_output_dir_omitted(monkeypatch, tmp_path):
    from evo_diagram.agentic_system.render_engine import service

    generated_dir = tmp_path / "generated-render"
    seen = {}

    class FakeRenderWorkflow:
        def __init__(self, canvas_library):
            seen["workflow_canvas"] = canvas_library

        def run(self, state):
            state.diagram_manifest = {"elements": [{"id": "n1"}]}
            return state

    def fake_render_canvas(*, output_path, canvas_library, **_kwargs):
        seen["output_path"] = output_path
        seen["canvas_library"] = canvas_library
        with open(output_path, "wb") as f:
            f.write(_PNG_1X1)

    monkeypatch.setattr(service, "RenderWorkflow", FakeRenderWorkflow)
    monkeypatch.setattr(service, "render_canvas", fake_render_canvas)
    monkeypatch.setattr(
        service.tempfile,
        "mkdtemp",
        lambda *, prefix: str(generated_dir),
    )

    result = service.render_manifest(
        layout_instantiation={},
        structure_instantiation={},
        output_dir=None,
    )

    assert result.manifest_path == str(generated_dir / "diagram_manifest.json")
    assert result.png_path == str(generated_dir / "diagram_manifest.png")
    assert seen["output_path"] == result.png_path
    assert seen["canvas_library"] == "excalidraw"
    assert (generated_dir / "rendered_diagram.excalidraw").exists()
    import json
    exported = json.loads((generated_dir / "rendered_diagram.excalidraw").read_text())
    assert exported["type"] == "excalidraw"
    assert exported["version"] == 2


def test_render_workflow_state_rejects_missing_stage_manifest():
    from evo_diagram.agentic_system.render_engine.state import WorkflowState

    state = WorkflowState(
        layout_instantiation={},
        structure_instantiation={},
    )

    with pytest.raises(ValueError, match="stage 'arrow'.*manifest dict"):
        state.update_stage("arrow", {})


def test_render_workflow_state_rejects_invalid_stage_manifest():
    from evo_diagram.agentic_system.render_engine.state import WorkflowState

    state = WorkflowState(
        layout_instantiation={},
        structure_instantiation={},
        diagram_manifest={"elements": [{"id": "old"}]},
    )

    with pytest.raises(ValueError, match="invalid manifest"):
        state.update_stage("fit_groups", {"manifest": {}})

    assert state.diagram_manifest == {"elements": [{"id": "old"}]}


def test_render_workflow_state_uses_shared_stage_constants():
    from evo_diagram.agentic_system.render_engine import stages
    from evo_diagram.agentic_system.render_engine.state import WorkflowState

    state = WorkflowState(
        layout_instantiation={},
        structure_instantiation={},
    )

    state.update_stage(stages.CONVERT, {"manifest": {"elements": []}})

    assert state.current_stage == stages.CONVERT
    assert state.diagram_manifest == {"elements": []}
    assert stages.CONVERT in stages.MANIFEST_STAGES
    assert stages.VALIDATE not in stages.MANIFEST_STAGES


def test_render_workflow_blocks_arrow_coverage_audit_only():
    from evo_diagram.agentic_system.render_engine.shared.render_audit import AuditIssue, AuditReport
    from evo_diagram.agentic_system.render_engine.workflow import _raise_on_blocking_render_audit

    _raise_on_blocking_render_audit(
        AuditReport(issues=[AuditIssue(category="empty_text", message="empty title")]),
        canvas_library="TLDraw",
    )

    with pytest.raises(RuntimeError, match="structure edges were not faithfully rendered"):
        _raise_on_blocking_render_audit(
            AuditReport(issues=[AuditIssue(category="arrow_coverage", message="missing e1")]),
            canvas_library="TLDraw",
        )


def test_render_png_result_rejects_unknown_canvas_before_render(monkeypatch, tmp_path):
    from evo_diagram.agentic_system.render_engine import service

    def fail_render_canvas(**kwargs):
        raise AssertionError("render_canvas should not be called")

    monkeypatch.setattr(service, "render_canvas", fail_render_canvas)

    with pytest.raises(ValueError, match="Unknown canvas_library"):
        service.render_png_result(
            manifest={"elements": []},
            output_path=str(tmp_path / "out.png"),
            canvas_library="bad-canvas",
        )


def test_render_png_result_preserves_renderer_error_detail(monkeypatch, tmp_path):
    from evo_diagram.agentic_system.render_engine import service

    def fail_render_canvas(**_kwargs):
        raise RuntimeError("renderer stderr tail")

    monkeypatch.setattr(service, "render_canvas", fail_render_canvas)

    result = service.render_png_result(
        manifest={"elements": []},
        output_path=str(tmp_path / "out.png"),
        canvas_library="excalidraw",
    )

    assert result.ok is False
    assert result.output_path == str(tmp_path / "out.png")
    assert result.error == "RuntimeError: renderer stderr tail"
