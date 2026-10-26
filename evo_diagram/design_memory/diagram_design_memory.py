from __future__ import annotations

import copy
import json
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set

from evo_diagram.config.settings import AppSettings

__all__ = [
    "DiagramDesignMemory",
    "VALID_LAYERS",
    "LAYER_ALIASES",
    "normalize_layer",
    "aliases_for_layer",
]

logger = logging.getLogger(__name__)

Chroma: Any = None
HuggingFaceEmbeddings: Any = None
Document: Any = None
filter_complex_metadata: Any = None

_EMBEDDING_CACHE: dict[tuple[Any, str], Any] = {}
_EMBEDDING_CACHE_LOCK = threading.Lock()


class _SharedEmbeddings:
    """Share model weights across private stores, serializing device inference."""

    def __init__(self, model: Any):
        self.model = model
        self.lock = threading.Lock()
        self._query_cache = ContextVar("design_memory_query_embeddings", default=None)

    @contextmanager
    def reuse_queries(self):
        """Reuse exact query vectors only within this retrieval, including nested calls."""
        if self._query_cache.get() is not None:
            yield
            return
        token = self._query_cache.set({})
        try:
            yield
        finally:
            self._query_cache.reset(token)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self.lock:
            return self.model.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        cache = self._query_cache.get()
        if cache is not None and text in cache:
            return list(cache[text])
        with self.lock:
            vector = self.model.embed_query(text)
        if cache is not None:
            cache[text] = tuple(vector)
        return vector


def _shared_embeddings(embeddings_cls: Any, model_name: str) -> _SharedEmbeddings:
    key = (embeddings_cls, model_name)
    with _EMBEDDING_CACHE_LOCK:
        if key not in _EMBEDDING_CACHE:
            _EMBEDDING_CACHE[key] = _SharedEmbeddings(embeddings_cls(
                model_name=model_name, encode_kwargs={"normalize_embeddings": True},
            ))
        return _EMBEDDING_CACHE[key]


def _resolve_chroma_dependencies():
    global Chroma, HuggingFaceEmbeddings, Document, filter_complex_metadata

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
    if filter_complex_metadata is None:
        from langchain_community.vectorstores.utils import (
            filter_complex_metadata as imported_filter_complex_metadata,
        )

        filter_complex_metadata = imported_filter_complex_metadata

    return Chroma, HuggingFaceEmbeddings, Document, filter_complex_metadata


def _document_class():
    if Document is None:
        _chroma_cls, _embeddings_cls, document_cls, _filter_metadata = (
            _resolve_chroma_dependencies()
        )
        return document_cls
    return Document


def _metadata_filter():
    if filter_complex_metadata is None:
        _chroma_cls, _embeddings_cls, _document_cls, filter_metadata = (
            _resolve_chroma_dependencies()
        )
        return filter_metadata
    return filter_complex_metadata

# Canonical layer names and their aliases. Single source of truth for layer
# normalisation across diagram_design_memory, retriever, and memory_workflow.
VALID_LAYERS = ("guideline", "principle", "samples", "strategy")
LAYER_ALIASES = {
    "guideline": "guideline", "guidelines": "guideline",
    "principle": "principle", "principles": "principle",
    "sample": "samples", "samples": "samples",
    "strategy": "strategy", "strategies": "strategy",
    "knowledge": "guideline",
}


def normalize_layer(name: str) -> str:
    """Map an alias (case/whitespace-insensitive) to a canonical layer name."""
    return LAYER_ALIASES.get(name.strip().lower(), name)


def aliases_for_layer(canonical: str) -> List[str]:
    """All alias names that resolve to ``canonical``, including itself."""
    return [alias for alias, target in LAYER_ALIASES.items() if target == canonical]


class DiagramDesignMemory:
    """
    Manages the persistent storage for design knowledge memory using LangChain's ChromaDB integration.
    Supports four types of knowledge: Guideline, Principle, Samples, Strategy.
    Each type has its own dedicated vector store with embedded SentenceTransformer integration.

    All collections are created with cosine distance and all embeddings are L2
    normalised, so ``doc.metadata['score']`` written by
    :meth:`search_design_item` is a genuine cosine similarity in ``[-1, 1]``
    (``[0, 1]`` in practice for sentence-transformer embeddings) and
    ``score_threshold`` is a cosine threshold. See
    :meth:`_check_distance_space_consistency` for why this is enforced rather
    than assumed.
    """
    _MODEL_META_KEY = "embedding_model_name"
    # Chroma's legacy metadata key for the HNSW distance function. LangChain
    # forwards ``collection_metadata`` to ``get_or_create_collection``, which
    # translates this into the collection's ``hnsw.space`` configuration.
    _DISTANCE_META_KEY = "hnsw:space"
    _DISTANCE_SPACE = "cosine"

    def __init__(self, vector_db_path=None, embedding_model_name=None):
        settings = AppSettings.get_default()
        if vector_db_path is None:
            vector_db_path = settings.design_memory_vector_db_path
        if embedding_model_name is None:
            embedding_model_name = settings.design_memory_embedding_model

        logger.info("Initializing DiagramDesignMemory with %s", embedding_model_name)
        self.vector_db_path = vector_db_path
        self.embedding_model_name = embedding_model_name
        self._lock = threading.Lock()

        chroma_cls, embeddings_cls, _document_cls, _filter_metadata = (
            _resolve_chroma_dependencies()
        )

        # L2-normalised embeddings + cosine space means cosine similarity,
        # cosine distance and (rescaled) euclidean distance all agree, and
        # LangChain's relevance score becomes ``1 - cosine_distance`` = the
        # cosine similarity itself.
        self.embedding_function = _shared_embeddings(embeddings_cls, embedding_model_name)

        collection_metadata = {self._DISTANCE_META_KEY: self._DISTANCE_SPACE}
        self.design_layers = {
            "guideline": {
                "vector_db": chroma_cls(
                    collection_name="guideline",
                    embedding_function=self.embedding_function,
                    persist_directory=f"{vector_db_path}/guideline",
                    collection_metadata=dict(collection_metadata),
                ),
                "collection_name": "guideline",
                "description": "Authoritative guidance for diagram design",
            },
            "principle": {
                "vector_db": chroma_cls(
                    collection_name="principle",
                    embedding_function=self.embedding_function,
                    persist_directory=f"{vector_db_path}/principle",
                    collection_metadata=dict(collection_metadata),
                ),
                "collection_name": "principle",
                "description": "Core design principles and best practices",
            },
            "samples": {
                "vector_db": chroma_cls(
                    collection_name="samples",
                    embedding_function=self.embedding_function,
                    persist_directory=f"{vector_db_path}/samples",
                    collection_metadata=dict(collection_metadata),
                ),
                "collection_name": "samples",
                "description": "Concrete examples illustrating design concepts",
            },
            "strategy": {
                "vector_db": chroma_cls(
                    collection_name="strategy",
                    embedding_function=self.embedding_function,
                    persist_directory=f"{vector_db_path}/strategy",
                    collection_metadata=dict(collection_metadata),
                ),
                "collection_name": "strategy",
                "description": "High-level strategies and workflows",
            },
        }
        self._check_distance_space_consistency()
        self._check_embedding_model_consistency()
        logger.info("DiagramDesignMemory initialized successfully.")

    # ── Distance-space enforcement ───────────────────────────────────────

    @staticmethod
    def _collection_distance_space(collection: Any) -> Optional[str]:
        """Best-effort read of a collection's configured HNSW/SPANN space.

        Returns ``None`` when the running ChromaDB does not expose it, so the
        caller can warn instead of failing on an unverifiable condition.
        """
        configuration = getattr(collection, "configuration", None)
        if isinstance(configuration, dict):
            for index_key in ("hnsw", "spann"):
                index_config = configuration.get(index_key)
                if isinstance(index_config, dict) and index_config.get("space"):
                    return str(index_config["space"])

        metadata = getattr(collection, "metadata", None)
        if isinstance(metadata, dict) and metadata.get(DiagramDesignMemory._DISTANCE_META_KEY):
            return str(metadata[DiagramDesignMemory._DISTANCE_META_KEY])
        return None

    def _check_distance_space_consistency(self) -> None:
        """Fail fast when a collection is not using cosine distance.

        ``collection_metadata`` only takes effect when the collection is
        *created*; reopening a collection that was created with the ChromaDB
        default (``l2``) silently keeps ``l2``, and LangChain then converts raw
        distances with ``_euclidean_relevance_score_fn`` (``1 - d/√2``). Since
        Chroma's l2 returns the *squared* distance, the value stored in
        ``doc.metadata['score']`` is then neither a cosine similarity nor
        bounded to ``[0, 1]``, and every ``score_threshold`` comparison in the
        retriever and engine becomes meaningless. There is no in-place
        migration: the distance function is fixed at creation time, so an
        affected collection must be rebuilt.
        """
        for layer_name, layer_config in self.design_layers.items():
            collection = getattr(layer_config["vector_db"], "_collection", None)
            if collection is None:
                continue
            space = self._collection_distance_space(collection)
            if space is None:
                logger.warning(
                    "Could not verify the distance metric of the %r collection; "
                    "relevance scores are only cosine similarities if it was "
                    "created with %r.",
                    layer_name,
                    self._DISTANCE_SPACE,
                )
                continue
            if space != self._DISTANCE_SPACE:
                try:
                    item_count = collection.count()
                except Exception:  # pragma: no cover - diagnostics only
                    item_count = "unknown"
                raise RuntimeError(
                    f"Design memory collection {layer_name!r} uses distance "
                    f"metric {space!r}, but cosine is required for relevance "
                    f"scores to be comparable ({item_count} items). ChromaDB "
                    "cannot change a collection's distance function in place: "
                    f"delete {self.vector_db_path}/{layer_name} and re-ingest "
                    "the layer."
                )

    # ── #2: Embedding model mismatch detection ───────────────────────────

    def _check_embedding_model_consistency(self) -> None:
        """Warn if stored vectors were created with a different embedding model."""
        for layer_name, layer_config in self.design_layers.items():
            try:
                collection = getattr(layer_config["vector_db"], "_collection", None)
                if collection is None:
                    continue
                stored_model = collection.metadata.get(self._MODEL_META_KEY) if collection.metadata else None
                if stored_model is None:
                    item_count = collection.count()
                    if item_count:
                        raise RuntimeError(
                            f"Embedding model metadata is missing on non-empty "
                            f"{layer_name!r} collection ({item_count} items). "
                            "Rebuild the vector DB before retrieval."
                        )
                    # First run on an empty collection — stamp the current model.
                    # ``modify`` replaces the metadata dict wholesale, but
                    # chromadb rejects any request carrying ``hnsw:*`` keys
                    # even when the value is unchanged ("Changing the distance
                    # function of a collection once it is created is not
                    # supported"). The distance space is already fixed at
                    # creation via ``collection_metadata``, so stamp only the
                    # embedding-model bookkeeping key.
                    new_metadata = {
                        key: value
                        for key, value in (collection.metadata or {}).items()
                        if not key.startswith("hnsw:")
                    }
                    new_metadata[self._MODEL_META_KEY] = self.embedding_model_name
                    collection.modify(metadata=new_metadata)
                    logger.info(
                        "Stamped embedding model '%s' on %s collection (no prior record).",
                        self.embedding_model_name, layer_name,
                    )
                elif stored_model != self.embedding_model_name:
                    raise RuntimeError(
                        f"Embedding model mismatch on {layer_name!r} collection: "
                        f"stored vectors were created with {stored_model!r}, "
                        f"but current model is {self.embedding_model_name!r}. "
                        "Rebuild the vector DB before retrieval."
                    )
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"Could not verify embedding model metadata for {layer_name}: {exc}"
                ) from exc

    # ── #3: Versioning helpers ───────────────────────────────────────────

    @staticmethod
    def _fetch_id_record(vector_db, candidate_id: str) -> Dict[str, Any]:
        """Read one ID with its metadata, tolerating stores without ``include``."""
        try:
            record = vector_db.get(ids=[candidate_id], include=["metadatas"])
        except TypeError:
            record = vector_db.get(ids=[candidate_id])
        return record or {}

    @classmethod
    def _id_is_free(
        cls,
        vector_db,
        candidate_id: str,
        reserved_ids: Set[str],
    ) -> bool:
        """Whether ``candidate_id`` may be claimed by a new document.

        An ID is free when nothing occupies it, or when everything occupying it
        has been archived (``active=False``). Archived rows are tombstones: they
        are skipped by every retrieval path and by the engine's DB seed, so
        letting them keep their base ID made re-derived knowledge land on
        ``guideline_h_v2``, ``_v3``, ... forever while the engine's content-hash
        collision check — which only ever produces the base ID — could never
        match them. Re-claiming the ID overwrites the tombstone with the live
        entry, which is the intended "this knowledge is back" semantics.
        """
        if candidate_id in reserved_ids:
            return False
        record = cls._fetch_id_record(vector_db, candidate_id)
        ids = record.get("ids") or []
        if not ids:
            return True
        metadatas = record.get("metadatas")
        if not isinstance(metadatas, list) or len(metadatas) != len(ids):
            # Cannot prove the occupants are archived — treat the ID as taken.
            return False
        return all(
            isinstance(meta, dict) and meta.get("active") is False
            for meta in metadatas
        )

    def _next_version_id(
        self,
        base_id: str,
        design_layer: str,
        reserved_ids: Optional[Set[str]] = None,
    ) -> str:
        """Return ``base_id`` if free, else ``base_id_v2``, ``_v3``, etc.

        Only *active* entries reserve an ID; see :meth:`_id_is_free`.
        """
        reserved_ids = reserved_ids or set()
        vector_db = self.design_layers[design_layer]["vector_db"]
        if self._id_is_free(vector_db, base_id, reserved_ids):
            return base_id
        # Find next available version
        version = 2
        while True:
            candidate = f"{base_id}_v{version}"
            if self._id_is_free(vector_db, candidate, reserved_ids):
                return candidate
            version += 1

    @staticmethod
    def _assign_document_id(doc, final_id: str):
        """Synchronize the vector-store ID across metadata and JSON payloads."""
        final_id = str(final_id)
        doc.id = final_id
        doc.metadata = dict(doc.metadata or {})
        doc.metadata["id"] = final_id

        original_json = doc.metadata.get("original_json_data")
        if original_json:
            try:
                original_data = json.loads(original_json)
            except (json.JSONDecodeError, TypeError) as exc:
                raise RuntimeError(
                    f"Cannot assign document id {final_id!r}: invalid original_json_data"
                ) from exc
            if not isinstance(original_data, dict):
                raise RuntimeError(
                    f"Cannot assign document id {final_id!r}: original_json_data must be an object"
                )
            original_data["id"] = final_id
            doc.metadata["original_json_data"] = json.dumps(original_data)

        content = None
        if isinstance(doc.page_content, str):
            try:
                content = json.loads(doc.page_content)
            except json.JSONDecodeError:
                content = None
        elif isinstance(doc.page_content, dict):
            content = copy.deepcopy(doc.page_content)

        if isinstance(content, dict):
            content["id"] = final_id
            doc.page_content = json.dumps(content)
        return doc

    def _normalize_design_layer(self, design_layer: str) -> str:
        """Normalize user-provided design_layer aliases to canonical keys."""
        return normalize_layer(design_layer)

    def get_vector_db(self, design_layer="guideline"):
        """
        Get a LangChain ChromaDB vector store for the specified knowledge type.

        Args:
            design_layer (str): Type of knowledge collection to retrieve ("guideline", "principle", "samples", "strategy")

        Returns:
            Chroma: LangChain ChromaDB vector store object
        """
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}")

        return self.design_layers[normalized_layer]["vector_db"]

    @staticmethod
    def _metadata_scalar(value: Any) -> Any:
        """Return a Chroma-compatible scalar value, or ``None`` if unsupported."""
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float):
            return value
        if isinstance(value, str):
            return value
        return None

    def _prepare_metadata_for_chromadb(self, metadata: Dict[str, Any], original_item_data: Dict[str, Any] = None, design_layer: str = "guideline"):
        """
        Prepare metadata for ChromaDB by converting lists and complex objects to individual boolean flags for compatibility.
        Also stores the full original item as a JSON string for future parsing.

        Args:
            metadata (dict): Original metadata dictionary (e.g., the 'tags' part of your item)
            original_item_data (dict): The complete original item for JSON storage

        Returns:
            dict: ChromaDB-compatible metadata with complex types converted to simple flags
        """
        prepared_metadata = {}

        # Store original JSON data if provided
        if original_item_data:
            prepared_metadata['original_json_data'] = json.dumps(original_item_data)

        original_item_data = original_item_data or {}

        # Copy basic metadata fields directly from the provided 'metadata' (which is usually the 'tags' dict)
        for key, value in metadata.items():
            if not isinstance(value, (list, dict)):
                prepared_metadata[key] = value

        scalar_defaults = {
            "tier": design_layer,
            "polarity": "positive",
            "generalization_status": "local",
        }
        for key, default_value in scalar_defaults.items():
            value = self._metadata_scalar(original_item_data.get(key, default_value))
            prepared_metadata[key] = value if value is not None else default_value

        quality_fields = (
            "confidence",
            "delta_score",
            "usage_count",
            "success_count",
            "support_count",
            "validation_success_rate",
        )
        for key in quality_fields:
            value = self._metadata_scalar(original_item_data.get(key))
            if value is not None:
                prepared_metadata[key] = value

        active_value = original_item_data.get("active", True)
        if isinstance(active_value, bool):
            prepared_metadata["active"] = active_value
        else:
            prepared_metadata["active"] = True

        diagram_tag_keys = ["domain", "diagram_type", "source", "agent"]
        prefix = design_layer.strip().lower()

        for tag_key in diagram_tag_keys:
            if tag_key in metadata and isinstance(metadata[tag_key], list):
                for v in metadata[tag_key]:
                    if isinstance(v, str):
                        normalized_value = v.strip().lower().replace(" ", "_")
                        meta_key = f"{prefix}_{tag_key}_{normalized_value}"
                        prepared_metadata[meta_key] = True
                    else:
                        logger.warning("Non-string value in tags['%s']: %s. Skipping.", tag_key, v)


        return prepared_metadata


    def preprocess_design_item(self, item: Dict[str, Any], design_layer: str = "guideline") -> Document:
        """
        Preprocess a knowledge item to ensure it has the required structure for storage.

        Args:
            item (dict): Original knowledge item dictionary

        Returns:
            Document: LangChain Document object ready for storage
        """
        design_layer = self._normalize_design_layer(design_layer)
        item_id = str(item['id'])
        metadata = item.get('tags', {})

        # Prepare metadata for ChromaDB compatibility, including the original JSON string
        prepared_metadata = self._prepare_metadata_for_chromadb(metadata, item, design_layer=design_layer)
        prepared_metadata['id'] = item_id
        prepared_metadata['design_layer'] = design_layer
        prepared_metadata['title'] = item.get('title', '')

        # Clear the content
        content = copy.deepcopy(item)
        other_keys = [
            'tags', 'id',
        ]
        for key in other_keys:
            if key in content:
                content.pop(key)
        # Create LangChain Document
        doc = _document_class()(
            id=item_id,
            page_content=json.dumps(content),
            metadata=prepared_metadata
        )

        return doc

    def add_design_item(self, item, design_layer="guideline"):
        """
        Add a single knowledge item using LangChain's vector store interface.
        If an item with the same base ID already exists, a version suffix is
        appended (e.g. ``id_v2``, ``id_v3``) so the old version is preserved.

        Args:
            item (dict): The knowledge item dictionary
            design_layer (str): Type of knowledge - "guideline", "principle", "samples", or "strategy"
        """
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}")

        doc = self.preprocess_design_item(item, design_layer=design_layer)

        with self._lock:
            final_id = self._next_version_id(
                doc.metadata['id'],
                normalized_layer,
                reserved_ids=set(),
            )
            self._assign_document_id(doc, final_id)
            vector_db = self.design_layers[normalized_layer]["vector_db"]
            vector_db.add_documents([doc], ids=[doc.id])
        logger.info("Added %s item %s", design_layer, doc.id)

    def save_design_memory(self, memory: List[Dict[str, Any]], design_layer: str):
        """
        Save design knowledge memory to appropriate ChromaDB collection using LangChain interface.
        Each item gets a versioned ID if the base ID already exists.

        Args:
            memory (list): List of knowledge items with content and metadata
            design_layer (str): Type of knowledge - "guideline", "principle", "samples", or "strategy"
        """
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}")

        knowledge_config = self.design_layers[normalized_layer]
        vector_db = knowledge_config["vector_db"]

        documents = []
        for item in memory:
            doc = self.preprocess_design_item(item, design_layer=design_layer)
            documents.append(doc)

        filtered_documents = _metadata_filter()(documents)
        if not filtered_documents:
            logger.warning("No valid documents after metadata filtering for %s.", normalized_layer)
            return

        with self._lock:
            reserved_ids: Set[str] = set()
            for doc in filtered_documents:
                final_id = self._next_version_id(
                    doc.metadata['id'],
                    normalized_layer,
                    reserved_ids=reserved_ids,
                )
                self._assign_document_id(doc, final_id)
                reserved_ids.add(final_id)
            filtered_ids = [doc.id for doc in filtered_documents]
            vector_db.add_documents(filtered_documents, ids=filtered_ids)
        logger.info("Saved %d %s items to %s", len(filtered_documents), normalized_layer, self.vector_db_path)

    def update_design_items(self, items: List[Dict[str, Any]], design_layer: str) -> None:
        """In-place upsert: existing IDs get their content/metadata replaced.

        Unlike :meth:`save_design_memory`, this does **not** append a version
        suffix. Use it for items already loaded from this DB whose stats or
        tier changed during a run; use ``save_design_memory`` for genuinely
        new items where versioning is desirable.
        """
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(
                f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}"
            )

        if not items:
            return

        vector_db = self.design_layers[normalized_layer]["vector_db"]
        documents = [self.preprocess_design_item(item, design_layer=design_layer) for item in items]
        filtered_documents = _metadata_filter()(documents)
        if not filtered_documents:
            logger.warning("No valid documents after metadata filtering for %s.", normalized_layer)
            return

        for doc in filtered_documents:
            self._assign_document_id(doc, doc.id)
        ids = [doc.id for doc in filtered_documents]
        with self._lock:
            update_documents = getattr(vector_db, "update_documents", None)
            if not callable(update_documents):
                raise RuntimeError(
                    f"Vector store for {normalized_layer} does not support safe document updates"
                )
            try:
                update_documents(ids=ids, documents=filtered_documents)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to update existing {normalized_layer} items"
                ) from exc
        logger.info(
            "Updated %d %s items in %s",
            len(filtered_documents),
            normalized_layer,
            self.vector_db_path,
        )

    def delete_design_items(self, item_ids: List[str], design_layer: str) -> None:
        """Physically delete IDs from a layer.

        This is reserved for explicit compaction/repair. Normal knowledge
        lifecycle retirement should use :meth:`archive_design_items` so the
        run remains auditable and old IDs cannot be silently reused.
        """
        if not item_ids:
            return
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(
                f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}"
            )
        vector_db = self.design_layers[normalized_layer]["vector_db"]
        with self._lock:
            try:
                vector_db.delete(ids=[str(i) for i in item_ids])
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to delete {len(item_ids)} {normalized_layer} items"
            ) from exc
        logger.info("Deleted %d %s items", len(item_ids), normalized_layer)

    def archive_design_items(
        self,
        item_ids: List[str],
        design_layer: str,
        *,
        status: str = "retired",
        reason: str = "",
    ) -> None:
        """Mark existing items inactive instead of deleting them.

        Archiving preserves provenance for maintenance decisions while keeping
        the active-positive retrieval path clean via ``active=False``.
        """
        if not item_ids:
            return
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(
                f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}"
            )

        target_ids = {str(item_id) for item_id in item_ids}
        loaded_items = self.load_all_items(normalized_layer)
        item_by_id = {
            str(item["id"]): copy.deepcopy(item)
            for item in loaded_items
            if isinstance(item, dict) and item.get("id") is not None
        }
        missing_ids = sorted(target_ids - set(item_by_id))
        if missing_ids:
            raise RuntimeError(
                f"Cannot archive missing {normalized_layer} item ids: "
                + ", ".join(missing_ids)
            )

        archived_at = datetime.now(timezone.utc).isoformat()
        archived_items: List[Dict[str, Any]] = []
        for item_id in sorted(target_ids):
            item = item_by_id[item_id]
            item["active"] = False
            item["generalization_status"] = status
            item["archive_reason"] = reason
            item["archived_at"] = archived_at
            item.setdefault("tier", normalized_layer)
            item.setdefault("polarity", "positive")
            archived_items.append(item)

        self.update_design_items(archived_items, design_layer=normalized_layer)
        logger.info(
            "Archived %d %s items with status %s",
            len(archived_items),
            normalized_layer,
            status,
        )

    def search_design_item(self, query_text: str, filters: Optional[Dict] = None, top_k: int = 5, score_threshold: float = 0.0, design_layer: str = "guideline"):
        """
        Search for knowledge items using LangChain's similarity search with optional metadata filtering.

        Args:
            query_text (str): Text query for semantic search
            filters (dict, optional): Metadata filters (no automatic filtering applied)
            top_k (int): Number of results to return
            score_threshold (float): Minimum **cosine similarity** a result must
                reach. Collections are created with cosine distance and
                embeddings are L2-normalised (see :meth:`__init__`), so
                LangChain's relevance score is ``1 - cosine_distance``, i.e. the
                cosine similarity itself, in ``[-1, 1]``. ``0.0`` therefore means
                "drop results that are not positively related to the query".
            design_layer (str): Type of knowledge to search in ("guideline", "principle", "samples", "strategy")

        Returns:
            list[Document]: Matching documents, each with its cosine similarity
            in ``metadata['score']``
        """
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}")

        vector_db = self.design_layers[normalized_layer]["vector_db"]
        try:
            langchain_filters = filters
            docs_and_scores = vector_db.similarity_search_with_relevance_scores(
                query_text,
                k=top_k,
                filter=langchain_filters,
                score_threshold=score_threshold,
            )
            # results = self._convert_langchain_results_to_chromadb_format(docs_and_scores)
            for doc, score in docs_and_scores:
                doc.page_content = json.loads(doc.page_content)
                doc.metadata['score'] = score
            docs = [doc for doc, score in docs_and_scores]
            return docs

        except Exception as e:
            logger.error("Search failed for %s: %s", design_layer, e)
            raise RuntimeError(f"Design memory search failed for {design_layer}") from e

    def search_all_design_layers(self, query_text, filters=None, top_k_per_type=3):
        """
        Search across all knowledge types using LangChain's vector stores.

        Args:
            query_text (str): Text query for semantic search
            filters (dict, optional): Metadata filters (applied to all types)
            top_k_per_type (int): Number of results to return from each knowledge type

        Returns:
            dict: Combined search results with knowledge type labels
        """
        combined_results = {design_layer: [] for design_layer in self.design_layers}

        for design_layer in self.design_layers:
            docs = self.search_design_item(
                query_text=query_text,
                filters=filters,
                top_k=top_k_per_type,
                design_layer=design_layer
            )

            combined_results[design_layer] = docs or []

        return combined_results

    def delete_design_item(self, item_id, design_layer="guideline"):
        """
        Delete a knowledge item using LangChain's vector store interface.

        Args:
            item_id (str): Unique identifier for the knowledge item
            design_layer (str): Type of knowledge to delete from ("guideline", "principle", "samples", "strategy")
        """
        normalized_layer = self._normalize_design_layer(design_layer)
        if normalized_layer not in self.design_layers:
            raise ValueError(f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}")

        with self._lock:
            vector_db = self.design_layers[normalized_layer]["vector_db"]
            vector_db.delete([str(item_id)])
        logger.info("Deleted %s item %s", normalized_layer, item_id)

    @staticmethod
    def _metadata_stats(metadatas: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_polarity: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        active_count = 0
        active_positive_count = 0
        archived_count = 0

        for metadata in metadatas:
            if not isinstance(metadata, dict):
                metadata = {}
            active = metadata.get("active") is True
            polarity = metadata.get("polarity")
            status = metadata.get("generalization_status")

            if isinstance(polarity, str):
                by_polarity[polarity] = by_polarity.get(polarity, 0) + 1
            if isinstance(status, str):
                by_status[status] = by_status.get(status, 0) + 1

            if active:
                active_count += 1
                if polarity == "positive":
                    active_positive_count += 1
            if metadata.get("active") is False or status in {"pruned", "retired"}:
                archived_count += 1

        return {
            "active_count": active_count,
            "active_positive_count": active_positive_count,
            "archived_count": archived_count,
            "by_polarity": by_polarity,
            "by_generalization_status": by_status,
        }

    def get_design_layer_stats(self):
        """Get statistics for each knowledge type collection."""
        stats = {}
        for design_layer, config in self.design_layers.items():
            try:
                vector_db = config["vector_db"]
                collection = getattr(vector_db, '_collection', None)
                count = collection.count() if collection else 0
                metadatas: List[Dict[str, Any]] = []
                if collection is not None and hasattr(collection, "get"):
                    metadata_result = collection.get(include=["metadatas"])
                    metadatas = metadata_result.get("metadatas") or []
                lifecycle_stats = self._metadata_stats(metadatas)
                stats[design_layer] = {
                    "count": count,
                    "total_count": count,
                    **lifecycle_stats,
                    "description": config["description"],
                    "collection_name": config["collection_name"],
                    "embedding_model": self.embedding_model_name,
                }
            except Exception as e:
                stats[design_layer] = {
                    "count": 0,
                    "description": config["description"],
                    "collection_name": config["collection_name"],
                    "embedding_model": self.embedding_model_name,
                    "error": str(e),
                }
        return stats

    def load_all_items(self, design_layer: str) -> List[Dict[str, Any]]:
        """Load every knowledge item in a layer as a raw dict.

        Used by the KE engine to seed in-memory state from the vector DB at
        startup, so multi-run distillation is incremental rather than
        starting from zero each invocation.

        Raises on DB access errors so callers do not mistake a failed seed for
        an empty collection and then create duplicate versions.
        """
        normalized = self._normalize_design_layer(design_layer)
        if normalized not in self.design_layers:
            raise ValueError(
                f"Invalid design_layer. Must be one of: {list(self.design_layers.keys())}"
            )

        vector_db = self.design_layers[normalized]["vector_db"]
        collection = getattr(vector_db, "_collection", None)
        if collection is None:
            raise RuntimeError(f"Design memory layer {normalized!r} has no collection")

        try:
            result = collection.get(include=["metadatas", "documents"])
        except Exception as exc:
            raise RuntimeError(f"Failed to load items from {normalized!r} collection") from exc

        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []
        documents = result.get("documents") or []

        items: List[Dict[str, Any]] = []
        for i, item_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            doc = documents[i] if i < len(documents) else ""

            # Prefer original_json_data: it round-trips the full item including tags.
            original = meta.get("original_json_data") if isinstance(meta, dict) else None
            if isinstance(meta, dict) and "original_json_data" in meta:
                try:
                    item = json.loads(original)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise RuntimeError(
                        "Failed to parse original_json_data for "
                        f"{normalized} item {item_id!r}"
                    ) from exc
                if not isinstance(item, dict):
                    raise RuntimeError(
                        "original_json_data for "
                        f"{normalized} item {item_id!r} must decode to an object"
                    )
                item.setdefault("id", item_id)
                items.append(item)
                continue

            # Fallback: rebuild from document body. Loses tags but keeps content.
            try:
                content = json.loads(doc) if isinstance(doc, str) else (doc or {})
            except json.JSONDecodeError:
                content = {}
            if isinstance(content, dict):
                content.setdefault("id", item_id)
                items.append(content)

        logger.info("Loaded %d items from %s collection.", len(items), normalized)
        return items
