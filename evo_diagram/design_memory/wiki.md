# Design Memory — Wiki

## Overview

`design_memory` is the persistent knowledge storage and retrieval subsystem for EvoDesign. It stores design knowledge (guidelines, principles, samples, strategies) in a ChromaDB vector database and provides semantic search for injecting relevant knowledge into the diagram generation pipeline.

## Architecture

```
                     ┌─────────────────────────────────────┐
                     │         DiagramDesignRetriever       │
                     │  retrieve_knowledge(query, types)    │
                     └──────────────┬──────────────────────┘
                                    │ delegates to
                     ┌──────────────▼──────────────────────┐
                     │         DiagramDesignMemory          │
                     │  4 × Chroma vector stores            │
                     │  (one per knowledge layer)           │
                     └──────────────┬──────────────────────┘
                                    │ uses
                     ┌──────────────▼──────────────────────┐
                     │     HuggingFaceEmbeddings            │
                     │     Qwen/Qwen3-Embedding-0.6B       │
                     └─────────────────────────────────────┘
```

## Knowledge Layers

| Layer | Purpose | Content |
|-------|---------|---------|
| `samples` | Concrete examples | Diagram generation records (text → structure → styling → layout) |
| `strategy` | Tactical patterns | Curated from samples — "when you see X, do Y" |
| `guideline` | Domain rules | Extracted from strategies grouped by domain/type/agent |
| `principle` | Universal axioms | Synthesized from guidelines — highest abstraction level |

Evolution flow: `samples → strategy → guideline → principle` (handled by `knowledge_evolution` module).

## File Structure

```
design_memory/
├── __init__.py                    # Public API exports
├── diagram_design_memory.py       # Core: DiagramDesignMemory class (ChromaDB CRUD + search)
├── diagram_design_retriever.py    # DiagramDesignRetriever (unified search across layers)
├── memory_workflow.py             # MemoryStorageWorkflow (validated JSON import -> ChromaDB)
├── utils/
│   └── format_memory.py           # Display helpers: print_retrieval_results, stringify_knowledge_item
├── README.md                      # Import contract and usage
├── RISKS.md                       # Known design-memory risks
└── wiki.md                        # This file
```

## Key Classes

### `DiagramDesignMemory` (`diagram_design_memory.py`)

Core storage layer. Manages 4 independent ChromaDB collections, one per knowledge layer.

```python
memory = DiagramDesignMemory(
    vector_db_path="../data/knowledge",          # or DESIGN_MEMORY_VECTOR_DB_PATH env
    embedding_model_name="Qwen/Qwen3-Embedding-0.6B",  # or DESIGN_MEMORY_EMBEDDING_MODEL env
)

# Write
memory.save_design_memory(items, design_layer="guideline")
memory.add_design_item(item, design_layer="strategy")

# Read
docs = memory.search_design_item(query_text="flowchart layout", design_layer="guideline", top_k=5)
all_results = memory.search_all_design_layers(query_text="swimlane", top_k_per_type=3)

# Delete
memory.delete_design_item(item_id="guideline_001", design_layer="guideline")

# Stats
stats = memory.get_design_layer_stats()  # → {"guideline": {"count": 42, ...}, ...}
```

**Metadata handling**: Lists in `tags` (e.g., `domain: ["workflow", "architecture"]`) are flattened to boolean flags (`guideline_domain_workflow: True`, `guideline_domain_architecture: True`) for ChromaDB compatibility. The full original item is stored as `original_json_data` JSON string.

### `DiagramDesignRetriever` (`diagram_design_retriever.py`)

High-level search interface used by the generation pipeline.

```python
retriever = DiagramDesignRetriever(design_memory=memory)
results = retriever.retrieve_knowledge(
    query="How to layout a flowchart with swimlanes",
    types=["guideline", "principle"],  # or "all"
    top_k=5,
    score_threshold=0.3,
    filters={"guideline_domain_workflow": True},
)
# → {"guideline": [Document, ...], "principle": [Document, ...]}
```

### `RetrievalFilter` (`retrieval_filter.py`)

Builds boolean filter expressions for metadata filtering.

```python
rf = RetrievalFilter.from_dict({
    "combine": "AND",
    "guideline": {"options": ["flowchart", "mindmap"], "operation": "OR"},
    "strategy": {"options": ["architecture"], "operation": "OR"},
})

rf.to_langchain_format()  # → {"$and": [{"$or": [{...}, {...}]}, {...}]}
rf.to_chroma_format()     # → similar, with $in for OR groups
```

### `MemoryStorageWorkflow` (`memory_workflow.py`)

Batch ingestion: loads JSON files from a directory and stores them into ChromaDB.

```python
workflow = MemoryStorageWorkflow(raw_memory_dir="./data/knowledge")
workflow.run_store_memory()
# Loads guideline.json, principle.json, samples.json, strategy.json
# Stores each into the corresponding ChromaDB collection
```

**JSON file format** — each file can be either:
- A bare list: `[{"id": "...", "title": "...", "content": "...", "tags": {...}}, ...]`
- A keyed object: `{"guideline": [{"id": "...", ...}, ...]}`

Import validation is fail-fast:

- Each item must be an object.
- Missing or blank `id` values receive stable content-hash IDs.
- Duplicate IDs inside a file fail before storage.
- Explicit `design_type` values must match the file layer.
- `tags` must be an object; known tag lists such as `domain`, `diagram_type`, `source`, and `agent` must be `list[str]`.
- At least one textual field among `title`, `content`, `description`, and `when_to_use` must be present.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DESIGN_MEMORY_VECTOR_DB_PATH` | `../data/knowledge` | ChromaDB persist directory |
| `DESIGN_MEMORY_EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | HuggingFace embedding model |

Defined through `evo_diagram.config.settings.AppSettings`, read in `diagram_design_memory.py` and `memory_workflow.py`.

## Integration Points

| Consumer | How it uses design_memory |
|----------|---------------------------|
| `knowledge_evolution/evolution_engine.py` | Creates `DiagramDesignMemory` + `DiagramDesignRetriever` for knowledge evolution pipeline |
| `agentic_system/workflow.py` | Retrieves design expertise to inject into agents as context |
| `knowledge_evolution/` distillers | Write evolved knowledge (guidelines, principles) back to memory |

## Running

```bash
# Batch ingest knowledge from JSON files
python -m evo_diagram.design_memory.memory_workflow

# Quick retrieval test (built into memory_workflow.py __main__)
# Searches for "Consistency builds trust" across guideline + principle layers
```

## Dependencies

- `langchain-chroma` — ChromaDB integration via LangChain
- `langchain-huggingface` — HuggingFace embeddings wrapper
- `langchain-core` — Document model
- `langchain-community` — `filter_complex_metadata` utility
- Runtime: `Qwen/Qwen3-Embedding-0.6B` model (auto-downloaded on first use)
