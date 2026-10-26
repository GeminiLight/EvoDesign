"""refinement_stage.state — Pydantic v2 state, edit ops, iteration logs.

EditOp is the **shared primitive vocabulary** between deterministic fixers
and the VLM agent. Every fix — rule-driven or LLM-driven — flows through
this edit DSL, which makes the audit log uniform and `apply_edits` a single
dispatch table.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from evo_diagram.agentic_system.verification_stage.checks.finding import Finding
from evo_diagram.canvas_runtime import normalize_canvas_library


SUPPORTED_REFINER_CANVAS_LIBRARIES = ("excalidraw",)


# Each op is one row in the iteration log; ``payload`` carries op-specific
# kwargs validated lazily by the dispatcher in fixers/apply_edits.py.
EditOpName = Literal[
    "set_icon",              # payload: {"name": bundled Material icon name}; targets the host node
    "set_position",          # payload: {"x": float, "y": float}
    "set_size",              # payload: {"width": float, "height": float}
    "set_style",             # payload: {"backgroundColor"?, "strokeColor"?, "strokeWidth"?, "strokeStyle"?, "fillStyle"?}
    "set_text",              # payload: {"text": str}
    "delete_element",        # payload: {}
    "clear_arrow_binding",   # payload: {"side": "start" | "end"}
    "clear_container_binding",  # payload: {"container_id"?: str}
    "append_bound_element",  # payload: {"bound_id": str, "type": "arrow" | "text"}
    "remove_bound_element",  # payload: {"bound_id": str}
    "set_index",             # payload: {"index": str}  fractional index for z-order
]


class EditOp(BaseModel):
    """Atomic edit op. Same shape whether emitted by rule or LLM."""

    op: EditOpName
    id: str = Field(..., description="Excalidraw element id this edit targets.")
    payload: Dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="", description="Short human-readable reason. Logged but not enforced.")
    source: Literal["deterministic", "llm"] = Field(
        default="deterministic",
        description="Which path emitted this edit. Used in iteration log.",
    )

    model_config = ConfigDict(extra="forbid")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class EditApplyOutcome(BaseModel):
    """Result of ONE proposed edit. Always recorded — successes, skips, rejects.

    ``edit`` is None only for a proposal that never became an EditOp at all
    (an LLM item that failed schema validation). Those used to be dropped with
    nothing but a log warning, which made "the model proposed 20 malformed
    edits" indistinguishable from "the model saw nothing to fix"; ``raw`` keeps
    the offending payload so the iteration log can show what was thrown away.
    """

    edit: Optional[EditOp] = None
    applied: bool
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class IterationLog(BaseModel):
    """One row of the refinement audit trail. Per refiner iteration."""

    rolled_back: bool = False

    iteration: int
    deterministic_edits: List[EditApplyOutcome] = Field(default_factory=list)
    llm_edits: List[EditApplyOutcome] = Field(default_factory=list)
    rerouted_arrows: List[Dict[str, Any]] = Field(default_factory=list)
    findings_before: Dict[str, int] = Field(default_factory=dict)   # severity histogram
    findings_after: Dict[str, int] = Field(default_factory=dict)
    rerender_ok: bool = False
    rerender_path: Optional[str] = None
    rerender_error: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class PreparedIteration(BaseModel):
    """Local deterministic work that can overlap the independent critic."""

    iteration: int
    findings_before: List[Finding]
    snapshot: Optional[Dict[str, Any]]
    log: IterationLog
    image_note: Optional[str] = None


class VerifierRefinerState(BaseModel):
    """Workflow-wide state, passed through every LangGraph node."""

    # ---- Inputs ----
    verifier_report_path: Optional[str] = None
    design_constraints: str = ""
    manifest_path: str
    image_path: str
    structure_path: Optional[str] = None
    layout_path: Optional[str] = None
    output_dir: Optional[str] = None
    canvas_library: str = "excalidraw"

    # ---- Controls ----
    max_iterations: int = Field(default=3, ge=1)
    skip_rerender_between_iterations: bool = False
    skip_checks: List[str] = Field(default_factory=list)
    emit_markdown: bool = False

    # ---- Loaded data ----
    initial_report: Optional[Dict[str, Any]] = None
    structure: Optional[Dict[str, Any]] = None
    layout_instantiation: Optional[Dict[str, Any]] = None
    manifest: Optional[Dict[str, Any]] = None  # mutated across iterations

    # ---- Mutable per-iteration ----
    current_iteration: int = 0
    current_image_path: Optional[str] = None
    analysis_manifest_fingerprint: Optional[str] = None
    prepared_iteration: Optional[PreparedIteration] = None
    prepared_input_fingerprint: Optional[str] = None
    iteration_logs: List[IterationLog] = Field(default_factory=list)
    latest_findings: List[Finding] = Field(default_factory=list)
    converged: bool = False
    termination_reason: Optional[str] = None
    # Plain field, NOT a PrivateAttr: ``StateGraph`` only builds channels for
    # ``model_fields`` and rebuilds the state from channel values on every node
    # entry, so a private attribute silently reset to None each iteration and
    # stagnation could never be detected.
    prev_findings_fingerprint: Optional[str] = None
    # Lowest (best) weighted finding score reached so far. A round that scores
    # worse than the round it started from is rolled back, so the manifest at
    # every round boundary is the historical best rather than the last attempt.
    best_findings_score: Optional[float] = None
    # Objective checks the refiner deliberately did not run this session, with
    # the reason. Surfaced in the report so a clean run cannot be mistaken for
    # a fully verified one.
    skipped_objective_checks: List[str] = Field(default_factory=list)

    # ---- Outputs ----
    refined_manifest_path: Optional[str] = None
    refined_image_path: Optional[str] = None
    candidate_manifest_path: Optional[str] = None
    candidate_image_path: Optional[str] = None
    refiner_report_path: Optional[str] = None

    # ---- Bookkeeping ----
    status: str = "init"
    errors: List[str] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def add_log(self, message: str) -> None:
        self.logs.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    @field_validator("canvas_library", mode="before")
    @classmethod
    def validate_canvas_library(cls, v: str) -> str:
        value = normalize_canvas_library(v)
        if value not in SUPPORTED_REFINER_CANVAS_LIBRARIES:
            raise ValueError(
                "IterativeRefinerWorkflow currently supports Excalidraw "
                f"manifests only; got canvas_library={v!r}."
            )
        return value


__all__ = [
    "EditOp",
    "EditOpName",
    "EditApplyOutcome",
    "IterationLog",
    "PreparedIteration",
    "VerifierRefinerState",
    "SUPPORTED_REFINER_CANVAS_LIBRARIES",
]
