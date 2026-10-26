import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Type

from .config import KnowledgeEvolutionConfig
from .schemas import load_dataset
from .iteration import RefineLoop
from evo_diagram.utils.io_utils import ensure_dirs, save_json
from .schemas import CONTROL_SCORE_KEY, IterationRecord, KnowledgeEntry
from .maintenance import MaintenanceCycle
from .maintenance.mergers import _content_hash

from evo_diagram.core.llm_factory import LLMFactory
from .distillation.curators import StrategyExtractorAgent
from .distillation.promoters import GuidelineExtractorAgent, PrinciplePromoterAgent
from .distillation.judges import DemotionJudgerAgent, MergeJudgerAgent

from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow
from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow


logger = logging.getLogger(__name__)

# Resolved lazily because ``design_memory`` imports ChromaDB. Knowledge
# evolution has pure logic and offline design-memory runs that should not need
# the vector DB dependency at module-import time.
DiagramDesignMemory: Optional[Type[Any]] = None
DiagramDesignRetriever: Optional[Type[Any]] = None


def _resolve_design_memory_classes() -> Tuple[Type[Any], Type[Any]]:
    global DiagramDesignMemory, DiagramDesignRetriever

    if DiagramDesignMemory is None or DiagramDesignRetriever is None:
        from evo_diagram.design_memory import (
            DiagramDesignMemory as ImportedDesignMemory,
            DiagramDesignRetriever as ImportedDesignRetriever,
        )

        if DiagramDesignMemory is None:
            DiagramDesignMemory = ImportedDesignMemory
        if DiagramDesignRetriever is None:
            DiagramDesignRetriever = ImportedDesignRetriever

    return DiagramDesignMemory, DiagramDesignRetriever


class DesignMemoryMode(str, Enum):
    ENABLED = "enabled"
    OFFLINE = "offline"


def _normalize_design_memory_mode(value: DesignMemoryMode | str) -> DesignMemoryMode:
    if isinstance(value, DesignMemoryMode):
        return value
    try:
        return DesignMemoryMode(str(value))
    except ValueError as exc:
        valid = ", ".join(mode.value for mode in DesignMemoryMode)
        raise ValueError(f"design_memory_mode must be one of: {valid}") from exc


_MEMORY_OPERATION_TYPES = {"add", "update"}
_MEMORY_ADD_REQUIRED_FIELDS = ("title", "description", "content", "when_to_use")
_MEMORY_UPDATE_FIELDS = ("title", "description", "content", "when_to_use")
_MEMORY_TAG_KEYS = ("domain", "diagram_type", "agent")
# Entries requested per knowledge layer for one sample. The retriever owns the
# quota of diagram-type-agnostic entries merged in on top of this.
_RETRIEVAL_TOP_K = 5
# Version suffix appended by ``DiagramDesignMemory._next_version_id``.
_VERSION_SUFFIX_RE = re.compile(r"_v\d+$")


def _memory_operation_error(item_type: str, index: int, message: str) -> RuntimeError:
    return RuntimeError(
        f"Invalid {item_type} memory operation at index {index}: {message}"
    )


def _base_entry_id(item_id: str) -> str:
    """Strip the ``_v<N>`` suffix ``DiagramDesignMemory`` appends on collision.

    ``guideline_ab12cd34`` and ``guideline_ab12cd34_v2`` are the same piece of
    knowledge; only the storage layer distinguishes them.
    """
    return _VERSION_SUFFIX_RE.sub("", str(item_id))


# ---------------------------------------------------------------------------
# "Did the retrieved knowledge help?" — the signal behind every usage stat
# ---------------------------------------------------------------------------


class KnowledgeSuccessCriterion(str, Enum):
    """How a sample is judged to have succeeded with the knowledge it retrieved.

    ``FIRST_PASS_VS_HISTORY`` (default) — the first iteration's ``score_before``
    compared against the running mean of first-pass scores observed so far for
    comparable tasks. Free to compute, but the baseline is a moving,
    partly-self-referential target.

    ``FIRST_PASS_VS_CONTROL`` — the first iteration's ``score_before`` compared
    against a knowledge-free control generation of the *same* sample. The clean
    causal comparison; costs one extra generator call per sample and requires
    ``config.first_pass_control_run``.

    ``REFINER_DELTA`` — the historical criterion, retained for reproducing
    earlier results. See :func:`evaluate_knowledge_outcome` for why it points
    the wrong way.
    """

    FIRST_PASS_VS_HISTORY = "first_pass_vs_history"
    FIRST_PASS_VS_CONTROL = "first_pass_vs_control"
    REFINER_DELTA = "refiner_delta"


# Schema version stamped into the persisted first-pass baseline JSON.
_FIRST_PASS_BASELINE_VERSION = 1


@dataclass
class FirstPassBaseline:
    """Running mean of first-pass objective scores, bucketed by task shape.

    Buckets are consulted most-specific first — ``(diagram_type, content_area)``
    → ``diagram_type`` → global — and a bucket is only usable once it holds
    ``min_samples`` observations. The global bucket fills within the first few
    samples of a run, so the cold-start window is short.

    Observations are recorded *after* the sample has been judged, so a sample
    never contributes to the baseline it is measured against.
    """

    min_samples: int = 3
    pair_stats: Dict[Tuple[str, str], Tuple[int, float]] = field(default_factory=dict)
    diagram_type_stats: Dict[str, Tuple[int, float]] = field(default_factory=dict)
    global_stats: Tuple[int, float] = (0, 0.0)

    @staticmethod
    def _mean(stats: Tuple[int, float]) -> float:
        count, total = stats
        return total / count

    def lookup(
        self, diagram_type: str, content_area: str
    ) -> Optional[Tuple[float, str]]:
        """Return ``(baseline, bucket_label)`` or ``None`` during cold start."""
        candidates = (
            (self.pair_stats.get((diagram_type, content_area)), f"{diagram_type}/{content_area}"),
            (self.diagram_type_stats.get(diagram_type), diagram_type),
            (self.global_stats, "all samples"),
        )
        for stats, label in candidates:
            if stats and stats[0] >= self.min_samples:
                return self._mean(stats), f"{label} (n={stats[0]})"
        return None

    def observe(self, diagram_type: str, content_area: str, score: float) -> None:
        def _add(stats: Optional[Tuple[int, float]]) -> Tuple[int, float]:
            count, total = stats or (0, 0.0)
            return count + 1, total + score

        self.pair_stats[(diagram_type, content_area)] = _add(
            self.pair_stats.get((diagram_type, content_area))
        )
        self.diagram_type_stats[diagram_type] = _add(
            self.diagram_type_stats.get(diagram_type)
        )
        self.global_stats = _add(self.global_stats)

    # ── Persistence (see FirstPassBaselineStore) ─────────────────────────
    #
    # Buckets are stored as ``{count, sum}`` — the same quantity the in-memory
    # representation carries, so a save/load round trip is lossless and the
    # running mean stays exact (no Welford reconstruction error). ``pair_stats``
    # is nested ``{diagram_type: {content_area: ...}}`` rather than joined
    # string keys because bucket labels are arbitrary user-visible text.

    def to_dict(self) -> Dict[str, Any]:
        pair_stats: Dict[str, Any] = {}
        for (diagram_type, content_area), (count, total) in self.pair_stats.items():
            pair_stats.setdefault(diagram_type, {})[content_area] = {
                "count": count,
                "sum": total,
            }
        return {
            "version": _FIRST_PASS_BASELINE_VERSION,
            "pair_stats": pair_stats,
            "diagram_type_stats": {
                diagram_type: {"count": count, "sum": total}
                for diagram_type, (count, total) in self.diagram_type_stats.items()
            },
            "global": {"count": self.global_stats[0], "sum": self.global_stats[1]},
        }

    @classmethod
    def from_dict(cls, data: Any, *, min_samples: int) -> "FirstPassBaseline":
        """Rebuild a baseline from its persisted form.

        ``min_samples`` is deliberately *not* read from the payload: the
        threshold is a config decision of the current run, only the evidence
        (counts and sums) is persisted. Raises ``ValueError`` on any structural
        problem so the store can degrade to an empty baseline with a warning.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"baseline payload must be an object, got {type(data).__name__}"
            )
        version = data.get("version")
        if version != _FIRST_PASS_BASELINE_VERSION:
            raise ValueError(
                f"unsupported baseline version {version!r}; expected "
                f"{_FIRST_PASS_BASELINE_VERSION}"
            )

        def _stats(payload: Any, where: str) -> Tuple[int, float]:
            if (
                not isinstance(payload, dict)
                or "count" not in payload
                or "sum" not in payload
            ):
                raise ValueError(
                    f"{where}: expected an object with 'count' and 'sum', "
                    f"got {payload!r}"
                )
            count = payload["count"]
            total = payload["sum"]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(
                    f"{where}: 'count' must be a non-negative integer, got {count!r}"
                )
            if isinstance(total, bool) or not isinstance(total, (int, float)):
                raise ValueError(f"{where}: 'sum' must be a number, got {total!r}")
            return count, float(total)

        baseline = cls(min_samples=min_samples)

        pair_raw = data.get("pair_stats", {})
        if not isinstance(pair_raw, dict):
            raise ValueError("pair_stats must be an object")
        for diagram_type, areas in pair_raw.items():
            if not isinstance(areas, dict):
                raise ValueError(f"pair_stats[{diagram_type!r}] must be an object")
            for content_area, payload in areas.items():
                baseline.pair_stats[(diagram_type, content_area)] = _stats(
                    payload, f"pair_stats[{diagram_type!r}][{content_area!r}]"
                )

        type_raw = data.get("diagram_type_stats", {})
        if not isinstance(type_raw, dict):
            raise ValueError("diagram_type_stats must be an object")
        for diagram_type, payload in type_raw.items():
            baseline.diagram_type_stats[diagram_type] = _stats(
                payload, f"diagram_type_stats[{diagram_type!r}]"
            )

        baseline.global_stats = _stats(
            data.get("global", {"count": 0, "sum": 0.0}), "global"
        )
        return baseline


class FirstPassBaselineStore:
    """JSON persistence for :class:`FirstPassBaseline` bucket statistics.

    The file lives beside the design-memory vector DB (path resolved by
    :class:`KnowledgeEvolutionConfig`) because the baseline is accumulated
    evidence about the knowledge base, not a per-run artifact: with it, the
    ``min_samples`` cold-start window happens once in the system's lifetime
    instead of at the head of every run.

    Robustness contract:

    - :meth:`load` never raises — a missing, unreadable or malformed file
      degrades to an empty baseline (with a warning for the corrupt cases) so
      a damaged stats cache can never brick an evolution run.
    - :meth:`save` writes atomically (tmp file + ``os.replace``) so a crash
      mid-write leaves the previous valid file in place, never a half-written
      one.
    """

    def __init__(self, path: str):
        self.path = path

    def load(self, *, min_samples: int) -> FirstPassBaseline:
        if not os.path.exists(self.path):
            logger.info(
                "No persisted first-pass baseline at %s; starting cold.",
                self.path,
            )
            return FirstPassBaseline(min_samples=min_samples)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            baseline = FirstPassBaseline.from_dict(data, min_samples=min_samples)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "Could not load persisted first-pass baseline from %s (%s: %s); "
                "starting with an empty baseline.",
                self.path,
                type(exc).__name__,
                exc,
            )
            return FirstPassBaseline(min_samples=min_samples)
        logger.info(
            "Loaded persisted first-pass baseline from %s (global n=%d).",
            self.path,
            baseline.global_stats[0],
        )
        return baseline

    def save(self, baseline: FirstPassBaseline) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(baseline.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)


@dataclass(frozen=True)
class KnowledgeOutcome:
    """Verdict on one sample, plus the numbers behind it (for logs / audits).

    ``INDETERMINATE`` is a real third state, not a soft failure: the sample is
    excluded from usage bookkeeping entirely. Counting an unjudgeable sample as
    a failure would inflate ``usage_count`` without ``success_count`` and push
    perfectly good knowledge towards demotion.
    """

    verdict: str  # "success" | "failure" | "indeterminate"
    criterion: KnowledgeSuccessCriterion
    detail: str
    score: Optional[float] = None
    baseline: Optional[float] = None

    @property
    def is_success(self) -> bool:
        return self.verdict == "success"

    @property
    def is_indeterminate(self) -> bool:
        return self.verdict == "indeterminate"


def _first_pass_observation(history: List[IterationRecord]) -> Tuple[str, str, float]:
    """``(diagram_type, content_area, score_before)`` of the first iteration."""
    first = history[0]
    evaluation = first.evaluation if isinstance(first.evaluation, dict) else {}
    score_before = evaluation.get("score_before")
    if score_before is None:
        raise RuntimeError(
            "First-pass success criteria require evaluation['score_before'] on "
            f"iteration record {first.id!r}"
        )
    diagram_type = (first.tags.diagram_type or [""])[0]
    content_area = (first.tags.domain or [""])[0]
    return diagram_type, content_area, float(score_before)


def _refiner_delta_outcome(history, config, baseline) -> KnowledgeOutcome:
    best_delta = max(r.delta_score for r in history)
    succeeded = best_delta >= config.delta_score_threshold
    return KnowledgeOutcome(
        verdict="success" if succeeded else "failure",
        criterion=KnowledgeSuccessCriterion.REFINER_DELTA,
        detail=f"best refiner Δscore {best_delta:.2f} vs threshold {config.delta_score_threshold}",
        score=best_delta,
    )


def _first_pass_vs_history_outcome(history, config, baseline) -> KnowledgeOutcome:
    criterion = KnowledgeSuccessCriterion.FIRST_PASS_VS_HISTORY
    diagram_type, content_area, score_before = _first_pass_observation(history)
    if baseline is None:
        raise RuntimeError(
            "knowledge_success_criterion='first_pass_vs_history' requires a "
            "FirstPassBaseline; the caller must thread run state through."
        )
    resolved = baseline.lookup(diagram_type, content_area)
    if resolved is None:
        return KnowledgeOutcome(
            verdict="indeterminate",
            criterion=criterion,
            detail=(
                f"no baseline yet for {diagram_type!r}/{content_area!r} "
                f"(need {baseline.min_samples} prior samples)"
            ),
            score=score_before,
        )
    baseline_score, bucket = resolved
    margin = config.first_pass_success_margin
    succeeded = score_before >= baseline_score + margin
    return KnowledgeOutcome(
        verdict="success" if succeeded else "failure",
        criterion=criterion,
        detail=(
            f"first-pass score {score_before:.2f} vs baseline {baseline_score:.2f} "
            f"from {bucket}, margin {margin}"
        ),
        score=score_before,
        baseline=baseline_score,
    )


def _first_pass_vs_control_outcome(history, config, baseline) -> KnowledgeOutcome:
    criterion = KnowledgeSuccessCriterion.FIRST_PASS_VS_CONTROL
    _diagram_type, _content_area, score_before = _first_pass_observation(history)
    evaluation = history[0].evaluation if isinstance(history[0].evaluation, dict) else {}
    control = evaluation.get(CONTROL_SCORE_KEY)
    if control is None:
        raise RuntimeError(
            "knowledge_success_criterion='first_pass_vs_control' requires "
            f"evaluation[{CONTROL_SCORE_KEY!r}] on iteration record "
            f"{history[0].id!r}; enable config.first_pass_control_run."
        )
    control_score = float(control)
    margin = config.first_pass_success_margin
    succeeded = score_before >= control_score + margin
    return KnowledgeOutcome(
        verdict="success" if succeeded else "failure",
        criterion=criterion,
        detail=(
            f"first-pass score {score_before:.2f} vs knowledge-free control "
            f"{control_score:.2f}, margin {margin}"
        ),
        score=score_before,
        baseline=control_score,
    )


_SUCCESS_CRITERIA = {
    KnowledgeSuccessCriterion.FIRST_PASS_VS_HISTORY: _first_pass_vs_history_outcome,
    KnowledgeSuccessCriterion.FIRST_PASS_VS_CONTROL: _first_pass_vs_control_outcome,
    KnowledgeSuccessCriterion.REFINER_DELTA: _refiner_delta_outcome,
}


def evaluate_knowledge_outcome(
    history: List[IterationRecord],
    config: KnowledgeEvolutionConfig,
    *,
    baseline: Optional[FirstPassBaseline] = None,
    criterion: Optional[KnowledgeSuccessCriterion | str] = None,
) -> KnowledgeOutcome:
    """Judge whether the knowledge retrieved for a sample helped.

    This verdict is the *only* reward signal in the whole knowledge lifecycle.
    It feeds ``_update_usage_stats`` (``success_count``) and
    ``_record_failed_usage``, which in turn drive
    ``maintenance.promoters.PromoterMixin._is_promotion_success`` and
    ``check_demotion``, ``maintenance.mergers`` score aggregation,
    ``maintenance.cycle.compute_confidence`` and
    ``design_memory.DiagramDesignRetriever._utility_score``.

    **The two scores in an iteration record measure different things and must
    not be substituted for one another.**

    - ``score_before`` is the objective score of the diagram the *generator*
      produced while holding the retrieved knowledge. The knowledge reaches the
      generator and only the generator
      (``iteration.loop.RefineLoop.run_loop`` passes it as
      ``design_expertise``), so this is the quantity the knowledge is
      responsible for.
    - ``delta_score = score_after - score_before`` is how much the *refiner*
      repaired. The refiner never sees the retrieved knowledge.

    The pipeline previously judged knowledge by ``delta_score``, which inverts
    the signal: since ``iteration.loop._compute_objective_score`` rewards fewer
    findings, good knowledge produces a near-clean first diagram, leaves the
    refiner nothing to fix, yields a small delta, and was recorded as a
    **failure** destined for ``failed_usage`` and demotion — while bad knowledge
    produced a poor first diagram, a large refiner repair, and was recorded as a
    **success**. ``REFINER_DELTA`` is kept only to reproduce earlier runs.

    A first-pass score is meaningful only against a baseline, because the
    absolute score is dominated by how hard the sample is. Two baselines are
    available (see :class:`KnowledgeSuccessCriterion`): the running historical
    mean (default, free, moving target) and a paired knowledge-free control
    generation (rigorous, one extra generator call per sample).

    Returns a :class:`KnowledgeOutcome`. ``INDETERMINATE`` means the sample
    could not be judged — during the historical criterion's cold start, or when
    no history exists — and the caller must exclude it from usage bookkeeping
    rather than treat it as a failure.
    """
    resolved = KnowledgeSuccessCriterion(
        criterion if criterion is not None else config.knowledge_success_criterion
    )
    if not history:
        return KnowledgeOutcome(
            verdict="indeterminate",
            criterion=resolved,
            detail="no iteration history recorded for this sample",
        )
    return _SUCCESS_CRITERIA[resolved](history, config, baseline)


def _require_op_string(
    op: Dict[str, Any],
    field: str,
    *,
    item_type: str,
    index: int,
    op_type: str,
) -> str:
    value = op.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _memory_operation_error(
            item_type,
            index,
            f"{op_type} operation requires non-empty string field {field!r}",
        )
    return value.strip()


def _require_tags_payload(
    op: Dict[str, Any],
    *,
    item_type: str,
    index: int,
) -> Dict[str, List[str]]:
    if "_tags" not in op:
        raise _memory_operation_error(
            item_type,
            index,
            "add operation requires _tags from the distillation grouping context",
        )
    tags = op["_tags"]
    if not isinstance(tags, dict):
        raise _memory_operation_error(
            item_type,
            index,
            "add operation _tags must be an object",
        )
    unknown_keys = sorted(set(tags) - set(_MEMORY_TAG_KEYS))
    if unknown_keys:
        raise _memory_operation_error(
            item_type,
            index,
            f"add operation _tags has unknown keys: {', '.join(unknown_keys)}",
        )

    normalized: Dict[str, List[str]] = {}
    for key in _MEMORY_TAG_KEYS:
        value = tags.get(key, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise _memory_operation_error(
                item_type,
                index,
                f"add operation _tags.{key} must be a list of strings",
            )
        normalized[key] = [item for item in value if item]
    return normalized


def _strategy_fingerprint(entry: KnowledgeEntry) -> str:
    """Stable digest of the strategy fields guideline distillation reads.

    Two entries with the same id but different text, tags, polarity or
    ``delta_score`` are different distillation inputs and must both be seen by
    ``_run_distillation``; two identical entries must not be distilled twice.
    """
    payload = {
        "domain": sorted(entry.tags.domain),
        "diagram_type": sorted(entry.tags.diagram_type),
        "agent": sorted(entry.tags.agent),
        "description": entry.description,
        "content": entry.content,
        "when_to_use": entry.when_to_use,
        "polarity": entry.polarity,
        "delta_score": entry.delta_score,
    }
    return _content_hash(entry.title, payload)


@dataclass
class _RunState:
    """In-memory bag of knowledge collected during a run.

    Threaded through the three phase methods (iteration → maintenance →
    persist) so the top-level :meth:`DiagramKnowledgeEvolverEngine.run` stays linear.

    ``loaded_ids`` records which entries were already in the vector DB at
    startup, so :meth:`_persist_results` can distinguish updates (existing IDs)
    from new entries (versioning eligible) and from deletions (loaded IDs that
    fell out of state via prune).

    ``all_strategies`` is the active positive strategy set. Neutral strategies
    and anti-patterns are retained in separate audit lists so they cannot be
    retrieved, merged, or promoted as positive knowledge.

    ``distilled_strategy_fingerprints`` maps a strategy id to a fingerprint of
    the version that was last fed to guideline distillation. An id that is
    absent, or present with a stale fingerprint, is re-distilled.

    It replaces an earlier integer high-water mark into ``all_strategies``,
    which silently broke on the second run over the same dataset: strategy ids
    are deterministic (``f"{sample_id}_{key}"``), and
    ``_upsert_entries_by_id`` merges a repeated id *in place* rather than
    appending, so the list length never grew past the seeded count and
    ``all_strategies[count:]`` was always empty. Distillation then returned
    immediately while still logging as if it had run.
    """

    all_strategies: List[KnowledgeEntry] = field(default_factory=list)
    neutral_strategies: List[KnowledgeEntry] = field(default_factory=list)
    anti_patterns: List[KnowledgeEntry] = field(default_factory=list)
    all_samples_history: List[IterationRecord] = field(default_factory=list)
    current_guidelines: List[KnowledgeEntry] = field(default_factory=list)
    current_principles: List[KnowledgeEntry] = field(default_factory=list)
    failed_usage: Dict[str, List[Dict]] = field(
        default_factory=lambda: defaultdict(list)
    )
    sample_failures: List[Dict[str, Any]] = field(default_factory=list)
    loaded_ids: Dict[str, Set[str]] = field(
        default_factory=lambda: {"strategy": set(), "guideline": set(), "principle": set()}
    )
    distilled_strategy_fingerprints: Dict[str, str] = field(default_factory=dict)
    first_pass_baseline: FirstPassBaseline = field(default_factory=FirstPassBaseline)
    indeterminate_samples: List[Dict[str, Any]] = field(default_factory=list)

    def pending_distillation(self) -> List[KnowledgeEntry]:
        """Strategies whose current content has not been distilled yet."""
        return [
            entry
            for entry in self.all_strategies
            if self.distilled_strategy_fingerprints.get(entry.id)
            != _strategy_fingerprint(entry)
        ]

    def mark_distilled(self, entries: List[KnowledgeEntry]) -> None:
        """Record ``entries`` as distilled at their current content."""
        for entry in entries:
            self.distilled_strategy_fingerprints[entry.id] = _strategy_fingerprint(entry)


class DiagramKnowledgeEvolverEngine:
    """Top-level orchestrator for the DiagramKnowledgeEvolver evolution loop.

    Owns the agents, retrieval, and refinement service; delegates all
    set-level passes (Score / Prune / Promote / Demote / Merge) to
    :class:`MaintenanceCycle`. Three phases:

    1. ``_run_iteration_phase`` — for each sample: refine → filter → distill
    2. ``_run_maintenance_phase`` — full Active Knowledge Maintenance pass
    3. ``_persist_results`` — write JSON + push into vector DB
    """

    def __init__(
        self,
        config: Optional[KnowledgeEvolutionConfig] = None,
        design_memory_mode: DesignMemoryMode | str | None = None,
    ):
        self.config = config or KnowledgeEvolutionConfig()
        self.design_memory_mode = _normalize_design_memory_mode(
            DesignMemoryMode.ENABLED
            if design_memory_mode is None
            else design_memory_mode
        )

        ensure_dirs(self.config.output_dir, self.config.images_dir, self.config.code_dir, self.config.results_dir)

        self._memory = None
        self._retriever = None
        if self._uses_design_memory():
            memory_cls, retriever_cls = _resolve_design_memory_classes()
            self._memory = memory_cls(
                embedding_model_name=self.config.embedding_model_name,
            )
            self._retriever = retriever_cls(design_memory=self._memory)
        # Cross-run persistence for the ``first_pass_vs_history`` baseline.
        # Independent of design_memory_mode: it is a small JSON file beside the
        # vector DB, not a vector-store operation, so offline runs can keep
        # their baseline evidence too. Disabled via config for tests and
        # isolated experiments.
        self._baseline_store = (
            FirstPassBaselineStore(self.config.first_pass_baseline_path)
            if self.config.persist_first_pass_baseline
            else None
        )
        self.generation_model = LLMFactory.create_for_role(self.config.generation_role)
        self.distillation_model = LLMFactory.create_for_role(self.config.distillation_role)
        self.judge_model = LLMFactory.create_for_role(self.config.judge_role)

        # Distillation agents
        self.strategy_extractor = StrategyExtractorAgent(self.distillation_model)
        self.extractor_agent = GuidelineExtractorAgent(self.distillation_model)
        self.principle_promoter = PrinciplePromoterAgent(self.judge_model)
        self.demotion_judger = DemotionJudgerAgent(self.judge_model)
        self.merge_judger = MergeJudgerAgent(self.judge_model)

        # Workflows
        self.generator_workflow = Text2DiagramWorkflow(
            self.generation_model,
            canvas_library=self.config.canvas_library,
        )
        self.refiner_workflow = IterativeRefinerWorkflow()

        # Per-sample iteration loop
        self.refinement_service = RefineLoop(
            config=self.config,
            generator_workflow=self.generator_workflow,
            refiner_workflow=self.refiner_workflow,
            extractor_agent=self.strategy_extractor,
        )

        # Active Knowledge Maintenance (Score → Prune → Merge → Promote → Demote)
        # Reuse the design-memory embedding model for title clustering when
        # available (RISKS.md #19); MergerMixin falls back to Jaccard when
        # offline design-memory mode leaves embedding_function as None.
        embedding_function = getattr(self._memory, "embedding_function", None) if self._memory else None
        self.maintenance = MaintenanceCycle(
            config=self.config,
            principle_promoter=self.principle_promoter,
            demotion_judger=self.demotion_judger,
            merge_judger=self.merge_judger,
            embedding_function=embedding_function,
        )

    def _uses_design_memory(self) -> bool:
        return _normalize_design_memory_mode(getattr(
            self,
            "design_memory_mode",
            DesignMemoryMode.ENABLED,
        )) == DesignMemoryMode.ENABLED

    def _design_memory_mode_label(self) -> str:
        return _normalize_design_memory_mode(getattr(
            self,
            "design_memory_mode",
            DesignMemoryMode.ENABLED,
        )).value

    # ------------------------------------------------------------------ run --

    def run(self, dataset_path: str) -> None:
        """Top-level entry point. Phase 1 → Phase 2 → Phase 3."""
        logger.info("Starting DiagramKnowledgeEvolver Engine with dataset: %s", dataset_path)
        dataset = load_dataset(dataset_path)
        state = _RunState(
            first_pass_baseline=FirstPassBaseline(
                min_samples=self.config.first_pass_baseline_min_samples,
            ),
        )

        self._load_persisted_first_pass_baseline(state)
        self._seed_state_from_db(state)
        self._run_iteration_phase(dataset, state)
        self._raise_if_all_samples_failed(dataset, state)
        self._run_maintenance_phase(state)
        self._persist_results(state)

        logger.info("✅ Knowledge Search Workflow Complete.")

    # ------------------------------------------- first-pass baseline I/O ---

    def _load_persisted_first_pass_baseline(self, state: _RunState) -> None:
        """Seed the run's baseline from the cross-run JSON store.

        Loaded counts merge with this run's observations, so the
        ``min_samples`` gate sees ``loaded + new``: after the system's first
        lifetime window the buckets stay warm across runs and samples stop
        being judged indeterminate at every run head. A missing or corrupt
        file degrades to an empty baseline (warning, never a failed run).
        """
        store = getattr(self, "_baseline_store", None)
        if store is None:
            return
        state.first_pass_baseline = store.load(
            min_samples=self.config.first_pass_baseline_min_samples,
        )

    def _persist_first_pass_baseline(self, state: _RunState) -> None:
        """Write the baseline back immediately after each judged sample.

        Immediate write-back (rather than end-of-run or throttled) was chosen
        because a crashed run must not lose the evidence it already collected,
        and the payload is tiny: one ``{count, sum}`` pair per
        ``diagram_type × content_area`` bucket plus rollups, so even a
        full-file atomic rewrite per sample costs kilobytes. The write is
        best-effort — a disk failure warns but does not invalidate the sample,
        whose own processing succeeded; each save writes the *full* current
        state, so a later successful save heals the gap.
        """
        store = getattr(self, "_baseline_store", None)
        if store is None or not self.config.persist_first_pass_baseline:
            return
        try:
            store.save(state.first_pass_baseline)
        except OSError as exc:
            logger.warning(
                "Could not persist first-pass baseline to %s: %s. The run "
                "continues with the in-memory baseline; the next sample will "
                "retry the write.",
                store.path,
                exc,
            )

    # --------------------------------------------------------- DB seeding ---

    def _seed_state_from_db(self, state: _RunState) -> None:
        """Populate ``state`` with knowledge that already lives in the vector DB.

        Multi-run distillation should accumulate knowledge across invocations.
        Without this, every ``run`` starts from zero and re-derives the same
        guidelines / principles, while the DB silently grows with versioned
        duplicates (see RISKS.md #12 / #13).

        Rows that fail :class:`KnowledgeEntry` validation abort the run. They
        used to be dropped at ``logger.debug`` level, so a schema mismatch
        between the writer and ``KnowledgeEntry`` emptied a whole layer while
        the log still read "Seeded 0 guidelines" as if the collection were
        empty — and the run then re-derived and re-inserted everything.
        """
        if not self._uses_design_memory() or self._memory is None:
            logger.info(
                "Skipping DB seed (design memory mode: %s).",
                self._design_memory_mode_label(),
            )
            return

        layer_to_field = (
            ("strategy", "all_strategies"),
            ("guideline", "current_guidelines"),
            ("principle", "current_principles"),
        )
        for layer, field_name in layer_to_field:
            try:
                raw_items = self._memory.load_all_items(layer)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to seed {layer} knowledge from design memory"
                ) from exc
            entries: List[KnowledgeEntry] = []
            archived_count = 0
            skipped: List[str] = []
            for raw in raw_items:
                if isinstance(raw, dict) and raw.get("active") is False:
                    archived_count += 1
                    continue
                try:
                    entries.append(KnowledgeEntry.model_validate(raw))
                except Exception as exc:
                    raw_id = raw.get("id") if isinstance(raw, dict) else None
                    skipped.append(f"{raw_id!r}: {exc}")

            if skipped:
                logger.warning(
                    "Rejected %d/%d %s items from design memory; the layer "
                    "would seed incomplete. First failures: %s",
                    len(skipped),
                    len(raw_items),
                    layer,
                    "; ".join(skipped[:3]),
                )
                raise RuntimeError(
                    f"{len(skipped)} of {len(raw_items)} {layer} items in design "
                    "memory do not satisfy the KnowledgeEntry schema. Seeding "
                    "would silently drop them and the run would re-derive "
                    "duplicates. Repair or rebuild the collection. Failures: "
                    + "; ".join(skipped)
                )

            if raw_items and not entries and archived_count < len(raw_items):
                raise RuntimeError(
                    f"Seeded 0 {layer} entries from a non-empty collection "
                    f"({len(raw_items)} rows, {archived_count} archived). "
                    "Rebuild the collection before running."
                )

            logger.info(
                "Seeded %d %s entries (%d archived, %d rows total).",
                len(entries),
                layer,
                archived_count,
                len(raw_items),
            )
            state.loaded_ids[layer] = {e.id for e in entries}
            if layer == "strategy":
                positive_entries = [e for e in entries if e.polarity == "positive"]
                state.neutral_strategies.extend(
                    e for e in entries if e.polarity == "neutral"
                )
                state.anti_patterns.extend(
                    e for e in entries if e.polarity == "negative"
                )
                getattr(state, field_name).extend(positive_entries)
            else:
                getattr(state, field_name).extend(entries)
        logger.info(
            "Seeded state from DB: %d strategies, %d guidelines, %d principles.",
            len(state.all_strategies),
            len(state.current_guidelines),
            len(state.current_principles),
        )

    # ------------------------------------------------------------ phase 1 ---

    def _run_iteration_phase(self, dataset, state: _RunState) -> None:
        """For each sample: refine, gate by Δscore, accumulate strategies.

        Guideline distillation is **deferred** to phase boundaries — running it
        on every sample fires several LLM calls per sample and inflates cost to
        O(N · groups) (RISKS.md #16). Set ``config.distillation_every_n_samples`` to a
        positive integer to run mid-phase checkpoints; otherwise distillation
        runs once after the loop.
        """
        every_n = self.config.distillation_every_n_samples
        # Mark everything loaded by _seed_state_from_db as already distilled so
        # DB-loaded strategies aren't fed back into distillation as if they were
        # freshly produced this run. A strategy re-derived this run with changed
        # content gets a new fingerprint and is picked up again.
        state.mark_distilled(state.all_strategies)

        for sample_idx, item in enumerate(dataset):
            logger.info("🚀 Processing Sample [%s]...", item.id)
            self._run_one_sample(item, sample_idx, state)

            # Periodic checkpoint distillation — partial-progress recovery
            # for long runs (RISKS.md #16). Defaults off (every_n == 0).
            if every_n > 0 and (sample_idx + 1) % every_n == 0:
                logger.info(
                    "   >> Checkpoint distillation at sample %d/%d...",
                    sample_idx + 1,
                    len(dataset),
                )
                self._run_distillation(state)

        # End-of-phase distillation — always runs, drains any strategies
        # accumulated since the last checkpoint.
        logger.info("📚 Running end-of-phase distillation over accumulated strategies...")
        self._run_distillation(state)
        logger.info(
            "   >> Phase 1 guideline distillation complete: %d guidelines; "
            "%d principles carried forward for maintenance.",
            len(state.current_guidelines),
            len(state.current_principles),
        )

    def _run_one_sample(self, item, sample_idx: int, state: _RunState) -> None:
        """Run one dataset item, recording failures without aborting the batch."""
        retrieved_items: List[Dict[str, str]] = []
        try:
            retrieved_knowledge, retrieved_items = self._retrieve_and_format_knowledge(
                item.query, diagram_type=item.diagram_type,
            )
            strategies, history = self.refinement_service.run_loop(
                sample_id=item.id,
                sample_info=item,
                retrieved_knowledge=retrieved_knowledge,
            )

            # Quality gate: only positive strategies enter active memory.
            # Neutral and negative outputs are retained as audit artifacts, not
            # retrieval/promotion sources.
            qualified, neutral, anti_patterns = self._filter_strategies(strategies)
            state.all_samples_history.extend(history)
            self._upsert_entries_by_id(state.all_strategies, qualified)
            self._upsert_entries_by_id(state.neutral_strategies, neutral)
            self._upsert_entries_by_id(state.anti_patterns, anti_patterns)
            logger.info(
                "   >> Quality filter: %d/%d positive, %d neutral, %d anti-patterns (τ=%s)",
                len(qualified),
                len(strategies),
                len(neutral),
                len(anti_patterns),
                self.config.delta_score_threshold,
            )

            # Update usage stats for retrieved items. See
            # ``evaluate_knowledge_outcome`` for what the verdict measures and
            # why it is a first-pass score rather than a refiner delta.
            outcome = evaluate_knowledge_outcome(
                history,
                self.config,
                baseline=state.first_pass_baseline,
            )
            self._observe_first_pass_baseline(history, state)
            # Write the updated buckets back immediately so a mid-run crash
            # keeps the evidence collected so far (see method docstring).
            self._persist_first_pass_baseline(state)

            if outcome.is_indeterminate:
                # Not a failure: an unjudgeable sample must not increment
                # usage_count without success_count, which would push the
                # retrieved knowledge towards demotion on no evidence.
                logger.info(
                    "   >> Sample %s not scored (%s): %s",
                    item.id,
                    outcome.criterion.value,
                    outcome.detail,
                )
                state.indeterminate_samples.append({
                    "sample_id": item.id,
                    "criterion": outcome.criterion.value,
                    "detail": outcome.detail,
                    "retrieved_item_ids": [
                        ref.get("id") for ref in retrieved_items
                        if isinstance(ref, dict) and ref.get("id")
                    ],
                })
                return

            logger.info(
                "   >> Sample %s judged %s (%s): %s",
                item.id,
                outcome.verdict,
                outcome.criterion.value,
                outcome.detail,
            )
            all_knowledge = {
                "guideline": state.current_guidelines,
                "principle": state.current_principles,
                "strategy": state.all_strategies,
            }
            self._update_usage_stats(all_knowledge, retrieved_items, outcome.is_success)

            if not outcome.is_success:
                self._record_failed_usage(
                    item,
                    retrieved_items,
                    history,
                    state.failed_usage,
                    issue=f"Sample underperformed its baseline: {outcome.detail}",
                )
        except Exception as exc:  # noqa: BLE001 - batch isolation records and continues
            logger.exception(
                "Sample %r failed during knowledge evolution; continuing with remaining samples.",
                item.id,
            )
            self._record_sample_failure(
                item,
                sample_idx,
                exc,
                state,
                retrieved_items=retrieved_items,
            )
            return

    @staticmethod
    def _observe_first_pass_baseline(
        history: List[IterationRecord],
        state: _RunState,
    ) -> None:
        """Fold this sample's first-pass score into the running baseline.

        Called *after* the sample has been judged so it never contributes to
        the baseline it was measured against. Recorded regardless of the active
        criterion so the statistics stay available for analysis and for a later
        switch of criterion.
        """
        if not history:
            return
        evaluation = history[0].evaluation if isinstance(history[0].evaluation, dict) else {}
        score_before = evaluation.get("score_before")
        if score_before is None:
            return
        state.first_pass_baseline.observe(
            (history[0].tags.diagram_type or [""])[0],
            (history[0].tags.domain or [""])[0],
            float(score_before),
        )

    def _record_sample_failure(
        self,
        item,
        sample_idx: int,
        exc: Exception,
        state: _RunState,
        *,
        retrieved_items: List[Dict[str, str]],
    ) -> None:
        failure = {
            "sample_id": item.id,
            "sample_index": sample_idx,
            "domain": item.content_area,
            "diagram_type": item.diagram_type,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "retrieved_item_ids": [
                ref.get("id") for ref in retrieved_items
                if isinstance(ref, dict) and ref.get("id")
            ],
        }
        state.sample_failures.append(failure)

        if retrieved_items:
            all_knowledge = {
                "guideline": state.current_guidelines,
                "principle": state.current_principles,
                "strategy": state.all_strategies,
            }
            self._update_usage_stats(all_knowledge, retrieved_items, sample_success=False)
            self._record_failed_usage(
                item,
                retrieved_items,
                [],
                state.failed_usage,
                issue=(
                    "Sample execution failed before completion: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

    @staticmethod
    def _merge_list_values(first: List[str], second: List[str]) -> List[str]:
        merged: List[str] = []
        for value in [*(first or []), *(second or [])]:
            if value not in merged:
                merged.append(value)
        return merged

    @classmethod
    def _merge_entry_for_upsert(
        cls,
        existing: KnowledgeEntry,
        incoming: KnowledgeEntry,
    ) -> KnowledgeEntry:
        merged = incoming.model_copy(deep=True)
        merged.usage_count = max(existing.usage_count, incoming.usage_count)
        merged.success_count = max(existing.success_count, incoming.success_count)
        merged.support_count = max(existing.support_count, incoming.support_count)
        merged.validation_success_rate = max(
            existing.validation_success_rate,
            incoming.validation_success_rate,
        )
        merged.validated_domains = cls._merge_list_values(
            existing.validated_domains,
            incoming.validated_domains,
        )
        merged.evidence_ids = cls._merge_list_values(
            existing.evidence_ids,
            incoming.evidence_ids,
        )
        if merged.generalization_status == "local" and existing.generalization_status != "local":
            merged.generalization_status = existing.generalization_status
        return merged

    @classmethod
    def _upsert_entries_by_id(
        cls,
        target: List[KnowledgeEntry],
        entries: List[KnowledgeEntry],
    ) -> None:
        if not entries and len({entry.id for entry in target}) == len(target):
            return

        positions: Dict[str, int] = {}
        deduped: List[KnowledgeEntry] = []
        for entry in target:
            if entry.id in positions:
                index = positions[entry.id]
                deduped[index] = cls._merge_entry_for_upsert(deduped[index], entry)
                continue
            positions[entry.id] = len(deduped)
            deduped.append(entry)

        for entry in entries:
            if entry.id in positions:
                index = positions[entry.id]
                deduped[index] = cls._merge_entry_for_upsert(deduped[index], entry)
                continue
            positions[entry.id] = len(deduped)
            deduped.append(entry)

        target[:] = deduped

    def _raise_if_all_samples_failed(self, dataset, state: _RunState) -> None:
        total_samples = len(dataset)
        if total_samples == 0 or len(state.sample_failures) != total_samples:
            return

        self._persist_results(state)
        raise RuntimeError(
            f"All {total_samples} knowledge evolution samples failed. "
            f"See {os.path.join(self.config.results_dir, 'sample_failures.json')} "
            "and failed_usage.json for diagnostics."
        )

    def _run_distillation(self, state: _RunState) -> None:
        """Distill new strategies into guidelines.

        Operates on the strategies whose current content has not been distilled
        yet (tracked per id by ``state.distilled_strategy_fingerprints``).
        Updates ``state.current_guidelines`` in place and records the distilled
        fingerprints. Principle creation is centralized in the maintenance
        promotion phase so guideline → principle decisions use one evidence gate
        and one agent.
        """
        new_strategies = state.pending_distillation()
        if not new_strategies:
            logger.info("   >> Distillation skipped: no new or changed strategies.")
            return

        logger.info(
            "   >> Distilling %d new/changed strategies (of %d active).",
            len(new_strategies),
            len(state.all_strategies),
        )
        guideline_ops = self._update_guidelines(new_strategies, state.current_guidelines)
        state.current_guidelines = self._apply_memory_operations(
            state.current_guidelines, guideline_ops, "guideline"
        )

        state.mark_distilled(new_strategies)

    # ------------------------------------------------------------ phase 2 ---

    def _run_maintenance_phase(self, state: _RunState) -> None:
        """End-of-phase full Active Knowledge Maintenance cycle.

        Score → Prune → Merge → Promote → Demote across the whole knowledge
        base. Subsumes the legacy retrospective promotion / demotion phases.
        """
        logger.info(
            "🔄 Running maintenance (full) on %d strategies, %d guidelines, %d principles...",
            len(state.all_strategies),
            len(state.current_guidelines),
            len(state.current_principles),
        )
        (
            state.all_strategies,
            state.current_guidelines,
            state.current_principles,
            _stats,
        ) = self.maintenance.run_full(
            state.all_strategies,
            state.current_guidelines,
            state.current_principles,
            state.failed_usage,
        )

    # ------------------------------------------------------------ phase 3 ---

    def _persist_results(self, state: _RunState) -> None:
        """Write JSON snapshots and push into the design-memory vector DB."""
        r = self.config.results_dir
        save_json([h.model_dump() for h in state.all_samples_history], os.path.join(r, "samples.json"))
        save_json(state.sample_failures, os.path.join(r, "sample_failures.json"))
        save_json(
            state.indeterminate_samples,
            os.path.join(r, "indeterminate_samples.json"),
        )
        save_json(dict(state.failed_usage), os.path.join(r, "failed_usage.json"))
        save_json([s.model_dump() for s in state.all_strategies], os.path.join(r, "strategy.json"))
        save_json(
            [s.model_dump() for s in state.neutral_strategies],
            os.path.join(r, "neutral_strategy.json"),
        )
        save_json(
            [s.model_dump() for s in state.anti_patterns],
            os.path.join(r, "anti_pattern.json"),
        )

        logger.info(
            "Phase 1 Complete. %d strategies (%d positive, %d neutral, %d anti-patterns).",
            len(state.all_strategies) + len(state.neutral_strategies) + len(state.anti_patterns),
            len(state.all_strategies),
            len(state.neutral_strategies),
            len(state.anti_patterns),
        )

        logger.info("Saving Final Evolved Knowledge...")
        save_json({"guideline": [g.model_dump() for g in state.current_guidelines]}, os.path.join(r, "guideline.json"))
        save_json({"principles": [p.model_dump() for p in state.current_principles]}, os.path.join(r, "principle.json"))

        logger.info("Saving Knowledge to Vector Database...")
        if not self._uses_design_memory() or self._memory is None:
            logger.info(
                "Skipping vector DB persistence (design memory mode: %s).",
                self._design_memory_mode_label(),
            )
        else:
            self._sync_layer_to_db("strategy", state.all_strategies, state.loaded_ids["strategy"])
            self._sync_layer_to_db("guideline", state.current_guidelines, state.loaded_ids["guideline"])
            self._sync_layer_to_db("principle", state.current_principles, state.loaded_ids["principle"])

    def _sync_layer_to_db(
        self,
        layer: str,
        entries: List[KnowledgeEntry],
        loaded_ids: Set[str],
    ) -> None:
        """Three-way sync between in-memory ``entries`` and the vector DB.

        - Existing IDs (in ``loaded_ids`` and still in ``entries``) → update in place.
        - New IDs (not in ``loaded_ids``) → save_design_memory (versioning eligible).
        - Removed IDs (in ``loaded_ids`` but not in ``entries``) → archive inactive.

        Without the loaded-ID bookkeeping, every run would re-push every entry
        through ``save_design_memory`` and accumulate ``_v2``/``_v3`` duplicates
        for items that did not actually change (RISKS.md #13).
        """
        seen_ids: Set[str] = set()
        duplicate_ids: List[str] = []
        for entry in entries:
            if entry.id in seen_ids and entry.id not in duplicate_ids:
                duplicate_ids.append(entry.id)
            seen_ids.add(entry.id)
        if duplicate_ids:
            raise RuntimeError(
                f"Duplicate {layer} knowledge ids before DB sync: "
                + ", ".join(sorted(duplicate_ids))
            )

        current_ids = {e.id for e in entries}
        existing = [e for e in entries if e.id in loaded_ids]
        new_items = [e for e in entries if e.id not in loaded_ids]
        removed_ids = sorted(loaded_ids - current_ids)

        if existing:
            self._memory.update_design_items(
                [e.model_dump() for e in existing],
                design_layer=layer,
            )
        if new_items:
            self._memory.save_design_memory(
                [e.model_dump() for e in new_items],
                design_layer=layer,
            )
        if removed_ids:
            archive_items = getattr(self._memory, "archive_design_items", None)
            if not callable(archive_items):
                raise RuntimeError(
                    "Design memory does not support archiving removed items"
                )
            archive_items(
                removed_ids,
                design_layer=layer,
                status="retired",
                reason="removed_from_active_sync",
            )

        logger.info(
            "Synced %s: %d updated, %d new, %d removed.",
            layer,
            len(existing),
            len(new_items),
            len(removed_ids),
        )

    # ----------------------------------------------------------- retrieval --

    def _retrieve_and_format_knowledge(
        self,
        user_query: str,
        diagram_type: str = "",
        retrieval_query: str = "",
    ):
        """Prompt-ready design knowledge for one sample, plus its provenance.

        The layer filters, active/positive gating, general-knowledge merge and
        prompt formatting all live on
        :meth:`DiagramDesignRetriever.retrieve_design_expertise` so that the
        inference path and this offline loop cannot drift into showing
        different knowledge to the same generator.
        """
        if not self._uses_design_memory() or self._retriever is None:
            return "", []

        return self._retriever.retrieve_design_expertise(
            user_query,
            diagram_type=diagram_type,
            retrieval_query=retrieval_query,
            top_k=_RETRIEVAL_TOP_K,
            score_threshold=0.0,
        )

    # ----------------------------------------------------- per-sample ops --

    def _filter_strategies(
        self, strategies: List[KnowledgeEntry]
    ) -> Tuple[List[KnowledgeEntry], List[KnowledgeEntry], List[KnowledgeEntry]]:
        """Three-way split of strategies by ``delta_score`` (RISKS.md #17).

        Returns ``(qualified, neutral, anti_patterns)``:
          - qualified:    ``delta_score >=  +threshold`` (polarity=positive)
          - neutral:      ``-threshold < delta_score < +threshold`` (polarity=neutral)
          - anti-patterns: ``delta_score <= -threshold`` (polarity=negative)

        Neutrals and anti-patterns are retained by the caller as audit records,
        but they must not enter active strategy memory, guideline distillation,
        maintenance, or vector DB retrieval.
        """
        threshold = self.config.delta_score_threshold
        qualified: List[KnowledgeEntry] = []
        neutral: List[KnowledgeEntry] = []
        anti_patterns: List[KnowledgeEntry] = []
        for s in strategies:
            if s.delta_score >= threshold:
                s.polarity = "positive"
                qualified.append(s)
            elif s.delta_score <= -threshold:
                s.polarity = "negative"
                anti_patterns.append(s)
            else:
                s.polarity = "neutral"
                neutral.append(s)
        return qualified, neutral, anti_patterns

    def _update_usage_stats(
        self,
        all_knowledge: Dict[str, List[KnowledgeEntry]],
        retrieved_items: List[Dict[str, str]],
        sample_success: bool,
    ) -> None:
        """Update usage_count and success_count for retrieved knowledge items."""
        id_map: Dict[Tuple[str, str], KnowledgeEntry] = {}
        for layer, layer_items in all_knowledge.items():
            for item in layer_items:
                id_map[(layer, item.id)] = item

        seen_refs: Set[Tuple[str, str]] = set()
        for ref in retrieved_items:
            item_id = ref.get("id")
            layer = ref.get("layer")
            if not item_id or not layer:
                continue
            key = (layer, item_id)
            if key in seen_refs:
                continue
            seen_refs.add(key)
            if key in id_map:
                entry = id_map[key]
                entry.usage_count += 1
                if sample_success:
                    entry.success_count += 1

    def _record_failed_usage(
        self,
        item,
        retrieved_items: List[Dict[str, str]],
        history: List[IterationRecord],
        failed_usage: Dict[str, List[Dict]],
        *,
        issue: str = "Sample did not improve after refinement",
    ) -> None:
        """Track which knowledge entries were retrieved for samples that
        didn't improve. Used by ``MaintenanceCycle.check_demotion``.
        """
        worst_delta = min((r.delta_score for r in history), default=0)
        seen_refs: Set[Tuple[str, str]] = set()
        for ref in retrieved_items:
            item_id = ref.get("id")
            layer = ref.get("layer")
            if not item_id or not layer:
                continue
            key = (layer, item_id)
            if key in seen_refs:
                continue
            seen_refs.add(key)
            usage_key = f"{layer}:{item_id}"
            failed_usage[usage_key].append(
                {
                    "id": item_id,
                    "layer": layer,
                    "sample_id": item.id,
                    "domain": item.content_area,
                    "delta_score": worst_delta,
                    "issue": issue,
                }
            )

    @staticmethod
    def _tags_compatible(a: List[str], b) -> bool:
        """Whether two tag lists overlap enough to share a knowledge bucket.

        Replaces exact list equality (RISKS.md #18). Empty on either side acts
        as a wildcard (universal scope), matching anything; otherwise the two
        sets must share at least one element. This lets a guideline tagged
        ``["finance"]`` cluster with strategies tagged ``["finance", "banking"]``
        instead of being mis-classified as a fresh add.
        """
        sa, sb = set(a or []), set(b or [])
        if not sa or not sb:
            return True
        return bool(sa & sb)

    def _update_guidelines(
        self,
        new_strategies: List[KnowledgeEntry],
        existing_guidelines: List[KnowledgeEntry],
    ) -> List[Dict]:
        """Group strategies by tags and extract guideline operations.

        Both ``negative`` and ``neutral`` polarities are skipped — only positive
        signal feeds guideline distillation. Tag-based matching uses set
        intersection rather than full equality (RISKS.md #18).
        """
        grouped = defaultdict(list)
        for entry in new_strategies:
            if entry.polarity in ("negative", "neutral"):
                continue
            domains = tuple(sorted(entry.tags.domain))
            dtypes = tuple(sorted(entry.tags.diagram_type))
            agents = tuple(sorted(entry.tags.agent))
            grouped[(domains, dtypes, agents)].append(entry.model_dump())

        all_operations = []
        for (domains, dtypes, agents), new_items in grouped.items():
            domain_str = domains[0] if domains else "general"
            dtype_str = dtypes[0] if dtypes else "general"
            agent_str = agents[0] if agents else "general"

            relevant_existing = [
                g.model_dump()
                for g in existing_guidelines
                if self._tags_compatible(g.tags.domain, domains)
                and self._tags_compatible(g.tags.diagram_type, dtypes)
                and self._tags_compatible(g.tags.agent, agents)
            ]

            logger.info(
                "Synthesizing updates for [%s - %s - %s]...",
                domain_str,
                dtype_str,
                agent_str,
            )
            output = self.extractor_agent.run(
                domain_str, dtype_str, agent_str, new_items, relevant_existing
            )

            for op in output.get("operations", []):
                if op.get("operation_type") == "add":
                    op["_tags"] = {
                        "domain": list(domains),
                        "diagram_type": list(dtypes),
                        "agent": list(agents),
                    }
                all_operations.append(op)

        return all_operations

    def _apply_memory_operations(
        self,
        existing_items: List[KnowledgeEntry],
        operations: List[Dict],
        item_type: str = "guideline",
    ) -> List[KnowledgeEntry]:
        """Apply ADD and UPDATE operations to a list of KnowledgeEntry items.

        Operations are treated as a strict LLM output contract: malformed
        payloads, unknown operation types, missing required add fields, empty
        update fields, or update targets that do not exist all fail fast
        instead of being silently skipped. Deletion is intentionally not part
        of the LLM contract; removing long-lived knowledge requires an
        explicit maintenance policy rather than one generated operation.

        New items get a deterministic ID derived from ``(title, tags)`` rather
        than a random UUID (RISKS.md #20). This makes runs reproducible and —
        crucially — lets the three-way DB sync recognise re-derived items
        across runs instead of versioning them as new entries.

        If a deterministic ID collides with an existing item already in
        ``existing_items`` (e.g., loaded from the DB at startup), the add op
        degrades gracefully to a no-op — the loaded entry already represents
        this knowledge and its usage stats should be preserved. The comparison
        is made on the *base* ID: an entry stored as ``guideline_h_v2`` by
        ``DiagramDesignMemory._next_version_id`` is the same knowledge as a
        freshly hashed ``guideline_h``, and matching only on the exact string
        made every run add another semantically duplicate copy.
        """
        if not isinstance(operations, list):
            raise RuntimeError(
                f"{item_type} memory operations must be a list; "
                f"got {type(operations).__name__}."
            )

        item_map = {item.id: item for item in existing_items}
        # base id → the actual stored id currently representing it.
        base_id_map: Dict[str, str] = {}
        for item in existing_items:
            base_id_map.setdefault(_base_entry_id(item.id), item.id)

        for index, op in enumerate(operations):
            if not isinstance(op, dict):
                raise _memory_operation_error(
                    item_type,
                    index,
                    f"operation must be an object; got {type(op).__name__}",
                )
            op_type = op.get("operation_type")
            if op_type not in _MEMORY_OPERATION_TYPES:
                raise _memory_operation_error(
                    item_type,
                    index,
                    f"unknown operation_type {op_type!r}; "
                    f"expected one of {', '.join(sorted(_MEMORY_OPERATION_TYPES))}",
                )

            if op_type == "add":
                tags = _require_tags_payload(op, item_type=item_type, index=index)
                fields = {
                    field: _require_op_string(
                        op,
                        field,
                        item_type=item_type,
                        index=index,
                        op_type="add",
                    )
                    for field in _MEMORY_ADD_REQUIRED_FIELDS
                }
                title = fields["title"]
                new_id = f"{item_type}_{_content_hash(title, tags)}"

                existing_id = base_id_map.get(_base_entry_id(new_id))
                if existing_id is not None:
                    # Re-derivation of an existing entry — keep the loaded copy
                    # so usage_count / success_count are preserved. Matching on
                    # the base id also absorbs versioned survivors (``_v2`` …).
                    logger.debug(
                        "   [=] %s %s already present as %s (deterministic ID "
                        "collision), skipping add.",
                        item_type, new_id, existing_id,
                    )
                    continue

                new_entry = KnowledgeEntry(
                    id=new_id,
                    tags=tags,
                    title=title,
                    description=fields["description"],
                    content=fields["content"],
                    when_to_use=fields["when_to_use"],
                    tier=item_type,
                )
                item_map[new_id] = new_entry
                base_id_map[_base_entry_id(new_id)] = new_id
                logger.info("   [+] Added %s: %s", item_type, title)

            elif op_type == "update":
                item_id = _require_op_string(
                    op,
                    "item_id",
                    item_type=item_type,
                    index=index,
                    op_type="update",
                )
                if item_id not in item_map:
                    raise _memory_operation_error(
                        item_type,
                        index,
                        f"update operation targets unknown item_id {item_id!r}",
                    )
                update_fields = {
                    field: _require_op_string(
                        op,
                        field,
                        item_type=item_type,
                        index=index,
                        op_type="update",
                    )
                    for field in _MEMORY_UPDATE_FIELDS
                    if field in op
                }
                if not update_fields:
                    raise _memory_operation_error(
                        item_type,
                        index,
                        "update operation must include at least one mutable field",
                    )
                entry = item_map[item_id]
                for field, value in update_fields.items():
                    setattr(entry, field, value)
                logger.info("   [*] Updated %s: %s", item_type, entry.title)

        return list(item_map.values())
