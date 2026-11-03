"""Core orchestrator for the MaintenanceCycle.

Single entry point: run_full — score → prune → promote → demote → merge.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple

from ..config import KnowledgeEvolutionConfig
from ..schemas import KnowledgeEntry
from ..utility_scoring import DEFAULT_DELTA_SCALE, compute_utility_score
from .promoters import PromoterMixin
from .mergers import MergerMixin, _apply_tier_shifts


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-score helper (also used by retriever via _utility_score; kept consistent)
# ---------------------------------------------------------------------------

def compute_confidence(
    item: KnowledgeEntry,
    delta_scale: float = DEFAULT_DELTA_SCALE,
) -> float:
    """Recompute aggregate confidence from current usage / Δscore / support.

    Thin wrapper over :func:`..utility_scoring.compute_utility_score`, which is
    also what :meth:`DiagramDesignRetriever._utility_score` calls. Sharing one
    implementation is deliberate: the two used to be hand-copied and had drifted
    apart on the ``delta_score`` floor (retrieval clamped at -1.0, maintenance at
    ``-delta_scale``), so the same entry scored differently in the two places.

    *delta_scale* normalises delta_score into roughly [-1, 1]. It equals the
    maximum absolute delta_score expected in practice (default 10.0, i.e. the
    full objective-score range).
    """
    return round(
        compute_utility_score(
            usage_count=item.usage_count,
            success_count=item.success_count,
            delta_score=item.delta_score,
            support_count=item.support_count,
            delta_scale=delta_scale,
        ),
        4,
    )


def _retention_score(item: KnowledgeEntry) -> Tuple[int, int, int, int, int, float, float, float]:
    """Rank duplicate IDs by retained evidence/statistical signal.

    Ties deliberately keep the earlier item, which preserves already-loaded
    entries over freshly re-derived promoted entries with identical evidence.
    """
    return (
        item.usage_count,
        item.success_count,
        item.support_count,
        len(item.evidence_ids or []),
        len(item.validated_domains or []),
        item.validation_success_rate,
        item.confidence,
        item.delta_score,
    )


def _dedupe_by_id_keep_best(items: List[KnowledgeEntry]) -> List[KnowledgeEntry]:
    """Remove duplicate IDs while keeping the statistically richer entry."""
    deduped: List[KnowledgeEntry] = []
    positions: Dict[str, int] = {}
    for item in items:
        if item.id not in positions:
            positions[item.id] = len(deduped)
            deduped.append(item)
            continue

        existing_index = positions[item.id]
        existing = deduped[existing_index]
        if _retention_score(item) > _retention_score(existing):
            deduped[existing_index] = item
    return deduped


def _retire_promoted_strategy_sources(
    strategies: List[KnowledgeEntry],
    promoted_guidelines: List[KnowledgeEntry],
) -> Tuple[List[KnowledgeEntry], List[KnowledgeEntry]]:
    """Remove strategies whose evidence is now represented by a guideline."""
    retired_ids = {
        evidence_id
        for guideline in promoted_guidelines
        for evidence_id in (guideline.evidence_ids or [])
    }
    if not retired_ids:
        return strategies, []

    kept: List[KnowledgeEntry] = []
    retired: List[KnowledgeEntry] = []
    for strategy in strategies:
        if strategy.id in retired_ids:
            strategy.generalization_status = "validated"
            retired.append(strategy)
        else:
            kept.append(strategy)
    return kept, retired


# ---------------------------------------------------------------------------
# MaintenanceCycle
# ---------------------------------------------------------------------------

class MaintenanceCycle(PromoterMixin, MergerMixin):
    """Owns the global Score → Prune → Merge → Promote → Demote loop.

    Thresholds come from :class:`KnowledgeEvolutionConfig` so a single object
    parametrises both per-sample filtering (in engine) and the
    set-level passes here.
    """

    def __init__(
        self,
        config: KnowledgeEvolutionConfig,
        principle_promoter,   # PrinciplePromoterAgent
        demotion_judger,      # DemotionJudgerAgent
        merge_judger,         # MergeJudgerAgent
        embedding_function=None,  # langchain Embeddings — optional, enables embedding-based merge clustering
    ):
        self.config = config
        self.principle_promoter = principle_promoter
        self.demotion_judger = demotion_judger
        self.merge_judger = merge_judger
        # MergerMixin reads this to pick clustering backend (RISKS.md #19).
        self.embedding_function = embedding_function

    # ---------- public entry points ------------------------------------------

    def run_full(
        self,
        strategies: List[KnowledgeEntry],
        guidelines: List[KnowledgeEntry],
        principles: List[KnowledgeEntry],
        failed_usage: Optional[Dict[str, List[Dict]]] = None,
    ) -> Tuple[List[KnowledgeEntry], List[KnowledgeEntry], List[KnowledgeEntry], Dict[str, int]]:
        """Full end-of-phase cycle.

        Order: Score → Prune → Merge → Promote → Demote.

        Merge before Promote: deduplicating first gives merged entries higher
        support_count / domain coverage, increasing their chance of promotion.
        Demote after Promote: items promoted *in this cycle* are skipped so they
        get a fair shot in the next cycle. That "this cycle" set is tracked
        locally (``just_promoted_ids``) rather than read off the persisted
        ``generalization_status`` field, which survives across runs and would
        otherwise make every once-promoted entry permanently undemotable.
        """
        failed_usage = failed_usage or {}
        logger.info("=== Running maintenance (full) ===")

        # 1. Score
        self._re_score_all(strategies, guidelines, principles)

        # 2. Prune (strategies only — guidelines/principles use demotion instead)
        strategies, pruned = self._prune_strategies(strategies)

        # 3. Merge each tier (LLM judge) — before promotion so merged entries
        #    accumulate domain coverage and support_count for promotion checks
        merged_strategies, merge_stats_s = self.merge_tier(strategies, "strategy")
        merged_guidelines, merge_stats_g = self.merge_tier(guidelines, "guideline")
        merged_principles, merge_stats_p = self.merge_tier(principles, "principle")
        strategies = merged_strategies
        guidelines = _dedupe_by_id_keep_best(merged_guidelines)
        principles = _dedupe_by_id_keep_best(merged_principles)

        # 4. Promote: strategies → guidelines (heuristic, no LLM)
        promoted_guidelines = self.promote_strategies(strategies)
        strategies, retired_strategies = _retire_promoted_strategy_sources(
            strategies,
            promoted_guidelines,
        )
        guidelines = _dedupe_by_id_keep_best(guidelines + promoted_guidelines)

        # 5. Promote: guidelines → principles (LLM judge)
        promoted_principles = self.promote_guidelines(guidelines)
        principles = _dedupe_by_id_keep_best(principles + promoted_principles)

        # 6. Demote underperforming guidelines + principles (LLM judge).
        #    Skip items promoted during *this* cycle — they don't have
        #    meaningful usage stats at their new tier yet. Membership is tracked
        #    in a cycle-local set instead of the persisted
        #    generalization_status field, which would keep granting immunity on
        #    every subsequent run.
        just_promoted_ids: Set[str] = {
            entry.id for entry in (*promoted_guidelines, *promoted_principles)
        }
        demoted = []
        if failed_usage:
            demoted_g = self.check_demotion(
                guidelines, failed_usage, just_promoted_ids=just_promoted_ids
            )
            demoted_p = self.check_demotion(
                principles, failed_usage, just_promoted_ids=just_promoted_ids
            )
            demoted = demoted_g + demoted_p
            strategies, guidelines, principles = _apply_tier_shifts(
                strategies, guidelines, principles, demoted
            )

        stats = {
            "pruned_strategies": len(pruned),
            "merged_strategies": merge_stats_s,
            "merged_guidelines": merge_stats_g,
            "merged_principles": merge_stats_p,
            "promoted_to_guideline": len(promoted_guidelines),
            "retired_promoted_strategies": len(retired_strategies),
            "promoted_to_principle": len(promoted_principles),
            "demoted": len(demoted),
        }
        logger.info("   >> Full cycle done: %s", stats)
        return strategies, guidelines, principles, stats

    # ---------- step implementations -----------------------------------------

    def _re_score_all(
        self,
        strategies: List[KnowledgeEntry],
        guidelines: List[KnowledgeEntry],
        principles: List[KnowledgeEntry],
    ) -> None:
        for layer in (strategies, guidelines, principles):
            for item in layer:
                item.confidence = compute_confidence(item)

    def _prune_strategies(
        self,
        strategies: List[KnowledgeEntry],
    ) -> Tuple[List[KnowledgeEntry], List[KnowledgeEntry]]:
        """Drop strategies with usage ≥ ``prune_min_usage`` and success_rate
        below ``prune_success_rate``. Untested strategies (usage=0) are kept.
        """
        min_usage = self.config.prune_min_usage
        min_rate = self.config.prune_success_rate
        kept, pruned = [], []
        for s in strategies:
            if s.usage_count >= min_usage:
                rate = s.success_count / max(s.usage_count, 1)
                if rate < min_rate:
                    s.generalization_status = "pruned"
                    pruned.append(s)
                    continue
            kept.append(s)
        if pruned:
            logger.info(
                "   >> Pruned %d strategies (usage>=%d, success_rate<%s)",
                len(pruned),
                min_usage,
                min_rate,
            )
        return kept, pruned
