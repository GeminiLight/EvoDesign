import json
from typing import Any, Dict, List, Union


def print_retrieval_results(results: Any, limit: int = 3, save_path: str | None = None):
    docs, metas, dists, ids = [], [], [], []
    if isinstance(results, list):
        for doc in results:
            if hasattr(doc, 'page_content'):
                docs.append(doc.page_content)
                meta = getattr(doc, 'metadata', {})
                metas.append(meta)
                dists.append(meta.get('score', 0.0))
                ids.append(meta.get('id', None))
    elif isinstance(results, dict):
        docs_list = results.get("documents", [])
        docs = docs_list[0] if docs_list and isinstance(docs_list[0], list) else docs_list
        metas_list = results.get("metadatas", [])
        metas = metas_list[0] if metas_list and isinstance(metas_list[0], list) else metas_list
        dists_list = results.get("distances", [])
        dists = dists_list[0] if dists_list and isinstance(dists_list[0], list) else dists_list
        ids_list = results.get("ids", [])
        ids = ids_list[0] if ids_list and isinstance(ids_list[0], list) else ids_list

    if not docs:
        print("  (no results)")
        return

    metas = metas or ([{}] * len(docs))
    dists = dists or ([0.0] * len(docs))
    ids = ids or ([None] * len(docs))

    serialized: List[Dict[str, Any]] = []

    for i, (doc, meta, dist, _id) in enumerate(zip(docs, metas, dists, ids)):
        if i >= limit:
            break
        snippet = str(doc)[:120].replace("\n", " ")
        print(f"-" * 80)
        print(f"{i+1}. id={_id} | score={dist:.4f}")
        print(f"    {snippet}...")

        serialized.append({
            "id": _id,
            "score": dist,
            "snippet": snippet,
            "doc": doc,
            "metadata": meta,
        })

    if save_path and serialized:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(serialized, f, ensure_ascii=True, indent=2)


def stringify_knowledge_item(knowledge_item: Dict[str, Any]) -> str:
    """Converts a knowledge item dictionary to a readable string format."""
    parts = []
    if 'id' in knowledge_item:
        parts.append(f"id={knowledge_item['id']}")
    if 'title' in knowledge_item:
        parts.append(f"title={knowledge_item['title']}")
    if 'design_layer' in knowledge_item:
        parts.append(f"layer={knowledge_item['design_layer']}")
    if 'content' in knowledge_item:
        snippet = str(knowledge_item['content'])[:100].replace("\n", " ")
        parts.append(f"content='{snippet}...'")
    return " | ".join(parts)
