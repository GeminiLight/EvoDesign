"""Knowledge evolution module tests.

Run:  python -m pytest evo_diagram/tests/knowledge_evolution/ -v
"""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from evo_diagram.design_memory.diagram_design_retriever import DiagramDesignRetriever

KS_DIR = Path(__file__).resolve().parents[2] / "knowledge_evolution"


# ── Structure tests ──────────────────────────────────────────────────────


class TestModuleStructure:

    def test_module_dir_exists(self):
        assert KS_DIR.is_dir()

    @pytest.mark.parametrize("filename", [
        "__main__.py", "config.py", "schemas.py", "engine.py",
    ])
    def test_key_file_exists(self, filename):
        assert (KS_DIR / filename).is_file()

    def test_has_iteration_dir(self):
        assert (KS_DIR / "iteration").is_dir()
        assert (KS_DIR / "iteration" / "loop.py").is_file()

    def test_has_distillation_dir(self):
        assert (KS_DIR / "distillation").is_dir()
        for f in ("curators.py", "promoters.py", "judges.py"):
            assert (KS_DIR / "distillation" / f).is_file()

    def test_has_maintenance_dir(self):
        assert (KS_DIR / "maintenance").is_dir()
        for f in ("cycle.py", "promoters.py", "mergers.py"):
            assert (KS_DIR / "maintenance" / f).is_file()

    def test_old_files_removed(self):
        """Files from earlier refactors must not linger."""
        for gone in ("evolution_engine.py", "playbook.py", "artifact_store.py",
                      "refine.py", "scoring.py"):
            assert not (KS_DIR / gone).is_file(), f"Stale file: {gone}"
        assert not (KS_DIR / "distiller").is_dir(), "Stale dir: distiller/"


# ── Config tests ─────────────────────────────────────────────────────────


class TestConfig:

    def test_images_dir_property(self):
        """Bug fix: config.py was missing `import os`."""
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        c = KnowledgeEvolutionConfig(output_dir="/tmp/test_ks")
        assert c.images_dir == "/tmp/test_ks/images"

    def test_code_dir_property(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        c = KnowledgeEvolutionConfig(output_dir="/tmp/test_ks")
        assert c.code_dir == "/tmp/test_ks/code"

    def test_results_dir_property(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        c = KnowledgeEvolutionConfig(output_dir="/tmp/test_ks")
        assert c.results_dir == "/tmp/test_ks/results"

    def test_defaults(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        c = KnowledgeEvolutionConfig()
        assert c.max_iterations == 3
        assert c.delta_score_threshold == 0.5
        assert c.promote_min_domains == 3
        assert c.demote_min_usage == 3
        assert c.merge_title_similarity == 0.6

    def test_canvas_library_normalized(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        c = KnowledgeEvolutionConfig(canvas_library=" Excalidraw ")
        assert c.canvas_library == "excalidraw"

    def test_tldraw_canvas_library_rejected_until_refiner_supports_it(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        with pytest.raises(ValueError, match="knowledge evolution currently requires Excalidraw"):
            KnowledgeEvolutionConfig(canvas_library="tldraw")

    def test_invalid_canvas_library_rejected(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        with pytest.raises(ValueError, match="Unknown canvas_library"):
            KnowledgeEvolutionConfig(canvas_library="unknown-canvas")

    def test_knowledge_evolution_uses_central_canvas_capability_gate(self):
        from evo_diagram.canvas_environment.capabilities import (
            get_canvas_capabilities,
            knowledge_evolution_unsupported_reason,
            require_knowledge_evolution_capability,
        )

        assert get_canvas_capabilities("excalidraw").supports_knowledge_evolution is True
        assert require_knowledge_evolution_capability(canvas_library=" Excalidraw ") is None
        assert get_canvas_capabilities("tldraw").supports_knowledge_evolution is False
        assert "generation-only" in knowledge_evolution_unsupported_reason(canvas_library="tldraw")


def test_engine_retrieval_uses_public_layered_retriever_api():
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
    )

    calls = []

    # Subclass the real retriever: prompt formatting, active/positive gating
    # and the general-knowledge merge live there now, so the inference path and
    # this offline loop cannot show different knowledge to the same generator.
    class FakeRetriever(DiagramDesignRetriever):
        design_types = ["strategy", "guideline", "principle"]

        def __init__(self):
            pass

        def retrieve_knowledge_by_layer(
            self,
            query,
            *,
            layer_filters,
            top_k,
            score_threshold,
        ):
            calls.append(
                {
                    "query": query,
                    "layer_filters": layer_filters,
                    "top_k": top_k,
                    "score_threshold": score_threshold,
                }
            )
            return {
                "strategy": [
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "strategy_1",
                                "title": "Use lanes",
                                "content": "Keep actor lanes stable.",
                            }
                        ),
                        metadata={},
                    )
                ],
                "guideline": [
                    SimpleNamespace(
                        page_content={
                            "id": "guideline_1",
                            "title": "Compact grouping",
                            "description": "Group related nodes tightly.",
                        },
                        metadata={},
                    )
                ],
                "principle": [],
            }

        def _collect_candidates(self, *args, **kwargs):
            raise AssertionError("engine must not call retriever private methods")

        def _rerank_candidates(self, *args, **kwargs):
            raise AssertionError("engine must not call retriever private methods")

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.design_memory_mode = DesignMemoryMode.ENABLED
    engine._retriever = FakeRetriever()

    formatted, retrieved_items = engine._retrieve_and_format_knowledge(
        user_query="draw the workflow",
        diagram_type="flowchart",
        retrieval_query="router semantic query",
    )

    assert calls[0] == {
        "query": "router semantic query",
        "layer_filters": {
            "strategy": {
                "$and": [
                    {"active": True},
                    {"polarity": "positive"},
                    {"strategy_diagram_type_flowchart": True},
                ]
            },
            "guideline": {
                "$and": [
                    {"active": True},
                    {"polarity": "positive"},
                    {"guideline_diagram_type_flowchart": True},
                ]
            },
            "principle": {
                "$and": [
                    {"active": True},
                    {"polarity": "positive"},
                    {"principle_diagram_type_flowchart": True},
                ]
            },
        },
        "top_k": 5,
        "score_threshold": 0.0,
    }
    assert calls[1] == {
        "query": "router semantic query",
        "layer_filters": {
            "strategy": {"$and": [{"active": True}, {"polarity": "positive"}]},
            "guideline": {"$and": [{"active": True}, {"polarity": "positive"}]},
            "principle": {"$and": [{"active": True}, {"polarity": "positive"}]},
        },
        "top_k": 7,
        "score_threshold": 0.0,
    }
    assert "=== STRATEGY ===" in formatted
    assert "Title: Use lanes" in formatted
    assert "Keep actor lanes stable." in formatted
    assert "=== GUIDELINE ===" in formatted
    assert "Compact grouping" in formatted
    assert retrieved_items == [
        {"id": "strategy_1", "layer": "strategy"},
        {"id": "guideline_1", "layer": "guideline"},
    ]


def test_engine_retrieval_includes_general_diagram_knowledge():
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
    )

    # Subclass the real retriever: prompt formatting, active/positive gating
    # and the general-knowledge merge live there now, so the inference path and
    # this offline loop cannot show different knowledge to the same generator.
    class FakeRetriever(DiagramDesignRetriever):
        design_types = ["strategy", "guideline", "principle"]

        def __init__(self):
            pass

        def retrieve_knowledge_by_layer(
            self,
            query,
            *,
            layer_filters,
            top_k,
            score_threshold,
        ):
            strategy_filter = json.dumps(layer_filters["strategy"], sort_keys=True)
            if "strategy_diagram_type_flowchart" in strategy_filter:
                return {
                    "strategy": [
                        SimpleNamespace(
                            page_content=json.dumps(
                                {
                                    "id": "specific",
                                    "title": "Specific flow",
                                    "content": "Use explicit flowchart direction.",
                                }
                            ),
                            metadata={
                                "id": "specific",
                                "strategy_diagram_type_flowchart": True,
                            },
                        )
                    ],
                    "guideline": [],
                    "principle": [],
                }
            docs = {
                "strategy": [
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "specific",
                                "title": "Specific flow",
                                "content": "Use explicit flowchart direction.",
                            }
                        ),
                        metadata={
                            "id": "specific",
                            "strategy_diagram_type_flowchart": True,
                        },
                    ),
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "general",
                                "title": "General clarity",
                                "content": "Keep labels legible.",
                            }
                        ),
                        metadata={"id": "general"},
                    ),
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "universal",
                                "title": "Universal spacing",
                                "content": "Avoid overlaps in every diagram.",
                            }
                        ),
                        metadata={
                            "id": "universal",
                            "strategy_diagram_type_universal": True,
                        },
                    ),
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "architecture",
                                "title": "Architecture only",
                                "content": "Use deployment zones.",
                            }
                        ),
                        metadata={
                            "id": "architecture",
                            "strategy_diagram_type_architecture": True,
                        },
                    ),
                ],
                "guideline": [],
                "principle": [],
            }
            return {
                layer: layer_docs[:top_k]
                for layer, layer_docs in docs.items()
            }

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.design_memory_mode = DesignMemoryMode.ENABLED
    engine._retriever = FakeRetriever()

    formatted, retrieved_items = engine._retrieve_and_format_knowledge(
        user_query="draw the workflow",
        diagram_type="flowchart",
    )

    assert "Specific flow" in formatted
    assert "General clarity" in formatted
    assert "Universal spacing" in formatted
    assert "Architecture only" not in formatted
    assert retrieved_items == [
        {"id": "specific", "layer": "strategy"},
        {"id": "general", "layer": "strategy"},
        {"id": "universal", "layer": "strategy"},
    ]


def test_engine_retrieval_filters_audit_only_strategy_documents_before_prompt():
    from evo_diagram.knowledge_evolution.engine import (
        DesignMemoryMode,
        DiagramKnowledgeEvolverEngine,
    )

    # Subclass the real retriever: prompt formatting, active/positive gating
    # and the general-knowledge merge live there now, so the inference path and
    # this offline loop cannot show different knowledge to the same generator.
    class FakeRetriever(DiagramDesignRetriever):
        design_types = ["strategy", "guideline", "principle"]

        def __init__(self):
            pass

        def retrieve_knowledge_by_layer(
            self,
            query,
            *,
            layer_filters,
            top_k,
            score_threshold,
        ):
            return {
                "strategy": [
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "positive",
                                "title": "Positive pattern",
                                "content": "Use stable lanes.",
                                "polarity": "positive",
                            }
                        ),
                        metadata={"id": "positive", "polarity": "positive", "active": True},
                    ),
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "neutral",
                                "title": "Neutral audit",
                                "content": "Unproven pattern.",
                                "polarity": "neutral",
                            }
                        ),
                        metadata={"id": "neutral", "polarity": "neutral", "active": True},
                    ),
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "negative",
                                "title": "Negative audit",
                                "content": "Avoid this failed pattern.",
                                "polarity": "negative",
                            }
                        ),
                        metadata={"id": "negative", "polarity": "negative", "active": True},
                    ),
                    SimpleNamespace(
                        page_content=json.dumps(
                            {
                                "id": "inactive",
                                "title": "Inactive pattern",
                                "content": "Retired pattern.",
                                "polarity": "positive",
                                "active": False,
                            }
                        ),
                        metadata={"id": "inactive", "polarity": "positive", "active": False},
                    ),
                ],
                "guideline": [],
                "principle": [],
            }

    engine = object.__new__(DiagramKnowledgeEvolverEngine)
    engine.design_memory_mode = DesignMemoryMode.ENABLED
    engine._retriever = FakeRetriever()

    formatted, retrieved_items = engine._retrieve_and_format_knowledge(
        user_query="draw the workflow",
        diagram_type="general",
    )

    assert "Positive pattern" in formatted
    assert "Neutral audit" not in formatted
    assert "Negative audit" not in formatted
    assert "Inactive pattern" not in formatted
    assert retrieved_items == [{"id": "positive", "layer": "strategy"}]


# ── Schemas tests ────────────────────────────────────────────────────────


class TestSchemas:

    def test_knowledge_entry_defaults(self):
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        entry = KnowledgeEntry(
            id="test_1", tags=TagSet(), title="T", description="D",
            content="C", when_to_use="W",
        )
        assert entry.tier == "strategy"
        assert entry.polarity == "positive"
        assert entry.delta_score == 0.0
        assert entry.usage_count == 0
        assert entry.generalization_status == "local"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("tier", "principel"),
            ("polarity", "False"),
            ("generalization_status", "TRUE"),
            ("usage_count", "3"),
            ("success_count", "1"),
            ("support_count", "2"),
        ],
    )
    def test_knowledge_entry_rejects_invalid_or_coerced_long_term_state(
        self,
        field,
        value,
    ):
        from pydantic import ValidationError
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

        payload = {
            "id": "test_1",
            "tags": TagSet(),
            "title": "T",
            "description": "D",
            "content": "C",
            "when_to_use": "W",
            field: value,
        }

        with pytest.raises(ValidationError):
            KnowledgeEntry.model_validate(payload)

    def test_load_dataset_flat(self):
        from evo_diagram.knowledge_evolution.schemas import load_dataset
        data = [
            {"id": "s1", "content": "hello", "content_area": "cs", "query": "draw it"},
            {"id": "s2", "content": "world", "content_area": "math", "query": "draw math"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            items = load_dataset(path)
            assert len(items) == 2
            assert items[0].content == "hello"
            assert items[1].query == "draw math"
        finally:
            os.unlink(path)

    def test_load_dataset_wrapped(self):
        from evo_diagram.knowledge_evolution.schemas import load_dataset
        data = {
            "dataset": [
                {"id": "x1", "content": "test", "content_area": "a", "query": "draw a"}
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            items = load_dataset(path)
            assert len(items) == 1
        finally:
            os.unlink(path)

    def test_load_dataset_rejects_legacy_format(self):
        from evo_diagram.knowledge_evolution.schemas import load_dataset
        data = [{"id": "s1", "text": "hello", "domain": "cs", "query": "q"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="content"):
                load_dataset(path)
        finally:
            os.unlink(path)


# ── Scoring tests ────────────────────────────────────────────────────────


class TestScoring:

    def test_no_findings(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _compute_objective_score
        assert _compute_objective_score([]) == 10.0

    def test_one_critical(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _compute_objective_score
        score = _compute_objective_score([{"severity": "critical"}])
        assert score == 10.0 * (1.0 - 5.0 / 50.0)

    def test_many_findings_saturate(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _compute_objective_score
        findings = [{"severity": "critical"}] * 20
        assert _compute_objective_score(findings) == 0.0

    def test_unknown_severity(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _compute_objective_score
        score = _compute_objective_score([{"severity": "unknown_xxx"}])
        assert score == 10.0 * (1.0 - 0.2 / 50.0)

    def test_mixed_severities(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _compute_objective_score
        findings = [
            {"severity": "major"},
            {"severity": "minor"},
            {"severity": "info"},
        ]
        expected = round(10.0 * (1.0 - (3.0 + 1.0 + 0.2) / 50.0), 2)
        assert _compute_objective_score(findings) == expected


# ── Refine loop context tests ───────────────────────────────────────────


class TestRefineLoopContext:

    def _build_loop(self, tmp_path, monkeypatch, *, canvas_library="excalidraw", render_ok=True):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        from evo_diagram.knowledge_evolution.iteration.loop import RefineLoop
        import evo_diagram.knowledge_evolution.iteration.loop as loop_module

        config = KnowledgeEvolutionConfig(
            output_dir=str(tmp_path),
            max_iterations=1,
            canvas_library=canvas_library,
        )
        generator = MagicMock()
        generator.run.return_value = SimpleNamespace(
            diagram_manifest={"type": canvas_library, "elements": []},
            structure_instantiation={"nodes": [{"id": "n1"}], "edges": []},
            layout_instantiation={"n1": {"x": 1, "y": 2}},
        )
        refiner = MagicMock()
        refiner.run.return_value = SimpleNamespace(
            refined_manifest_path=None,
            iteration_logs=[],
        )
        extractor = MagicMock()
        extractor.run.return_value = {
            "layout": {
                "title": "Layout rule",
                "description": "Keep related nodes close",
                "content": "Cluster nodes by relation.",
                "when_to_use": "When diagrams have related concepts.",
            }
        }
        render_calls = []
        check_calls = []

        def fake_render_png_result(*, manifest, output_path, canvas_library):
            render_calls.append({
                "manifest": manifest,
                "output_path": output_path,
                "canvas_library": canvas_library,
            })
            if render_ok:
                Path(output_path).write_bytes(b"png")
            return SimpleNamespace(
                ok=render_ok,
                output_path=output_path,
                error="" if render_ok else "render failed",
            )

        def fake_run_all_checks(
            manifest,
            structure=None,
            layout_instantiation=None,
            canvas_library="excalidraw",
            skip_categories=None,
        ):
            check_calls.append({
                "manifest": manifest,
                "structure": structure,
                "layout_instantiation": layout_instantiation,
                "canvas_library": canvas_library,
                "skip_categories": skip_categories,
            })
            return []

        monkeypatch.setattr(loop_module, "render_png_result", fake_render_png_result)
        monkeypatch.setattr(loop_module, "run_all_checks", fake_run_all_checks)

        return (
            RefineLoop(config, generator, refiner, extractor),
            generator,
            refiner,
            extractor,
            render_calls,
            check_calls,
        )

    def test_loop_passes_canvas_and_sample_context(self, tmp_path, monkeypatch):
        from evo_diagram.knowledge_evolution.schemas import DatasetItem

        loop, generator, refiner, extractor, render_calls, check_calls = self._build_loop(
            tmp_path,
            monkeypatch,
            canvas_library="excalidraw",
        )
        sample = DatasetItem(
            id="s1",
            content="Explain transformers.",
            content_area="machine learning",
            diagram_type="architecture",
            query="Draw the model blocks.",
        )

        strategies, history = loop.run_loop("s1", sample, "retrieved rule")

        assert generator.run.call_args.kwargs["design_expertise"] == "retrieved rule"
        assert generator.run.call_args.kwargs["diagram_type"] == "architecture"
        assert generator.run.call_args.kwargs["content_area"] == "machine learning"
        assert render_calls[0]["canvas_library"] == "excalidraw"
        assert refiner.run.call_args.kwargs["canvas_library"] == "excalidraw"
        assert refiner.run.call_args.kwargs["structure_path"].endswith("structure.json")
        assert refiner.run.call_args.kwargs["layout_path"].endswith("layout.json")
        assert json.loads(
            Path(refiner.run.call_args.kwargs["structure_path"]).read_text(encoding="utf-8")
        ) == {"nodes": [{"id": "n1"}], "edges": []}
        assert json.loads(
            Path(refiner.run.call_args.kwargs["layout_path"]).read_text(encoding="utf-8")
        ) == {"n1": {"x": 1, "y": 2}}
        assert len(check_calls) == 2
        assert {call["canvas_library"] for call in check_calls} == {"excalidraw"}
        assert all(call["structure"] == {"nodes": [{"id": "n1"}], "edges": []} for call in check_calls)
        assert all(call["layout_instantiation"] == {"n1": {"x": 1, "y": 2}} for call in check_calls)
        extractor.run.assert_called_once()
        assert len(strategies) == 1
        assert len(history) == 1
        assert history[0].tags.domain == ["machine learning"]
        assert history[0].tags.diagram_type == ["architecture"]

    def test_loop_records_refined_artifacts_as_primary_diagram(self, tmp_path, monkeypatch):
        from evo_diagram.knowledge_evolution.schemas import DatasetItem

        loop, generator, refiner, extractor, render_calls, check_calls = self._build_loop(
            tmp_path,
            monkeypatch,
            canvas_library="excalidraw",
        )
        refined_manifest = {
            "type": "excalidraw",
            "elements": [{"id": "after-node", "type": "rectangle"}],
        }

        def fake_refiner_run(**kwargs):
            refined_path = Path(kwargs["output_dir"]) / "refined_manifest.json"
            refined_path.write_text(json.dumps(refined_manifest), encoding="utf-8")
            return SimpleNamespace(
                refined_manifest_path=str(refined_path),
                iteration_logs=[],
            )

        refiner.run.side_effect = fake_refiner_run
        sample = DatasetItem(
            id="s1",
            content="Explain transformers.",
            content_area="machine learning",
            diagram_type="architecture",
            query="Draw the model blocks.",
        )

        strategies, history = loop.run_loop("s1", sample, "retrieved rule")

        assert len(strategies) == 1
        assert len(history) == 1
        record = history[0]
        assert record.diagram.representation.endswith("s1_iter_0_refined.json")
        assert record.diagram.manifest_ref.endswith("s1_iter_0_refined.png")
        assert Path(record.diagram.representation).is_file()
        assert Path(record.diagram.manifest_ref).is_file()
        assert json.loads(Path(record.diagram.representation).read_text(encoding="utf-8")) == refined_manifest

        artifacts = record.evaluation["artifacts"]
        assert artifacts["before"]["manifest"].endswith("s1_iter_0.json")
        assert artifacts["before"]["image"].endswith("s1_iter_0.png")
        assert artifacts["after"]["manifest"] == record.diagram.representation
        assert artifacts["after"]["image"] == record.diagram.manifest_ref
        assert artifacts["after"]["source_manifest"].endswith("refined_manifest.json")
        assert render_calls[0]["manifest"] == generator.run.return_value.diagram_manifest
        assert render_calls[1]["manifest"] == refined_manifest
        assert check_calls[1]["manifest"] == refined_manifest

    def test_loop_ignores_non_converged_candidate_as_primary_diagram(
        self,
        tmp_path,
        monkeypatch,
    ):
        from evo_diagram.knowledge_evolution.schemas import DatasetItem

        loop, generator, refiner, extractor, render_calls, check_calls = self._build_loop(
            tmp_path,
            monkeypatch,
            canvas_library="excalidraw",
        )
        candidate_manifest = {
            "type": "excalidraw",
            "elements": [{"id": "candidate-node", "type": "rectangle"}],
        }

        def fake_refiner_run(**kwargs):
            candidate_path = Path(kwargs["output_dir"]) / "candidate_manifest.json"
            candidate_path.write_text(json.dumps(candidate_manifest), encoding="utf-8")
            return SimpleNamespace(
                refined_manifest_path=None,
                candidate_manifest_path=str(candidate_path),
                iteration_logs=[],
            )

        refiner.run.side_effect = fake_refiner_run
        sample = DatasetItem(
            id="s1",
            content="Explain transformers.",
            content_area="machine learning",
            diagram_type="architecture",
            query="Draw the model blocks.",
        )

        strategies, history = loop.run_loop("s1", sample, "retrieved rule")

        assert len(strategies) == 1
        assert len(history) == 1
        record = history[0]
        assert record.diagram.representation.endswith("s1_iter_0_refined.json")
        assert json.loads(Path(record.diagram.representation).read_text(encoding="utf-8")) == (
            generator.run.return_value.diagram_manifest
        )

        artifacts = record.evaluation["artifacts"]
        assert artifacts["after"]["manifest"] == record.diagram.representation
        assert artifacts["after"]["source_manifest"] is None
        assert render_calls[1]["manifest"] == generator.run.return_value.diagram_manifest
        assert check_calls[1]["manifest"] == generator.run.return_value.diagram_manifest
        history_json = extractor.run.call_args.args[3]
        assert "candidate-node" not in history_json

    def test_loop_fails_fast_when_render_fails(self, tmp_path, monkeypatch):
        from evo_diagram.knowledge_evolution.schemas import DatasetItem

        loop, generator, refiner, extractor, render_calls, check_calls = self._build_loop(
            tmp_path,
            monkeypatch,
            canvas_library="excalidraw",
            render_ok=False,
        )
        sample = DatasetItem(
            id="s1",
            content="A",
            content_area="cs",
            diagram_type="flow",
            query="draw",
        )

        with pytest.raises(RuntimeError, match="Render failed"):
            loop.run_loop("s1", sample, "")

        assert render_calls[0]["canvas_library"] == "excalidraw"
        refiner.run.assert_not_called()
        extractor.run.assert_not_called()
        assert check_calls == []

    def test_loop_fails_fast_when_generator_returns_no_manifest(self, tmp_path, monkeypatch):
        from evo_diagram.knowledge_evolution.schemas import DatasetItem

        loop, generator, refiner, extractor, render_calls, check_calls = self._build_loop(
            tmp_path,
            monkeypatch,
        )
        generator.run.return_value.diagram_manifest = None
        sample = DatasetItem(
            id="s1",
            content="A",
            content_area="cs",
            diagram_type="flow",
            query="draw",
        )

        with pytest.raises(RuntimeError, match="Generator produced no diagram manifest"):
            loop.run_loop("s1", sample, "")

        assert render_calls == []
        assert check_calls == []
        refiner.run.assert_not_called()
        extractor.run.assert_not_called()

    def test_loop_fails_fast_when_refiner_fails(self, tmp_path, monkeypatch):
        from evo_diagram.knowledge_evolution.schemas import DatasetItem

        loop, generator, refiner, extractor, render_calls, check_calls = self._build_loop(
            tmp_path,
            monkeypatch,
        )
        refiner.run.return_value = SimpleNamespace(
            status="failed",
            errors=["load failed"],
            refined_manifest_path=None,
            iteration_logs=[],
        )
        sample = DatasetItem(
            id="s1",
            content="A",
            content_area="cs",
            diagram_type="flow",
            query="draw",
        )

        with pytest.raises(RuntimeError, match="Refiner failed.*load failed"):
            loop.run_loop("s1", sample, "")

        assert len(render_calls) == 1
        assert len(check_calls) == 1
        extractor.run.assert_not_called()


class TestStrategyExtractorContract:

    def test_strategy_summary_validation_accepts_known_categories(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _validate_strategy_summary

        summary = _validate_strategy_summary(
            {
                "parse": {"title": "Keep entities", "description": "D"},
                "styling": {
                    "title": "Use role colors",
                    "description": "D",
                    "content": "C",
                },
            },
            sample_id="s1",
        )

        assert set(summary) == {"parse", "styling"}

    def test_strategy_summary_validation_rejects_unknown_category(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _validate_strategy_summary

        with pytest.raises(RuntimeError, match="unknown strategy category 'color'"):
            _validate_strategy_summary(
                {"color": {"title": "T", "description": "D"}},
                sample_id="s1",
            )

    def test_strategy_summary_validation_rejects_missing_required_fields(self):
        from evo_diagram.knowledge_evolution.iteration.loop import _validate_strategy_summary

        with pytest.raises(RuntimeError, match="missing title"):
            _validate_strategy_summary(
                {"layout": {"title": "", "description": "D"}},
                sample_id="s1",
            )


# ── Confidence scoring tests ─────────────────────────────────────────────


class TestConfidence:

    def test_basic(self):
        from evo_diagram.knowledge_evolution.maintenance.cycle import compute_confidence
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        entry = KnowledgeEntry(
            id="t", tags=TagSet(), title="T", description="D", content="C",
            when_to_use="W", usage_count=10, success_count=8,
            delta_score=3.0, support_count=4,
        )
        c = compute_confidence(entry)
        assert 0.0 <= c <= 1.0

    def test_custom_delta_scale(self):
        from evo_diagram.knowledge_evolution.maintenance.cycle import compute_confidence
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        entry = KnowledgeEntry(
            id="t", tags=TagSet(), title="T", description="D", content="C",
            when_to_use="W", delta_score=3.0,
        )
        c1 = compute_confidence(entry)
        c2 = compute_confidence(entry, delta_scale=5.0)
        assert c1 != c2

    def test_zero_usage(self):
        from evo_diagram.knowledge_evolution.maintenance.cycle import compute_confidence
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        entry = KnowledgeEntry(
            id="t", tags=TagSet(), title="T", description="D", content="C",
            when_to_use="W", delta_score=2.0,
        )
        c = compute_confidence(entry)
        assert 0.0 <= c <= 1.0


# ── Filter strategies tests ──────────────────────────────────────────────


class TestFilterStrategies:

    @pytest.fixture
    def engine(self):
        """Minimal engine with mocked heavy deps."""
        import sys
        mock_modules = [
            'evo_diagram.design_memory',
            'evo_diagram.design_memory.diagram_design_memory',
            'evo_diagram.design_memory.diagram_design_retriever',
            'chromadb',
            'evo_diagram.agentic_system.iterative_workflow',
            'evo_diagram.agentic_system.workflow',
            'evo_diagram.agentic_system.render_engine',
            'evo_diagram.canvas_environment.rendering',
        ]
        saved = {}
        for mod in mock_modules:
            saved[mod] = sys.modules.get(mod)
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        config = KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp())

        from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine
        with patch.object(DiagramKnowledgeEvolverEngine, '__init__', lambda self, *a, **kw: None):
            eng = DiagramKnowledgeEvolverEngine()
            eng.config = config

        for mod, original in saved.items():
            if original is None and mod in sys.modules:
                del sys.modules[mod]
            elif original is not None:
                sys.modules[mod] = original
        return eng

    def _make_entry(self, delta, polarity="positive"):
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        return KnowledgeEntry(
            id=f"s_{delta}", tags=TagSet(), title="T", description="D",
            content="C", when_to_use="W", delta_score=delta, polarity=polarity,
        )

    def test_above_threshold_is_qualified(self, engine):
        q, n, a = engine._filter_strategies([self._make_entry(0.6)])
        assert len(q) == 1 and len(n) == 0 and len(a) == 0

    def test_below_neg_threshold_is_anti_pattern(self, engine):
        q, n, a = engine._filter_strategies([self._make_entry(-0.6)])
        assert len(q) == 0 and len(n) == 0 and len(a) == 1
        assert a[0].polarity == "negative"

    def test_exact_threshold_is_qualified(self, engine):
        """Bug fix: delta_score == threshold was silently dropped."""
        q, n, a = engine._filter_strategies([self._make_entry(0.5)])
        assert len(q) == 1 and len(n) == 0 and len(a) == 0

    def test_exact_neg_threshold_is_anti_pattern(self, engine):
        """Bug fix: delta_score == -threshold was silently dropped."""
        q, n, a = engine._filter_strategies([self._make_entry(-0.5)])
        assert len(q) == 0 and len(n) == 0 and len(a) == 1

    def test_between_thresholds_is_neutral(self, engine):
        """RISKS.md #17: neutrals are kept (polarity='neutral'), not dropped."""
        q, n, a = engine._filter_strategies([self._make_entry(0.3)])
        assert len(q) == 0 and len(a) == 0
        assert len(n) == 1 and n[0].polarity == "neutral"

    def test_zero_is_neutral(self, engine):
        """RISKS.md #17: delta_score == 0 is neutral, not dropped."""
        q, n, a = engine._filter_strategies([self._make_entry(0.0)])
        assert len(q) == 0 and len(a) == 0
        assert len(n) == 1 and n[0].polarity == "neutral"

    def test_mixed(self, engine):
        items = [
            self._make_entry(1.0),
            self._make_entry(-1.0),
            self._make_entry(0.1),
            self._make_entry(0.5),
            self._make_entry(-0.5),
        ]
        q, n, a = engine._filter_strategies(items)
        assert len(q) == 2   # 1.0 and 0.5
        assert len(n) == 1   # 0.1
        assert len(a) == 2   # -1.0 and -0.5


# ── _apply_memory_operations tests ──────────────────────────────────────


class TestApplyMemoryOperations:

    @pytest.fixture
    def engine(self):
        import sys
        mock_modules = [
            'evo_diagram.design_memory',
            'evo_diagram.design_memory.diagram_design_memory',
            'evo_diagram.design_memory.diagram_design_retriever',
            'chromadb',
            'evo_diagram.agentic_system.iterative_workflow',
            'evo_diagram.agentic_system.workflow',
            'evo_diagram.agentic_system.render_engine',
            'evo_diagram.canvas_environment.rendering',
        ]
        saved = {}
        for mod in mock_modules:
            saved[mod] = sys.modules.get(mod)
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        config = KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp())

        from evo_diagram.knowledge_evolution.engine import DiagramKnowledgeEvolverEngine
        with patch.object(DiagramKnowledgeEvolverEngine, '__init__', lambda self, *a, **kw: None):
            eng = DiagramKnowledgeEvolverEngine()
            eng.config = config

        for mod, original in saved.items():
            if original is None and mod in sys.modules:
                del sys.modules[mod]
            elif original is not None:
                sys.modules[mod] = original
        return eng

    def _entry(self, id_, title="T"):
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        return KnowledgeEntry(
            id=id_, tags=TagSet(), title=title, description="D",
            content="C", when_to_use="W",
        )

    def test_add(self, engine):
        ops = [{
            "operation_type": "add", "title": "New",
            "description": "A new guideline", "content": "Do X",
            "when_to_use": "When Y",
            "_tags": {"domain": ["cs"], "diagram_type": ["flow"], "agent": ["layout"]},
        }]
        result = engine._apply_memory_operations([], ops, "guideline")
        assert len(result) == 1
        assert result[0].title == "New"
        assert result[0].id.startswith("guideline_")
        assert result[0].tier == "guideline"

    @pytest.mark.parametrize("item_type", ["guideline", "principle"])
    def test_add_sets_tier_to_requested_item_type(self, engine, item_type):
        ops = [{
            "operation_type": "add", "title": f"New {item_type}",
            "description": "D", "content": "C", "when_to_use": "W",
            "_tags": {"domain": ["cs"], "diagram_type": ["flow"], "agent": ["layout"]},
        }]

        result = engine._apply_memory_operations([], ops, item_type)

        assert len(result) == 1
        assert result[0].id.startswith(f"{item_type}_")
        assert result[0].tier == item_type

    def test_update(self, engine):
        existing = [self._entry("g_001", "Old Title")]
        ops = [{"operation_type": "update", "item_id": "g_001", "title": "New Title", "content": "New"}]
        result = engine._apply_memory_operations(existing, ops, "guideline")
        assert len(result) == 1
        assert result[0].title == "New Title"
        assert result[0].content == "New"
        assert result[0].description == "D"  # unchanged

    def test_delete_operation_is_rejected(self, engine):
        existing = [self._entry("g_001"), self._entry("g_002")]
        ops = [{"operation_type": "delete", "item_id": "g_001"}]

        with pytest.raises(RuntimeError, match="unknown operation_type 'delete'"):
            engine._apply_memory_operations(existing, ops, "guideline")

    def test_update_nonexistent(self, engine):
        ops = [{"operation_type": "update", "item_id": "nonexistent", "title": "X"}]
        with pytest.raises(RuntimeError, match="unknown item_id 'nonexistent'"):
            engine._apply_memory_operations([], ops, "guideline")

    def test_delete_nonexistent_rejected_before_target_lookup(self, engine):
        ops = [{"operation_type": "delete", "item_id": "nonexistent"}]

        with pytest.raises(RuntimeError, match="unknown operation_type 'delete'"):
            engine._apply_memory_operations([], ops, "guideline")

    def test_unknown_operation_type_rejected(self, engine):
        ops = [{"operation_type": "merge", "item_id": "g_001"}]

        with pytest.raises(RuntimeError, match="unknown operation_type 'merge'"):
            engine._apply_memory_operations([], ops, "guideline")

    def test_add_requires_complete_payload(self, engine):
        ops = [{
            "operation_type": "add",
            "title": "Incomplete",
            "description": "D",
            "content": "",
            "when_to_use": "W",
            "_tags": {"domain": [], "diagram_type": [], "agent": []},
        }]

        with pytest.raises(RuntimeError, match="non-empty string field 'content'"):
            engine._apply_memory_operations([], ops, "guideline")

    def test_add_requires_grouping_tags(self, engine):
        ops = [{
            "operation_type": "add",
            "title": "Missing tags",
            "description": "D",
            "content": "C",
            "when_to_use": "W",
        }]

        with pytest.raises(RuntimeError, match="requires _tags"):
            engine._apply_memory_operations([], ops, "guideline")

    def test_mixed(self, engine):
        existing = [self._entry("g_001", "A"), self._entry("g_002", "B")]
        ops = [
            {"operation_type": "update", "item_id": "g_002", "title": "B2"},
            {
                "operation_type": "add",
                "title": "C",
                "description": "D",
                "content": "C content",
                "when_to_use": "When useful",
                "_tags": {"domain": [], "diagram_type": [], "agent": []},
            },
        ]
        result = engine._apply_memory_operations(existing, ops, "guideline")
        assert len(result) == 3
        assert {e.title for e in result} == {"A", "B2", "C"}


# ── Promotion ID tests ──────────────────────────────────────────────────


class TestPromotionIds:

    class _Harness:
        def __init__(self, *, principle_result=None):
            from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
            from evo_diagram.knowledge_evolution.maintenance.promoters import PromoterMixin

            self.config = KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp())
            self.principle_promoter = MagicMock()
            self.principle_promoter.run.return_value = principle_result or {
                "should_promote": True,
                "principle_title": "Preserve Visual Invariants",
                "principle_description": "General principle",
                "principle_content": "Keep stable semantic anchors across layouts.",
                "principle_when_to_use": "When translating diagrams across contexts.",
            }

            # Bind mixin methods onto this lightweight harness without
            # constructing the full MaintenanceCycle dependency graph.
            for name in (
                "_is_promotion_success",
                "promote_strategies",
                "promote_guidelines",
            ):
                setattr(self, name, getattr(PromoterMixin, name).__get__(self))

    @staticmethod
    def _entry(
        id_,
        *,
        title="Use stable lanes",
        domain="domain",
        diagram_type="flowchart",
        agent="layout",
        tier="strategy",
    ):
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

        return KnowledgeEntry(
            id=id_,
            tags=TagSet(
                domain=[domain],
                diagram_type=[diagram_type],
                agent=[agent],
            ),
            title=title,
            description="D",
            content="C",
            when_to_use="W",
            tier=tier,
            delta_score=1.2,
        )

    def _strategies(self):
        return [
            self._entry("s1", domain="commerce", diagram_type="flowchart"),
            self._entry("s2", domain="health", diagram_type="sequence"),
            self._entry("s3", domain="education", diagram_type="architecture"),
        ]

    def test_strategy_promotion_uses_deterministic_id_and_aggregate_tags(self):
        harness = self._Harness()

        first = harness.promote_strategies(self._strategies())
        second = harness.promote_strategies(self._strategies())

        assert len(first) == 1
        assert first[0].id == second[0].id
        assert first[0].id.startswith("guideline_")
        assert first[0].evidence_ids == ["s1", "s2", "s3"]
        assert sorted(first[0].tags.domain) == ["commerce", "education", "health"]
        assert sorted(first[0].tags.diagram_type) == [
            "architecture",
            "flowchart",
            "sequence",
        ]

    def _guidelines(self):
        return [
            self._entry(
                "g1",
                title="[Guideline] Use stable lanes",
                domain="commerce",
                diagram_type="flowchart",
                tier="guideline",
            ),
            self._entry(
                "g2",
                title="[Guideline] Use stable lanes",
                domain="commerce",
                diagram_type="sequence",
                tier="guideline",
            ),
        ]

    def test_guideline_promotion_uses_deterministic_principle_id(self):
        harness = self._Harness()

        first = harness.promote_guidelines(self._guidelines())
        second = harness.promote_guidelines(self._guidelines())

        assert len(first) == 1
        assert first[0].id == second[0].id
        assert first[0].id.startswith("principle_")
        assert first[0].evidence_ids == ["g1", "g2"]
        assert sorted(first[0].tags.diagram_type) == ["flowchart", "sequence"]
        assert harness.principle_promoter.run.call_count == 2

    def test_guideline_promotion_rejects_string_bool_decision(self):
        harness = self._Harness(principle_result={
            "should_promote": "false",
            "reasoning": "not enough shared evidence",
        })

        assert harness.promote_guidelines(self._guidelines()) == []


class TestMaintenancePromotionDedupe:

    @staticmethod
    def _entry(
        id_,
        *,
        title="Use stable lanes",
        domain="domain",
        diagram_type="flowchart",
        agent="layout",
        tier="strategy",
    ):
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

        return KnowledgeEntry(
            id=id_,
            tags=TagSet(
                domain=[domain],
                diagram_type=[diagram_type],
                agent=[agent],
            ),
            title=title,
            description="D",
            content="C",
            when_to_use="W",
            tier=tier,
            delta_score=1.2,
        )

    def _cycle(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        from evo_diagram.knowledge_evolution.maintenance.cycle import MaintenanceCycle

        principle_promoter = MagicMock()
        principle_promoter.run.return_value = {
            "should_promote": True,
            "principle_title": "Preserve Visual Invariants",
            "principle_description": "General principle",
            "principle_content": "Keep stable semantic anchors across layouts.",
            "principle_when_to_use": "When translating diagrams across contexts.",
        }
        cycle = MaintenanceCycle(
            KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp()),
            principle_promoter=principle_promoter,
            demotion_judger=MagicMock(),
            merge_judger=MagicMock(),
        )
        cycle.merge_tier = MagicMock(side_effect=lambda items, _tier: (items, {"merged": 0}))
        return cycle

    def test_run_full_dedupes_repeated_strategy_promotion_and_keeps_existing_stats(self):
        cycle = self._cycle()
        strategies = [
            self._entry("s1", domain="commerce", diagram_type="flowchart"),
            self._entry("s2", domain="health", diagram_type="sequence"),
            self._entry("s3", domain="education", diagram_type="architecture"),
        ]
        existing_guideline = cycle.promote_strategies(strategies)[0]
        existing_guideline.usage_count = 9
        existing_guideline.success_count = 7

        strategies_after, guidelines, _, stats = cycle.run_full(strategies, [existing_guideline], [])

        assert strategies_after == []
        assert [g.id for g in guidelines] == [existing_guideline.id]
        assert guidelines[0].usage_count == 9
        assert guidelines[0].success_count == 7
        assert stats["retired_promoted_strategies"] == 3

    def test_run_full_dedupes_repeated_guideline_promotion_and_keeps_existing_stats(self):
        cycle = self._cycle()
        guidelines = [
            self._entry(
                "g1",
                title="[Guideline] Use stable lanes",
                domain="commerce",
                diagram_type="flowchart",
                tier="guideline",
            ),
            self._entry(
                "g2",
                title="[Guideline] Use stable lanes",
                domain="commerce",
                diagram_type="sequence",
                tier="guideline",
            ),
        ]
        existing_principle = cycle.promote_guidelines(guidelines)[0]
        existing_principle.usage_count = 8
        existing_principle.success_count = 6

        _, _, principles, _ = cycle.run_full([], guidelines, [existing_principle])

        assert [p.id for p in principles] == [existing_principle.id]
        assert principles[0].usage_count == 8
        assert principles[0].success_count == 6


# ── Title clustering tests ──────────────────────────────────────────────


class TestTitleClustering:

    def test_identical_titles_cluster(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import _cluster_by_title
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        items = [
            KnowledgeEntry(id="a", tags=TagSet(), title="Use color for roles", description="", content="", when_to_use=""),
            KnowledgeEntry(id="b", tags=TagSet(), title="Use color for roles", description="", content="", when_to_use=""),
        ]
        clusters = _cluster_by_title(items, threshold=0.6)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_different_titles_separate(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import _cluster_by_title
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        items = [
            KnowledgeEntry(id="a", tags=TagSet(), title="Use color for roles", description="", content="", when_to_use=""),
            KnowledgeEntry(id="b", tags=TagSet(), title="Align nodes to grid", description="", content="", when_to_use=""),
        ]
        clusters = _cluster_by_title(items, threshold=0.6)
        assert len(clusters) == 2

    def test_single_item(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import _cluster_by_title
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        items = [KnowledgeEntry(id="a", tags=TagSet(), title="X", description="", content="", when_to_use="")]
        clusters = _cluster_by_title(items, threshold=0.6)
        assert len(clusters) == 1

    def test_empty(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import _cluster_by_title
        assert _cluster_by_title([], threshold=0.6) == []


# ── Strict judge schema tests ────────────────────────────────────────────


class TestStrictJudgeSchemas:

    @staticmethod
    def _entry(
        entry_id,
        *,
        tier="strategy",
        title="Use stable lanes",
        diagram_type="flowchart",
    ):
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

        return KnowledgeEntry(
            id=entry_id,
            tags=TagSet(domain=["ops"], diagram_type=[diagram_type], agent=["layout"]),
            title=title,
            description="D",
            content="C",
            when_to_use="W",
            tier=tier,
            usage_count=10,
            success_count=0,
            delta_score=1.2,
        )

    @staticmethod
    def _cycle(*, merge_result=None):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        from evo_diagram.knowledge_evolution.maintenance.cycle import MaintenanceCycle

        merge_judger = MagicMock()
        if merge_result is not None:
            merge_judger.run.return_value = merge_result
        return MaintenanceCycle(
            KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp()),
            principle_promoter=MagicMock(),
            demotion_judger=MagicMock(),
            merge_judger=merge_judger,
        )

    @staticmethod
    def _promoter_harness(*, principle_result=None, demotion_result=None):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        from evo_diagram.knowledge_evolution.maintenance.promoters import PromoterMixin

        class Harness:
            pass

        h = Harness()
        h.config = KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp())
        h.principle_promoter = MagicMock()
        h.demotion_judger = MagicMock()
        if principle_result is not None:
            h.principle_promoter.run.return_value = principle_result
        if demotion_result is not None:
            h.demotion_judger.run.return_value = demotion_result

        for name in (
            "_is_promotion_success",
            "promote_guidelines",
            "check_demotion",
        ):
            setattr(h, name, getattr(PromoterMixin, name).__get__(h))
        return h

    def _guidelines_for_principle_promotion(self):
        return [
            self._entry(
                "g1",
                tier="guideline",
                title="[Guideline] Use stable lanes",
                diagram_type="flowchart",
            ),
            self._entry(
                "g2",
                tier="guideline",
                title="[Guideline] Use stable lanes",
                diagram_type="sequence",
            ),
        ]

    def test_merge_rejects_string_bool_decision(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        from evo_diagram.knowledge_evolution.maintenance.cycle import MaintenanceCycle

        merge_judger = MagicMock()
        merge_judger.run.return_value = {
            "should_merge": "false",
            "reasoning": "items are distinct",
        }
        cycle = MaintenanceCycle(
            KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp()),
            principle_promoter=MagicMock(),
            demotion_judger=MagicMock(),
            merge_judger=merge_judger,
        )

        merged, merge_count = cycle.merge_tier(
            [self._entry("s1"), self._entry("s2")],
            "strategy",
        )

        assert merge_count == 0
        assert [entry.id for entry in merged] == ["s1", "s2"]

    def test_merge_true_requires_complete_merged_payload(self):
        cycle = self._cycle(merge_result={
            "should_merge": True,
            "merged_title": "Merged stable lanes",
            "merged_description": "Merged description",
            "merged_when_to_use": "When lanes repeat across diagrams.",
            "reasoning": "same design rule",
        })

        merged, merge_count = cycle.merge_tier(
            [self._entry("s1"), self._entry("s2")],
            "strategy",
        )

        assert merge_count == 0
        assert [entry.id for entry in merged] == ["s1", "s2"]
        assert [entry.content for entry in merged] == ["C", "C"]

    def test_principle_promotion_true_requires_when_to_use(self):
        h = self._promoter_harness(principle_result={
            "should_promote": True,
            "principle_title": "Preserve Visual Invariants",
            "principle_description": "General principle",
            "principle_content": "Keep stable semantic anchors across layouts.",
            "reasoning": "shared across diagram types",
        })
        guidelines = self._guidelines_for_principle_promotion()

        assert h.promote_guidelines(guidelines) == []
        assert [entry.generalization_status for entry in guidelines] == [
            "local",
            "local",
        ]

    def test_demotion_rejects_string_bool_decision(self):
        from evo_diagram.knowledge_evolution.config import KnowledgeEvolutionConfig
        from evo_diagram.knowledge_evolution.maintenance.promoters import PromoterMixin

        class Harness:
            pass

        h = Harness()
        h.config = KnowledgeEvolutionConfig(output_dir=tempfile.mkdtemp())
        h.demotion_judger = MagicMock()
        h.demotion_judger.run.return_value = {
            "should_demote": "false",
            "reason": "keep it",
        }
        h.check_demotion = PromoterMixin.check_demotion.__get__(h)

        guideline = self._entry("g1", tier="guideline")

        assert h.check_demotion([guideline], {"guideline:g1": [{"sample_id": "bad"}]}) == []
        assert guideline.tier == "guideline"

    def test_guideline_demotion_to_guideline_is_skipped(self):
        h = self._promoter_harness(demotion_result={
            "should_demote": True,
            "new_tier": "guideline",
            "reason": "too broad for current use",
        })
        guideline = self._entry("g1", tier="guideline")

        assert h.check_demotion([guideline], {"guideline:g1": [{"sample_id": "bad"}]}) == []
        assert guideline.tier == "guideline"
        assert guideline.generalization_status == "local"

    def test_principle_demotion_to_strategy_is_skipped(self):
        h = self._promoter_harness(demotion_result={
            "should_demote": True,
            "new_tier": "strategy",
            "reason": "too specific",
        })
        principle = self._entry("p1", tier="principle")

        assert h.check_demotion([principle], {"principle:p1": [{"sample_id": "bad"}]}) == []
        assert principle.tier == "principle"
        assert principle.generalization_status == "local"

    def test_valid_demotion_true_downgrades_guideline(self):
        h = self._promoter_harness(demotion_result={
            "should_demote": True,
            "new_tier": "strategy",
            "reason": "only works in one local context",
            "updated_when_to_use": "Use only for local operational flowcharts.",
        })
        guideline = self._entry("g1", tier="guideline")

        assert h.check_demotion([guideline], {"guideline:g1": [{"sample_id": "bad"}]}) == [
            guideline
        ]
        assert guideline.tier == "strategy"
        assert guideline.generalization_status == "local"
        assert guideline.when_to_use == "Use only for local operational flowcharts."


# ── Tier shift tests ────────────────────────────────────────────────────


class TestTierShifts:

    def test_demoted_guideline_moves_to_strategy(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import _apply_tier_shifts
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        g = KnowledgeEntry(id="g1", tags=TagSet(), title="T", description="D", content="C", when_to_use="W", tier="strategy")
        strategies, guidelines, principles = _apply_tier_shifts([], [g], [], [g])
        assert len(guidelines) == 0
        assert len(strategies) == 1

    def test_demoted_principle_moves_to_guideline(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import _apply_tier_shifts
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet
        p = KnowledgeEntry(id="p1", tags=TagSet(), title="T", description="D", content="C", when_to_use="W", tier="guideline")
        strategies, guidelines, principles = _apply_tier_shifts([], [], [p], [p])
        assert len(principles) == 0
        assert len(guidelines) == 1

    def test_invalid_demoted_tier_is_rejected(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import _apply_tier_shifts
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

        item = KnowledgeEntry.model_construct(
            id="x1",
            tags=TagSet(),
            title="T",
            description="D",
            content="C",
            when_to_use="W",
            tier="unsupported",
        )

        with pytest.raises(ValueError, match="Invalid demoted tier"):
            _apply_tier_shifts([], [], [], [item])


# ── Demotion skip tests ─────────────────────────────────────────────────


class TestDemotionSkip:
    """``check_demotion`` grants immunity for one cycle, not forever."""

    @staticmethod
    def _underperforming_promoted_guideline():
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

        return KnowledgeEntry(
            id="g1", tags=TagSet(), title="T", description="D", content="C",
            when_to_use="W", tier="guideline",
            usage_count=10, success_count=0,  # terrible stats
            generalization_status="promoted",
        )

    def test_items_promoted_this_cycle_are_skipped(self):
        h = TestStrictJudgeSchemas._promoter_harness(
            demotion_result={"should_demote": True, "new_tier": "strategy"}
        )
        guideline = self._underperforming_promoted_guideline()

        assert h.check_demotion(
            [guideline],
            {"guideline:g1": [{"sample_id": "bad"}]},
            just_promoted_ids={"g1"},
        ) == []
        assert guideline.tier == "guideline"

    def test_persisted_promoted_status_does_not_grant_permanent_immunity(self):
        """Regression: ``generalization_status`` is persisted and restored.

        Using it as the "promoted this cycle" marker meant an entry promoted in
        any earlier run could never be demoted again, however badly it later
        performed.
        """
        h = TestStrictJudgeSchemas._promoter_harness(
            demotion_result={"should_demote": True, "new_tier": "strategy"}
        )
        guideline = self._underperforming_promoted_guideline()

        demoted = h.check_demotion(
            [guideline],
            {"guideline:g1": [{"sample_id": "bad"}]},
        )

        assert [item.id for item in demoted] == ["g1"]
        assert guideline.tier == "strategy"


# ── Validation evidence must not be inferred from tags ──────────────────


class TestValidatedDomainProvenance:

    @staticmethod
    def _fresh_guideline(entry_id, domain):
        from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

        return KnowledgeEntry(
            id=entry_id,
            tags=TagSet(domain=[domain], diagram_type=["flowchart"], agent=["layout"]),
            title="[Guideline] Use stable lanes",
            description="D",
            content="C",
            when_to_use="W",
            tier="guideline",
        )

    def test_merge_does_not_promote_tag_domains_to_validated_domains(self):
        """Three never-used guidelines must not merge into 3 validated domains."""
        from evo_diagram.knowledge_evolution.maintenance.mergers import MergerMixin

        sources = [
            self._fresh_guideline("g1", "finance"),
            self._fresh_guideline("g2", "medical"),
            self._fresh_guideline("g3", "legal"),
        ]
        for source in sources:
            assert source.usage_count == 0 and source.validated_domains == []

        merged = MergerMixin._build_merged_entry(
            "guideline",
            sources,
            {"merged_title": "[Guideline] Use stable lanes"},
        )

        assert merged.validated_domains == []
        # Tag coverage is still preserved — it just isn't evidence.
        assert merged.tags.domain == ["finance", "legal", "medical"]

    def test_merge_keeps_genuinely_validated_domains(self):
        from evo_diagram.knowledge_evolution.maintenance.mergers import MergerMixin

        validated = self._fresh_guideline("g1", "finance")
        validated.validated_domains = ["finance"]
        merged = MergerMixin._build_merged_entry(
            "guideline",
            [validated, self._fresh_guideline("g2", "medical")],
            {"merged_title": "[Guideline] Use stable lanes"},
        )

        assert merged.validated_domains == ["finance"]

    def test_principle_promotion_separates_tag_domains_from_validated_domains(self):
        h = TestStrictJudgeSchemas._promoter_harness(
            principle_result={
                "should_promote": True,
                "principle_title": "[Principle] Use stable lanes",
                "principle_description": "D",
                "principle_content": "C",
                "principle_when_to_use": "W",
            }
        )
        guidelines = [
            self._fresh_guideline("g1", "finance"),
            self._fresh_guideline("g2", "medical"),
        ]
        guidelines[0].tags.diagram_type = ["flowchart"]
        guidelines[1].tags.diagram_type = ["sequence"]
        guidelines[0].validated_domains = ["finance"]
        for g in guidelines:
            g.delta_score = 2.0  # clears _is_promotion_success

        promoted = h.promote_guidelines(guidelines)

        assert len(promoted) == 1
        assert promoted[0].validated_domains == ["finance"]
        assert promoted[0].tags.domain == ["finance", "medical"]
