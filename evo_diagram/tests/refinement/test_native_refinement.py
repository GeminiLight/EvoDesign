import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from evo_diagram.agentic_system.generation_stage.unified.native_defaults import (
    complete_native_elements, complete_native_semantics,
)
from evo_diagram.agentic_system.generation_stage.unified.sidecar import validate_semantic_sidecar
from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow
from evo_diagram.agentic_system.refinement_stage.state import EditOp
from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow


def _native_scene():
    return {
        "type": "excalidraw/clipboard", "files": {}, "appState": {},
        "elements": [
            {"id": "shape-a", "type": "rectangle", "x": 100, "y": 100,
             "width": 120, "height": 60, "strokeColor": "#334155", "backgroundColor": "#ffffff"},
            {"id": "shape-b", "type": "rectangle", "x": 420, "y": 100,
             "width": 120, "height": 60, "strokeColor": "#334155", "backgroundColor": "#ffffff"},
            {"id": "authored-arrow", "type": "arrow", "x": 220, "y": 130,
             "width": 200, "height": 0, "strokeColor": "#123456", "backgroundColor": "transparent",
             "points": [[0, 0], [200, 0]], "elbowed": True,
             "startBinding": {"elementId": "shape-a", "focus": 0, "gap": 0},
             "endBinding": {"elementId": "shape-b", "focus": 0, "gap": 0},
             "startArrowhead": None, "endArrowhead": "arrow", "meta": {"semantic_edge_id": "edge:a2b"}},
            {"id": "authored-label", "type": "text", "x": 263, "y": 101,
             "width": 114, "height": 21.25, "fontSize": 17, "text": "depends on",
             "strokeColor": "#234567", "backgroundColor": "transparent", "containerId": None},
        ],
        "_meta": {
            "structure_instantiation": {
                "chart_type": "concept_map",
                "nodes": [{"id": key, "label": key, "class": "concept"} for key in ("a", "b")],
                "edges": [{"id": "edge:a2b", "source": "a", "target": "b", "label": "depends on"}],
                "groups": [],
            },
            "id_map": {"a": "shape-a", "b": "shape-b", "edge:a2b": "authored-arrow",
                       "edge:a2b:label": "authored-label"},
        },
    }


def test_native_refinement_moves_node_reroutes_and_preserves_single_mapped_label(tmp_path, monkeypatch):
    manifest = _native_scene()
    authored = deepcopy(manifest)
    complete_native_elements(manifest)
    complete_native_semantics(manifest)
    structure = validate_semantic_sidecar(manifest)
    for old, completed in zip(authored["elements"], manifest["elements"]):
        for key in ("x", "y", "width", "height", "strokeColor", "backgroundColor"):
            assert completed[key] == old[key]
    scene_path, structure_path, image_path = (tmp_path / name for name in ("scene.json", "structure.json", "scene.png"))
    scene_path.write_text(json.dumps(manifest))
    structure_path.write_text(json.dumps(structure))
    image_path.write_bytes(b"test input image")
    render_calls = []

    def fake_render(scene, output_path, **_kwargs):
        render_calls.append(deepcopy(scene))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"test render")
        return SimpleNamespace(ok=True, output_path=output_path, error="")

    class MoveNode:
        last_exhaustion_error = None

        def propose_edits(self, **_kwargs):
            return [EditOp(op="set_position", id="shape-b", payload={"x": 420, "y": 300}, source="llm")]

    monkeypatch.setattr("evo_diagram.agentic_system.iterative_workflow.render_png_result", fake_render)
    state = IterativeRefinerWorkflow(llm_agent=MoveNode()).run(
        manifest_path=str(scene_path), image_path=str(image_path),
        structure_path=str(structure_path), output_dir=str(tmp_path / "refined"),
        max_iterations=1, skip_checks=["layout_audit"],
    )
    assert not state.errors
    assert state.converged
    assert render_calls
    assert not any("missing_layout" in finding.category for finding in state.latest_findings)
    result = state.manifest
    validate_semantic_sidecar(result)
    by_id = {element["id"]: element for element in result["elements"]}
    assert by_id["shape-b"]["y"] == 300
    assert "authored-arrow" not in by_id and "authored-label" not in by_id
    assert all(value in by_id for value in result["_meta"]["id_map"].values())
    labels = [element for element in by_id.values() if element.get("type") == "text"]
    assert len(labels) == 1
    assert labels[0]["text"] == "depends on"
    assert labels[0]["fontSize"] == 17 and labels[0]["strokeColor"] == "#234567"
    arrow = by_id[result["_meta"]["id_map"]["edge:a2b"]]
    assert arrow["strokeColor"] == "#123456"
    assert arrow["y"] + arrow["points"][-1][1] >= 300


def test_native_metadata_rejects_conflicting_label_ownership():
    manifest = _native_scene()
    manifest["elements"][-1]["meta"] = {"semantic_edge_id": "edge:other2edge"}
    with pytest.raises(ValueError, match="conflicting label mapping"):
        complete_native_semantics(manifest)


def test_excalidraw_native_pipeline_accepts_explicit_refinement():
    workflow = Text2DiagramWorkflow(
        FakeListChatModel(responses=["{}"]), mode="oneshot", enable_refiner=True,
    )
    assert workflow._should_refine()
