"""Process-wide cache of design-memory retrievers.

Constructing ``DiagramDesignMemory`` loads a sentence-transformer model and
opens the Chroma collections, so it must happen once per process rather than
once per generation (``agentic_system/main.py`` builds one workflow per dataset
item, and the backend reuses the store across jobs).

Only permanent failures are cached: a missing optional dependency
(``ImportError``) or a store built with a different metric / embedding model
(``DesignMemoryConsistencyError``). Anything else (a locked file, a transient
I/O error) is reported but not cached, so the next call retries.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple

RetrieverResult = Tuple[Any, Optional[str]]

_CACHE: Dict[Tuple[Optional[str], Optional[str]], RetrieverResult] = {}
_CACHE_LOCK = threading.Lock()


def reset_shared_retriever_cache() -> None:
    """Drop the shared design-memory retrievers (tests, or after a rebuild)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def load_shared_retriever(
    vector_db_path: Optional[str],
    embedding_model_name: Optional[str],
) -> RetrieverResult:
    """Return ``(retriever, error_message)`` for the shared design-memory store."""
    key = (vector_db_path, embedding_model_name)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        try:
            # Resolved through the package so tests can patch the public names.
            from evo_diagram.design_memory import (
                DiagramDesignMemory,
                DiagramDesignRetriever,
            )
            from evo_diagram.design_memory.diagram_design_memory import (
                DesignMemoryConsistencyError,
            )
        except ImportError as exc:
            result: RetrieverResult = (None, f"design memory dependencies unavailable: {exc}")
            _CACHE[key] = result
            return result
        try:
            memory = DiagramDesignMemory(
                vector_db_path=vector_db_path,
                embedding_model_name=embedding_model_name,
            )
            result = (DiagramDesignRetriever(design_memory=memory), None)
        except ImportError as exc:
            # chromadb / sentence-transformers are optional extras.
            result = (None, f"design memory dependencies unavailable: {exc}")
        except DesignMemoryConsistencyError as exc:
            result = (None, f"design memory initialization failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - transient; do not cache
            return (None, f"design memory initialization failed: {exc}")
        _CACHE[key] = result
        return result
