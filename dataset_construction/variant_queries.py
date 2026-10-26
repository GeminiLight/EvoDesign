#!/usr/bin/env python3
"""变体 query 合成（库模块）：为 final.json 记录生成 other_queries。

每条记录 8 个变体，受控双轴设计：
  - 4 个 focus 变体：diagram_type 不变，换 4 个内容聚焦视角（axis="focus"）
  - 4 个 type 变体：聚焦视角不变，换 4 种图表类型（axis="type"）
格式对齐原数据 other_queries（content_focus/diagram_type/user_query），
额外带 axis 字段便于单变量对比分析。纯文本调用（不看图），断点续跑。

命令行入口见 main.py（variants 子命令）。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from filter_and_describe import REPO_ROOT, VLMClient

FINAL_JSON = REPO_ROOT / "dataset" / "final.json"

WORKERS = 5
SAVE_EVERY = 50

DIAGRAM_TYPES = ("architecture, class, concept, dataflow, er, fishbone, flowchart, "
                 "funnel, gantt, hybrid, matrix, mindmap, orgchart, pyramid, "
                 "sequence, state, swimlane, swot, timeline, tree, venn")

VARIANT_PROMPT = """You are enriching a diagram dataset. Given one record:
- diagram_type: {diagram_type}
- vertical_domain: {domain}
- canonical query: {query}
- content: {content}

Generate 8 ALTERNATIVE user requirements for the SAME content, in TWO controlled groups:

GROUP A - 4 focus variants: keep diagram_type = "{diagram_type}" UNCHANGED for all
4, vary ONLY the analytical perspective. Use 4 genuinely distinct content_focus
angles (e.g., stakeholder/responsibility, process/workflow, information flow,
decision logic, temporal phasing, hierarchy/organization, comparison, causality).

GROUP B - 4 type variants: keep ONE single content_focus (the core perspective of
the content) UNCHANGED across all 4, vary ONLY the diagram_type: pick 4 distinct
types from: {types}, each genuinely suited to render this content.

For each variant output:
- "content_focus": short phrase naming the perspective
- "diagram_type": as constrained above
- "user_query": one natural user instruction expressing that requirement

OUTPUT JSON only, no markdown, no prose:
{{"focus_variants":[{{"content_focus":"...","diagram_type":"...","user_query":"..."}},x4],
"type_variants":[{{"content_focus":"...","diagram_type":"...","user_query":"..."}},x4]}}"""


class VariantQueryGenerator:
    def __init__(self, client: VLMClient, path: Path = FINAL_JSON):
        self.client = client
        self.path = path
        self.records: list[dict] = json.loads(path.read_text())

    def run(self, limit: int = 0) -> None:
        todo = [r for r in self.records if "other_queries" not in r]
        if limit:
            todo = todo[:limit]
        print(f"[variants] 待生成 {len(todo)} 条")

        done = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(self._gen_one, r): r for r in todo}
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if done % SAVE_EVERY == 0:
                    self._save()
                    print(f"[variants] {done}/{len(todo)}", flush=True)
        self._save()
        ok = sum(1 for r in self.records if r.get("other_queries"))
        print(f"[variants] 完成: {ok} 条记录已有 other_queries")

    def _gen_one(self, record: dict) -> None:
        text = self.client.complete([], VARIANT_PROMPT.format(
            diagram_type=record["diagram_type"], domain=record["vertical_domain"],
            query=record["query"], content=record["content"],
            types=DIAGRAM_TYPES))
        try:
            m = re.search(r"\{.*\}", text, re.S)
            groups = json.loads(m.group())
            out = []
            for axis, key in (("focus", "focus_variants"),
                              ("type", "type_variants")):
                for v in groups.get(key, [])[:4]:
                    out.append({"axis": axis,
                                "content_focus": v.get("content_focus", ""),
                                "diagram_type": v.get("diagram_type", ""),
                                "user_query": v.get("user_query", "")})
            record["other_queries"] = out
        except Exception as e:
            print(f"  [variants] {record['id']} 失败: {e}", flush=True)

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.records, ensure_ascii=False, indent=1))
        tmp.replace(self.path)
