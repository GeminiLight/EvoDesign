"""Top-level workflow temp-directory path hygiene tests."""

from __future__ import annotations

import pytest


def test_clear_temp_paths_removes_only_temp_artifacts(tmp_path):
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow, WorkflowState, _RunDirectories

    temp_dir = tmp_path / "tmp-run"
    final_dir = tmp_path / "final"
    temp_dir.mkdir()
    final_dir.mkdir()

    state = WorkflowState(
        text_content="content",
        user_query="query",
        manifest_path=str(temp_dir / "4_render" / "diagram_manifest.json"),
        png_path=str(temp_dir / "4_render" / "diagram_manifest.png"),
        refined_manifest_path=str(temp_dir / "7_refiner" / "refined_manifest.json"),
        refined_png_path=str(temp_dir / "7_refiner" / "refined.png"),
        verification_report_path=str(temp_dir / "6_verification" / "report.json"),
        refiner_report_path=str(temp_dir / "7_refiner" / "refiner_report.json"),
        final_manifest_path=str(final_dir / "final_diagram_manifest.json"),
        final_png_path=str(final_dir / "rendered_diagram.png"),
        artifact_paths={
            "render_manifest_path": str(temp_dir / "4_render" / "diagram_manifest.json"),
            "verification_report_path": str(temp_dir / "6_verification" / "report.json"),
            "final_manifest_path": str(final_dir / "final_diagram_manifest.json"),
        },
    )

    Text2DiagramWorkflow._clear_temp_paths(
        state,
        _RunDirectories(
            save_dir=str(temp_dir),
            final_dir=str(final_dir),
            temp_dir=None,
        ),
    )

    assert state.manifest_path is None
    assert state.png_path is None
    assert state.refined_manifest_path is None
    assert state.refined_png_path is None
    assert state.verification_report_path is None
    assert state.refiner_report_path is None
    assert state.final_manifest_path == str(final_dir / "final_diagram_manifest.json")
    assert state.final_png_path == str(final_dir / "rendered_diagram.png")
    assert state.artifact_paths == {
        "final_manifest_path": str(final_dir / "final_diagram_manifest.json"),
    }


def test_workflow_default_save_dir_uses_repo_experiments(monkeypatch):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow
    from evo_diagram.utils.path_manager import EXPERIMENTS_DIR

    monkeypatch.setattr(workflow_module, "create_generator", lambda *args, **kwargs: object())

    workflow = Text2DiagramWorkflow(
        object(),
        enable_verifier=False,
    )

    assert workflow.save_dir == str(EXPERIMENTS_DIR)


def test_temp_dir_is_cleaned_when_workflow_raises(tmp_path):
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow, _RunDirectories

    class FakeTempDir:
        def __init__(self, name):
            self.name = name
            self.cleaned = False

        def cleanup(self):
            self.cleaned = True

    temp_dir = tmp_path / "temp-run"
    temp_dir.mkdir()
    fake_temp = FakeTempDir(str(temp_dir))
    workflow = object.__new__(Text2DiagramWorkflow)

    workflow._resolve_run_directories = lambda save_dir, final_dir: _RunDirectories(
        save_dir=str(temp_dir),
        final_dir=None,
        temp_dir=fake_temp,
    )

    def failing_generation(**_kwargs):
        raise RuntimeError("generation failed")

    workflow._run_generation_phase = failing_generation

    with pytest.raises(RuntimeError, match="generation failed"):
        workflow.run("content", "query", save_dir=None)

    assert fake_temp.cleaned is True
