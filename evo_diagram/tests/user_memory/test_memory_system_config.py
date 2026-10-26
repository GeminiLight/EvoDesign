"""User memory configuration wiring tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeDocument:
    def __init__(self, page_content, metadata):
        self.page_content = page_content
        self.metadata = metadata


class _RecordingCollection:
    def __init__(self, search_results=None, get_result=None):
        self.added_documents = []
        self.added_ids = []
        self.search_calls = []
        self._search_results = search_results or []
        self._get_result = get_result or {"ids": [], "documents": [], "metadatas": []}

    def add_documents(self, documents, *, ids):
        self.added_documents.extend(documents)
        self.added_ids.extend(ids)

    def similarity_search(self, *, query, k, filter=None):
        self.search_calls.append({"query": query, "k": k, "filter": filter})
        return self._search_results[:k]

    def get(self, **kwargs):
        return self._get_result


def test_user_memory_system_passes_memory_db_path_to_storage(tmp_path, monkeypatch):
    import evo_diagram.user_memory.main as memory_main

    captured = {}

    class FakeStorage:
        def __init__(
            self,
            *,
            user_id,
            vector_db_path=None,
            allow_in_memory_fallback=False,
        ):
            captured["user_id"] = user_id
            captured["vector_db_path"] = vector_db_path
            captured["allow_in_memory_fallback"] = allow_in_memory_fallback

    monkeypatch.setattr(memory_main, "Mem0PreferenceStorage", FakeStorage)

    memory_db_path = str(tmp_path / "user-memory")
    memory_main.UserPreferenceMemorySystem(
        user_id="alice",
        memory_db_path=memory_db_path,
    )

    assert captured == {
        "user_id": "alice",
        "vector_db_path": memory_db_path,
        "allow_in_memory_fallback": False,
    }


def test_user_memory_system_retrieve_path_does_not_initialize_learning_layers(
    tmp_path, monkeypatch
):
    import evo_diagram.user_memory.main as memory_main

    captured = {}

    class FakeStorage:
        def __init__(
            self,
            *,
            user_id,
            vector_db_path=None,
            allow_in_memory_fallback=False,
        ):
            captured["user_id"] = user_id
            captured["vector_db_path"] = vector_db_path

        def retrieve_preferences(self, **kwargs):
            captured["retrieve_kwargs"] = kwargs
            return [{"memory": "prefer compact diagrams", "metadata": {}}]

    class FailingVLMImageObserver:
        def __init__(self):
            raise AssertionError("VLM should not be initialized for retrieve-only")

    class FailingPreferenceAgent:
        def __init__(self, model):
            raise AssertionError("LLM preference agent should not be initialized")

    class FailingLLMFactory:
        @classmethod
        def create_for_role(cls, *args, **kwargs):
            raise AssertionError("LLM should not be created for retrieve-only")

    monkeypatch.setattr(memory_main, "Mem0PreferenceStorage", FakeStorage)
    monkeypatch.setattr(memory_main, "VLMImageObserver", FailingVLMImageObserver)
    monkeypatch.setattr(memory_main, "LLMPreferenceExtractionAgent", FailingPreferenceAgent)
    monkeypatch.setattr(memory_main, "LLMFactory", FailingLLMFactory)

    system = memory_main.UserPreferenceMemorySystem(
        user_id="alice",
        memory_db_path=str(tmp_path / "user-memory"),
    )
    results = system.retrieve_preferences(query="compact diagrams")

    assert results == [{"memory": "prefer compact diagrams", "metadata": {}}]
    assert captured["retrieve_kwargs"]["query"] == "compact diagrams"


def test_user_memory_cli_passes_memory_db_path_for_retrieve(tmp_path, monkeypatch):
    import sys
    import evo_diagram.user_memory.main as memory_main

    captured = {}

    class FakeUserPreferenceMemorySystem:
        def __init__(self, *, user_id, memory_db_path=None):
            captured["user_id"] = user_id
            captured["memory_db_path"] = memory_db_path

        def retrieve_preferences(self, **kwargs):
            captured["retrieve_kwargs"] = kwargs
            return []

    memory_db_path = str(tmp_path / "user-memory")
    monkeypatch.setattr(memory_main, "UserPreferenceMemorySystem", FakeUserPreferenceMemorySystem)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "user-memory",
            "--mode",
            "retrieve",
            "--query",
            "minimal diagrams",
            "--user-id",
            "alice",
            "--memory-db-path",
            memory_db_path,
        ],
    )

    memory_main.main()

    assert captured["user_id"] == "alice"
    assert captured["memory_db_path"] == memory_db_path
    assert captured["retrieve_kwargs"]["query"] == "minimal diagrams"


def test_user_memory_cli_learn_requires_input_files(monkeypatch):
    import sys
    import pytest
    import evo_diagram.user_memory.main as memory_main

    monkeypatch.setattr(sys, "argv", ["user-memory", "--mode", "learn"])

    with pytest.raises(SystemExit) as exc_info:
        memory_main.main()

    assert exc_info.value.code == 2


def test_mem0_storage_init_failure_raises_by_default(tmp_path, monkeypatch):
    import pytest
    import evo_diagram.user_memory.storage.mem0_storage as mem0_storage

    def fail_embeddings(*args, **kwargs):
        raise ValueError("embedding model unavailable")

    monkeypatch.setattr(mem0_storage, "HuggingFaceEmbeddings", fail_embeddings)

    with pytest.raises(RuntimeError, match="Failed to initialize persistent user preference storage"):
        mem0_storage.Mem0PreferenceStorage(
            user_id="alice",
            vector_db_path=str(tmp_path / "user-memory"),
            embedding_model_name="fake-embedding-model",
        )


def test_mem0_storage_init_failure_falls_back_only_when_explicitly_allowed(
    tmp_path, monkeypatch
):
    import evo_diagram.user_memory.storage.mem0_storage as mem0_storage

    def fail_embeddings(*args, **kwargs):
        raise ValueError("embedding model unavailable")

    monkeypatch.setattr(mem0_storage, "HuggingFaceEmbeddings", fail_embeddings)

    storage = mem0_storage.Mem0PreferenceStorage(
        user_id="alice",
        vector_db_path=str(tmp_path / "user-memory"),
        embedding_model_name="fake-embedding-model",
        allow_in_memory_fallback=True,
    )

    assert storage.initialized is False
    memory_id = storage._add_memory(
        "prefer compact diagrams",
        {"user_id": "alice", "layer": "semantic_preference"},
    )
    assert storage.retrieve_preferences("compact", layer="semantic_preference") == [
        {
            "id": memory_id,
            "memory": "prefer compact diagrams",
            "metadata": {
                "user_id": "alice",
                "layer": "semantic_preference",
                "memory_id": memory_id,
            },
        }
    ]


def test_mem0_storage_uses_same_memory_id_for_chroma_and_result(monkeypatch):
    import evo_diagram.user_memory.storage.mem0_storage as mem0_storage

    collection = _RecordingCollection()
    storage = object.__new__(mem0_storage.Mem0PreferenceStorage)
    storage.initialized = True
    storage.allow_in_memory_fallback = False
    storage.preferences_collection = collection
    storage.observations_collection = _RecordingCollection()
    storage.memory_fallback = []

    monkeypatch.setattr(mem0_storage, "Document", _FakeDocument)

    memory_id = storage._add_memory(
        "prefer compact diagrams",
        {"user_id": "alice", "layer": "semantic_preference"},
    )
    collection._search_results = collection.added_documents

    assert collection.added_ids == [memory_id]
    assert collection.added_documents[0].metadata["memory_id"] == memory_id
    assert storage._search_preferences("compact", {"user_id": "alice"}) == [
        {
            "id": memory_id,
            "memory": "prefer compact diagrams",
            "metadata": {
                "user_id": "alice",
                "layer": "semantic_preference",
                "memory_id": memory_id,
            },
        }
    ]


def test_mem0_storage_pushes_confidence_filter_into_vector_search():
    from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage

    collection = _RecordingCollection()
    storage = object.__new__(Mem0PreferenceStorage)
    storage.initialized = True
    storage.allow_in_memory_fallback = False
    storage.user_id = "alice"
    storage.preferences_collection = collection

    assert storage.retrieve_preferences(
        "compact",
        min_confidence=0.7,
        layer="semantic_preference",
    ) == []
    assert collection.search_calls[0]["filter"] == {
        "$and": [
            {"user_id": "alice"},
            {"layer": "semantic_preference"},
            {"confidence": {"$gte": 0.7}},
        ]
    }


def test_mem0_storage_retrieves_preferences_by_task_context_when_applies_to_missing(
    tmp_path, monkeypatch
):
    import evo_diagram.user_memory.storage.mem0_storage as mem0_storage

    def fail_embeddings(*args, **kwargs):
        raise ValueError("embedding model unavailable")

    monkeypatch.setattr(mem0_storage, "HuggingFaceEmbeddings", fail_embeddings)

    storage = mem0_storage.Mem0PreferenceStorage(
        user_id="alice",
        vector_db_path=str(tmp_path / "user-memory"),
        embedding_model_name="fake-embedding-model",
        allow_in_memory_fallback=True,
    )
    storage._add_memory(
        "prefer swimlane diagrams for operating procedures",
        {
            "user_id": "alice",
            "layer": "semantic_preference",
            "agent_category": "Structure",
            "task_diagram_type": "swimlane",
            "task_content_area": "Operations",
            "confidence": 0.9,
        },
    )

    results = storage.retrieve_preferences(
        "operating procedure",
        agent_category="Structure",
        diagram_type="swimlane",
        content_area="Operations",
        min_confidence=0.7,
        layer="semantic_preference",
    )

    assert [r["memory"] for r in results] == [
        "prefer swimlane diagrams for operating procedures"
    ]


def test_mem0_storage_fallback_search_is_lexically_ranked_and_scoped():
    from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage

    storage = object.__new__(Mem0PreferenceStorage)
    storage.initialized = False
    storage.allow_in_memory_fallback = True
    storage.user_id = "alice"
    storage.memory_fallback = []

    storage._add_memory(
        "prefer spacious diagrams",
        {
            "user_id": "alice",
            "layer": "semantic_preference",
            "confidence": 0.9,
        },
    )
    compact_id = storage._add_memory(
        "prefer compact diagrams for authentication modules",
        {
            "user_id": "alice",
            "layer": "semantic_preference",
            "confidence": 0.8,
        },
    )
    storage._add_memory(
        "prefer compact diagrams",
        {
            "user_id": "bob",
            "layer": "semantic_preference",
            "confidence": 0.95,
        },
    )

    results = storage.retrieve_preferences(
        "compact auth module",
        layer="semantic_preference",
        top_k=1,
    )

    assert [r["id"] for r in results] == [compact_id]
    assert storage.retrieve_preferences(
        "radial hierarchy",
        layer="semantic_preference",
    ) == []


def test_mem0_storage_fallback_confidence_filter_is_numeric():
    from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage

    storage = object.__new__(Mem0PreferenceStorage)
    storage.initialized = False
    storage.allow_in_memory_fallback = True
    storage.user_id = "alice"
    storage.memory_fallback = []

    high_id = storage._add_memory(
        "prefer compact diagrams",
        {
            "user_id": "alice",
            "layer": "semantic_preference",
            "confidence": "0.9",
        },
    )
    storage._add_memory(
        "prefer spacious diagrams",
        {
            "user_id": "alice",
            "layer": "semantic_preference",
            "confidence": "not-a-number",
        },
    )

    results = storage.retrieve_preferences(
        "compact spacious",
        layer="semantic_preference",
        min_confidence=0.7,
    )

    assert [r["id"] for r in results] == [high_id]


def _write_manifest(tmp_path, name: str) -> str:
    path = tmp_path / name
    path.write_text('{"shapes": []}', encoding="utf-8")
    return str(path)


def _visual_observation():
    from evo_diagram.user_memory.schemas.observation_schemas import (
        CategoryObservation,
        VisualObservation,
    )

    category = CategoryObservation(
        description="No visible preference",
        magnitude="minor",
        affected_properties=[],
    )
    return VisualObservation(
        structural_changes=category,
        styling_changes=category,
        layout_changes=category,
        semantic_changes=category,
        overall_intent="No clear preference",
    )


def test_mem0_storage_rejects_failed_or_empty_extraction_results():
    import pytest
    from evo_diagram.user_memory.schemas.diff_schemas import GuidedDiff
    from evo_diagram.user_memory.schemas.semantic_preference_schemas import (
        PreferenceExtractionResult,
    )
    from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage

    storage = object.__new__(Mem0PreferenceStorage)
    observation = _visual_observation()
    diff = GuidedDiff(visual_observation=observation)

    with pytest.raises(ValueError, match="status 'failed'"):
        storage.store_preferences(
            visual_observation=observation,
            guided_diff=diff,
            extraction_result=PreferenceExtractionResult(status="failed"),
            session_id="session-1",
        )

    with pytest.raises(ValueError, match="empty result"):
        storage.store_preferences(
            visual_observation=observation,
            guided_diff=diff,
            extraction_result=PreferenceExtractionResult(status="succeeded"),
            session_id="session-1",
        )


def test_get_all_preferences_fallback_returns_only_semantic_preferences():
    from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage

    storage = object.__new__(Mem0PreferenceStorage)
    storage.initialized = False
    storage.allow_in_memory_fallback = True
    storage.user_id = "alice"
    storage.memory_fallback = [
        {
            "id": "pref-1",
            "content": "prefer compact diagrams",
            "metadata": {
                "memory_id": "pref-1",
                "user_id": "alice",
                "layer": "semantic_preference",
            },
        },
        {
            "content": "User Intent: unclear",
            "metadata": {
                "user_id": "alice",
                "layer": "vlm_observation",
            },
        },
        {
            "content": "prefer spacious diagrams",
            "metadata": {
                "user_id": "bob",
                "layer": "semantic_preference",
            },
        },
    ]

    assert storage.get_all_preferences() == [
        {
            "id": "pref-1",
            "memory": "prefer compact diagrams",
            "metadata": {
                "memory_id": "pref-1",
                "user_id": "alice",
                "layer": "semantic_preference",
            },
        }
    ]


def _install_learning_fakes(
    monkeypatch,
    *,
    extraction_status: str,
    with_preference: bool = False,
):
    import evo_diagram.user_memory.main as memory_main
    from evo_diagram.user_memory.schemas.diff_schemas import GuidedDiff
    from evo_diagram.user_memory.schemas.semantic_preference_schemas import (
        PreferenceExtractionResult,
        SemanticPreference,
    )

    captured = {}

    class FakeStorage:
        def __init__(self, **kwargs):
            captured["storage_init"] = kwargs

        def store_preferences(self, **kwargs):
            captured["stored_extraction"] = kwargs["extraction_result"]

    class FakeVLMImageObserver:
        def observe_differences(self, **kwargs):
            captured["vlm_kwargs"] = kwargs
            return _visual_observation()

    class FakeDiffExtractor:
        def extract_diff(self, *, visual_observation, **_kwargs):
            return GuidedDiff(visual_observation=visual_observation)

    class FakePreferenceAgent:
        def __init__(self, model):
            captured["preference_agent_model"] = model

        def extract_preferences(self, *, task_context, **_kwargs):
            captured["task_context"] = task_context
            preferences = []
            if with_preference:
                preferences = [
                    SemanticPreference(
                        preference_text="Prefer compact auth module grouping",
                        agent_category="Structure",
                        applies_to={"diagram_type": "class"},
                        confidence=0.9,
                        design_rationale="Grouping clarifies module boundaries",
                        evidence_summary="User grouped authentication nodes",
                    )
                ]
            return PreferenceExtractionResult(
                status=extraction_status,
                preferences=preferences,
                filtered_count=0,
                task_context=task_context,
                errors=["RuntimeError: model unavailable"]
                if extraction_status == "failed"
                else [],
            )

    class FakeLLMFactory:
        @classmethod
        def create_for_role(cls, *args, **kwargs):
            captured["llm_args"] = (args, kwargs)
            return "fake-llm"

    monkeypatch.setattr(memory_main, "Mem0PreferenceStorage", FakeStorage)
    monkeypatch.setattr(memory_main, "VLMImageObserver", FakeVLMImageObserver)
    monkeypatch.setattr(memory_main, "EnhancedDiffExtractor", FakeDiffExtractor)
    monkeypatch.setattr(memory_main, "LLMPreferenceExtractionAgent", FakePreferenceAgent)
    monkeypatch.setattr(memory_main, "LLMFactory", FakeLLMFactory)
    return captured


def test_learn_from_edit_returns_no_preferences_status_and_skips_storage(
    tmp_path, monkeypatch
):
    import evo_diagram.user_memory.main as memory_main

    captured = _install_learning_fakes(monkeypatch, extraction_status="no_preferences")
    system = memory_main.UserPreferenceMemorySystem(user_id="alice")

    result = system.learn_from_edit(
        task_json={
            "id": "task-1",
            "content": "Draw auth",
            "query": "show auth module",
            "diagram_type": "class",
            "content_area": "Software Engineering",
            "vertical_domain": "backend",
        },
        model_manifest_path=_write_manifest(tmp_path, "model.json"),
        model_image_path=str(tmp_path / "model.png"),
        user_manifest_path=_write_manifest(tmp_path, "user.json"),
        user_image_path=str(tmp_path / "user.png"),
        session_id="session-1",
    )

    assert result["status"] == "no_preferences"
    assert result["task_context"]["query"] == "show auth module"
    assert result["task_context"]["vertical_domain"] == "backend"
    assert captured["task_context"] == result["task_context"]
    assert "stored_extraction" not in captured


def test_learn_from_edit_stores_successful_semantic_preferences(
    tmp_path, monkeypatch
):
    import evo_diagram.user_memory.main as memory_main

    captured = _install_learning_fakes(
        monkeypatch,
        extraction_status="succeeded",
        with_preference=True,
    )
    system = memory_main.UserPreferenceMemorySystem(user_id="alice")

    result = system.learn_from_edit(
        task_json={
            "content": "Draw auth",
            "diagram_type": "class",
        },
        model_manifest_path=_write_manifest(tmp_path, "model.json"),
        model_image_path=str(tmp_path / "model.png"),
        user_manifest_path=_write_manifest(tmp_path, "user.json"),
        user_image_path=str(tmp_path / "user.png"),
        session_id="session-1",
    )

    assert result["status"] == "stored_preferences"
    assert result["preferences"]["extracted"] == 1
    assert captured["stored_extraction"].status == "succeeded"
    assert len(captured["stored_extraction"].preferences) == 1


def test_learn_from_edit_returns_failed_status_when_preference_extraction_fails(
    tmp_path, monkeypatch
):
    import evo_diagram.user_memory.main as memory_main

    captured = _install_learning_fakes(monkeypatch, extraction_status="failed")
    system = memory_main.UserPreferenceMemorySystem(user_id="alice")

    result = system.learn_from_edit(
        task_json={"content": "Draw auth"},
        model_manifest_path=_write_manifest(tmp_path, "model.json"),
        model_image_path=str(tmp_path / "model.png"),
        user_manifest_path=_write_manifest(tmp_path, "user.json"),
        user_image_path=str(tmp_path / "user.png"),
        session_id="session-1",
    )

    assert result["status"] == "failed"
    assert result["preferences"]["extraction_status"] == "failed"
    assert result["preferences"]["errors"] == ["RuntimeError: model unavailable"]
    assert "stored_extraction" not in captured


def test_learn_from_edit_stops_before_storage_when_diff_is_untrusted(
    tmp_path, monkeypatch
):
    import pytest
    import evo_diagram.user_memory.main as memory_main

    captured = {}

    class FakeStorage:
        def __init__(self, **kwargs):
            captured["storage_init"] = kwargs

        def store_preferences(self, **_kwargs):
            raise AssertionError("untrusted diffs must not be stored")

    class FakeVLMImageObserver:
        def observe_differences(self, **kwargs):
            captured["vlm_kwargs"] = kwargs
            return _visual_observation()

    class FailingDiffExtractor:
        def extract_diff(self, **_kwargs):
            raise ValueError("manifest format is unknown")

    class FailingPreferenceAgent:
        def __init__(self, model):
            raise AssertionError("preference agent should not initialize")

    class FailingLLMFactory:
        @classmethod
        def create_for_role(cls, *args, **kwargs):
            raise AssertionError("LLM should not initialize")

    monkeypatch.setattr(memory_main, "Mem0PreferenceStorage", FakeStorage)
    monkeypatch.setattr(memory_main, "VLMImageObserver", FakeVLMImageObserver)
    monkeypatch.setattr(memory_main, "EnhancedDiffExtractor", FailingDiffExtractor)
    monkeypatch.setattr(memory_main, "LLMPreferenceExtractionAgent", FailingPreferenceAgent)
    monkeypatch.setattr(memory_main, "LLMFactory", FailingLLMFactory)

    system = memory_main.UserPreferenceMemorySystem(user_id="alice")

    with pytest.raises(ValueError, match="manifest format is unknown"):
        system.learn_from_edit(
            task_json={"content": "Draw auth"},
            model_manifest_path=_write_manifest(tmp_path, "model.json"),
            model_image_path=str(tmp_path / "model.png"),
            user_manifest_path=_write_manifest(tmp_path, "user.json"),
            user_image_path=str(tmp_path / "user.png"),
            session_id="session-1",
        )


def test_learn_from_edit_stops_before_storage_when_vlm_observation_fails(
    tmp_path, monkeypatch
):
    import pytest
    import evo_diagram.user_memory.main as memory_main

    captured = {}

    class FakeStorage:
        def __init__(self, **kwargs):
            captured["storage_init"] = kwargs

        def store_preferences(self, **_kwargs):
            raise AssertionError("failed VLM observations must not be stored")

    class FailingVLMImageObserver:
        def observe_differences(self, **kwargs):
            captured["vlm_kwargs"] = kwargs
            raise ValueError("bad VLM response")

    class FailingDiffExtractor:
        def extract_diff(self, **_kwargs):
            raise AssertionError("diff extraction should not run after VLM failure")

    class FailingPreferenceAgent:
        def __init__(self, model):
            raise AssertionError("preference agent should not initialize")

    class FailingLLMFactory:
        @classmethod
        def create_for_role(cls, *args, **kwargs):
            raise AssertionError("LLM should not initialize")

    monkeypatch.setattr(memory_main, "Mem0PreferenceStorage", FakeStorage)
    monkeypatch.setattr(memory_main, "VLMImageObserver", FailingVLMImageObserver)
    monkeypatch.setattr(memory_main, "EnhancedDiffExtractor", FailingDiffExtractor)
    monkeypatch.setattr(memory_main, "LLMPreferenceExtractionAgent", FailingPreferenceAgent)
    monkeypatch.setattr(memory_main, "LLMFactory", FailingLLMFactory)

    system = memory_main.UserPreferenceMemorySystem(user_id="alice")

    with pytest.raises(ValueError, match="bad VLM response"):
        system.learn_from_edit(
            task_json={"content": "Draw auth"},
            model_manifest_path=_write_manifest(tmp_path, "model.json"),
            model_image_path=str(tmp_path / "model.png"),
            user_manifest_path=_write_manifest(tmp_path, "user.json"),
            user_image_path=str(tmp_path / "user.png"),
            session_id="session-1",
        )

    assert captured["vlm_kwargs"]["task_description"] == "Draw auth"


# ── applies_to normalisation (LLM-authored, unconstrained values) ────────


def _semantic_preference(applies_to):
    from evo_diagram.user_memory.schemas.semantic_preference_schemas import (
        SemanticPreference,
    )

    return SemanticPreference(
        preference_text="prefer red entity nodes",
        agent_category="Styling",
        applies_to=applies_to,
        confidence=0.9,
        design_rationale="R",
        evidence_summary="E",
    )


def _fallback_storage(user_id="alice"):
    from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage

    storage = object.__new__(Mem0PreferenceStorage)
    storage.initialized = False
    storage.allow_in_memory_fallback = True
    storage.user_id = user_id
    storage.memory_fallback = []
    return storage


def test_applies_to_list_values_stay_retrievable_per_diagram_type():
    """``applies_to`` is ``Dict[str, Any]`` filled by the LLM.

    ``str(["class", "sequence"])`` stored the literal ``"['class',
    'sequence']"``, which the equality filter could never match for a single
    diagram type, so those preferences were unreachable.
    """
    storage = _fallback_storage()
    storage._store_semantic_preference(
        _semantic_preference({
            "diagram_type": ["class", "sequence"],
            "content_area": "Software Engineering",
        }),
        session_id="s1",
        task_context={},
    )

    metadata = storage.memory_fallback[0]["metadata"]
    assert metadata["applies_to_diagram_type"] == "class"
    assert metadata["applies_to_diagram_type_class"] is True
    assert metadata["applies_to_diagram_type_sequence"] is True
    assert metadata["applies_to_content_area"] == "software engineering"

    for diagram_type in ("class", "sequence", "Sequence"):
        assert [
            r["memory"]
            for r in storage.retrieve_preferences(
                "red entity nodes",
                diagram_type=diagram_type,
                layer="semantic_preference",
            )
        ] == ["prefer red entity nodes"]


def test_applies_to_retrieval_is_case_insensitive():
    storage = _fallback_storage()
    storage._store_semantic_preference(
        _semantic_preference({"diagram_type": "Class", "content_area": "Software Engineering"}),
        session_id="s1",
        task_context={"diagram_type": "Class"},
    )

    assert storage.memory_fallback[0]["metadata"]["applies_to_diagram_type"] == "class"
    assert [
        r["memory"]
        for r in storage.retrieve_preferences(
            "red entity nodes",
            diagram_type="class",
            content_area="software engineering",
            layer="semantic_preference",
        )
    ] == ["prefer red entity nodes"]


def test_applies_to_normalisation_keeps_unrelated_types_out():
    storage = _fallback_storage()
    storage._store_semantic_preference(
        _semantic_preference({"diagram_type": ["class", "sequence"]}),
        session_id="s1",
        task_context={},
    )

    assert storage.retrieve_preferences(
        "red entity nodes",
        diagram_type="swimlane",
        layer="semantic_preference",
    ) == []


def test_applies_to_empty_values_are_stored_as_empty_strings():
    storage = _fallback_storage()
    storage._store_semantic_preference(
        _semantic_preference({"diagram_type": [], "element_role": None}),
        session_id="s1",
        task_context={},
    )

    metadata = storage.memory_fallback[0]["metadata"]
    assert metadata["applies_to_diagram_type"] == ""
    assert metadata["applies_to_element_role"] == ""
