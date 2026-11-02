#!/usr/bin/env python3
"""Bench 选择（库模块）：每个组合从 keep 图中选出最佳 1 张进 Bench。

输入 dataset/filtered.json（keep 行），对每组合：
  - 仅 1 张 keep：直接入选（不调 VLM）
  - ≥2 张 keep：一次多图 VLM 调用选出 best
输出 dataset/bench.json，断点续跑。

命令行入口见 main.py（bench 子命令）。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from filter_and_describe import REPO_ROOT, VLMClient, expectation

HERE = Path(__file__).resolve().parent
FILTERED_JSON = REPO_ROOT / "dataset" / "filtered.json"
BENCH_JSON = REPO_ROOT / "dataset" / "bench.json"

WORKERS = 5

BENCH_PROMPT = """You are curating a diagram benchmark. Attached are {n} candidate
images (Image 1..{n}) for the combo "{expect}". All were pre-validated as clean,
canvas-reproducible diagrams on the same topic.

Select the ONE best image for the benchmark. Criteria (in priority order):
1. Strict reproducibility: pure vector-like shapes and connectors that a tool
   like Excalidraw/tldraw can rebuild one-to-one.
2. Structural clarity: labels legible, even font sizing, layout neither cramped
   nor sparse, reading flow obvious.
3. Topological richness: informative structure, not trivial (avoid 2-3 node toys),
   but not an unreadable hairball either - moderate-to-rich is ideal.
4. Topical representativeness: a typical exemplar of "{expect}", not an edge case.
5. Clean and self-contained: no watermarks, no brand logos, no webpage-frame or
   screenshot feel; understandable without any external context.

OUTPUT JSON only, no markdown, no prose:
{{"best": <index>, "reason": "<15 words>"}}"""


class BenchStore:
    """dataset/bench.json 的读写。"""

    def __init__(self, path: Path = BENCH_JSON):
        self.path = path
        self.rows: list[dict] = []
        if path.exists():
            self.rows = json.loads(path.read_text())

    @property
    def done_combos(self) -> set[str]:
        return {r["combo"] for r in self.rows}

    def append(self, row: dict) -> None:
        self.rows.append(row)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.rows, ensure_ascii=False))
        tmp.replace(self.path)


class BenchSelector:
    def __init__(self, client: VLMClient, store: BenchStore):
        self.client = client
        self.store = store

    def run(self, combos_filter: str = "", limit: int = 0) -> None:
        groups = self._group_keeps(combos_filter)
        done = self.store.done_combos
        todo = {c: rows for c, rows in groups.items() if c not in done}
        if limit:
            todo = dict(list(todo.items())[:limit])
        print(f"[bench] 待选 {len(todo)} 组合, 已完成 {len(done)}")

        finished = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(self._select_one, combo, rows): combo
                       for combo, rows in todo.items()}
            for fut in as_completed(futures):
                row = fut.result()
                if row:
                    self.store.append(row)
                finished += 1
                if finished % 20 == 0:
                    self.store.save()
                    print(f"[bench] {finished}/{len(todo)}", flush=True)
        self.store.save()
        print(f"[bench] 完成: bench 共 {len(self.store.rows)} 条")

    @staticmethod
    def _group_keeps(combos_filter: str) -> dict[str, list[dict]]:
        wanted = set(combos_filter.split(",")) if combos_filter else None
        groups: dict[str, list[dict]] = {}
        for r in json.loads(FILTERED_JSON.read_text()):
            if not r.get("keep"):
                continue
            if wanted and r["combo"] not in wanted:
                continue
            groups.setdefault(r["combo"], []).append(r)
        return groups

    def _select_one(self, combo: str, rows: list[dict]) -> dict | None:
        rows = rows[:5]  # 最多送5张（并发在飞可能略超target）
        if len(rows) == 1:  # 只有1张 keep，直接入选，省一次调用
            return {**rows[0], "bench_reason": "only candidate",
                    "bench_candidates": 1}

        text = self.client.complete(
            [REPO_ROOT / r["local_path"] for r in rows],
            BENCH_PROMPT.format(n=len(rows), expect=expectation(combo)))
        try:
            m = re.search(r"\{.*\}", text, re.S)
            result = json.loads(m.group())
            best = rows[int(result["best"]) - 1]
            return {**best, "bench_reason": result.get("reason", ""),
                    "bench_candidates": len(rows)}
        except Exception as e:
            print(f"  [bench] {combo} 选择失败: {e}", flush=True)
            return None
