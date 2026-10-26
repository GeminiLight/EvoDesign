import json
from types import SimpleNamespace

import pytest

from evo_diagram.design_memory.web_memory import prepare_web_memory, learn_verified_refinement


class Memory:
    def __init__(self):
        self.items = []

    def load_all_items(self, layer):
        assert layer == "strategy"
        return self.items

    def save_design_memory(self, items, layer):
        assert layer == "strategy"
        self.items.extend(items)


def test_private_stores_share_model_weights_without_sharing_content():
    from evo_diagram.design_memory.diagram_design_memory import _shared_embeddings
    constructed = []
    class Embedder:
        def __init__(self, **kwargs):
            constructed.append(kwargs)
        def embed_query(self, text):
            return [len(text)]
        def embed_documents(self, texts):
            return [[len(text)] for text in texts]
    first = _shared_embeddings(Embedder, "model")
    second = _shared_embeddings(Embedder, "model")
    assert first is second
    assert len(constructed) == 1
    assert second.embed_query("example") == [7]
    assert first.embed_documents(["a", "bb"]) == [[1], [2]]
    assert _shared_embeddings(Embedder, "another-model") is not first


def test_query_reuse_is_nested_request_scoped_and_does_not_cache_failures():
    from evo_diagram.design_memory.diagram_design_memory import _SharedEmbeddings
    calls = []
    class Embedder:
        def embed_query(self, text):
            calls.append(text)
            if text == "broken":
                raise RuntimeError("offline")
            return [len(text)]
    shared = _SharedEmbeddings(Embedder())
    with shared.reuse_queries():
        shared.embed_query("query")[0] = -1
        with shared.reuse_queries():
            assert shared.embed_query("query") == [5]
        for _ in range(2):
            with pytest.raises(RuntimeError):
                shared.embed_query("broken")
    with shared.reuse_queries():
        assert shared.embed_query("query") == [5]
    assert calls == ["query", "broken", "broken", "query"]
    with pytest.raises(ValueError), shared.reuse_queries():
        shared.embed_query("cleanup")
        raise ValueError("interrupted")
    with shared.reuse_queries():
        shared.embed_query("cleanup")
    assert calls[-2:] == ["cleanup", "cleanup"]


def test_parallel_retrievals_do_not_share_query_caches():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from evo_diagram.design_memory.diagram_design_memory import _SharedEmbeddings
    calls = []
    class Embedder:
        def embed_query(self, text):
            calls.append(text)
            return [1.0]
    shared = _SharedEmbeddings(Embedder())
    barrier = Barrier(2)
    def retrieve(_):
        with shared.reuse_queries():
            barrier.wait(timeout=5)
            assert shared.embed_query("same") == shared.embed_query("same")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(retrieve, range(2)))
    assert calls == ["same", "same"]


def test_all_retrieval_layers_reuse_vectors_but_still_query_each_store():
    from evo_diagram.design_memory.diagram_design_memory import _SharedEmbeddings
    from evo_diagram.design_memory.diagram_design_retriever import DiagramDesignRetriever
    calls, searches = [], []
    class Embedder:
        def embed_query(self, text):
            calls.append(text)
            return [1.0]
        def embed_documents(self, texts):
            return [[1.0] for _ in texts]
    class Store:
        embedding_function = _SharedEmbeddings(Embedder())
        def search_design_item(self, *, query_text, design_layer, **kwargs):
            searches.append(design_layer)
            self.embedding_function.embed_query(query_text)
            return [SimpleNamespace(page_content={"content": "Reusable layout"},
                                    metadata={"id": design_layer, "score": 1.0})]
    result = DiagramDesignRetriever(Store()).retrieve_knowledge_by_layer("Flow?!")
    assert searches == ["strategy", "guideline", "principle"]
    assert calls == ["Flow?!", "flow"]  # raw search and normalized rerank
    assert all(result[layer][0].metadata["id"] == layer for layer in searches)


def test_seed_is_idempotent_and_normalizes_retrieval_tags(tmp_path, monkeypatch):
    memory = Memory()
    monkeypatch.setattr("evo_diagram.agentic_system.workflow._load_design_memory_retriever",
                        lambda *_: (SimpleNamespace(design_memory=memory), None))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([{"id": "one", "content": "Use hierarchy", "diagram_type": "concept"}]))
    for _ in range(2):
        prepare_web_memory(str(tmp_path / "private"), "model", str(seed))
    assert len(memory.items) == 1
    assert memory.items[0]["id"] == "seed_one"
    assert memory.items[0]["tags"]["diagram_type"] == ["concept_map"]
    assert memory.items[0]["active"] is True


@pytest.mark.parametrize("before,after", [
    ({"score": 8}, {"score": 8}),
    ({"score": 8}, {"score": 7}),
    ({"score": 8}, {"score": 9, "findings": {"major": 1}}),
    ({"score": None, "findings": {"major": 1}}, {"score": 9}),
    ({"score": 8, "findings": {"major": 1}}, {"score": None}),
    ({"score": 8}, {"score": float("nan")}),
])
def test_unproven_or_regressed_results_never_reach_distiller(tmp_path, before, after):
    result = learn_verified_refinement(retriever=None, model=None,
        report_path=str(tmp_path / "does-not-exist"), diagram_type="flowchart",
        before=before, after=after, request_id="test")
    assert result["status"] == "skipped"
    assert result["saved_count"] == 0


def test_learns_only_surviving_edits_and_deduplicates(tmp_path, monkeypatch):
    seen = []
    class Extractor:
        def __init__(self, model):
            assert model == "live-model"
        def run(self, **kwargs):
            seen.append(json.loads(kwargs["iteration_history"]))
            return {"layout": {"title": "Return paths", "description": "Separate loops",
                               "content": "Reserve lanes above the main flow.",
                               "when_to_use": "Flowcharts with feedback loops."}}
    monkeypatch.setattr("evo_diagram.knowledge_evolution.distillation.curators.StrategyExtractorAgent", Extractor)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"iterations": [
        {"rolled_back": True, "llm_edits": [{"applied": True, "edit": {"id": "bad"}}]},
        {"llm_edits": [{"applied": True, "edit": {"id": "good"}},
                       {"applied": False, "edit": {"id": "rejected"}}]},
    ]}))
    memory = Memory()
    args = dict(retriever=SimpleNamespace(design_memory=memory), model="live-model",
                report_path=str(report), diagram_type="flowchart", before={"score": 7},
                after={"score": 8}, request_id="test")
    assert learn_verified_refinement(**args)["saved_count"] == 1
    assert learn_verified_refinement(**args)["saved_count"] == 0
    assert seen[0]["applied_edits"] == [{"id": "good"}]
    assert len(memory.items) == 1
    assert memory.items[0]["tags"]["diagram_type"] == ["flowchart"]
    assert memory.items[0]["provenance"]["request_id"] == "test"


def test_rolled_back_only_run_does_not_learn(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"iterations": [{"notes": ["round 1 rolled back"],
        "llm_edits": [{"applied": True, "edit": {"id": "bad"}}]}]}))
    result = learn_verified_refinement(retriever=None, model=None, report_path=str(report),
        diagram_type="flowchart", before={"score": 7}, after={"score": 8}, request_id="test")
    assert result["reason"] == "no_applied_edits"
