"""Regression tests for iterative refiner workflow failure contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow
from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity


class _NoOpRefinerLLM:
    last_exhaustion_error = None

    def propose_edits(self, **kwargs):
        return []


def _workflow_with_noop_llm() -> IterativeRefinerWorkflow:
    return IterativeRefinerWorkflow(llm_agent=_NoOpRefinerLLM())


@pytest.mark.parametrize("move_target", [True, False])
@pytest.mark.parametrize("chart_type", ["flowchart", "concept_map"])
@pytest.mark.parametrize("whole_iteration", [False, True])
def test_edit_batch_preserves_label_style_and_recomputes_geometry(
    move_target, chart_type, whole_iteration, monkeypatch,
):
    from evo_diagram.agentic_system.iterative_workflow import _apply_edit_batch
    from evo_diagram.agentic_system.refinement_stage.state import (
        EditOp, IterationLog, VerifierRefinerState,
    )
    from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
        add_excalidraw_arrows_to_manifest,
    )
    from evo_diagram.agentic_system.render_engine.excalidraw.converter import (
        InstantiationToExcalidrawConverter,
    )
    from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
        check_edge_node_intersections,
    )

    structure = {
        "chart_type": chart_type,
        "nodes": [{"id": key, "label": key, "class": "process"} for key in ("a", "b")],
        "edges": [{"id": "edge:a2b", "source": "a", "target": "b", "label": "supplies"}],
        "groups": [],
    }
    layout = {
        "a": {"type": "rectangle", "x": 80, "y": 80, "w": 120, "h": 60},
        "b": {"type": "rectangle", "x": 400, "y": 80, "w": 120, "h": 60},
        "edge:a2b": {
            "type": "arrow",
            "start": {"elementId": "a", "side": "right"},
            "end": {"elementId": "b", "side": "left"},
        },
    }
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout, structure_instantiation=structure,
    ).convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, structure)
    target_id = manifest["_meta"]["id_map"]["b"]
    arrow = next(element for element in manifest["elements"] if element["type"] == "arrow")
    label = next(element for element in manifest["elements"] if element.get("meta", {}).get("semantic_edge_id") == "edge:a2b" and element["type"] == "text")
    original_label_width = label["width"]
    state = VerifierRefinerState(
        manifest_path="unused.json", image_path="unused.png",
        manifest=manifest, structure=structure,
    )
    log = IterationLog(iteration=1)
    edits = [
        EditOp(op="set_style", id=arrow["id"], payload={"strokeColor": "#456789"}),
        EditOp(op="set_style", id=label["id"], payload={"fontSize": 18, "strokeColor": "#123456"}),
    ]
    if move_target:
        edits.extend([
            EditOp(op="set_position", id=target_id, payload={"x": 460, "y": 300}),
            EditOp(op="set_size", id=target_id, payload={"width": 160, "height": 80}),
        ])
    if whole_iteration:
        from evo_diagram.agentic_system import iterative_workflow

        # Once the scene router has rebuilt connectors and positioned their
        # labels, endpoint-only fallback routing must not overwrite that work.
        def unexpected_fallback(*args, **kwargs):
            pytest.fail("semantic routes were overwritten by endpoint-only routing")

        monkeypatch.setattr(iterative_workflow, "reroute_bound_arrows", unexpected_fallback)
        monkeypatch.setattr(iterative_workflow, "run_all_deterministic_fixers", lambda *args: edits)
        monkeypatch.setattr(iterative_workflow, "_run_objective_checks", lambda state: [])
        state.skip_rerender_between_iterations = True
        iterative_workflow._run_one_iteration(state, llm_agent=None)
        log = state.iteration_logs[0]
        outcomes = log.deterministic_edits
    else:
        outcomes = _apply_edit_batch(
            state,
            edits,
            log=log, target_attr="llm_edits", log_prefix="test",
        )

    assert all(outcome.applied for outcome in outcomes)
    moved = next(element for element in state.manifest["elements"] if element["id"] == target_id)
    routed = next(element for element in state.manifest["elements"] if element["type"] == "arrow")
    end_x = routed["x"] + routed["points"][-1][0]
    end_y = routed["y"] + routed["points"][-1][1]
    assert moved["y"] <= end_y <= moved["y"] + moved["height"]
    assert end_x == pytest.approx(moved["x"], abs=10)
    assert routed["meta"]["target"] == "b"
    assert routed["strokeColor"] == "#456789"
    assert state.manifest["_meta"]["id_map"]["edge:a2b"] == routed["id"]
    assert not check_edge_node_intersections(state.manifest)
    assert any("rebuilt connectors" in note for note in log.notes)
    rebuilt_label = next(element for element in state.manifest["elements"] if element.get("meta", {}).get("semantic_edge_id") == "edge:a2b" and element["type"] == "text")
    assert rebuilt_label["fontSize"] == 18
    assert rebuilt_label["strokeColor"] == "#123456"
    assert rebuilt_label["width"] > original_label_width


def test_refiner_manifest_summary_pins_finding_elements_before_cap():
    from evo_diagram.agentic_system.refinement_stage.agent.llm_agent import (
        build_manifest_summary,
    )

    manifest = {
        "elements": [
            {
                "id": f"n{i}",
                "type": "rectangle",
                "x": i,
                "y": i,
                "width": 10,
                "height": 10,
            }
            for i in range(10)
        ]
    }

    summary = build_manifest_summary(manifest, cap=3, pinned_ids={"n8"})

    assert [entry["id"] for entry in summary] == ["n8", "n0", "n1"]


def test_refiner_prompt_retains_semantic_context_and_labels_after_element_80():
    from evo_diagram.agentic_system.refinement_stage.agent.llm_agent import build_manifest_summary
    from evo_diagram.agentic_system.refinement_stage.agent.prompts import build_refiner_user_prompt

    elements = [{"id": f"element_{index}", "type": "rectangle", "x": index * 20, "y": 40,
                 "width": 10, "height": 10} for index in range(82)]
    elements.extend([
        {"id": "group", "type": "rectangle", "is_group": True, "x": 0, "y": 0,
         "width": 100, "height": 100, "meta": {"memberIds": ["collective"]}},
        {"id": "collective", "type": "rectangle", "x": 10, "y": 10,
         "width": 60, "height": 40, "meta": {"conceptFactAnchor": True}},
        {"id": "late_predicate", "type": "text", "text": "enables", "x": 120, "y": 20,
         "width": 80, "height": 20, "fontSize": 14, "strokeColor": "#123456",
         "meta": {"semantic_edge_id": "collective_to_outcome", "semantic_arrow_id": "connector"}},
    ])
    summary = build_manifest_summary({"elements": elements, "_meta": {"id_map": {"category": "collective"}}})
    prompt = build_refiner_user_prompt(
        chart_type="concept_map", remaining_findings=[], critique=None, manifest_summary=summary,
    )
    assert "late_predicate" in prompt
    assert "collective_to_outcome" in prompt
    assert "fact_bearing_section_heading_keep_border" in prompt
    assert '"member_ids": ["collective"]' in prompt
    assert '"fontSize": 14' in prompt
    assert '"strokeColor": "#123456"' in prompt


def test_refiner_prompt_includes_finding_location():
    from evo_diagram.agentic_system.refinement_stage.agent.prompts import (
        build_refiner_user_prompt,
    )

    prompt = build_refiner_user_prompt(
        chart_type="flowchart",
        remaining_findings=[
            {
                "category": "collision/node_overlap",
                "severity": "major",
                "message": "overlap",
                "element_id": "n1",
                "location": {"other_id": "n2", "a": [0, 0, 10, 10]},
            }
        ],
        critique=None,
        manifest_summary=[],
    )

    assert "location=" in prompt
    assert '"other_id": "n2"' in prompt


def test_refiner_final_render_failure_marks_state_failed(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    layout_path = tmp_path / "layout_instantiation.json"
    output_dir = tmp_path / "refiner"
    output_dir.mkdir()

    manifest_path.write_text(
        json.dumps(
            {
                "type": "excalidraw",
                "version": 2,
                "source": "https://evodiagram.local",
                "elements": [],
                "appState": {},
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    layout_path.write_text("{}", encoding="utf-8")
    (output_dir / "refined_manifest.json").write_text("stale", encoding="utf-8")
    (output_dir / "refined_diagram.png").write_bytes(b"stale")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    render_calls = []

    def fake_render_png_result(_manifest, output_path, **_kwargs):
        render_calls.append(output_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        # Every per-iteration render succeeds (including the pre-LLM one that
        # keeps the VLM from seeing a pre-fix picture); only the final render
        # fails, which is what this test is about.
        if "refined_iter_1" in output_path:
            Path(output_path).write_bytes(b"png")
            return SimpleNamespace(
                ok=True,
                output_path=output_path,
                error="",
            )
        Path(output_path).write_bytes(b"partial")
        return SimpleNamespace(
            ok=False,
            output_path=output_path,
            error="RuntimeError: renderer stderr tail",
        )

    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        layout_path=str(layout_path),
        output_dir=str(output_dir),
        max_iterations=1,
        emit_markdown=True,
    )

    assert state.status == "failed"
    assert "final render failed: RuntimeError: renderer stderr tail" in state.errors
    assert render_calls == [
        str(output_dir / "refined_iter_1_det.png"),
        str(output_dir / "refined_diagram.png"),
    ]
    assert state.refined_manifest_path is None
    assert state.refined_image_path is None
    assert state.refiner_report_path == str(output_dir / "refiner_report.json")
    assert not (output_dir / "refined_manifest.json").exists()
    assert not (output_dir / "refined_diagram.png").exists()


def test_refiner_workflow_rejects_non_excalidraw_canvas(tmp_path):
    with pytest.raises(ValueError, match="Excalidraw"):
        _workflow_with_noop_llm().run(
            manifest_path=str(tmp_path / "diagram_manifest.json"),
            image_path=str(tmp_path / "diagram_manifest.png"),
            canvas_library="tldraw",
        )


def test_refiner_cli_reports_environment_loader_failure(monkeypatch, tmp_path):
    from evo_diagram.agentic_system.refinement_stage import __main__ as refiner_cli

    monkeypatch.setattr(refiner_cli, "_load_environment", lambda: False)

    result = refiner_cli.main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--image",
            str(tmp_path / "image.png"),
        ]
    )

    assert result == 2


def test_refiner_cli_passes_explicit_layout_path(monkeypatch, tmp_path):
    from evo_diagram.agentic_system.refinement_stage import __main__ as refiner_cli

    captured = {}

    class _FakeWorkflow:
        def run(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                status="reported",
                manifest_path=kwargs["manifest_path"],
                image_path=kwargs["image_path"],
                current_iteration=1,
                max_iterations=1,
                converged=True,
                termination_reason="fixed_point",
                refined_manifest_path=None,
                refined_image_path=None,
                refiner_report_path=None,
                iteration_logs=[],
                errors=[],
                skipped_objective_checks=[],
            )

    monkeypatch.setattr(refiner_cli, "_load_environment", lambda: True)
    monkeypatch.setattr(
        "evo_diagram.agentic_system.iterative_workflow.IterativeRefinerWorkflow",
        lambda: _FakeWorkflow(),
    )

    manifest_path = tmp_path / "manifest.json"
    image_path = tmp_path / "image.png"
    layout_path = tmp_path / "layout.json"

    result = refiner_cli.main(
        [
            "--manifest",
            str(manifest_path),
            "--image",
            str(image_path),
            "--layout",
            str(layout_path),
            "--max-iterations",
            "1",
        ]
    )

    assert result == 0
    assert captured["layout_path"] == str(layout_path.resolve())
    assert captured["canvas_library"] == "excalidraw"


def test_refiner_cli_rejects_tldraw_manifest_before_workflow(monkeypatch, tmp_path, capsys):
    from evo_diagram.agentic_system.refinement_stage import __main__ as refiner_cli

    class _UnexpectedWorkflow:
        def run(self, **_kwargs):
            raise AssertionError("TLDraw manifest must be rejected before workflow.run")

    monkeypatch.setattr(refiner_cli, "_load_environment", lambda: True)
    monkeypatch.setattr(
        "evo_diagram.agentic_system.iterative_workflow.IterativeRefinerWorkflow",
        lambda: _UnexpectedWorkflow(),
    )

    manifest_path = tmp_path / "tldraw_manifest.json"
    manifest_path.write_text(
        json.dumps({"document": {"id": "document:document"}, "store": {}}),
        encoding="utf-8",
    )
    image_path = tmp_path / "image.png"

    result = refiner_cli.main(
        [
            "--manifest",
            str(manifest_path),
            "--image",
            str(image_path),
        ]
    )

    assert result == 2
    assert "Excalidraw manifests only" in capsys.readouterr().err


def test_refiner_workflow_rejects_non_positive_max_iterations(tmp_path):
    with pytest.raises(ValueError, match="max_iterations"):
        _workflow_with_noop_llm().run(
            manifest_path=str(tmp_path / "diagram_manifest.json"),
            image_path=str(tmp_path / "diagram_manifest.png"),
            max_iterations=0,
        )


def test_refiner_load_failure_writes_report_without_rendering(tmp_path, monkeypatch):
    output_dir = tmp_path / "refiner"

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    def fail_render_png_result(*args, **kwargs):
        raise AssertionError("finalize must not render when input loading failed")

    monkeypatch.setattr(iterative_workflow, "render_png_result", fail_render_png_result)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(tmp_path / "missing_manifest.json"),
        image_path=str(tmp_path / "missing_image.png"),
        output_dir=str(output_dir),
        max_iterations=1,
    )

    assert state.status == "failed"
    assert state.refined_manifest_path is None
    assert state.refined_image_path is None
    assert state.refiner_report_path == str(output_dir / "refiner_report.json")
    assert not (output_dir / "refined_manifest.json").exists()
    assert any("could not load manifest" in error for error in state.errors)


def test_refiner_explicit_missing_structure_path_fails_before_iteration(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    structure_path = tmp_path / "missing_structure.json"
    output_dir = tmp_path / "refiner"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    monkeypatch.setattr(
        iterative_workflow,
        "run_all_checks",
        lambda *args, **kwargs: pytest.fail("refiner must not run checks without structure context"),
    )
    monkeypatch.setattr(
        iterative_workflow,
        "render_png_result",
        lambda *args, **kwargs: pytest.fail("refiner must not render failed context"),
    )

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        structure_path=str(structure_path),
        output_dir=str(output_dir),
        max_iterations=1,
    )

    assert state.status == "failed"
    assert state.current_iteration == 0
    assert state.refined_manifest_path is None
    assert state.refined_image_path is None
    assert state.refiner_report_path == str(output_dir / "refiner_report.json")
    assert any("explicit structure_path" in error for error in state.errors)
    assert not (output_dir / "refined_manifest.json").exists()


def test_refiner_converged_iteration_omits_unused_analysis_render(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [],
    )

    def fake_render_png_result(manifest, output_path, *, canvas_library, **_kwargs):
        assert canvas_library == "excalidraw"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"png")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=1,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=None)

    assert result.current_iteration == 1
    assert result.converged is True
    assert result.termination_reason == "no_edits_resolved"
    assert len(result.iteration_logs) == 1
    assert result.iteration_logs[0].rerender_ok is False
    assert result.iteration_logs[0].rerender_path is None
    assert result.current_image_path == str(image_path)
    assert "terminal analysis render omitted" in result.iteration_logs[0].notes[-1]


def test_refiner_intermediate_rerender_failure_stops_before_stale_image_reuse(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        iterative_workflow,
        "render_png_result",
        lambda _manifest, output_path, **_kwargs: SimpleNamespace(
            ok=False,
            output_path=output_path,
            error="RuntimeError: renderer stderr tail",
        ),
    )

    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=2,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=_NoOpRefinerLLM())

    assert result.status == "failed"
    assert result.current_iteration == 1
    assert result.current_image_path == str(image_path)
    assert result.termination_reason is None
    assert result.iteration_logs[0].rerender_ok is False
    assert result.iteration_logs[0].rerender_path is None
    assert result.iteration_logs[0].rerender_error == "RuntimeError: renderer stderr tail"
    assert any("stale image input" in error for error in result.errors)
    assert "renderer stderr tail" in result.errors[-1]
    assert IterativeRefinerWorkflow()._after_iteration(result) == "finalize"


def test_refiner_loads_layout_and_passes_it_to_objective_checks(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    layout_path = tmp_path / "layout_instantiation.json"
    output_dir = tmp_path / "refiner"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    layout_path.write_text(
        json.dumps({"n1": {"x": 10, "y": 20}}),
        encoding="utf-8",
    )

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    check_calls = []

    def fake_run_all_checks(
        manifest,
        structure=None,
        layout_instantiation=None,
        canvas_library="excalidraw",
        **kwargs,
    ):
        check_calls.append(
            {
                "layout_instantiation": layout_instantiation,
                "canvas_library": canvas_library,
            }
        )
        return []

    def fake_render_png_result(manifest, output_path, *, canvas_library, **_kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"png")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    monkeypatch.setattr(iterative_workflow, "run_all_checks", fake_run_all_checks)
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        layout_path=str(layout_path),
        output_dir=str(output_dir),
        max_iterations=1,
    )

    assert state.layout_instantiation == {"n1": {"x": 10, "y": 20}}
    assert check_calls
    assert {call["canvas_library"] for call in check_calls} == {"excalidraw"}
    assert all(
        call["layout_instantiation"] == {"n1": {"x": 10, "y": 20}}
        for call in check_calls
    )


def test_refiner_report_metadata_uses_refiner_model_role(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.config.model_loader import ModelConfig

    seen_roles = []

    class FakeModelConfig:
        def get_model_config(self, role):
            seen_roles.append(role)
            return {"model": f"{role}-model"}

    monkeypatch.setattr(
        ModelConfig,
        "get_default",
        classmethod(lambda cls: FakeModelConfig()),
    )
    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [],
    )

    def fake_render_png_result(manifest, output_path, *, canvas_library, **_kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"png")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        max_iterations=1,
    )

    report = json.loads(Path(state.refiner_report_path).read_text(encoding="utf-8"))
    assert seen_roles == ["refiner"]
    assert report["metadata"]["vlm_model"] == "refiner-model"
    assert state.refined_manifest_path == str(output_dir / "refined_manifest.json")
    assert state.refined_image_path == str(output_dir / "refined_diagram.png")
    assert (output_dir / "refined_manifest.json").exists()
    assert (output_dir / "refined_diagram.png").exists()


def test_refiner_no_rerender_still_renders_final_refined_png(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text('{"elements": []}', encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    render_png_result_calls = []

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [],
    )

    def fake_render_png_result(manifest, output_path, *, canvas_library, **_kwargs):
        render_png_result_calls.append(
            {
                "manifest": manifest,
                "output_path": output_path,
                "canvas_library": canvas_library,
            }
        )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"final-png")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        max_iterations=1,
        skip_rerender_between_iterations=True,
    )

    assert state.status == "reported"
    assert state.converged is True
    assert state.refined_manifest_path == str(output_dir / "refined_manifest.json")
    assert state.refined_image_path == str(output_dir / "refined_diagram.png")
    assert [call["output_path"] for call in render_png_result_calls] == [
        str(output_dir / "refined_diagram.png")
    ]
    assert (output_dir / "refined_diagram.png").read_bytes() == b"final-png"
    assert state.iteration_logs[0].rerender_ok is False
    assert "re-render skipped (--no-rerender)" in state.iteration_logs[0].notes


def test_refiner_non_converged_finalize_writes_candidate_artifacts(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    output_dir.mkdir()
    manifest_path.write_text('{"elements": []}', encoding="utf-8")
    image_path.write_bytes(b"original-png")
    (output_dir / "refined_manifest.json").write_text("stale", encoding="utf-8")
    (output_dir / "refined_diagram.png").write_bytes(b"stale")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    serious = Finding(
        category="collision/node_overlap",
        severity=Severity.MAJOR,
        message="node overlap remains",
        element_id="n1",
    )
    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [serious])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [],
    )

    def fake_render_png_result(manifest, output_path, *, canvas_library, **_kwargs):
        assert canvas_library == "excalidraw"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"candidate-png")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        max_iterations=1,
    )

    assert state.status == "reported"
    assert state.converged is False
    assert state.termination_reason == "fixed_point_unresolved"
    assert state.refined_manifest_path is None
    assert state.refined_image_path is None
    assert state.candidate_manifest_path == str(output_dir / "candidate_manifest.json")
    assert state.candidate_image_path == str(output_dir / "candidate_diagram.png")
    assert not (output_dir / "refined_manifest.json").exists()
    assert not (output_dir / "refined_diagram.png").exists()
    assert json.loads((output_dir / "candidate_manifest.json").read_text(encoding="utf-8")) == {
        "elements": []
    }
    assert (output_dir / "candidate_diagram.png").read_bytes() == b"candidate-png"


def test_refiner_fixed_point_with_serious_findings_is_not_converged(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

    serious = Finding(
        category="collision/node_overlap",
        severity=Severity.MAJOR,
        message="node overlap remains",
        element_id="n1",
    )
    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [serious])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [],
    )

    def fake_render_png_result(manifest, output_path, *, canvas_library, **_kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"png")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=3,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=None)

    assert result.converged is False
    assert result.termination_reason == "fixed_point_unresolved"
    assert IterativeRefinerWorkflow()._after_iteration(result) == "finalize"


def test_refiner_rejected_edits_do_not_count_as_progress(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import EditOp, VerifierRefinerState

    serious = Finding(
        category="collision/node_overlap",
        severity=Severity.MAJOR,
        message="node overlap remains",
        element_id="missing",
    )
    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [serious])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [
            EditOp(
                op="set_position",
                id="missing",
                payload={"x": 10, "y": 20},
                rationale="attempt to move missing element",
            )
        ],
    )

    def fake_render_png_result(manifest, output_path, *, canvas_library, **_kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"png")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    monkeypatch.setattr(iterative_workflow, "render_png_result", fake_render_png_result)

    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=1,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=None)

    assert result.converged is False
    assert result.termination_reason == "fixed_point_unresolved"
    assert result.iteration_logs[0].deterministic_edits[0].applied is False
    assert "not found" in result.iteration_logs[0].deterministic_edits[0].error


def test_refiner_records_deterministic_fixer_failure(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
        DeterministicFixerError,
    )
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *args, **kwargs: [])

    def failing_fixers(*args, **kwargs):
        raise DeterministicFixerError("group_frame_zorder", RuntimeError("boom"))

    monkeypatch.setattr(iterative_workflow, "run_all_deterministic_fixers", failing_fixers)
    monkeypatch.setattr(
        iterative_workflow,
        "render_png_result",
        lambda *args, **kwargs: pytest.fail("failed fixer iteration must not render"),
    )

    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=1,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=None)

    assert result.status == "failed"
    assert result.current_iteration == 1
    assert any("group_frame_zorder" in error for error in result.errors)
    assert result.iteration_logs
    assert any("group_frame_zorder" in note for note in result.iteration_logs[0].notes)


def test_refiner_report_includes_intermediate_rerender_error(tmp_path):
    from evo_diagram.agentic_system.refinement_stage.reports.refiner_report import (
        build_refiner_report,
    )
    from evo_diagram.agentic_system.refinement_stage.state import (
        IterationLog,
        VerifierRefinerState,
    )

    state = VerifierRefinerState(
        manifest_path=str(tmp_path / "input_manifest.json"),
        image_path=str(tmp_path / "input.png"),
        output_dir=str(tmp_path),
        manifest={"type": "excalidraw", "elements": [], "appState": {}, "files": {}},
        current_image_path=str(tmp_path / "input.png"),
    )
    state.iteration_logs.append(
        IterationLog(
            iteration=1,
            rerender_ok=False,
            rerender_error="RuntimeError: renderer stderr tail",
        )
    )

    report = build_refiner_report(state)

    assert report["iterations"][0]["rerender_error"] == (
        "RuntimeError: renderer stderr tail"
    )


def _valid_manifest() -> dict:
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://evodiagram.local",
        "elements": [],
        "appState": {},
        "files": {},
    }


def _ok_render(_manifest, output_path, **_kwargs):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(b"png")
    return SimpleNamespace(ok=True, output_path=output_path, error="")


def test_refiner_detects_stagnation_across_iterations(tmp_path, monkeypatch):
    """``stagnant`` was unreachable: the fingerprint lived in a PrivateAttr.

    LangGraph only builds channels for ``model_fields`` and rebuilds the state
    from channel values on every node entry, so the previous round's
    fingerprint was always None and identical findings looped until
    max_iterations.
    """
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest = _valid_manifest()
    manifest["elements"] = [
        {"id": "n1", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 60}
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import EditOp

    unfixable = [
        Finding(
            category="collision/node_overlap",
            severity=Severity.MAJOR,
            message="n1 overlaps n2",
            element_id="n1",
        )
    ]
    monkeypatch.setattr(
        iterative_workflow, "run_all_checks", lambda *args, **kwargs: list(unfixable)
    )
    # An edit that applies every round without changing the findings — the
    # exact shape of a loop that must terminate on stagnation.
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [
            EditOp(op="set_style", id="n1", payload={"opacity": 100})
        ],
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", _ok_render)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        layout_path=None,
        output_dir=str(output_dir),
        max_iterations=5,
    )

    assert state.termination_reason == "stagnant"
    assert state.current_iteration == 2
    assert state.converged is False
    assert state.prev_findings_fingerprint
    assert any(
        "stagnation" in note
        for log in state.iteration_logs
        for note in log.notes
    )


def test_refiner_rolls_back_a_round_that_makes_findings_worse(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import (
        EditOp,
        VerifierRefinerState,
    )

    calls = {"n": 0}

    def worsening_checks(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                Finding(
                    category="collision/node_overlap",
                    severity=Severity.MAJOR,
                    message="one overlap",
                    element_id="n1",
                )
            ]
        return [
            Finding(
                category="collision/node_overlap",
                severity=Severity.MAJOR,
                message=f"overlap {i}",
                element_id="n1",
            )
            for i in range(3)
        ]

    monkeypatch.setattr(iterative_workflow, "run_all_checks", worsening_checks)
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *args, **kwargs: [
            EditOp(op="set_position", id="n1", payload={"x": 9000, "y": 9000})
        ],
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", _ok_render)

    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={
            "elements": [
                {"id": "n1", "type": "rectangle", "x": 10, "y": 20, "width": 100, "height": 50}
            ]
        },
        current_image_path=str(image_path),
        max_iterations=2,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=None)

    # The damage is gone: the round started from a deepcopy snapshot.
    assert result.manifest["elements"][0]["x"] == 10
    assert result.manifest["elements"][0]["y"] == 20
    log = result.iteration_logs[0]
    assert any("rolled back" in note for note in log.notes)
    assert log.rolled_back is True
    # The round is reported as making no progress, so the loop stops instead of
    # re-deriving the same regression from the same input.
    assert log.findings_after["major"] == 1
    assert result.termination_reason == "fixed_point_unresolved"
    assert result.best_findings_score == 10.0


def test_refiner_skips_layout_audit_when_no_layout_is_provided(tmp_path, monkeypatch):
    """``--layout`` is documented as optional, so it must not block convergence.

    ``check_layout_audit`` returns a CRITICAL when layout is missing and no
    fixer can ever produce one, so the refiner used to burn every iteration and
    write a candidate with exit code 1 even when the diagram was clean.
    """
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    seen: list = []
    real_run_all_checks = iterative_workflow.run_all_checks

    def spy(*args, **kwargs):
        seen.append(kwargs.get("skip_categories"))
        return real_run_all_checks(*args, **kwargs)

    monkeypatch.setattr(iterative_workflow, "run_all_checks", spy)
    monkeypatch.setattr(iterative_workflow, "render_png_result", _ok_render)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        max_iterations=2,
    )

    assert seen and all(skip == ["layout_audit"] for skip in seen)
    assert state.converged is True
    assert state.refined_manifest_path == str(output_dir / "refined_manifest.json")
    assert any(
        "layout_audit" in entry for entry in state.skipped_objective_checks
    )

    report = json.loads((output_dir / "refiner_report.json").read_text(encoding="utf-8"))
    assert any(
        "did NOT run" in entry for entry in report["skipped_objective_checks"]
    )


def test_refiner_records_schema_rejected_llm_edits(tmp_path, monkeypatch):
    """A fully rejected proposal batch must not look like "nothing to fix"."""
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

    class _RejectingLLM:
        last_exhaustion_error = None

        def __init__(self):
            self.last_rejected_edits = []
            self.seen_kwargs = {}

        def propose_edits(self, **kwargs):
            self.seen_kwargs = kwargs
            self.last_rejected_edits = [
                {
                    "raw": {"op": "set_position", "id": "n1", "reason": "typo"},
                    "error": "schema: Extra inputs are not permitted [type=extra_forbidden]",
                }
            ]
            return []

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        iterative_workflow, "run_all_deterministic_fixers", lambda *a, **k: []
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", _ok_render)

    agent = _RejectingLLM()
    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=1,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=agent)

    log = result.iteration_logs[0]
    assert len(log.llm_edits) == 1
    rejected = log.llm_edits[0]
    assert rejected.edit is None
    assert rejected.applied is False
    assert rejected.error.startswith("schema:")
    assert rejected.raw == {"op": "set_position", "id": "n1", "reason": "typo"}
    assert any("schema validation" in err for err in result.errors)

    # The report must carry the rejection instead of dropping the row.
    from evo_diagram.agentic_system.refinement_stage.reports.refiner_report import (
        build_markdown_report,
        build_refiner_report,
    )

    report = build_refiner_report(result)
    assert report["iterations"][0]["llm_edits"][0]["edit"] is None
    assert "(rejected)" in build_markdown_report(report)


def test_refiner_rerenders_before_the_llm_call_and_says_so(tmp_path, monkeypatch):
    """The VLM must not judge this round's coordinates against last round's PNG."""
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

    renders: list = []

    def tracking_render(manifest, output_path, **kwargs):
        renders.append(output_path)
        return _ok_render(manifest, output_path, **kwargs)

    class _CapturingLLM:
        last_exhaustion_error = None
        last_rejected_edits: list = []

        def __init__(self):
            self.seen = {}

        def propose_edits(self, **kwargs):
            self.seen = kwargs
            return []

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        iterative_workflow, "run_all_deterministic_fixers", lambda *a, **k: []
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", tracking_render)

    agent = _CapturingLLM()
    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=1,
    )

    iterative_workflow._run_one_iteration(state, llm_agent=agent)

    assert renders[0] == str(output_dir / "refined_iter_1_det.png")
    assert agent.seen["image_path"] == str(output_dir / "refined_iter_1_det.png")
    assert "AFTER" in agent.seen["image_note"]
    # This round's own deterministic log reaches the prompt, not only closed rounds.
    assert agent.seen["previous_attempts"][-1]["iteration"] == 1


def test_refiner_warns_the_llm_when_rerender_is_disabled(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

    class _CapturingLLM:
        last_exhaustion_error = None
        last_rejected_edits: list = []

        def __init__(self):
            self.seen = {}

        def propose_edits(self, **kwargs):
            self.seen = kwargs
            return []

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        iterative_workflow, "run_all_deterministic_fixers", lambda *a, **k: []
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", _ok_render)

    agent = _CapturingLLM()
    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest={"elements": []},
        current_image_path=str(image_path),
        max_iterations=1,
        skip_rerender_between_iterations=True,
    )

    iterative_workflow._run_one_iteration(state, llm_agent=agent)

    assert "predates" in agent.seen["image_note"]


def test_refiner_reroutes_arrows_after_applying_geometry_edits(tmp_path, monkeypatch):
    """The loop, not just the fixer, must keep arrows attached."""
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow
    from evo_diagram.agentic_system.refinement_stage.state import (
        EditOp,
        VerifierRefinerState,
    )
    from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
        check_arrow_endpoint_geometry,
    )

    manifest = {
        "_meta": {"id_map": {"n1": "n1", "n2": "n2"}},
        "elements": [
            {"id": "n1", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 60},
            {"id": "n2", "type": "rectangle", "x": 300, "y": 0, "width": 100, "height": 60},
            {
                "id": "a1",
                "type": "arrow",
                "x": 100.0,
                "y": 30.0,
                "width": 200.0,
                "height": 1.0,
                "points": [[0.0, 0.0], [200.0, 0.0]],
                "meta": {"semantic_edge_id": "edge:n1n2", "source": "n1", "target": "n2"},
            },
        ],
    }

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        iterative_workflow,
        "run_all_deterministic_fixers",
        lambda *a, **k: [EditOp(op="set_position", id="n2", payload={"x": 300, "y": 500})],
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", _ok_render)

    state = VerifierRefinerState(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        manifest=manifest,
        current_image_path=str(image_path),
        max_iterations=1,
    )

    result = iterative_workflow._run_one_iteration(state, llm_agent=None)

    assert check_arrow_endpoint_geometry(result.manifest) == []
    log = result.iteration_logs[0]
    assert [item["arrow_id"] for item in log.rerouted_arrows] == ["a1"]
    assert any("re-routed" in note for note in log.notes)


def test_refiner_iteration_renders_use_analysis_mode_and_final_render_does_not(
    tmp_path, monkeypatch
):
    """VLM-facing re-renders go through the analysis channel (scale 1, no
    smart crop) while the shipped product render keeps the pipeline
    defaults (renderer-default scale + crop)."""
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "refiner"
    manifest_path.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    import evo_diagram.agentic_system.iterative_workflow as iterative_workflow

    calls: list = []

    def tracking_render(manifest, output_path, **kwargs):
        calls.append({"output_path": output_path, "kwargs": kwargs})
        return _ok_render(manifest, output_path, **kwargs)

    monkeypatch.setattr(iterative_workflow, "run_all_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        iterative_workflow, "run_all_deterministic_fixers", lambda *a, **k: []
    )
    monkeypatch.setattr(iterative_workflow, "render_png_result", tracking_render)

    state = _workflow_with_noop_llm().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        max_iterations=1,
    )

    assert state.converged is True
    by_path = {Path(call["output_path"]).name: call["kwargs"] for call in calls}

    # The pre-LLM image uses analysis geometry; no unused terminal image.
    assert "refined_iter_1.png" not in by_path
    for name in ("refined_iter_1_det.png",):
        assert by_path[name]["render_scale"] == 1.0, name
        assert by_path[name]["crop"] is False, name

    # The finalized product render passes no analysis overrides.
    final_kwargs = by_path["refined_diagram.png"]
    assert "render_scale" not in final_kwargs
    assert "crop" not in final_kwargs


@pytest.mark.parametrize("severity", ["minor"])
def test_refiner_continues_after_new_low_severity_findings(severity):
    from evo_diagram.agentic_system.iterative_workflow import _mark_convergence
    from evo_diagram.agentic_system.refinement_stage.state import IterationLog, VerifierRefinerState
    from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity

    state = VerifierRefinerState(manifest_path="scene.json", image_path="scene.png")
    finding = Finding(
        category="binding/edge_label_distance", severity=Severity(severity),
        element_id="predicate", message="Label became detached after editing.",
    )
    _mark_convergence(
        state, log=IterationLog(iteration=1, findings_before={"total": 0}),
        findings_after_iter=[finding], edits_applied=True, iteration=1,
    )
    assert state.converged is False
    assert state.termination_reason is None
    assert IterativeRefinerWorkflow()._after_iteration(state) == "run_iteration"

    _mark_convergence(
        state, log=IterationLog(iteration=2, findings_before={severity: 1}),
        findings_after_iter=[], edits_applied=True, iteration=2,
    )
    assert state.converged is True
    assert state.termination_reason == "resolved"


@pytest.mark.parametrize("edits_applied,stagnant", [(False, False), (True, True)])
def test_refiner_unfixable_new_minor_is_not_marked_converged(edits_applied, stagnant):
    from evo_diagram.agentic_system.iterative_workflow import _fingerprint_findings, _mark_convergence
    from evo_diagram.agentic_system.refinement_stage.state import IterationLog, VerifierRefinerState
    from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity

    state = VerifierRefinerState(manifest_path="scene.json", image_path="scene.png")
    finding = Finding(
        category="binding/edge_label_distance", severity=Severity.MINOR,
        element_id="predicate", message="Label became detached after editing.",
    )
    if stagnant:
        state.prev_findings_fingerprint = _fingerprint_findings([finding])
    _mark_convergence(
        state, log=IterationLog(iteration=1, findings_before={"total": 0}),
        findings_after_iter=[finding], edits_applied=edits_applied, iteration=1,
    )
    assert state.converged is False
    assert state.termination_reason == ("stagnant" if stagnant else "fixed_point_unresolved")


def test_refiner_continues_for_remaining_minor_after_removing_major():
    from evo_diagram.agentic_system.iterative_workflow import _mark_convergence
    from evo_diagram.agentic_system.refinement_stage.state import IterationLog, VerifierRefinerState
    from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity

    state = VerifierRefinerState(manifest_path="scene.json", image_path="scene.png")
    finding = Finding(
        category="binding/edge_label_distance", severity=Severity.MINOR,
        element_id="predicate", message="Small remaining gap.",
    )
    _mark_convergence(
        state, log=IterationLog(iteration=1, findings_before={"major": 1}),
        findings_after_iter=[finding], edits_applied=True, iteration=1,
    )
    assert state.converged is False
    assert state.termination_reason is None
