#!/usr/bin/env python3
"""数据集图片重建管线 —— 统一入口。

子命令：
  python main.py plan                          # 打印检索计划（不调 API）
  python main.py collect [--num 100]           # S1a：Serper 检索留底 -> dataset/candidates.json
  python main.py download                      # S1b：下载候选图 -> dataset/raw/
  python main.py filter  [--target 5]          # S2+S3：VLM 过滤+合成 -> dataset/filtered.json
  python main.py bench                         # S4：每组合选最佳1张 -> dataset/bench.json
  python main.py all                           # collect + download + filter 连跑

通用参数：--limit N（只跑前N个组合/张，调试）、--combos "a|b,c|d"（指定组合）
"""

from __future__ import annotations

import argparse

from fetch_candidates import (CandidateFetcher, CandidateLedger, build_combos,
                              load_api_key, print_plan)
from filter_and_describe import (FilterAndDescribe, FilteredStore, VLMClient,
                                 load_env_key)
from bench_select import BenchSelector, BenchStore
from assemble_dataset import DatasetAssembler
from variant_queries import VariantQueryGenerator
from memory_gen import MemoryGenerator


def cmd_plan(args) -> None:
    print_plan(_combos(args), args.num)


def cmd_collect(args) -> None:
    fetcher = CandidateFetcher(CandidateLedger().load(), load_api_key())
    fetcher.collect(_combos(args), args.num)


def cmd_download(args) -> None:
    fetcher = CandidateFetcher(CandidateLedger().load(), load_api_key())
    fetcher.download(per_combo=args.per_combo)


def cmd_filter(args) -> None:
    pipeline = FilterAndDescribe(
        VLMClient(load_env_key("FREE_TOKENS_API_KEY")), FilteredStore())
    queue = pipeline.build_queue(args.combos, args.limit)
    pipeline.run(queue, args.batch_size, args.target)


def cmd_all(args) -> None:
    cmd_collect(args)
    cmd_download(args)
    cmd_filter(args)


def cmd_bench(args) -> None:
    selector = BenchSelector(
        VLMClient(load_env_key("FREE_TOKENS_API_KEY")), BenchStore())
    selector.run(combos_filter=args.combos, limit=args.limit)


def cmd_assemble(args) -> None:
    DatasetAssembler().run()


def cmd_variants(args) -> None:
    gen = VariantQueryGenerator(
        VLMClient(load_env_key("FREE_TOKENS_API_KEY")))
    gen.run(limit=args.limit)


def cmd_memory(args) -> None:
    gen = MemoryGenerator(VLMClient(load_env_key("FREE_TOKENS_API_KEY")))
    gen.run(ks_per_type=args.ks_per_type, kp_count=args.kp_count)


def _combos(args):
    combos = build_combos()
    if args.combos:
        wanted = set(args.combos.split(","))
        combos = [c for c in combos if c.key in wanted]
    if args.limit:
        combos = combos[: args.limit]
    return combos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def add_common(p, with_limit=True):
        p.add_argument("--combos", type=str, default="",
                       help="只跑指定组合，逗号分隔，如 'flowchart|Biology'")
        if with_limit:
            p.add_argument("--limit", type=int, default=0, help="只跑前N个（调试）")

    p = sub.add_parser("plan", help="打印检索计划（不调 API）")
    add_common(p)
    p.add_argument("--num", type=int, default=100, help="每组合候选数")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("collect", help="S1a：检索留底")
    add_common(p)
    p.add_argument("--num", type=int, default=100, help="每组合候选数")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("download", help="S1b：下载候选图")
    p.add_argument("--per-combo", type=int, default=20,
                   help="每组合下载配额（默认20张ok，失败自动补；0=全部）")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("filter", help="S2+S3：VLM 过滤+合成")
    add_common(p)
    p.add_argument("--batch-size", type=int, default=1, help="每次VLM调用的图片数")
    p.add_argument("--target", type=int, default=5, help="每组合keep目标数（早停）")
    p.set_defaults(func=cmd_filter)

    p = sub.add_parser("all", help="collect + download + filter 连跑")
    add_common(p)
    p.add_argument("--num", type=int, default=100, help="每组合候选数")
    p.add_argument("--per-combo", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--target", type=int, default=5)
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("bench", help="S4：每组合从keep图中选最佳1张进Bench")
    add_common(p)
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("assemble", help="S5：组装最终DataSet（带bench字段）")
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser("variants", help="S6：为记录生成other_queries变体")
    p.add_argument("--limit", type=int, default=0, help="只处理前N条（调试）")
    p.set_defaults(func=cmd_variants)

    p = sub.add_parser("memory", help="S7：生成三层设计专家记忆 K^s/K^g/K^p")
    p.add_argument("--ks-per-type", type=int, default=4, help="每图型的K^s条数（默认4）")
    p.add_argument("--kp-count", type=int, default=12, help="K^p通用原则条数（默认12）")
    p.set_defaults(func=cmd_memory)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
