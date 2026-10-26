import json
import os
import sys
import time
from typing import Any, Dict, List


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def make_backup(path: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.bak_{ts}"
    with open(path, "rb") as src, open(backup_path, "wb") as dst:
        dst.write(src.read())
    return backup_path


def extract_other_queries(obj_list: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    other: List[Dict[str, str]] = []
    for item in obj_list:
        # skip meta objects or anything missing required keys
        if not isinstance(item, dict):
            continue
        if "_meta" in item:
            continue
        cf = item.get("content_focus")
        dt = item.get("diagram_type")
        uq = item.get("user_query")
        if cf and dt and uq:
            other.append({
                "content_focus": str(cf),
                "diagram_type": str(dt),
                "user_query": str(uq),
            })
    return other


def merge_other_queries(dataset_path: str, results_dir: str):
    dataset = load_json(dataset_path)
    if not isinstance(dataset, list):
        raise ValueError("dataset.json is expected to be a JSON array of objects")

    # index dataset entries by id
    by_id: Dict[str, Dict[str, Any]] = {}
    for entry in dataset:
        if isinstance(entry, dict) and "id" in entry:
            by_id[str(entry["id"]) ] = entry

    processed = 0
    matched = 0
    created = 0
    skipped = 0
    missing_ids: List[str] = []

    for fn in os.listdir(results_dir):
        if not fn.endswith("_queries.json"):
            continue
        full_path = os.path.join(results_dir, fn)
        try:
            data = load_json(full_path)
        except Exception as e:
            print(f"[WARN] Failed to load {full_path}: {e}")
            skipped += 1
            continue

        # each file is expected to be {"<id>": [ ... ]}
        if not isinstance(data, dict) or len(data) != 1:
            print(f"[WARN] Unexpected structure in {full_path}, skipping.")
            skipped += 1
            continue

        result_id, obj_list = next(iter(data.items()))
        processed += 1

        other = extract_other_queries(obj_list if isinstance(obj_list, list) else [])
        if not other:
            print(f"[INFO] No other_queries extracted from {fn}")
            continue

        target = by_id.get(result_id)
        if not target:
            missing_ids.append(result_id)
            continue

        # Merge: append new items, deduplicate by user_query
        existing = target.get("other_queries", [])
        if not isinstance(existing, list):
            existing = []

        # Dedup by user_query
        seen = {str(item.get("user_query")) for item in existing if isinstance(item, dict)}
        for item in other:
            uq = item["user_query"]
            if uq in seen:
                continue
            existing.append(item)
            seen.add(uq)

        target["other_queries"] = existing
        matched += 1

    stats = {
        "processed_files": processed,
        "matched_entries": matched,
        "created_other_queries": created,
        "skipped_files": skipped,
        "missing_ids": missing_ids,
        "total_dataset_entries": len(dataset),
    }
    return dataset, stats


def main():
    # Defaults relative to repository root
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dataset_path = os.path.join(repo_root, "dataset", "train", "data.json")
    results_dir = os.path.join(repo_root, "dataset_construction", "baseline_content2query", "results")

    # Allow overrides via CLI args
    if len(sys.argv) >= 2:
        dataset_path = sys.argv[1]
    if len(sys.argv) >= 3:
        results_dir = sys.argv[2]

    print(f"[INFO] Loading dataset from: {dataset_path}")
    print(f"[INFO] Reading results from: {results_dir}")

    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"dataset.json not found: {dataset_path}")
    if not os.path.isdir(results_dir):
        raise FileNotFoundError(f"results directory not found: {results_dir}")

    merged_dataset, stats = merge_other_queries(dataset_path, results_dir)

    # Persist changes to a new file
    output_path = os.path.join(repo_root, "dataset", "train", "dataset_with_other_queries.json")
    # Allow optional 3rd arg override for output path
    if len(sys.argv) >= 4:
        output_path = sys.argv[3]
    save_json(output_path, merged_dataset)

    print("[DONE] Merge complete.")
    print(json.dumps({**stats, "output_path": output_path}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
