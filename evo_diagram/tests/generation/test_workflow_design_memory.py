"""Design-memory integration contracts for the top-level workflow.

These tests cover the path that makes evolved design knowledge actually reach a
generator prompt: ``Text2DiagramWorkflow`` builds one retriever,
``build_design_expertise`` splices its output into ``design_expertise``, and
``WorkflowState`` records whether that happened.

The real store needs chromadb + sentence-transformers, so
``evo_diagram.design_memory`` is stubbed the same way
``tests/design_memory/test_design_memory_fail_fast.py`` stubs the layer search.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── Stubs ───────────────────────────────────────────────────────────────


class _StubRetriever:
    """Stands in for DiagramDesignRetriever and records how it was called."""

    def __init__(self, *, expertise: str = "", items=None, error=None):
        self.expertise = expertise
        self.items = items if items is not None else []
        self.error = error
        self.calls = []

    def retrieve_design_expertise(
        self,
        user_query,
        *,
        diagram_type="",
        content_area="",
        retrieval_query="",
        top_k=5,
        score_threshold=0.0,
    ):
        self.calls.append({
            "user_query": user_query,
            "diagram_type": diagram_type,
            "content_area": content_area,
            "retrieval_query": retrieval_query,
            "top_k": top_k,
            "score_threshold": score_threshold,
        })
        if self.error is not None:
            raise self.error
        return self.expertise, list(self.items)


def _install_design_memory(
    monkeypatch,
    retriever=None,
    *,
    memory_error=None,
    constructed=None,
):
    """Patch the optional design-memory package with in-process fakes."""
    import evo_diagram.design_memory as design_memory_module

    class FakeDiagramDesignMemory:
        def __init__(self, vector_db_path=None, embedding_model_name=None):
            if constructed is not None:
                constructed.append({
                    "vector_db_path": vector_db_path,
                    "embedding_model_name": embedding_model_name,
                })
            if memory_error is not None:
                raise memory_error
            self.vector_db_path = vector_db_path

    monkeypatch.setattr(
        design_memory_module, "DiagramDesignMemory", FakeDiagramDesignMemory
    )
    monkeypatch.setattr(
        design_memory_module,
        "DiagramDesignRetriever",
        lambda design_memory: retriever,
    )
    return retriever


def _generator_outputs() -> dict:
    return {
        "structure_instantiation": {
            "chart_type": "flowchart",
            "nodes": [{"id": "n1", "label": "A", "class": "process"}],
            "edges": [],
            "groups": [],
        },
        "structure_specification": {"chart_type": "flowchart"},
        "styling_instantiation": {
            "n1": {
                "shape": "rectangle",
                "label": {"text": "A"},
                "strokeColor": "#111111",
                "backgroundColor": "#ffffff",
            }
        },
        "styling_specification": {"palette": "neutral"},
        "layout_instantiation": {"n1": {"x": 10, "y": 20, "w": 120, "h": 60}},
        "layout_specification": {"bounds": "ok"},
        "artifact_paths": {},
    }


def _run_workflow(monkeypatch, tmp_path, **workflow_kwargs):
    """Run the full pipeline with rendering/verification stubbed out."""
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.canvas_environment import RenderResult

    manifest = {"type": "excalidraw", "version": 2, "elements": [], "appState": {}}
    captured: dict = {}

    class CapturingGenerator:
        def run(self, **kwargs):
            captured.update(kwargs)
            return _generator_outputs()

    def fake_render_manifest(*, output_dir, **_kwargs):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        manifest_path = out / "diagram_manifest.json"
        png_path = out / "diagram_manifest.png"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        png_path.write_bytes(b"png")
        return RenderResult(
            manifest=manifest,
            manifest_path=str(manifest_path),
            png_path=str(png_path),
        )

    monkeypatch.setattr(
        workflow_module, "create_generator", lambda *args, **kwargs: CapturingGenerator()
    )
    monkeypatch.setattr(workflow_module, "render_manifest", fake_render_manifest)

    workflow = workflow_module.Text2DiagramWorkflow(
        object(),
        enable_verifier=False,
        enable_refiner=False,
        **workflow_kwargs,
    )
    state = workflow.run(
        text_content="A flows to B",
        user_query="draw the onboarding workflow",
        save_dir=str(tmp_path / "run"),
        diagram_type="flowchart",
        content_area="Software Engineering",
    )
    return workflow, state, captured


@pytest.fixture(autouse=True)
def _reset_shared_design_memory():
    """The retriever cache is process-wide, so no test may inherit another's."""
    from evo_diagram.agentic_system.workflow import reset_design_memory_cache

    reset_design_memory_cache()
    yield
    reset_design_memory_cache()


@pytest.fixture
def design_memory_store(tmp_path):
    """An existing directory that passes the "vector store present" pre-check."""
    store = tmp_path / "knowledge"
    store.mkdir()
    return str(store)


# ── Injection ───────────────────────────────────────────────────────────


def test_retrieved_design_knowledge_reaches_the_generator_prompt(
    monkeypatch, tmp_path, design_memory_store
):
    from evo_diagram.agentic_system.workflow import (
        DESIGN_MEMORY_SECTION_FOOTER,
        DESIGN_MEMORY_SECTION_HEADER,
    )

    retriever = _install_design_memory(
        monkeypatch,
        _StubRetriever(
            expertise="=== GUIDELINE ===\nTitle: Compact grouping\nContent: Group related nodes.",
            items=[{"id": "g1", "layer": "guideline"}],
        ),
    )

    _workflow, state, captured = _run_workflow(
        monkeypatch,
        tmp_path,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
        design_memory_top_k=7,
        design_memory_score_threshold=0.3,
    )

    expertise = captured["design_expertise"]
    assert DESIGN_MEMORY_SECTION_HEADER in expertise
    assert DESIGN_MEMORY_SECTION_FOOTER in expertise
    assert "Title: Compact grouping" in expertise

    # The retrieval scope comes from run()'s own arguments; the router-generated
    # query is not available this early, so user_query is the semantic query.
    assert retriever.calls == [{
        "user_query": "draw the onboarding workflow",
        "diagram_type": "flowchart",
        "content_area": "Software Engineering",
        "retrieval_query": "",
        "top_k": 7,
        "score_threshold": 0.3,
    }]

    assert state.design_memory_enabled is True
    assert state.design_memory_degraded is False
    # Same convention as user_memory_errors: an empty list, not None.
    assert state.design_memory_errors == []
    assert state.design_memory_retrieved_items == [{"id": "g1", "layer": "guideline"}]


def test_empty_design_memory_leaves_generation_untouched(
    monkeypatch, tmp_path, design_memory_store
):
    """An empty store must be a no-op, not an empty section or a failure."""
    from evo_diagram.agentic_system.workflow import DESIGN_MEMORY_SECTION_HEADER

    _install_design_memory(monkeypatch, _StubRetriever(expertise="", items=[]))

    _workflow, state, captured = _run_workflow(
        monkeypatch,
        tmp_path,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )

    assert captured["design_expertise"] == ""
    assert DESIGN_MEMORY_SECTION_HEADER not in captured["design_expertise"]
    assert state.design_memory_enabled is True
    assert state.design_memory_degraded is False
    assert state.design_memory_retrieved_items is None
    assert state.final_png_path is not None  # generation still completed


def test_explicit_design_expertise_stays_first_and_is_never_dropped(
    monkeypatch, tmp_path, design_memory_store
):
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.workflow import DESIGN_MEMORY_SECTION_HEADER

    _install_design_memory(
        monkeypatch, _StubRetriever(expertise="Retrieved knowledge.", items=[])
    )
    monkeypatch.setattr(
        workflow_module, "create_generator", lambda *args, **kwargs: object()
    )

    workflow = workflow_module.Text2DiagramWorkflow(
        object(),
        enable_verifier=False,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )

    assert workflow.build_design_expertise(
        "Use lane layout.",
        "flowchart",
        "operations",
        user_query="draw it",
    ) == (
        "Use lane layout.\n\n"
        f"{DESIGN_MEMORY_SECTION_HEADER}\n"
        "Retrieved knowledge.\n"
        "=== END RETRIEVED DESIGN KNOWLEDGE ==="
    )


# ── Segmentation with user memory ───────────────────────────────────────


def test_design_memory_and_user_memory_are_kept_as_separate_segments():
    """Caller text → design memory → user preferences, never interleaved."""
    from evo_diagram.agentic_system.workflow import (
        DESIGN_MEMORY_SECTION_FOOTER,
        DESIGN_MEMORY_SECTION_HEADER,
        Text2DiagramWorkflow,
    )

    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.enable_design_memory = True
    workflow.design_memory_retriever = _StubRetriever(
        expertise="=== PRINCIPLE ===\nTitle: Visual hierarchy\nContent: Lead with the goal.",
        items=[{"id": "p1", "layer": "principle"}],
    )
    workflow.enable_user_memory = True
    workflow.memory_system = object()
    workflow._retrieve_user_preferences = lambda **_kwargs: "Prefer compact groups."

    result = workflow.build_design_expertise(
        "Use lane layout.",
        "flowchart",
        "operations",
        user_query="draw the release process",
    )

    assert result == (
        "Use lane layout.\n\n"
        f"{DESIGN_MEMORY_SECTION_HEADER}\n"
        "=== PRINCIPLE ===\n"
        "Title: Visual hierarchy\n"
        "Content: Lead with the goal.\n"
        f"{DESIGN_MEMORY_SECTION_FOOTER}\n\n"
        "Prefer compact groups."
    )
    # The design-memory segment is one contiguous, delimited block, which is
    # what makes design_memory_retrieved_items checkable against the prompt.
    header_index = result.index(DESIGN_MEMORY_SECTION_HEADER)
    footer_index = result.index(DESIGN_MEMORY_SECTION_FOOTER)
    assert header_index < footer_index < result.index("Prefer compact groups.")
    assert workflow.design_memory_retrieved_items == [
        {"id": "p1", "layer": "principle"},
    ]


def test_user_memory_alone_keeps_its_previous_concatenation():
    """Adding design memory must not move user preferences for existing runs."""
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow

    workflow = object.__new__(Text2DiagramWorkflow)
    workflow.enable_user_memory = True
    workflow.memory_system = object()
    workflow._retrieve_user_preferences = lambda **_kwargs: "Prefer compact groups."

    assert workflow.build_design_expertise(
        "Use lane layout.", "flowchart", "operations"
    ) == "Use lane layout.\n\nPrefer compact groups."


# ── Degradation ─────────────────────────────────────────────────────────


def test_missing_design_memory_dependencies_degrade_without_raising(
    monkeypatch, tmp_path, design_memory_store
):
    _install_design_memory(
        monkeypatch,
        None,
        memory_error=ImportError("No module named 'sentence_transformers'"),
    )

    _workflow, state, captured = _run_workflow(
        monkeypatch,
        tmp_path,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )

    assert captured["design_expertise"] == ""
    assert state.design_memory_enabled is False
    assert state.design_memory_degraded is True
    assert any(
        "dependencies unavailable" in error for error in state.design_memory_errors
    )
    assert state.final_png_path is not None  # the run still produced a diagram


def test_embedding_consistency_failure_degrades_instead_of_failing_the_run(
    monkeypatch, tmp_path, design_memory_store
):
    """DiagramDesignMemory raises RuntimeError on a store built with l2."""
    _install_design_memory(
        monkeypatch,
        None,
        memory_error=RuntimeError("existing collection uses hnsw:space=l2"),
    )

    _workflow, state, _captured = _run_workflow(
        monkeypatch,
        tmp_path,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )

    assert state.design_memory_enabled is False
    assert state.design_memory_degraded is True
    assert any("hnsw:space=l2" in error for error in state.design_memory_errors)


def test_missing_vector_store_degrades_without_loading_dependencies(
    monkeypatch, tmp_path
):
    """No evolved store yet must not drag in chromadb or build an empty one."""
    import evo_diagram.design_memory as design_memory_module

    def _fail(*_args, **_kwargs):
        raise AssertionError("design memory must not be constructed")

    monkeypatch.setattr(design_memory_module, "DiagramDesignMemory", _fail)

    missing_store = str(tmp_path / "never-evolved")
    _workflow, state, _captured = _run_workflow(
        monkeypatch,
        tmp_path,
        enable_design_memory=True,
        design_memory_db_path=missing_store,
    )

    assert state.design_memory_enabled is False
    assert state.design_memory_degraded is True
    assert any(
        "vector store not found" in error for error in state.design_memory_errors
    )


def test_retrieval_failure_is_reported_and_generation_continues(
    monkeypatch, tmp_path, design_memory_store
):
    """A failing query must not look like 'there is no design knowledge'."""
    _install_design_memory(
        monkeypatch, _StubRetriever(error=RuntimeError("chroma query failed"))
    )

    _workflow, state, captured = _run_workflow(
        monkeypatch,
        tmp_path,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )

    assert captured["design_expertise"] == ""
    # The retriever was built, so design memory was "on"; the failure shows up
    # as a degradation rather than as an empty knowledge set.
    assert state.design_memory_enabled is True
    assert state.design_memory_degraded is True
    assert any("chroma query failed" in error for error in state.design_memory_errors)
    assert state.final_png_path is not None


def test_retrieval_is_skipped_when_there_is_no_query_signal(
    monkeypatch, tmp_path, design_memory_store
):
    """The backend streaming path calls with no query, type or content area."""
    from evo_diagram.agentic_system import workflow as workflow_module

    retriever = _install_design_memory(
        monkeypatch, _StubRetriever(expertise="Retrieved knowledge.")
    )
    monkeypatch.setattr(
        workflow_module, "create_generator", lambda *args, **kwargs: object()
    )

    workflow = workflow_module.Text2DiagramWorkflow(
        object(),
        enable_verifier=False,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )

    assert workflow.build_design_expertise("", None, None) == ""
    assert retriever.calls == []


# ── Switch and lifecycle ────────────────────────────────────────────────


def test_disabled_design_memory_never_constructs_a_memory_object(
    monkeypatch, tmp_path, design_memory_store
):
    import evo_diagram.design_memory as design_memory_module

    def _fail(*_args, **_kwargs):
        raise AssertionError("design memory must not be constructed when disabled")

    monkeypatch.setattr(design_memory_module, "DiagramDesignMemory", _fail)
    monkeypatch.setattr(design_memory_module, "DiagramDesignRetriever", _fail)

    workflow, state, captured = _run_workflow(
        monkeypatch,
        tmp_path,
        enable_design_memory=False,
        design_memory_db_path=design_memory_store,
    )

    assert workflow.design_memory_retriever is None
    assert captured["design_expertise"] == ""
    assert state.design_memory_enabled is False
    assert state.design_memory_degraded is False
    assert state.design_memory_errors == []


def test_bare_constructor_keeps_design_memory_off_by_default(monkeypatch, tmp_path):
    """knowledge_evolution's knowledge-free control run must stay knowledge-free."""
    import evo_diagram.design_memory as design_memory_module

    def _fail(*_args, **_kwargs):
        raise AssertionError("design memory must be opt-in on the kwarg path")

    monkeypatch.setattr(design_memory_module, "DiagramDesignMemory", _fail)

    workflow, state, _captured = _run_workflow(monkeypatch, tmp_path)

    assert workflow.enable_design_memory is False
    assert workflow.design_memory_retriever is None
    assert state.design_memory_enabled is False


def test_agentic_system_config_enables_design_memory_by_default():
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    config = AgenticSystemConfig(enable_refiner=False)

    assert config.enable_design_memory is True
    assert config.design_memory_db_path  # resolved from settings.yaml


def test_design_memory_is_built_once_per_process(
    monkeypatch, tmp_path, design_memory_store
):
    """main.py builds a workflow per dataset item; the store must be shared."""
    from evo_diagram.agentic_system import workflow as workflow_module

    constructed: list = []
    _install_design_memory(
        monkeypatch,
        _StubRetriever(expertise="Retrieved knowledge."),
        constructed=constructed,
    )
    monkeypatch.setattr(
        workflow_module, "create_generator", lambda *args, **kwargs: object()
    )

    first = workflow_module.Text2DiagramWorkflow(
        object(),
        enable_verifier=False,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )
    second = workflow_module.Text2DiagramWorkflow(
        object(),
        enable_verifier=False,
        enable_design_memory=True,
        design_memory_db_path=design_memory_store,
    )

    assert len(constructed) == 1
    assert constructed[0]["vector_db_path"] == design_memory_store
    assert first.design_memory_retriever is second.design_memory_retriever


def test_cli_can_disable_design_memory(tmp_path):
    from evo_diagram.agentic_system.main import parse_arguments
    import sys

    argv = ["main.py", "--example", "1", "--no-design-memory"]
    sys_argv = sys.argv
    try:
        sys.argv = argv
        args = parse_arguments()
    finally:
        sys.argv = sys_argv

    assert args.enable_design_memory is False
