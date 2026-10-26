#!/usr/bin/env python3
"""S4 组装（库模块）：filtered.json (keep) + bench.json -> dataset/final.json。

每条记录：
  id, combo, diagram_type, vertical_domain, image_url (本地路径),
  source_url (原始网络URL), page_url, content, query, bench (bool)

命令行入口见 main.py（assemble 子命令）。
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
FILTERED_JSON = REPO_ROOT / "dataset" / "filtered.json"
BENCH_JSON = REPO_ROOT / "dataset" / "bench.json"
FINAL_JSON = REPO_ROOT / "dataset" / "final.json"


class DatasetAssembler:
    def __init__(self,
                 filtered_path: Path = FILTERED_JSON,
                 bench_path: Path = BENCH_JSON,
                 final_path: Path = FINAL_JSON):
        self.filtered_path = filtered_path
        self.bench_path = bench_path
        self.final_path = final_path

    def run(self) -> None:
        filtered = json.loads(self.filtered_path.read_text())
        bench_pairs = set()
        if self.bench_path.exists():
            for r in json.loads(self.bench_path.read_text()):
                bench_pairs.add((r["local_path"], r["combo"]))

        # 保留已有 final.json 中的 other_queries（assemble 重跑不丢变体）
        existing_variants = {}
        if self.final_path.exists():
            for r in json.loads(self.final_path.read_text()):
                if r.get("other_queries"):
                    existing_variants[r["id"]] = r["other_queries"]

        by_combo: dict[str, list[dict]] = {}
        for r in filtered:
            if r.get("keep") and not r.get("deprecated"):
                by_combo.setdefault(r["combo"], []).append(r)

        records: list[dict] = []
        for combo, rows in sorted(by_combo.items()):
            diagram_type, domain = combo.split("|", 1)
            for i, r in enumerate(rows, 1):
                record_id = f"{diagram_type}_{domain.lower().replace(' ', '-')}_{i:02d}"
                rec = {
                    "id": record_id,
                    "combo": combo,
                    "diagram_type": diagram_type,
                    "vertical_domain": domain,
                    "image_url": r["local_path"],
                    "source_url": r["image_url"],
                    "page_url": r["page_url"],
                    "content": r["content"],
                    "query": r["query"],
                    "bench": (r["local_path"], combo) in bench_pairs,
                }
                if record_id in existing_variants:
                    rec["other_queries"] = existing_variants[record_id]
                records.append(rec)

        tmp = self.final_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=1))
        tmp.replace(self.final_path)

        bench_n = sum(1 for r in records if r["bench"])
        counts = [len(v) for v in by_combo.values()]
        print(f"[assemble] final.json: {len(records)} 条, "
              f"{len(by_combo)} 组合, bench {bench_n} 条")
        print(f"[assemble] 每组合图片数: min {min(counts)}, "
              f"中位 {sorted(counts)[len(counts) // 2]}, max {max(counts)}")
