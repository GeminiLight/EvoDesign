#!/usr/bin/env python3
"""A/B comparison: stage-specific vs full domain knowledge.

The script runs a small fixed panel of examples through both knowledge modes
and writes side-by-side artifacts for visual inspection. It intentionally keeps
LLM/environment setup inside ``main()`` so ``--help`` is safe and fast.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXPERIMENT_ITEMS = [
    {"num": 1, "id": "architecture_20251204_203338_119", "type": "architecture"},
    {"num": 61, "id": "flowchart_20251205_090059_103", "type": "flowchart"},
    {"num": 111, "id": "mindmap_20251205_051354_105", "type": "mindmap"},
    {"num": 141, "id": "sequence_20251204_230134_167", "type": "sequence"},
    {"num": 41, "id": "er_20251205_060209_110", "type": "er"},
]
DEFAULT_DATASET_PATH = REPO_ROOT / "dataset" / "test" / "data.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "compare_domain_knowledge"


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
    return parser.parse_args(argv)


def selected_experiments(item_ids: list[str] | None) -> list[dict[str, Any]]:
    if not item_ids:
        return list(EXPERIMENT_ITEMS)
    selected = [item for item in EXPERIMENT_ITEMS if item["id"] in set(item_ids)]
    missing = sorted(set(item_ids) - {item["id"] for item in selected})
    if missing:
        raise ValueError(f"Unknown experiment item ids: {missing}")
    return selected


def load_dataset(dataset_path: Path) -> list[dict[str, Any]]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Dataset must be a JSON array: {dataset_path}")
    return data


def find_item(dataset: Iterable[dict[str, Any]], target_id: str) -> dict[str, Any]:
    for item in dataset:
        if item.get("id") == target_id:
            return item
    raise ValueError(f"Item {target_id} not found in dataset")


def create_model():
    from evo_diagram.core.llm_factory import LLMFactory

    return LLMFactory.create_for_role("generator", max_tokens=16384, max_retries=6)


def run_single(
    item: dict[str, Any],
    model: Any,
    *,
    full_mode: bool,
    output_dir: Path,
) -> Path | None:
    """Run one example in either default or full-domain-knowledge mode."""
    from evo_diagram.agentic_system.config import AgenticSystemConfig
    from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow

    config = AgenticSystemConfig(
        mode="multiagent",
        save_intermediate=True,
        enable_verifier=False,
        enable_refiner=False,
        enable_critic=False,
        full_domain_knowledge=full_mode,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    workflow = Text2DiagramWorkflow(model, config=config, save_dir=str(output_dir))
    state = workflow.run(
        text_content=item.get("content", ""),
        user_query=item.get("query", ""),
        diagram_type=item.get("diagram_type", ""),
    )

    png_src = Path(state.png_path) if state.png_path else None
    if png_src and png_src.exists():
        png_dst = output_dir / "rendered_diagram.png"
        shutil.copy2(png_src, png_dst)
        return png_dst
    return None


def write_comparison_html(results: list[dict[str, Any]], output_dir: Path) -> Path:
    html_path = output_dir / "comparison.html"
    lines = [
        "<html><head><style>",
        "body{font-family:sans-serif;margin:40px}",
        "h2{margin-top:40px}",
        ".row{display:flex;gap:20px;margin-bottom:20px}",
        ".col{flex:1;text-align:center}",
        "img{max-width:100%;border:1px solid #ccc}",
        "</style></head><body>",
        "<h1>Domain Knowledge A/B Comparison</h1>",
        "<p>Left: default (stage-specific) | Right: full (all stages)</p>",
    ]
    for result in results:
        lines.append(
            f"<h2>{html.escape(result['type'])} - {html.escape(result['id'])}</h2>"
        )
        lines.append("<div class='row'>")
        for mode, title in (("default_png", "Default"), ("full_png", "Full")):
            png = result.get(mode)
            if png:
                rel = html.escape(str(Path(png).relative_to(output_dir)))
                lines.append(f"<div class='col'><h3>{title}</h3><img src='{rel}'></div>")
            else:
                lines.append(f"<div class='col'><h3>{title}</h3><p>Failed or no PNG</p></div>")
        lines.append("</div>")
    lines.append("</body></html>")
    html_path.write_text("\n".join(lines), encoding="utf-8")
    return html_path


def has_missing_outputs(results: list[dict[str, Any]]) -> bool:
    return any(
        not result.get("default_png") or not result.get("full_png")
        for result in results
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()
    dataset = load_dataset(args.dataset_path)
    experiments = selected_experiments(args.item_ids)
    model = create_model()

    print("=" * 80)
    print("Domain Knowledge A/B Comparison")
    print(f"Dataset: {args.dataset_path}")
    print(f"Output: {args.output_dir}")
    print("=" * 80)

    results: list[dict[str, Any]] = []
    for exp in experiments:
        item = find_item(dataset, exp["id"])
        item_id = exp["id"]
        item_type = exp["type"]

        print(f"\n--- {item_type.upper()} ({item_id}) ---")
        default_dir = args.output_dir / "default" / item_id
        print(f"  [DEFAULT] -> {default_dir}")
        default_png = run_single(item, model, full_mode=False, output_dir=default_dir)

        full_dir = args.output_dir / "full" / item_id
        print(f"  [FULL]    -> {full_dir}")
        full_png = run_single(item, model, full_mode=True, output_dir=full_dir)

        results.append(
            {
                "type": item_type,
                "id": item_id,
                "default_png": str(default_png) if default_png else None,
                "full_png": str(full_png) if full_png else None,
            }
        )

    print("\n" + "=" * 80)
    print("COMPARISON COMPLETE")
    print("=" * 80)
    for result in results:
        ok_default = "OK" if result["default_png"] else "FAIL"
        ok_full = "OK" if result["full_png"] else "FAIL"
        print(f"  {result['type']:12s}  default: {ok_default}  |  full: {ok_full}")
        print(f"               {result['default_png'] or 'N/A'}")
        print(f"               {result['full_png'] or 'N/A'}")

    html_path = write_comparison_html(results, args.output_dir)
    print(f"\nComparison HTML: {html_path}")
    return 1 if has_missing_outputs(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
