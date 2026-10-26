"""Integration test against real chromadb + sentence-transformers.

Guards the paths that stub-based tests cannot reach: cosine collection
creation, the embedding-model metadata stamp (chromadb rejects modify()
requests carrying ``hnsw:*`` keys), score dimensionality, and reopening a
persisted store. Skipped when the heavy extras are not installed.
"""

from __future__ import annotations

import pytest

chromadb = pytest.importorskip("chromadb")
pytest.importorskip("sentence_transformers")
pytest.importorskip("langchain_chroma")
pytest.importorskip("langchain_huggingface")

from evo_diagram.design_memory.diagram_design_memory import (  # noqa: E402
    DiagramDesignMemory,
)
from evo_diagram.design_memory.diagram_design_retriever import (  # noqa: E402
    DiagramDesignRetriever,
)
from evo_diagram.knowledge_evolution.schemas import (  # noqa: E402
    KnowledgeEntry,
    TagSet,
)


def _entry(entry_id: str, title: str, description: str, content: str, when: str, diagram_type: str) -> dict:
    return KnowledgeEntry(
        id=entry_id,
        title=title,
        description=description,
        content=content,
        when_to_use=when,
        tags=TagSet(domain=["software"], diagram_type=[diagram_type], agent=["layout"]),
    ).model_dump()


def test_fresh_store_stamps_model_and_retrieves_cosine_scores(tmp_path):
    # No AppSettings.init needed: get_default() falls back to the packaged
    # defaults, which name the same Qwen3-Embedding-0.6B model.
    store = str(tmp_path / "knowledge")
    memory = DiagramDesignMemory(vector_db_path=store)
    memory.save_design_memory(
        [
            _entry(
                "g_lanes", "Align swimlane titles",
                "Lane titles must sit inside the lane header band.",
                "Place group title text at the top-left of each lane.",
                "swimlane diagrams with multiple lanes", "swimlane",
            ),
            _entry(
                "g_warm", "Warm palette for marketing",
                "Marketing diagrams read better with warm families.",
                "Prefer warm saturated fills with dark strokes.",
                "marketing or sales funnel diagrams", "flowchart",
            ),
        ],
        "guideline",
    )

    retriever = DiagramDesignRetriever(design_memory=memory)
    docs = retriever.retrieve_knowledge(
        "how to lay out swimlane lanes", types="guideline", top_k=2
    )["guideline"]

    assert docs, "cosine store returned nothing for a matching query"
    scores = [d.metadata["score"] for d in docs]
    # Real cosine relevance: in [0, 1] and descending. Under the old l2
    # default these were neither.
    assert all(0.0 <= s <= 1.0 for s in scores), scores
    assert scores == sorted(scores, reverse=True), scores
    assert "swimlane" in docs[0].metadata["title"].lower()

    # Reopening the persisted store must pass both consistency checks
    # (distance space + embedding-model stamp written via modify()).
    reopened = DiagramDesignMemory(vector_db_path=store)
    assert reopened is not None
