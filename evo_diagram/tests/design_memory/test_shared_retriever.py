"""Only permanent design-memory init failures may be cached process-wide."""

from __future__ import annotations

import pytest

import evo_diagram.design_memory as design_memory_module
from evo_diagram.design_memory import shared_retriever
from evo_diagram.design_memory.diagram_design_memory import DesignMemoryConsistencyError


@pytest.fixture(autouse=True)
def _reset_cache():
    shared_retriever.reset_shared_retriever_cache()
    yield
    shared_retriever.reset_shared_retriever_cache()


def _install(monkeypatch, errors):
    calls = []

    class FakeMemory:
        def __init__(self, vector_db_path=None, embedding_model_name=None):
            calls.append(vector_db_path)
            if errors:
                raise errors.pop(0)

    class FakeRetriever:
        def __init__(self, design_memory):
            self.design_memory = design_memory

    monkeypatch.setattr(design_memory_module, "DiagramDesignMemory", FakeMemory)
    monkeypatch.setattr(design_memory_module, "DiagramDesignRetriever", FakeRetriever)
    return calls


def test_transient_init_failure_is_retried_on_next_call(monkeypatch):
    calls = _install(monkeypatch, [OSError("database is locked")])

    retriever, error = shared_retriever.load_shared_retriever("/store", "model")
    assert retriever is None and "database is locked" in error

    retriever, error = shared_retriever.load_shared_retriever("/store", "model")
    assert retriever is not None and error is None
    assert len(calls) == 2


@pytest.mark.parametrize("permanent", [
    ImportError("No module named 'chromadb'"),
    DesignMemoryConsistencyError("collection uses metric 'l2'"),
])
def test_permanent_init_failure_is_cached(monkeypatch, permanent):
    calls = _install(monkeypatch, [permanent])

    first = shared_retriever.load_shared_retriever("/store", "model")
    second = shared_retriever.load_shared_retriever("/store", "model")
    assert first == second and first[0] is None
    assert len(calls) == 1


def test_workflow_private_name_stays_a_compatible_alias(monkeypatch):
    from evo_diagram.agentic_system.workflow import _load_design_memory_retriever

    _install(monkeypatch, [])
    retriever, error = _load_design_memory_retriever("/store", "model")
    assert retriever is not None and error is None
