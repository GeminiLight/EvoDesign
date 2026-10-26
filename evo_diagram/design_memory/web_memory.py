"""Bootstrap scoped web memories and learn only from verified improvements."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def prepare_web_memory(path: str, embedding_model: str, seed_path: str) -> None:
    # Use the same process cache as generation; do not load the embedder twice.
    from evo_diagram.agentic_system.workflow import _load_design_memory_retriever

    with _LOCK:
        Path(path).mkdir(parents=True, exist_ok=True)
        retriever, error = _load_design_memory_retriever(path, embedding_model)
        if retriever is None:
            raise RuntimeError(error or "Design memory could not be initialized")
        marker = Path(path) / "seed.json"
        if not Path(seed_path).is_file():
            return
        source_hash = hashlib.sha256(Path(seed_path).read_bytes()).hexdigest()
        if marker.exists() and json.loads(marker.read_text()).get("source_sha256") == source_hash:
            return
        rows = json.loads(Path(seed_path).read_text())
        if not isinstance(rows, list):
            raise ValueError("Design memory seed must be a JSON array")
        memory = retriever.design_memory
        existing = {str(row.get("id")) for row in memory.load_all_items("strategy")}
        items = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("id") or not row.get("content"):
                continue
            item_id = "seed_" + str(row["id"])
            if item_id in existing:
                continue
            diagram_type = {"concept": "concept_map", "flow": "flowchart"}.get(
                row.get("diagram_type"), row.get("diagram_type", "general")
            )
            items.append({**row, "id": item_id, "active": True, "polarity": "positive",
                          "tags": {"diagram_type": [diagram_type],
                                   "domain": [row.get("domain", "general")],
                                   "agent": [row.get("agent", "Layout")]}})
        if items:
            memory.save_design_memory(items, "strategy")
        marker.write_text(json.dumps({"source_sha256": source_hash, "seed_count": len(rows)}))


def learn_verified_refinement(
    *, retriever: Any, model: Any, report_path: str, diagram_type: str,
    before: dict[str, Any], after: dict[str, Any], request_id: str,
) -> dict[str, Any]:
    """Distill edits into private, task-specific strategies, never principles.

    The caller must first accept the final artifact after verification. A clean
    final score alone is not evidence that the edits improved the first draft.
    """
    from evo_diagram.agentic_system.quality_policy import verified_learning_gain
    if not verified_learning_gain(before, after):
        return {"status": "skipped", "reason": "no_verified_gain", "saved_count": 0}
    report = json.loads(Path(report_path).read_text())
    edits = [row["edit"] for iteration in report.get("iterations", [])
             if not iteration.get("rolled_back")
             and not any("rolled back" in note for note in iteration.get("notes", []))
             for key in ("deterministic_edits", "llm_edits")
             for row in iteration.get(key, []) if row.get("applied") and row.get("edit")]
    if not edits:
        return {"status": "skipped", "reason": "no_applied_edits", "saved_count": 0}
    from evo_diagram.knowledge_evolution.distillation.curators import StrategyExtractorAgent

    strategies = StrategyExtractorAgent(model).run(
        text_content="Extract reusable visual design lessons from verified edits only.",
        domain="general", diagram_type=diagram_type,
        iteration_history=json.dumps({"before": before, "after": after,
                                      "applied_edits": edits}, ensure_ascii=False),
    )
    if not isinstance(strategies, dict) or set(strategies) - {"parse", "styling", "layout"}:
        raise ValueError("Invalid strategy extraction result")
    items = []
    for category, value in strategies.items():
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str) or not value[key].strip()
            for key in ("title", "description", "content", "when_to_use")
        ):
            raise ValueError("Incomplete strategy extraction result")
        digest = hashlib.sha256((diagram_type + category + value["content"]).encode()).hexdigest()[:24]
        items.append({**value, "id": "web_" + digest, "active": True, "polarity": "positive",
                      "tier": "sample_strategy", "confidence": 0.6,
                      "tags": {"diagram_type": [diagram_type], "domain": ["general"],
                               "agent": [{"parse": "Structure", "styling": "Styling", "layout": "Layout"}[category]]},
                      "provenance": {"request_id": request_id, "before": before, "after": after}})
    with _LOCK:
        existing = {str(row.get("id")) for row in retriever.design_memory.load_all_items("strategy")}
        items = [row for row in items if row["id"] not in existing]
        if items:
            retriever.design_memory.save_design_memory(items, "strategy")
    return {"status": "saved" if items else "skipped", "saved_count": len(items),
            "saved_ids": [row["id"] for row in items]}
