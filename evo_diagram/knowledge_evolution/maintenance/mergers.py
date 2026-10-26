"""Merge logic and title-similarity clustering for the MaintenanceCycle.

- merge_tier: cluster by title similarity, LLM judge to merge each cluster
- _cluster_by_embedding: cosine similarity over title embeddings (preferred)
- _cluster_by_title: Jaccard token similarity (fallback when no embedder)
- _apply_tier_shifts: rebalance tier lists after demotion
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError, model_validator

from ..schemas import KnowledgeEntry, TagSet


logger = logging.getLogger(__name__)


def _has_text(value: Optional[str]) -> bool:
    return isinstance(value, str) and bool(value.strip())


class MergeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    should_merge: StrictBool
    merged_title: Optional[str] = None
    merged_description: Optional[str] = None
    merged_content: Optional[str] = None
    merged_when_to_use: Optional[str] = None
    reasoning: Optional[str] = None

    @model_validator(mode="after")
    def _require_merged_fields(self) -> "MergeDecision":
        if self.should_merge:
            missing = [
                field
                for field in (
                    "merged_title",
                    "merged_description",
                    "merged_content",
                    "merged_when_to_use",
                )
                if not _has_text(getattr(self, field))
            ]
            if missing:
                raise ValueError(
                    "merge decisions with should_merge=true require: "
                    + ", ".join(missing)
                )
        return self


# ---------------------------------------------------------------------------
# Title-similarity clustering for global merge
# ---------------------------------------------------------------------------

_GUIDELINE_PREFIX = "[Guideline] "
_PRINCIPLE_PREFIX = "[Principle] "


def _normalize_title(title: str) -> str:
    return (
        title.replace(_GUIDELINE_PREFIX, "")
        .replace(_PRINCIPLE_PREFIX, "")
        .strip()
        .lower()
    )


def _title_tokens(title: str) -> Set[str]:
    return {tok for tok in _normalize_title(title).split() if tok}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Standalone cosine — mirrors the helper in DiagramDesignRetriever."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _union_find_clusters(
    n: int, edges: List[Tuple[int, int]]
) -> Dict[int, int]:
    """Union-find over an undirected edge set. Returns ``index → root``."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i, j in edges:
        union(i, j)
    return {idx: find(idx) for idx in range(n)}


def _cluster_by_title(
    items: List[KnowledgeEntry],
    threshold: float,
) -> List[List[KnowledgeEntry]]:
    """Group items whose titles share ≥ ``threshold`` Jaccard token similarity.

    Fallback for when no embedding function is wired in (e.g. retrieval
    disabled, unit tests). Naked token Jaccard is brittle on paraphrases —
    the engine prefers :func:`_cluster_by_embedding` when an embedder is
    available (RISKS.md #19).
    """
    n = len(items)
    if n < 2:
        return [[item] for item in items]

    token_sets = [_title_tokens(item.title) for item in items]
    edges: List[Tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard(token_sets[i], token_sets[j]) >= threshold:
                edges.append((i, j))

    roots = _union_find_clusters(n, edges)
    groups: Dict[int, List[KnowledgeEntry]] = defaultdict(list)
    for idx, item in enumerate(items):
        groups[roots[idx]].append(item)
    return list(groups.values())


def _cluster_by_embedding(
    items: List[KnowledgeEntry],
    threshold: float,
    embed_documents: Callable[[List[str]], List[List[float]]],
) -> List[List[KnowledgeEntry]]:
    """Cluster items by cosine similarity over title embeddings.

    Replaces naked Jaccard for the merge-clustering step (RISKS.md #19) so
    paraphrases like ``"Add icons to nodes"`` and ``"Annotate nodes with
    icons"`` cluster despite low token overlap, while semantically distinct
    titles that happen to share filler words ("Use a flowchart" /
    "Choose a flowchart") don't get bundled.

    A single batched ``embed_documents`` call runs once per tier; pairwise
    comparisons are pure math. Falls back to Jaccard clustering on embedding
    failure so the maintenance cycle never aborts on a transient embedder
    error.
    """
    n = len(items)
    if n < 2:
        return [[item] for item in items]

    titles = [_normalize_title(item.title) for item in items]
    try:
        embeddings = embed_documents(titles)
    except Exception as exc:
        logger.warning(
            "Embedding-based title clustering failed (%s); falling back to Jaccard.",
            exc,
        )
        # Use a Jaccard threshold rather than the cosine one — they're not
        # interchangeable. Conservatively pick 0.6 (the default Jaccard cap).
        return _cluster_by_title(items, 0.6)

    if not embeddings or len(embeddings) != n:
        logger.warning(
            "Embedder returned %d vectors for %d titles; falling back to Jaccard.",
            len(embeddings) if embeddings else 0,
            n,
        )
        return _cluster_by_title(items, 0.6)

    edges: List[Tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if _cosine_similarity(embeddings[i], embeddings[j]) >= threshold:
                edges.append((i, j))

    roots = _union_find_clusters(n, edges)
    groups: Dict[int, List[KnowledgeEntry]] = defaultdict(list)
    for idx, item in enumerate(items):
        groups[roots[idx]].append(item)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Deterministic content-addressable IDs (RISKS.md #20)
# ---------------------------------------------------------------------------

def _content_hash(title: str, tags: Optional[Dict[str, Any]] = None) -> str:
    """Stable 8-char hex digest of ``(title, tags)``.

    Used in place of ``uuid.uuid4().hex[:8]`` so the same conceptual item
    produced by two different runs gets the same ID, enabling deduplication
    against ``state.loaded_ids`` (RISKS.md #20). Only the title and tag
    set matter — content / when_to_use can drift across runs without
    breaking the stable identity.
    """
    tag_payload: Dict[str, Any] = {}
    if tags:
        for k, v in tags.items():
            if isinstance(v, list):
                tag_payload[k] = sorted(str(x) for x in v)
            else:
                tag_payload[k] = v
    payload = json.dumps(
        {"title": _normalize_title(title), "tags": tag_payload},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Tier-shift bookkeeping after demotion
# ---------------------------------------------------------------------------

def _apply_tier_shifts(
    strategies: List[KnowledgeEntry],
    guidelines: List[KnowledgeEntry],
    principles: List[KnowledgeEntry],
    demoted: List[KnowledgeEntry],
) -> Tuple[List[KnowledgeEntry], List[KnowledgeEntry], List[KnowledgeEntry]]:
    """Move demoted items between tier lists according to their new ``tier``.

    Each demoted item already has its ``tier`` field updated by the demotion
    judger; this routine only rebalances the three tier lists so the caller's
    state stays in sync. Returns the updated (strategies, guidelines, principles).
    """
    demoted_ids = {item.id for item in demoted}
    new_strategies = list(strategies)
    new_guidelines = [g for g in guidelines if g.id not in demoted_ids]
    new_principles = [p for p in principles if p.id not in demoted_ids]

    for item in demoted:
        if item.tier == "principle":
            new_principles.append(item)
        elif item.tier == "guideline":
            new_guidelines.append(item)
        elif item.tier == "strategy":
            new_strategies.append(item)
        else:
            raise ValueError(f"Invalid demoted tier: {item.tier!r}")

    return new_strategies, new_guidelines, new_principles


# ---------------------------------------------------------------------------
# MergerMixin — merge_tier and helpers
# ---------------------------------------------------------------------------

class MergerMixin:
    """Merge logic mixed into MaintenanceCycle.

    Expects ``self.config``, ``self.merge_judger``, and (optional)
    ``self.embedding_function`` to be set by the host class. When the
    embedding function is provided, title clustering uses cosine similarity
    over title embeddings (RISKS.md #19); otherwise it falls back to token
    Jaccard.
    """

    def merge_tier(
        self,
        items: List[KnowledgeEntry],
        tier: str,
    ) -> Tuple[List[KnowledgeEntry], int]:
        """Within a tier, cluster by title similarity and ask the LLM to merge
        each cluster of ≥2 items. Returns (deduped_items, n_merges_applied).
        """
        if len(items) < 2:
            return items, 0

        clusters = self._cluster_titles(items)
        max_group = self.config.merge_max_group_size
        merged_count = 0
        result: List[KnowledgeEntry] = []

        for cluster in clusters:
            if len(cluster) < 2:
                result.extend(cluster)
                continue

            # Cap LLM input to keep prompts bounded
            candidates = cluster[:max_group]
            leftovers = cluster[max_group:]

            decision = self._call_merge_judger(tier, candidates)
            if decision is None or not decision.get("should_merge", False):
                if decision is not None:
                    reason = decision.get("reasoning", "no reason")
                    logger.debug("   >> Skipped merge in %s: %s", tier, reason)
                result.extend(cluster)
                continue

            merged = self._build_merged_entry(tier, candidates, decision)
            result.append(merged)
            result.extend(leftovers)
            merged_count += 1
            logger.info(
                "   >> Merged %d %s items into '%s'",
                len(candidates),
                tier,
                merged.title,
            )

        return result, merged_count

    def _cluster_titles(
        self, items: List[KnowledgeEntry]
    ) -> List[List[KnowledgeEntry]]:
        """Pick the right clustering backend.

        Embedding-based when ``self.embedding_function`` is wired (covers
        paraphrases / synonymy); Jaccard fallback otherwise so unit tests and
        offline design-memory runs still work.
        """
        embed_fn = getattr(self, "embedding_function", None)
        if embed_fn is not None:
            embed_documents = getattr(embed_fn, "embed_documents", None)
            if callable(embed_documents):
                return _cluster_by_embedding(
                    items,
                    self.config.merge_title_embedding_similarity,
                    embed_documents,
                )
        return _cluster_by_title(items, self.config.merge_title_similarity)

    def _call_merge_judger(
        self,
        tier: str,
        candidates: List[KnowledgeEntry],
    ) -> Optional[Dict]:
        try:
            raw = self.merge_judger.run(tier, [c.model_dump() for c in candidates])
            decision = MergeDecision.model_validate(raw)
            return decision.model_dump(exclude_none=True)
        except ValidationError as e:
            logger.warning("   [!] MergeJudger returned invalid schema for %s: %s", tier, e)
            return None
        except Exception as e:
            logger.warning("   [!] MergeJudger failed for %s: %s", tier, e)
            return None

    @staticmethod
    def _build_merged_entry(
        tier: str,
        sources: List[KnowledgeEntry],
        decision: Dict,
    ) -> KnowledgeEntry:
        """Construct a merged KnowledgeEntry, taking the strongest evidence
        from the source group while overlaying LLM-synthesized text fields.
        """
        # Pick the source with the highest delta_score as the structural base
        base = max(sources, key=lambda s: s.delta_score)

        # Union tags across sources (preserves cross-domain provenance)
        union_domains: Set[str] = set()
        union_diagram_types: Set[str] = set()
        union_agents: Set[str] = set()
        union_validated_domains: Set[str] = set()
        union_evidence_ids: List[str] = []
        for s in sources:
            union_domains.update(s.tags.domain)
            union_diagram_types.update(s.tags.diagram_type)
            union_agents.update(s.tags.agent)
            # Only domains that were actually validated carry over. Falling back
            # to ``s.tags.domain`` here would let three brand-new, never-used
            # guidelines tagged finance / medical / legal merge into an entry
            # claiming three *validated* domains, which downstream promotion
            # gates then read as cross-domain evidence. Tag coverage is already
            # preserved in ``union_domains``.
            union_validated_domains.update(s.validated_domains or [])
            union_evidence_ids.append(s.id)

        # Aggregate scores: best Δ, sum support, max success rate
        best_delta = max(s.delta_score for s in sources)
        total_support = sum(s.support_count for s in sources)
        best_success_rate = max(
            (s.success_count / max(s.usage_count, 1) for s in sources),
            default=0.0,
        )
        total_usage = sum(s.usage_count for s in sources)
        total_success = sum(s.success_count for s in sources)

        merged_title = decision.get("merged_title", base.title)
        # Deterministic ID over (title, tags) so re-running on the same data
        # produces stable IDs and enables dedup (RISKS.md #20). The
        # ``_merged_`` infix preserves the legacy naming convention so
        # search/log filters that look for it keep working.
        merged_id_hash = _content_hash(
            merged_title,
            {
                "domain": sorted(union_domains),
                "diagram_type": sorted(union_diagram_types),
                "agent": sorted(union_agents),
            },
        )
        return KnowledgeEntry(
            id=f"{tier}_merged_{merged_id_hash}",
            tags=TagSet(
                domain=sorted(union_domains),
                diagram_type=sorted(union_diagram_types),
                agent=sorted(union_agents),
            ),
            title=merged_title,
            description=decision.get("merged_description", base.description),
            content=decision.get("merged_content", base.content),
            when_to_use=decision.get("merged_when_to_use", base.when_to_use),
            tier=tier,
            delta_score=best_delta,
            confidence=best_success_rate,
            usage_count=total_usage,
            success_count=total_success,
            support_count=max(total_support, len(sources)),
            generalization_status="merged",
            validated_domains=sorted(union_validated_domains),
            validation_success_rate=best_success_rate,
            evidence_ids=union_evidence_ids,
        )
