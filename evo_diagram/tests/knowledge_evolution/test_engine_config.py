"""Knowledge evolution engine configuration wiring tests."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest


def test_engine_passes_embedding_model_name_to_design_memory(tmp_path, monkeypatch):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution import engine as engine_module

    captured = {}

    class FakeDesignMemory:
        embedding_function = "fake-embedding-function"

        def __init__(self, **kwargs):
            captured["memory_kwargs"] = kwargs

    class FakeRetriever:
        def __init__(self, *, design_memory):
            captured["retriever_memory"] = design_memory

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

    class FakeWorkflow:
        def __init__(self, *args, **kwargs):
            pass

    class FakeRefineLoop:
        def __init__(self, **kwargs):
            captured["refine_loop_kwargs"] = kwargs

    class FakeMaintenanceCycle:
        def __init__(self, **kwargs):
            captured["maintenance_kwargs"] = kwargs

    monkeypatch.setattr(engine_module, "DiagramDesignMemory", FakeDesignMemory)
    monkeypatch.setattr(engine_module, "DiagramDesignRetriever", FakeRetriever)
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

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        embedding_model_name="custom-embedding-model",
    )

    engine_module.DiagramKnowledgeEvolverEngine(
        config=config,
        design_memory_mode=engine_module.DesignMemoryMode.ENABLED,
    )

    assert captured["memory_kwargs"] == {
        "embedding_model_name": "custom-embedding-model",
    }
    assert captured["maintenance_kwargs"]["embedding_function"] == "fake-embedding-function"


def test_engine_offline_design_memory_mode_skips_vector_services(tmp_path, monkeypatch):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution import engine as engine_module

    captured = {}

    def fail_if_design_memory_loads():
        raise AssertionError("offline design memory mode must not load vector services")

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
            captured["maintenance_kwargs"] = kwargs

    monkeypatch.setattr(engine_module, "_resolve_design_memory_classes", fail_if_design_memory_loads)
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

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))

    engine = engine_module.DiagramKnowledgeEvolverEngine(
        config=config,
        design_memory_mode=engine_module.DesignMemoryMode.OFFLINE,
    )

    assert engine.design_memory_mode == engine_module.DesignMemoryMode.OFFLINE
    assert engine._memory is None
    assert engine._retriever is None
    assert captured["maintenance_kwargs"]["embedding_function"] is None


def test_engine_wires_stage_specific_model_roles(tmp_path, monkeypatch):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution import engine as engine_module

    captured = {
        "roles": [],
        "agents": {},
    }

    def fake_create_for_role(cls, role):
        captured["roles"].append(role)
        return f"{role}-model"

    def fake_agent_class(agent_name):
        class FakeAgent:
            def __init__(self, model, *args, **kwargs):
                captured["agents"][agent_name] = model

        return FakeAgent

    class FakeGeneratorWorkflow:
        def __init__(self, model, **kwargs):
            captured["generator_model"] = model
            captured["generator_kwargs"] = kwargs

    class FakeWorkflow:
        def __init__(self, *args, **kwargs):
            pass

    class FakeRefineLoop:
        def __init__(self, **kwargs):
            captured["refine_loop_kwargs"] = kwargs

    class FakeMaintenanceCycle:
        def __init__(self, **kwargs):
            captured["maintenance_kwargs"] = kwargs

    monkeypatch.setattr(
        engine_module.LLMFactory,
        "create_for_role",
        classmethod(fake_create_for_role),
    )
    monkeypatch.setattr(
        engine_module,
        "StrategyExtractorAgent",
        fake_agent_class("strategy_extractor"),
    )
    monkeypatch.setattr(
        engine_module,
        "GuidelineExtractorAgent",
        fake_agent_class("guideline_extractor"),
    )
    monkeypatch.setattr(
        engine_module,
        "PrinciplePromoterAgent",
        fake_agent_class("principle_promoter"),
    )
    monkeypatch.setattr(
        engine_module,
        "DemotionJudgerAgent",
        fake_agent_class("demotion_judger"),
    )
    monkeypatch.setattr(
        engine_module,
        "MergeJudgerAgent",
        fake_agent_class("merge_judger"),
    )
    monkeypatch.setattr(engine_module, "Text2DiagramWorkflow", FakeGeneratorWorkflow)
    monkeypatch.setattr(engine_module, "IterativeRefinerWorkflow", FakeWorkflow)
    monkeypatch.setattr(engine_module, "RefineLoop", FakeRefineLoop)
    monkeypatch.setattr(engine_module, "MaintenanceCycle", FakeMaintenanceCycle)

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        generation_role="generator-main",
        distillation_role="distiller-fast",
        judge_role="judge-accurate",
    )

    engine = engine_module.DiagramKnowledgeEvolverEngine(
        config=config,
        design_memory_mode=engine_module.DesignMemoryMode.OFFLINE,
    )

    assert captured["roles"] == [
        "generator-main",
        "distiller-fast",
        "judge-accurate",
    ]
    assert engine.generation_model == "generator-main-model"
    assert engine.distillation_model == "distiller-fast-model"
    assert engine.judge_model == "judge-accurate-model"
    assert captured["generator_model"] == "generator-main-model"
    assert captured["agents"] == {
        "strategy_extractor": "distiller-fast-model",
        "guideline_extractor": "distiller-fast-model",
        "principle_promoter": "judge-accurate-model",
        "demotion_judger": "judge-accurate-model",
        "merge_judger": "judge-accurate-model",
    }
    assert captured["refine_loop_kwargs"]["generator_workflow"] is engine.generator_workflow
    assert captured["refine_loop_kwargs"]["extractor_agent"] is engine.strategy_extractor
    assert captured["maintenance_kwargs"]["principle_promoter"] is engine.principle_promoter


def test_cli_passes_stage_roles_and_design_memory_mode(tmp_path, monkeypatch):
    from evo_diagram.knowledge_evolution import __main__ as cli

    captured = {}

    class FakeConfig:
        def __init__(self, **kwargs):
            captured["config_kwargs"] = kwargs
            self.__dict__.update(kwargs)

    class FakeEngine:
        def __init__(self, config, *, design_memory_mode):
            captured["config"] = config
            captured["design_memory_mode"] = design_memory_mode

        def run(self, dataset):
            captured["dataset"] = dataset

    monkeypatch.setattr(cli, "KnowledgeEvolutionConfig", FakeConfig)
    monkeypatch.setattr(cli, "DiagramKnowledgeEvolverEngine", FakeEngine)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "knowledge-evolution",
            "--dataset",
            "dataset.json",
            "--output-dir",
            str(tmp_path),
            "--generation-role",
            "generator-main",
            "--distillation-role",
            "distiller-fast",
            "--judge-role",
            "judge-accurate",
            "--design-memory-mode",
            "offline",
        ],
    )

    cli.main()

    assert captured["config_kwargs"] == {
        "generation_role": "generator-main",
        "distillation_role": "distiller-fast",
        "judge_role": "judge-accurate",
        "output_dir": str(tmp_path),
        "max_iterations": 3,
    }
    assert captured["design_memory_mode"] == cli.DesignMemoryMode.OFFLINE.value
    assert captured["dataset"] == "dataset.json"


def test_engine_rejects_unknown_design_memory_mode(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))

    with pytest.raises(ValueError, match="design_memory_mode must be one of"):
        DiagramKnowledgeEvolverEngine(
            config=config,
            design_memory_mode="retrieval-only",
        )


def test_iteration_run_dir_is_sample_and_iteration_scoped(tmp_path):
    from evo_diagram.knowledge_evolution.iteration.loop import _iteration_run_dir

    first = _iteration_run_dir(str(tmp_path), "sample-1", 0)
    second = _iteration_run_dir(str(tmp_path), "sample-1", 1)
    other = _iteration_run_dir(str(tmp_path), "other_sample", 0)

    assert first == tmp_path / "runs" / "sample-1" / "iter_0"
    assert second == tmp_path / "runs" / "sample-1" / "iter_1"
    assert other == tmp_path / "runs" / "other_sample" / "iter_0"
    assert len({first, second, other}) == 3


def test_iteration_run_dir_rejects_unsafe_sample_ids(tmp_path):
    from evo_diagram.knowledge_evolution.iteration.loop import _iteration_run_dir

    for sample_id in ("sample/1", "other:sample", " sample", "sample "):
        with pytest.raises(ValueError, match="dataset sample id"):
            _iteration_run_dir(str(tmp_path), sample_id, 0)


def test_engine_seed_from_db_fails_fast_on_design_memory_read_errors():
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
        _RunState,
    )

    class FailingMemory:
        def load_all_items(self, layer):
            raise RuntimeError(f"{layer} DB unavailable")

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.design_memory_mode = DesignMemoryMode.ENABLED
    engine._memory = FailingMemory()

    with pytest.raises(RuntimeError, match="Failed to seed strategy knowledge"):
        engine._seed_state_from_db(_RunState())


def test_engine_seed_from_db_keeps_only_positive_strategies_active():
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
        _RunState,
    )
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    def entry(entry_id: str, polarity: str) -> dict:
        return KnowledgeEntry(
            id=entry_id,
            tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
            title=f"Strategy {entry_id}",
            description="D",
            content="C",
            when_to_use="W",
            polarity=polarity,
        ).model_dump()

    class FakeMemory:
        def load_all_items(self, layer):
            if layer == "strategy":
                return [
                    entry("positive", "positive"),
                    entry("neutral", "neutral"),
                    entry("negative", "negative"),
                ]
            return []

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.design_memory_mode = DesignMemoryMode.ENABLED
    engine._memory = FakeMemory()

    state = _RunState()
    engine._seed_state_from_db(state)

    assert [item.id for item in state.all_strategies] == ["positive"]
    assert [item.id for item in state.neutral_strategies] == ["neutral"]
    assert [item.id for item in state.anti_patterns] == ["negative"]
    assert state.loaded_ids["strategy"] == {"positive", "neutral", "negative"}


def test_engine_seed_from_db_fails_fast_on_invalid_stored_entry(caplog):
    """A schema mismatch must abort the run, not silently empty a layer.

    Skipping malformed rows at debug level made the log read "Seeded 0
    guidelines" as if the collection were empty, and the run then re-derived
    and re-inserted everything it had failed to load.
    """
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
        _RunState,
    )
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    valid = KnowledgeEntry(
        id="valid",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Valid strategy",
        description="D",
        content="C",
        when_to_use="W",
    ).model_dump()
    invalid = {
        **valid,
        "id": "invalid",
        "polarity": "False",
    }

    class FakeMemory:
        def load_all_items(self, layer):
            if layer == "strategy":
                return [valid, invalid]
            return []

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.design_memory_mode = DesignMemoryMode.ENABLED
    engine._memory = FakeMemory()

    state = _RunState()
    with caplog.at_level("WARNING"):
        with pytest.raises(RuntimeError, match="do not satisfy the KnowledgeEntry schema"):
            engine._seed_state_from_db(state)

    assert "Rejected 1/2 strategy items" in caplog.text


def test_engine_seed_from_db_ignores_archived_rows():
    """Archived tombstones are expected to seed nothing and must not fail."""
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
        _RunState,
    )
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    active = KnowledgeEntry(
        id="valid",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Valid strategy",
        description="D",
        content="C",
        when_to_use="W",
    ).model_dump()
    archived = {**active, "id": "retired", "active": False}

    class FakeMemory:
        def load_all_items(self, layer):
            if layer == "strategy":
                return [active, archived]
            return []

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.design_memory_mode = DesignMemoryMode.ENABLED
    engine._memory = FakeMemory()

    state = _RunState()
    engine._seed_state_from_db(state)

    assert [item.id for item in state.all_strategies] == ["valid"]
    assert state.loaded_ids["strategy"] == {"valid"}


def test_knowledge_entry_accepts_archived_tombstone_fields():
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    entry = KnowledgeEntry(
        id="g1",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Archived guideline",
        description="D",
        content="C",
        when_to_use="W",
        tier="guideline",
        active=False,
        generalization_status="retired",
        archive_reason="removed_from_active_sync",
        archived_at="2026-06-14T00:00:00+00:00",
    )

    assert entry.active is False
    assert entry.generalization_status == "retired"
    assert entry.archive_reason == "removed_from_active_sync"
    assert entry.archived_at == "2026-06-14T00:00:00+00:00"


def test_engine_db_sync_archives_loaded_strategy_ids_removed_by_maintenance():
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    calls = {}

    class FakeMemory:
        def update_design_items(self, items, *, design_layer):
            calls["updated"] = (design_layer, items)

        def save_design_memory(self, items, *, design_layer):
            calls["saved"] = (design_layer, items)

        def delete_design_items(self, item_ids, *, design_layer):
            raise AssertionError("removed active knowledge must be archived, not deleted")

        def archive_design_items(self, item_ids, *, design_layer, status, reason):
            calls["archived"] = (design_layer, item_ids, status, reason)

    def entry(entry_id: str) -> KnowledgeEntry:
        return KnowledgeEntry(
            id=entry_id,
            tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
            title=f"Strategy {entry_id}",
            description="D",
            content="C",
            when_to_use="W",
        )

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine._memory = FakeMemory()

    engine._sync_layer_to_db(
        "strategy",
        entries=[entry("kept"), entry("new")],
        loaded_ids={"kept", "retired"},
    )

    assert calls["updated"][0] == "strategy"
    assert [item["id"] for item in calls["updated"][1]] == ["kept"]
    assert calls["saved"][0] == "strategy"
    assert [item["id"] for item in calls["saved"][1]] == ["new"]
    assert calls["archived"] == (
        "strategy",
        ["retired"],
        "retired",
        "removed_from_active_sync",
    )


def test_engine_db_sync_rejects_duplicate_entry_ids_before_update():
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    class FakeMemory:
        def update_design_items(self, items, *, design_layer):
            raise AssertionError("duplicate ids must fail before DB writes")

        def save_design_memory(self, items, *, design_layer):
            raise AssertionError("duplicate ids must fail before DB writes")

        def delete_design_items(self, item_ids, *, design_layer):
            raise AssertionError("duplicate ids must fail before DB writes")

        def archive_design_items(self, item_ids, *, design_layer, status, reason):
            raise AssertionError("duplicate ids must fail before DB writes")

    def entry(entry_id: str) -> KnowledgeEntry:
        return KnowledgeEntry(
            id=entry_id,
            tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
            title=f"Strategy {entry_id}",
            description="D",
            content="C",
            when_to_use="W",
        )

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine._memory = FakeMemory()

    with pytest.raises(RuntimeError, match="Duplicate strategy knowledge ids"):
        engine._sync_layer_to_db(
            "strategy",
            entries=[entry("dup"), entry("dup")],
            loaded_ids={"dup"},
        )


def test_usage_stats_dedupes_retrieved_item_ids_per_sample():
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    entry = KnowledgeEntry(
        id="g1",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Existing guideline",
        description="D",
        content="C",
        when_to_use="W",
        tier="guideline",
    )
    engine = object.__new__(DiagramKnowledgeEvolverEngine)

    engine._update_usage_stats(
        {"guideline": [entry]},
        [{"id": "g1", "layer": "guideline"}, {"id": "g1", "layer": "guideline"}],
        sample_success=True,
    )

    assert entry.usage_count == 1
    assert entry.success_count == 1


def test_usage_stats_are_layer_aware_for_shared_ids():
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    guideline = KnowledgeEntry(
        id="shared",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Existing guideline",
        description="D",
        content="C",
        when_to_use="W",
        tier="guideline",
    )
    strategy = KnowledgeEntry(
        id="shared",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Existing strategy",
        description="D",
        content="C",
        when_to_use="W",
        tier="strategy",
    )
    engine = object.__new__(DiagramKnowledgeEvolverEngine)

    engine._update_usage_stats(
        {"guideline": [guideline], "strategy": [strategy]},
        [{"id": "shared", "layer": "guideline"}],
        sample_success=True,
    )

    assert guideline.usage_count == 1
    assert guideline.success_count == 1
    assert strategy.usage_count == 0
    assert strategy.success_count == 0


def test_phase_one_distillation_updates_guidelines_only():
    from evo_diagram.knowledge_evolution.engine import (
        DiagramKnowledgeEvolverEngine,
        _RunState,
    )
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    engine = object.__new__(DiagramKnowledgeEvolverEngine)

    strategy = KnowledgeEntry(
        id="s1",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Keep lanes stable",
        description="D",
        content="C",
        when_to_use="W",
        delta_score=1.0,
    )
    existing_principle = KnowledgeEntry(
        id="p1",
        tags=TagSet(domain=["universal"], diagram_type=["universal"], agent=["layout"]),
        title="Existing principle",
        description="D",
        content="C",
        when_to_use="W",
        tier="principle",
    )

    def fake_guideline_ops(new_strategies, existing_guidelines):
        assert [entry.id for entry in new_strategies] == ["s1"]
        assert existing_guidelines == []
        return [
            {
                "operation_type": "add",
                "title": "Lane stability",
                "description": "D",
                "content": "C",
                "when_to_use": "W",
                "_tags": {
                    "domain": ["ops"],
                    "diagram_type": ["flowchart"],
                    "agent": ["layout"],
                },
            }
        ]

    engine._update_guidelines = fake_guideline_ops
    state = _RunState(
        all_strategies=[strategy],
        current_principles=[existing_principle],
    )

    engine._run_distillation(state)

    assert [entry.title for entry in state.current_guidelines] == ["Lane stability"]
    assert state.current_principles == [existing_principle]
    assert set(state.distilled_strategy_fingerprints) == {"s1"}
    # Nothing changed, so a second pass is a no-op.
    assert state.pending_distillation() == []


def test_iteration_phase_records_sample_failure_and_continues(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
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

    # Pinned to the legacy criterion: this test is about batch isolation, not
    # about how a sample is scored.
    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        knowledge_success_criterion="refiner_delta",
    )
    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.config = config
    engine.design_memory_mode = DesignMemoryMode.OFFLINE
    engine._memory = None

    retrieved_refs = [{"id": "g1", "layer": "guideline"}]

    def fake_retrieve(*_args, **_kwargs):
        return "retrieved knowledge", list(retrieved_refs)

    class FakeRefinementService:
        def __init__(self):
            self.sample_ids = []

        def run_loop(self, *, sample_id, sample_info, retrieved_knowledge):
            self.sample_ids.append(sample_id)
            assert retrieved_knowledge == "retrieved knowledge"
            if sample_id == "bad":
                raise RuntimeError("render failed")
            strategy = KnowledgeEntry(
                id="s_good",
                tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
                title="Keep lanes aligned",
                description="D",
                content="C",
                when_to_use="W",
                delta_score=0.8,
            )
            history = [
                IterationRecord(
                    id="good_iter_0",
                    iteration=0,
                    tags=TagSet(),
                    text_content=sample_info.content,
                    user_query=sample_info.query,
                    diagram=DiagramRef(representation="manifest.json", manifest_ref="image.png"),
                    evaluation={},
                    feedback=Feedback(LLM_comments=[]),
                    delta_score=0.8,
                )
            ]
            return [strategy], history

    distillation_calls = []

    def fake_distillation(state):
        distillation_calls.append(len(state.all_strategies))

    engine._retrieve_and_format_knowledge = fake_retrieve
    engine.refinement_service = FakeRefinementService()
    engine._run_distillation = fake_distillation

    state = _RunState(
        current_guidelines=[
            KnowledgeEntry(
                id="g1",
                tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
                title="Existing guideline",
                description="D",
                content="C",
                when_to_use="W",
                tier="guideline",
            )
        ]
    )
    dataset = [
        DatasetItem(id="bad", content="A", content_area="ops", diagram_type="flowchart", query="q"),
        DatasetItem(id="good", content="B", content_area="ops", diagram_type="flowchart", query="q"),
    ]

    engine._run_iteration_phase(dataset, state)

    assert engine.refinement_service.sample_ids == ["bad", "good"]
    assert distillation_calls == [1]
    assert [failure["sample_id"] for failure in state.sample_failures] == ["bad"]
    assert state.sample_failures[0]["error_type"] == "RuntimeError"
    assert state.sample_failures[0]["retrieved_item_ids"] == ["g1"]
    assert [entry.id for entry in state.all_strategies] == ["s_good"]
    assert len(state.all_samples_history) == 1
    assert state.current_guidelines[0].usage_count == 2
    assert state.current_guidelines[0].success_count == 1
    assert "Sample execution failed" in state.failed_usage["guideline:g1"][0]["issue"]

    engine._persist_results(state)
    failures_path = tmp_path / "results" / "sample_failures.json"
    failures = json.loads(failures_path.read_text(encoding="utf-8"))
    assert failures[0]["sample_id"] == "bad"
    failed_usage_path = tmp_path / "results" / "failed_usage.json"
    failed_usage = json.loads(failed_usage_path.read_text(encoding="utf-8"))
    assert failed_usage["guideline:g1"][0]["sample_id"] == "bad"
    assert "Sample execution failed" in failed_usage["guideline:g1"][0]["issue"]


def test_engine_run_fails_before_maintenance_when_all_samples_fail(tmp_path, monkeypatch):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution import engine as engine_module
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
    )
    from evo_diagram.knowledge_evolution.schemas import DatasetItem

    dataset = [
        DatasetItem(
            id="bad_1",
            content="A",
            content_area="ops",
            diagram_type="flowchart",
            query="q",
        ),
        DatasetItem(
            id="bad_2",
            content="B",
            content_area="ops",
            diagram_type="flowchart",
            query="q",
        ),
    ]

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))
    engine.design_memory_mode = DesignMemoryMode.OFFLINE
    engine._memory = None
    monkeypatch.setattr(engine_module, "load_dataset", lambda _path: dataset)

    def fake_iteration_phase(_dataset, state):
        for index, item in enumerate(_dataset):
            state.sample_failures.append(
                {
                    "sample_id": item.id,
                    "sample_index": index,
                    "domain": item.content_area,
                    "diagram_type": item.diagram_type,
                    "error_type": "RuntimeError",
                    "error": "render failed",
                    "retrieved_item_ids": [],
                }
            )

    def fail_if_maintenance_runs(_state):
        raise AssertionError("maintenance must not run when every sample failed")

    engine._run_iteration_phase = fake_iteration_phase
    engine._run_maintenance_phase = fail_if_maintenance_runs

    with pytest.raises(RuntimeError, match="All 2 knowledge evolution samples failed"):
        engine.run("dataset.json")

    failures_path = tmp_path / "results" / "sample_failures.json"
    failures = json.loads(failures_path.read_text(encoding="utf-8"))
    assert [failure["sample_id"] for failure in failures] == ["bad_1", "bad_2"]
    assert (tmp_path / "results" / "failed_usage.json").exists()


def test_legacy_refiner_delta_criterion_uses_configured_delta_threshold(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import (
        DiagramKnowledgeEvolverEngine,
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

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        delta_score_threshold=0.5,
        knowledge_success_criterion="refiner_delta",
    )
    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.config = config

    def fake_retrieve(*_args, **_kwargs):
        return "retrieved knowledge", [{"id": "g1", "layer": "guideline"}]

    class FakeRefinementService:
        def run_loop(self, *, sample_id, sample_info, retrieved_knowledge):
            strategy = KnowledgeEntry(
                id="s_noise",
                tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
                title="Tiny positive delta",
                description="D",
                content="C",
                when_to_use="W",
                delta_score=0.01,
            )
            history = [
                IterationRecord(
                    id=f"{sample_id}_iter_0",
                    iteration=0,
                    tags=TagSet(),
                    text_content=sample_info.content,
                    user_query=sample_info.query,
                    diagram=DiagramRef(representation="manifest.json", manifest_ref="image.png"),
                    evaluation={},
                    feedback=Feedback(LLM_comments=[]),
                    delta_score=0.01,
                )
            ]
            return [strategy], history

    engine._retrieve_and_format_knowledge = fake_retrieve
    engine.refinement_service = FakeRefinementService()

    state = _RunState(
        current_guidelines=[
            KnowledgeEntry(
                id="g1",
                tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
                title="Existing guideline",
                description="D",
                content="C",
                when_to_use="W",
                tier="guideline",
            )
        ]
    )
    item = DatasetItem(
        id="tiny_delta",
        content="A",
        content_area="ops",
        diagram_type="flowchart",
        query="q",
    )

    engine._run_one_sample(item, 0, state)

    assert state.current_guidelines[0].usage_count == 1
    assert state.current_guidelines[0].success_count == 0
    assert state.all_strategies == []
    assert [entry.polarity for entry in state.neutral_strategies] == ["neutral"]
    assert state.anti_patterns == []
    assert state.failed_usage["guideline:g1"][0]["delta_score"] == 0.01
    assert state.sample_failures == []


def test_run_one_sample_upserts_existing_strategy_id_without_resetting_stats(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import (
        DiagramKnowledgeEvolverEngine,
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

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    # Pinned to the legacy criterion: this test is about ID upsert semantics.
    engine.config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        knowledge_success_criterion="refiner_delta",
    )
    engine._retrieve_and_format_knowledge = lambda *_args, **_kwargs: ("", [])

    class FakeRefinementService:
        def run_loop(self, *, sample_id, sample_info, retrieved_knowledge):
            strategy = KnowledgeEntry(
                id="sample_layout",
                tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
                title="Fresh layout strategy",
                description="New description",
                content="New content",
                when_to_use="Use now",
                delta_score=0.8,
                evidence_ids=["new-evidence"],
            )
            history = [
                IterationRecord(
                    id=f"{sample_id}_iter_0",
                    iteration=0,
                    tags=TagSet(),
                    text_content=sample_info.content,
                    user_query=sample_info.query,
                    diagram=DiagramRef(representation="manifest.json", manifest_ref="image.png"),
                    evaluation={},
                    feedback=Feedback(LLM_comments=[]),
                    delta_score=0.8,
                )
            ]
            return [strategy], history

    engine.refinement_service = FakeRefinementService()
    existing = KnowledgeEntry(
        id="sample_layout",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Old layout strategy",
        description="Old description",
        content="Old content",
        when_to_use="Use before",
        delta_score=0.6,
        usage_count=5,
        success_count=4,
        support_count=2,
        generalization_status="validated",
        validation_success_rate=0.8,
        evidence_ids=["old-evidence"],
    )
    state = _RunState(all_strategies=[existing])
    item = DatasetItem(
        id="sample",
        content="A",
        content_area="ops",
        diagram_type="flowchart",
        query="q",
    )

    engine._run_one_sample(item, 0, state)

    assert [entry.id for entry in state.all_strategies] == ["sample_layout"]
    merged = state.all_strategies[0]
    assert merged.title == "Fresh layout strategy"
    assert merged.content == "New content"
    assert merged.delta_score == 0.8
    assert merged.usage_count == 5
    assert merged.success_count == 4
    assert merged.support_count == 2
    assert merged.validation_success_rate == 0.8
    assert merged.generalization_status == "validated"
    assert merged.evidence_ids == ["old-evidence", "new-evidence"]
    assert len(state.all_samples_history) == 1
    assert state.sample_failures == []


# ── Knowledge success criterion (the reward signal) ─────────────────────


def _iteration_record(
    *,
    record_id,
    delta_score,
    score_before,
    diagram_type="flowchart",
    content_area="ops",
):
    from evo_diagram.knowledge_evolution.schemas import (
        DiagramRef,
        Feedback,
        IterationRecord,
        TagSet,
    )

    return IterationRecord(
        id=record_id,
        iteration=0,
        tags=TagSet(domain=[content_area], diagram_type=[diagram_type]),
        text_content="T",
        user_query="Q",
        diagram=DiagramRef(representation="m.json", manifest_ref="m.png"),
        evaluation={
            "quality": score_before + delta_score,
            "score_before": score_before,
            "score_after": score_before + delta_score,
        },
        feedback=Feedback(LLM_comments=[]),
        delta_score=delta_score,
    )


def _baseline(observations, *, min_samples=3):
    """FirstPassBaseline pre-loaded with ``(diagram_type, content_area, score)``."""
    from evo_diagram.knowledge_evolution.engine import FirstPassBaseline

    baseline = FirstPassBaseline(min_samples=min_samples)
    for diagram_type, content_area, score in observations:
        baseline.observe(diagram_type, content_area, score)
    return baseline


def test_default_criterion_scores_the_generator_not_the_refiner(tmp_path):
    """The retrieved knowledge only reaches the generator.

    ``delta_score`` measures the refiner's repair work, so it rewarded exactly
    the knowledge that made the first diagram worse. The default now compares
    the first-pass score against a baseline.
    """
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import (
        KnowledgeSuccessCriterion,
        evaluate_knowledge_outcome,
    )

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))
    assert (
        config.knowledge_success_criterion
        == KnowledgeSuccessCriterion.FIRST_PASS_VS_HISTORY
    )

    baseline = _baseline([("flowchart", "ops", 5.0)] * 3)

    # Near-perfect first pass, nothing left for the refiner to do.
    strong = [_iteration_record(record_id="a", delta_score=0.0, score_before=9.8)]
    # Terrible first pass that the refiner largely repairs.
    weak = [_iteration_record(record_id="b", delta_score=4.0, score_before=2.0)]

    assert evaluate_knowledge_outcome(strong, config, baseline=baseline).is_success
    assert not evaluate_knowledge_outcome(weak, config, baseline=baseline).is_success

    # The legacy criterion gives the opposite verdicts — that is the bug.
    legacy = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path), knowledge_success_criterion="refiner_delta"
    )
    assert not evaluate_knowledge_outcome(strong, legacy).is_success
    assert evaluate_knowledge_outcome(weak, legacy).is_success


def test_cold_start_samples_are_indeterminate_not_failures(tmp_path):
    """Missing baseline must not be recorded as evidence against the knowledge."""
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import evaluate_knowledge_outcome

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))
    history = [_iteration_record(record_id="a", delta_score=0.0, score_before=6.0)]

    outcome = evaluate_knowledge_outcome(history, config, baseline=_baseline([]))

    assert outcome.is_indeterminate
    assert outcome.is_success is False
    assert "no baseline yet" in outcome.detail


def test_baseline_falls_back_from_specific_bucket_to_global(tmp_path):
    from evo_diagram.knowledge_evolution.engine import FirstPassBaseline

    baseline = FirstPassBaseline(min_samples=2)
    baseline.observe("flowchart", "ops", 4.0)
    baseline.observe("sequence", "finance", 6.0)

    # Neither specific bucket has 2 observations, but the global bucket does.
    resolved = baseline.lookup("class", "medical")
    assert resolved is not None
    assert resolved[0] == pytest.approx(5.0)
    assert "all samples" in resolved[1]

    # Once the exact pair is warm it wins over the global mean.
    baseline.observe("flowchart", "ops", 4.0)
    exact, label = baseline.lookup("flowchart", "ops")
    assert exact == pytest.approx(4.0)
    assert label.startswith("flowchart/ops")


def test_baseline_observation_order_excludes_the_sample_being_judged(tmp_path):
    """A sample must not be measured against a baseline it contributed to."""
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import (
        DiagramKnowledgeEvolverEngine,
        _RunState,
        evaluate_knowledge_outcome,
    )

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))
    state = _RunState(first_pass_baseline=_baseline([("flowchart", "ops", 5.0)] * 3))
    history = [_iteration_record(record_id="a", delta_score=0.0, score_before=9.0)]

    outcome = evaluate_knowledge_outcome(
        history, config, baseline=state.first_pass_baseline
    )
    assert outcome.baseline == pytest.approx(5.0)

    DiagramKnowledgeEvolverEngine._observe_first_pass_baseline(history, state)
    assert state.first_pass_baseline.lookup("flowchart", "ops")[0] == pytest.approx(6.0)


def test_control_criterion_compares_against_knowledge_free_generation(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import evaluate_knowledge_outcome
    from evo_diagram.knowledge_evolution.schemas import CONTROL_SCORE_KEY

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        knowledge_success_criterion="first_pass_vs_control",
    )
    # Selecting the control criterion must turn the control run on, or the
    # required field would be missing halfway through a run.
    assert config.first_pass_control_run is True

    helped = [_iteration_record(record_id="a", delta_score=0.0, score_before=7.0)]
    helped[0].evaluation[CONTROL_SCORE_KEY] = 5.0
    hurt = [_iteration_record(record_id="b", delta_score=0.0, score_before=4.0)]
    hurt[0].evaluation[CONTROL_SCORE_KEY] = 5.0

    assert evaluate_knowledge_outcome(helped, config).is_success
    assert not evaluate_knowledge_outcome(hurt, config).is_success
    assert evaluate_knowledge_outcome(hurt, config).verdict == "failure"


def test_control_criterion_fails_fast_without_a_control_score(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import evaluate_knowledge_outcome

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        knowledge_success_criterion="first_pass_vs_control",
    )
    history = [_iteration_record(record_id="a", delta_score=0.0, score_before=7.0)]

    with pytest.raises(RuntimeError, match="control_score_before"):
        evaluate_knowledge_outcome(history, config)


def test_empty_history_is_indeterminate(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import evaluate_knowledge_outcome

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))

    assert evaluate_knowledge_outcome([], config).is_indeterminate


def test_indeterminate_sample_does_not_touch_usage_stats(tmp_path):
    """Cold-start samples must not inflate usage_count without success_count."""
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.engine import (
        DiagramKnowledgeEvolverEngine,
        _RunState,
    )
    from evo_diagram.knowledge_evolution.schemas import DatasetItem, KnowledgeEntry, TagSet

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))
    engine._retrieve_and_format_knowledge = lambda *_a, **_k: (
        "knowledge",
        [{"id": "g1", "layer": "guideline"}],
    )

    class FakeRefinementService:
        def run_loop(self, *, sample_id, sample_info, retrieved_knowledge):
            return [], [_iteration_record(
                record_id=f"{sample_id}_iter_0", delta_score=0.0, score_before=6.0
            )]

    engine.refinement_service = FakeRefinementService()
    guideline = KnowledgeEntry(
        id="g1",
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Existing guideline",
        description="D",
        content="C",
        when_to_use="W",
        tier="guideline",
    )
    state = _RunState(current_guidelines=[guideline])
    item = DatasetItem(
        id="s1", content="A", content_area="ops", diagram_type="flowchart", query="q"
    )

    engine._run_one_sample(item, 0, state)

    assert guideline.usage_count == 0
    assert guideline.success_count == 0
    assert state.failed_usage == {}
    assert state.sample_failures == []
    assert [s["sample_id"] for s in state.indeterminate_samples] == ["s1"]
    # The observation still warms the baseline for later samples.
    assert state.first_pass_baseline.global_stats == (1, 6.0)


def test_knowledge_success_criterion_is_validated(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig

    with pytest.raises(ValueError, match="knowledge_success_criterion"):
        KnowledgeEvolutionConfig(
            output_dir=str(tmp_path),
            knowledge_success_criterion="whatever",
        )


# ── Distillation bookkeeping across repeated runs ───────────────────────


def _strategy(entry_id, *, content="C", delta_score=1.0):
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    return KnowledgeEntry(
        id=entry_id,
        tags=TagSet(domain=["ops"], diagram_type=["flowchart"], agent=["layout"]),
        title="Keep lanes stable",
        description="D",
        content=content,
        when_to_use="W",
        delta_score=delta_score,
    )


def _distilling_engine(recorded_batches):
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine

    engine = object.__new__(DiagramKnowledgeEvolverEngine)

    def fake_guideline_ops(new_strategies, existing_guidelines):
        recorded_batches.append([entry.id for entry in new_strategies])
        return []

    engine._update_guidelines = fake_guideline_ops
    engine._apply_memory_operations = lambda existing, ops, item_type: existing
    return engine


def test_second_run_over_same_dataset_still_distills_changed_strategies():
    """The old integer high-water mark made run 2 a silent no-op.

    Strategy IDs are deterministic (``f"{sample_id}_{key}"``) and
    ``_upsert_entries_by_id`` merges a repeated ID *in place*, so
    ``len(all_strategies)`` never grew past the seeded count and
    ``all_strategies[count:]`` was always empty — while the log still claimed
    distillation had run.
    """
    from evo_diagram.knowledge_evolution.engine import (
        DiagramKnowledgeEvolverEngine,
        _RunState,
    )

    batches = []
    engine = _distilling_engine(batches)

    # Run 2 startup: the strategy is seeded from the vector DB.
    state = _RunState(all_strategies=[_strategy("sample1_layout")])
    state.mark_distilled(state.all_strategies)
    assert state.pending_distillation() == []

    # The sample is re-processed and produces the same ID with new content.
    DiagramKnowledgeEvolverEngine._upsert_entries_by_id(
        state.all_strategies,
        [_strategy("sample1_layout", content="Refined content", delta_score=2.0)],
    )
    assert len(state.all_strategies) == 1  # merged in place; the list did not grow

    engine._run_distillation(state)

    assert batches == [["sample1_layout"]]


def test_distillation_skips_strategies_that_did_not_change():
    from evo_diagram.knowledge_evolution.engine import _RunState

    batches = []
    engine = _distilling_engine(batches)

    state = _RunState(all_strategies=[_strategy("sample1_layout")])
    engine._run_distillation(state)
    engine._run_distillation(state)

    assert batches == [["sample1_layout"]]


# ── Versioned-ID collision handling ─────────────────────────────────────


def test_apply_memory_operations_matches_versioned_survivor_of_same_knowledge():
    """``guideline_h_v2`` is the same knowledge as a fresh ``guideline_h``.

    ``archive_design_items`` left the base ID occupied, so re-derived knowledge
    was stored as ``_v2``; the content-hash collision check only ever produces
    the base ID, so every run added another semantically duplicate guideline.
    """
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine
    from evo_diagram.knowledge_evolution.maintenance.mergers import _content_hash
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    tags = {"domain": ["ops"], "diagram_type": ["flowchart"], "agent": ["layout"]}
    base_id = f"guideline_{_content_hash('Lane stability', tags)}"
    existing = KnowledgeEntry(
        id=f"{base_id}_v2",
        tags=TagSet(**tags),
        title="Lane stability",
        description="D",
        content="C",
        when_to_use="W",
        tier="guideline",
        usage_count=7,
        success_count=5,
    )

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    result = engine._apply_memory_operations(
        [existing],
        [
            {
                "operation_type": "add",
                "title": "Lane stability",
                "description": "D",
                "content": "C",
                "when_to_use": "W",
                "_tags": tags,
            }
        ],
        "guideline",
    )

    assert [entry.id for entry in result] == [f"{base_id}_v2"]
    assert result[0].usage_count == 7  # loaded stats preserved


def test_apply_memory_operations_still_adds_genuinely_new_knowledge():
    from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    result = engine._apply_memory_operations(
        [],
        [
            {
                "operation_type": "add",
                "title": "Lane stability",
                "description": "D",
                "content": "C",
                "when_to_use": "W",
                "_tags": {"domain": ["ops"], "diagram_type": ["flowchart"], "agent": ["layout"]},
            }
        ],
        "guideline",
    )

    assert [entry.title for entry in result] == ["Lane stability"]


# ── CLI: test-split leakage guard ───────────────────────────────────────


def test_cli_requires_an_explicit_dataset(monkeypatch):
    """``--dataset`` used to default to the test split.

    Evolved knowledge is persisted to design memory and retrieved during
    generation, so defaulting to ``dataset/test`` made evaluation-set leakage
    the default behaviour of the command.
    """
    import sys
    from evo_diagram.knowledge_evolution import __main__ as ke_main

    monkeypatch.setattr(sys, "argv", ["knowledge-evolution"])

    with pytest.raises(SystemExit) as exc_info:
        ke_main.main()

    assert exc_info.value.code == 2


def test_cli_refuses_the_test_split(monkeypatch):
    import sys
    from evo_diagram.knowledge_evolution import __main__ as ke_main

    test_dataset = str(ke_main.TEST_SPLIT_DIR / "data.json")
    monkeypatch.setattr(sys, "argv", ["knowledge-evolution", "--dataset", test_dataset])

    with pytest.raises(SystemExit) as exc_info:
        ke_main.main()

    assert "Refusing to run knowledge evolution on the test split" in str(exc_info.value)


def test_cli_allows_the_test_split_only_with_explicit_override():
    from evo_diagram.knowledge_evolution import __main__ as ke_main

    test_dataset = str(ke_main.TEST_SPLIT_DIR / "data.json")

    # Does not raise.
    ke_main._reject_test_split(test_dataset, allow_test_split=True)


def test_cli_accepts_the_training_split():
    from evo_diagram.utils.path_manager import DATASET_DIR
    from evo_diagram.knowledge_evolution import __main__ as ke_main

    ke_main._reject_test_split(
        str(DATASET_DIR / "train" / "data.json"), allow_test_split=False
    )


# ── Paired knowledge-free control generation ────────────────────────────


class _FakeGeneratorWorkflow:
    def __init__(self, manifests):
        self.manifests = list(manifests)
        self.expertise_seen = []

    def run(self, text_content, user_prompt, *, design_expertise, diagram_type, content_area):
        self.expertise_seen.append(design_expertise)
        return SimpleNamespace(
            diagram_manifest=self.manifests.pop(0),
            structure_instantiation=None,
            layout_instantiation=None,
        )


def _refine_loop(config, generator):
    from evo_diagram.knowledge_evolution.iteration.loop import RefineLoop

    return RefineLoop(
        config=config,
        generator_workflow=generator,
        refiner_workflow=None,
        extractor_agent=None,
    )


def test_control_run_is_off_by_default(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig

    config = KnowledgeEvolutionConfig(output_dir=str(tmp_path))
    generator = _FakeGeneratorWorkflow([{"elements": []}])
    loop = _refine_loop(config, generator)

    assert loop._control_score(
        sample_id="s1",
        text_content="A",
        user_prompt="q",
        diagram_type="flowchart",
        content_domain="ops",
    ) is None
    assert generator.expertise_seen == []


def test_control_run_generates_without_design_expertise(tmp_path, monkeypatch):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
    from evo_diagram.knowledge_evolution.iteration import loop as loop_module

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        knowledge_success_criterion="first_pass_vs_control",
    )
    generator = _FakeGeneratorWorkflow([{"elements": []}])
    monkeypatch.setattr(loop_module, "run_all_checks", lambda *a, **k: [])

    score = _refine_loop(config, generator)._control_score(
        sample_id="s1",
        text_content="A",
        user_prompt="q",
        diagram_type="flowchart",
        content_domain="ops",
    )

    assert generator.expertise_seen == [""]
    assert score == 10.0  # no findings → perfect objective score


def test_control_run_fails_fast_without_a_manifest(tmp_path):
    from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig

    config = KnowledgeEvolutionConfig(
        output_dir=str(tmp_path),
        knowledge_success_criterion="first_pass_vs_control",
    )
    generator = _FakeGeneratorWorkflow([None])

    with pytest.raises(RuntimeError, match="Control generation produced no diagram manifest"):
        _refine_loop(config, generator)._control_score(
            sample_id="s1",
            text_content="A",
            user_prompt="q",
            diagram_type="flowchart",
            content_domain="ops",
        )
