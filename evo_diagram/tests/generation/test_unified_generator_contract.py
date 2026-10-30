from __future__ import annotations

import pytest

from evo_diagram.agentic_system.generation_stage.unified.generator import UnifiedGenerator
from evo_diagram.agentic_system.generation_stage.unified.state import UnifiedWorkflowState
from evo_diagram.agentic_system.generation_stage.unified.workflow import UnifiedGeneratorWorkflow


def _generator_with_output(output):
    generator = object.__new__(UnifiedGenerator)
    generator.full_domain_knowledge = True
    generator._last_raw_output = None
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
