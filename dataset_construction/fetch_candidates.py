#!/usr/bin/env python3
"""S1 检索下载：为 CanvasBench 重建抓取候选图片。

两阶段：
  阶段A (--collect)  逐组合调 Serper /images，元数据按 image_url 全局去重，
                     落 dataset/candidates.json（不下载）。
  阶段B (--download) 读台账，下载 status=pending 的图，校验/去重后更新状态。

用法：
  python fetch_candidates.py --dry-run          # 只打印检索计划（默认）
  python fetch_candidates.py --collect          # 只跑阶段A
  python fetch_candidates.py --download         # 只跑阶段B
  python fetch_candidates.py --write            # A+B 连跑
  python fetch_candidates.py --write --limit 3  # 只跑前3个组合（调试）
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
TYPES_CSV = HERE / "diagram_type.csv"
DOMAINS_CSV = HERE / "vertical_domain.csv"
LEDGER_PATH = REPO_ROOT / "dataset" / "candidates.json"
RAW_DIR = REPO_ROOT / "dataset" / "raw"
ERROR_LOG = HERE / "logs" / "errors.jsonl"

SERPER_URL = "https://google.serper.dev/images"
REQUEST_INTERVAL = 0.5
MAX_RETRIES = 3
DOWNLOAD_WORKERS = 8
SAVE_EVERY = 100

TYPE_LABELS = {
    "er": "ER",
    "orgchart": "org chart",
    "dataflow": "data flow",
    "mindmap": "mind map",
    "swot": "SWOT analysis",
    "gantt": "gantt chart",
}

MIN_BYTES = 10_000
MIN_DIM = 200


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 组合 ----------

@dataclass(frozen=True)
class Combo:
    diagram_type: str
    domain: str

    @property
    def key(self) -> str:
        return f"{self.diagram_type}|{self.domain}"

    @property
    def slug(self) -> str:
        return self.key.replace("|", "__").lower().replace(" ", "-")

    @property
    def query(self) -> str:
        label = TYPE_LABELS.get(self.diagram_type, self.diagram_type)
        return f"{label} diagram of {self.domain}"


def build_combos() -> list[Combo]:
    """从两个 CSV 叉乘出检索组合（21 类型 × 30 领域）。"""
    with open(TYPES_CSV, newline="") as f:
        types = [r["diagram_type"] for r in csv.DictReader(f)
                 if r["diagram_type"] != "react"]
    with open(DOMAINS_CSV, newline="") as f:
        domains = [r["mmmu_domain"] for r in csv.DictReader(f)]
    return [Combo(t, d) for t in types for d in domains]


# ---------- 台账 ----------

@dataclass
class Candidate:
    image_url: str
    page_url: str
    title: str
    rank: int
    combos: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    status: str = "pending"
    local_path: str | None = None
    width: int | None = None
    height: int | None = None
    phash: str | None = None
    collected_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Candidate:
        return cls(**d)

    def to_dict(self) -> dict:
        return {
            "image_url": self.image_url, "page_url": self.page_url,
            "title": self.title, "combos": self.combos, "queries": self.queries,
            "rank": self.rank, "status": self.status,
            "local_path": self.local_path, "width": self.width,
            "height": self.height, "phash": self.phash,
            "collected_at": self.collected_at,
        }


class CandidateLedger:
    """dataset/candidates.json 的读写与去重。原子写入，支持断点续跑。"""

    def __init__(self, path: Path = LEDGER_PATH):
        self.path = path
        self.rows: list[Candidate] = []
        self._by_url: dict[str, Candidate] = {}

    def load(self) -> CandidateLedger:
        if self.path.exists():
            self.rows = [Candidate.from_dict(d)
                         for d in json.loads(self.path.read_text())]
        self._by_url = {r.image_url: r for r in self.rows}
        return self

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([r.to_dict() for r in self.rows],
                                  ensure_ascii=False))
        tmp.replace(self.path)

    def add_or_merge(self, item: dict, combo: Combo) -> bool:
        """按 image_url 全局去重；重复时追加服务的组合。返回是否新增。"""
        url = item.get("imageUrl")
        if not url:
            return False
        if url in self._by_url:
            row = self._by_url[url]
            if combo.key not in row.combos:
                row.combos.append(combo.key)
                row.queries.append(combo.query)
            return False
        row = Candidate(
            image_url=url, page_url=item.get("link", ""),
            title=item.get("title", ""), rank=item.get("_rank", 0),
            combos=[combo.key], queries=[combo.query],
            collected_at=utcnow(),
        )
        self._by_url[url] = row
        self.rows.append(row)
        return True

    @property
    def done_queries(self) -> set[str]:
        return {q for r in self.rows for q in r.queries}

    @property
    def pending(self) -> list[Candidate]:
        return [r for r in self.rows if r.status == "pending"]

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.status] = out.get(r.status, 0) + 1
        return out


# ---------- 两阶段编排（含检索与下载的全部细节） ----------

class CandidateFetcher:
    def __init__(self, ledger: CandidateLedger, api_key: str):
        self.ledger = ledger
        self.api_key = api_key

    # -- 阶段A：检索留底 --

    def collect(self, combos: list[Combo], num: int) -> None:
        done = self.ledger.done_queries
        todo = [c for c in combos if c.query not in done]
        print(f"[collect] 已有 {len(self.ledger.rows)} 条, "
              f"待检索组合 {len(todo)}/{len(combos)}")
        new_rows = 0
        for i, combo in enumerate(todo, 1):
            for rank, item in enumerate(self._serper(combo.query, num)[:num], 1):
                item["_rank"] = rank
                new_rows += self.ledger.add_or_merge(item, combo)
            if i % 50 == 0:
                self.ledger.save()
                print(f"[collect] {i}/{len(todo)} combos, "
                      f"ledger {len(self.ledger.rows)} rows", flush=True)
        self.ledger.save()
        print(f"[collect] 完成, 新增 {new_rows}, 台账总计 {len(self.ledger.rows)}")

    def _serper(self, query: str, num: int) -> list[dict]:
        body = json.dumps({"q": query, "num": num}).encode()
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    SERPER_URL, data=body,
                    headers={"Content-Type": "application/json",
                             "X-API-KEY": self.api_key})
                resp = json.load(urllib.request.urlopen(req, timeout=30))
                time.sleep(REQUEST_INTERVAL)
                return resp.get("images", [])
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                print(f"  [retry {attempt + 1}/{MAX_RETRIES}] {query}: {e}", flush=True)
                time.sleep(2 ** attempt)
        self._log_error(query)
        return []

    @staticmethod
    def _log_error(query: str) -> None:
        ERROR_LOG.parent.mkdir(exist_ok=True)
        with open(ERROR_LOG, "a") as f:
            f.write(json.dumps({"stage": "serper", "query": query,
                                "ts": utcnow()}, ensure_ascii=False) + "\n")

    # -- 阶段B：下载 + 校验 + 去重 --

    def download(self, per_combo: int = 0) -> None:
        """per_combo>0：按组合配额下载（每组合凑满 N 张 ok，失败自动用后续 rank 补）；
        per_combo=0：下载全部 pending。"""
        seq = {id(c): i for i, c in enumerate(self.ledger.rows)}
        if per_combo:
            self._download_with_quota(per_combo, seq)
        else:
            self._download_batch(self.ledger.pending, seq)
            dup = self._dedup_by_phash()
            self.ledger.save()
            print(f"[download] 内容重复 {dup} 张, 状态分布: {self.ledger.stats()}")

    def _download_with_quota(self, per_combo: int, seq: dict) -> None:
        for round_no in range(1, 11):
            self._dedup_by_phash()  # duplicate 不算 ok，每轮先刷新
            # 共享记账：一张图给它 combos 列表里的每个组合都计配额
            by_combo: dict[str, list] = {}
            for r in self.ledger.rows:
                for combo in r.combos:
                    by_combo.setdefault(combo, []).append(r)

            selected = []
            selected_ids: set[int] = set()
            satisfied = exhausted = 0
            for combo, rows in sorted(by_combo.items()):
                rows.sort(key=lambda r: r.rank)
                have = sum(1 for r in rows
                           if r.status == "ok" or id(r) in selected_ids)
                if have >= per_combo:
                    satisfied += 1
                    continue
                for r in rows:
                    if have >= per_combo:
                        break
                    if r.status == "pending" and id(r) not in selected_ids:
                        selected.append(r)
                        selected_ids.add(id(r))
                        have += 1
                if have < per_combo:
                    exhausted += 1  # URL 耗尽仍凑不满

            print(f"[download] 第{round_no}轮: 达标 {satisfied}/{len(by_combo)} 组合"
                  f" ({exhausted} 个URL耗尽), 补下载 {len(selected)} 张", flush=True)
            if not selected:
                break
            self._download_batch(selected, seq)

        dup = self._dedup_by_phash()
        self.ledger.save()
        ok_per_combo = {c: sum(1 for r in rows if r.status == "ok")
                        for c, rows in by_combo.items()}
        full = sum(1 for v in ok_per_combo.values() if v >= per_combo)
        print(f"[download] 完成: {full}/{len(ok_per_combo)} 组合达到 {per_combo} 张, "
              f"内容重复 {dup} 张, 状态分布: {self.ledger.stats()}")

    def _download_batch(self, pending: list, seq: dict) -> None:
        if not pending:
            return
        done = 0
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = {pool.submit(self._process, c, seq[id(c)]): c
                       for c in pending}
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if done % SAVE_EVERY == 0:
                    self.ledger.save()
                    print(f"[download] {done}/{len(pending)}", flush=True)

    @staticmethod
    def _process(cand: Candidate, seq: int) -> None:
        """下载+校验单条候选，原地更新 cand 的 status 与元数据。"""
        data = CandidateFetcher._fetch(cand.image_url)
        if data is None:
            cand.status = "download_failed"
            return
        ext = CandidateFetcher._sniff_ext(data)
        if ext is None:
            cand.status = "skipped_format"
            return
        ok, w, h = CandidateFetcher._validate(data)
        if not ok:
            cand.status = "too_small"
            return
        out_dir = RAW_DIR / cand.combos[0].replace("|", "__").lower().replace(" ", "-")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{seq:05d}.{ext}"
        path.write_bytes(data)
        cand.local_path = str(path.relative_to(REPO_ROOT))
        cand.width, cand.height = w, h
        cand.phash = CandidateFetcher._ahash(data)
        cand.status = "ok"

    @staticmethod
    def _fetch(url: str, timeout: int = 20) -> bytes | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception:
            return None

    @staticmethod
    def _sniff_ext(data: bytes) -> str | None:
        if data[:3] == b"\xff\xd8\xff":
            return "jpg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "webp"
        return None  # SVG/GIF/其它非目标格式

    @staticmethod
    def _validate(data: bytes) -> tuple[bool, int | None, int | None]:
        if len(data) < MIN_BYTES:
            return False, None, None
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size
        except Exception:
            return False, None, None
        if w < MIN_DIM or h < MIN_DIM:
            return False, None, None
        return True, w, h

    @staticmethod
    def _ahash(data: bytes) -> str | None:
        """64-bit average hash，Pillow 内联实现，避免 imagehash 依赖。"""
        try:
            with Image.open(io.BytesIO(data)) as im:
                px = list(im.convert("L").resize((8, 8)).getdata())
        except Exception:
            return None
        avg = sum(px) / len(px)
        return format(int("".join("1" if p > avg else "0" for p in px), 2), "016x")

    def _dedup_by_phash(self) -> int:
        seen: set[str] = set()
        dup = 0
        for r in self.ledger.rows:
            if r.status != "ok" or not r.phash:
                continue
            if r.phash in seen:
                r.status = "duplicate"
                dup += 1
            else:
                seen.add(r.phash)
        return dup


# ---------- 入口 ----------

def load_api_key() -> str:
    key = os.environ.get("SERPER_API_KEY", "")
    if not key:  # 兜底：手动解析 repo 根 .env（不依赖 python-dotenv）
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("SERPER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("缺少 SERPER_API_KEY（环境变量或 .env）")
    return key


def print_plan(combos: list[Combo], num: int) -> None:
    print(f"组合数: {len(combos)}  每组合候选: {num}  "
          f"预计候选总量: {len(combos) * num}")
    print(f"预计 Serper 请求: {len(combos)}")
    print("\nquery 样例:")
    for c in combos[:10]:
        print(f"  {c.query}")
    if len(combos) > 10:
        print(f"  ... 其余 {len(combos) - 10} 个")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="只打印检索计划（默认）")
    ap.add_argument("--collect", action="store_true", help="只跑阶段A：检索留底")
    ap.add_argument("--download", action="store_true", help="只跑阶段B：下载")
    ap.add_argument("--write", action="store_true", help="A+B 连跑")
    ap.add_argument("--num", type=int, default=100, help="每组合候选数（默认100）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前N个组合（调试）")
    ap.add_argument("--combos", type=str, default="",
                    help="只跑指定组合，逗号分隔，如 'flowchart|Biology'")
    args = ap.parse_args()

    combos = build_combos()
    if args.combos:
        wanted = set(args.combos.split(","))
        combos = [c for c in combos if c.key in wanted]
    if args.limit:
        combos = combos[: args.limit]

    if not (args.collect or args.download or args.write):
        print_plan(combos, args.num)
        return

    fetcher = CandidateFetcher(CandidateLedger().load(), load_api_key())
    if args.collect or args.write:
        fetcher.collect(combos, args.num)
    if args.download or args.write:
        fetcher.download()


if __name__ == "__main__":
    main()
