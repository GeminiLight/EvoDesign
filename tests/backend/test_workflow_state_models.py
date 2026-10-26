from __future__ import annotations

from datetime import datetime, timedelta

from evo_diagram.agentic_system.generation_stage.structure.state import WorkflowState
from evo_diagram.agentic_system.refinement_stage.reports.refiner_report import build_refiner_report
from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState
from evo_diagram.agentic_system.verification_stage.checks.finding import Finding, Severity
from evo_diagram.agentic_system.verification_stage.reports.report_builder import build_report
from evo_diagram.agentic_system.verification_stage.state import VerifierState


def _assert_utc_z_timestamp(value: str) -> None:
    assert value.endswith("Z")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_structure_workflow_state_uses_timezone_aware_created_at():
    state = WorkflowState(text_content="A to B")

    created_at = datetime.fromisoformat(state.created_at)

    assert created_at.tzinfo is not None
    assert created_at.utcoffset() is not None


def test_verifier_state_keeps_arbitrary_finding_types_allowed():
    finding = Finding(
        category="layout_overlap",
        severity="major",
        message="Node overlap detected",
    )

    state = VerifierState(
        manifest_path="diagram.json",
        image_path="diagram.png",
        objective_findings=[finding],
    )

    assert state.objective_findings == [finding]


def test_verifier_report_uses_utc_z_timestamp():
    state = VerifierState(manifest_path="diagram.json", image_path="diagram.png")

    report = build_report(state)

    _assert_utc_z_timestamp(report["metadata"]["timestamp"])


def test_verifier_report_marks_error_state_metadata():
    clean_state = VerifierState(manifest_path="diagram.json", image_path="diagram.png")
    errored_state = VerifierState(
        manifest_path="diagram.json",
        image_path="diagram.png",
        status="reported_with_errors",
        errors=["critic unavailable"],
    )
    errored_state.add_error("objective checks failed")

    assert build_report(clean_state)["metadata"]["had_errors"] is False
    assert build_report(errored_state)["metadata"]["had_errors"] is True
    assert build_report(errored_state)["metadata"]["had_blocking_errors"] is True
    assert build_report(errored_state)["metadata"]["blocking_errors"] == [
        "objective checks failed",
    ]


def test_verifier_state_distinguishes_nonblocking_errors():
    state = VerifierState(
        manifest_path="diagram.json",
        image_path="diagram.png",
        status="reported_with_warnings",
    )

    state.add_error("subjective critic failed: model unavailable", blocking=False)

    assert state.has_errors is True
    assert state.has_blocking_errors is False
    assert state.has_nonblocking_errors is True
    assert state.quality_passed is True
    assert state.cli_exit_code == 0

    report = build_report(state)

    assert report["metadata"]["had_errors"] is True
    assert report["metadata"]["had_blocking_errors"] is False
    assert report["metadata"]["quality_passed"] is True
    assert report["metadata"]["errors"] == [
        "subjective critic failed: model unavailable",
    ]
    assert report["metadata"]["blocking_errors"] == []
    assert report["metadata"]["nonblocking_errors"] == [
        "subjective critic failed: model unavailable",
    ]


def test_verifier_state_treats_legacy_error_status_as_blocking():
    state = VerifierState(
        manifest_path="diagram.json",
        image_path="diagram.png",
        status="reported_with_errors",
        errors=["legacy serialized verifier error"],
    )

    assert state.has_errors is True
    assert state.has_blocking_errors is True
    assert state.quality_passed is False
    assert state.cli_exit_code == 1

    report = build_report(state)

    assert report["metadata"]["had_blocking_errors"] is True
    assert report["metadata"]["quality_passed"] is False
    assert report["metadata"]["errors"] == ["legacy serialized verifier error"]
    assert report["metadata"]["blocking_errors"] == [
        "legacy serialized verifier error",
    ]


def test_verifier_state_quality_helpers_track_blocking_findings_and_errors():
    minor_state = VerifierState(
        manifest_path="diagram.json",
        image_path="diagram.png",
        status="reported",
        objective_findings=[
            Finding(category="render/audit", severity=Severity.MINOR, message="minor")
        ],
    )
    major_state = VerifierState(
        manifest_path="diagram.json",
        image_path="diagram.png",
        status="reported_with_findings",
        objective_findings=[
            Finding(category="collision", severity=Severity.MAJOR, message="major")
        ],
    )
    errored_state = VerifierState(
        manifest_path="diagram.json",
        image_path="diagram.png",
        status="reported_with_errors",
    )
    errored_state.add_error("objective checks failed")

    assert minor_state.has_blocking_findings is False
    assert minor_state.quality_passed is True
    assert minor_state.cli_exit_code == 0

    assert major_state.blocking_finding_count == 1
    assert major_state.has_blocking_findings is True
    assert major_state.quality_passed is False
    assert major_state.cli_exit_code == 1

    assert errored_state.has_errors is True
    assert errored_state.has_blocking_errors is True
    assert errored_state.quality_passed is False
    assert errored_state.cli_exit_code == 1


def test_refiner_report_uses_utc_z_timestamp():
    state = VerifierRefinerState(
        manifest_path="diagram.json",
        image_path="diagram.png",
    )

    report = build_refiner_report(state)

    _assert_utc_z_timestamp(report["metadata"]["timestamp"])
