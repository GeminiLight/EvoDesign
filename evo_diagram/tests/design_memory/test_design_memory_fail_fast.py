from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from evo_diagram.design_memory.diagram_design_memory import DiagramDesignMemory
from evo_diagram.design_memory.diagram_design_retriever import DiagramDesignRetriever


class _FakeCollection:
    def __init__(self, *, metadata=None, count=0, fail_count=False):
        self.metadata = metadata
        self._count = count
        self._fail_count = fail_count
        self.modified_metadata = None

    def count(self):
        if self._fail_count:
            raise ValueError("metadata unavailable")
        return self._count

    def modify(self, *, metadata):
        # Mirror ChromaDB 1.x ``_validate_modify_request``: the distance
        # function is immutable after creation, so any modify payload carrying
        # the legacy ``hnsw:space`` key is rejected — even when unchanged. A
        # fake that silently accepted it is what let the real incompatibility
        # slip past this suite once.
        if metadata and "hnsw:space" in metadata:
            raise ValueError(
                "Changing the distance function of a collection once it is "
                "created is not supported currently."
            )
        self.modified_metadata = metadata
        self.metadata = metadata


class _FakeVectorDb:
    def __init__(self, collection):
        self._collection = collection


class _FailingDeleteVectorDb:
    def __init__(self):
        self.added = False

    def delete(self, *, ids):
        raise RuntimeError(f"delete unavailable for {ids}")

    def add_documents(self, documents, *, ids):
        self.added = True


class _VersionedAddVectorDb:
    def __init__(self, *, existing_ids=()):
        self.existing_ids = set(existing_ids)
        self.added_documents = []
        self.added_ids = []

    def get(self, ids):
        return {"ids": [item_id for item_id in ids if item_id in self.existing_ids]}

    def add_documents(self, documents, *, ids):
        self.added_documents = list(documents)
        self.added_ids = list(ids)
        self.existing_ids.update(ids)


class _SafeUpdateVectorDb:
    def __init__(self, *, fail_update=False):
        self.fail_update = fail_update
        self.updated_ids = None
        self.updated_documents = None
        self.deleted = False
        self.added = False

    def update_documents(self, *, ids, documents):
        if self.fail_update:
            raise RuntimeError("safe update unavailable")
        self.updated_ids = list(ids)
        self.updated_documents = list(documents)

    def delete(self, *, ids):
        self.deleted = True

    def add_documents(self, documents, *, ids):
        self.added = True


class _NoSafeUpdateVectorDb:
    def __init__(self):
        self.deleted = False
        self.added = False

    def delete(self, *, ids):
        self.deleted = True

    def add_documents(self, documents, *, ids):
        self.added = True


class _LoadCollection:
    def __init__(self, *, ids, metadatas, documents):
        self.ids = ids
        self.metadatas = metadatas
        self.documents = documents

    def get(self, **kwargs):
        return {
            "ids": self.ids,
            "metadatas": self.metadatas,
            "documents": self.documents,
        }


class _StatsCollection:
    metadata = {}

    def __init__(self, metadatas):
        self.metadatas = metadatas

    def count(self):
        return len(self.metadatas)

    def get(self, **kwargs):
        return {"metadatas": self.metadatas}


def _memory_with_collection(collection, *, embedding_model_name="current-model"):
    memory = object.__new__(DiagramDesignMemory)
    memory.embedding_model_name = embedding_model_name
    memory.design_layers = {
        "guideline": {
            "vector_db": _FakeVectorDb(collection),
        },
    }
    return memory


def _patch_metadata_filter(monkeypatch):
    from langchain_core.documents import Document
    from evo_diagram.design_memory import diagram_design_memory as memory_module

    monkeypatch.setattr(memory_module, "Document", Document)
    monkeypatch.setattr(memory_module, "filter_complex_metadata", lambda docs: docs)


def _memory_with_vector_db(vector_db):
    memory = object.__new__(DiagramDesignMemory)
    memory._lock = threading.Lock()
    memory.vector_db_path = "memory-test"
    memory.design_layers = {"guideline": {"vector_db": vector_db}}
    return memory


def test_design_memory_stamps_empty_collection_embedding_model():
    # A freshly created Chroma collection carries the legacy ``hnsw:space``
    # metadata key. ChromaDB 1.x rejects that key in ``modify`` (the distance
    # function is fixed at creation and lives in the collection
    # ``configuration``), so the stamp must drop it and keep only the
    # embedding-model bookkeeping key.
    collection = _FakeCollection(
        metadata={DiagramDesignMemory._DISTANCE_META_KEY: DiagramDesignMemory._DISTANCE_SPACE},
        count=0,
    )
    memory = _memory_with_collection(collection)

    memory._check_embedding_model_consistency()

    # ``hnsw:space`` is stripped from the modify payload; cosine space survives
    # in ``configuration``, which ``_collection_distance_space`` reads first,
    # so the distance-space check stays verifiable on the next startup.
    assert collection.modified_metadata == {
        DiagramDesignMemory._MODEL_META_KEY: "current-model",
    }
    assert DiagramDesignMemory._DISTANCE_META_KEY not in collection.modified_metadata


def test_design_memory_rejects_missing_embedding_metadata_on_non_empty_collection():
    memory = _memory_with_collection(_FakeCollection(metadata=None, count=3))

    with pytest.raises(RuntimeError, match="metadata is missing"):
        memory._check_embedding_model_consistency()


def test_design_memory_rejects_embedding_model_mismatch():
    memory = _memory_with_collection(
        _FakeCollection(
            metadata={DiagramDesignMemory._MODEL_META_KEY: "old-model"},
            count=3,
        )
    )

    with pytest.raises(RuntimeError, match="Embedding model mismatch"):
        memory._check_embedding_model_consistency()


def test_design_memory_search_errors_are_not_silently_dropped():
    class FailingVectorDb:
        def similarity_search_with_relevance_scores(self, *args, **kwargs):
            raise ValueError("vector store unavailable")

    memory = object.__new__(DiagramDesignMemory)
    memory.design_layers = {"guideline": {"vector_db": FailingVectorDb()}}

    with pytest.raises(RuntimeError, match="Design memory search failed"):
        memory.search_design_item("layout", design_layer="guideline")


def test_design_memory_load_all_items_errors_are_not_silently_dropped():
    class FailingCollection:
        def get(self, **kwargs):
            raise RuntimeError("collection unavailable")

    memory = _memory_with_collection(FailingCollection())

    with pytest.raises(RuntimeError, match="Failed to load items"):
        memory.load_all_items("guideline")


def test_design_memory_load_all_items_rejects_corrupt_original_json_data():
    memory = _memory_with_collection(
        _LoadCollection(
            ids=["g1"],
            metadatas=[{"original_json_data": "{not json"}],
            documents=['{"id": "fallback", "title": "Fallback"}'],
        )
    )

    with pytest.raises(
        RuntimeError,
        match="Failed to parse original_json_data for guideline item 'g1'",
    ):
        memory.load_all_items("guideline")


def test_design_memory_load_all_items_rejects_non_object_original_json_data():
    memory = _memory_with_collection(
        _LoadCollection(
            ids=["g1"],
            metadatas=[{"original_json_data": '["not", "an", "object"]'}],
            documents=['{"id": "fallback", "title": "Fallback"}'],
        )
    )

    with pytest.raises(
        RuntimeError,
        match="original_json_data for guideline item 'g1' must decode to an object",
    ):
        memory.load_all_items("guideline")


def test_design_memory_load_all_items_keeps_legacy_document_fallback():
    memory = _memory_with_collection(
        _LoadCollection(
            ids=["g1"],
            metadatas=[{}],
            documents=['{"title": "Legacy fallback"}'],
        )
    )

    assert memory.load_all_items("guideline") == [
        {"title": "Legacy fallback", "id": "g1"}
    ]


def test_design_memory_save_syncs_versioned_id_into_metadata_and_payload(monkeypatch):
    _patch_metadata_filter(monkeypatch)
    vector_db = _VersionedAddVectorDb(existing_ids={"g1"})
    memory = _memory_with_vector_db(vector_db)

    memory.save_design_memory(
        [
            {
                "id": "g1",
                "title": "Use stable lanes",
                "content": "Keep lanes aligned.",
                "tags": {"diagram_type": ["flowchart"], "domain": ["workflow"]},
            }
        ],
        design_layer="guideline",
    )

    assert vector_db.added_ids == ["g1_v2"]
    doc = vector_db.added_documents[0]
    assert doc.id == "g1_v2"
    assert doc.metadata["id"] == "g1_v2"
    assert json.loads(doc.metadata["original_json_data"])["id"] == "g1_v2"
    assert json.loads(doc.metadata["original_json_data"])["tags"] == {
        "diagram_type": ["flowchart"],
        "domain": ["workflow"],
    }
    assert json.loads(doc.page_content)["id"] == "g1_v2"

    reloaded_memory = _memory_with_collection(
        _LoadCollection(
            ids=vector_db.added_ids,
            metadatas=[doc.metadata],
            documents=[doc.page_content],
        )
    )
    assert reloaded_memory.load_all_items("guideline")[0]["id"] == "g1_v2"


def test_design_memory_save_reserves_duplicate_ids_within_batch(monkeypatch):
    _patch_metadata_filter(monkeypatch)
    vector_db = _VersionedAddVectorDb(existing_ids=())
    memory = _memory_with_vector_db(vector_db)

    memory.save_design_memory(
        [
            {
                "id": "g1",
                "title": "Use stable lanes",
                "content": "Keep lanes aligned.",
                "tags": {"diagram_type": ["flowchart"]},
            },
            {
                "id": "g1",
                "title": "Use stable lanes again",
                "content": "Keep lanes aligned again.",
                "tags": {"diagram_type": ["flowchart"]},
            },
        ],
        design_layer="guideline",
    )

    assert vector_db.added_ids == ["g1", "g1_v2"]
    assert [doc.metadata["id"] for doc in vector_db.added_documents] == [
        "g1",
        "g1_v2",
    ]
    assert [
        json.loads(doc.metadata["original_json_data"])["id"]
        for doc in vector_db.added_documents
    ] == ["g1", "g1_v2"]
    assert [json.loads(doc.page_content)["id"] for doc in vector_db.added_documents] == [
        "g1",
        "g1_v2",
    ]


def test_design_memory_persists_quality_metadata_for_retrieval(monkeypatch):
    _patch_metadata_filter(monkeypatch)
    memory = object.__new__(DiagramDesignMemory)

    doc = memory.preprocess_design_item(
        {
            "id": "s1",
            "title": "Use stable lanes",
            "content": "Keep lanes aligned.",
            "tier": "strategy",
            "polarity": "positive",
            "generalization_status": "validated",
            "confidence": 0.81,
            "delta_score": 1.25,
            "usage_count": 7,
            "success_count": 6,
            "support_count": 3,
            "validation_success_rate": 0.86,
            "tags": {"diagram_type": ["flowchart"], "domain": ["workflow"]},
        },
        design_layer="strategy",
    )

    assert doc.metadata["id"] == "s1"
    assert doc.metadata["design_layer"] == "strategy"
    assert doc.metadata["active"] is True
    assert doc.metadata["tier"] == "strategy"
    assert doc.metadata["polarity"] == "positive"
    assert doc.metadata["generalization_status"] == "validated"
    assert doc.metadata["confidence"] == 0.81
    assert doc.metadata["delta_score"] == 1.25
    assert doc.metadata["usage_count"] == 7
    assert doc.metadata["success_count"] == 6
    assert doc.metadata["support_count"] == 3
    assert doc.metadata["validation_success_rate"] == 0.86
    assert doc.metadata["strategy_diagram_type_flowchart"] is True
    assert doc.metadata["strategy_domain_workflow"] is True


def test_design_memory_defaults_quality_metadata_for_minimal_items(monkeypatch):
    _patch_metadata_filter(monkeypatch)
    memory = object.__new__(DiagramDesignMemory)

    doc = memory.preprocess_design_item(
        {
            "id": "g1",
            "title": "Use stable lanes",
            "content": "Keep lanes aligned.",
            "tags": {"diagram_type": ["flowchart"]},
        },
        design_layer="guideline",
    )

    assert doc.metadata["active"] is True
    assert doc.metadata["tier"] == "guideline"
    assert doc.metadata["polarity"] == "positive"
    assert doc.metadata["generalization_status"] == "local"


def test_design_memory_update_uses_safe_update_without_delete_add(monkeypatch):
    _patch_metadata_filter(monkeypatch)
    vector_db = _SafeUpdateVectorDb()
    memory = _memory_with_vector_db(vector_db)

    memory.update_design_items(
        [
            {
                "id": "g1",
                "title": "Updated",
                "content": "Updated content",
                "tags": {"diagram_type": ["flowchart"]},
            }
        ],
        design_layer="guideline",
    )

    assert vector_db.updated_ids == ["g1"]
    assert vector_db.deleted is False
    assert vector_db.added is False
    doc = vector_db.updated_documents[0]
    assert doc.id == "g1"
    assert doc.metadata["id"] == "g1"
    assert json.loads(doc.metadata["original_json_data"])["id"] == "g1"
    assert json.loads(doc.page_content)["id"] == "g1"


def test_design_memory_update_fails_without_delete_add_fallback(monkeypatch):
    _patch_metadata_filter(monkeypatch)
    vector_db = _SafeUpdateVectorDb(fail_update=True)
    memory = _memory_with_vector_db(vector_db)

    with pytest.raises(RuntimeError, match="Failed to update existing guideline items"):
        memory.update_design_items([{"id": "g1"}], design_layer="guideline")

    assert vector_db.added is False
    assert vector_db.deleted is False


def test_design_memory_update_rejects_vector_store_without_safe_update(monkeypatch):
    _patch_metadata_filter(monkeypatch)
    vector_db = _NoSafeUpdateVectorDb()
    memory = _memory_with_vector_db(vector_db)

    with pytest.raises(RuntimeError, match="does not support safe document updates"):
        memory.update_design_items([{"id": "g1"}], design_layer="guideline")

    assert vector_db.added is False
    assert vector_db.deleted is False


def test_design_memory_archive_marks_items_inactive_without_delete():
    captured = {}
    memory = object.__new__(DiagramDesignMemory)
    memory.design_layers = {"guideline": {"vector_db": object()}}
    memory.load_all_items = lambda design_layer: [
        {
            "id": "g1",
            "title": "Use stable lanes",
            "content": "Keep lanes aligned.",
            "tags": {"diagram_type": ["flowchart"]},
        }
    ]
    memory.update_design_items = lambda items, *, design_layer: captured.update(
        {"items": items, "design_layer": design_layer}
    )

    memory.archive_design_items(
        ["g1"],
        design_layer="guideline",
        status="retired",
        reason="removed_from_active_sync",
    )

    assert captured["design_layer"] == "guideline"
    archived = captured["items"][0]
    assert archived["id"] == "g1"
    assert archived["active"] is False
    assert archived["generalization_status"] == "retired"
    assert archived["archive_reason"] == "removed_from_active_sync"
    assert archived["tier"] == "guideline"
    assert archived["polarity"] == "positive"
    assert "archived_at" in archived


def test_design_memory_archive_fails_for_missing_ids():
    memory = object.__new__(DiagramDesignMemory)
    memory.design_layers = {"guideline": {"vector_db": object()}}
    memory.load_all_items = lambda design_layer: [{"id": "g1"}]

    with pytest.raises(RuntimeError, match="Cannot archive missing guideline item ids"):
        memory.archive_design_items(["missing"], design_layer="guideline")


def test_design_memory_stats_report_lifecycle_counts():
    memory = object.__new__(DiagramDesignMemory)
    memory.embedding_model_name = "current-model"
    memory.design_layers = {
        "guideline": {
            "vector_db": _FakeVectorDb(
                _StatsCollection(
                    [
                        {
                            "active": True,
                            "polarity": "positive",
                            "generalization_status": "local",
                        },
                        {
                            "active": True,
                            "polarity": "neutral",
                            "generalization_status": "local",
                        },
                        {
                            "active": False,
                            "polarity": "positive",
                            "generalization_status": "retired",
                        },
                    ]
                )
            ),
            "description": "Guidelines",
            "collection_name": "guideline",
        }
    }

    stats = memory.get_design_layer_stats()["guideline"]

    assert stats["count"] == 3
    assert stats["total_count"] == 3
    assert stats["active_count"] == 2
    assert stats["active_positive_count"] == 1
    assert stats["archived_count"] == 1
    assert stats["by_polarity"] == {"positive": 2, "neutral": 1}
    assert stats["by_generalization_status"] == {"local": 2, "retired": 1}


def test_design_memory_delete_fails_fast_on_vector_store_errors():
    vector_db = _FailingDeleteVectorDb()
    memory = object.__new__(DiagramDesignMemory)
    memory._lock = threading.Lock()
    memory.design_layers = {"guideline": {"vector_db": vector_db}}

    with pytest.raises(RuntimeError, match="Failed to delete 1 guideline items"):
        memory.delete_design_items(["g1"], design_layer="guideline")


def test_design_retriever_propagates_design_memory_search_errors():
    class FailingDesignMemory:
        def search_design_item(self, **kwargs):
            raise RuntimeError("Design memory search failed")

    retriever = object.__new__(DiagramDesignRetriever)
    retriever.design_memory = FailingDesignMemory()
    retriever.rerank_top_n = 3

    with pytest.raises(RuntimeError, match="Design memory search failed"):
        retriever._collect_candidates(
            query_text="layout",
            filters=None,
            top_k=1,
            score_threshold=0.0,
            design_layer="guideline",
        )


def test_design_retriever_constructor_does_not_expose_unused_verbose_parameter():
    import inspect

    signature = inspect.signature(DiagramDesignRetriever)

    assert "design_memory" in signature.parameters
    assert "verbose" not in signature.parameters


def _retriever_with_embedding(embedding_function):
    class FakeDesignMemory:
        def __init__(self):
            self.embedding_function = embedding_function

    retriever = object.__new__(DiagramDesignRetriever)
    from collections import OrderedDict
    from threading import RLock
    retriever._candidate_cache = OrderedDict()
    retriever._candidate_cache_lock = RLock()
    retriever.design_memory = FakeDesignMemory()
    retriever._utility_weight = 0.0
    retriever._diversity_weight = 0.0
    retriever._exploration_weight = 0.0
    return retriever


def _doc(item_id, *, title, score=0.1):
    return SimpleNamespace(
        page_content={
            "title": title,
            "description": "",
            "content": "",
            "when_to_use": "",
        },
        metadata={"id": item_id, "score": score},
    )


def test_design_retriever_rerank_uses_persisted_quality_metadata():
    retriever = object.__new__(DiagramDesignRetriever)
    retriever._utility_weight = 1.0
    retriever._exploration_weight = 0.0
    retriever._diversity_weight = 0.0
    retriever._embed_query = lambda query_text, embedding_cache: None
    retriever._embed_candidate_texts = lambda texts, embedding_cache: False
    retriever._cached_candidate_embedding = lambda text, embedding_cache: None
    retriever._mark_rerank_degraded = lambda ordered, reason: None

    weak = _doc("weak", title="Same relevance", score=0.1)
    weak.metadata.update({
        "usage_count": 10,
        "success_count": 0,
        "delta_score": -1.0,
        "support_count": 1,
    })
    strong = _doc("strong", title="Same relevance", score=0.1)
    strong.metadata.update({
        "usage_count": 10,
        "success_count": 10,
        "delta_score": 10.0,
        "support_count": 5,
    })

    ordered = retriever._rerank_candidates(
        "same relevance",
        [weak, strong],
        top_k=2,
        embedding_cache={},
    )

    assert [doc.metadata["id"] for doc in ordered] == ["strong", "weak"]


def test_design_retriever_batches_and_caches_rerank_embeddings():
    class FakeEmbedding:
        def __init__(self):
            self.query_calls = []
            self.document_calls = []

        def embed_query(self, text):
            self.query_calls.append(text)
            return [1.0, 0.0]

        def embed_documents(self, texts):
            self.document_calls.append(list(texts))
            return [[1.0, float(index)] for index, _ in enumerate(texts)]

    embedding = FakeEmbedding()
    retriever = _retriever_with_embedding(embedding)
    cache = {}
    docs = [
        _doc("a", title="Stable lanes"),
        _doc("b", title="Balanced spacing"),
    ]

    first = retriever._rerank_candidates(
        "layout query",
        docs,
        top_k=2,
        embedding_cache=cache,
    )
    second = retriever._rerank_candidates(
        "layout query",
        docs,
        top_k=1,
        embedding_cache=cache,
    )

    assert len(first) == 2
    assert len(second) == 1
    assert embedding.query_calls == ["layout query"]
    assert embedding.document_calls == [["stable lanes", "balanced spacing"]]
    assert not hasattr(retriever, "final_top_k")


def test_design_retriever_normalize_text_preserves_cjk_terms():
    normalized = DiagramDesignRetriever._normalize_text("流程图节点 / API-网关  V2")

    assert "流程图节点" in normalized
    assert "api" in normalized
    assert "网关" in normalized
    assert "v2" in normalized


def test_design_retriever_marks_embedding_rerank_degraded(caplog):
    class FailingDocumentEmbedding:
        def embed_query(self, text):
            return [1.0, 0.0]

        def embed_documents(self, texts):
            raise RuntimeError("embedding backend unavailable")

    retriever = _retriever_with_embedding(FailingDocumentEmbedding())
    docs = [
        _doc("a", title="Stable lanes", score=0.8),
        _doc("b", title="Balanced spacing", score=0.7),
    ]

    with caplog.at_level("WARNING"):
        result = retriever._rerank_candidates("layout query", docs, top_k=2)

    assert [doc.metadata["id"] for doc in result] == ["a", "b"]
    assert all(doc.metadata["rerank_degraded"] is True for doc in result)
    assert all("embedding unavailable" in doc.metadata["rerank_degraded_reason"] for doc in result)
    assert "Embedding rerank degraded" in caplog.text


def test_design_retriever_keeps_cached_embedding_failure_degraded():
    class FailingDocumentEmbedding:
        def embed_query(self, text):
            return [1.0, 0.0]

        def embed_documents(self, texts):
            raise RuntimeError("embedding backend unavailable")

    retriever = _retriever_with_embedding(FailingDocumentEmbedding())
    cache = {}
    retriever._rerank_candidates(
        "layout query",
        [_doc("a", title="Stable lanes", score=0.8)],
        top_k=1,
        embedding_cache=cache,
    )

    repeated_doc = _doc("b", title="Stable lanes", score=0.7)
    result = retriever._rerank_candidates(
        "layout query",
        [repeated_doc],
        top_k=1,
        embedding_cache=cache,
    )

    assert result == [repeated_doc]
    assert repeated_doc.metadata["rerank_degraded"] is True


def test_design_retriever_retrieves_with_layer_specific_filters():
    retriever = object.__new__(DiagramDesignRetriever)
    retriever.design_types = ["strategy", "guideline", "principle"]

    calls = []

    def fake_search_and_rerank(**kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(metadata={"id": kwargs["design_layer"]})]

    retriever._search_and_rerank = fake_search_and_rerank

    result = retriever.retrieve_knowledge_by_layer(
        "flowchart query",
        types=["strategy", "principle"],
        layer_filters={
            "strategy": {"strategy_diagram_type_flowchart": True},
            "principle": {"principle_diagram_type_flowchart": True},
        },
        top_k=3,
        score_threshold=0.2,
    )

    assert set(result) == {"strategy", "principle"}
    assert [call["design_layer"] for call in calls] == ["strategy", "principle"]
    assert calls[0]["query_text"] == "flowchart query"
    assert calls[0]["filters"] == {"strategy_diagram_type_flowchart": True}
    assert calls[1]["filters"] == {"principle_diagram_type_flowchart": True}
    assert calls[0]["top_k"] == 3
    assert calls[0]["score_threshold"] == 0.2
    assert calls[0]["embedding_cache"] is calls[1]["embedding_cache"]


def test_design_retriever_normalizes_layer_aliases_for_types_and_filters():
    retriever = object.__new__(DiagramDesignRetriever)
    retriever.design_types = ["strategy", "guideline", "principle"]

    calls = []

    def fake_search_and_rerank(**kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(metadata={"id": kwargs["design_layer"]})]

    retriever._search_and_rerank = fake_search_and_rerank

    result = retriever.retrieve_knowledge_by_layer(
        "flowchart query",
        types=["guidelines", "principles"],
        layer_filters={
            "guidelines": {"guideline_diagram_type_flowchart": True},
            "principles": {"principle_diagram_type_flowchart": True},
        },
    )

    assert set(result) == {"guideline", "principle"}
    assert [call["design_layer"] for call in calls] == ["guideline", "principle"]
    assert calls[0]["filters"] == {"guideline_diagram_type_flowchart": True}
    assert calls[1]["filters"] == {"principle_diagram_type_flowchart": True}


def test_design_retriever_rejects_unknown_layer_specific_filter():
    retriever = object.__new__(DiagramDesignRetriever)
    retriever.design_types = ["strategy", "guideline", "principle"]

    with pytest.raises(ValueError, match="design_layer 'unknown'"):
        retriever.retrieve_knowledge_by_layer(
            "flowchart query",
            layer_filters={"unknown": {"unknown_flag": True}},
        )


def test_design_retriever_rejects_samples_layer_for_retrieval():
    retriever = object.__new__(DiagramDesignRetriever)
    retriever.design_types = ["strategy", "guideline", "principle"]

    with pytest.raises(ValueError, match="design_layer 'samples'"):
        retriever.retrieve_knowledge("query", types="samples")


# ── Cosine distance space (relevance-score contract) ────────────────────


class _ConfiguredCollection:
    def __init__(self, *, space=None, count=0, metadata=None):
        self.configuration = {"hnsw": {"space": space}} if space else {}
        self.metadata = metadata
        self._count = count

    def count(self):
        return self._count

    def modify(self, *, metadata):
        self.metadata = metadata


class _RecordingChroma:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._collection = _ConfiguredCollection(
            space="cosine",
            metadata={"hnsw:space": "cosine", "embedding_model_name": "fake-model"},
        )
        _RecordingChroma.instances.append(self)


class _RecordingEmbeddings:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _RecordingEmbeddings.instances.append(self)


def _patch_chroma_dependencies(monkeypatch, chroma_cls, embeddings_cls):
    from evo_diagram.design_memory import diagram_design_memory as memory_module

    monkeypatch.setattr(memory_module, "Chroma", chroma_cls)
    monkeypatch.setattr(memory_module, "HuggingFaceEmbeddings", embeddings_cls)
    monkeypatch.setattr(memory_module, "Document", object)
    monkeypatch.setattr(memory_module, "filter_complex_metadata", lambda docs: docs)


def test_design_memory_creates_cosine_collections_with_normalized_embeddings(
    tmp_path, monkeypatch
):
    """Relevance scores are only cosine similarities under these two settings.

    Without ``hnsw:space`` LangChain falls back to
    ``_euclidean_relevance_score_fn`` (``1 - d/√2``) over Chroma's *squared* l2
    distance, so ``doc.metadata['score']`` is neither a cosine nor bounded to
    [0, 1] and every ``score_threshold`` comparison becomes meaningless.
    """
    _RecordingChroma.instances = []
    _RecordingEmbeddings.instances = []
    _patch_chroma_dependencies(monkeypatch, _RecordingChroma, _RecordingEmbeddings)

    memory = DiagramDesignMemory(
        vector_db_path=str(tmp_path / "db"),
        embedding_model_name="fake-model",
    )

    assert _RecordingEmbeddings.instances[0].kwargs["encode_kwargs"] == {
        "normalize_embeddings": True
    }
    assert len(_RecordingChroma.instances) == len(memory.design_layers)
    for instance in _RecordingChroma.instances:
        assert instance.kwargs["collection_metadata"] == {"hnsw:space": "cosine"}


def test_design_memory_rejects_collection_created_with_another_distance_metric(
    tmp_path, monkeypatch
):
    """Reopening an l2 collection with cosine metadata silently keeps l2."""

    class _LegacyChroma(_RecordingChroma):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._collection = _ConfiguredCollection(space="l2", count=12)

    _patch_chroma_dependencies(monkeypatch, _LegacyChroma, _RecordingEmbeddings)

    with pytest.raises(RuntimeError, match="uses distance metric 'l2'"):
        DiagramDesignMemory(
            vector_db_path=str(tmp_path / "db"),
            embedding_model_name="fake-model",
        )


def test_design_memory_warns_when_distance_metric_cannot_be_verified(
    tmp_path, monkeypatch, caplog
):
    class _OpaqueChroma(_RecordingChroma):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._collection = _ConfiguredCollection(
                space=None, metadata={"embedding_model_name": "fake-model"}
            )

    _patch_chroma_dependencies(monkeypatch, _OpaqueChroma, _RecordingEmbeddings)

    with caplog.at_level("WARNING"):
        DiagramDesignMemory(
            vector_db_path=str(tmp_path / "db"),
            embedding_model_name="fake-model",
        )

    assert "Could not verify the distance metric" in caplog.text


# ── Archived entries must release their base ID ─────────────────────────


class _ArchiveAwareVectorDb:
    def __init__(self, rows):
        # rows: id -> metadata dict
        self.rows = dict(rows)

    def get(self, ids, include=None):
        present = [item_id for item_id in ids if item_id in self.rows]
        result = {"ids": present}
        if include and "metadatas" in include:
            result["metadatas"] = [self.rows[item_id] for item_id in present]
        return result


def test_next_version_id_reclaims_base_id_held_only_by_archived_entry():
    """Archived rows are tombstones and must not push knowledge to ``_v2``.

    They are skipped by retrieval and by the engine's DB seed, so the engine's
    content-hash collision check (which only ever produces the base ID) could
    never match the ``_v2`` copy, and every run added another duplicate.
    """
    memory = object.__new__(DiagramDesignMemory)
    memory.design_layers = {
        "guideline": {
            "vector_db": _ArchiveAwareVectorDb({"g1": {"active": False}}),
        }
    }

    assert memory._next_version_id("g1", "guideline") == "g1"


def test_next_version_id_still_yields_to_active_entry():
    memory = object.__new__(DiagramDesignMemory)
    memory.design_layers = {
        "guideline": {
            "vector_db": _ArchiveAwareVectorDb(
                {"g1": {"active": True}, "g1_v2": {"active": False}}
            ),
        }
    }

    assert memory._next_version_id("g1", "guideline") == "g1_v2"


def test_next_version_id_treats_unverifiable_occupant_as_taken():
    class _NoMetadataVectorDb:
        def get(self, ids, include=None):
            return {"ids": [item_id for item_id in ids if item_id == "g1"]}

    memory = object.__new__(DiagramDesignMemory)
    memory.design_layers = {"guideline": {"vector_db": _NoMetadataVectorDb()}}

    assert memory._next_version_id("g1", "guideline") == "g1_v2"


# ── Retrieval scoring chain ─────────────────────────────────────────────


class _MappedEmbedding:
    """Embeds text via an explicit lookup table; unknown text embeds to None."""

    def __init__(self, table, *, query_vector=None):
        self.table = table
        self.query_vector = query_vector if query_vector is not None else [1.0, 0.0]
        self.query_calls = []
        self.document_calls = []

    def embed_query(self, text):
        self.query_calls.append(text)
        return list(self.query_vector)

    def embed_documents(self, texts):
        self.document_calls.append(list(texts))
        return [self.table.get(text) for text in texts]


def _weighted_retriever(embedding, *, utility=0.0, exploration=0.0, diversity=0.0):
    class FakeDesignMemory:
        def __init__(self):
            self.embedding_function = embedding

    retriever = object.__new__(DiagramDesignRetriever)
    from collections import OrderedDict
    from threading import RLock
    retriever._candidate_cache = OrderedDict()
    retriever._candidate_cache_lock = RLock()
    retriever.design_memory = FakeDesignMemory()
    retriever._utility_weight = utility
    retriever._exploration_weight = exploration
    retriever._diversity_weight = diversity
    return retriever


def test_design_retriever_relevance_uses_recomputed_cosine_not_store_score():
    """One relevance scale only.

    ``max(store_relevance, cosine)`` compared a euclidean-derived relevance
    (``1.414c - 0.414`` for unit vectors) with a true cosine, so the winner was
    decided by which of the two text paths a candidate happened to take.
    """
    embedding = _MappedEmbedding({
        "stale but well scored": [0.0, 1.0],   # cosine 0.0 against the query
        "actually relevant": [0.8, 0.6],       # cosine 0.8 against the query
    })
    retriever = _weighted_retriever(embedding)

    stale = _doc("stale", title="Stale but well scored", score=0.95)
    relevant = _doc("relevant", title="Actually relevant", score=0.1)

    ordered = retriever._rerank_candidates(
        "layout", [stale, relevant], top_k=2, embedding_cache={}
    )

    assert [doc.metadata["id"] for doc in ordered] == ["relevant", "stale"]


def test_design_retriever_embeds_query_through_candidate_normalization():
    """Both sides must be embedded from identically normalised text."""
    embedding = _MappedEmbedding({"stable lanes": [1.0, 0.0]})
    retriever = _weighted_retriever(embedding)

    retriever._rerank_candidates(
        "Layout: Stable-Lanes!",
        [_doc("a", title="Stable lanes")],
        top_k=1,
        embedding_cache={},
    )

    assert embedding.query_calls == ["layout stable lanes"]


def test_design_retriever_does_not_reward_candidates_without_embeddings():
    """A missing vector must not buy a free diversity discount.

    With the shipped weights the diversity term is worth up to 0.20 while
    utility is worth 0.25, so a zero penalty for embedding-less candidates was
    enough to dominate the ranking.
    """
    embedding = _MappedEmbedding({
        "exact match": [1.0, 0.0],
        "near duplicate": [0.9, 0.43589],   # cosine 0.9 to both query and "exact match"
        "unembeddable": None,
    })
    retriever = _weighted_retriever(embedding, diversity=0.2)

    exact = _doc("exact", title="Exact match", score=0.5)
    near = _doc("near", title="Near duplicate", score=0.5)
    # Falls back to the store score because it has no vector.
    unembeddable = _doc("unembeddable", title="Unembeddable", score=0.75)

    ordered = retriever._rerank_candidates(
        "layout",
        [exact, near, unembeddable],
        top_k=2,
        embedding_cache={},
    )

    # Round 1: exact (1.0) wins. Round 2: near = 0.9 - 0.2*0.9 = 0.72 beats
    # unembeddable = 0.75 - 0.2*0.9 = 0.57. Under the old rule unembeddable kept
    # a 0.0 penalty and won with 0.75.
    assert [doc.metadata["id"] for doc in ordered] == ["exact", "near"]


def test_design_retriever_positive_ranking_weights_sum_to_one():
    retriever = _weighted_retriever(_MappedEmbedding({}), utility=0.25, exploration=0.10)

    assert retriever._relevance_weight == pytest.approx(0.65)
    assert (
        retriever._relevance_weight
        + retriever._utility_weight
        + retriever._exploration_weight
    ) == pytest.approx(1.0)


def test_design_retriever_utility_matches_maintenance_confidence():
    """Retrieval and maintenance must score the same entry identically."""
    from evo_diagram.knowledge_evolution.maintenance.cycle import compute_confidence
    from evo_diagram.knowledge_evolution.schemas import KnowledgeEntry, TagSet

    entry = KnowledgeEntry(
        id="s1",
        tags=TagSet(),
        title="T",
        description="D",
        content="C",
        when_to_use="W",
        usage_count=4,
        success_count=1,
        support_count=2,
        delta_score=-8.0,   # the case where the two implementations disagreed
    )

    assert DiagramDesignRetriever._utility_score(entry.model_dump()) == pytest.approx(
        compute_confidence(entry), abs=1e-4
    )


# ── Public integration entry point (agentic_system → design memory) ──────


class _StubLayerRetriever(DiagramDesignRetriever):
    """Real retrieve_design_expertise over a stubbed per-layer search."""

    def __init__(self, docs_by_layer, *, general_docs_by_layer=None):
        self.design_types = ["strategy", "guideline", "principle"]
        self._docs_by_layer = docs_by_layer
        self._general_docs_by_layer = general_docs_by_layer or {}
        self.calls = []

    def retrieve_knowledge_by_layer(self, query, *, layer_filters, top_k, score_threshold):
        self.calls.append({"query": query, "layer_filters": layer_filters, "top_k": top_k})
        source = (
            self._general_docs_by_layer
            if len(self.calls) > 1
            else self._docs_by_layer
        )
        return {layer: list(source.get(layer, [])) for layer in self.design_types}


def _knowledge_doc(item_id, *, title, content, layer="guideline", **metadata):
    meta = {"id": item_id, "score": 0.9}
    meta.update(metadata)
    return SimpleNamespace(
        page_content=json.dumps({"id": item_id, "title": title, "content": content}),
        metadata=meta,
    )


def test_retrieve_design_expertise_returns_prompt_ready_text_and_provenance():
    retriever = _StubLayerRetriever({
        "guideline": [
            _knowledge_doc("g1", title="Compact grouping", content="Group related nodes."),
        ],
        "principle": [
            _knowledge_doc("p1", title="Visual hierarchy", content="Lead with the goal."),
        ],
    })

    formatted, retrieved_items = retriever.retrieve_design_expertise(
        "draw the onboarding workflow",
        diagram_type="flowchart",
        content_area="Software Engineering",
    )

    assert "=== GUIDELINE ===" in formatted
    assert "Title: Compact grouping\nContent: Group related nodes." in formatted
    assert "=== PRINCIPLE ===" in formatted
    assert retrieved_items == [
        {"id": "g1", "layer": "guideline"},
        {"id": "p1", "layer": "principle"},
    ]
    # diagram_type and content_area both widen the semantic query.
    assert retriever.calls[0]["query"] == (
        "flowchart diagram: draw the onboarding workflow (Software Engineering)"
    )
    assert retriever.calls[0]["layer_filters"]["guideline"] == {
        "$and": [
            {"active": True},
            {"polarity": "positive"},
            {"guideline_diagram_type_flowchart": True},
        ]
    }


def test_retrieve_design_expertise_never_leaks_inactive_or_negative_knowledge():
    """Archived tombstones and anti-patterns must not reach a generator prompt."""
    retriever = _StubLayerRetriever({
        "guideline": [
            _knowledge_doc("archived", title="Retired", content="X", active=False),
            _knowledge_doc("anti", title="Anti-pattern", content="Y", polarity="negative"),
            _knowledge_doc("retired", title="Retired tier", content="Z",
                           generalization_status="retired"),
            _knowledge_doc("good", title="Good", content="Keep it."),
        ],
    })

    formatted, retrieved_items = retriever.retrieve_design_expertise("q")

    assert [item["id"] for item in retrieved_items] == ["good"]
    assert "Retired" not in formatted and "Anti-pattern" not in formatted


def test_retrieve_design_expertise_returns_empty_string_when_nothing_matches():
    retriever = _StubLayerRetriever({})

    formatted, retrieved_items = retriever.retrieve_design_expertise("q")

    assert formatted == ""
    assert retrieved_items == []


def test_retrieve_design_expertise_merges_a_quota_of_general_knowledge():
    from evo_diagram.design_memory.diagram_design_retriever import GENERAL_RETRIEVAL_TOP_K

    retriever = _StubLayerRetriever(
        {"guideline": [_knowledge_doc(
            "exact", title="Exact", content="E", guideline_diagram_type_flowchart=True
        )]},
        general_docs_by_layer={"guideline": [
            _knowledge_doc("gen1", title="General 1", content="G1",
                           guideline_diagram_type_general=True),
            _knowledge_doc("gen2", title="General 2", content="G2",
                           guideline_diagram_type_universal=True),
            _knowledge_doc("gen3", title="General 3", content="G3",
                           guideline_diagram_type_general=True),
            _knowledge_doc("other", title="Other type", content="O",
                           guideline_diagram_type_sequence=True),
        ]},
    )

    _formatted, retrieved_items = retriever.retrieve_design_expertise(
        "q", diagram_type="flowchart"
    )

    ids = [item["id"] for item in retrieved_items]
    assert ids[0] == "exact"
    assert len(ids) == 1 + GENERAL_RETRIEVAL_TOP_K
    assert "other" not in ids  # a different diagram type is not "general"


def test_candidate_vectors_reused_across_queries_but_content_changes_invalidate():
    class Embedding:
        calls = []
        def embed_documents(self, texts):
            self.calls.append(list(texts))
            return [[1.0, 0.0] for _ in texts]
    embedding = Embedding()
    retriever = _retriever_with_embedding(embedding)
    retriever._embed_candidate_texts(["blue layouts"], {})
    retriever._embed_candidate_texts(["blue layouts"], {})
    retriever._embed_candidate_texts(["violet layouts"], {})
    assert embedding.calls == [["blue layouts"], ["violet layouts"]]
    retriever._embed_candidate_texts([f"entry {n}" for n in range(520)], {})
    assert len(retriever._candidate_cache) == 512
