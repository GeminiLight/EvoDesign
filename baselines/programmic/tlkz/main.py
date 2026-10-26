#!/usr/bin/env python3
"""
Main entry point for Tlkz (TiKZ) diagram generation.

Usage:
    # Single input mode (prints the TikZ code; add --output-dir to also render a PNG)
    python -m baselines.programmic.tlkz.main --input "Create a flowchart for user login"
    python -m baselines.programmic.tlkz.main --input "User login" --query "Show authentication flow"

    # Batch dataset mode (writes the evaluation artifact contract:
    # <output-dir>/<sample_id>/{input.json,diagram.tex,render.png} plus a
    # run-level <output-dir>/mapping.json, matching diagramagent's layout)
    python -m baselines.programmic.tlkz.main --dataset /path/to/dataset.json \
        --model k3 --output-dir /path/to/output [--start 0 --end 10]

Rendering requires a local pdflatex (TeX Live/MacTeX) and PyMuPDF in the
Python environment; see baselines/programmic/tlkz/tikz_render.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from baselines.programmic.tlkz.tikz_render import (
    DEFAULT_TIMEOUT,
    RenderResult,
    extract_tikz_code,
    render_tikz_to_png,
)

if TYPE_CHECKING:
    from baselines.programmic.tlkz.tlkz_agent import TlkzAgent

# baselines/programmic/tlkz/main.py -> repo root; used only to resolve the
# optional ground-truth reference image recorded in mapping.json.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# mapping.json is shared by all worker threads.
_MAPPING_LOCK = threading.Lock()

DEFAULT_QUERY = "Generate a diagram representing this content"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate TiKZ diagrams from text using LLM, render PNG via pdflatex"
    )

    parser.add_argument(
        "--input", "-i",
        type=str,
        help="Text input to process (single-sample mode)"
    )

    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Query/intent for the diagram (e.g., 'Show the process flow')"
    )

    parser.add_argument(
        "--model", "-m",
        type=str,
        help="Model name (overrides env variable)"
    )

    parser.add_argument(
        "--temperature",
        type=float,
        help="Temperature for generation (overrides env variable)"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Maximum number of tokens to generate (overrides env variable)"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        help="LLM API timeout in seconds (overrides env variable)"
    )

    # Batch mode arguments (same contract as baselines/programmic/mermaid/main.py:
    # --start is 0-based, --end is exclusive; scripts/run_baselines.sh converts
    # its 1-based inclusive START/END into these).
    parser.add_argument(
        "--dataset", "-d",
        type=str,
        help="Dataset JSON file path for batch processing"
    )

    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Start index for dataset processing (0-based)"
    )

    parser.add_argument(
        "--end",
        type=int,
        help="End index for dataset processing (exclusive)"
    )

    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        help="Output directory (required in batch mode; optional in single mode to render a PNG)"
    )

    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        help="Maximum concurrent requests (default: 4)"
    )

    return parser.parse_args()


def clean_tikz_code(response: str) -> str:
    """Clean markdown fences from generated TikZ code (capture-group based)."""
    return extract_tikz_code(response)


def process_single(agent: TlkzAgent, content: str, query: Optional[str] = None) -> str:
    """Process a single item and return fence-stripped TikZ code."""
    q = query or DEFAULT_QUERY
    # TASK_PROMPT uses ``{{content}}`` / ``{{query}}`` placeholders rendered by
    # BaseAgent._render_template; passing raw values here is the only path
    # that substitutes them (same note as mermaid/main.py).
    response = agent.invoke({"content": content, "query": q})
    return clean_tikz_code(response)


def _atomic_write_json(path: str, obj: Any) -> None:
    """Write JSON via tmp + os.replace (mirrors diagramagent's writer)."""
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _safe_sample_id(sample_id: str) -> str:
    return str(sample_id).replace(os.sep, "_").replace("/", "_")


def _resolve_reference_image(data_id: str) -> str:
    """Ground-truth image path recorded in mapping.json ('' when absent).

    Same convention as diagramagent's _resolve_reference_image and the
    evaluation path_resolver: dataset/images/diagrams/<data_id>.jpg.
    """
    candidate = _REPO_ROOT / "dataset" / "images" / "diagrams" / f"{data_id}.jpg"
    return str(candidate) if candidate.exists() else ""


def _append_mapping_entry(output_dir: str, entry: Dict[str, Any]) -> None:
    """Append (or replace) one sample entry in <output_dir>/mapping.json.

    Field set matches diagramagent DiagramAgentEvaluator._write_eval_artifacts:
    id / query / content_path / reference_image_path / generated_image_path /
    code_path. Thread-safe: called from batch workers under a lock.
    """
    mapping_path = os.path.join(output_dir, "mapping.json")
    with _MAPPING_LOCK:
        mapping: Any = []
        if os.path.exists(mapping_path):
            try:
                with open(mapping_path, "r", encoding="utf-8") as f:
                    mapping = json.load(f)
            except Exception:
                mapping = []
        if not isinstance(mapping, list):
            mapping = []
        mapping = [
            m for m in mapping
            if not (isinstance(m, dict) and m.get("id") == entry["id"])
        ]
        mapping.append(entry)
        _atomic_write_json(mapping_path, mapping)


def _write_failed_record(sample_dir: str, item_id: str, error: str, expected_image_path: str) -> None:
    """Persist an explicit failure record for a sample with no render.png.

    Mirrors the evaluation-side missing_output convention
    (evaluation/run_evaluation.py::write_missing_output_record uses
    RESULT_STATUS_MISSING_OUTPUT = "missing_output" plus an error message and
    the expected image path), so a failed sample stays distinguishable from a
    sample that was never part of the run.
    """
    _atomic_write_json(
        os.path.join(sample_dir, "failed.json"),
        {
            "id": item_id,
            "status": "missing_output",
            "error": error,
            "expected_image_path": expected_image_path,
        },
    )


def _render_with_repair(
    tikz_code: str,
    png_path: str,
    fix_agent: Optional[TlkzAgent],
    query: str,
    sample_dir: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> RenderResult:
    """Compile TikZ to PNG; on failure ask the LLM once to repair the code.

    Mirrors diagramagent CheckAgent.check's compile-fix-compile loop, capped
    at a single repair round. When a repair produces different code,
    diagram.tex is overwritten with it so the saved code is always the code
    that generated the final artifact (the first attempt stays on disk as
    diagram_attempt1.tex for debugging).
    """
    result = render_tikz_to_png(tikz_code, png_path, timeout=timeout)
    if result.success or fix_agent is None:
        return result

    with open(os.path.join(sample_dir, "diagram_attempt1.tex"), "w", encoding="utf-8") as f:
        f.write(tikz_code)

    try:
        fixed_response = fix_agent.invoke({
            "query": query,
            "code": tikz_code,
            "errors": result.diagnostics or "(no diagnostics captured)",
        })
    except Exception as e:  # noqa: BLE001 - a broken repair call is still a sample failure
        return RenderResult(
            success=False,
            diagnostics=f"{result.diagnostics}\nrepair call failed: {e}".strip(),
        )

    fixed_code = extract_tikz_code(fixed_response)
    if not fixed_code.strip() or fixed_code == tikz_code:
        return result

    with open(os.path.join(sample_dir, "diagram.tex"), "w", encoding="utf-8") as f:
        f.write(fixed_code)
    return render_tikz_to_png(fixed_code, png_path, timeout=timeout)


def _process_one_item(
    idx: int,
    item: dict,
    agent: TlkzAgent,
    fix_agent: Optional[TlkzAgent],
    output_dir: str,
    start: int,
    total: int,
):
    """Process a single dataset item (thread-safe)."""
    item_id = _safe_sample_id(item.get("id", item.get("data_id", f"item_{start + idx}")))
    content = item.get("text", item.get("content", item.get("query", "")))
    query = item.get("query", DEFAULT_QUERY)
    sample_dir = os.path.join(output_dir, item_id)
    os.makedirs(sample_dir, exist_ok=True)

    # Save raw input first, like mermaid/main.py, so failures stay debuggable.
    input_path = os.path.join(sample_dir, "input.json")
    _atomic_write_json(input_path, {"id": item_id, "query": query, "content": content})

    png_path = os.path.join(sample_dir, "render.png")
    try:
        tikz_code = process_single(agent, content, query)

        # ALWAYS save the generated code first (mirrors mermaid's diagram.mmd).
        code_path = os.path.join(sample_dir, "diagram.tex")
        with open(code_path, "w", encoding="utf-8") as f_tex:
            f_tex.write(tikz_code)

        if not tikz_code.strip():
            _write_failed_record(sample_dir, item_id, "Empty TiKZ code after fence stripping", png_path)
            return idx, item_id, "empty", 0

        result = _render_with_repair(tikz_code, png_path, fix_agent, query, sample_dir)
        if result.success:
            _append_mapping_entry(output_dir, {
                "id": item_id,
                "query": query,
                "content_path": input_path,
                "reference_image_path": _resolve_reference_image(item_id),
                "generated_image_path": png_path,
                "code_path": code_path,
            })
            return idx, item_id, "ok", len(tikz_code)

        _write_failed_record(
            sample_dir,
            item_id,
            f"pdflatex compilation failed after one repair attempt: {result.diagnostics[:2000]}",
            png_path,
        )
        return idx, item_id, "failed", 0
    except Exception as e:
        _write_failed_record(sample_dir, item_id, str(e), png_path)
        return idx, item_id, f"error: {e}", 0


def process_dataset(
    agent: TlkzAgent,
    dataset_path: str,
    output_dir: str,
    start: int = 0,
    end: Optional[int] = None,
    max_concurrent: int = 4,
    fix_agent: Optional[TlkzAgent] = None,
):
    """Process dataset in batch mode with concurrency."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    if not isinstance(dataset, list):
        raise ValueError("Dataset must be a JSON list")

    dataset = dataset[start:end]
    total = len(dataset)

    os.makedirs(output_dir, exist_ok=True)

    print(f"[INFO] Processing {total} items with {max_concurrent} workers...", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(
                _process_one_item, idx, item, agent, fix_agent, output_dir, start, total
            ): idx
            for idx, item in enumerate(dataset)
        }

        for future in as_completed(futures):
            idx, item_id, status, length = future.result()
            if status == "ok":
                print(f"[{idx + 1}/{total}] {item_id}  ✓ TEX ({length} chars) + PNG saved", flush=True)
            elif status == "empty":
                print(f"[{idx + 1}/{total}] {item_id}  ⚠ Empty TiKZ code", flush=True)
            elif status == "failed":
                print(f"[{idx + 1}/{total}] {item_id}  ✗ pdflatex failed after repair retry", flush=True)
            else:
                print(f"[{idx + 1}/{total}] {item_id}  ✗ {status}", flush=True)
            results.append((idx, item_id, status))

    ok_count = sum(1 for _, _, s in results if s == "ok")
    empty_count = sum(1 for _, _, s in results if s == "empty")
    failed_count = sum(1 for _, _, s in results if s == "failed")
    error_count = total - ok_count - empty_count - failed_count
    print(
        f"\n[INFO] Done: {ok_count} OK, {empty_count} empty, {failed_count} compile-failed, "
        f"{error_count} errors / {total} total",
        flush=True,
    )


def main():
    """Main entry point with CLI support."""
    args = parse_args()

    # Load environment variables
    from dotenv import load_dotenv
    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()
    load_dotenv(Path(__file__).parent / ".env", override=True)

    # Create model using LLMFactory
    model_name = os.getenv("LLM_MODEL_NAME", "qwen3-vl-plus")
    model_provider = os.getenv("LLM_MODEL_PROVIDER", "openai")
    base_url = os.getenv("LLM_ENDPOINT_URL", "https://apis.iflow.cn/v1")
    api_key = os.getenv("LLM_API_KEY")
    # Decoding/robustness defaults mirror the EvoDiagram generator and the
    # mermaid baseline (max_tokens=16384, max_retries=6, timeout=300) so both
    # sides face the same transient-failure and truncation risk.
    temperature = float(os.getenv("TEMPERATURE", "0"))
    max_tokens = int(os.getenv("MAX_TOKENS", "16384"))
    timeout = int(os.getenv("TIMEOUT", "300"))
    max_retries = int(os.getenv("MAX_RETRIES", "6"))

    if args.model:
        model_name = args.model
    if args.temperature is not None:
        temperature = args.temperature
    if args.max_tokens is not None:
        max_tokens = args.max_tokens
    if args.timeout is not None:
        timeout = args.timeout

    print(f"Loading model: {model_name}", flush=True)
    print(f"Timeout: {timeout}s", flush=True)
    print(f"Max tokens: {max_tokens}", flush=True)
    print(f"Max retries: {max_retries}", flush=True)
    print(f"Streaming: False", flush=True)
    print(f"Concurrency: {args.max_concurrent}", flush=True)

    from evo_diagram.core.llm_factory import LLMFactory
    from baselines.programmic.tlkz.prompts import FIX_SYSTEM_PROMPT, FIX_TASK_PROMPT
    from baselines.programmic.tlkz.tlkz_agent import TlkzAgent

    model = LLMFactory.create(
        model=model_name.split("/")[-1] if "/" in model_name else model_name,
        model_provider=model_provider,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        streaming=False
    )

    # Initialize TlkzAgent with the model
    agent = TlkzAgent(model)
    # Compile-repair agent: same model, fix prompts (CheckAgent-style single
    # diagnostic round; see _render_with_repair).
    fix_agent = TlkzAgent(model, system_prompt=FIX_SYSTEM_PROMPT, task_prompt=FIX_TASK_PROMPT)

    if args.dataset:
        # Batch mode
        if not args.output_dir:
            print("Error: --output-dir is required in batch mode")
            sys.exit(1)
        process_dataset(
            agent,
            args.dataset,
            args.output_dir,
            start=args.start,
            end=args.end,
            max_concurrent=args.max_concurrent,
            fix_agent=fix_agent,
        )
    elif args.input:
        # Single input mode
        query = args.query or DEFAULT_QUERY
        print(f"\nInput: {args.input}", flush=True)
        print(f"Query: {query}", flush=True)
        print("-" * 50, flush=True)

        tikz_code = process_single(agent, args.input, args.query)
        print(f"\nGenerated TiKZ code:")
        print("=" * 50)
        print(tikz_code)
        print("=" * 50)

        if args.output_dir:
            # Optional render so single-sample runs can also produce a PNG.
            os.makedirs(args.output_dir, exist_ok=True)
            with open(os.path.join(args.output_dir, "diagram.tex"), "w", encoding="utf-8") as f_tex:
                f_tex.write(tikz_code)
            png_path = os.path.join(args.output_dir, "render.png")
            result = _render_with_repair(tikz_code, png_path, fix_agent, query, args.output_dir)
            if result.success:
                print(f"\n[INFO] PNG rendered: {png_path}", flush=True)
            else:
                print(f"\n[ERROR] Render failed: {result.diagnostics[:2000]}", flush=True)
                sys.exit(1)
    else:
        print("Error: Please provide --input or --dataset argument")
        print("Usage: python -m baselines.programmic.tlkz.main --input \"Your text here\" [--query \"Your query\"]")
        print("   or: python -m baselines.programmic.tlkz.main --dataset data.json --output-dir out/")
        sys.exit(1)


if __name__ == "__main__":
    main()
