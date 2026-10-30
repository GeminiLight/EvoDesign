"""Regression tests for verifier input loading contracts."""

from __future__ import annotations

import base64
import json

from evo_diagram.agentic_system.verification_stage.workflow import VerifierWorkflow
from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity


_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _write_png(path):
    path.write_bytes(_VALID_PNG)


def test_verifier_loads_explicit_layout_path(tmp_path):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    layout_path = tmp_path / "custom_layout" / "layout_instantiation.json"
    output_dir = tmp_path / "verification"

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
    _write_png(image_path)
    layout_path.parent.mkdir(parents=True)
    layout_path.write_text(
        json.dumps({"elements": {"n1": {"x": 10, "y": 20, "width": 100, "height": 40}}}),
        encoding="utf-8",
    )

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        layout_path=str(layout_path),
        output_dir=str(output_dir),
        skip_critic=True,
    )

    assert state.status == "reported"
    assert state.layout_instantiation == {
        "elements": {"n1": {"x": 10, "y": 20, "width": 100, "height": 40}},
    }
    assert any(str(layout_path) in log for log in state.logs)
    assert state.report_path == str(output_dir / "verifier_report.json")


def test_verifier_reports_error_for_corrupt_png_without_running_checks_or_critic(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "verification"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    def fail_checks(**kwargs):
        raise AssertionError("corrupt verifier input must not run objective checks")

    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.workflow.run_all_checks",
        fail_checks,
    )

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        skip_critic=False,
        skip_checks=["layout_audit"],
    )

    assert state.status == "reported_with_errors"
    assert state.report["metadata"]["had_errors"] is True
    assert state.objective_findings == []
    assert state.critique is None
    assert any("verifier input" in error for error in state.errors)
    assert any(
        "unreadable PNG" in error or "corrupt PNG" in error
        for error in state.errors
    )


def test_verifier_reports_error_for_explicit_missing_structure_path(tmp_path):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    structure_path = tmp_path / "missing_structure.json"
    output_dir = tmp_path / "verification"

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
    _write_png(image_path)

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        structure_path=str(structure_path),
        output_dir=str(output_dir),
        skip_critic=True,
    )

    assert state.status == "reported_with_errors"
    assert state.report["metadata"]["had_errors"] is True
    assert any("explicit structure_path" in error for error in state.errors)


def test_verifier_reports_error_for_unknown_canvas_library(tmp_path):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "verification"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    _write_png(image_path)

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        canvas_library="bad-canvas",
        output_dir=str(output_dir),
        skip_critic=True,
    )

    assert state.status == "reported_with_errors"
    assert state.objective_findings == []
    assert any("Unknown canvas_library" in error for error in state.errors)
    assert state.report["metadata"]["had_errors"] is True


def test_standalone_verifier_reports_missing_layout_as_blocking_finding(tmp_path):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram.png"
    output_dir = tmp_path / "verification"
    manifest_path.write_text(
        json.dumps(
            {
                "type": "excalidraw",
                "version": 2,
                "elements": [],
                "appState": {},
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    _write_png(image_path)

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        skip_critic=True,
    )

    assert state.status == "reported_with_findings"
    assert state.has_blocking_findings is True
    assert state.cli_exit_code == 1
    assert any(
        finding.category == "render_validation/layout_audit/missing_layout"
        and finding.severity == Severity.CRITICAL
        for finding in state.objective_findings
    )

    report = json.loads(
        (output_dir / "verifier_report.json").read_text(encoding="utf-8")
    )
    assert report["metadata"]["had_blocking_findings"] is True
    assert report["metadata"]["quality_passed"] is False
    assert any(
        finding["category"] == "render_validation/layout_audit/missing_layout"
        for finding in report["objective"]["findings"]
    )


def test_verifier_uses_tldraw_schema_when_canvas_library_is_tldraw(tmp_path):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"

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
    manifest_path.write_text(
        json.dumps(
            {
                "document": {
                    "store": {
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
                    },
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
        ),
        encoding="utf-8",
    )
    _write_png(image_path)

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        canvas_library="tldraw",
        output_dir=str(tmp_path / "verification"),
        skip_critic=True,
        skip_checks=["layout_audit"],
    )

    assert state.status == "reported"
    assert state.report["canvas_library"] == "tldraw"
    assert state.report["metadata"]["canvas_library"] == "tldraw"
    assert state.objective_summary.get("critical", 0) == 0


def test_verifier_surfaces_tldraw_render_audit_findings(tmp_path):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    structure_path = tmp_path / "structure_instantiation.json"
    output_dir = tmp_path / "verification"

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
    manifest_path.write_text(
        json.dumps(
            {
                "document": {
                    "store": {
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
                        "shape:g_lane:title": {
                            "id": "shape:g_lane:title",
                            "typeName": "shape",
                            "type": "geo",
                            "x": 0,
                            "y": 0,
                            "rotation": 0,
                            "isLocked": False,
                            "opacity": 1,
                            "meta": {},
                            "parentId": "page:page",
                            "index": "a00001",
                            "props": {
                                "w": 120,
                                "h": 24,
                                "geo": "rectangle",
                                "color": "black",
                                "fill": "none",
                                "text": "   ",
                            },
                        },
                    },
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
        ),
        encoding="utf-8",
    )
    _write_png(image_path)
    structure_path.write_text(
        json.dumps(
            {
                "chart_type": "flowchart",
                "nodes": [],
                "edges": [],
                "groups": [{"id": "g_lane", "label": "Lane", "members": []}],
            }
        ),
        encoding="utf-8",
    )

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        structure_path=str(structure_path),
        canvas_library="tldraw",
        output_dir=str(output_dir),
        skip_critic=True,
    )

    assert state.status == "reported_with_findings"
    assert any(
        finding.category == "render_validation/audit/empty_text"
        and finding.element_id == "shape:g_lane:title"
        for finding in state.objective_findings
    )
    assert state.report["metadata"]["quality_passed"] is False


def test_verifier_report_preserves_failed_status_when_objective_checks_raise(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "verification"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    _write_png(image_path)

    def fail_checks(**kwargs):
        raise RuntimeError("check exploded")

    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.workflow.run_all_checks",
        fail_checks,
    )

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        skip_critic=True,
    )

    assert state.status == "reported_with_errors"
    assert state.report["metadata"]["status"] == "reported_with_errors"
    assert state.report["metadata"]["had_errors"] is True
    assert state.report_path == str(output_dir / "verifier_report.json")
    assert any("objective checks failed" in error for error in state.errors)
    assert any("objective checks failed" in error for error in state.blocking_errors)


def test_verifier_marks_subjective_critic_failure_as_nonblocking_error(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "verification"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    _write_png(image_path)

    class FailingCritic:
        def critique(self, **kwargs):
            raise RuntimeError("critic model unavailable")

    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.critic.critic_agent.VerifierCriticAgent",
        lambda: FailingCritic(),
    )

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        skip_critic=False,
        skip_checks=["layout_audit"],
    )

    assert state.status == "reported_with_warnings"
    assert state.has_errors is True
    assert state.has_blocking_errors is False
    assert state.has_nonblocking_errors is True
    assert state.quality_passed is True
    assert state.cli_exit_code == 0
    assert state.blocking_errors == []
    assert state.nonblocking_errors == [
        "subjective critic failed: critic model unavailable"
    ]
    assert any("subjective critic failed" in error for error in state.errors)
    assert state.report["metadata"]["had_errors"] is True
    assert state.report["metadata"]["had_blocking_errors"] is False
    assert state.report["metadata"]["quality_passed"] is True
    assert state.report["metadata"]["blocking_errors"] == []
    assert state.report["metadata"]["nonblocking_errors"] == [
        "subjective critic failed: critic model unavailable"
    ]


def test_verifier_marks_report_write_failure_as_nonblocking_error(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "verification"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    _write_png(image_path)

    def fail_write_report(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.workflow.write_report",
        fail_write_report,
    )

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        skip_critic=True,
        skip_checks=["layout_audit"],
    )

    assert state.status == "reported_with_warnings"
    assert state.has_errors is True
    assert state.has_blocking_errors is False
    assert state.has_nonblocking_errors is True
    assert state.quality_passed is True
    assert state.cli_exit_code == 0
    assert state.blocking_errors == []
    assert any("failed to write report" in error for error in state.errors)
    assert state.report_path is None
    assert state.report["metadata"]["had_errors"] is True
    assert state.report["metadata"]["had_blocking_errors"] is False
    assert state.report["metadata"]["quality_passed"] is True
    assert state.report["metadata"]["errors"] == [
        "failed to write report: disk unavailable"
    ]
    assert state.report["metadata"]["blocking_errors"] == []
    assert state.report["metadata"]["nonblocking_errors"] == [
        "failed to write report: disk unavailable"
    ]


def test_verifier_reports_blocking_findings_as_quality_failure(tmp_path, monkeypatch):
    manifest_path = tmp_path / "diagram_manifest.json"
    image_path = tmp_path / "diagram_manifest.png"
    output_dir = tmp_path / "verification"

    manifest_path.write_text(
        json.dumps({"type": "excalidraw", "elements": [], "files": {}}),
        encoding="utf-8",
    )
    _write_png(image_path)

    finding = Finding(
        category="collision/node_overlap",
        severity=Severity.MAJOR,
        message="overlap remains",
        element_id="n1",
    )
    monkeypatch.setattr(
        "evo_diagram.agentic_system.verification_stage.workflow.run_all_checks",
        lambda **kwargs: [finding],
    )

    state = VerifierWorkflow().run(
        manifest_path=str(manifest_path),
        image_path=str(image_path),
        output_dir=str(output_dir),
        skip_critic=True,
    )

    assert state.status == "reported_with_findings"
    assert state.report["metadata"]["status"] == "reported_with_findings"
    assert state.report["metadata"]["had_errors"] is False
    assert state.report["metadata"]["had_blocking_findings"] is True
    assert state.report["metadata"]["quality_passed"] is False
