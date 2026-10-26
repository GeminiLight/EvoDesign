"""Cross-run persistence of the ``first_pass_vs_history`` baseline.

The bucketed baseline used to live only in engine memory, so every run
restarted cold and its first samples were judged indeterminate again. These
tests cover the JSON store (round trip, corrupt-file degradation, atomic
write), the config switch, and continuity across two engine instances —
all with stubbed embeddings, no real ChromaDB required.

Run:  python -m pytest evo_diagram/tests/knowledge_evolution/test_baseline_persistence.py -v
"""

from __future__ import annotations

import json

import pytest

from evo_diagram.knowledge_evolution import engine as engine_module
from evo_diagram.knowledge_evolution.config import (
    FIRST_PASS_BASELINE_FILENAME,
    KnowledgeEvolutionConfig,
)
from evo_diagram.knowledge_evolution.engine import (
    DesignMemoryMode,
    DiagramKnowledgeEvolverEngine,
    FirstPassBaseline,
    FirstPassBaselineStore,
    _RunState,
)
from evo_diagram.knowledge_evolution.schemas import (
    DatasetItem,
    DiagramRef,
    Feedback,
    IterationRecord,
    KnowledgeEntry,
    TagSet,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _iteration_record(*, record_id, score_before, diagram_type="flowchart", content_area="ops"):
    return IterationRecord(
        id=record_id,
        iteration=0,
        tags=TagSet(domain=[content_area], diagram_type=[diagram_type]),
        text_content="T",
        user_query="Q",
        diagram=DiagramRef(representation="m.json", manifest_ref="m.png"),
        evaluation={
            "quality": score_before,
            "score_before": score_before,
            "score_after": score_before,
        },
        feedback=Feedback(LLM_comments=[]),
        delta_score=0.0,
    )


class FakeRefinementService:
    """Returns one first-pass record per sample with a scripted score."""

    def __init__(self, scores):
        self.scores = dict(scores)

    def run_loop(self, *, sample_id, sample_info, retrieved_knowledge):
        return [], [_iteration_record(
            record_id=f"{sample_id}_iter_0",
            score_before=self.scores[sample_id],
            diagram_type=sample_info.diagram_type,
            content_area=sample_info.content_area,
        )]


def _sample(sample_id):
    return DatasetItem(
        id=sample_id,
        content="A",
        content_area="ops",
        diagram_type="flowchart",
        query="q",
    )


def _partial_engine(config, store, *, scores, retrieved=None):
    """Engine built via ``object.__new__`` with only the attributes ``_run_one_sample`` needs."""
    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.config = config
    engine._baseline_store = store
    engine.refinement_service = FakeRefinementService(scores)
    refs = list(retrieved or [])
    engine._retrieve_and_format_knowledge = lambda *_a, **_k: (
        "knowledge" if refs else "",
        refs,
    )
    return engine


def _build_real_engine(monkeypatch, tmp_path, **config_kwargs):
    """Engine through the real ``__init__`` with all heavy collaborators faked."""

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

    class FakeWorkflow:
        def __init__(self, *args, **kwargs):
            pass

    class FakeRefineLoop:
        def __init__(self, **kwargs):
            pass

    class FakeMaintenanceCycle:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        engine_module.LLMFactory,
        "create_for_role",
        classmethod(lambda cls, role: "fake-llm"),
    )
    for name in (
        "StrategyExtractorAgent",
        "GuidelineExtractorAgent",
        "PrinciplePromoterAgent",
        "DemotionJudgerAgent",
        "MergeJudgerAgent",
    ):
        monkeypatch.setattr(engine_module, name, FakeAgent)
    monkeypatch.setattr(engine_module, "Text2DiagramWorkflow", FakeWorkflow)
    monkeypatch.setattr(engine_module, "IterativeRefinerWorkflow", FakeWorkflow)
    monkeypatch.setattr(engine_module, "RefineLoop", FakeRefineLoop)
    monkeypatch.setattr(engine_module, "MaintenanceCycle", FakeMaintenanceCycle)

    config_kwargs.setdefault("output_dir", str(tmp_path / "run"))
    config_kwargs.setdefault(
        "first_pass_baseline_path",
        str(tmp_path / FIRST_PASS_BASELINE_FILENAME),
    )
    config = KnowledgeEvolutionConfig(**config_kwargs)
    return engine_module.DiagramKnowledgeEvolverEngine(
        config, design_memory_mode="offline"
    )


# ── Config wiring ────────────────────────────────────────────────────────


def test_persistence_enabled_by_default_and_path_comes_from_settings(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DESIGN_MEMORY_VECTOR_DB_PATH", str(tmp_path))

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path / "out"))

    assert config.persist_first_pass_baseline is True
    assert config.first_pass_baseline_path == str(
        tmp_path / FIRST_PASS_BASELINE_FILENAME
    )


def test_explicit_baseline_path_override_wins(tmp_path):
    custom = str(tmp_path / "custom_baselines.json")

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path / "out"),
        first_pass_baseline_path=custom,
    )

    assert config.first_pass_baseline_path == custom


def test_engine_init_creates_store_only_when_persistence_enabled(
    tmp_path, monkeypatch
):
    enabled = _build_real_engine(monkeypatch, tmp_path, persist_first_pass_baseline=True)
    assert isinstance(enabled._baseline_store, FirstPassBaselineStore)
    assert enabled._baseline_store.path == str(
        tmp_path / FIRST_PASS_BASELINE_FILENAME
    )

    disabled = _build_real_engine(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        persist_first_pass_baseline=False,
    )
    assert disabled._baseline_store is None


# ── Store: round trip, degradation, atomicity ────────────────────────────


def test_store_round_trip_preserves_every_bucket(tmp_path):
    baseline = FirstPassBaseline(min_samples=2)
    baseline.observe("flowchart", "ops", 5.0)
    baseline.observe("flowchart", "ops", 7.0)
    baseline.observe("sequence", "finance", 6.0)

    store = FirstPassBaselineStore(str(tmp_path / FIRST_PASS_BASELINE_FILENAME))
    store.save(baseline)
    loaded = store.load(min_samples=2)

    assert loaded.pair_stats == baseline.pair_stats
    assert loaded.diagram_type_stats == baseline.diagram_type_stats
    assert loaded.global_stats == baseline.global_stats
    assert loaded.min_samples == 2
    assert loaded.lookup("flowchart", "ops") == baseline.lookup("flowchart", "ops")


def test_saved_payload_is_count_sum_json_without_tmp_leftovers(tmp_path):
    path = tmp_path / FIRST_PASS_BASELINE_FILENAME
    baseline = FirstPassBaseline(min_samples=3)
    baseline.observe("flowchart", "ops", 4.0)

    FirstPassBaselineStore(str(path)).save(baseline)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["pair_stats"] == {"flowchart": {"ops": {"count": 1, "sum": 4.0}}}
    assert data["diagram_type_stats"] == {"flowchart": {"count": 1, "sum": 4.0}}
    assert data["global"] == {"count": 1, "sum": 4.0}
    assert sorted(tmp_path.iterdir()) == [path]  # no .tmp remnants


def test_missing_file_starts_cold_without_failing(tmp_path, caplog):
    store = FirstPassBaselineStore(str(tmp_path / "absent.json"))

    with caplog.at_level("INFO"):
        baseline = store.load(min_samples=3)

    assert baseline.global_stats == (0, 0.0)
    assert baseline.min_samples == 3
    assert "No persisted first-pass baseline" in caplog.text


def test_corrupt_file_degrades_to_empty_baseline_with_warning(tmp_path, caplog):
    path = tmp_path / FIRST_PASS_BASELINE_FILENAME
    path.write_text("{not json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        baseline = FirstPassBaselineStore(str(path)).load(min_samples=3)

    assert baseline.global_stats == (0, 0.0)
    assert "Could not load persisted first-pass baseline" in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        [],                                        # not an object
        {"version": 999},                          # unknown version
        {"version": 1, "global": {"count": "x", "sum": 0}},   # bad count type
        {"version": 1, "global": {"count": -1, "sum": 0}},    # negative count
        {"version": 1, "global": {"count": 1}},               # missing sum
        {"version": 1, "pair_stats": {"flowchart": "nope"}},  # bad nesting
        {"version": 1, "diagram_type_stats": {"flowchart": {"count": 1, "sum": "s"}}},
    ],
)
def test_malformed_payloads_degrade_with_warning(tmp_path, caplog, payload):
    path = tmp_path / FIRST_PASS_BASELINE_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")

    with caplog.at_level("WARNING"):
        baseline = FirstPassBaselineStore(str(path)).load(min_samples=3)

    assert baseline.global_stats == (0, 0.0)
    assert baseline.pair_stats == {}
    assert baseline.diagram_type_stats == {}
    assert "Could not load persisted first-pass baseline" in caplog.text


def test_load_uses_current_min_samples_not_a_persisted_one(tmp_path):
    """The threshold is a config decision of the run; only evidence persists."""
    store = FirstPassBaselineStore(str(tmp_path / FIRST_PASS_BASELINE_FILENAME))
    baseline = FirstPassBaseline(min_samples=5)
    for _ in range(3):
        baseline.observe("flowchart", "ops", 6.0)
    store.save(baseline)

    loaded = store.load(min_samples=2)

    assert loaded.min_samples == 2
    resolved = loaded.lookup("flowchart", "ops")
    assert resolved is not None
    assert resolved[0] == pytest.approx(6.0)


# ── Engine wiring: immediate write-back, run seeding, switch off ─────────


def test_run_one_sample_writes_baseline_back_immediately(tmp_path):
    path = tmp_path / FIRST_PASS_BASELINE_FILENAME
    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path / "out"),
        first_pass_baseline_path=str(path),
        first_pass_baseline_min_samples=2,
    )
    engine = _partial_engine(config, FirstPassBaselineStore(str(path)), scores={"s1": 6.0})
    state = _RunState(
        first_pass_baseline=FirstPassBaseline(min_samples=2),
    )

    engine._run_one_sample(_sample("s1"), 0, state)

    # The very first sample is indeterminate, but its observation is already
    # on disk — a crash right after this sample loses nothing.
    assert [entry["sample_id"] for entry in state.indeterminate_samples] == ["s1"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["global"] == {"count": 1, "sum": 6.0}


def test_baseline_continues_across_two_engine_instances(tmp_path):
    """Cold start happens once per system lifetime, not once per run."""
    path = tmp_path / FIRST_PASS_BASELINE_FILENAME
    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path / "out"),
        first_pass_baseline_path=str(path),
        first_pass_baseline_min_samples=2,
    )
    guideline = KnowledgeEntry(
        id="g1",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Existing guideline",
        description="D",
        content="C",
        when_to_use="W",
        tier="guideline",
    )
    refs = [{"id": "g1", "layer": "guideline"}]

    # Run 1: two samples warm the global bucket; both are indeterminate.
    engine_1 = _partial_engine(
        config,
        FirstPassBaselineStore(str(path)),
        scores={"s1": 6.0, "s2": 7.0},
        retrieved=refs,
    )
    state_1 = _RunState(
        first_pass_baseline=FirstPassBaseline(min_samples=2),
        current_guidelines=[guideline],
    )
    engine_1._run_one_sample(_sample("s1"), 0, state_1)
    engine_1._run_one_sample(_sample("s2"), 1, state_1)
    assert [e["sample_id"] for e in state_1.indeterminate_samples] == ["s1", "s2"]
    assert guideline.usage_count == 0  # indeterminate never touches usage stats

    # Run 2: a fresh engine seeds from the persisted file and judges at once.
    engine_2 = _partial_engine(
        config,
        FirstPassBaselineStore(str(path)),
        scores={"s3": 9.0},
        retrieved=refs,
    )
    state_2 = _RunState(current_guidelines=[guideline])
    engine_2._load_persisted_first_pass_baseline(state_2)

    assert state_2.first_pass_baseline.global_stats == (2, 13.0)
    assert state_2.first_pass_baseline.min_samples == 2

    engine_2._run_one_sample(_sample("s3"), 0, state_2)

    assert state_2.indeterminate_samples == []
    # 9.0 >= mean(6.0, 7.0) + 0.0 → success bookkeeping ran.
    assert guideline.usage_count == 1
    assert guideline.success_count == 1
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["global"] == {"count": 3, "sum": 22.0}


def test_run_seeds_state_from_persisted_baseline(tmp_path, monkeypatch):
    path = tmp_path / FIRST_PASS_BASELINE_FILENAME
    seeded = FirstPassBaseline(min_samples=2)
    seeded.observe("flowchart", "ops", 5.0)
    seeded.observe("flowchart", "ops", 7.0)
    FirstPassBaselineStore(str(path)).save(seeded)

    engine = _build_real_engine(
        monkeypatch,
        tmp_path,
        first_pass_baseline_min_samples=2,
    )
    monkeypatch.setattr(engine_module, "load_dataset", lambda _path: [])
    captured = {}

    def fake_iteration_phase(_dataset, state):
        captured["baseline"] = state.first_pass_baseline

    engine._run_iteration_phase = fake_iteration_phase
    engine._run_maintenance_phase = lambda state: None
    engine._persist_results = lambda state: None

    engine.run("dataset.json")

    assert captured["baseline"].global_stats == (2, 12.0)
    assert captured["baseline"].min_samples == 2


def test_disabled_persistence_keeps_everything_in_memory(tmp_path, monkeypatch):
    engine = _build_real_engine(
        monkeypatch,
        tmp_path,
        persist_first_pass_baseline=False,
        first_pass_baseline_min_samples=1,
    )
    path = tmp_path / FIRST_PASS_BASELINE_FILENAME
    assert not path.exists()

    engine.refinement_service = FakeRefinementService({"s1": 6.0, "s2": 7.0})
    engine._retrieve_and_format_knowledge = lambda *_a, **_k: ("", [])
    state = _RunState(
        first_pass_baseline=FirstPassBaseline(
            min_samples=engine.config.first_pass_baseline_min_samples,
        ),
    )
    engine._load_persisted_first_pass_baseline(state)  # no store → untouched
    engine._run_one_sample(_sample("s1"), 0, state)
    engine._run_one_sample(_sample("s2"), 1, state)

    # In-memory behaviour is unchanged: s1 is indeterminate (nothing observed
    # yet), s2 is judged against s1's score (min_samples=1).
    assert state.first_pass_baseline.global_stats == (2, 13.0)
    assert [e["sample_id"] for e in state.indeterminate_samples] == ["s1"]
    # …and nothing ever hit the disk.
    assert not path.exists()


def test_persist_failure_warns_and_continues(tmp_path, caplog):
    """A stats-cache write error must not invalidate a successful sample."""
    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path / "out"),
        first_pass_baseline_path=str(tmp_path / FIRST_PASS_BASELINE_FILENAME),
    )

    class FailingStore:
        path = str(tmp_path / FIRST_PASS_BASELINE_FILENAME)

        def save(self, baseline):
            raise OSError("disk full")

    engine = _partial_engine(config, FailingStore(), scores={"s1": 6.0})
    state = _RunState()

    with caplog.at_level("WARNING"):
        engine._run_one_sample(_sample("s1"), 0, state)

    assert "Could not persist first-pass baseline" in caplog.text
    assert state.sample_failures == []
    assert state.first_pass_baseline.global_stats == (1, 6.0)
