"""Finding & severity types — the lingua franca of the objective check layer.

Every check function in `verification_stage/checks/` returns `List[Finding]`.
The aggregator concatenates them and produces a per-severity histogram.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Severity(str, Enum):
    """Severity ladder for objective findings.

    CRITICAL = render is broken (schema invalid, required field missing)
    MAJOR    = visual bug (overlap, wrong containment, missing arrow)
    MINOR    = quality nit (out-of-canvas, redundant element, low contrast)
    INFO     = observational, not actionable
    """

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class Finding(BaseModel):
    """Single objective check finding.

    `category` groups findings by check kind ("render_validation",
    "collision", "containment", "binding", "render_audit"). `element_id`
    points at the offending Excalidraw element when applicable; `location`
    can carry coordinates / bbox for downstream visualization.
    """

    category: str
    severity: Severity
    message: str
    element_id: Optional[str] = None
    location: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True, mode="json")


def summarize_findings(findings: List[Finding]) -> Dict[str, int]:
    """Histogram findings by severity. Always returns all 4 keys."""
    summary = {s.value: 0 for s in Severity}
    for f in findings:
        summary[f.severity.value] = summary.get(f.severity.value, 0) + 1
    summary["total"] = len(findings)
    return summary


__all__ = ["Severity", "Finding", "summarize_findings"]
