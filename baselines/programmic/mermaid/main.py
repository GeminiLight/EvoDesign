"""
Main entry point for Mermaid diagram generation.

Usage:
    # Single input mode
    python -m baselines.programmic.mermaid.main --input "Your text content here"

    # With intent
    python -m baselines.programmic.mermaid.main --input "text" --query "Show the process flow"

    # Batch dataset mode
    python -m baselines.programmic.mermaid.main --dataset /path/to/dataset.json --model kimi-k2.6 --output-dir /path/to/output
"""

from __future__ import annotations

import json
import os
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from baselines.programmic.mermaid.mermaid_agent import MermaidAgent


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate Mermaid diagrams from text using LLM"
    )

    parser.add_argument(
        "--input", "-i",
        type=str,
        help="Text input to process"
    )

    parser.add_argument(
        "--query",
        type=str,
        help="Query for the diagram (e.g., 'Show the process flow')"
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

    # Batch mode arguments
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
        help="Output directory for batch mode"
    )

    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        help="Maximum concurrent requests (default: 4)"
    )

    return parser.parse_args()


def clean_mermaid_code(response: str) -> str:
    """Clean markdown fences from mermaid code."""
    mermaid_code = response.strip()
    if mermaid_code.startswith("```mermaid"):
        mermaid_code = mermaid_code[len("```mermaid"):].strip()
    if mermaid_code.startswith("```"):
        mermaid_code = mermaid_code[3:].strip()
    if mermaid_code.endswith("```"):
        mermaid_code = mermaid_code[:-3].strip()
    return mermaid_code


def process_single(agent: MermaidAgent, content: str, query: str = None) -> str:
    """Process a single item and return mermaid code."""
    q = query or "Generate a diagram representing this content"
    # TASK_PROMPT uses ``{{content}}`` / ``{{query}}`` placeholders, which are
    # rendered by BaseAgent._render_template. Passing the raw values here is the
    # only path that actually substitutes them; str.format() would treat the
    # doubled braces as escapes and emit literal "{query}".
    response = agent.invoke({"content": content, "query": q})
    return clean_mermaid_code(response)


def _process_one_item(
    idx: int,
    item: dict,
    agent: MermaidAgent,
    renderer,
    output_dir: str,
    start: int,
    total: int,
):
    """Process a single dataset item (thread-safe)."""
    item_id = item.get("id", item.get("data_id", f"item_{start + idx}"))
    content = item.get("text", item.get("content", item.get("query", "")))
    query = item.get("query", "Generate a diagram representing this content")
    sample_dir = os.path.join(output_dir, str(item_id).replace(os.sep, "_").replace("/", "_"))
    os.makedirs(sample_dir, exist_ok=True)

    # Save raw input for debug
    raw_path = os.path.join(sample_dir, "input.json")
    with open(raw_path, "w", encoding="utf-8") as f_raw:
        json.dump({"id": item_id, "content": content, "query": query}, f_raw, ensure_ascii=False, indent=2)

    try:
        mermaid_code = process_single(agent, content, query)

        # ALWAYS save the generated mermaid code first
        mmd_path = os.path.join(sample_dir, "diagram.mmd")
        with open(mmd_path, "w", encoding="utf-8") as f_mmd:
            f_mmd.write(mermaid_code)

        if not mermaid_code.strip():
            error_path = os.path.join(sample_dir, "empty.txt")
            with open(error_path, "w") as f_err:
                f_err.write("Empty mermaid code after cleaning")
            return idx, item_id, "empty", 0

        # Render PNG via Kroki
        output_path = os.path.join(sample_dir, "render.png")
        renderer.render(mermaid_code, output_path)
        return idx, item_id, "ok", len(mermaid_code)
    except Exception as e:
        error_path = os.path.join(sample_dir, "error.txt")
        with open(error_path, "w") as f_err:
            f_err.write(str(e))
        return idx, item_id, f"error: {e}", 0


def process_dataset(agent: MermaidAgent, dataset_path: str, output_dir: str, start: int = 0, end: int = None, max_concurrent: int = 4):
    """Process dataset in batch mode with concurrency."""
    from baselines.programmic.kroki_render import KrokiRender

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    if not isinstance(dataset, list):
        raise ValueError("Dataset must be a JSON list")

    dataset = dataset[start:end]
    total = len(dataset)

    os.makedirs(output_dir, exist_ok=True)
    renderer = KrokiRender(output_format="png")

    print(f"[INFO] Processing {total} items with {max_concurrent} workers...", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(
                _process_one_item, idx, item, agent, renderer, output_dir, start, total
            ): idx
            for idx, item in enumerate(dataset)
        }

        for future in as_completed(futures):
            idx, item_id, status, length = future.result()
            if status == "ok":
                print(f"[{idx + 1}/{total}] {item_id}  ✓ MMD ({length} chars) + PNG saved", flush=True)
            elif status == "empty":
                print(f"[{idx + 1}/{total}] {item_id}  ⚠ Empty mermaid code", flush=True)
            else:
                print(f"[{idx + 1}/{total}] {item_id}  ✗ {status}", flush=True)
            results.append((idx, item_id, status))

    ok_count = sum(1 for _, _, s in results if s == "ok")
    empty_count = sum(1 for _, _, s in results if s == "empty")
    error_count = total - ok_count - empty_count
    print(f"\n[INFO] Done: {ok_count} OK, {empty_count} empty, {error_count} errors / {total} total", flush=True)


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
    # Decoding/robustness defaults mirror the EvoDiagram generator
    # (evo_diagram/agentic_system/main.py: max_tokens=16384, max_retries=6;
    # configs/models.yaml: temperature=0) so both sides face the same
    # transient-failure and truncation risk.
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
    from baselines.programmic.mermaid.mermaid_agent import MermaidAgent

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

    # Initialize MermaidAgent with the model
    agent = MermaidAgent(model)

    if args.dataset:
        # Batch mode
        if not args.output_dir:
            print("Error: --output-dir is required in batch mode")
            return
        process_dataset(
            agent,
            args.dataset,
            args.output_dir,
            start=args.start,
            end=args.end,
            max_concurrent=args.max_concurrent
        )
    elif args.input:
        # Single input mode
        print(f"\nInput: {args.input}", flush=True)
        if args.query:
            print(f"Query: {args.query}", flush=True)
        print("-" * 50, flush=True)

        mermaid_code = process_single(agent, args.input, args.query)
        print(f"Response:\n{mermaid_code}", flush=True)
    else:
        print("Error: Please provide --input or --dataset argument")
        print("Usage: python -m baselines.programmic.mermaid.main --input \"Your text here\" [--query \"Your query\"]")
        print("   or: python -m baselines.programmic.mermaid.main --dataset data.json --output-dir out/")


if __name__ == "__main__":
    main()
