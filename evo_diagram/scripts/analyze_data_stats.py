#!/usr/bin/env python3
"""Summarize EvoDiagram dataset distribution and text lengths."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "dataset" / "test" / "data.json"


def _load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected dataset root to be a list; got {type(data).__name__}.")
    return [item for item in data if isinstance(item, dict)]


def _field_counts(records: Iterable[dict[str, Any]], field_name: str) -> Counter[str]:
    return Counter(str(item.get(field_name) or "Unknown") for item in records)


def _length_stats(values: list[int]) -> tuple[float, int, int]:
    if not values:
        return 0.0, 0, 0
    return mean(values), min(values), max(values)


def summarize_dataset(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return stable summary metrics for a dataset record list."""
    content_lengths = [len(str(item.get("content") or "")) for item in records]
    query_lengths = [len(str(item.get("query") or "")) for item in records]
    content_mean, content_min, content_max = _length_stats(content_lengths)
    query_mean, query_min, query_max = _length_stats(query_lengths)

    return {
        "total_records": len(records),
        "diagram_type_counts": dict(_field_counts(records, "diagram_type").most_common()),
        "content_area_counts": dict(_field_counts(records, "content_area").most_common()),
        "length_stats": {
            "content": {
                "mean": content_mean,
                "min": content_min,
                "max": content_max,
            },
            "query": {
                "mean": query_mean,
                "min": query_min,
                "max": query_max,
            },
        },
    }


def _format_counts(title: str, counts: dict[str, int], total: int) -> list[str]:
    lines = [f"\n{title}:"]
    for key, count in counts.items():
        ratio = (count / total * 100.0) if total else 0.0
        lines.append(f"  {key}: {count} ({ratio:.1f}%)")
    return lines


def format_summary(summary: dict[str, Any]) -> str:
    """Format dataset summary as a human-readable report."""
    total = int(summary["total_records"])
    content_stats = summary["length_stats"]["content"]
    query_stats = summary["length_stats"]["query"]
    lines = [
        f"Total records: {total}",
        "-" * 30,
        *_format_counts("Diagram Type Distribution", summary["diagram_type_counts"], total),
        *_format_counts("Content Area Distribution", summary["content_area_counts"], total),
        "\nLength Statistics (Characters):",
        (
            "  Content - "
            f"Mean: {content_stats['mean']:.1f}, "
            f"Min: {content_stats['min']}, "
            f"Max: {content_stats['max']}"
        ),
        (
            "  Query   - "
            f"Mean: {query_stats['mean']:.1f}, "
            f"Min: {query_stats['min']}, "
            f"Max: {query_stats['max']}"
        ),
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-json",
        type=Path,
        default=DEFAULT_DATASET,
        help=f"Dataset JSON path. Defaults to {DEFAULT_DATASET}.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the text report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = args.input_json
    if not input_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {input_path}")

    summary = summarize_dataset(_load_records(input_path))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
