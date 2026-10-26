# User Preference Memory System - Wiki

## Overview

The User Preference Memory System learns user design preferences by analyzing manual adjustments made to auto-generated diagrams. It extracts semantic, context-rich preferences and stores them for future personalized diagram generation.

**Core idea**: When a user manually edits a machine-generated diagram (e.g., changes node colors, repositions elements, modifies arrow styles), the system captures *why* they made those changes and applies the learned preferences to future diagrams.

---

## Architecture

The system follows a **4-layer pipeline**:

```
Layer 1 (VLM Observer) → Layer 2 (JSON Diff) → Layer 3 (LLM Agent) → Layer 4 (ChromaDB Storage)
```

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       User Preference Memory System                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │   Layer 1    │   │   Layer 2    │   │   Layer 3    │   │   Layer 4    │ │
│  │ VLM Observer │──>│  JSON Diff   │──>│  LLM Agent   │──>│  ChromaDB    │ │
│  │              │   │  Extractor   │   │  Preference  │   │  Storage     │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│        │                  │                  │                  │            │
│        v                  v                  v                  v            │
│  VisualObservation   GuidedDiff      SemanticPreference    Vector Store     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    v
┌──────────────────────────────────────────────────────────────────────────────┐
│                      Agentic System Integration                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │  Structure   │   │   Styling    │   │   Layout     │   │   Render     │ │
│  │   Stage      │   │    Stage     │   │    Stage     │   │    Stage     │ │
│  │  <── Struct  │   │  <── Style   │   │  <── Layout  │   │              │ │
│  │     Prefs    │   │     Prefs    │   │     Prefs    │   │              │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Layer 1: VLM Image Observer

**File**: `extractors/vlm_observer.py`
**Class**: `VLMImageObserver`

Compares before/after diagram images using a Vision-Language Model to produce a high-level understanding of what the user changed and why.

- **Input**: model image, user-adjusted image, task description
- **Output**: `VisualObservation` (structural/styling/layout/semantic changes + overall intent)
- **Purpose**: Provides semantic context that guides subsequent layers

### Layer 2: JSON Diff Extractor

**Files**: `extractors/manifest_validator.py`, `extractors/manifest_normalizer.py`, `extractors/diff_extractor.py`
**Classes**: `ManifestValidator`, `ManifestNormalizer`, `EnhancedDiffExtractor`

Extracts precise property-level differences between two TLDraw manifests. Handles multiple manifest formats (v3.15 store dict, legacy array, hybrid).

- **Input**: model manifest JSON, user manifest JSON, VLM observation
- **Output**: `GuidedDiff` (additions, deletions, modifications with per-property changes)
- **Features**: Numeric tolerance (epsilon = 0.01), format auto-detection, VLM-guided priority flagging

### Layer 3: LLM Preference Extraction Agent

**File**: `extractors/llm_preference_agent.py`
**Class**: `LLMPreferenceExtractionAgent`

Uses an LLM with few-shot examples to analyze VLM observations + JSON diffs and extract generalizable, semantic preferences.

- **Input**: `VisualObservation`, `GuidedDiff`, task context
- **Output**: `PreferenceExtractionResult` (list of `SemanticPreference` with confidence scores)
- **Features**: Few-shot prompting, confidence filtering (default >= 0.7), agent-category alignment

### Layer 4: ChromaDB Storage

**File**: `storage/mem0_storage.py`
**Class**: `Mem0PreferenceStorage`

Persists preferences in ChromaDB with HuggingFace embeddings for semantic retrieval.

- **Technology**: ChromaDB + `Qwen/Qwen3-Embedding-0.6B`
- **Collections**: `user_preferences_{user_id}` (semantic prefs), `user_observations_{user_id}` (VLM obs + diff metadata)
- **Features**: Metadata filtering, similarity search, in-memory fallback

---

## Directory Structure

```
user_memory/
├── __init__.py                         # Module exports
├── main.py                             # Orchestrator (UserPreferenceMemorySystem)
├── extractors/
│   ├── __init__.py
│   ├── vlm_observer.py                 # Layer 1: VLM image observation
│   ├── manifest_validator.py           # Layer 2a: manifest format detection
│   ├── manifest_normalizer.py          # Layer 2b: manifest normalization
│   ├── diff_extractor.py               # Layer 2c: JSON diff extraction
│   ├── llm_preference_agent.py         # Layer 3: LLM semantic extraction
├── schemas/
│   ├── __init__.py
│   ├── observation_schemas.py          # VisualObservation, CategoryObservation
│   ├── diff_schemas.py                 # PropertyChange, GuidedDiff, Shape{Addition,Deletion,Modification}
│   └── semantic_preference_schemas.py  # SemanticPreference, PreferenceExtractionResult, PreferenceQuery
├── storage/
│   ├── __init__.py
│   └── mem0_storage.py                 # Layer 4: ChromaDB + HuggingFace storage
├── docs/
│   ├── wiki.md                         # Detailed Chinese documentation
│   ├── integration_plan.md             # Integration status
│   └── future_features.md             # API design & roadmap
└── data_example/                       # Sample data for testing
```

---

## Data Flow

### Learning Flow

```
User edits diagram  -->  learn_from_edit()
   |
   +--> Layer 1: VLM compares images -> VisualObservation
   +--> Layer 2: JSON diff extraction -> GuidedDiff
   +--> Layer 3: LLM extracts semantic preferences -> PreferenceExtractionResult
   +--> Layer 4: Store in ChromaDB
```

### Retrieval Flow

```
New diagram request  -->  retrieve_preferences(query, category, ...)
   |
   +--> ChromaDB similarity search with metadata filters
   +--> format_preferences_for_prompt()
   +--> Inject into agent's design_expertise field
```

Preferences are injected **per-stage**: Structure stage gets only `agent_category="Structure"` preferences, Styling stage gets only Styling, Layout gets only Layout.

---

## Key APIs

### UserPreferenceMemorySystem (main.py)

```python
system = UserPreferenceMemorySystem(user_id="user_123")

# Learn from a user edit
result = system.learn_from_edit(
    task_json={"diagram_type": "class", "content_area": "Software Engineering", ...},
    model_manifest_path="path/to/model/manifest.json",
    model_image_path="path/to/model/image.png",
    user_manifest_path="path/to/user/manifest.json",
    user_image_path="path/to/user/image.png",
    session_id="session_001",
)

# Retrieve preferences
prefs = system.retrieve_preferences(
    query="User preferences for class diagrams",
    agent_category="Styling",       # Structure | Styling | Layout
    diagram_type="class",
    min_confidence=0.7,
    top_k=5,
)

# Format for prompt injection
prompt_text = system.format_preferences_for_prompt(prefs, max_length=1000)
```

### Data Models

| Schema | Location | Purpose |
|--------|----------|---------|
| `VisualObservation` | `schemas/observation_schemas.py` | VLM layer output |
| `GuidedDiff` | `schemas/diff_schemas.py` | JSON diff layer output |
| `SemanticPreference` | `schemas/semantic_preference_schemas.py` | LLM-extracted preference |
| `PreferenceExtractionResult` | `schemas/semantic_preference_schemas.py` | Layer 3 output container |

---

## CLI Usage

### Learn preferences

```bash
python -m evo_diagram.agentic_system.main \
    --learn-from-edit \
    --user-id "test_user" \
    --task-json "path/to/task.json" \
    --model-manifest "path/to/model/manifest.json" \
    --model-image "path/to/model/image.png" \
    --user-manifest "path/to/user/manifest.json" \
    --user-image "path/to/user/image.png"
```

### Generate with memory

```bash
python -m evo_diagram.agentic_system.main \
    --example 1 \
    --enable-user-memory \
    --user-id "test_user"
```

---

## Configuration

```yaml
# config/default.yaml
user_memory:
  vector_db_path: ${oc.env:USER_PREFERENCE_MEMORY_PATH,./data/user_preferences}
  embedding_model_name: ${oc.env:USER_PREFERENCE_EMBEDDING_MODEL,Qwen/Qwen3-Embedding-0.6B}
```

Environment variables (optional):
- `USER_PREFERENCE_MEMORY_PATH` - ChromaDB storage path (default: `./data/user_preferences`)
- `USER_PREFERENCE_EMBEDDING_MODEL` - Embedding model (default: `Qwen/Qwen3-Embedding-0.6B`)

---

## Dependencies

- `langchain-chroma` - ChromaDB vector store integration
- `langchain-huggingface` - HuggingFace embeddings
- `langchain-core` - Base LLM/message abstractions
- `pydantic` - Data validation and schemas
- `core.llm_factory` - LLM instance creation (project-internal)
- `core.base_agent` - Base agent class (project-internal)

---

## Implementation Status

| Feature | Status |
|---------|--------|
| VLM image observation (Layer 1) | Done |
| JSON diff extraction (Layer 2) | Done |
| LLM preference extraction (Layer 3) | Done |
| ChromaDB storage (Layer 4) | Done |
| CLI learn mode | Done |
| CLI generation with memory | Done |
| Per-stage preference injection | Done |
| Confidence filtering | Done |
| Backend REST API | Planned |
| Frontend integration | Planned |
