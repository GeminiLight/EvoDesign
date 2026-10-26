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

    # ------------------------------------------------------------------
    # Contrast target selection
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "background",
        ["#4a90d9", "#e67e22", "#7a9e7e"],
    )
    def test_contrast_fixer_picks_target_by_measured_ratio(self, background):
        """Mid-light fills need DARK text even though luminance is below 0.5.

        The old ``lum >= 0.5`` threshold sent white text onto all three of
        these (3.34 / 2.85 / 2.99 — all failing AA) while dark text cleared it
        (4.99 / 5.85 / 5.57). The crossover for this _DARK/_LIGHT pair is at
        L≈0.2072, so the choice must be measured, not thresholded.
        """
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            _contrast_ratio,
            _hex_to_rgb,
            fix_low_contrast,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "elements": [
                {"id": "box", "type": "rectangle", "backgroundColor": background},
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
                severity=Severity.MAJOR,
                message="text contrast below AA",
                element_id="text",
            )
        ]

        edits = fix_low_contrast(manifest, findings)

        assert [e.payload for e in edits] == [{"strokeColor": "#1e1e1e"}]
        chosen = _contrast_ratio(_hex_to_rgb("#1e1e1e"), _hex_to_rgb(background))
        rejected = _contrast_ratio(_hex_to_rgb("#ffffff"), _hex_to_rgb(background))
        assert chosen >= 4.5 > rejected

    def test_contrast_fixer_repaints_background_when_neither_text_color_passes(self):
        """A mid-tone fill caps contrast below AA — spinning is not an option.

        With ``#808080`` the best candidate reaches only 4.22, so emitting the
        text edit alone would leave the MAJOR standing while the next round
        short-circuits on ``strokeColor == target`` and emits nothing at all.
        """
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_low_contrast,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "elements": [
                {"id": "box", "type": "rectangle", "backgroundColor": "#808080"},
                {
                    "id": "text",
                    "type": "text",
                    "containerId": "box",
                    "strokeColor": "#1e1e1e",
                },
            ],
        }
        findings = [
            Finding(
                category="render_validation/audit/contrast",
                severity=Severity.MAJOR,
                message="text contrast below AA",
                element_id="text",
            )
        ]

        edits = fix_low_contrast(manifest, findings)

        # Text already carries the better colour, so the only useful edit left
        # is on the container — the fixer must not return an empty list.
        assert [(e.id, e.payload) for e in edits] == [
            ("box", {"backgroundColor": "#ffffff"})
        ]

    # ------------------------------------------------------------------
    # Overlap displacement ledger
    # ------------------------------------------------------------------

    def test_node_overlap_fixer_merges_two_findings_naming_the_same_element(self):
        """n1 overlapping both n2 and n3 must move once, accounting for both.

        ``check_node_overlap`` puts the first shape of every pair in
        ``element_id``, so one crowded node produces several findings all
        naming it. Computed against the same unmodified manifest they became
        several absolute ``set_position`` edits, and only the last survived —
        with every outcome still reporting ``applied=True``.
        """
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import (
            apply_edits,
        )
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_node_overlap,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "elements": [
                {"id": "n1", "type": "rectangle", "x": 100, "y": 100, "width": 100, "height": 60},
                {"id": "n2", "type": "rectangle", "x": 180, "y": 100, "width": 100, "height": 60},
                {"id": "n3", "type": "rectangle", "x": 100, "y": 140, "width": 100, "height": 60},
            ],
        }
        findings = [
            Finding(
                category="collision/node_overlap",
                severity=Severity.MAJOR,
                message="n1 overlaps n2",
                element_id="n1",
                location={"a": [100, 100, 100, 60], "b": [180, 100, 100, 60], "other_id": "n2"},
            ),
            Finding(
                category="collision/node_overlap",
                severity=Severity.MAJOR,
                message="n1 overlaps n3",
                element_id="n1",
                location={"a": [100, 100, 100, 60], "b": [100, 140, 100, 60], "other_id": "n3"},
            ),
        ]

        edits = fix_node_overlap(manifest, findings)

        assert [e.id for e in edits] == ["n1"]
        apply_edits(manifest, edits)
        n1 = manifest["elements"][0]
        # Both pushes are present: horizontal away from n2, vertical away from n3.
        assert n1["x"] != 100
        assert n1["y"] != 100
        # And the result actually separates n1 from both counterparts.
        for other in manifest["elements"][1:]:
            assert (
                n1["x"] + n1["width"] <= other["x"]
                or other["x"] + other["width"] <= n1["x"]
                or n1["y"] + n1["height"] <= other["y"]
                or other["y"] + other["height"] <= n1["y"]
            )

    # ------------------------------------------------------------------
    # Canvas clamping
    # ------------------------------------------------------------------

    def test_out_of_canvas_fixer_leaves_oversized_lane_background_alone(self):
        """A lane as wide as the canvas can never satisfy the safe area.

        Clamping it re-emits the same MINOR every round and, worse, drags the
        lane out from under its members without moving them.
        """
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_out_of_canvas,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "_meta": {"id_map": {"lane:background": "lane_bg", "n1": "n1"}},
            "elements": [
                {"id": "lane_bg", "type": "rectangle", "x": 0, "y": 0, "width": 4000, "height": 300},
                {"id": "n1", "type": "rectangle", "x": 40, "y": 40, "width": 120, "height": 60},
            ],
        }
        findings = [
            Finding(
                category="collision/out_of_canvas",
                severity=Severity.MINOR,
                message="lane background violates canvas safe area",
                element_id="lane_bg",
                location={"x": 0, "y": 0, "w": 4000, "h": 300},
            )
        ]

        assert fix_out_of_canvas(manifest, findings) == []

    def test_out_of_canvas_fixer_moves_frame_members_by_the_same_delta(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import (
            apply_edits,
        )
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_out_of_canvas,
        )
        from evo_diagram.agentic_system.verification_stage.checks.finding import (
            Finding,
            Severity,
        )

        manifest = {
            "_meta": {"id_map": {"lane:background": "lane_bg", "n1": "n1"}},
            "elements": [
                {"id": "lane_bg", "type": "rectangle", "x": -60, "y": 40, "width": 400, "height": 200},
                {"id": "n1", "type": "rectangle", "x": -20, "y": 80, "width": 120, "height": 60},
            ],
        }
        findings = [
            Finding(
                category="collision/out_of_canvas",
                severity=Severity.MINOR,
                message="lane background violates canvas safe area",
                element_id="lane_bg",
                location={"x": -60, "y": 40, "w": 400, "h": 200},
            )
        ]

        edits = fix_out_of_canvas(manifest, findings)
        assert sorted(e.id for e in edits) == ["lane_bg", "n1"]

        apply_edits(manifest, edits)
        lane, node = manifest["elements"]
        assert lane["x"] == 16.0  # CANVAS_MARGIN
        # The member kept its offset inside the lane instead of being left behind.
        assert node["x"] - lane["x"] == 40.0
        assert node["y"] == 80

    # ------------------------------------------------------------------
    # Dangling bindings dispatch
    # ------------------------------------------------------------------

    def test_dangling_binding_fixer_removes_stale_label_ref_from_an_arrow(self):
        """Arrows carry labels, so they hit the boundElements finding too.

        The old type-based dispatch handled ``boundElements`` only in the
        non-arrow / non-text branch, so this MAJOR came back every round with
        no edit able to clear it.
        """
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            fix_dangling_bindings,
        )
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_shape_binding,
        )

        manifest = {
            "elements": [
                {
                    "id": "arrow1",
                    "type": "arrow",
                    "x": 0,
                    "y": 0,
                    "points": [[0, 0], [50, 0]],
                    "boundElements": [{"id": "ghost_label", "type": "text"}],
                },
            ],
        }
        findings = check_arrow_shape_binding(manifest)
        assert [f.category for f in findings] == ["binding/dangling_reference"]

        edits = fix_dangling_bindings(manifest, findings)

        assert len(edits) == 1
        assert edits[0].op == "remove_bound_element"
        assert edits[0].id == "arrow1"
        assert edits[0].payload == {"bound_id": "ghost_label"}

    # ------------------------------------------------------------------
    # Arrow geometry
    # ------------------------------------------------------------------

    def test_set_position_and_set_size_refuse_arrow_targets(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import (
            apply_edits,
        )
        from evo_diagram.agentic_system.refinement_stage.state import EditOp

        manifest = {
            "elements": [
                {
                    "id": "arrow1",
                    "type": "arrow",
                    "x": 0,
                    "y": 0,
                    "width": 50,
                    "height": 1,
                    "points": [[0, 0], [50, 0]],
                },
            ],
        }

        _, outcomes = apply_edits(
            manifest,
            [
                EditOp(op="set_position", id="arrow1", payload={"x": 500, "y": 500}),
                EditOp(op="set_size", id="arrow1", payload={"width": 10, "height": 10}),
            ],
        )

        assert [o.applied for o in outcomes] == [False, False]
        assert all("not directly editable" in (o.error or "") for o in outcomes)
        assert manifest["elements"][0]["x"] == 0
        assert manifest["elements"][0]["width"] == 50

    def test_manifest_summary_omits_arrows(self):
        from evo_diagram.agentic_system.refinement_stage.agent.llm_agent import (
            build_manifest_summary,
        )

        manifest = {
            "elements": [
                {"id": "n1", "type": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10},
                {"id": "a1", "type": "arrow", "x": 0, "y": 0, "width": 10, "height": 10},
            ]
        }

        assert [e["id"] for e in build_manifest_summary(manifest)] == ["n1"]

    def test_reorder_elements_by_index_restores_array_order(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            reorder_elements_by_index,
        )

        manifest = {
            "elements": [
                {"id": "child", "type": "rectangle", "index": "a00001"},
                {"id": "bg", "type": "rectangle", "index": "a00000"},
            ]
        }

        assert reorder_elements_by_index(manifest) is True
        assert [e["id"] for e in manifest["elements"]] == ["bg", "child"]
        # Idempotent once the array agrees with the indices.
        assert reorder_elements_by_index(manifest) is False

    def test_reorder_elements_by_index_refuses_partial_indices(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.deterministic import (
            reorder_elements_by_index,
        )

        manifest = {
            "elements": [
                {"id": "child", "type": "rectangle", "index": "a00001"},
                {"id": "bg", "type": "rectangle"},
            ]
        }

        assert reorder_elements_by_index(manifest) is False
        assert [e["id"] for e in manifest["elements"]] == ["child", "bg"]


def _arrow_manifest(*, with_bindings: bool = True):
    arrow = {
        "id": "a1",
        "type": "arrow",
        "x": 100.0,
        "y": 30.0,
        "width": 200.0,
        "height": 1.0,
        "points": [[0.0, 0.0], [200.0, 0.0]],
        "boundElements": [{"id": "a1_label", "type": "text"}],
    }
    if with_bindings:
        arrow["startBinding"] = {"elementId": "n1", "focus": 0, "gap": 0}
        arrow["endBinding"] = {"elementId": "n2", "focus": 0, "gap": 0}
    else:
        arrow["meta"] = {"semantic_edge_id": "edge:n1n2", "source": "n1", "target": "n2"}
    back_refs = [{"id": "a1", "type": "arrow"}] if with_bindings else []
    return {
        "_meta": {"id_map": {"n1": "n1", "n2": "n2"}},
        "elements": [
            {
                "id": "n1", "type": "rectangle", "x": 0, "y": 0,
                "width": 100, "height": 60, "boundElements": list(back_refs),
            },
            {
                "id": "n2", "type": "rectangle", "x": 300, "y": 0,
                "width": 100, "height": 60, "boundElements": list(back_refs),
            },
            arrow,
            {
                "id": "a1_label",
                "type": "text",
                "containerId": "a1",
                "x": 180.0,
                "y": 20.0,
                "width": 40.0,
                "height": 20.0,
            },
        ],
    }


class TestArrowGeometryRepair:
    """Arrows must follow the shapes they connect (bug #2)."""

    def test_reroute_is_a_noop_while_the_arrow_still_touches_both_shapes(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.arrow_reroute import (
            reroute_bound_arrows,
        )

        manifest = _arrow_manifest()
        before = deepcopy(manifest)

        assert reroute_bound_arrows(manifest) == []
        assert manifest == before

    def test_reroute_follows_a_moved_endpoint_shape_and_carries_its_label(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import (
            apply_edits,
        )
        from evo_diagram.agentic_system.refinement_stage.fixers.arrow_reroute import (
            reroute_bound_arrows,
        )
        from evo_diagram.agentic_system.refinement_stage.state import EditOp
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_endpoint_geometry,
        )

        manifest = _arrow_manifest()
        label_before = dict(manifest["elements"][3])

        _, outcomes = apply_edits(
            manifest,
            [EditOp(op="set_position", id="n2", payload={"x": 300, "y": 600})],
        )
        assert outcomes[0].applied is True

        # The id-level check still sees a perfectly bound arrow…
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_shape_binding,
        )
        assert check_arrow_shape_binding(manifest) == []
        # …but the geometry check reports the detached endpoint.
        drift = check_arrow_endpoint_geometry(manifest)
        assert [f.category for f in drift] == ["binding/arrow_endpoint_drift"]
        assert drift[0].location["shape_id"] == "n2"

        rerouted = reroute_bound_arrows(manifest, touched_ids={"n2"})

        assert [item["arrow_id"] for item in rerouted] == ["a1"]
        assert check_arrow_endpoint_geometry(manifest) == []
        label_after = manifest["elements"][3]
        assert (label_after["x"], label_after["y"]) != (
            label_before["x"],
            label_before["y"],
        )

    def test_reroute_resolves_endpoints_from_semantic_meta_without_bindings(self):
        """Real Excalidraw pipeline output has no start/end bindings at all.

        ``excalidraw/arrow_adder.py`` never writes them — it stamps
        ``meta.source`` / ``meta.target`` instead — so a binding-only resolver
        would make this whole repair dead code in production.
        """
        from evo_diagram.agentic_system.refinement_stage.fixers.arrow_reroute import (
            reroute_bound_arrows,
        )
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_endpoint_geometry,
        )

        manifest = _arrow_manifest(with_bindings=False)
        manifest["elements"][1]["x"] = 900

        assert [f.category for f in check_arrow_endpoint_geometry(manifest)] == [
            "binding/arrow_endpoint_drift"
        ]

        rerouted = reroute_bound_arrows(manifest)

        assert [item["arrow_id"] for item in rerouted] == ["a1"]
        assert check_arrow_endpoint_geometry(manifest) == []

    def test_reroute_drops_stale_locked_elbow_segments(self):
        from evo_diagram.agentic_system.refinement_stage.fixers.arrow_reroute import (
            reroute_bound_arrows,
        )

        manifest = _arrow_manifest()
        manifest["elements"][2]["fixedSegments"] = [
            {"start": [0, 0], "end": [200, 0], "index": 1}
        ]
        manifest["elements"][1]["y"] = 500

        assert reroute_bound_arrows(manifest)
        assert "fixedSegments" not in manifest["elements"][2]


class TestArrowRoutingFacade:
    """Contract the re-route pass depends on (``canvas_environment.geometry``)."""

    def test_facade_routes_between_two_bboxes(self):
        from evo_diagram.canvas_environment import route_arrow_between_bboxes

        route = route_arrow_between_bboxes(
            {"x": 0, "y": 0, "w": 100, "h": 60},
            {"x": 300, "y": 0, "w": 100, "h": 60},
        )

        assert (route.start_side, route.end_side) == ("right", "left")
        assert route.absolute_points[0] == [100.0, 30.0]
        assert route.absolute_points[-1] == [300.0, 30.0]
        # ``points`` are stored relative to the element origin.
        assert route.points[0] == [0.0, 0.0]
        assert (route.x, route.y) == (100.0, 30.0)

    def test_facade_keeps_a_same_side_hint_so_back_edges_keep_their_detour(self):
        from evo_diagram.canvas_environment import route_arrow_between_bboxes

        route = route_arrow_between_bboxes(
            {"x": 300, "y": 0, "w": 100, "h": 60},
            {"x": 0, "y": 0, "w": 100, "h": 60},
            start_side_hint="top",
            end_side_hint="top",
        )

        assert (route.start_side, route.end_side) == ("top", "top")
        # Bows outward instead of collapsing onto the forward edge.
        assert min(point[1] for point in route.absolute_points) < 0

    def test_facade_drops_an_implausible_hint(self):
        from evo_diagram.canvas_environment import route_arrow_between_bboxes

        route = route_arrow_between_bboxes(
            {"x": 0, "y": 0, "w": 100, "h": 60},
            {"x": 300, "y": 0, "w": 100, "h": 60},
            start_side_hint="left",
            end_side_hint="right",
        )

        assert (route.start_side, route.end_side) == ("right", "left")

    def test_facade_refuses_canvases_without_refinement_support(self):
        """tldraw must not slip into a path that rewrites Excalidraw geometry."""
        from evo_diagram.canvas_environment import route_arrow_between_bboxes

        with pytest.raises(NotImplementedError, match="tldraw"):
            route_arrow_between_bboxes(
                {"x": 0, "y": 0, "w": 10, "h": 10},
                {"x": 90, "y": 90, "w": 10, "h": 10},
                canvas_library="tldraw",
            )
