#!/usr/bin/env python3
"""设计专家记忆生成（库模块）：对齐论文三层记忆 M = {K^s, K^g, K^p}。

- K^s sample strategies：从 bench 记录（verified samples）蒸馏，带 provenance
- K^g domain guidelines：按 30 个 MMMU 领域蒸馏领域规则
- K^p general principles：从指南抽象出的通用设计公理

条目 schema 对齐论文附录（result-analysis.tex）：
  tier / agent / domain / diagram_type / title / description / content /
  when_to_use / confidence / provenance|promoted_from

输出 dataset/design_memory.json，断点续跑。
命令行入口见 main.py（memory 子命令）。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from filter_and_describe import REPO_ROOT, VLMClient

FINAL_JSON = REPO_ROOT / "dataset" / "final.json"
MEMORY_JSON = REPO_ROOT / "dataset" / "design_memory.json"

WORKERS = 3  # variants 可能在并行跑，限流友好

KS_PROMPT = """You are distilling design expertise for a diagram-generation agentic system,
from a VERIFIED high-quality diagram sample (it passed strict canvas-reproducibility review).

Sample:
- diagram_type: {diagram_type}
- vertical_domain: {domain}
- user query: {query}
- content: {content}

Distill ONE "sample strategy" memory item: a reusable design tactic this sample
embodies, useful when the {agent_hint} agent handles similar tasks.
OUTPUT JSON only, no markdown:
{{"agent": "<one of Structure|Styling|Layout|Refiner>",
"title": "<short name of the tactic>",
"description": "<what this record preserves, 1-2 sentences>",
"content": "<the actionable tactic, 1-2 sentences, concrete>",
"when_to_use": "<the precondition/scenario, 1 sentence>",
"confidence": <0.0-1.0>}}"""

KG_PROMPT = """You are distilling design expertise for a diagram-generation agentic system.
Below are verified diagram samples from the "{domain}" domain:

{examples}

Distill ONE "domain guideline" memory item: a field-specific design RULE that
generalizes across these samples (notation requirements, layout conventions,
styling norms typical of {domain} diagrams).
OUTPUT JSON only, no markdown:
{{"agent": "<one of Structure|Styling|Layout|Refiner>",
"title": "<short rule name>",
"description": "<what contextual layer this aggregates, 1-2 sentences>",
"content": "<the rule, 1-2 sentences, prescriptive>",
"when_to_use": "<when this rule applies, 1 sentence>",
"confidence": <0.0-1.0>}}"""

KP_PROMPT = """You are distilling design expertise for a diagram-generation agentic system.
Below are domain guidelines covering many fields and diagram types:

{guidelines}

Abstract {n} "general principles": universal, domain-agnostic design axioms that
transfer across ALL diagram types (e.g., density control, modular separation,
role-consistent visual hierarchy, spatial exclusion for clarity).
Each must be genuinely universal — not tied to any domain or diagram type.
OUTPUT JSON only, no markdown:
{{"principles":[{{"agent": "<one of Structure|Styling|Layout|Refiner>",
"title": "...", "description": "...", "content": "...", "when_to_use": "...",
"confidence": <0.0-1.0>}}]}}"""


class MemoryGenerator:
    def __init__(self, client: VLMClient,
                 final_path: Path = FINAL_JSON, memory_path: Path = MEMORY_JSON):
        self.client = client
        self.final_path = final_path
        self.memory_path = memory_path
        self.items: list[dict] = []
        if memory_path.exists():
            self.items = json.loads(memory_path.read_text())

    def run(self, ks_per_type: int = 4, kp_count: int = 12) -> None:
        records = json.loads(self.final_path.read_text())
        bench = [r for r in records if r["bench"]]
        have = {(i["tier"], i.get("provenance", {}).get("record_id") or i["domain"])
                for i in self.items}

        tasks: list[tuple[str, dict]] = []
        # K^s：每类型取 ks_per_type 条 bench（均匀覆盖 21 类型）
        by_type: dict[str, list[dict]] = defaultdict(list)
        for r in bench:
            by_type[r["diagram_type"]].append(r)
        for t, rows in by_type.items():
            for r in rows[:ks_per_type]:
                if ("sample_strategy", r["id"]) not in have:
                    tasks.append(("ks", r))
        # K^g：30 领域各 1 条
        by_domain: dict[str, list[dict]] = defaultdict(list)
        for r in bench:
            by_domain[r["vertical_domain"]].append(r)
        for d in by_domain:
            if ("domain_guideline", d) not in have:
                tasks.append(("kg", {"domain": d, "examples": by_domain[d][:4]}))
        # K^p：指南凑齐后一次性抽象
        kg_done = [i for i in self.items if i["tier"] == "domain_guideline"]

        print(f"[memory] 待生成 K^s {sum(1 for t, _ in tasks if t == 'ks')}, "
              f"K^g {sum(1 for t, _ in tasks if t == 'kg')}")

        done = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {}
            for kind, payload in tasks:
                futures[pool.submit(self._gen, kind, payload)] = kind
            for fut in as_completed(futures):
                item = fut.result()
                if item:
                    self.items.append(item)
                    if item["tier"] == "domain_guideline":
                        kg_done.append(item)
                done += 1
                if done % 10 == 0:
                    self._save()
                    print(f"[memory] {done}/{len(tasks)}", flush=True)
        self._save()

        if not any(i["tier"] == "general_principle" for i in self.items):
            self._gen_kp(kg_done, kp_count)
            self._save()

        from collections import Counter
        print(f"[memory] 完成: {len(self.items)} items, "
              f"{dict(Counter(i['tier'] for i in self.items))}")

    def _gen(self, kind: str, payload: dict) -> dict | None:
        if kind == "ks":
            r = payload
            text = self.client.complete([], KS_PROMPT.format(
                diagram_type=r["diagram_type"], domain=r["vertical_domain"],
                query=r["query"], content=r["content"],
                agent_hint="Structure/Styling/Layout/Refiner"))
            item = self._parse(text)
            if item:
                item.update({"tier": "sample_strategy",
                             "domain": r["vertical_domain"],
                             "diagram_type": r["diagram_type"],
                             "provenance": {"record_id": r["id"], "combo": r["combo"]}})
            return item
        else:
            d, examples = payload["domain"], payload["examples"]
            ex = "\n".join(f"- ({r['diagram_type']}) {r['content'][:300]}"
                           for r in examples)
            text = self.client.complete([], KG_PROMPT.format(domain=d, examples=ex))
            item = self._parse(text)
            if item:
                item.update({"tier": "domain_guideline", "domain": d,
                             "diagram_type": "various",
                             "promoted_from": [r["id"] for r in examples]})
            return item

    def _gen_kp(self, guidelines: list[dict], n: int) -> None:
        gl = "\n".join(f"- [{g['domain']}] {g['title']}: {g['content']}"
                       for g in guidelines)
        text = self.client.complete([], KP_PROMPT.format(guidelines=gl, n=n))
        m = re.search(r"\{.*\}", text, re.S)
        try:
            for p in json.loads(m.group())["principles"]:
                p.update({"tier": "general_principle", "domain": "Universal",
                          "diagram_type": "Universal",
                          "promoted_from": [g["title"] for g in guidelines[:6]]})
                self.items.append(p)
        except Exception as e:
            print(f"  [memory] K^p 生成失败: {e}", flush=True)

    @staticmethod
    def _parse(text: str) -> dict | None:
        try:
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group())
        except Exception:
            return None

    def _save(self) -> None:
        for i, item in enumerate(self.items, 1):
            item.setdefault("id", "")
            if not item["id"]:
                prefix = {"sample_strategy": "ks", "domain_guideline": "kg",
                          "general_principle": "kp"}[item["tier"]]
                item["id"] = f"{prefix}_{i:03d}"
        tmp = self.memory_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=1))
        tmp.replace(self.memory_path)
