"""Refinement stage tests."""
from copy import deepcopy

import pytest


@pytest.mark.parametrize("operation,payload", [
    ("set_style", {"opacity": 0}),
    ("set_style", {"strokeWidth": 0}),
    ("set_style", {"strokeColor": "transparent"}),
    ("delete_element", {}),
])
def test_visual_refiner_cannot_erase_semantic_connectors(operation, payload):
    from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
    from evo_diagram.agentic_system.refinement_stage.state import EditOp

    manifest = {
        "elements": [{"id": "a", "type": "arrow", "opacity": 62,
                      "meta": {"semantic_edge_id": "requires"}}],
        "_meta": {"id_map": {"requires": "a"}},
    }
    original = deepcopy(manifest)
    result, outcomes = apply_edits(manifest, [
        EditOp(op=operation, id="a", payload=payload, source="llm"),
    ])
    assert result == original
    assert not outcomes[0].applied
    assert "semantic" in outcomes[0].error


@pytest.mark.parametrize("payload", [
    {"strokeWidth": 0},
    {"strokeColor": "#f8fcf7", "backgroundColor": "#f8fcf7"},
])
def test_refiner_keeps_visible_boundary_on_fact_bearing_heading(payload):
    from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
    from evo_diagram.agentic_system.refinement_stage.state import EditOp

    manifest = {
        "elements": [{"id": "heading", "type": "rectangle", "strokeWidth": 1,
                      "meta": {"conceptFactAnchor": True}}],
        "_meta": {"id_map": {"category": "heading"}},
    }
    result, outcomes = apply_edits(manifest, [
        EditOp(op="set_style", id="heading", payload=payload, source="llm"),
    ])
    assert result["elements"][0]["strokeWidth"] == 1
    assert not outcomes[0].applied


class TestFixers:
    def test_edit_op_has_expected_ops(self):
        from evo_diagram.agentic_system.refinement_stage.state import EditOp
        ops = str(EditOp.model_fields["op"].annotation)
        for expected in [
            "set_position",
            "set_size",
            "set_style",
            "set_text",
            "delete_element",
            "clear_container_binding",
            "remove_bound_element",
        ]:
            assert expected in ops

    def test_refinement_workflow_importable(self):
        from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow
        assert IterativeRefinerWorkflow is not None

    def test_refinement_state_importable(self):
        from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState
        assert VerifierRefinerState is not None

    def test_deterministic_fixers_importable(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import run_all_deterministic_fixers
        assert callable(run_all_deterministic_fixers)

    def test_deterministic_fixer_exception_is_not_swallowed(self, monkeypatch):
        from evo_diagram.agentic_system.refinement_stage.fixers import deterministic

        def failing_fixer(manifest, findings, structure=None):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            deterministic,
            "_FIXERS",
            (("failing", failing_fixer),),
        )

        with pytest.raises(deterministic.DeterministicFixerError, match="failing"):
            deterministic.run_all_deterministic_fixers({"elements": []}, [])

    def test_apply_edits_importable(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        assert callable(apply_edits)

    def test_patch_schema_defaults_uses_stable_seeds_and_preserves_existing_values(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            patch_schema_defaults,
        )

        original = {
            "elements": [
                {"id": "n1", "type": "rectangle"},
                {
                    "id": "n2",
                    "type": "rectangle",
                    "seed": 123,
                    "versionNonce": 456,
                },
            ]
        }
        first = deepcopy(original)
        second = deepcopy(original)

        patch_schema_defaults(first)
        patch_schema_defaults(second)

        assert first == second
        assert first["elements"][0]["seed"] != first["elements"][0]["versionNonce"]
        assert 1 <= first["elements"][0]["seed"] <= 2_000_000_000
        assert 1 <= first["elements"][0]["versionNonce"] <= 2_000_000_000
        assert first["elements"][1]["seed"] == 123
        assert first["elements"][1]["versionNonce"] == 456

    def test_refiner_state_rejects_non_excalidraw_canvas_library(self):
        from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState

        state = VerifierRefinerState(
            manifest_path="/tmp/manifest.json",
            image_path="/tmp/image.png",
            canvas_library=" Excalidraw ",
        )

        assert state.canvas_library == "excalidraw"
        with pytest.raises(ValueError, match="Excalidraw"):
            VerifierRefinerState(
                manifest_path="/tmp/manifest.json",
                image_path="/tmp/image.png",
                canvas_library="tldraw",
            )

    def test_apply_edits_reports_missing_elements_list(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest, outcomes = apply_edits(
            {},
            [EditOp(op="set_position", id="n1", payload={"x": 1, "y": 2})],
        )

        assert manifest == {}
        assert outcomes[0].applied is False
        assert outcomes[0].error == "manifest has no elements list"

    def test_set_style_mutates_and_bumps_version(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {"id": "n1", "type": "rectangle", "version": 3},
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [
                EditOp(
                    op="set_style",
                    id="n1",
                    payload={"backgroundColor": "#fff"},
                ),
            ],
        )

        assert outcomes[0].applied is True
        assert manifest["elements"][0]["backgroundColor"] == "#fff"
        assert manifest["elements"][0]["version"] == 4

    def test_set_style_rejects_unknown_keys_without_partial_mutation(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {"id": "n1", "type": "rectangle", "version": 3},
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [
                EditOp(
                    op="set_style",
                    id="n1",
                    payload={"backgroundColor": "#fff", "unknown": "rejected"},
                ),
            ],
        )

        assert outcomes[0].applied is False
        assert "unknown style keys" in outcomes[0].error
        assert "backgroundColor" not in manifest["elements"][0]
        assert "unknown" not in manifest["elements"][0]
        assert manifest["elements"][0]["version"] == 3

    def test_set_position_moves_bound_text_with_container(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "x": 10,
                    "y": 20,
                    "width": 120,
                    "height": 60,
                    "version": 1,
                    "boundElements": [{"id": "text", "type": "text"}],
                },
                {
                    "id": "text",
                    "type": "text",
                    "containerId": "shape",
                    "x": 35,
                    "y": 38,
                    "width": 70,
                    "height": 24,
                    "version": 1,
                },
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [EditOp(op="set_position", id="shape", payload={"x": 30, "y": 50})],
        )

        assert outcomes[0].applied is True
        assert manifest["elements"][0]["x"] == 30
        assert manifest["elements"][0]["y"] == 50
        assert manifest["elements"][1]["x"] == 55
        assert manifest["elements"][1]["y"] == 68
        assert manifest["elements"][1]["version"] == 2

    def test_set_size_recenters_bound_text_inside_container(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "x": 10,
                    "y": 20,
                    "width": 120,
                    "height": 60,
                    "version": 1,
                    "boundElements": [{"id": "text", "type": "text"}],
                },
                {
                    "id": "text",
                    "type": "text",
                    "containerId": "shape",
                    "x": 35,
                    "y": 38,
                    "width": 70,
                    "height": 24,
                    "version": 1,
                },
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [EditOp(op="set_size", id="shape", payload={"width": 200, "height": 100})],
        )

        assert outcomes[0].applied is True
        assert manifest["elements"][0]["width"] == 200
        assert manifest["elements"][0]["height"] == 100
        assert manifest["elements"][1]["x"] == 75
        assert manifest["elements"][1]["y"] == 58
        assert manifest["elements"][1]["version"] == 2

    def test_clear_arrow_binding_strips_shape_back_reference(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "boundElements": [{"id": "arrow", "type": "arrow"}],
                    "version": 1,
                },
                {
                    "id": "arrow",
                    "type": "arrow",
                    "startBinding": {"elementId": "shape"},
                    "version": 1,
                },
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [EditOp(op="clear_arrow_binding", id="arrow", payload={"side": "start"})],
        )

        assert outcomes[0].applied is True
        assert manifest["elements"][1]["startBinding"] is None
        assert manifest["elements"][0]["boundElements"] == []
        assert manifest["elements"][0]["version"] == 2

        _, repeat_outcomes = apply_edits(
            manifest,
            [EditOp(op="clear_arrow_binding", id="arrow", payload={"side": "start"})],
        )

        assert repeat_outcomes[0].applied is False
        assert manifest["elements"][1]["version"] == 2

    def test_append_bound_element_reports_duplicate_as_noop(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "boundElements": [{"id": "arrow", "type": "arrow"}],
                    "version": 1,
                },
                {"id": "arrow", "type": "arrow"},
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [
                EditOp(
                    op="append_bound_element",
                    id="shape",
                    payload={"bound_id": "arrow", "type": "arrow"},
                )
            ],
        )

        assert outcomes[0].applied is False
        assert manifest["elements"][0]["boundElements"] == [{"id": "arrow", "type": "arrow"}]
        assert manifest["elements"][0]["version"] == 1

    def test_remove_bound_element_strips_only_matching_ref(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "boundElements": [
                        {"id": "arrow", "type": "arrow"},
                        {"id": "ghost", "type": "arrow"},
                    ],
                    "version": 1,
                },
                {"id": "arrow", "type": "arrow", "version": 1},
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [EditOp(op="remove_bound_element", id="shape", payload={"bound_id": "ghost"})],
        )

        assert outcomes[0].applied is True
        assert manifest["elements"][0]["boundElements"] == [
            {"id": "arrow", "type": "arrow"},
        ]
        assert manifest["elements"][0]["version"] == 2

        _, repeat_outcomes = apply_edits(
            manifest,
            [EditOp(op="remove_bound_element", id="shape", payload={"bound_id": "ghost"})],
        )

        assert repeat_outcomes[0].applied is False
        assert manifest["elements"][0]["boundElements"] == [
            {"id": "arrow", "type": "arrow"},
        ]
        assert manifest["elements"][0]["version"] == 2

    def test_clear_container_binding_detaches_text_and_container_back_reference(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "boundElements": [{"id": "text", "type": "text"}],
                    "version": 1,
                },
                {
                    "id": "text",
                    "type": "text",
                    "containerId": "shape",
                    "version": 1,
                },
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [
                EditOp(
                    op="clear_container_binding",
                    id="text",
                    payload={"container_id": "shape"},
                )
            ],
        )

        assert outcomes[0].applied is True
        assert manifest["elements"][1]["containerId"] is None
        assert manifest["elements"][1]["version"] == 2
        assert manifest["elements"][0]["boundElements"] == []
        assert manifest["elements"][0]["version"] == 2

        _, stale_outcomes = apply_edits(
            manifest,
            [
                EditOp(
                    op="clear_container_binding",
                    id="text",
                    payload={"container_id": "shape"},
                )
            ],
        )

        assert stale_outcomes[0].applied is False
        assert stale_outcomes[0].error is None

    def test_delete_element_reports_already_deleted_as_noop(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "isDeleted": True,
                    "version": 3,
                },
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [EditOp(op="delete_element", id="shape", payload={})],
        )

        assert outcomes[0].applied is False
        assert manifest["elements"][0]["isDeleted"] is True
        assert manifest["elements"][0]["version"] == 3

    def test_deterministic_fixer_removes_dangling_bound_element_from_verifier_finding(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            run_all_deterministic_fixers,
        )
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_shape_binding,
        )

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "boundElements": [{"id": "ghost", "type": "arrow"}],
                    "version": 1,
                },
            ],
        }

        findings = check_arrow_shape_binding(manifest)

        assert len(findings) == 1
        assert findings[0].category == "binding/dangling_reference"
        assert findings[0].element_id == "shape"
        assert findings[0].location == {
            "holder_id": "shape",
            "missing_bound_id": "ghost",
        }

        edits = run_all_deterministic_fixers(manifest, findings)

        assert len(edits) == 1
        assert edits[0].op == "remove_bound_element"
        assert edits[0].id == "shape"
        assert edits[0].payload == {"bound_id": "ghost"}

        apply_edits(manifest, edits)

        assert manifest["elements"][0]["boundElements"] == []
        assert check_arrow_shape_binding(manifest) == []

    def test_deterministic_fixer_clears_dangling_text_container(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            run_all_deterministic_fixers,
        )
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_shape_binding,
        )

        manifest = {
            "elements": [
                {
                    "id": "label",
                    "type": "text",
                    "containerId": "ghost",
                    "version": 1,
                },
            ],
        }

        findings = check_arrow_shape_binding(manifest)

        assert len(findings) == 1
        assert findings[0].category == "binding/dangling_reference"
        assert findings[0].element_id == "label"
        assert findings[0].location == {"missing_container_id": "ghost"}

        edits = run_all_deterministic_fixers(manifest, findings)

        assert len(edits) == 1
        assert edits[0].op == "clear_container_binding"
        assert edits[0].id == "label"
        assert edits[0].payload == {"container_id": "ghost"}

        apply_edits(manifest, edits)

        assert manifest["elements"][0]["containerId"] is None
        assert check_arrow_shape_binding(manifest) == []

    def test_binding_checker_treats_deleted_container_as_dangling(self):
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_shape_binding,
        )

        manifest = {
            "elements": [
                {
                    "id": "shape",
                    "type": "rectangle",
                    "isDeleted": True,
                },
                {
                    "id": "label",
                    "type": "text",
                    "containerId": "shape",
                },
            ],
        }

        findings = check_arrow_shape_binding(manifest)

        assert len(findings) == 1
        assert findings[0].category == "binding/dangling_reference"
        assert findings[0].element_id == "label"
        assert findings[0].location == {"missing_container_id": "shape"}

    def test_group_zorder_fixer_ignores_legacy_aggregated_findings(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_group_frame_zorder,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "id_map": {"g_lane:background": "bg1"},
            "elements": [{"id": "bg1", "type": "rectangle", "index": "z999"}],
        }
        findings = [
            Finding(
                category="render_validation/audit",
                severity=Severity.MINOR,
                message="zorder issue in a frame",
            )
        ]

        assert fix_group_frame_zorder(manifest, findings) == []

    def test_group_zorder_fixer_uses_structured_element_findings(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_group_frame_zorder,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {"elements": [{"id": "bg1", "type": "rectangle", "index": "z999"}]}
        findings = [
            Finding(
                category="render_validation/audit/zorder",
                severity=Severity.MINOR,
                message="frame should render below children",
                element_id="bg1",
            )
        ]

        edits = fix_group_frame_zorder(manifest, findings)

        assert len(edits) == 1
        assert edits[0].op == "set_index"
        assert edits[0].id == "bg1"

    def test_group_zorder_fixer_reindexes_manifest_without_duplicate_indices(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_group_frame_zorder,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "_meta": {
                "id_map": {
                    "lane:background": "bg1",
                    "n1": "child1",
                }
            },
            "elements": [
                {
                    "id": "child1",
                    "type": "rectangle",
                    "x": 20,
                    "y": 20,
                    "width": 80,
                    "height": 40,
                    "index": "a00000",
                },
                {
                    "id": "bg1",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 140,
                    "height": 90,
                    "index": "z99999",
                },
            ],
        }
        findings = [
            Finding(
                category="render_validation/audit/zorder",
                severity=Severity.MINOR,
                message="frame should render below children",
                element_id="bg1",
            )
        ]

        edits = fix_group_frame_zorder(manifest, findings)
        _, outcomes = apply_edits(manifest, edits)
        by_id = {element["id"]: element for element in manifest["elements"]}
        indices = [element["index"] for element in manifest["elements"]]

        assert all(outcome.applied for outcome in outcomes)
        assert len(indices) == len(set(indices))
        assert by_id["bg1"]["index"] < by_id["child1"]["index"]

    def test_node_overlap_fixer_ignores_group_frame_false_positive_in_either_order(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_node_overlap,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "_meta": {
                "id_map": {
                    "service_layer:background": "frame1",
                    "service_api": "child1",
                }
            },
            "elements": [
                {
                    "id": "frame1",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 360,
                    "height": 220,
                },
                {
                    "id": "child1",
                    "type": "rectangle",
                    "x": 40,
                    "y": 64,
                    "width": 120,
                    "height": 72,
                },
            ],
        }
        findings = [
            Finding(
                category="collision/node_overlap",
                severity=Severity.MAJOR,
                message="legacy frame overlap false positive",
                element_id="frame1",
                location={
                    "a": [0, 0, 360, 220],
                    "b": [40, 64, 120, 72],
                    "other_id": "child1",
                },
            ),
            Finding(
                category="collision/node_overlap",
                severity=Severity.MAJOR,
                message="legacy frame overlap false positive",
                element_id="child1",
                location={
                    "a": [40, 64, 120, 72],
                    "b": [0, 0, 360, 220],
                    "other_id": "frame1",
                },
            ),
        ]

        assert fix_node_overlap(manifest, findings) == []

    def test_node_overlap_fixer_still_moves_real_node_overlap(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_node_overlap,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "elements": [
                {
                    "id": "node_a",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 100,
                },
                {
                    "id": "node_b",
                    "type": "rectangle",
                    "x": 50,
                    "y": 0,
                    "width": 100,
                    "height": 100,
                },
            ],
        }
        findings = [
            Finding(
                category="collision/node_overlap",
                severity=Severity.MAJOR,
                message="real node overlap",
                element_id="node_a",
                location={
                    "a": [0, 0, 100, 100],
                    "b": [50, 0, 100, 100],
                    "other_id": "node_b",
                },
            )
        ]

        edits = fix_node_overlap(manifest, findings)

        assert len(edits) == 1
        assert edits[0].op == "set_position"
        assert edits[0].id == "node_a"
        assert edits[0].payload == {"x": -54.0, "y": 0.0}

    def test_contrast_fixer_ignores_legacy_aggregated_findings(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_low_contrast,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "elements": [
                {
                    "id": "box",
                    "type": "rectangle",
                    "backgroundColor": "#ffffff",
                },
                {
                    "id": "text",
                    "type": "text",
                    "containerId": "box",
                    "strokeColor": "#ffffff",
                },
            ],
        }
        findings = [
            Finding(
                category="render_validation/audit",
                severity=Severity.MINOR,
                message="contrast issue found",
            )
        ]

        assert fix_low_contrast(manifest, findings) == []

    def test_contrast_fixer_uses_structured_element_findings(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_low_contrast,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "elements": [
                {
                    "id": "box",
                    "type": "rectangle",
                    "backgroundColor": "#ffffff",
                },
                {
                    "id": "text",
                    "type": "text",
                    "containerId": "box",
                    "strokeColor": "#ffffff",
                },
            ],
        }
        findings = [
            Finding(
                category="render_validation/audit/contrast",
                severity=Severity.MINOR,
                message="text contrast below AA",
                element_id="text",
            )
        ]

        edits = fix_low_contrast(manifest, findings)

        assert len(edits) == 1
        assert edits[0].op == "set_style"
        assert edits[0].id == "text"
        assert edits[0].payload == {"strokeColor": "#1e1e1e"}
