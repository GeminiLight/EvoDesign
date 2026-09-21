from __future__ import annotations

import pytest

from evo_diagram.agentic_system.generation_stage.unified.generator import UnifiedGenerator
from evo_diagram.agentic_system.generation_stage.unified.state import UnifiedWorkflowState
from evo_diagram.agentic_system.generation_stage.unified.workflow import UnifiedGeneratorWorkflow
from evo_diagram.agentic_system.generation_stage.unified.transport_journal import NativeStreamJournal


def _generator_with_output(output):
    generator = object.__new__(UnifiedGenerator)
    generator.full_domain_knowledge = True
    generator._last_raw_output = None
    generator.stream_journal = NativeStreamJournal()
    generator.invoke = lambda _inputs: output
    return generator


def _semantic_meta(*, with_edge: bool = False):
    structure = {
        "chart_type": "flowchart",
        "nodes": [
            {"id": "n1", "label": "One", "class": "process"},
            {"id": "n2", "label": "Two", "class": "process"},
        ] if with_edge else [
            {"id": "n1", "label": "One", "class": "process"},
        ],
        "edges": [
            {"id": "edge:n12n2", "source": "n1", "target": "n2"},
        ] if with_edge else [],
        "groups": [],
    }
    id_map = {"n1": "n1"}
    if with_edge:
        id_map.update({"n2": "n2", "edge:n12n2": "arrow1"})
    return {"structure_instantiation": structure, "id_map": id_map}


def _manifest(*, with_edge: bool = False):
    elements = [{"id": "n1", "type": "rectangle"}]
    if with_edge:
        elements.extend([
            {"id": "n2", "type": "rectangle"},
            {
                "id": "arrow1",
                "type": "arrow",
                "meta": {"semantic_edge_id": "edge:n12n2"},
            },
        ])
    return {
        "type": "excalidraw/clipboard",
        "elements": elements,
        "files": {},
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
        "_meta": _semantic_meta(with_edge=with_edge),
    }


def test_unified_generator_rejects_legacy_element_list_output():
    generator = _generator_with_output([{"id": "n1", "type": "rectangle"}])

    with pytest.raises(ValueError, match="expected a dict"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_accepts_exact_top_level_contract():
    manifest = _manifest()
    generator = _generator_with_output(manifest)

    state = generator.run(UnifiedWorkflowState(text_content="hello"))

    assert state.diagram_manifest == manifest
    assert state.structure_instantiation == manifest["_meta"]["structure_instantiation"]


def test_unified_generator_requires_semantic_sidecar():
    manifest = _manifest()
    manifest.pop("_meta")
    generator = _generator_with_output(manifest)

    with pytest.raises(ValueError, match="_meta"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_invalid_semantic_sidecar():
    manifest = _manifest()
    manifest["_meta"]["structure_instantiation"]["edges"] = [
        {"id": "edge:n12missing", "source": "n1", "target": "missing"},
    ]
    generator = _generator_with_output(manifest)

    with pytest.raises(ValueError, match="semantic sidecar validation failed"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_id_map_to_missing_element():
    manifest = _manifest()
    manifest["_meta"]["id_map"]["n1"] = "missing_element"
    generator = _generator_with_output(manifest)

    with pytest.raises(ValueError, match="id_map references missing"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_missing_semantic_id_map_entry():
    manifest = _manifest(with_edge=True)
    manifest["_meta"]["id_map"].pop("n2")
    generator = _generator_with_output(manifest)

    with pytest.raises(ValueError, match="id_map is missing semantic id"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_unknown_semantic_id_map_entry():
    manifest = _manifest()
    manifest["_meta"]["id_map"]["ghost_node"] = "n1"
    generator = _generator_with_output(manifest)

    with pytest.raises(ValueError, match="id_map contains unknown semantic id"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_allows_group_companion_id_map_entries():
    manifest = _manifest()
    structure = manifest["_meta"]["structure_instantiation"]
    structure["groups"] = [
        {"id": "g_lane", "label": "Lane", "members": ["n1"]},
    ]
    manifest["elements"] = [
        {"id": "shape1", "type": "rectangle"},
        {"id": "lane-bg", "type": "rectangle"},
        {"id": "lane-title", "type": "text"},
        {"id": "node-icon", "type": "image"},
    ]
    manifest["_meta"]["id_map"] = {
        "n1": "shape1",
        "g_lane:background": "lane-bg",
        "g_lane:title": "lane-title",
        "n1:icon": "node-icon",
    }
    generator = _generator_with_output(manifest)

    state = generator.run(UnifiedWorkflowState(text_content="hello"))

    assert state.structure_instantiation["groups"][0]["id"] == "g_lane"


def test_unified_generator_rejects_missing_arrow_semantic_edge_metadata():
    manifest = _manifest(with_edge=True)
    manifest["elements"][2]["meta"] = {}
    generator = _generator_with_output(manifest)

    with pytest.raises(ValueError, match="missing arrow meta\\.semantic_edge_id"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_missing_elements_array():
    generator = _generator_with_output({"type": "excalidraw/clipboard"})

    with pytest.raises(ValueError, match="missing required top-level key"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_non_list_elements():
    generator = _generator_with_output(
        {
            "type": "excalidraw/clipboard",
            "elements": {"n1": {"id": "n1"}},
            "files": {},
            "appState": {},
            "_meta": _semantic_meta(),
        }
    )

    with pytest.raises(ValueError, match="'elements' must be a list"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_extra_top_level_keys():
    manifest = _manifest()
    manifest["debug_notes"] = "not part of the contract"
    generator = _generator_with_output(manifest)

    with pytest.raises(ValueError, match="unexpected top-level key"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_generator_rejects_missing_envelope_keys():
    generator = _generator_with_output(
        {
            "type": "excalidraw/clipboard",
            "elements": [],
            "files": {},
        }
    )

    with pytest.raises(ValueError, match="appState"):
        generator.run(UnifiedWorkflowState(text_content="hello"))


def test_unified_workflow_normalizer_failure_is_fatal(monkeypatch):
    import evo_diagram.agentic_system.generation_stage.unified.workflow as workflow_module

    workflow = object.__new__(UnifiedGeneratorWorkflow)
    state = UnifiedWorkflowState(
        diagram_manifest={
            "type": "excalidraw/clipboard",
            "elements": [],
            "files": {},
            "appState": {},
            "_meta": _semantic_meta(),
        }
    )

    def fail_normalize(*args, **kwargs):
        raise ValueError("normalizer exploded")

    monkeypatch.setattr(workflow_module, "normalize_manifest", fail_normalize)

    with pytest.raises(RuntimeError, match="normalizer failed"):
        workflow._run_normalizer(state)


def test_unified_workflow_revalidates_sidecar_after_normalizer(monkeypatch):
    import evo_diagram.agentic_system.generation_stage.unified.workflow as workflow_module

    workflow = object.__new__(UnifiedGeneratorWorkflow)
    manifest = _manifest()
    state = UnifiedWorkflowState(
        diagram_manifest=manifest,
        structure_instantiation=manifest["_meta"]["structure_instantiation"],
    )

    def remove_mapped_element(manifest, *args, **kwargs):
        manifest["elements"] = []
        return manifest

    monkeypatch.setattr(workflow_module, "normalize_manifest", remove_mapped_element)

    with pytest.raises(ValueError, match="invalid semantic sidecar"):
        workflow._run_normalizer(state)


def test_unified_workflow_validator_rejects_schema_errors():
    workflow = object.__new__(UnifiedGeneratorWorkflow)
    state = UnifiedWorkflowState(
        diagram_manifest={
            "type": "excalidraw/clipboard",
            "elements": [{"id": "n1", "type": "rectangle"}],
            "files": {},
        }
    )

    with pytest.raises(ValueError, match="schema validation failed"):
        workflow._run_validator(state)


def test_unified_workflow_validator_passes_structure_to_audit(monkeypatch):
    import evo_diagram.agentic_system.generation_stage.unified.workflow as workflow_module

    workflow = object.__new__(UnifiedGeneratorWorkflow)
    manifest = _manifest()
    structure = manifest["_meta"]["structure_instantiation"]
    state = UnifiedWorkflowState(
        diagram_manifest=manifest,
        structure_instantiation=structure,
    )
    captured = {}

    def fake_validate_manifest(*args, **kwargs):
        return {"is_valid": True, "errors": []}

    class FakeAuditReport:
        warnings = ["checked"]

    def fake_audit_manifest(manifest_arg, *, structure_instantiation=None, canvas_library=None):
        captured["manifest"] = manifest_arg
        captured["structure_instantiation"] = structure_instantiation
        captured["canvas_library"] = canvas_library
        return FakeAuditReport()

    monkeypatch.setattr(workflow_module, "validate_manifest", fake_validate_manifest)
    monkeypatch.setattr(workflow_module, "audit_manifest", fake_audit_manifest)

    workflow._run_validator(state)

    assert captured["manifest"] == manifest
    assert captured["structure_instantiation"] == structure
    assert captured["canvas_library"] == "excalidraw"
    assert state.audit_warnings == ["checked"]


@pytest.mark.parametrize("failure_stage", ["generate", "normalize", "validate"])
def test_unified_workflow_repairs_current_scene_from_concrete_errors(tmp_path, monkeypatch, failure_stage):
    import json
    from copy import deepcopy
    import evo_diagram.agentic_system.generation_stage.unified.workflow as workflow_module
    from evo_diagram.agentic_system.generation_stage.unified.generator import UNIFIED_TASK_PROMPT
    from evo_diagram.agentic_system.render_engine.excalidraw.converter import _excalidraw_defaults

    good = _manifest()
    good["elements"][0].update(_excalidraw_defaults("repair-node"))
    good["elements"][0].update(x=80, y=80, width=160, height=60)
    bad = deepcopy(good)
    if failure_stage == "generate":
        bad["_meta"]["id_map"]["n1"] = "missing_shape"
    elif failure_stage == "validate":
        bad["elements"][0].pop("width")
    else:
        original_normalize = workflow_module.normalize_manifest
        calls = []

        def reject_first_scene(manifest, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("invalid frame index")
            return original_normalize(manifest, **kwargs)

        monkeypatch.setattr(workflow_module, "normalize_manifest", reject_first_scene)

    generator = _generator_with_output(deepcopy(bad))
    generator._system_prompt = "Respect source facts."
    generator._task_prompt = UNIFIED_TASK_PROMPT
    received = []

    def repair(messages):
        received.append(deepcopy(messages))
        return deepcopy(good)

    generator.invoke_with_history = repair
    workflow = object.__new__(UnifiedGeneratorWorkflow)
    workflow.agent = generator
    workflow.graph = workflow._build_graph()
    report_path = tmp_path / "attempts.json"
    state = workflow.run(UnifiedWorkflowState(
        text_content="One is a process.", validation_report_path=str(report_path),
    ))

    assert len(received) == 1
    assert received[0][-2]["role"] == "assistant"
    previous = json.loads(received[0][-2]["content"])
    assert previous["elements"][0]["id"] == "n1"
    assert failure_stage in received[0][-1]["content"]
    assert "One is a process." in received[0][1]["content"]
    assert state.diagram_manifest["elements"][0]["width"] == 160
    assert state.structure_instantiation["nodes"][0]["id"] == "n1"
    report = json.loads(report_path.read_text())
    assert report["status"] == "complete"
    assert len(report["attempts"]) == 2
    assert report["attempts"][0]["stage"] == failure_stage
    assert report["attempts"][0]["output"] == previous
    assert report["attempts"][1]["error"] is None


def test_unified_workflow_bounds_repairs_and_keeps_failure_evidence(tmp_path):
    import json
    from copy import deepcopy
    from evo_diagram.agentic_system.generation_stage.unified.generator import UNIFIED_TASK_PROMPT

    bad = _manifest()
    bad["_meta"]["id_map"]["n1"] = "missing_shape"
    generator = _generator_with_output(deepcopy(bad))
    generator._system_prompt = "Respect source facts."
    generator._task_prompt = UNIFIED_TASK_PROMPT
    repairs = []
    generator.invoke_with_history = lambda messages: (repairs.append(messages) or deepcopy(bad))
    workflow = object.__new__(UnifiedGeneratorWorkflow)
    workflow.agent = generator
    workflow.graph = workflow._build_graph()
    report_path = tmp_path / "failed-attempts.json"

    with pytest.raises(ValueError, match="remains invalid after 3 attempts"):
        workflow.run(UnifiedWorkflowState(
            text_content="One is a process.", validation_report_path=str(report_path),
        ))

    assert len(repairs) == 2
    report = json.loads(report_path.read_text())
    assert report["status"] == "failed"
    assert len(report["attempts"]) == 3
    assert all(item["output"] == bad for item in report["attempts"])


def test_unified_workflow_does_not_send_transport_errors_as_scene_feedback():
    workflow = object.__new__(UnifiedGeneratorWorkflow)
    generator = _generator_with_output(None)

    def unavailable(_inputs):
        raise OSError("connection unavailable")

    generator.invoke = unavailable
    workflow.agent = generator
    workflow.graph = workflow._build_graph()
    with pytest.raises(OSError, match="connection unavailable"):
        workflow.run(UnifiedWorkflowState(text_content="One is a process."))


def _compact_native_scene():
    manifest = _manifest(with_edge=True)
    manifest["elements"] = [
        {"id": "n1", "type": "rectangle", "x": 80, "y": 80, "width": 160,
         "height": 60, "strokeColor": "#3F7E8C", "backgroundColor": "#E8F4F6"},
        {"id": "n2", "type": "rectangle", "x": 400, "y": 80, "width": 160,
         "height": 60, "strokeColor": "#3F7E8C", "backgroundColor": "#E8F4F6"},
        {"id": "arrow1", "type": "arrow", "x": 240, "y": 110, "width": 160,
         "height": 1, "points": [[0, 0], [160, 0]], "strokeColor": "#64707A",
         "backgroundColor": "transparent", "startArrowhead": None, "endArrowhead": "arrow",
         "startBinding": {"elementId": "n1", "focus": 0, "gap": 0},
         "endBinding": {"elementId": "n2", "focus": 0, "gap": 0},
         "meta": {"semantic_edge_id": "edge:n12n2"}},
        {"id": "label1", "type": "text", "x": 120, "y": 100, "width": 80,
         "height": 22.5, "text": "One", "fontSize": 18, "containerId": "n1",
         "strokeColor": "#173C45", "backgroundColor": "transparent"},
    ]
    return manifest


def test_compact_native_scene_normalizes_and_validates_without_visual_drift():
    from copy import deepcopy
    from evo_diagram.agentic_system.generation_stage.unified.native_defaults import complete_native_elements
    from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import check_arrow_shape_binding

    manifest = _compact_native_scene()
    authored = deepcopy(manifest)
    state = UnifiedWorkflowState(diagram_manifest=manifest)
    workflow = object.__new__(UnifiedGeneratorWorkflow)
    workflow._run_normalizer(state)
    workflow._run_validator(state)
    completed = {element["id"]: element for element in manifest["elements"]}
    for original in authored["elements"]:
        for key, value in original.items():
            actual = completed[original["id"]][key]
            if key == "meta":
                assert all(actual[name] == content for name, content in value.items())
            else:
                assert actual == value
    assert {item["id"] for item in completed["n1"]["boundElements"]} == {"arrow1", "label1"}
    assert completed["label1"]["originalText"] == "One"
    assert completed["label1"]["fontFamily"] == 2
    assert completed["n1"]["seed"] != completed["n2"]["seed"]
    assert not check_arrow_shape_binding(manifest)
    once = deepcopy(manifest)
    complete_native_elements(manifest)
    assert manifest == once


@pytest.mark.parametrize("fault", ["geometry", "reference"])
def test_native_completion_leaves_missing_geometry_and_bad_references_invalid(fault):
    from evo_diagram.agentic_system.generation_stage.unified.native_defaults import complete_native_elements
    manifest = _compact_native_scene()
    if fault == "geometry":
        manifest["elements"][0].pop("width")
    else:
        manifest["elements"][2]["endBinding"]["elementId"] = "missing_target"
    complete_native_elements(manifest)
    workflow = object.__new__(UnifiedGeneratorWorkflow)
    with pytest.raises(ValueError, match="schema validation failed"):
        workflow._run_validator(UnifiedWorkflowState(diagram_manifest=manifest))


def test_native_completion_preserves_explicit_metadata_and_typography():
    from evo_diagram.agentic_system.generation_stage.unified.native_defaults import complete_native_elements
    manifest = _compact_native_scene()
    label = manifest["elements"][-1]
    label.update(fontFamily=3, lineHeight=1.4, autoResize=False, roughness=1, seed=42)
    complete_native_elements(manifest)
    assert {key: label[key] for key in ("fontFamily", "lineHeight", "autoResize", "roughness", "seed")} == {
        "fontFamily": 3, "lineHeight": 1.4, "autoResize": False, "roughness": 1, "seed": 42,
    }
