import copy
import hashlib
import json
import logging
import os
from typing import Dict, List, Any

from evo_diagram.config.settings import AppSettings
from .diagram_design_memory import (
    DiagramDesignMemory,
    VALID_LAYERS,
    aliases_for_layer,
)

logger = logging.getLogger(__name__)

# Canonical knowledge file mapping
KNOWLEDGE_FILES = {layer: f"{layer}.json" for layer in VALID_LAYERS}

# Accept both singular and plural keys inside JSON objects.
# Derived from LAYER_ALIASES so there is a single source of truth.
DATA_KEYS = {layer: aliases_for_layer(layer) for layer in VALID_LAYERS}
TEXT_FIELDS = ("title", "content", "description", "when_to_use")
TAG_LIST_FIELDS = ("domain", "diagram_type", "source", "agent")


def _hash_payload_for_generated_id(item: Dict[str, Any]) -> str:
    payload = copy.deepcopy(item)
    payload.pop("id", None)
    tags = payload.get("tags")
    if isinstance(tags, dict):
        payload["tags"] = {
            key: sorted(value) if isinstance(value, list) else value
            for key, value in tags.items()
        }
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:12]


def _validate_tags(tags: Any, *, source_file: str, index: int) -> Dict[str, Any]:
    if tags is None:
        return {}
    if not isinstance(tags, dict):
        raise ValueError(
            f"{source_file} item {index}: tags must be an object, "
            f"got {type(tags).__name__}"
        )

    normalized_tags = copy.deepcopy(tags)
    for key, value in normalized_tags.items():
        if key in TAG_LIST_FIELDS or isinstance(value, list):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(
                    f"{source_file} item {index}: tags[{key!r}] must be a list of strings"
                )
        elif isinstance(value, dict):
            raise ValueError(
                f"{source_file} item {index}: tags[{key!r}] must be a scalar "
                "or a list of strings"
            )
    return normalized_tags


def _missing_text_fields(item: Dict[str, Any]) -> List[str]:
    """Required textual fields that are absent, non-string, or blank.

    The write-side contract mirrors :class:`KnowledgeEntry`, which requires
    ``title``, ``description``, ``content`` and ``when_to_use`` on every entry.
    Accepting less here let incomplete items into the vector DB that the
    evolution engine's read side (``KnowledgeEntry.model_validate`` during DB
    seeding, and the retriever's prompt formatting) treats as mandatory.
    """
    return [
        field
        for field in TEXT_FIELDS
        if not (isinstance(item.get(field), str) and item[field].strip())
    ]


def _normalize_knowledge_item(
    item: Any,
    *,
    design_type: str,
    source_file: str,
    index: int,
    seen_ids: set[str] | None = None,
) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(
            f"{source_file} {design_type} item {index}: expected object, "
            f"got {type(item).__name__}"
        )

    normalized = copy.deepcopy(item)
    normalized["tags"] = _validate_tags(
        normalized.get("tags"),
        source_file=source_file,
        index=index,
    )

    missing = _missing_text_fields(normalized)
    if missing:
        raise ValueError(
            f"{source_file} {design_type} item {index} "
            f"(id={normalized.get('id')!r}, title={normalized.get('title')!r}): "
            f"missing or empty required field(s): {', '.join(missing)}. "
            f"Knowledge items must provide all of {', '.join(TEXT_FIELDS)} "
            "as non-empty strings (KnowledgeEntry write-side contract)."
        )

    raw_id = normalized.get("id")
    item_id = str(raw_id).strip() if raw_id is not None else ""
    if not item_id:
        item_id = f"{design_type}_{_hash_payload_for_generated_id(normalized)}"
    normalized["id"] = item_id

    raw_design_type = normalized.get("design_type")
    if raw_design_type is not None and str(raw_design_type).strip() != design_type:
        raise ValueError(
            f"{source_file} {design_type} item {index}: design_type "
            f"{raw_design_type!r} does not match file layer {design_type!r}"
        )
    normalized["design_type"] = design_type

    if seen_ids is not None:
        if item_id in seen_ids:
            raise ValueError(
                f"{source_file} {design_type} item {index}: duplicate id {item_id!r}"
            )
        seen_ids.add(item_id)

    return normalized


class MemoryStorageWorkflow:

    def __init__(
        self,
        raw_memory_dir: str,
        vector_db_path: str = None,
        embedding_model_name: str = None,
    ) -> None:
        settings = AppSettings.get_default()
        if vector_db_path is None:
            vector_db_path = settings.design_memory_vector_db_path
        if embedding_model_name is None:
            embedding_model_name = settings.design_memory_embedding_model

        self.raw_memory_dir = raw_memory_dir
        self.vector_db_path = vector_db_path
        self.embedding_model_name = embedding_model_name
        self.design_memory = DiagramDesignMemory(
            vector_db_path=vector_db_path, embedding_model_name=embedding_model_name,
        )

    def load_knowledge_items(self, folder_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """Load knowledge items from separate JSON files per type within the folder.

        Supports two JSON layouts per file:
          1) A bare list of items
          2) An object with a single array field, e.g. {"guideline": [...]}
        Expected files: guideline.json, principle.json, samples.json, strategy.json.

        Every item must carry all four ``KnowledgeEntry`` text fields
        (``title``, ``description``, ``content``, ``when_to_use``) as non-empty
        strings. Validation is fail-fast like every other check in this module
        (duplicate ids, tag schema, design_type mismatch): the first invalid
        item raises ``ValueError`` naming the missing fields and the item's
        id/title, and nothing from the folder is ingested. Skipping bad items
        instead would silently ingest a partial corpus and degrade retrieval
        quality; ingestion is offline and re-runnable, so failing the load is
        cheap and surfaces corpus problems while they are still fixable.
        """
        all_knowledge_items: Dict[str, List[Dict[str, Any]]] = {
            layer: [] for layer in KNOWLEDGE_FILES
        }
        any_file_found = False

        for design_type, filename in KNOWLEDGE_FILES.items():
            data_file = os.path.join(folder_path, filename)
            if not os.path.exists(data_file):
                logger.debug("Skipping %s: file not found at %s", design_type, data_file)
                continue

            any_file_found = True
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            items_raw: List[Dict[str, Any]] = []
            if isinstance(data, list):
                items_raw = data
            elif isinstance(data, dict):
                matched = False
                for key in DATA_KEYS.get(design_type, []):
                    if key in data and isinstance(data[key], list):
                        items_raw = data[key]
                        matched = True
                        break
                if not matched:
                    raise ValueError(
                        f"Expected a list or a keyed list (one of {DATA_KEYS.get(design_type, [])}) "
                        f"in {data_file}, got {type(data).__name__}"
                    )
            else:
                raise ValueError(f"Expected a list or object in {data_file}, got {type(data).__name__}")

            processed_items: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()
            for i, item in enumerate(items_raw):
                processed_items.append(
                    _normalize_knowledge_item(
                        item,
                        design_type=design_type,
                        source_file=data_file,
                        index=i,
                        seen_ids=seen_ids,
                    )
                )

            all_knowledge_items[design_type].extend(processed_items)
            logger.info("Loaded %d items for %s from %s", len(processed_items), design_type, data_file)

        if not any_file_found:
            raise FileNotFoundError(
                f"No knowledge files found in {folder_path}. Expected one of: {list(KNOWLEDGE_FILES.values())}"
            )
        return all_knowledge_items

    def run_store_memory(self) -> None:
        """Load and store all knowledge corpus data into the vector database."""
        logger.info("Storing corpus from %s to %s", self.raw_memory_dir, self.vector_db_path)

        all_knowledge_items = self.load_knowledge_items(self.raw_memory_dir)
        for design_type, all_items in all_knowledge_items.items():
            if not all_items:
                logger.debug("Skipping %s — no items found", design_type)
                continue
            self.design_memory.save_design_memory(all_items, design_type)
            logger.info("Stored %d items of type %s", len(all_items), design_type)

        stats = self.design_memory.get_design_layer_stats()
        for k_type, stat in stats.items():
            logger.info("  %s: %d items", k_type, stat.get('count', 0))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    raw_memory_dir = "./data"
    settings = AppSettings.get_default()
    vector_db_dir = settings.design_memory_vector_db_path
    embedding_model_name = settings.design_memory_embedding_model

    workflow = MemoryStorageWorkflow(
        raw_memory_dir=raw_memory_dir,
        vector_db_path=vector_db_dir,
        embedding_model_name=embedding_model_name,
    )
    workflow.run_store_memory()

    # Quick retrieval test
    from .diagram_design_retriever import DiagramDesignRetriever
    retriever = DiagramDesignRetriever(workflow.design_memory)
    query = "Consistency builds trust and enables rapid scanning."
    results = retriever.retrieve_knowledge(query, types=["guideline", "principle"], top_k=3)
    for layer, docs in results.items():
        logger.info("%s: %d results", layer.upper(), len(docs))
        for doc in docs[:2]:
            logger.info(
                "  score=%.4f | %s",
                doc.metadata.get("score", 0),
                str(doc.page_content)[:80],
            )
