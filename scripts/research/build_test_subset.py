"""
Stratified sampler for the research round.

Given the project's test dataset (`dataset/test/data.json`,
210 entries × 21 diagram types × 10 each), pick `--types-per-round` types
and `--samples-per-type` samples from each type with a deterministic seed,
then write the chosen subset to `--out`.

Default selection covers a range of structural paradigms:
- DAG / flow:   flowchart, architecture, dataflow
- hierarchy:    class, tree, orgchart
- axis-based:   sequence, timeline
- relational:   er
- geometric:    venn

Output format (JSON list, same shape as data.json entries):
[
  {"id": "...", "diagram_type": "...", "content": "...", ...},
  ...
]

Usage:
    python -m scripts.research.build_test_subset \\
        --data dataset/test/data.json \\
        --types-per-round 10 --samples-per-type 2 \\
        --seed 0 \\
        --out results/research/round0_baseline/samples.json
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


_DEFAULT_TYPES = [
    "flowchart",
    "architecture",
    "dataflow",
    "class",
    "tree",
    "orgchart",
    "sequence",
    "timeline",
    "er",
    "venn",
]


def _load_dataset(path: Path) -> List[Dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list at {path}, got {type(data).__name__}")
    return data


def _group_by_type(entries: List[Dict]) -> Dict[str, List[Dict]]:
    bucket: Dict[str, List[Dict]] = defaultdict(list)
    for e in entries:
        t = e.get("diagram_type") or e.get("type") or "unknown"
        bucket[t].append(e)
    return bucket


def sample_subset(
    entries: List[Dict],
    types: List[str],
    samples_per_type: int,
    seed: int,
) -> List[Dict]:
    rng = random.Random(seed)
    bucket = _group_by_type(entries)

    missing = [t for t in types if t not in bucket]
    if missing:
        raise ValueError(
            f"Requested types not present in dataset: {missing}. "
            f"Available types: {sorted(bucket.keys())}"
        )

    chosen: List[Dict] = []
    for t in types:
        pool = list(bucket[t])
        if len(pool) < samples_per_type:
            raise ValueError(
                f"Type '{t}' only has {len(pool)} entries; need {samples_per_type}"
            )
        rng.shuffle(pool)
        chosen.extend(pool[:samples_per_type])
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        default="dataset/test/data.json",
        help="Path to source data.json",
    )
    parser.add_argument(
        "--types",
        nargs="+",
        default=_DEFAULT_TYPES,
        help="Diagram types to include (defaults to 10 representative types)",
    )
    parser.add_argument("--types-per-round", type=int, default=10)
    parser.add_argument("--samples-per-type", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out",
        default="results/research/round0_baseline/samples.json",
        help="Where to write the sampled subset",
    )
    args = parser.parse_args()

    data_path = Path(args.data).resolve()
    out_path = Path(args.out).resolve()

    if len(args.types) < args.types_per_round:
        raise ValueError(
            f"--types has {len(args.types)} entries but --types-per-round={args.types_per_round}"
        )
    types = args.types[: args.types_per_round]

    entries = _load_dataset(data_path)
    chosen = sample_subset(entries, types, args.samples_per_type, args.seed)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(chosen, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(chosen)} entries to {out_path}")
    print(f"Types ({len(types)}): {types}")
    print(f"Samples per type: {args.samples_per_type}")
    print(f"Seed: {args.seed}")
    print()
    print("Selected ids:")
    for e in chosen:
        print(f"  {e.get('diagram_type'):14s} {e.get('id')}")


if __name__ == "__main__":
    main()
