"""Configuration for the DiagramKnowledgeEvolver evolution pipeline.

All tunable thresholds for the Generate → Reflect → Curate → Maintain cycle live
here as a single dataclass, so the whole pipeline can be re-parametrised by
callers (CLI, tests, sweeps) without touching the algorithms.
"""

from dataclasses import dataclass
import os
from typing import Optional

from evo_diagram.canvas_environment.capabilities import require_knowledge_evolution_capability
from evo_diagram.canvas_runtime import normalize_canvas_library
from evo_diagram.config.settings import AppSettings


# File name of the persisted ``first_pass_vs_history`` baseline statistics.
# Lives inside the design-memory vector DB directory: the baseline is part of
# the knowledge base's evidence, not a per-run artifact, and must survive
# across runs so the cold-start window happens once per system lifetime
# instead of once per run.
FIRST_PASS_BASELINE_FILENAME = "first_pass_baselines.json"


@dataclass
class KnowledgeEvolutionConfig:
    # ── LLM (via models.yaml) ───────────────────────────────────────────────
    generation_role: str = "generator"
    distillation_role: str = "distiller"
    judge_role: str = "distiller"

    # ── Canvas backend ──────────────────────────────────────────────────────
    canvas_library: str = "excalidraw"

    # ── Embedding ───────────────────────────────────────────────────────────
    embedding_model_name: Optional[str] = None

    # ── I/O ─────────────────────────────────────────────────────────────────
    output_dir: str = "output/knowledge_evolution"
    rendered_diagram_fname: str = "rendered_diagram.png"
    manifest_document_fname: str = "diagram_manifest.json"

    # ── Refinement loop ─────────────────────────────────────────────────────
    max_iterations: int = 3

    # ── Quality gate: per-sample Δscore filter ──────────────────────────────
    # Strategies with delta_score above this qualify as positive signal;
    # below the negative threshold they become anti-pattern audit records.
    # Strategies in the inner band ``(-threshold, +threshold)`` are kept as
    # ``polarity="neutral"`` audit records. Only positive strategies enter
    # active memory, retrieval, maintenance, and guideline distillation.
    delta_score_threshold: float = 0.5

    # ── Which signal decides "this sample succeeded with the retrieved knowledge"
    # Drives usage/success bookkeeping, failed_usage records, promotion,
    # demotion and merge decisions. See
    # ``knowledge_evolution.engine.evaluate_knowledge_outcome`` for what each
    # criterion measures.
    #
    # The default judges the *generator's* first-pass score, which is the only
    # stage the retrieved knowledge reaches, against a baseline. The legacy
    # ``refiner_delta`` criterion measured how much the refiner repaired — a
    # stage that never sees the knowledge — and therefore rewarded knowledge
    # that made the first diagram worse. It is kept only for reproducing
    # earlier runs.
    knowledge_success_criterion: str = "first_pass_vs_history"
    # How much the first-pass score must exceed its baseline to count as a
    # success. 0.0 means "at least as good as the baseline"; raise it to demand
    # a real improvement at the cost of labelling more samples as failures.
    first_pass_success_margin: float = 0.0
    # ``first_pass_vs_history`` only: observations required in a bucket before
    # it can serve as a baseline. Samples seen before that are reported as
    # indeterminate and excluded from usage bookkeeping — never counted as
    # failures.
    first_pass_baseline_min_samples: int = 3
    # ``first_pass_vs_history`` only: persist the bucketed baseline statistics
    # across runs. Without this every run restarts the buckets from zero and
    # the first ``first_pass_baseline_min_samples`` samples of each run are
    # indeterminate again. When enabled, the buckets are loaded at run start
    # and written back after every judged sample, so ``min_samples`` counts
    # loaded observations plus this run's, and the cold-start window only
    # occurs once in the system's lifetime. Disable for isolated experiments
    # and tests that must not touch shared state.
    persist_first_pass_baseline: bool = True
    # JSON file holding the persisted baseline. Defaults to
    # ``<design_memory.vector_db_path>/first_pass_baselines.json`` (resolved
    # from AppSettings, i.e. settings.yaml / DESIGN_MEMORY_VECTOR_DB_PATH).
    # Override to point a run at a scratch copy of the baseline.
    first_pass_baseline_path: Optional[str] = None
    # ``first_pass_vs_control``: also generate each sample without any retrieved
    # knowledge and score that manifest, giving a paired causal baseline. Costs
    # one extra generator call per sample (no extra render). Forced on when the
    # control criterion is selected.
    first_pass_control_run: bool = False

    # ── Distillation cadence ────────────────────────────────────────────────
    # ``_update_guidelines`` can make several LLM calls per invocation; running
    # it on every sample inflates cost to O(N · groups) (RISKS.md #16). The
    # default below defers it to the end of phase 1; set to a positive integer
    # to also run after every N samples for partial-progress checkpointing on
    # long runs.
    distillation_every_n_samples: int = 0

    # ── Strategy → Guideline promotion (heuristic, no LLM) ──────────────────
    promote_min_domains: int = 3
    promote_success_rate: float = 0.6
    # Two complementary success criteria. A strategy counts as a
    # "promotion success" if EITHER its source-sample delta_score is strong
    # (creation-time evidence — required because newly-distilled strategies
    # have no retrieval history yet) OR it has been retrieved enough times
    # with a healthy success rate (in-the-wild evidence). Without either gate
    # the success_rate check is vacuous: ``_filter_strategies`` already kept
    # only strategies with ``delta_score >= delta_score_threshold``, so
    # ``delta_score > threshold`` would always be true (RISKS.md #15).
    promote_strong_delta_score: float = 1.0
    promote_min_retrieval_usage: int = 2
    promote_per_strategy_success_rate: float = 0.5

    # ── Guideline → Principle promotion (LLM judge) ─────────────────────────
    principle_min_diagram_types: int = 2
    principle_success_rate: float = 0.6

    # ── Demotion (LLM judge — tier downgrade) ───────────────────────────────
    demote_min_usage: int = 3
    demote_success_rate: float = 0.4

    # ── Prune (strategy deletion only — guidelines/principles are demoted) ──
    prune_min_usage: int = 3
    prune_success_rate: float = 0.2

    # ── Merge clustering ────────────────────────────────────────────────────
    # Cosine threshold for embedding-based title clustering (RISKS.md #19).
    # Used when the engine wires an embedding function into MaintenanceCycle.
    # ``merge_title_similarity`` is the Jaccard fallback used in tests / when
    # retrieval is disabled.
    merge_title_embedding_similarity: float = 0.78
    merge_title_similarity: float = 0.6   # Token-level Jaccard threshold (fallback)
    merge_max_group_size: int = 5         # Items capped per LLM call

    def __post_init__(self):
        self.canvas_library = normalize_canvas_library(self.canvas_library)
        require_knowledge_evolution_capability(canvas_library=self.canvas_library)
        if self.embedding_model_name is None:
            self.embedding_model_name = AppSettings.get_default().design_memory_embedding_model
        valid_criteria = (
            "first_pass_vs_history",
            "first_pass_vs_control",
            "refiner_delta",
        )
        if self.knowledge_success_criterion not in valid_criteria:
            raise ValueError(
                "knowledge_success_criterion must be one of "
                f"{', '.join(valid_criteria)}; got {self.knowledge_success_criterion!r}"
            )
        if self.first_pass_baseline_min_samples < 1:
            raise ValueError(
                "first_pass_baseline_min_samples must be >= 1; got "
                f"{self.first_pass_baseline_min_samples!r}"
            )
        if self.first_pass_baseline_path is None:
            # Beside the vector DB, resolved from settings — never hardcoded.
            self.first_pass_baseline_path = os.path.join(
                AppSettings.get_default().design_memory_vector_db_path,
                FIRST_PASS_BASELINE_FILENAME,
            )
        if self.knowledge_success_criterion == "first_pass_vs_control":
            # The criterion reads a field only the control run produces, so
            # selecting it must not be able to fail halfway through a run.
            self.first_pass_control_run = True

    @property
    def images_dir(self) -> str:
        return os.path.join(self.output_dir, "images")

    @property
    def code_dir(self) -> str:
        return os.path.join(self.output_dir, "code")

    @property
    def results_dir(self) -> str:
        return os.path.join(self.output_dir, "results")
