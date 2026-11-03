"""One quality policy for interactive generation, CLI runs and refinement.

Geometry settling is not a visual-quality claim. Candidate adoption requires
objective convergence; visual targets and user constraints still need verification.
"""
from math import isfinite
from typing import Any, Mapping

VISUAL_TARGET = 7.0
VISUAL_REGRESSION_TOLERANCE = 0.5
SEVERITIES = ("critical", "major", "minor")


def objective_rank(summary: Mapping[str, Any]) -> tuple[int, ...]:
    return tuple(int(summary.get(key, 0) or 0) for key in SEVERITIES)


def quality_summary(state: Any) -> dict[str, Any]:
    critique = getattr(state, "critique", None)
    score = getattr(critique, "overall_score", None)
    findings = dict(getattr(state, "objective_summary", {}) or {})
    if not findings:
        for finding in getattr(state, "objective_findings", []) or []:
            severity = getattr(finding, "severity", None)
            key = getattr(severity, "value", severity)
            findings[key] = findings.get(key, 0) + 1
    return {
        "findings": findings,
        "score": float(score) if isinstance(score, (int, float)) and isfinite(score) else None,
        "constraint_violations": list(getattr(critique, "constraint_violations", []) or []),
        **({"blocking_errors": True} if blocking_errors(state) else {}),
    }


def blocking_errors(state: Any) -> bool:
    explicit = getattr(state, "has_blocking_errors", None)
    if isinstance(explicit, bool):
        return explicit
    errors = getattr(state, "blocking_errors", None)
    if isinstance(errors, (str, list, tuple)):
        return bool(errors)
    return getattr(state, "has_errors", False) is True


def needs_refinement(summary: Mapping[str, Any]) -> bool:
    score = summary.get("score")
    return (any(objective_rank(summary.get("findings", {})))
            or bool(summary.get("constraint_violations"))
            or isinstance(score, (int, float)) and score < VISUAL_TARGET)


def should_refine(state: Any, *, force: bool = False) -> bool:
    return not blocking_errors(state) and (force or getattr(state, "has_blocking_findings", False) is True
                                          or needs_refinement(quality_summary(state)))


def quality_regressed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if after.get("blocking_errors") or after.get("constraint_violations"):
        return True
    if objective_rank(after.get("findings", {})) > objective_rank(before.get("findings", {})):
        return True
    old, new = before.get("score"), after.get("score")
    return isinstance(old, (int, float)) and (
        not isinstance(new, (int, float)) or not isfinite(new)
        or new < old - VISUAL_REGRESSION_TOLERANCE
    )


def refinement_rejection(initial: Any, candidate: Any) -> str | None:
    if candidate is None or blocking_errors(candidate):
        return "Candidate verification unavailable."
    after = quality_summary(candidate)
    if after["constraint_violations"]:
        return "Candidate violates explicit user constraints."
    if any(objective_rank(after["findings"])[:2]):
        return "Candidate still has serious objective findings."
    if initial is not None and quality_regressed(quality_summary(initial), after):
        return "Candidate quality regressed or visual verification is incomplete."
    return None


def quality_status(summary: Mapping[str, Any]) -> str:
    if summary.get("blocking_errors"):
        return "unverified"
    if needs_refinement(summary):
        return "needs_attention"
    return "passed" if summary.get("score") is not None else "unverified"


def verified_learning_gain(before: dict, after: dict) -> bool:
    old, new = before.get("score"), after.get("score")
    if before.get("blocking_errors") or after.get("blocking_errors"):
        return False
    if not all(isinstance(score, (int, float)) and isfinite(score) for score in (old, new)):
        return False
    return (quality_status(after) == "passed" and not quality_regressed(before, after)
            and new >= old and (new >= old + 0.5
            or objective_rank(after.get("findings", {})) < objective_rank(before.get("findings", {}))
            or bool(before.get("constraint_violations"))))
