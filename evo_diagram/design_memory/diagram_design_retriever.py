import json
import logging
import math
import threading
from collections import OrderedDict
from contextlib import nullcontext
from functools import wraps
from typing import Dict, Any, List, Optional, Tuple, Union

try:
    from .diagram_design_memory import DiagramDesignMemory, normalize_layer
except ImportError:  # pragma: no cover - direct script execution fallback
    from diagram_design_memory import DiagramDesignMemory, normalize_layer

from evo_diagram.config.settings import AppSettings
# Shared with ``knowledge_evolution.maintenance.cycle.compute_confidence`` so
# retrieval-time and maintenance-time utility can never drift apart again.
# ``knowledge_evolution`` is a namespace package, so this import pulls in a
# dependency-free leaf module and nothing else.
from evo_diagram.knowledge_evolution.utility_scoring import compute_utility_score

logger = logging.getLogger(__name__)


# Default number of entries returned per knowledge layer, and the quota of
# diagram-type-agnostic entries merged in on top of a type-filtered result.
DEFAULT_RETRIEVAL_TOP_K = 5
GENERAL_RETRIEVAL_TOP_K = 2


def _reuse_query_embeddings(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        embedder = getattr(getattr(self, "design_memory", None), "embedding_function", None)
        reuse = getattr(embedder, "reuse_queries", None)
        with reuse() if callable(reuse) else nullcontext():
            return method(self, *args, **kwargs)
    return wrapped


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


class DiagramDesignRetriever:
    """Unified retrieval over the three knowledge layers: strategy, guideline, principle.

    Ranking combines four terms, all on a ``[0, 1]`` scale so their configured
    weights are directly comparable::

        score = w_rel * relevance
              + w_util * utility
              + w_expl * exploration
              - w_div  * diversity_penalty

    - ``relevance``  — cosine similarity between the query and the candidate,
      recomputed from embeddings of the *same* normalised text on both sides,
      clamped to ``[0, 1]``. Falls back to the vector store's cosine relevance
      score when embeddings are unavailable (the rerank is then marked degraded).
    - ``utility``    — :func:`compute_utility_score` over the entry's usage /
      Δscore / support record, already clamped to ``[0, 1]``.
    - ``exploration``— ``1 / (usage_count + 1)`` ∈ ``(0, 1]``.
    - ``diversity_penalty`` — max cosine similarity to the items already
      selected, clamped to ``[0, 1]``.

    ``w_rel`` is whatever positive-score budget the configured utility and
    exploration weights leave over, so the three positive terms always sum to
    one and the final score lies in ``[-w_div, 1]``. The earlier code added the
    raw vector-store score with an implicit weight of 1.0 alongside weights of
    0.25 / 0.10 / 0.20, and mixed two different relevance scales with ``max()``.
    """

    def __init__(
        self,
        design_memory: "DiagramDesignMemory",
    ):
        settings = AppSettings.get_default()
        self.design_memory = design_memory
        self.design_types = ["strategy", "guideline", "principle"]
        self.rerank_top_n = 20
        self._candidate_cache = OrderedDict()
        self._candidate_cache_lock = threading.RLock()
        self._utility_weight = settings.retriever_utility_weight
        self._diversity_weight = settings.retriever_diversity_weight
        self._exploration_weight = settings.retriever_exploration_weight
        if self._utility_weight + self._exploration_weight > 1.0:
            raise ValueError(
                "retriever.utility_weight + retriever.exploration_weight must "
                "not exceed 1.0; relevance is given the remaining budget "
                f"(got {self._utility_weight} + {self._exploration_weight})"
            )

    @property
    def _relevance_weight(self) -> float:
        """Positive-score budget left over for relevance.

        Derived rather than configured so the three positive terms provably sum
        to 1.0 with the existing ``retriever.*`` settings keys.
        """
        return max(0.0, 1.0 - self._utility_weight - self._exploration_weight)

    # ── Embedding-based similarity (#4) ──────────────────────────────

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _embed_query(
        self,
        text: str,
        embedding_cache: Optional[Dict[Tuple[str, str], Optional[List[float]]]] = None,
    ) -> Optional[List[float]]:
        """Get embedding vector for a text string."""
        cache_key = ("query", text)
        if embedding_cache is not None and cache_key in embedding_cache:
            return embedding_cache[cache_key]
        try:
            embedding = self.design_memory.embedding_function.embed_query(text)
        except Exception as exc:
            logger.warning("Embedding rerank degraded: query embedding failed: %s", exc)
            embedding = None
        if embedding_cache is not None:
            embedding_cache[cache_key] = embedding
        return embedding

    def _embed_candidate_texts(
        self,
        texts: List[str],
        embedding_cache: Dict[Tuple[str, str], Optional[List[float]]],
    ) -> bool:
        """Batch candidate embeddings into ``embedding_cache``.

        Returns True when embedding failed and rerank had to degrade to stored
        vector scores plus non-embedding heuristics.
        """
        # Model identity is fixed for this retriever. Cache by normalized content,
        # so edited knowledge naturally gets a new vector; bound retained memory.
        with self._candidate_cache_lock:
            for text in texts:
                cached = self._candidate_cache.get(text)
                if cached is not None:
                    embedding_cache[("candidate", text)] = cached
                    self._candidate_cache.move_to_end(text)
        missing = []
        seen = set()
        for text in texts:
            if not text:
                continue
            cache_key = ("candidate", text)
            if cache_key in embedding_cache or text in seen:
                continue
            missing.append(text)
            seen.add(text)

        if not missing:
            return any(
                embedding_cache.get(("candidate", text)) is None
                for text in texts
                if text
            )

        try:
            embed_documents = getattr(self.design_memory.embedding_function, "embed_documents", None)
            if callable(embed_documents):
                embeddings = embed_documents(missing)
            else:
                embeddings = [
                    self.design_memory.embedding_function.embed_query(text)
                    for text in missing
                ]
            if len(embeddings) != len(missing):
                raise ValueError(
                    f"embed_documents returned {len(embeddings)} vectors for {len(missing)} texts"
                )
        except Exception as exc:
            logger.warning("Embedding rerank degraded: candidate embedding failed: %s", exc)
            for text in missing:
                embedding_cache[("candidate", text)] = None
            return True

        for text, embedding in zip(missing, embeddings):
            embedding_cache[("candidate", text)] = embedding
            if embedding is not None:
                with self._candidate_cache_lock:
                    self._candidate_cache[text] = embedding
                    self._candidate_cache.move_to_end(text)
                    while len(self._candidate_cache) > 512:
                        self._candidate_cache.popitem(last=False)
        return any(embedding is None for embedding in embeddings)

    @staticmethod
    def _mark_rerank_degraded(docs: List[Any], reason: str) -> None:
        for doc in docs:
            metadata = getattr(doc, "metadata", None)
            if isinstance(metadata, dict):
                metadata["rerank_degraded"] = True
                metadata["rerank_degraded_reason"] = reason

    @staticmethod
    def _cached_candidate_embedding(
        text: str,
        embedding_cache: Dict[Tuple[str, str], Optional[List[float]]],
    ) -> Optional[List[float]]:
        if not text:
            return None
        return embedding_cache.get(("candidate", text))

    def get_design_stats(self) -> Dict[str, Any]:
        return self.design_memory.get_design_layer_stats()

    @staticmethod
    def _normalize_text(value: Any) -> str:
        text = str(value or "").casefold()
        normalized_chars: List[str] = []
        previous_was_space = True
        for char in text:
            if char.isalnum():
                normalized_chars.append(char)
                previous_was_space = False
            elif not previous_was_space:
                normalized_chars.append(" ")
                previous_was_space = True
        return "".join(normalized_chars).strip()

    @staticmethod
    def _item_text(doc: Any) -> str:
        if isinstance(doc.page_content, dict):
            parts = [
                doc.page_content.get("title", ""),
                doc.page_content.get("description", ""),
                doc.page_content.get("content", ""),
                doc.page_content.get("when_to_use", ""),
            ]
            return " ".join(str(p) for p in parts if p)
        return str(doc.page_content)

    @staticmethod
    def _utility_score(metadata: Dict[str, Any]) -> float:
        """Track-record score in ``[0, 1]``.

        Delegates to the shared implementation so retrieval and
        ``MaintenanceCycle`` cannot diverge; a local copy previously floored
        ``delta_score`` at ``-1.0`` while maintenance floored it at ``-10.0``,
        so a counter-example entry was penalised eight times harder during
        maintenance than during retrieval.
        """
        return compute_utility_score(
            usage_count=metadata.get("usage_count", 0) or 0,
            success_count=metadata.get("success_count", 0) or 0,
            delta_score=metadata.get("delta_score", 0.0) or 0.0,
            support_count=metadata.get("support_count", 1) or 1,
        )

    @staticmethod
    def _exploration_score(metadata: Dict[str, Any]) -> float:
        """Novelty bonus in ``(0, 1]`` — 1.0 for never-retrieved entries."""
        usage = float(metadata.get("usage_count", 0) or 0)
        return 1.0 / (usage + 1.0)

    def _collect_candidates(
        self,
        query_text: str,
        filters: Optional[Dict[str, Any]],
        top_k: int,
        score_threshold: float,
        design_layer: str,
    ) -> List[Any]:
        """Fetch the rerank candidate pool for one layer.

        ``score_threshold`` is a cosine-similarity floor — see
        :meth:`DiagramDesignMemory.search_design_item`.
        """
        fetch_k = max(top_k, self.rerank_top_n)
        docs = self.design_memory.search_design_item(
            design_layer=design_layer,
            query_text=query_text,
            top_k=fetch_k,
            score_threshold=score_threshold,
            filters=filters,
        )
        return [doc for doc in docs if doc.metadata.get("score", 0.0) >= score_threshold]

    def _rerank_candidates(
        self,
        query_text: str,
        candidates: List[Any],
        *,
        top_k: int = 5,
        embedding_cache: Optional[Dict[Tuple[str, str], Optional[List[float]]]] = None,
    ) -> List[Any]:
        if not candidates:
            return []

        embedding_cache = embedding_cache if embedding_cache is not None else {}
        # Query and candidates must go through the same normalisation, or the
        # two sides are embedded from different text distributions and the
        # cosine similarity between them is not comparable across candidates.
        normalized_query = self._normalize_text(query_text)
        query_emb = self._embed_query(normalized_query, embedding_cache)
        candidate_texts = [
            self._normalize_text(self._item_text(doc))
            for doc in candidates
        ]
        candidate_embedding_failed = self._embed_candidate_texts(
            candidate_texts,
            embedding_cache,
        )
        cached_candidate_missing = any(
            text and embedding_cache.get(("candidate", text)) is None
            for text in candidate_texts
        )
        embedding_degraded = (
            query_emb is None
            or candidate_embedding_failed
            or cached_candidate_missing
        )

        candidate_rows = []
        for doc, text in zip(candidates, candidate_texts):
            metadata = getattr(doc, "metadata", {}) or {}
            doc_emb = self._cached_candidate_embedding(text, embedding_cache)
            if query_emb is not None and doc_emb is not None:
                # One relevance definition only. Mixing the store's relevance
                # score with a recomputed cosine via ``max()`` compared two
                # different scales, so the winner was decided by which text
                # path a candidate happened to take rather than by fit.
                relevance = _clamp_unit(self._cosine_similarity(query_emb, doc_emb))
            else:
                # Degraded path: the store's own cosine relevance score.
                relevance = _clamp_unit(float(metadata.get("score", 0.0) or 0.0))
            candidate_rows.append({
                "doc": doc,
                "relevance": relevance,
                "utility": self._utility_score(metadata),
                "exploration": self._exploration_score(metadata),
                "text": text,
                "emb": doc_emb,
            })

        relevance_weight = self._relevance_weight
        selected: List[Dict[str, Any]] = []
        remaining = candidate_rows[:]
        while remaining and len(selected) < top_k:
            penalties = self._diversity_penalties(remaining, selected)
            best_row = None
            best_score = float("-inf")
            for row in remaining:
                final_score = (
                    (relevance_weight * row["relevance"])
                    + (self._utility_weight * row["utility"])
                    + (self._exploration_weight * row["exploration"])
                    - (self._diversity_weight * penalties[id(row)])
                )
                if final_score > best_score:
                    best_score = final_score
                    best_row = row
            if best_row is None:
                break
            selected.append(best_row)
            remaining.remove(best_row)

        ordered = [row["doc"] for row in selected]
        if len(ordered) < min(top_k, len(candidates)):
            selected_ids = {doc.metadata.get("id") for doc in ordered}
            for row in sorted(candidate_rows, key=lambda r: r["relevance"], reverse=True):
                doc_id = row["doc"].metadata.get("id")
                if doc_id in selected_ids:
                    continue
                ordered.append(row["doc"])
                selected_ids.add(doc_id)
                if len(ordered) >= min(top_k, len(candidates)):
                    break
        if embedding_degraded:
            self._mark_rerank_degraded(
                ordered,
                "embedding unavailable; used vector score and heuristic rerank",
            )
        return ordered

    @classmethod
    def _diversity_penalties(
        cls,
        remaining: List[Dict[str, Any]],
        selected: List[Dict[str, Any]],
    ) -> Dict[int, float]:
        """MMR redundancy penalty for each remaining row, keyed by ``id(row)``.

        Candidates whose embedding is missing get the mean penalty of the
        candidates that do have one, instead of 0.0. A zero penalty is not
        neutral: with the shipped weights the diversity term is worth up to
        0.20 while utility is worth 0.25 and exploration 0.10, so an
        embedding-less candidate used to gain up to 0.20 over every embedded
        rival in each round purely because its similarity could not be
        measured. When no candidate in the round has an embedding the penalty
        is 0.0 for all of them, which is uniform and therefore rank-neutral.
        """
        if not selected:
            return {id(row): 0.0 for row in remaining}

        selected_embeddings = [
            picked["emb"] for picked in selected if picked["emb"] is not None
        ]
        penalties: Dict[int, float] = {}
        measured: List[float] = []
        for row in remaining:
            if row["emb"] is None or not selected_embeddings:
                continue
            penalty = _clamp_unit(
                max(
                    cls._cosine_similarity(row["emb"], picked)
                    for picked in selected_embeddings
                )
            )
            penalties[id(row)] = penalty
            measured.append(penalty)

        fallback = sum(measured) / len(measured) if measured else 0.0
        for row in remaining:
            penalties.setdefault(id(row), fallback)
        return penalties

    def _resolve_design_types(
        self,
        types: Optional[Union[str, list]] = "all",
    ) -> List[str]:
        if types is None or types == "all":
            return self.design_types
        elif isinstance(types, str):
            return [self._validate_type(types)]
        elif isinstance(types, list):
            resolved = [self._validate_type(kt) for kt in types]
            return resolved if resolved else self.design_types
        else:
            raise ValueError("'types' must be 'all', a string, a list of strings, or None")

    @_reuse_query_embeddings
    def retrieve_knowledge(
        self,
        query: Any,
        types: Optional[Union[str, list]] = "all",
        top_k: int = 5,
        score_threshold: float = 0.0,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        design_types = self._resolve_design_types(types)
        embedding_cache: Dict[Tuple[str, str], Optional[List[float]]] = {}
        return {
            kt: self._search_and_rerank(
                query_text=query,
                filters=filters,
                top_k=top_k,
                score_threshold=score_threshold,
                design_layer=kt,
                embedding_cache=embedding_cache,
            )
            for kt in design_types
        }

    @_reuse_query_embeddings
    def retrieve_knowledge_by_layer(
        self,
        query: Any,
        *,
        layer_filters: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
        types: Optional[Union[str, list]] = "all",
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """Retrieve knowledge with layer-specific metadata filters.

        Use this when metadata keys differ by design layer, such as flattened
        tag fields prefixed with ``strategy_``, ``guideline_``, or
        ``principle_``. Embedding rerank state is shared across layers to avoid
        repeated query/candidate embeddings within one retrieval request.
        """
        design_types = self._resolve_design_types(types)
        normalized_layer_filters = {
            self._validate_type(layer): layer_filter
            for layer, layer_filter in (layer_filters or {}).items()
        }

        embedding_cache: Dict[Tuple[str, str], Optional[List[float]]] = {}
        return {
            layer: self._search_and_rerank(
                query_text=query,
                filters=normalized_layer_filters.get(layer),
                top_k=top_k,
                score_threshold=score_threshold,
                design_layer=layer,
                embedding_cache=embedding_cache,
            )
            for layer in design_types
        }

    def _search_and_rerank(
        self,
        query_text: str,
        filters: Optional[Dict[str, Any]],
        top_k: int,
        score_threshold: float,
        design_layer: str,
        embedding_cache: Optional[Dict[Tuple[str, str], Optional[List[float]]]] = None,
    ) -> List[Any]:
        candidates = self._collect_candidates(
            query_text=query_text,
            filters=filters,
            top_k=top_k,
            score_threshold=score_threshold,
            design_layer=design_layer,
        )
        return self._rerank_candidates(
            query_text,
            candidates,
            top_k=top_k,
            embedding_cache=embedding_cache,
        )

    # ── Prompt-facing retrieval (public integration entry point) ─────

    @staticmethod
    def _build_diagram_type_filter(diagram_type: str, layer: str) -> Optional[Dict[str, Any]]:
        """Build a ChromaDB metadata filter for ``diagram_type`` on a specific layer.

        Knowledge entries store diagram_type as a list in tags, which gets
        flattened to boolean flags like ``strategy_diagram_type_flowchart``.
        This helper builds a filter matching the flattened key.
        """
        if not diagram_type or diagram_type.lower() == "general":
            return None
        key = f"{layer}_diagram_type_{diagram_type.strip().lower().replace(' ', '_')}"
        return {key: True}

    @staticmethod
    def _combine_metadata_filters(*filters: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        terms = [dict(filter_value) for filter_value in filters if filter_value]
        if not terms:
            return None
        if len(terms) == 1:
            return terms[0]
        return {"$and": terms}

    @classmethod
    def _build_active_positive_filter(
        cls,
        diagram_type_filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return cls._combine_metadata_filters(
            {"active": True},
            {"polarity": "positive"},
            diagram_type_filter,
        ) or {"active": True}

    @staticmethod
    def _doc_identity(doc: Any) -> str:
        metadata = getattr(doc, "metadata", None)
        if isinstance(metadata, dict):
            doc_id = metadata.get("id") or metadata.get("item_id")
            if doc_id:
                return f"id:{doc_id}"
        page_content = getattr(doc, "page_content", None)
        if isinstance(page_content, (dict, list)):
            try:
                return "content:" + json.dumps(page_content, sort_keys=True, ensure_ascii=False)
            except TypeError:
                return f"object:{id(doc)}"
        return f"content:{page_content}"

    @staticmethod
    def _doc_metadata_id(doc: Any) -> Optional[str]:
        metadata = getattr(doc, "metadata", None)
        if not isinstance(metadata, dict):
            return None
        doc_id = metadata.get("id") or metadata.get("item_id")
        return str(doc_id) if doc_id else None

    @staticmethod
    def _is_general_diagram_doc(doc: Any, layer: str) -> bool:
        metadata = getattr(doc, "metadata", None)
        if not isinstance(metadata, dict):
            return True
        prefix = f"{layer}_diagram_type_"
        flags = [
            key
            for key, value in metadata.items()
            if key.startswith(prefix) and value is True
        ]
        if not flags:
            return True
        return any(key in {f"{prefix}general", f"{prefix}universal"} for key in flags)

    def _merge_exact_and_general_docs(
        self,
        exact_docs: Dict[str, List[Any]],
        general_docs: Dict[str, List[Any]],
    ) -> Dict[str, List[Any]]:
        merged: Dict[str, List[Any]] = {}
        for layer in self.design_types:
            layer_docs = list(exact_docs.get(layer, []))
            seen = {self._doc_identity(doc) for doc in layer_docs}
            added_general = 0
            for doc in general_docs.get(layer, []):
                if not self._is_general_diagram_doc(doc, layer):
                    continue
                identity = self._doc_identity(doc)
                if identity in seen:
                    continue
                layer_docs.append(doc)
                seen.add(identity)
                added_general += 1
                if added_general >= GENERAL_RETRIEVAL_TOP_K:
                    break
            merged[layer] = layer_docs
        return merged

    @staticmethod
    def _is_active_positive_doc(doc: Any, content_json: Any = None) -> bool:
        metadata = getattr(doc, "metadata", None)
        sources = []
        if isinstance(metadata, dict):
            sources.append(metadata)
        if isinstance(content_json, dict):
            sources.append(content_json)

        inactive_statuses = {"pruned", "retired"}
        for source in sources:
            active = source.get("active")
            if active is False:
                return False
            polarity = source.get("polarity")
            if polarity is not None and polarity != "positive":
                return False
            status = source.get("generalization_status")
            if isinstance(status, str) and status in inactive_statuses:
                return False
        return True

    @_reuse_query_embeddings
    def retrieve_design_expertise(
        self,
        user_query: str,
        *,
        diagram_type: str = "",
        content_area: str = "",
        retrieval_query: str = "",
        top_k: int = DEFAULT_RETRIEVAL_TOP_K,
        score_threshold: float = 0.0,
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Retrieve design knowledge already formatted for a generator prompt.

        This is the entry point for callers that want to *inject* knowledge into
        generation. It owns the rules that make retrieved knowledge safe to show
        a model, so callers must not rebuild them:

        - only ``active=True``, ``polarity="positive"`` entries are returned, so
          archived tombstones, neutral audit records and anti-patterns can never
          reach a prompt;
        - ``diagram_type`` is matched against the layer-prefixed flattened
          metadata flags, with a small quota of diagram-type-agnostic
          ("general" / "universal") entries merged in so a rare diagram type
          still gets cross-cutting guidance.

        Args:
            user_query: the user's request; used as the semantic query when no
                ``retrieval_query`` is supplied.
            diagram_type: e.g. ``"flowchart"``. ``""`` or ``"general"`` disables
                diagram-type filtering.
            content_area: e.g. ``"Software Engineering"``. Only widens the
                semantic query text; there is no content-area metadata filter.
            retrieval_query: a purpose-built search query (e.g. from a router
                agent). Takes precedence over ``user_query``.
            top_k: entries per layer before the general-knowledge merge.
            score_threshold: cosine-similarity floor (see
                :meth:`DiagramDesignMemory.search_design_item`).

        Returns:
            ``(formatted_text, retrieved_items)``.

            ``formatted_text`` is a prompt-ready string with one
            ``=== STRATEGY|GUIDELINE|PRINCIPLE ===`` section per non-empty
            layer, each entry rendered as ``Title: ...\nContent: ...``. It is
            ``""`` when nothing matched — safe to pass straight through as
            ``design_expertise``.

            ``retrieved_items`` is a list of ``{"id": str, "layer": str}`` in
            retrieval order, one per entry that actually made it into the text.
            Callers that track knowledge performance must feed these back; a
            caller that only injects knowledge can ignore them.
        """
        # Build the semantic search query: prefer Router-generated query,
        # else fall back to diagram_type + user_query (no raw text truncation).
        if retrieval_query:
            search_query = retrieval_query
        elif diagram_type and diagram_type.lower() != "general":
            search_query = f"{diagram_type} diagram: {user_query}"
        else:
            search_query = user_query
        if content_area:
            search_query = f"{search_query} ({content_area})"

        # Query through the retriever's public per-layer API because flattened
        # metadata keys are layer-prefixed (strategy_, guideline_, principle_).
        diagram_type_filters = {
            layer: self._build_diagram_type_filter(diagram_type, layer)
            for layer in self.design_types
        }
        layer_filters = {
            layer: self._build_active_positive_filter(diagram_type_filter)
            for layer, diagram_type_filter in diagram_type_filters.items()
        }
        retrieved_docs = self.retrieve_knowledge_by_layer(
            search_query,
            layer_filters=layer_filters,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        if any(layer_filter is not None for layer_filter in diagram_type_filters.values()):
            general_docs = self.retrieve_knowledge_by_layer(
                search_query,
                layer_filters={
                    layer: self._build_active_positive_filter()
                    for layer in self.design_types
                },
                top_k=top_k + GENERAL_RETRIEVAL_TOP_K,
                score_threshold=score_threshold,
            )
            retrieved_docs = self._merge_exact_and_general_docs(
                retrieved_docs,
                general_docs,
            )

        # Collect raw docs for usage tracking (id, layer, metadata)
        retrieved_items = []

        parts = []
        for layer, docs in retrieved_docs.items():
            if not docs:
                continue
            content_list = []
            for doc in docs:
                doc_id = self._doc_metadata_id(doc)
                content_json = None
                if isinstance(doc.page_content, str):
                    try:
                        content_json = json.loads(doc.page_content)
                    except Exception:
                        if not self._is_active_positive_doc(doc):
                            continue
                        content_list.append(doc.page_content)
                        if doc_id:
                            retrieved_items.append({"id": doc_id, "layer": layer})
                        continue
                elif isinstance(doc.page_content, (dict, list)):
                    content_json = doc.page_content
                else:
                    if not self._is_active_positive_doc(doc):
                        continue
                    content_list.append(str(doc.page_content))
                    if doc_id:
                        retrieved_items.append({"id": doc_id, "layer": layer})
                    continue

                if not self._is_active_positive_doc(doc, content_json):
                    continue

                if doc_id:
                    retrieved_items.append({"id": doc_id, "layer": layer})

                if isinstance(content_json, dict):
                    if not doc_id:
                        cid = content_json.get("id") or content_json.get("item_id")
                        if cid:
                            doc_id = cid
                            retrieved_items.append({"id": cid, "layer": layer})
                    desc = content_json.get("content", "") or content_json.get("description", "")
                    title = content_json.get("title", "")
                    if title:
                        content_list.append(f"Title: {title}\nContent: {desc}")
                    else:
                        content_list.append(str(desc))
                else:
                    content_list.append(str(content_json))

            section_text = "\n\n".join(content_list)
            parts.append(f"=== {layer.upper()} ===\n{section_text}")

        formatted = "\n\n".join(parts)
        return formatted, retrieved_items

    def _validate_type(self, design_layer: str):
        normalized = normalize_layer(design_layer)
        if normalized not in self.design_types:
            raise ValueError(
                f"design_layer '{design_layer}' must resolve to one of {self.design_types}"
            )
        return normalized
