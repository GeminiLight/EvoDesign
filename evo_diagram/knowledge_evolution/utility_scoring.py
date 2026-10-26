"""Single source of truth for the knowledge *utility* score.

Retrieval-time ranking (``DiagramDesignRetriever._utility_score``) and
maintenance-time re-scoring (``MaintenanceCycle._re_score_all`` via
:func:`~evo_diagram.knowledge_evolution.maintenance.cycle.compute_confidence`)
used to carry two hand-copied implementations of the same formula. They drifted:
the retriever clamped ``delta_score`` at ``-1.0`` while maintenance clamped it at
``-delta_scale`` (``-10.0``), so a counter-example entry with ``delta_score=-8``
lost 0.035 during retrieval but 0.28 during maintenance. Both call sites now
delegate here so the signal can only be changed in one place.

This module is intentionally dependency-free (no pydantic, no vector store) so
that ``design_memory`` and ``knowledge_evolution`` — which sit on opposite sides
of the ChromaDB import boundary — can both import it.
"""

from __future__ import annotations

__all__ = ["DEFAULT_DELTA_SCALE", "compute_utility_score"]


# Maximum absolute ``delta_score`` expected in practice. It equals the full
# objective-score range produced by
# ``knowledge_evolution.iteration.loop._compute_objective_score`` (0-10), so
# ``delta / DELTA_SCALE`` lands in roughly [-1, 1].
DEFAULT_DELTA_SCALE = 10.0

# Component weights. They sum to 1.0, so the raw score before clamping is in
# [-0.35, 1.0] and the clamped result is in [0.0, 1.0].
_SUCCESS_RATE_WEIGHT = 0.45
_DELTA_WEIGHT = 0.35
_SUPPORT_WEIGHT = 0.20

# Support saturates at this many pieces of evidence.
_SUPPORT_SATURATION = 5.0


def compute_utility_score(
    *,
    usage_count: float,
    success_count: float,
    delta_score: float,
    support_count: float,
    delta_scale: float = DEFAULT_DELTA_SCALE,
) -> float:
    """Aggregate a knowledge entry's track record into a ``[0.0, 1.0]`` score.

    Three signals, weighted 0.45 / 0.35 / 0.20:

    - **success rate** — ``success_count / max(usage_count, 1)``; how often the
      entry was retrieved for a sample that ended up counting as a success.
    - **delta** — the entry's recorded ``delta_score``, normalised by
      *delta_scale* and floored at ``-delta_scale`` so a single catastrophic
      sample cannot dominate. Note the caveat on the meaning of ``delta_score``
      documented in ``knowledge_evolution.engine.evaluate_knowledge_success``.
    - **support** — evidence count, saturating at ``_SUPPORT_SATURATION``.

    The result is clamped to ``[0.0, 1.0]``; callers may therefore treat it as a
    normalised quantity when combining it with other ranking terms.
    """
    if delta_scale <= 0:
        raise ValueError(f"delta_scale must be positive; got {delta_scale!r}")

    usage = float(usage_count or 0)
    success = float(success_count or 0)
    delta = float(delta_score or 0.0)
    support = float(support_count or 1)

    success_rate = success / max(usage, 1.0)
    score = (
        _SUCCESS_RATE_WEIGHT * success_rate
        + _DELTA_WEIGHT * max(delta, -delta_scale) / delta_scale
        + _SUPPORT_WEIGHT * min(support / _SUPPORT_SATURATION, 1.0)
    )
    return max(0.0, min(1.0, score))
