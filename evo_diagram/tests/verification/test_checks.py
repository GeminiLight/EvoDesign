"""Verification stage tests."""
import pytest


@pytest.mark.parametrize("offset,end_x,endpoint,expected", [
    (0, 180, False, True),
    (-2, 180, False, True),
    (-6, 180, False, False),
    (0, 100, False, False),
    (0, 180, True, False),
])
def test_edge_clearance_distinguishes_border_runs_from_endpoints_and_corners(offset, end_x, endpoint, expected):
    from evo_diagram.agentic_system.verification_stage.checks.collision_detection import check_edge_node_clearance

    manifest = {"elements": [
        {"id": "node", "type": "rectangle", "x": 100, "y": 100, "width": 40, "height": 40},
        {"id": "edge", "type": "arrow", "x": 0, "y": 100 + offset,
         "points": [[0, 0], [end_x, 0]], "meta": {"target": "node"} if endpoint else {}},
    ]}
    findings = check_edge_node_clearance(manifest)
    assert bool(findings) is expected
    if expected:
        assert findings[0].category == "collision/edge_node_clearance"
        assert findings[0].location["node_id"] == "node"


def _minimal_tldraw_manifest(*shape_records):
    required_schema_keys = [
        "com.tldraw.store",
        "com.tldraw.asset",
        "com.tldraw.document",
        "com.tldraw.page",
        "com.tldraw.shape",
        "com.tldraw.asset.image",
        "com.tldraw.shape.geo",
        "com.tldraw.shape.image",
    ]
    store = {
        "document:document": {
            "id": "document:document",
            "typeName": "document",
            "meta": {},
        },
        "page:page": {
            "id": "page:page",
            "typeName": "page",
            "meta": {},
        },
    }
    for record in shape_records:
        store[record["id"]] = record
    return {
        "document": {
            "store": store,
            "schema": {
                "schemaVersion": 2,
                "sequences": {key: 1 for key in required_schema_keys},
            },
        },
        "session": {
            "currentPageId": "page:page",
            "pageStates": [],
        },
    }


def _tldraw_geo_shape(shape_id, *, x, y, w=120, h=60, text="Node"):
    return {
        "id": shape_id,
        "typeName": "shape",
        "type": "geo",
        "x": x,
        "y": y,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {},
        "parentId": "page:page",
        "index": "a00001",
        "props": {
            "w": w,
            "h": h,
            "geo": "rectangle",
            "color": "black",
            "fill": "none",
            "text": text,
        },
    }


def _tldraw_arrow_shape(
    shape_id,
    *,
    x=0,
    y=0,
    edge_id="edge:n12n2",
    start=None,
    end=None,
    kind="elbow",
):
    return {
        "id": shape_id,
        "typeName": "shape",
        "type": "arrow",
        "x": x,
        "y": y,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {
            "semantic_edge_id": edge_id,
            "source": "n1",
            "target": "n2",
        },
        "parentId": "page:page",
        "index": "b00001",
        "props": {
            "start": start or {"x": 10, "y": 10},
            "end": end or {"x": 150, "y": 90},
            "kind": kind,
            "elbowMidPoint": 0.5,
            "text": "",
        },
    }


def _tldraw_arrow_binding(binding_id, *, arrow_id, target_id, terminal):
    return {
        "id": binding_id,
        "typeName": "binding",
        "type": "arrow",
        "fromId": arrow_id,
        "toId": target_id,
        "meta": {},
        "props": {
            "terminal": terminal,
            "isPrecise": True,
            "isExact": True,
            "normalizedAnchor": {"x": 0.5, "y": 0.5},
        },
    }


def test_layout_audit_requires_layout_unless_explicitly_skipped():
    from evo_diagram.agentic_system.verification_stage.checks import aggregator
    from evo_diagram.agentic_system.verification_stage.checks.finding import Severity

    manifest = {
        "type": "excalidraw",
        "version": 2,
        "elements": [],
        "appState": {},
        "files": {},
    }

    findings = aggregator.run_all_checks(
        manifest,
        layout_instantiation=None,
        canvas_library="excalidraw",
    )

    missing_layout = [
        finding
        for finding in findings
        if finding.category == "render_validation/layout_audit/missing_layout"
    ]
    assert len(missing_layout) == 1
    assert missing_layout[0].severity == Severity.CRITICAL
    assert "layout_instantiation" in missing_layout[0].message

    malformed_findings = aggregator.run_all_checks(
        manifest,
        layout_instantiation=[],
        canvas_library="excalidraw",
    )
    assert any(
        finding.category == "render_validation/layout_audit/missing_layout"
        and finding.severity == Severity.CRITICAL
        and "got list" in finding.message
        for finding in malformed_findings
    )

    skipped_findings = aggregator.run_all_checks(
        manifest,
        layout_instantiation=None,
        canvas_library="excalidraw",
        skip_categories=["layout_audit"],
    )
    assert not [
        finding
        for finding in skipped_findings
        if finding.category == "render_validation/layout_audit/missing_layout"
    ]


class TestObjectiveChecks:
    def test_finding_severity_enum(self):
        from evo_diagram.agentic_system.verification_stage.checks.finding import Severity
        assert Severity.CRITICAL.value == "critical"
        assert Severity.MAJOR.value == "major"
        assert Severity.MINOR.value == "minor"
        assert Severity.INFO.value == "info"

    def test_finding_model(self):
        from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity
        f = Finding(category="collision", severity=Severity.MINOR, message="test", element_id="n1")
        assert f.category == "collision"
        assert f.severity == Severity.MINOR

    def test_verifier_workflow_importable(self):
        from evo_diagram.agentic_system.verification_stage.workflow import VerifierWorkflow
        assert VerifierWorkflow is not None

    def test_verifier_state_importable(self):
        from evo_diagram.agentic_system.verification_stage.state import VerifierState
        assert VerifierState is not None

    def test_run_all_checks_supports_skip_prefixes(self, monkeypatch):
        from evo_diagram.agentic_system.verification_stage.checks import aggregator
        from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity

        def no_findings(*args):
            return []

        def one_finding(category):
            def check(*args):
                return [
                    Finding(
                        category=category,
                        severity=Severity.MINOR,
                        message=category,
                    )
                ]
            return check

        monkeypatch.setattr(aggregator, "check_schema", no_findings)
        monkeypatch.setattr(aggregator, "check_render_audit", no_findings)
        monkeypatch.setattr(aggregator, "check_layout_audit", no_findings)
        monkeypatch.setattr(aggregator, "check_arrow_shape_binding", no_findings)
        monkeypatch.setattr(aggregator, "check_group_bbox_contains_children", no_findings)
        monkeypatch.setattr(aggregator, "check_swimlane_lane_membership", no_findings)
        monkeypatch.setattr(aggregator, "check_node_overlap", one_finding("collision/node_overlap"))
        monkeypatch.setattr(aggregator, "check_edge_crossings", one_finding("collision/edge_crossing"))
        monkeypatch.setattr(aggregator, "check_out_of_canvas", one_finding("collision/out_of_canvas"))

        assert aggregator.run_all_checks({}, skip_categories=["collision"]) == []

        findings = aggregator.run_all_checks({}, skip_categories=["collision/node_overlap"])
        assert [finding.category for finding in findings] == [
            "collision/edge_crossing",
            "collision/out_of_canvas",
        ]

    def test_run_all_checks_isolates_individual_check_failures(self, monkeypatch):
        from evo_diagram.agentic_system.verification_stage.checks import aggregator
        from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity

        def no_findings(*args):
            return []

        def exploding_check(*args):
            raise RuntimeError("boom")

        def later_finding(*args):
            return [
                Finding(
                    category="collision/node_overlap",
                    severity=Severity.MAJOR,
                    message="later check still ran",
                )
            ]

        monkeypatch.setattr(aggregator, "check_schema", no_findings)
        monkeypatch.setattr(aggregator, "check_render_audit", exploding_check)
        monkeypatch.setattr(aggregator, "check_layout_audit", no_findings)
        monkeypatch.setattr(aggregator, "check_arrow_shape_binding", no_findings)
        monkeypatch.setattr(aggregator, "check_group_bbox_contains_children", no_findings)
        monkeypatch.setattr(aggregator, "check_swimlane_lane_membership", no_findings)
        monkeypatch.setattr(aggregator, "check_node_overlap", later_finding)
        monkeypatch.setattr(aggregator, "check_edge_crossings", no_findings)
        monkeypatch.setattr(aggregator, "check_out_of_canvas", no_findings)

        findings = aggregator.run_all_checks({})

        assert [finding.category for finding in findings] == [
            "verification/internal_error/render_audit",
            "collision/node_overlap",
        ]
        assert findings[0].severity == Severity.CRITICAL
        assert "RuntimeError: boom" in findings[0].message

    def test_run_all_checks_rejects_unknown_canvas_before_running_checks(self, monkeypatch):
        from evo_diagram.agentic_system.verification_stage.checks import aggregator

        def fail_if_called(*args):
            raise AssertionError("checks must not run for an unknown canvas library")

        monkeypatch.setattr(aggregator, "check_schema", fail_if_called)
        monkeypatch.setattr(aggregator, "check_render_audit", fail_if_called)
        monkeypatch.setattr(aggregator, "check_layout_audit", fail_if_called)
        monkeypatch.setattr(aggregator, "check_arrow_shape_binding", fail_if_called)
        monkeypatch.setattr(aggregator, "check_group_bbox_contains_children", fail_if_called)
        monkeypatch.setattr(aggregator, "check_swimlane_lane_membership", fail_if_called)
        monkeypatch.setattr(aggregator, "check_node_overlap", fail_if_called)
        monkeypatch.setattr(aggregator, "check_edge_crossings", fail_if_called)
        monkeypatch.setattr(aggregator, "check_out_of_canvas", fail_if_called)

        with pytest.raises(ValueError, match="Unknown canvas_library"):
            aggregator.run_all_checks({}, canvas_library="bad-canvas")

    def test_run_all_checks_projects_tldraw_shapes_for_canvas_bounds(self):
        from evo_diagram.agentic_system.verification_stage.checks import aggregator

        manifest = _minimal_tldraw_manifest(
            _tldraw_geo_shape("shape:outside", x=9000, y=9000),
        )

        findings = aggregator.run_all_checks(
            manifest,
            canvas_library="tldraw",
        )

        assert any(
            finding.category == "collision/out_of_canvas"
            and finding.element_id == "shape:outside"
            for finding in findings
        )

    def test_collision_checks_ignore_deleted_excalidraw_elements(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_node_overlap,
            check_out_of_canvas,
        )

        manifest = {
            "elements": [
                {
                    "id": "deleted",
                    "type": "rectangle",
                    "x": -100,
                    "y": -100,
                    "width": 100,
                    "height": 100,
                    "isDeleted": True,
                },
                {
                    "id": "live",
                    "type": "rectangle",
                    "x": 20,
                    "y": 20,
                    "width": 100,
                    "height": 100,
                },
            ],
        }

        assert check_out_of_canvas(manifest) == []
        assert check_node_overlap(manifest) == []

    def test_out_of_canvas_uses_safe_area_margin_not_only_fully_outside(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_out_of_canvas,
        )

        manifest = {
            "elements": [
                {
                    "id": "clipped",
                    "type": "rectangle",
                    "x": 4,
                    "y": 20,
                    "width": 100,
                    "height": 100,
                },
            ],
        }

        findings = check_out_of_canvas(manifest)

        assert len(findings) == 1
        assert findings[0].category == "collision/out_of_canvas"
        assert findings[0].element_id == "clipped"
        assert "violates canvas safe area" in findings[0].message

    def test_out_of_canvas_ignores_arrow_bound_text_placeholder(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_out_of_canvas,
        )

        manifest = {
            "elements": [
                {
                    "id": "arrow:1",
                    "type": "arrow",
                    "x": 100,
                    "y": 100,
                    "points": [[0, 0], [200, 0]],
                },
                {
                    "id": "arrow-label",
                    "type": "text",
                    "containerId": "arrow:1",
                    "x": 120,
                    "y": 0,
                    "width": 48,
                    "height": 16,
                    "text": "depends on",
                },
                {
                    "id": "ordinary-text",
                    "type": "text",
                    "x": 120,
                    "y": 0,
                    "width": 48,
                    "height": 16,
                    "text": "visible",
                },
            ],
        }

        findings = check_out_of_canvas(manifest)

        assert [finding.element_id for finding in findings] == ["ordinary-text"]

    def test_run_all_checks_projects_tldraw_shapes_for_overlap_detection(self):
        from evo_diagram.agentic_system.verification_stage.checks import aggregator

        manifest = _minimal_tldraw_manifest(
            _tldraw_geo_shape("shape:n1", x=0, y=0, w=120, h=80),
            _tldraw_geo_shape("shape:n2", x=60, y=30, w=120, h=80),
        )

        findings = aggregator.run_all_checks(
            manifest,
            canvas_library="tldraw",
        )

        assert any(
            finding.category == "collision/node_overlap"
            and finding.element_id == "shape:n1"
            and finding.location.get("other_id") == "shape:n2"
            for finding in findings
        )

    def test_node_overlap_ignores_direct_group_frame_containing_child(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_node_overlap,
        )

        manifest = {
            "elements": [
                {
                    "id": "service_layer",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 360,
                    "height": 220,
                },
                {
                    "id": "service_layer:title",
                    "type": "text",
                    "x": 16,
                    "y": 12,
                    "width": 140,
                    "height": 24,
                    "text": "Service Layer",
                },
                {
                    "id": "auth_service",
                    "type": "rectangle",
                    "x": 40,
                    "y": 64,
                    "width": 120,
                    "height": 72,
                },
                {
                    "id": "billing_service",
                    "type": "rectangle",
                    "x": 210,
                    "y": 80,
                    "width": 120,
                    "height": 72,
                },
            ],
            "_meta": {
                "id_map": {
                    "service_layer": "service_layer",
                    "service_layer:title": "service_layer:title",
                    "auth_service": "auth_service",
                    "billing_service": "billing_service",
                }
            },
        }

        assert check_node_overlap(manifest) == []

    def test_node_overlap_skips_structural_group_frame_but_keeps_child_overlap(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_node_overlap,
        )

        manifest = {
            "elements": [
                {
                    "id": "service_layer",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 360,
                    "height": 220,
                },
                {
                    "id": "service_layer:title",
                    "type": "text",
                    "x": 16,
                    "y": 12,
                    "width": 140,
                    "height": 24,
                    "text": "Service Layer",
                },
                {
                    "id": "auth_service",
                    "type": "rectangle",
                    "x": 40,
                    "y": 72,
                    "width": 120,
                    "height": 72,
                },
                {
                    "id": "billing_service",
                    "type": "rectangle",
                    "x": 100,
                    "y": 96,
                    "width": 120,
                    "height": 72,
                },
            ],
            "_meta": {
                "id_map": {
                    "service_layer": "service_layer",
                    "service_layer:title": "service_layer:title",
                    "auth_service": "auth_service",
                    "billing_service": "billing_service",
                }
            },
        }

        findings = check_node_overlap(manifest)

        assert len(findings) == 1
        assert findings[0].category == "collision/node_overlap"
        assert findings[0].element_id == "auth_service"
        assert findings[0].location.get("other_id") == "billing_service"

    def test_node_overlap_skips_title_sibling_group_frame_from_id_map(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_node_overlap,
        )

        manifest = {
            "elements": [
                {
                    "id": "frame1",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 500,
                    "height": 180,
                },
                {
                    "id": "title1",
                    "type": "text",
                    "x": 20,
                    "y": 20,
                    "width": 220,
                    "height": 32,
                    "text": "Service Boundary Layer",
                },
                {
                    "id": "child1",
                    "type": "rectangle",
                    "x": 80,
                    "y": 80,
                    "width": 160,
                    "height": 60,
                },
                {
                    "id": "child2",
                    "type": "rectangle",
                    "x": 280,
                    "y": 80,
                    "width": 160,
                    "height": 60,
                },
            ],
            "_meta": {
                "id_map": {
                    "service_layer": "frame1",
                    "service_layer:title": "title1",
                    "service_api": "child1",
                    "service_worker": "child2",
                }
            },
        }

        assert check_node_overlap(manifest) == []

    def test_node_overlap_does_not_treat_titled_node_as_group_frame(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_node_overlap,
        )

        manifest = {
            "elements": [
                {
                    "id": "service_node",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 240,
                    "height": 120,
                },
                {
                    "id": "service_node:title",
                    "type": "text",
                    "x": 16,
                    "y": 12,
                    "width": 120,
                    "height": 24,
                    "text": "Service",
                },
                {
                    "id": "nested_badge",
                    "type": "rectangle",
                    "x": 32,
                    "y": 52,
                    "width": 80,
                    "height": 40,
                },
            ],
            "_meta": {
                "id_map": {
                    "service_node": "service_node",
                    "service_node:title": "service_node:title",
                    "nested_badge": "nested_badge",
                }
            },
        }

        findings = check_node_overlap(manifest)

        assert any(
            finding.category == "collision/node_overlap"
            and finding.element_id == "service_node"
            and finding.location.get("other_id") == "nested_badge"
            for finding in findings
        )

    def test_tldraw_objective_manifest_projects_arrow_bindings_and_semantic_edge_id(self):
        from evo_diagram.agentic_system.verification_stage.checks.binding_consistency import (
            check_arrow_shape_binding,
        )
        from evo_diagram.agentic_system.verification_stage.checks.objective_manifest import (
            build_objective_manifest,
        )

        manifest = _minimal_tldraw_manifest(
            _tldraw_geo_shape("shape:n1", x=0, y=0),
            _tldraw_geo_shape("shape:n2", x=240, y=120),
            _tldraw_arrow_shape("shape:arrow1", x=20, y=20),
            _tldraw_arrow_binding(
                "binding:start",
                arrow_id="shape:arrow1",
                target_id="shape:n1",
                terminal="start",
            ),
            _tldraw_arrow_binding(
                "binding:end",
                arrow_id="shape:arrow1",
                target_id="shape:n2",
                terminal="end",
            ),
        )

        objective = build_objective_manifest(manifest, canvas_library="tldraw")
        arrows = [elem for elem in objective["elements"] if elem["type"] == "arrow"]

        assert objective["_meta"]["id_map"]["edge:n12n2"] == "shape:arrow1"
        assert len(arrows) == 1
        arrow = arrows[0]
        assert arrow["id"] == "shape:arrow1"
        assert arrow["x"] == 20.0
        assert arrow["y"] == 20.0
        assert arrow["points"] == [
            [10.0, 10.0],
            [80.0, 10.0],
            [80.0, 90.0],
            [150.0, 90.0],
        ]
        assert arrow["tldrawKind"] == "elbow"
        assert arrow["semanticEdgeId"] == "edge:n12n2"
        assert arrow["_meta"]["source"] == "n1"
        assert arrow["_meta"]["target"] == "n2"
        assert arrow["startBinding"] == {"elementId": "shape:n1"}
        assert arrow["endBinding"] == {"elementId": "shape:n2"}
        assert check_arrow_shape_binding(objective) == []

    def test_tldraw_elbow_projection_prevents_chord_crossing_false_positive(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_edge_crossings,
        )
        from evo_diagram.agentic_system.verification_stage.checks.objective_manifest import (
            build_objective_manifest,
        )

        manifest = _minimal_tldraw_manifest(
            _tldraw_arrow_shape(
                "shape:arrow_elbow",
                edge_id="edge:a",
                start={"x": 0, "y": 0},
                end={"x": 100, "y": 100},
                kind="elbow",
            ),
            _tldraw_arrow_shape(
                "shape:arrow_vertical",
                edge_id="edge:b",
                start={"x": 80, "y": 60},
                end={"x": 80, "y": 90},
                kind="straight",
            ),
        )

        objective = build_objective_manifest(manifest, canvas_library="tldraw")
        arrows = {elem["id"]: elem for elem in objective["elements"] if elem["type"] == "arrow"}

        assert arrows["shape:arrow_elbow"]["points"] == [
            [0.0, 0.0],
            [50.0, 0.0],
            [50.0, 100.0],
            [100.0, 100.0],
        ]
        assert check_edge_crossings(objective) == []

    def test_edge_node_intersection_ignores_bound_endpoints(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_edge_node_intersections,
        )

        manifest = {
            "_meta": {"id_map": {"source": "source", "target": "target", "middle": "middle"}},
            "elements": [
                {"id": "source", "type": "rectangle", "x": 0, "y": 40, "width": 40, "height": 40},
                {"id": "middle", "type": "rectangle", "x": 100, "y": 40, "width": 40, "height": 40},
                {"id": "target", "type": "rectangle", "x": 200, "y": 40, "width": 40, "height": 40},
                {
                    "id": "arrow:1",
                    "type": "arrow",
                    "x": 40,
                    "y": 60,
                    "points": [[0, 0], [200, 0]],
                    "meta": {"source": "source", "target": "target"},
                },
            ],
        }

        findings = check_edge_node_intersections(manifest)

        assert len(findings) == 1
        assert findings[0].category == "collision/edge_node_intersection"
        assert findings[0].location["node_id"] == "middle"

    def test_edge_node_intersection_does_not_flag_border_touch(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_edge_node_intersections,
        )

        manifest = {
            "elements": [
                {"id": "node", "type": "rectangle", "x": 100, "y": 100, "width": 40, "height": 40},
                {
                    "id": "arrow:touch",
                    "type": "arrow",
                    "x": 0,
                    "y": 100,
                    "points": [[0, 0], [100, 0]],
                },
            ],
        }

        assert check_edge_node_intersections(manifest) == []

    def test_edge_node_intersection_flags_early_entry_into_target(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_edge_node_intersections,
        )

        manifest = {
            "_meta": {"id_map": {"source": "source", "target": "target"}},
            "elements": [
                {"id": "source", "type": "rectangle", "x": 0, "y": 4, "width": 40, "height": 40},
                {"id": "target", "type": "rectangle", "x": 200, "y": 40, "width": 40, "height": 40},
                {
                    "id": "arrow:hugs-target",
                    "type": "arrow",
                    "x": 40,
                    "y": 44,
                    "points": [[0, 0], [0, -2], [180, -2], [180, -4]],
                    "meta": {"source": "source", "target": "target"},
                },
            ],
        }

        findings = check_edge_node_intersections(manifest)

        assert len(findings) == 1
        assert findings[0].element_id == "arrow:hugs-target"
        assert findings[0].location["node_id"] == "target"
        assert findings[0].location["segment_index"] == 1

    def test_collision_checks_ignore_fully_transparent_arrows(self):
        from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
            check_edge_crossings,
            check_edge_node_intersections,
        )

        manifest = {
            "elements": [
                {"id": "node", "type": "rectangle", "x": 90, "y": 90, "width": 20, "height": 20},
                {
                    "id": "hidden-horizontal",
                    "type": "arrow",
                    "opacity": 0,
                    "x": 0,
                    "y": 100,
                    "points": [[0, 0], [200, 0]],
                },
                {
                    "id": "visible-vertical",
                    "type": "arrow",
                    "opacity": 100,
                    "x": 100,
                    "y": 0,
                    "points": [[0, 0], [0, 200]],
                },
            ],
        }

        assert check_edge_crossings(manifest) == []
        intersection_ids = {
            finding.element_id for finding in check_edge_node_intersections(manifest)
        }
        assert "hidden-horizontal" not in intersection_ids
        assert "visible-vertical" in intersection_ids
