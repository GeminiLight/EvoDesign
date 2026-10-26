"""Smoke test: exercise the full orchestrator wiring WITHOUT calling real LLMs.

Run:  python -m pytest tests/pipeline/ -v
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

MOCK_STRUCTURE = {
    "chart_type": "flowchart",
    "nodes": [{"id": "n1", "label": "A", "class": "Concept"}],
    "edges": [],
    "groups": [],
}
MOCK_STYLING = {
    "n1": {
        "shape": "rectangle",
        "label": {"text": "A"},
        "strokeColor": "#1565C0",
        "backgroundColor": "#BBDEFB",
    }
}
MOCK_LAYOUT = {"n1": {"x": 100, "y": 200, "w": 150, "h": 80}}
MOCK_MANIFEST = {"type": "excalidraw", "version": 2, "elements": [], "appState": {}, "files": {}}


def _mock_styling_for_canvas(canvas_library: str = "excalidraw"):
    if canvas_library == "tldraw":
        return {
            "n1": {
                "type": "geo",
                "props": {
                    "geo": "rectangle",
                    "color": "blue",
                    "fill": "solid",
                    "text": "A",
                },
            }
        }
    return MOCK_STYLING


def _mock_model():
    m = MagicMock()
    m.invoke.return_value = MagicMock(
        content='{"chart_type":"flowchart","nodes":[],"edges":[],"groups":[]}'
    )
    m.bind_tools.return_value = m
    return m


def _gen_mocks(canvas_library: str = "excalidraw"):
    """Return a mock GeneratorWorkflow whose run() returns pipeline outputs."""
    gen = MagicMock()
    gen.run.return_value = {
        "structure_instantiation": MOCK_STRUCTURE,
        "structure_specification": {},
        "styling_instantiation": _mock_styling_for_canvas(canvas_library),
        "styling_specification": {},
        "layout_instantiation": MOCK_LAYOUT,
        "layout_specification": {},
    }
    return gen


def _render_result():
    from evo_diagram.canvas_environment import RenderResult
    png_path = Path("/tmp/evodiagram-test-render.png")
    manifest_path = Path("/tmp/evodiagram-test-render.json")
    png_path.write_bytes(b"png")
    manifest_path.write_text("{}", encoding="utf-8")
    return RenderResult(
        manifest=MOCK_MANIFEST,
        png_path=str(png_path),
        manifest_path=str(manifest_path),
    )


def _verifier_state():
    vs = MagicMock(); vs.status = "completed"; vs.objective_findings = []; vs.critique = None
    vs.report_path = None
    return vs


class TestPipelineSmoke:

    def test_full_pipeline_runs(self):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = _gen_mocks()
        vf = MagicMock(); vf.run.return_value = _verifier_state()
        rf = MagicMock(); rs = MagicMock()
        rs.status = "completed"; rs.current_iteration = 0
        rs.refined_manifest_path = None; rs.refined_image_path = None
        rf.run.return_value = rs

        with (
            patch.object(m, "create_generator", return_value=gen),
            patch.object(m, "render_manifest", return_value=_render_result()),
            patch.object(m, "VerifierWorkflow", return_value=vf),
            patch.object(m, "IterativeRefinerWorkflow", return_value=rf),
        ):
            wf = Text2DiagramWorkflow(model=_mock_model(), enable_refiner=True, enable_critic=False)
            state = wf.run(text_content="A flows to B", user_query="draw a flowchart")

        assert state.structure_instantiation == MOCK_STRUCTURE
        assert state.styling_instantiation == MOCK_STYLING
        assert state.layout_instantiation == MOCK_LAYOUT
        assert state.diagram_manifest == MOCK_MANIFEST

    def test_unconverged_refiner_artifacts_are_not_promoted(self, tmp_path):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = _gen_mocks()
        vf = MagicMock(); vf.run.return_value = _verifier_state()
        refined_manifest_path = tmp_path / "refined_manifest.json"
        refined_png_path = tmp_path / "refined_diagram.png"
        refined_manifest_path.write_text(
            '{"type":"excalidraw","elements":[{"id":"refined"}]}',
            encoding="utf-8",
        )
        refined_png_path.write_bytes(b"png")

        rf = MagicMock()
        rs = MagicMock()
        rs.status = "reported"
        rs.current_iteration = 1
        rs.converged = False
        rs.termination_reason = "fixed_point_unresolved"
        rs.refined_manifest_path = str(refined_manifest_path)
        rs.refined_image_path = str(refined_png_path)
        rs.refiner_report_path = str(tmp_path / "refiner_report.json")
        rs.latest_findings = []
        rf.run.return_value = rs

        with (
            patch.object(m, "create_generator", return_value=gen),
            patch.object(m, "render_manifest", return_value=_render_result()),
            patch.object(m, "VerifierWorkflow", return_value=vf),
            patch.object(m, "IterativeRefinerWorkflow", return_value=rf),
        ):
            wf = Text2DiagramWorkflow(model=_mock_model(), enable_refiner=True, enable_critic=False, always_refine=True)
            state = wf.run(text_content="A flows to B", user_query="draw a flowchart")

        assert state.refiner_status == "reported"
        assert state.refiner_converged is False
        assert state.refiner_termination_reason == "fixed_point_unresolved"
        assert state.refined_diagram_manifest is None
        assert state.refined_manifest_path is None
        assert state.refined_png_path is None
        assert state.final_diagram_manifest == MOCK_MANIFEST

    def test_verification_only_mode(self):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = _gen_mocks()
        vf = MagicMock(); vf.run.return_value = _verifier_state()

        with (
            patch.object(m, "create_generator", return_value=gen),
            patch.object(m, "render_manifest", return_value=_render_result()),
            patch.object(m, "VerifierWorkflow", return_value=vf),
        ):
            wf = Text2DiagramWorkflow(model=_mock_model(), verification_only=True, enable_critic=False)
            state = wf.run(text_content="A flows to B", user_query="draw a flowchart")

        assert state.refined_diagram_manifest is None

    def test_oneshot_pipeline_uses_render_result_contract(self, tmp_path):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = MagicMock()
        gen.run.return_value = {
            "structure_instantiation": MOCK_STRUCTURE,
            "diagram_manifest": MOCK_MANIFEST,
        }
        seen = {}

        def fake_render_png_result(manifest, output_path, *, canvas_library):
            seen["manifest"] = manifest
            seen["output_path"] = output_path
            seen["canvas_library"] = canvas_library
            Path(output_path).write_bytes(b"png")
            return SimpleNamespace(ok=True, error="")

        with (
            patch.object(m, "create_generator", return_value=gen),
            patch.object(m, "render_png_result", side_effect=fake_render_png_result),
        ):
            wf = Text2DiagramWorkflow(
                model=_mock_model(),
                mode="oneshot",
                enable_verifier=False,
            )
            state = wf.run(
                text_content="A flows to B",
                user_query="draw a flowchart",
                save_dir=str(tmp_path),
            )

        assert seen["manifest"] == MOCK_MANIFEST
        assert seen["canvas_library"] == "excalidraw"
        assert seen["output_path"].endswith("4_render/diagram_manifest.png")
        assert state.diagram_manifest == MOCK_MANIFEST
        assert state.structure_instantiation == MOCK_STRUCTURE
        assert state.final_diagram_manifest == MOCK_MANIFEST
        assert state.artifact_paths["render_manifest_path"].endswith("4_render/diagram_manifest.json")
        assert state.artifact_paths["render_png_path"].endswith("4_render/diagram_manifest.png")
        assert Path(state.final_manifest_path).exists()
        assert Path(state.final_png_path).exists()

    def test_oneshot_render_failure_preserves_renderer_detail(self, tmp_path):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = MagicMock()
        gen.run.return_value = {
            "structure_instantiation": MOCK_STRUCTURE,
            "diagram_manifest": MOCK_MANIFEST,
        }

        with (
            patch.object(m, "create_generator", return_value=gen),
            patch.object(
                m,
                "render_png_result",
                return_value=SimpleNamespace(
                    ok=False,
                    error="RuntimeError: renderer stderr tail",
                ),
            ),
        ):
            wf = Text2DiagramWorkflow(
                model=_mock_model(),
                mode="oneshot",
                enable_verifier=False,
            )
            with pytest.raises(RuntimeError, match="renderer stderr tail"):
                wf.run(
                    text_content="A flows to B",
                    user_query="draw a flowchart",
                    save_dir=str(tmp_path),
                )

    def test_workflow_state_fields(self):
        from evo_diagram.agentic_system.workflow import WorkflowState
        s = WorkflowState(text_content="t", user_query="q")
        for f in [
            "structure_instantiation", "styling_instantiation", "layout_instantiation",
            "diagram_manifest", "png_path", "refined_diagram_manifest", "refined_png_path",
        ]:
            assert hasattr(s, f)

    def test_legacy_pipeline_mode_is_rejected(self):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        with patch.object(m, "create_generator", return_value=MagicMock()):
            with pytest.raises(ValueError, match="Unknown generation mode"):
                Text2DiagramWorkflow(
                    model=_mock_model(),
                    mode="pipeline",
                    enable_verifier=False,
                )

    def test_oneshot_rejects_non_excalidraw_canvas(self):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow

        with pytest.raises(ValueError, match="oneshot.*Excalidraw"):
            Text2DiagramWorkflow(
                model=_mock_model(),
                mode="oneshot",
                canvas_library="tldraw",
            )

    def test_explicit_none_save_dir_uses_temp_work_dir(self):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = _gen_mocks()
        vf = MagicMock(); vf.run.return_value = _verifier_state()
        seen = {}

        def fake_render_manifest(*, output_dir, **kwargs):
            seen["output_dir"] = output_dir
            from evo_diagram.canvas_environment import RenderResult

            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            png_path = out / "diagram_manifest.png"
            manifest_path = out / "diagram_manifest.json"
            png_path.write_bytes(b"png")
            manifest_path.write_text("{}", encoding="utf-8")
            return RenderResult(
                manifest=MOCK_MANIFEST,
                png_path=str(png_path),
                manifest_path=str(manifest_path),
            )

        with (
            patch.object(m, "create_generator", return_value=gen),
            patch.object(m, "render_manifest", side_effect=fake_render_manifest),
            patch.object(m, "VerifierWorkflow", return_value=vf),
        ):
            wf = Text2DiagramWorkflow(model=_mock_model(), enable_critic=False)
            state = wf.run(
                text_content="A flows to B",
                user_query="draw a flowchart",
                save_dir=None,
            )

        assert "None/4_render" not in seen["output_dir"]
        assert seen["output_dir"].endswith("4_render")
        assert not Path(seen["output_dir"]).parent.exists()
        assert state.png_path is None

    def test_config_canvas_library_flows_to_generator_render_without_refiner(self):
        from evo_diagram.agentic_system.config import AgenticSystemConfig
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = _gen_mocks()
        vf = MagicMock(); vf.run.return_value = _verifier_state()
        rf = MagicMock(); rs = MagicMock()
        rs.status = "completed"; rs.current_iteration = 1
        rs.refined_manifest_path = None; rs.refined_image_path = None
        rf.run.return_value = rs
        seen = {}

        def fake_create_generator(mode, model, **kwargs):
            seen["generator_canvas"] = kwargs["canvas_library"]
            nonlocal gen
            gen = _gen_mocks(kwargs["canvas_library"])
            return gen

        def fake_render_manifest(*, canvas_library, **kwargs):
            seen["render_canvas"] = canvas_library
            return _render_result()

        with (
            patch.object(m, "create_generator", side_effect=fake_create_generator),
            patch.object(m, "render_manifest", side_effect=fake_render_manifest),
            patch.object(m, "VerifierWorkflow", return_value=vf),
            patch.object(m, "IterativeRefinerWorkflow", return_value=rf),
        ):
            config = AgenticSystemConfig(
                canvas_library="tldraw",
                enable_refiner=False,
            )
            wf = Text2DiagramWorkflow(model=_mock_model(), config=config)
            wf.run(text_content="A flows to B", user_query="draw a flowchart")

        assert wf.canvas_library == "tldraw"
        assert seen == {
            "generator_canvas": "tldraw",
            "render_canvas": "tldraw",
        }
        rf.run.assert_not_called()

    def test_direct_tldraw_refiner_request_is_rejected_at_initialization(self):
        from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
        import evo_diagram.agentic_system.workflow as m

        gen = _gen_mocks()

        with patch.object(m, "create_generator", return_value=gen):
            with pytest.raises(ValueError, match="iterative refiner.*Excalidraw"):
                Text2DiagramWorkflow(
                    model=_mock_model(),
                    canvas_library="tldraw",
                    enable_refiner=True,
                    enable_verifier=False,
                )
