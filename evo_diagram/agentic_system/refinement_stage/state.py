"""refinement_stage.state — Pydantic v2 state, edit ops, iteration logs.

EditOp is the **shared primitive vocabulary** between deterministic fixers
and the VLM agent. Every fix — rule-driven or LLM-driven — flows through
this 10-op DSL, which makes the audit log uniform and `apply_edits` a single
dispatch table.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from evo_diagram.agentic_system.verification_stage.checks.finding import Finding
from evo_diagram.canvas_runtime import normalize_canvas_library


SUPPORTED_REFINER_CANVAS_LIBRARIES = ("excalidraw",)


# Each op is one row in the iteration log; ``payload`` carries op-specific
# kwargs validated lazily by the dispatcher in fixers/apply_edits.py.
EditOpName = Literal[
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
    """Result of applying ONE EditOp. Always recorded — successes and skips."""

    edit: EditOp
    applied: bool
    error: Optional[str] = None


class IterationLog(BaseModel):
    """One row of the refinement audit trail. Per refiner iteration."""

    iteration: int
    deterministic_edits: List[EditApplyOutcome] = Field(default_factory=list)
    llm_edits: List[EditApplyOutcome] = Field(default_factory=list)
    findings_before: Dict[str, int] = Field(default_factory=dict)   # severity histogram
    findings_after: Dict[str, int] = Field(default_factory=dict)
    rerender_ok: bool = False
    rerender_path: Optional[str] = None
    rerender_error: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class VerifierRefinerState(BaseModel):
    """Workflow-wide state, passed through every LangGraph node."""

    # ---- Inputs ----
    verifier_report_path: Optional[str] = None
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
    iteration_logs: List[IterationLog] = Field(default_factory=list)
    latest_findings: List[Finding] = Field(default_factory=list)
    converged: bool = False
    termination_reason: Optional[str] = None
    _prev_findings_fingerprint: Optional[str] = PrivateAttr(default=None)

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
    "VerifierRefinerState",
    "SUPPORTED_REFINER_CANVAS_LIBRARIES",
]
