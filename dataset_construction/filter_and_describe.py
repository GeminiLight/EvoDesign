#!/usr/bin/env python3
"""S2+S3 过滤与内容合成（库模块）：一次 VLM 调用完成。

对每张候选图，VLM 同时输出：
  - keep / reject_reason   （S2 canvas-recoverability 过滤）
  - content / query        （S3 由图合成 dense description + 规范 user query，仅 keep 时）

按 rank 顺序处理，每个组合凑够 target 张 keep 即提前停止。
输出 dataset/filtered.json，定期落盘，重跑自动跳过已判定。

本模块为库，命令行入口见 main.py（filter 子命令）。
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CANDIDATES_JSON = REPO_ROOT / "dataset" / "candidates.json"
FILTERED_JSON = REPO_ROOT / "dataset" / "filtered.json"

VLM_URL = "https://free-tokens.msh.team/v1/chat/completions"
VLM_MODEL = "joint-model-0715-vibe-highspeed"
MAX_TOKENS = 6000  # 推理模型，思考过程也占额度，留足余量
WORKERS = 5  # freetokens 限流较敏感，429 过多再降
MAX_RETRIES = 3

PROMPT_TEMPLATE = """You are building a diagram dataset. For EACH attached image (Image 1..{n} in order), do TWO tasks in one pass.

Context: each image was retrieved as a candidate "{expect}".

TASK A - canvas-recoverability filter. keep=true only if the image is
essentially a diagram: a structured schematic whose content (nodes, containers,
connectors, text labels) could be reproduced with diagramming tools such as
Excalidraw or tldraw.
keep=false for: hand-drawn sketches or photos of paper/whiteboard/screens;
data visualizations dominated by plotted data (bar/line/pie/scatter charts);
photographic infographics, posters, decorative collages; scanned/blurred
documents; text pages where a diagram is not the dominant subject; photos of
real objects; images unrelated to the expected diagram type or topic.

TASK B - only when keep=true: synthesize
- "content": a dense description capturing your understanding of the diagram's
  content: every node label, the connections/groupings, and the reading flow.
  Be as detailed as the diagram warrants - someone could rebuild the diagram
  from the text alone. Do not pad, do not summarize away labels.
- "query": one canonical user instruction that, given to a diagram-generation
  AI, would reproduce this diagram, e.g. "Design a flowchart of ...".

OUTPUT JSON only, no markdown, no prose:
{{"images":[{{"index":1,"keep":true,"reject_reason":null,"content":"...","query":"..."}},
{{"index":2,"keep":false,"reject_reason":"<10 words","content":null,"query":null}}]}}"""


def load_env_key(name: str) -> str:
    key = os.environ.get(name, "")
    if not key:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith(f"{name}="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit(f"缺少 {name}（环境变量或 .env）")
    return key


def expectation(combo: str) -> str:
    diagram_type, domain = combo.split("|", 1)
    return f"{diagram_type} diagram of {domain}"


# ---------- VLM 调用 ----------

class VLMClient:
    """VLM 调用：拼多图请求、重试、从推理模型输出中提取结果。"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def complete(self, image_paths: list[Path], prompt_text: str) -> str:
        """通用多图调用，返回原始文本输出。"""
        body = json.dumps({
            "model": VLM_MODEL,
            "messages": [{"role": "user",
                          "content": self._build_content(image_paths, prompt_text)}],
            "max_tokens": MAX_TOKENS,
        }).encode()
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    VLM_URL, data=body,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {self.api_key}"})
                resp = json.load(urllib.request.urlopen(req, timeout=600))
                return resp["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"  [vlm retry {attempt + 1}/{MAX_RETRIES}] {e}", flush=True)
                time.sleep(2 ** attempt * 5)
        return ""

    def judge(self, image_paths: list[Path], expect: str) -> list[dict]:
        """S2+S3 过滤+合成专用调用。"""
        text = self.complete(
            image_paths, PROMPT_TEMPLATE.format(n=len(image_paths), expect=expect))
        try:
            return self._parse(text)
        except Exception:
            return []

    @staticmethod
    def _build_content(image_paths: list[Path], prompt_text: str) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt_text}]
        for i, p in enumerate(image_paths, 1):
            mime = "image/png" if p.suffix == ".png" else "image/jpeg"
            b64 = base64.b64encode(p.read_bytes()).decode()
            content.append({"type": "text", "text": f"Image {i}:"})
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}})
        return content

    @staticmethod
    def _parse(text: str) -> list[dict]:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group())["images"]


# ---------- 产物存储 ----------

class FilteredStore:
    """dataset/filtered.json 的读写与进度统计。"""

    def __init__(self, path: Path = FILTERED_JSON):
        self.path = path
        self.rows: list[dict] = []
        if path.exists():
            self.rows = json.loads(path.read_text())

    @property
    def done_pairs(self) -> set[tuple[str, str]]:
        """已判定的 (local_path, combo) 对。"""
        return {(r["local_path"], r["combo"]) for r in self.rows}

    @property
    def verdict_by_path(self) -> dict[str, dict]:
        """已判定图片的结论（按 local_path），用于跨组合复用，不重复调 VLM。"""
        return {r["local_path"]: r for r in self.rows}

    @property
    def kept_per_combo(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            if r.get("keep"):
                out[r["combo"]] = out.get(r["combo"], 0) + 1
        return out

    def extend(self, batch: list[dict]) -> None:
        self.rows.extend(batch)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.rows, ensure_ascii=False))
        tmp.replace(self.path)

    def keep_count(self) -> int:
        return sum(1 for r in self.rows if r["keep"])


# ---------- 编排 ----------

class FilterAndDescribe:
    def __init__(self, client: VLMClient, store: FilteredStore):
        self.client = client
        self.store = store

    def build_queue(self, combos_filter: str, limit: int) -> list[dict]:
        """待判集合：status=ok 的图，按它服务的每个组合各排一次队（共享记账），
        组内按 rank 序，组合间交错；已判过的 (图, 组合) 对跳过。"""
        candidates = json.loads(CANDIDATES_JSON.read_text())
        done = self.store.done_pairs
        wanted = set(combos_filter.split(",")) if combos_filter else None

        by_combo: dict[str, list[dict]] = {}
        for c in candidates:
            if c["status"] != "ok":
                continue
            for combo in c["combos"]:
                if wanted and combo not in wanted:
                    continue
                if (c["local_path"], combo) in done:
                    continue
                by_combo.setdefault(combo, []).append(c)
        for rows in by_combo.values():
            rows.sort(key=lambda c: c["rank"])

        queue: list[dict] = []
        max_len = max((len(v) for v in by_combo.values()), default=0)
        for i in range(max_len):
            for combo in sorted(by_combo):
                if i < len(by_combo[combo]):
                    item = dict(by_combo[combo][i])
                    item["_combo"] = combo  # 本次判定服务的组合（共享图非归属组合时不同）
                    queue.append(item)
        return queue[:limit] if limit else queue

    def run(self, queue: list[dict], batch_size: int, target: int) -> None:
        kept = self.store.kept_per_combo
        stop = {k for k, v in kept.items() if v >= target}
        batches = self._make_batches(queue, batch_size, stop)
        print(f"待判定 {sum(len(b) for b in batches)} 张 "
              f"({len(batches)} 批), 已完成 {len(self.store.rows)} 张")

        import threading
        lock = threading.Lock()
        done = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(self._process_batch, b, kept, target, lock): b
                       for b in batches}
            for fut in as_completed(futures):
                batch_rows = fut.result()
                if not batch_rows:
                    continue
                self.store.extend(batch_rows)
                done += len(batch_rows)
                if done % 30 < batch_size:
                    self.store.save()
                    print(f"[vlm] 已处理 {done}, keep {self.store.keep_count()}",
                          flush=True)

        self.store.save()
        total = len(self.store.rows)
        print(f"完成: 判定 {total}, keep {self.store.keep_count()} "
              f"({self.store.keep_count() / max(total, 1):.0%})")
        reached = sum(1 for v in kept.values() if v >= target)
        print(f"达到 target 的组合: {reached}")

    @staticmethod
    def _make_batches(queue: list[dict], batch_size: int,
                      stop: set[str]) -> list[list[dict]]:
        """同组合的图才进同一批（保证 expect 一致）；已达 target 的组合跳过。"""
        by_combo: dict[str, list[dict]] = {}
        for c in queue:
            by_combo.setdefault(c["_combo"], []).append(c)
        batches = []
        for combo, rows in by_combo.items():
            if combo in stop:
                continue
            for i in range(0, len(rows), batch_size):
                batches.append(rows[i: i + batch_size])
        return batches

    def _process_batch(self, batch: list[dict], kept: dict[str, int],
                       target: int, lock) -> list[dict]:
        combo = batch[0]["_combo"]
        with lock:
            if kept.get(combo, 0) >= target:
                return []  # 该组合已凑满 target，跳过不花 VLM 调用

        # 共享图复用：已判定过的图直接记账，不重复调 VLM
        out = []
        to_judge: list[dict] = []
        verdicts = self.store.verdict_by_path
        for c in batch:
            v = verdicts.get(c["local_path"])
            if v is not None:
                row = self._make_row(c, combo, v)
                row["reused"] = True
                out.append(row)
            else:
                to_judge.append(c)

        if to_judge:
            judged = self.client.judge(
                [REPO_ROOT / c["local_path"] for c in to_judge],
                expectation(combo))
            by_index = {v.get("index"): v for v in judged}
            for i, c in enumerate(to_judge, 1):
                out.append(self._make_row(c, combo, by_index.get(i, {})))

        with lock:
            for r in out:
                if r["keep"]:
                    kept[combo] = kept.get(combo, 0) + 1
        return out

    @staticmethod
    def _make_row(c: dict, combo: str, v: dict) -> dict:
        return {
            "local_path": c["local_path"], "image_url": c["image_url"],
            "page_url": c["page_url"], "combo": combo,
            "diagram_type": combo.split("|")[0],
            "mmmu_domain": combo.split("|")[1],
            "keep": bool(v.get("keep")),
            "reject_reason": v.get("reject_reason"),
            "content": v.get("content"), "query": v.get("query"),
            "reused": False,
        }
