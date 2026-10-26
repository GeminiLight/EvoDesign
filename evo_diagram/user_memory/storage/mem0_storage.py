"""ChromaDB-based User Preference Storage - Layer 4 of the preference learning system.

This module stores semantic preferences using ChromaDB with HuggingFace embeddings,
following the same pattern as design_memory.
"""

import logging
import os
import re
import uuid
from typing import Dict, List, Optional, Any

from evo_diagram.config.settings import AppSettings
from ..schemas.diff_schemas import GuidedDiff
from ..schemas.observation_schemas import VisualObservation
from ..schemas.semantic_preference_schemas import (
    PreferenceExtractionResult,
    SemanticPreference,
)

logger = logging.getLogger(__name__)

Chroma: Any = None
HuggingFaceEmbeddings: Any = None
Document: Any = None


def _resolve_chroma_dependencies():
    global Chroma, HuggingFaceEmbeddings, Document

    if Chroma is None:
        from langchain_chroma import Chroma as ImportedChroma

        Chroma = ImportedChroma
    if HuggingFaceEmbeddings is None:
        from langchain_huggingface import (
            HuggingFaceEmbeddings as ImportedHuggingFaceEmbeddings,
        )

        HuggingFaceEmbeddings = ImportedHuggingFaceEmbeddings
    if Document is None:
        from langchain_core.documents import Document as ImportedDocument

        Document = ImportedDocument
    return Chroma, HuggingFaceEmbeddings, Document


class Mem0PreferenceStorage:
    """Store user preferences in ChromaDB with HuggingFace embeddings."""

    def __init__(
        self,
        user_id: str = "diagram_user_default",
        vector_db_path: str = None,
        embedding_model_name: str = None,
        allow_in_memory_fallback: bool = False,
    ):
        """Initialize ChromaDB storage.

        Args:
            user_id: User identifier for preference isolation
            vector_db_path: Path to persist ChromaDB data
            embedding_model_name: HuggingFace embedding model name
            allow_in_memory_fallback: Explicitly allow volatile in-memory
                fallback if persistent storage cannot be initialized or used.
        """
        self.user_id = user_id
        self.allow_in_memory_fallback = allow_in_memory_fallback

        settings = AppSettings.get_default()
        if vector_db_path is None:
            vector_db_path = settings.user_preference_memory_path
        if embedding_model_name is None:
            embedding_model_name = settings.user_preference_embedding_model

        self.vector_db_path = vector_db_path
        self.embedding_model_name = embedding_model_name
        self.memory_fallback = []

        logger.info(f"Initializing UserPreferenceStorage with ChromaDB and {embedding_model_name}...")

        try:
            chroma_cls, embeddings_cls, _document_cls = _resolve_chroma_dependencies()

            # Initialize HuggingFace embedding model
            self.embedding_function = embeddings_cls(model_name=embedding_model_name)

            # Initialize ChromaDB collections for different data types
            self.preferences_collection = chroma_cls(
                collection_name=f"user_preferences_{user_id}",
                persist_directory=vector_db_path,
                embedding_function=self.embedding_function,
            )

            self.observations_collection = chroma_cls(
                collection_name=f"user_observations_{user_id}",
                persist_directory=vector_db_path,
                embedding_function=self.embedding_function,
            )

            logger.info(f"ChromaDB initialized successfully at {vector_db_path}")
            self.initialized = True

        except Exception as e:
            message = (
                "Failed to initialize persistent user preference storage "
                f"at {vector_db_path!r} with embedding model {embedding_model_name!r}: {e}"
            )
            if not allow_in_memory_fallback:
                logger.error(message)
                raise RuntimeError(message) from e
            logger.warning("%s. Falling back to in-memory storage.", message)
            self.initialized = False

    def _prepare_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare metadata for ChromaDB (convert complex types to strings)."""
        prepared = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                prepared[key] = value
            elif value is None:
                prepared[key] = ""
            else:
                prepared[key] = str(value)
        return prepared

    def store_preferences(
        self,
        visual_observation: VisualObservation,
        guided_diff: GuidedDiff,
        extraction_result: PreferenceExtractionResult,
        session_id: str,
    ):
        """Store semantic preferences extracted by LLM.

        Args:
            visual_observation: VLM observation from Layer 1
            guided_diff: VLM-guided diff from Layer 2
            extraction_result: LLM-extracted preferences from Layer 3
            session_id: Session identifier for tracking
        """
        if extraction_result.status != "succeeded":
            raise ValueError(
                "Cannot store user preferences from extraction result with "
                f"status {extraction_result.status!r}."
            )
        if not extraction_result.preferences:
            raise ValueError("Cannot store user preferences from an empty result.")

        logger.info(f"Storing preferences for session {session_id}")

        # Layer 1: Store VLM observation (high-level understanding)
        self._store_vlm_observation(visual_observation, session_id)

        # Layer 2: Store JSON diff metadata
        self._store_diff_metadata(guided_diff, session_id)

        # Layer 3: Store semantic preferences (LLM-extracted)
        for pref in extraction_result.preferences:
            self._store_semantic_preference(pref, session_id, extraction_result.task_context)

        logger.info(
            f"Stored {len(extraction_result.preferences)} semantic preferences "
            f"(filtered {extraction_result.filtered_count} low-confidence)"
        )

    def _store_vlm_observation(
        self, observation: VisualObservation, session_id: str
    ):
        """Store high-level VLM observation."""
        content = f"User Intent: {observation.overall_intent}"

        metadata = {
            "layer": "vlm_observation",
            "session_id": session_id,
            "user_id": self.user_id,
            "structural_magnitude": observation.structural_changes.magnitude,
            "styling_magnitude": observation.styling_changes.magnitude,
            "layout_magnitude": observation.layout_changes.magnitude,
            "semantic_magnitude": observation.semantic_changes.magnitude,
        }

        self._add_memory(content, metadata, collection="observations")

    def _store_diff_metadata(self, guided_diff: GuidedDiff, session_id: str):
        """Store JSON diff metadata."""
        content = (
            f"Session {session_id}: User made {len(guided_diff.modifications)} modifications, "
            f"{len(guided_diff.additions)} additions, {len(guided_diff.deletions)} deletions."
        )

        metadata = {
            "layer": "json_diff_metadata",
            "session_id": session_id,
            "user_id": self.user_id,
            "num_additions": len(guided_diff.additions),
            "num_deletions": len(guided_diff.deletions),
            "num_modifications": len(guided_diff.modifications),
        }

        self._add_memory(content, metadata, collection="observations")

    @staticmethod
    def _context_slug(value: Any) -> str:
        """Lower-cased, whitespace-collapsed form used for exact-match filters."""
        return " ".join(str(value).strip().lower().split())

    @staticmethod
    def _flag_key(prefix: str, key: str, value: Any) -> str:
        """Boolean-flag metadata key for one value of a multi-valued context."""
        slug = Mem0PreferenceStorage._context_slug(value).replace(" ", "_")
        return f"{prefix}_{key}_{slug}"

    @classmethod
    def _normalize_context_metadata(
        cls, context: Dict[str, Any], prefix: str
    ) -> Dict[str, Any]:
        """Flatten an LLM-authored context dict into filterable metadata.

        ``SemanticPreference.applies_to`` is typed ``Dict[str, Any]`` and the
        values come straight from the model, so ``diagram_type`` may arrive as
        ``"class"`` or as ``["class", "sequence"]``. Storing ``str(value)``
        turned the list into the literal string ``"['class', 'sequence']"``,
        which the equality filter in :meth:`retrieve_preferences` could never
        match for a single diagram type.

        Each key therefore yields:

        - ``<prefix>_<key>`` — the primary value, lower-cased (the first element
          for a sequence), so exact-match filters keep working;
        - ``<prefix>_<key>_<value>`` → ``True`` for every value of a sequence,
          so multi-valued contexts stay matchable on their non-primary values.
        """
        normalized: Dict[str, Any] = {}
        for key, value in context.items():
            if isinstance(value, (list, tuple, set)):
                values = [item for item in value if item is not None and item != ""]
                if not values:
                    normalized[f"{prefix}_{key}"] = ""
                    continue
                normalized[f"{prefix}_{key}"] = cls._context_slug(values[0])
                for item in values:
                    normalized[cls._flag_key(prefix, key, item)] = True
                continue
            if value is None or value == "":
                normalized[f"{prefix}_{key}"] = ""
                continue
            if isinstance(value, dict):
                # Nothing sensible to match on; keep it readable for auditing.
                normalized[f"{prefix}_{key}"] = cls._context_slug(value)
                continue
            normalized[f"{prefix}_{key}"] = cls._context_slug(value)
        return normalized

    def _store_semantic_preference(
        self, pref: SemanticPreference, session_id: str, task_context: Dict
    ):
        """Store semantic preference extracted by LLM."""
        # Use preference_text as memory content
        content = pref.preference_text

        # Build rich metadata for filtering during retrieval
        metadata = {
            "layer": "semantic_preference",
            "agent_category": pref.agent_category,
            "session_id": session_id,
            "user_id": self.user_id,
            "confidence": pref.confidence,
            "design_rationale": pref.design_rationale,
            "evidence_summary": pref.evidence_summary,
        }

        # Add applies_to context
        if pref.applies_to:
            metadata.update(
                self._normalize_context_metadata(pref.applies_to, "applies_to")
            )

        # Add task context
        if task_context:
            metadata.update(
                self._normalize_context_metadata(task_context, "task")
            )

        self._add_memory(content, metadata, collection="preferences")
        logger.debug(
            f"Stored {pref.agent_category} preference (confidence={pref.confidence:.2f}): "
            f"{pref.preference_text[:80]}..."
        )

    def retrieve_preferences(
        self,
        query: str,
        agent_category: Optional[str] = None,
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
        min_confidence: float = 0.0,
        layer: Optional[str] = None,
        top_k: int = 5,
    ) -> List[dict]:
        """Retrieve semantic preferences with filtering.

        Args:
            query: Natural language search query
            agent_category: Filter by agent category (Structure, Styling, Layout)
            diagram_type: Filter by diagram type (e.g., "class", "dataflow")
            content_area: Filter by content area (e.g., "Software Engineering")
            min_confidence: Minimum confidence threshold (0.0-1.0)
            layer: Filter by layer (vlm_observation, semantic_preference)
            top_k: Number of results to return

        Returns:
            List of memory dictionaries with content and metadata
        """
        # Build a single filter expression for ChromaDB and the in-memory
        # fallback. Learned preferences may carry either explicit applies_to_*
        # metadata or the original task_* context; both are valid retrieval
        # scopes for a new task.
        filter_terms: List[dict] = [{"user_id": self.user_id}]
        if agent_category:
            filter_terms.append({"agent_category": agent_category})
        if diagram_type:
            filter_terms.append(self._context_filter("diagram_type", diagram_type))
        if content_area:
            filter_terms.append(self._context_filter("content_area", content_area))
        if layer:
            filter_terms.append({"layer": layer})
        if min_confidence > 0.0:
            filter_terms.append({"confidence": {"$gte": float(min_confidence)}})

        results = self._search_preferences(
            query,
            self._combine_filter_terms(filter_terms),
            top_k,
        )

        return results

    @classmethod
    def _context_filter(cls, key: str, value: str) -> dict:
        """Match one context value against applies_to_* and task_* metadata.

        Writes are normalised by :meth:`_normalize_context_metadata` (lower
        case, plus per-value boolean flags for multi-valued contexts), so the
        query side must lower-case too. The raw value is kept in the ``$or`` as
        well, so rows written before normalisation still match.
        """
        slug = cls._context_slug(value)
        terms = [
            {f"applies_to_{key}": slug},
            {f"task_{key}": slug},
            {cls._flag_key("applies_to", key, value): True},
            {cls._flag_key("task", key, value): True},
        ]
        if value != slug:
            terms.extend([
                {f"applies_to_{key}": value},
                {f"task_{key}": value},
            ])
        return {"$or": terms}

    def _add_memory(self, content: str, metadata: dict, collection: str = "preferences"):
        """Add memory to ChromaDB."""
        memory_id = str(uuid.uuid4())
        metadata_with_id = dict(metadata)
        metadata_with_id["memory_id"] = memory_id
        if self.initialized:
            try:
                prepared_metadata = self._prepare_metadata(metadata_with_id)
                document_cls = Document
                if document_cls is None:
                    _, _, document_cls = _resolve_chroma_dependencies()
                doc = document_cls(page_content=content, metadata=prepared_metadata)

                if collection == "preferences":
                    self.preferences_collection.add_documents([doc], ids=[memory_id])
                else:
                    self.observations_collection.add_documents([doc], ids=[memory_id])
                return memory_id

            except Exception as e:
                logger.error(f"Failed to add memory to ChromaDB: {e}")
                if not self.allow_in_memory_fallback:
                    raise RuntimeError("Failed to persist user preference memory") from e
                self.memory_fallback.append({
                    "id": memory_id,
                    "content": content,
                    "metadata": metadata_with_id,
                })
                return memory_id
        else:
            if not self.allow_in_memory_fallback:
                raise RuntimeError("Persistent user preference storage is not initialized")
            self.memory_fallback.append({
                "id": memory_id,
                "content": content,
                "metadata": metadata_with_id,
            })
            return memory_id

    def _combine_filter_terms(self, terms: List[dict]) -> dict:
        if not terms:
            return {}
        if len(terms) == 1:
            return terms[0]
        return {"$and": terms}

    def _search_preferences(
        self, query: str, where_filter: dict, top_k: int = 5
    ) -> List[dict]:
        """Search preferences in ChromaDB."""
        if self.initialized:
            try:
                # Use similarity search with filter
                results = self.preferences_collection.similarity_search(
                    query=query,
                    k=top_k,
                    filter=where_filter or None,
                )

                # Convert to standard format
                return [
                    {
                        "id": doc.metadata.get("memory_id", ""),
                        "memory": doc.page_content,
                        "metadata": doc.metadata,
                    }
                    for doc in results
                ]
            except Exception as e:
                logger.error(f"Failed to search ChromaDB: {e}")
                if not self.allow_in_memory_fallback:
                    raise RuntimeError("Failed to search persistent user preference storage") from e
                return self._fallback_search(query, where_filter, top_k)
        else:
            if not self.allow_in_memory_fallback:
                raise RuntimeError("Persistent user preference storage is not initialized")
            return self._fallback_search(query, where_filter, top_k)

    def _fallback_search(
        self, query: str, filters: dict, top_k: int
    ) -> List[dict]:
        """Fallback search in in-memory storage."""
        query_tokens = self._tokenize(query)
        ranked_results = []
        for order, mem in enumerate(self.memory_fallback):
            metadata = mem.get("metadata", {})
            if not self._metadata_matches_filter(metadata, filters):
                continue

            content = mem.get("content", "")
            score = len(query_tokens & self._tokenize(content)) if query_tokens else 0
            if query_tokens and score <= 0:
                continue
            ranked_results.append(
                (
                    -score,
                    order,
                    {
                        "id": mem.get("id") or metadata.get("memory_id", ""),
                        "memory": content,
                        "metadata": metadata,
                    },
                )
            )

        ranked_results.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in ranked_results[:top_k]]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        text = text or ""
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        tokens.update(re.findall(r"[\u4e00-\u9fff]+", text))
        tokens.update(re.findall(r"[\u4e00-\u9fff]", text))
        return tokens

    def _metadata_matches_filter(self, metadata: dict, filters: dict) -> bool:
        if not filters:
            return True
        for key, value in filters.items():
            if key == "$and":
                return all(self._metadata_matches_filter(metadata, item) for item in value)
            if key == "$or":
                return any(self._metadata_matches_filter(metadata, item) for item in value)
            if isinstance(value, dict):
                actual = metadata.get(key)
                if "$gte" in value:
                    try:
                        if float(actual) < float(value["$gte"]):
                            return False
                    except (TypeError, ValueError):
                        return False
                if "$lte" in value:
                    try:
                        if float(actual) > float(value["$lte"]):
                            return False
                    except (TypeError, ValueError):
                        return False
                continue
            if metadata.get(key) != value:
                return False
        return True

    def get_all_preferences(self, limit: int = 100) -> List[dict]:
        """Get all stored preferences for this user."""
        if self.initialized:
            try:
                results = self.preferences_collection.get(
                    where={"user_id": self.user_id},
                    limit=limit,
                )
                # Convert to standard format
                docs = []
                if results and results.get("documents"):
                    for i, doc in enumerate(results["documents"]):
                        metadata = results["metadatas"][i] if results.get("metadatas") else {}
                        result_ids = results.get("ids") or []
                        memory_id = metadata.get("memory_id") or (result_ids[i] if i < len(result_ids) else "")
                        docs.append({
                            "id": memory_id,
                            "memory": doc,
                            "metadata": metadata,
                        })
                return docs
            except Exception as e:
                logger.error(f"Failed to get preferences from ChromaDB: {e}")
                if not self.allow_in_memory_fallback:
                    raise RuntimeError("Failed to read persistent user preference storage") from e
                return []
        else:
            if not self.allow_in_memory_fallback:
                raise RuntimeError("Persistent user preference storage is not initialized")
            return [
                {
                    "id": m.get("id") or m.get("metadata", {}).get("memory_id", ""),
                    "memory": m.get("content", ""),
                    "metadata": m.get("metadata", {}),
                }
                for m in self.memory_fallback
                if m.get("metadata", {}).get("user_id") == self.user_id
                and m.get("metadata", {}).get("layer") == "semantic_preference"
            ]
