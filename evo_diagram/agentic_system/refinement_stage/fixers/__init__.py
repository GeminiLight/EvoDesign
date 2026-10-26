"""refinement_stage.fixers — primitive edit ops + dispatchers.

Two layers:

- ``primitives.py`` — atomic edit op handlers. Each takes a manifest's
  elements list (or full manifest for boundElements ops) and one EditOp,
  performs the change in place, and reports back via EditApplyOutcome.
- ``apply_edits.py`` — single dispatcher that walks a List[EditOp] and
  routes each to the right primitive.
- ``deterministic.py`` — finding-class fixers that emit List[EditOp] from
  a list of Findings + manifest.
- ``arrow_reroute.py`` — post-edit repair pass. Arrow geometry cannot be
  expressed as an EditOp (the polyline is derived, not authored), so arrows
  are re-routed directly after a batch is applied, the same way
  ``patch_schema_defaults`` mutates the manifest outside the DSL.
"""

from .apply_edits import apply_edits  # noqa: F401
from .arrow_reroute import reroute_bound_arrows  # noqa: F401
from .deterministic import (  # noqa: F401
    reorder_elements_by_index,
    run_all_deterministic_fixers,
)

__all__ = [
    "apply_edits",
    "reorder_elements_by_index",
    "reroute_bound_arrows",
    "run_all_deterministic_fixers",
]
