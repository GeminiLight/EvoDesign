"""verification_stage.checks — objective checks on diagram_manifest.json.

Each module exports one function returning ``List[Finding]``.  The
aggregator runs them all and concatenates the results.
"""

from .aggregator import run_all_checks  # noqa: F401
from .finding import Finding, Severity, summarize_findings  # noqa: F401

__all__ = ["Finding", "Severity", "summarize_findings", "run_all_checks"]
