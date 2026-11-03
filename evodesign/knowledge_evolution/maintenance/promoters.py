"""Promotion and demotion logic for the MaintenanceCycle.

- promote_strategies: strategy → guideline (cross-domain, heuristic)
- promote_guidelines: guideline → principle (cross-diagram-type, LLM judge)
- check_demotion: guideline/principle → lower tier (LLM judge)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Literal, Optional, Set

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError, model_validator

from ..schemas import KnowledgeEntry, TagSet
from .mergers import _content_hash, _normalize_title


logger = logging.getLogger(__name__)


def _has_text(value: Optional[str]) -> bool:
    return isinstance(value, str) and bool(value.strip())


class PrinciplePromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    should_promote: StrictBool
    principle_title: Optional[str] = None
    principle_description: Optional[str] = None
    principle_content: Optional[str] = None
    principle_when_to_use: Optional[str] = None
    reasoning: Optional[str] = None

    @model_validator(mode="after")
    def _require_principle_fields(self) -> "PrinciplePromotionDecision":
        if self.should_promote:
            missing = [
                field
                for field in (
                    "principle_title",
                    "principle_description",
                    "principle_content",
                    "principle_when_to_use",
                )
                if not _has_text(getattr(self, field))
            ]
            if missing:
                raise ValueError(
                    "promotion decisions with should_promote=true require: "
                    + ", ".join(missing)
                )
        return self


class DemotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    should_demote: StrictBool
    new_tier: Optional[Literal["strategy", "guideline"]] = None
    reason: Optional[str] = None
    reasoning: Optional[str] = None
    updated_when_to_use: Optional[str] = None

    @model_validator(mode="after")
    def _require_demotion_fields(self) -> "DemotionDecision":
        if self.should_demote and self.new_tier is None:
            raise ValueError("demotion decisions with should_demote=true require new_tier")
        return self


def _promotion_tags_payload(
    *,
    domains: Set[str],
    diagram_types: Set[str],
    agents: Set[str],
) -> Dict[str, List[str]]:
    return {
        "domain": sorted(domains),
        "diagram_type": sorted(diagram_types),
        "agent": sorted(agents),
    }


def _promotion_id(
    *,
    tier: str,
    title: str,
    tags: Dict[str, List[str]],
    evidence_ids: List[str],
) -> str:
    identity_payload = {
        **tags,
        "tier": [tier],
        "evidence_ids": sorted(evidence_ids),
    }
    return f"{tier}_{_content_hash(title, identity_payload)}"


class PromoterMixin:
    """Promotion and demotion methods mixed into MaintenanceCycle.

    Expects ``self.config`` and ``self.principle_promoter`` / ``self.demotion_judger``
    to be set by the host class.
    """

    def _is_promotion_success(self, item: KnowledgeEntry) -> bool:
        """Whether a strategy/guideline counts as a 'success' for promotion.

        Two complementary signals — either alone is sufficient:

        - **In-the-wild**: retrieved enough times with a healthy success rate
          (``usage_count >= promote_min_retrieval_usage`` and
          ``success_count/usage_count >= promote_per_strategy_success_rate``).
        - **Creation-time**: source-sample ``delta_score`` is strong
          (``>= promote_strong_delta_score``). Required because newly
          distilled items have ``usage_count == 0`` until they're indexed
          and re-retrieved on the next run.

        The earlier code used ``delta_score > delta_score_threshold`` for
        success-counting, but ``_filter_strategies`` already kept only
        strategies meeting that threshold, so ``success_rate`` was always
        ~1.0 and the gate was vacuous (RISKS.md #15).
        """
        cfg = self.config
        if (
            item.usage_count >= cfg.promote_min_retrieval_usage
            and item.success_count / max(item.usage_count, 1)
                >= cfg.promote_per_strategy_success_rate
        ):
            return True
        if item.delta_score >= cfg.promote_strong_delta_score:
            return True
        return False

    def promote_strategies(
        self,
        strategies: List[KnowledgeEntry],
    ) -> List[KnowledgeEntry]:
        """Cross-domain promotion: strategy → guideline.

        Group strategies by lowercased title. Promote a group when it covers
        ≥ ``promote_min_domains`` distinct domains with success_rate
        ≥ ``promote_success_rate`` (using the two-signal gate in
        :meth:`_is_promotion_success`).
        """
        min_domains = self.config.promote_min_domains
        min_rate = self.config.promote_success_rate

        groups: Dict[str, List[KnowledgeEntry]] = defaultdict(list)
        for s in strategies:
            groups[_normalize_title(s.title)].append(s)

        promoted: List[KnowledgeEntry] = []
        for title_key, group in groups.items():
            seen_domains: Set[str] = set()
            seen_diagram_types: Set[str] = set()
            seen_agents: Set[str] = set()
            for s in group:
                seen_domains.update(s.tags.domain)
                seen_diagram_types.update(s.tags.diagram_type)
                seen_agents.update(s.tags.agent)

            if len(seen_domains) < min_domains:
                continue

            success_count = sum(1 for s in group if self._is_promotion_success(s))
            success_rate = success_count / len(group)
            if success_rate < min_rate:
                continue

            best = max(group, key=lambda s: s.delta_score)
            evidence_ids = [s.id for s in group]
            title = f"[Guideline] {best.title}"
            tags_payload = _promotion_tags_payload(
                domains=seen_domains,
                diagram_types=seen_diagram_types,
                agents=seen_agents,
            )
            guideline = KnowledgeEntry(
                id=_promotion_id(
                    tier="guideline",
                    title=title,
                    tags=tags_payload,
                    evidence_ids=evidence_ids,
                ),
                tags=TagSet(**tags_payload),
                title=title,
                description=(
                    f"Cross-domain guideline derived from {len(group)} "
                    f"strategies across {len(seen_domains)} domains"
                ),
                content=best.content,
                when_to_use=(
                    f"Applies across diagram_types: "
                    f"{', '.join(sorted(seen_diagram_types))} | "
                    f"domains: {', '.join(sorted(seen_domains))}"
                ),
                tier="guideline",
                delta_score=best.delta_score,
                confidence=success_rate,
                support_count=len(group),
                generalization_status="promoted",
                validated_domains=sorted(seen_domains),
                validation_success_rate=success_rate,
                evidence_ids=evidence_ids,
            )
            promoted.append(guideline)
            for s in group:
                s.generalization_status = "validated"

        if promoted:
            logger.info("   >> Promoted %d strategies → guidelines", len(promoted))
        return promoted

    def promote_guidelines(
        self,
        guidelines: List[KnowledgeEntry],
    ) -> List[KnowledgeEntry]:
        """Cross-diagram-type promotion: guideline → principle (LLM judge)."""
        if len(guidelines) < 2:
            return []

        min_diagram_types = self.config.principle_min_diagram_types
        min_rate = self.config.principle_success_rate

        groups: Dict[str, List[KnowledgeEntry]] = defaultdict(list)
        for g in guidelines:
            groups[_normalize_title(g.title)].append(g)

        promoted: List[KnowledgeEntry] = []
        for title_key, group in groups.items():
            all_diagram_types: Set[str] = set()
            for g in group:
                all_diagram_types.update(g.tags.diagram_type or ["general"])

            if len(all_diagram_types) < min_diagram_types:
                continue

            success_count = sum(1 for g in group if self._is_promotion_success(g))
            success_rate = success_count / len(group)
            if success_rate < min_rate:
                continue

            logger.info(
                "   >> Evaluating principle promotion for '%s' (%d guidelines, %d diagram types)...",
                title_key,
                len(group),
                len(all_diagram_types),
            )
            try:
                raw_result = self.principle_promoter.run(
                    [g.model_dump() for g in group]
                )
                result = PrinciplePromotionDecision.model_validate(raw_result)
            except ValidationError as e:
                logger.warning(
                    "   [!] PrinciplePromoter returned invalid schema for '%s': %s",
                    title_key,
                    e,
                )
                continue
            except Exception as e:
                logger.warning(
                    "   [!] PrinciplePromoter failed for '%s': %s", title_key, e
                )
                continue

            if not result.should_promote:
                logger.debug(
                    "   >> Not promoting '%s': %s",
                    title_key,
                    result.reasoning or "no reason",
                )
                continue

            best = max(group, key=lambda g: g.delta_score)
            evidence_ids = [g.id for g in group]
            title = result.principle_title or f"[Principle] {title_key}"
            # Tag coverage and validation evidence are different claims: tags
            # say where a guideline was *written for*, validated_domains say
            # where it was actually observed to help. Only the former may fall
            # back to ``tags.domain``.
            seen_domains = {d for g in group for d in g.tags.domain}
            validated_domains = {
                d for g in group for d in (g.validated_domains or [])
            }
            seen_agents = {a for g in group for a in g.tags.agent}
            tags_payload = _promotion_tags_payload(
                domains=seen_domains,
                diagram_types=all_diagram_types,
                agents=seen_agents,
            )
            principle = KnowledgeEntry(
                id=_promotion_id(
                    tier="principle",
                    title=title,
                    tags=tags_payload,
                    evidence_ids=evidence_ids,
                ),
                tags=TagSet(**tags_payload),
                title=title,
                description=result.principle_description
                or f"Principle derived from {len(group)} guidelines",
                content=result.principle_content or best.content,
                when_to_use=result.principle_when_to_use
                or (
                    f"Applies across diagram types: "
                    f"{', '.join(sorted(all_diagram_types))}"
                ),
                tier="principle",
                delta_score=best.delta_score,
                confidence=success_rate,
                support_count=len(group),
                generalization_status="promoted",
                validated_domains=sorted(validated_domains),
                validation_success_rate=success_rate,
                evidence_ids=evidence_ids,
            )
            promoted.append(principle)
            for g in group:
                g.generalization_status = "validated"
            logger.info("   >> Promoted to principle: %s", principle.title)

        return promoted

    def check_demotion(
        self,
        items: List[KnowledgeEntry],
        failed_usage: Dict[str, List[Dict]],
        *,
        just_promoted_ids: Optional[Set[str]] = None,
    ) -> List[KnowledgeEntry]:
        """Find guideline/principle items underperforming in recent usage and,
        if the LLM concurs, downgrade their tier (in place). Returns the list
        of demoted items so the caller can rebalance tier lists.

        *just_promoted_ids* holds the entries promoted during the current
        maintenance cycle; they are skipped because they have no usage history
        at their new tier yet. It must be a cycle-local set. The previous
        implementation used ``generalization_status == "promoted"`` for this,
        but that field is persisted with the entry and restored on the next run,
        so any entry promoted once became permanently immune to demotion even
        when its success rate later collapsed.
        """
        min_usage = self.config.demote_min_usage
        min_rate = self.config.demote_success_rate
        just_promoted_ids = just_promoted_ids or set()

        demoted: List[KnowledgeEntry] = []
        for item in items:
            # Skip items promoted in this cycle — no usage at the new tier yet.
            if item.id in just_promoted_ids:
                continue
            if item.usage_count < min_usage:
                continue
            success_rate = item.success_count / max(item.usage_count, 1)
            if success_rate >= min_rate:
                continue

            logger.info(
                "   >> Evaluating demotion for '%s' (tier=%s, success_rate=%.2f)...",
                item.title,
                item.tier,
                success_rate,
            )
            try:
                usage_key = f"{item.tier}:{item.id}"
                raw_result = self.demotion_judger.run(
                    item.model_dump(), failed_usage.get(usage_key, [])
                )
                result = DemotionDecision.model_validate(raw_result)
            except ValidationError as e:
                logger.warning(
                    "   [!] DemotionJudger returned invalid schema for '%s': %s",
                    item.title,
                    e,
                )
                continue
            except Exception as e:
                logger.warning(
                    "   [!] DemotionJudger failed for '%s': %s", item.title, e
                )
                continue

            reason = result.reasoning or result.reason or "no reason"
            if not result.should_demote:
                logger.debug(
                    "   >> Keeping '%s' at %s: %s",
                    item.title,
                    item.tier,
                    reason,
                )
                continue

            new_tier = result.new_tier
            if item.tier == "guideline" and new_tier != "strategy":
                logger.warning(
                    "   [!] DemotionJudger requested invalid downgrade for '%s': %s → %s",
                    item.title,
                    item.tier,
                    new_tier,
                )
                continue
            if item.tier == "principle" and new_tier != "guideline":
                logger.warning(
                    "   [!] DemotionJudger requested invalid downgrade for '%s': %s → %s",
                    item.title,
                    item.tier,
                    new_tier,
                )
                continue
            item.tier = new_tier
            item.generalization_status = "local"
            item.validated_domains = []
            if result.updated_when_to_use:
                item.when_to_use = result.updated_when_to_use
            demoted.append(item)
            logger.info(
                "   >> Demoted '%s' → %s: %s",
                item.title,
                new_tier,
                reason,
            )

        return demoted
