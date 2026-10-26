#!/usr/bin/env python
"""
Direct LLM Text-to-Diagram Converter

Directly invoke LLM to convert text to Excalidraw JSON format diagrams.

Usage:
    # Process a single file
    python -m baselines.direct_llm.main --input input/text_content.txt

    # Process all files
    python -m baselines.direct_llm.main --all

    # Process dataset
    python -m baselines.direct_llm.main --dataset /dataset/test/data.json

    # Direct text input
    python -m baselines.direct_llm.main --text "Your text content here"

    # Read text content from txt file
    python -m baselines.direct_llm.main --direct-text /path/to/content.txt

    # Render JSON output to PNG image
    python -m baselines.direct_llm.main --input input/test.txt --render

    # Use different model
    python -m baselines.direct_llm.main --input input/test.txt --model gpt-4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, Optional

if TYPE_CHECKING:
    from baselines.direct_llm.state import WorkflowState

BaselineWorkflow = None


def _create_baseline_workflow(config: Dict[str, Any]):
    """Lazy import the baseline workflow so `--help` stays cheap."""
    workflow_cls = BaselineWorkflow
    if workflow_cls is None:
        from baselines.direct_llm.workflow import BaselineWorkflow as workflow_cls

    return workflow_cls(config=config)


def _get_render_funcs(canvas_library):
    """Lazy import render functions to avoid loading the full agentic_system chain."""
    from evo_diagram.canvas_environment import render_canvas_file

    def _render_file(input_path: str, output_path: str):
        return render_canvas_file(
            input_path=input_path,
            output_path=output_path,
            canvas_library=canvas_library,
        )

    return _render_file, "input_path"


def _resolve_named_model_config(model_name: Optional[str]) -> Dict[str, Any]:
    """Resolve a model name from configs/models.yaml when available."""
    if not model_name:
        return {}

    try:
        from evo_diagram.config.model_loader import ModelConfig

        cfg = ModelConfig.get_default()
        if model_name not in cfg.list_models():
            return {}

        resolved_cfg = cfg.get_named_model_config(model_name)
        resolved: Dict[str, Any] = {
            "model_name": resolved_cfg.get("model", model_name),
            "model_alias": model_name,
            "provider": resolved_cfg.get("model_provider"),
            "base_url": resolved_cfg.get("base_url"),
            "api_key": resolved_cfg.get("api_key"),
            "temperature": resolved_cfg.get("temperature"),
            "max_tokens": resolved_cfg.get("max_tokens"),
        }
        return {k: v for k, v in resolved.items() if v is not None}
    except Exception as exc:
        raise RuntimeError(f"Failed to resolve model config for {model_name}") from exc


def process_text(
    text: str,
    config: Dict[str, Any],
    output_path: Optional[str] = None,
    render_image: bool = False,
    user_query: str = "",
    save_simplified: bool = False,
) -> WorkflowState:
    """Process text content and generate diagram JSON.

    Args:
        text: Input text content
        config: Configuration dictionary
        output_path: Output file path
        render_image: Whether to render the JSON to PNG image
        user_query: User query or request text
        save_simplified: Whether to save the simplified JSON output

    Returns:
        WorkflowState containing processing results
    """
    print(f"[Input] Text length: {len(text)} characters")
    if user_query:
        print(f"[Query] {user_query[:100]}...")

    # Create workflow
    workflow = _create_baseline_workflow(config)

    # Run workflow
    state = workflow.run(text, user_query)

    # Check results
    if state.has_errors():
        print(f"[Error] Processing failed:")
        for error in state.get_errors():
            print(f"  - {error}")
        return state

    if state.output is None:
        print(f"[Error] Output is empty")
        return state

    print(f"[Success] JSON generation completed")

    # Save outputs
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Save complete canvas snapshot
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(state.output, f, indent=2, ensure_ascii=False)
        print(f"[Saved] Complete snapshot: {output_path}")

        # Optionally save simplified JSON
        if save_simplified and hasattr(state, "simplified_output"):
            simplified_path = str(Path(output_path).with_suffix('.simplified.json'))
            with open(simplified_path, "w", encoding="utf-8") as f:
                json.dump(state.simplified_output, f, indent=2, ensure_ascii=False)
            print(f"[Saved] Simplified JSON: {simplified_path}")

        # Render to image if requested
        if render_image:
            try:
                image_output_path = str(Path(output_path).with_suffix('.png'))
                canvas_lib = config.get("canvas_library", "excalidraw")
                render_fn, kwarg_name = _get_render_funcs(canvas_lib)
                resp = render_fn(**{kwarg_name: output_path, "output_path": image_output_path})
                print(f"[Rendered] {resp.get('output_path', image_output_path)}")
            except Exception as e:
                print(f"[Warning] Failed to render image: {e}")

    return state


def _default_output_path_for_input(input_path: str, config: Dict[str, Any]) -> str:
    """Build the default output path for a single text file."""
    base_dir = Path(__file__).parent
    input_name = Path(input_path).stem
    model_safe = config.get("model_alias") or config.get("model_name", "model")
    model_safe = model_safe.replace("/", "_").replace(":", "_")
    return str(base_dir / "output" / model_safe / input_name / "scene.json")


def _safe_sample_id(sample_id: Any) -> str:
    s = str(sample_id or "").strip()
    if not s:
        return "sample"
    return s.replace(os.sep, "_").replace("/", "_")


def process_file(
    input_path: str,
    config: Dict[str, Any],
    output_path: Optional[str] = None,
    render_image: bool = False,
    save_simplified: bool = False,
) -> WorkflowState:
    """Process one text file through the direct LLM baseline."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        text_content = f.read().strip()

    if not text_content:
        raise ValueError(f"Input file is empty: {input_path}")

    output_path = output_path or _default_output_path_for_input(input_path, config)
    return process_text(
        text_content,
        config,
        output_path,
        render_image,
        save_simplified=save_simplified,
    )


def process_all_files(
    config: Dict[str, Any],
    input_dir: Optional[str] = None,
    render_image: bool = False,
    save_simplified: bool = False,
) -> Dict[str, Any]:
    """Process all .txt files in the baseline input directory."""
    base_dir = Path(__file__).parent
    resolved_input_dir = Path(input_dir) if input_dir else base_dir / "input"
    if not resolved_input_dir.is_absolute():
        resolved_input_dir = base_dir / resolved_input_dir

    if not resolved_input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {resolved_input_dir}")

    input_files = sorted(resolved_input_dir.glob("*.txt"))
    if not input_files:
        raise ValueError(f"No .txt files found in input directory: {resolved_input_dir}")

    results: Dict[str, Any] = {}
    for input_file in input_files:
        print(f"\n[Processing] {input_file}")
        try:
            state = process_file(
                str(input_file),
                config,
                render_image=render_image,
                save_simplified=save_simplified,
            )
            results[input_file.name] = {
                "status": state.status,
                "has_errors": state.has_errors(),
                "errors": state.get_errors(),
            }
        except Exception as exc:
            results[input_file.name] = {"status": "failed", "error": str(exc)}
            print(f"[Error] Failed to process {input_file}: {exc}")

    return results


def _process_one_direct_llm(
    idx: int,
    item: dict,
    config: Dict[str, Any],
    output_dir: Path,
    render_image: bool,
    save_simplified: bool,
    total: int,
) -> tuple:
    """Process a single dataset item in a worker thread."""
    item_id = item.get("id", f"item_{idx}")
    content = item.get("content", "")
    query = item.get("query", "")
    canvas_library = config.get("canvas_library", "excalidraw")

    if not content:
        return item_id, {"status": "skipped"}, idx, total

    try:
        safe_item_id = _safe_sample_id(item_id)
        sample_dir = output_dir / safe_item_id
        output_path = sample_dir / "scene.json"
        # Each thread creates its own workflow instance for thread safety
        workflow = _create_baseline_workflow(config)
        state = workflow.run(content, query)

        # Save outputs
        if state.output is not None:
            sample_dir.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(state.output, f, indent=2, ensure_ascii=False)

            # Optionally render PNG
            if render_image:
                image_output_path = str(sample_dir / "render.png")
                try:
                    render_fn, kwarg_name = _get_render_funcs(canvas_library)
                    render_fn(**{kwarg_name: str(output_path), "output_path": image_output_path})
                except Exception as render_err:
                    print(f"  [{item_id}] Render warning: {render_err}", flush=True)

            # Optionally save simplified JSON
            if save_simplified and hasattr(state, "simplified_output") and state.simplified_output:
                simplified_path = str(sample_dir / "simplified.json")
                with open(simplified_path, "w", encoding="utf-8") as f:
                    json.dump(state.simplified_output, f, indent=2, ensure_ascii=False)

        return item_id, {"status": state.status, "output": str(output_path), "sample_dir": str(sample_dir), "has_errors": state.has_errors()}, idx, total
    except Exception as e:
        return item_id, {"status": "failed", "error": str(e)}, idx, total


def process_datasets(
    dataset_path: str,
    config: Dict[str, Any],
    limit: int = 0,
    start: int = 0,
    render_image: bool = False,
    save_simplified: bool = False,
    max_concurrent: int = 4,
) -> Dict[str, Any]:
    """Process dataset JSON file with concurrency.

    Args:
        dataset_path: Dataset file path
        config: Configuration dictionary
        limit: Limit processing quantity (0=no limit)
        start: Start index (0-based, default: 0)
        render_image: Whether to render the JSON to PNG image
        save_simplified: Whether to save the simplified JSON output
        max_concurrent: Number of concurrent workers

    Returns:
        Processing results dictionary
    """
    base_dir = Path(__file__).parent

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    if not isinstance(dataset, list):
        raise ValueError("Dataset must be a JSON array")

    total = len(dataset)

    # Apply start index
    if start > 0:
        if start >= total:
            raise ValueError(f"Start index {start} exceeds dataset size {total}")
        dataset = dataset[start:]
        print(f"[Found] {total} items, starting from index {start}")

    # Apply limit
    if limit > 0:
        dataset = dataset[:limit]
        if start > 0:
            print(f"[Processing] Items {start} to {start + len(dataset) - 1} (total {len(dataset)} items)")
        else:
            print(f"[Processing] First {len(dataset)} items")
    else:
        if start > 0:
            print(f"[Processing] Items {start} to {total - 1} (total {len(dataset)} items)")
        else:
            print(f"[Processing] All {total} items")

    # Use output_dir from config
    output_dir = Path(config.get("output_dir", base_dir / "results"))
    model_safe = config.get("model_alias") or config.get("model_name", "model")
    model_safe = model_safe.replace("/", "_").replace(":", "_")
    output_dir = output_dir / model_safe
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Processing {len(dataset)} items with {max_concurrent} workers...", flush=True)

    results = {}
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(
                _process_one_direct_llm, idx, item, config, output_dir, render_image, save_simplified, len(dataset)
            ): idx
            for idx, item in enumerate(dataset)
        }

        for future in as_completed(futures):
            item_id, result, idx, total = future.result()
            results[item_id] = result
            status = result.get("status", "unknown")
            if status == "completed":
                print(f"[{idx + 1}/{total}] {item_id}  ✓ {status}", flush=True)
            elif status == "skipped":
                print(f"[{idx + 1}/{total}] {item_id}  ⚠ skipped", flush=True)
            else:
                err = result.get("error", "")
                print(f"[{idx + 1}/{total}] {item_id}  ✗ {status}: {err}", flush=True)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Directly invoke LLM to convert text to Excalidraw diagram JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--input", "-i", help="Input file path")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--text", "-t", help="Direct text input")
    parser.add_argument("--direct-text", help="txt file path, read file content as input text")
    parser.add_argument("--all", "-a", action="store_true", help="Process all files in input/ directory")
    parser.add_argument("--dataset", "-d", help="Dataset JSON file path")
    parser.add_argument(
        "--env", "-e",
        default=None,
        help="Environment variable file path (default: the repository .env)",
    )
    parser.add_argument("--model", "-m", help="Model name (override .env config)")
    parser.add_argument("--provider", help="Model provider (override .env config)")
    parser.add_argument("--base-url", help="API base URL (override .env config)")
    parser.add_argument("--api-key", help="API key (override .env config)")
    parser.add_argument("--temperature", type=float, help="Temperature parameter (override .env config)")
    parser.add_argument("--limit", "-l", type=int, default=0, help="Limit processing quantity (0=no limit)")
    parser.add_argument("--start", type=int, default=0, help="Start index for dataset processing (0-based)")
    parser.add_argument("--render", "-r", action="store_true", help="Render JSON output to PNG image")
    parser.add_argument("--save-simplified", "-s", action="store_true", help="Save simplified JSON output (for debugging)")
    parser.add_argument("--canvas-library", type=str, default="excalidraw", choices=["tldraw", "excalidraw"], help="Canvas library for output format (default: excalidraw)")
    parser.add_argument("--max-concurrent", type=int, default=1, help="Max concurrent workers for dataset processing (default: 1)")

    args = parser.parse_args()
    base_dir = Path(__file__).parent
    repo_root = Path(__file__).resolve().parents[2]

    # Load environment variables
    from dotenv import load_dotenv
    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()
    # load_dotenv() is a silent no-op on a missing path, so an env file the user
    # explicitly asked for must exist; the default is best-effort but never silent.
    if args.env:
        env_path = Path(args.env)
        if not env_path.is_file():
            parser.error(f"env file not found: {env_path}")
    else:
        env_path = repo_root / ".env"
        if not env_path.is_file():
            print(
                f"[WARN] No env file at {env_path}; provider config comes from the process "
                "environment only.",
                flush=True,
            )
            env_path = None
    if env_path is not None:
        load_dotenv(env_path, override=True)

    requested_model = args.model or os.getenv("LLM_MODEL_NAME")
    named_model_config = _resolve_named_model_config(requested_model)
    resolved_model_name = named_model_config.get("model_name") or requested_model or "qwen3-vl-plus"

    # Build configuration from environment variables
    config = {
        "model_name": resolved_model_name,
        "model_alias": named_model_config.get("model_alias") or requested_model or resolved_model_name,
        "provider": args.provider or named_model_config.get("provider") or os.getenv("LLM_MODEL_PROVIDER", "openai"),
        "base_url": args.base_url or named_model_config.get("base_url") or os.getenv("LLM_ENDPOINT_URL", "https://apis.iflow.cn/v1"),
        "api_key": (
            args.api_key
            or named_model_config.get("api_key")
            or os.getenv("LLM_API_KEY")
            or os.getenv("IFLOW_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        ),
        # Parity with the EvoDiagram generator (max_tokens=16384, max_retries=6,
        # temperature=0); see evo_diagram/agentic_system/main.py.
        "temperature": args.temperature if args.temperature is not None else float(os.getenv("LLM_TEMPERATURE", str(named_model_config.get("temperature", 0)))),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", str(named_model_config.get("max_tokens", 16384)))),
        "max_retries": int(os.getenv("LLM_MAX_RETRIES", "6")),
        "output_dir": os.getenv("LLM_OUTPUT_DIR", str(base_dir.parent.parent / "results" / "baselines" / "direct_llm")),
        "canvas_library": args.canvas_library,
    }

    if not config["api_key"]:
        print("[Warning] API key not found, please set LLM_API_KEY in .env file")

    print("=" * 60)
    print("Direct LLM Text-to-Diagram Converter")
    print("=" * 60)
    print(f"Model: {config['model_name']}")
    print(f"Provider: {config['provider']}")
    print(f"API URL: {config['base_url']}")
    print(f"Temperature: {config['temperature']}")
    print(f"Max Tokens: {config['max_tokens']}")
    print(f"Max Retries: {config['max_retries']}")
    print(f"Canvas Library: {config['canvas_library']}")
    print(f"Output Dir: {config['output_dir']}")
    print("=" * 60)

    try:
        if args.text:
            # Process text directly
            output_path = args.output or str(base_dir / "output" / "direct_output.json")
            state = process_text(args.text, config, output_path, args.render, save_simplified=args.save_simplified)
            if state.is_completed():
                print(f"\n[Completed] Output saved to: {output_path}")

        elif args.direct_text:
            # Read text content from txt file
            direct_text_path = args.direct_text
            if not os.path.isabs(direct_text_path):
                direct_text_path = str(base_dir / direct_text_path)

            if not os.path.exists(direct_text_path):
                raise FileNotFoundError(f"txt file not found: {direct_text_path}")

            print(f"[Reading] {direct_text_path}")
            with open(direct_text_path, "r", encoding="utf-8") as f:
                text_content = f.read().strip()

            if not text_content:
                raise ValueError("txt file content is empty")

            # Generate output path
            output_path = args.output
            if output_path is None:
                input_name = Path(direct_text_path).stem
                model_safe = (config.get("model_alias") or config.get("model_name", "model")).replace("/", "_").replace(":", "_")
                output_path = str(base_dir / "output" / model_safe / input_name / "scene.json")
            elif not os.path.isabs(output_path):
                output_path = str(base_dir / output_path)

            state = process_text(text_content, config, output_path, args.render, save_simplified=args.save_simplified)
            if state.is_completed():
                print(f"\n[Completed] Output saved to: {output_path}")

        elif args.dataset:
            # Process dataset
            results = process_datasets(args.dataset, config, limit=args.limit, start=args.start, render_image=args.render, save_simplified=args.save_simplified, max_concurrent=args.max_concurrent)
            success = sum(1 for r in results.values() if r.get("status") == "completed")
            print(f"\n[Summary] Success: {success}/{len(results)}")

        elif args.all:
            # Process all files
            results = process_all_files(
                config,
                render_image=args.render,
                save_simplified=args.save_simplified,
            )
            success = sum(1 for r in results.values() if r.get("status") == "completed")
            print(f"\n[Summary] Success: {success}/{len(results)}")

        elif args.input:
            # Process single file
            input_path = args.input
            if not os.path.isabs(input_path):
                input_path = str(base_dir / input_path)

            output_path = args.output
            if output_path and not os.path.isabs(output_path):
                output_path = str(base_dir / output_path)

            state = process_file(
                input_path,
                config,
                output_path,
                args.render,
                save_simplified=args.save_simplified,
            )
            if state.is_completed():
                print(f"\n[Completed] Processing successful")

        else:
            # Use default dataset
            default_dataset = base_dir.parent.parent / "dataset" / "test" / "data.json"
            if default_dataset.exists():
                print(f"[Info] Using default dataset: {default_dataset}\n")
                results = process_datasets(str(default_dataset), config, limit=args.limit, start=args.start, render_image=args.render, save_simplified=args.save_simplified, max_concurrent=args.max_concurrent)
                success = sum(1 for r in results.values() if r.get("status") == "completed")
                print(f"\n[Summary] Success: {success}/{len(results)}")
            else:
                parser.print_help()
                print("\nError: Please specify --input, --text, --all, or --dataset")
                sys.exit(1)

    except Exception as e:
        print(f"\n[Error] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
