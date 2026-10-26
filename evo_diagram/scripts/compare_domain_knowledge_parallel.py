#!/usr/bin/env python3
"""Parallel A/B comparison: stage-specific vs full domain knowledge."""

from __future__ import annotations

import argparse
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evo_diagram.scripts.compare_domain_knowledge import (
    DEFAULT_DATASET_PATH,
    DEFAULT_OUTPUT_DIR,
    create_model,
    find_item,
    has_missing_outputs,
    load_dataset,
    run_single,
    selected_experiments,
    write_comparison_html,
)

DEFAULT_MAX_WORKERS = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Dataset JSON path.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for comparison artifacts.",
    )
    parser.add_argument(
        "--item-id",
        action="append",
        dest="item_ids",
        help="Dataset item id to include. Repeat to select multiple items.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Maximum concurrent examples. Each worker creates its own LLM client.",
    )
    return parser.parse_args(argv)


def run_pair(item: dict[str, Any], exp: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Run both modes for one example sequentially inside one worker."""
    item_id = exp["id"]
    item_type = exp["type"]
    result: dict[str, Any] = {"type": item_type, "id": item_id}
    model = create_model()

    default_dir = output_dir / "default" / item_id
    print(f"[{item_type}] Starting DEFAULT mode...")
    default_png = run_single(item, model, full_mode=False, output_dir=default_dir)
    result["default_png"] = str(default_png) if default_png else None
    print(f"[{item_type}] DEFAULT: {'OK' if default_png else 'FAIL'}")

    full_dir = output_dir / "full" / item_id
    print(f"[{item_type}] Starting FULL mode...")
    full_png = run_single(item, model, full_mode=True, output_dir=full_dir)
    result["full_png"] = str(full_png) if full_png else None
    print(f"[{item_type}] FULL: {'OK' if full_png else 'FAIL'}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_workers < 1:
        raise ValueError("--max-workers must be >= 1")

    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()
    dataset = load_dataset(args.dataset_path)
    experiments = selected_experiments(args.item_ids)

    print("=" * 80)
    print("Domain Knowledge A/B Comparison (Parallel)")
    print(f"Dataset: {args.dataset_path}")
    print(f"Output: {args.output_dir}")
    print(f"Max concurrent examples: {args.max_workers}")
    print("=" * 80)

    all_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_map = {}
        for exp in experiments:
            item = find_item(dataset, exp["id"])
            future = executor.submit(run_pair, item, exp, args.output_dir)
            future_map[future] = exp

        for future in as_completed(future_map):
            exp = future_map[future]
            try:
                all_results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - keep other examples running
                print(f"[{exp['type']}] CRASHED: {exc}")
                all_results.append(
                    {
                        "type": exp["type"],
                        "id": exp["id"],
                        "default_png": None,
                        "full_png": None,
                        "error": str(exc),
                        "trace": traceback.format_exc(),
                    }
                )

    order = {exp["id"]: index for index, exp in enumerate(experiments)}
    all_results.sort(key=lambda result: order.get(result.get("id"), 999))

    print("\n" + "=" * 80)
    print("COMPARISON COMPLETE")
    print("=" * 80)
    for result in all_results:
        ok_default = "OK" if result.get("default_png") else "FAIL"
        ok_full = "OK" if result.get("full_png") else "FAIL"
        print(f"  {result['type']:12s}  default: {ok_default:4s}  |  full: {ok_full:4s}")
        if result.get("error"):
            print(f"               error: {result['error']}")
        if result.get("default_png"):
            print(f"               default PNG: {result['default_png']}")
        if result.get("full_png"):
            print(f"               full    PNG: {result['full_png']}")

    html_path = write_comparison_html(all_results, args.output_dir)
    print(f"\nComparison HTML: {html_path}")
    return 1 if any(result.get("error") for result in all_results) or has_missing_outputs(all_results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
