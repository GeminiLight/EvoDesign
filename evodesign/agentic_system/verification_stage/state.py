"""Verifier state — Pydantic v2 model that survives every workflow node.

Mirrors the pattern used by refinement_stage/state.py but stays fully
independent (does not import any refiner type).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .checks.finding import Finding, Severity


class DimensionCritique(BaseModel):
    """One dimension's worth of the VLM's three-section output."""

    score: float = Field(..., ge=0.0, le=10.0)
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class Critique(BaseModel):
    """Full structured response from the single VLM call."""

    structure: DimensionCritique
    styling: DimensionCritique
    layout: DimensionCritique
    overall_score: float = Field(..., ge=0.0, le=10.0)
    constraint_violations: List[str] = Field(default_factory=list)
    summary: str = ""
    call_metrics: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Optional[str] = Field(
        default=None,
        description="Full raw LLM response, kept for debugging when JSON parse fails."
    )


class VerifierState(BaseModel):
    """Workflow-wide state for the verifier pipeline.

    Shared across the 4 LangGraph nodes (load → check → critic → report).
    """

    # ---- Inputs ----
    manifest_path: str
    image_path: str
    canvas_library: str = "excalidraw"
    structure_path: Optional[str] = None
    layout_path: Optional[str] = None
    source_text: Optional[str] = None
    design_constraints: str = ""
    output_dir: Optional[str] = None
    skip_critic: bool = False
    skip_checks: List[str] = Field(default_factory=list)
    emit_markdown: bool = False

    # ---- Loaded data ----
    manifest: Optional[Dict[str, Any]] = None
    structure: Optional[Dict[str, Any]] = None
    layout_instantiation: Optional[Dict[str, Any]] = None  # optional, derived if structure dir holds it

    # ---- Objective output ----
    objective_findings: List[Finding] = Field(default_factory=list)
    objective_summary: Dict[str, int] = Field(default_factory=dict)

    # ---- Subjective output ----
    critique: Optional[Critique] = None

    # ---- Report ----
    report: Optional[Dict[str, Any]] = None
    report_path: Optional[str] = None

    # ---- Bookkeeping ----
    # init | loaded | checked | critiqued | reported | reported_with_findings |
    # reported_with_warnings | reported_with_errors | failed
    status: str = "init"
    errors: List[str] = Field(default_factory=list)
    blocking_errors: List[str] = Field(default_factory=list)
    nonblocking_errors: List[str] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)

    # Convenience helpers — keep the same names as refinement_stage for
    # consistency, but DO NOT import refiner types.
    def add_log(self, message: str) -> None:
        self.logs.append(message)

    def add_error(self, message: str, *, blocking: bool = True) -> None:
        self.errors.append(message)
        if blocking:
            self.blocking_errors.append(message)
        else:
            self.nonblocking_errors.append(message)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors) or self.status in {"failed", "reported_with_errors"}

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.blocking_errors) or self.status in {
            "failed",
            "reported_with_errors",
        }

    @property
    def has_nonblocking_errors(self) -> bool:
        return bool(self.nonblocking_errors)

    @property
    def blocking_finding_count(self) -> int:
        if self.objective_summary:
            return int(self.objective_summary.get("critical", 0) or 0) + int(
                self.objective_summary.get("major", 0) or 0
            )
        return sum(
            1
            for finding in self.objective_findings
            if finding.severity in {Severity.CRITICAL, Severity.MAJOR}
        )

    @property
    def has_blocking_findings(self) -> bool:
        return self.blocking_finding_count > 0

    @property
    def quality_passed(self) -> bool:
        return not self.has_blocking_errors and not self.has_blocking_findings

    @property
    def cli_exit_code(self) -> int:
        return 0 if self.status in {"reported", "reported_with_warnings"} and self.quality_passed else 1

    model_config = ConfigDict(arbitrary_types_allowed=True)


__all__ = ["VerifierState", "Critique", "DimensionCritique"]
