#!/usr/bin/env python3
"""
Handy Direct LLM Refiner

A CLI tool to perform multi-iteration refinement on already-generated baseline diagrams
using IterativeRefinerWorkflow from evo_diagram.agentic_system.

Usage:
    python -m baselines.direct_llm.handydirectllmrefiner --method baselines_direct_llm_gpt-5.2 --iterations 3
    python -m baselines.direct_llm.handydirectllmrefiner --method baselines_code_mermaid_gemini-3-pro --limit 10
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, List
from dotenv import load_dotenv
from evo_diagram.utils.env_loader import ensure_env_loaded


# Baseline types ordered by length (longest first) to avoid prefix matching issues
BASELINE_TYPES = ["code_mermaid", "code_tlkz", "direct_llm", "pixel"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_method_path(method: str) -> Tuple[str, str, Path]:
    """
    Parse method parameter to extract baseline type, model name, and base path.

    Args:
        method: Method name in format "baselines_<type>_<model>"
                Examples: "baselines_direct_llm_gpt-5.2"
                         "baselines_code_mermaid_gemini-3-pro"

    Returns:
        Tuple of (baseline_type, model_name, base_path)

    Raises:
        ValueError: If method format is invalid
    """
    if not method.startswith("baselines_"):
        raise ValueError(
            f"Invalid method format: '{method}'. "
            f"Expected format: 'baselines_<type>_<model>' where type is one of {BASELINE_TYPES}"
        )

    # Remove "baselines_" prefix
    remaining = method[10:]

    # Find matching baseline type
    baseline_type = None
    model_name = None

    for btype in BASELINE_TYPES:
        if remaining.startswith(btype + "_"):
            baseline_type = btype
            model_name = remaining[len(btype) + 1:]
            break

    if baseline_type is None or not model_name:
        raise ValueError(
            f"Invalid baseline method: '{method}'. "
            f"Available types: {BASELINE_TYPES}. "
            f"Expected format: 'baselines_<type>_<model>'"
        )

    from evo_diagram.core.experiment import get_baseline_output_dir

    base_path = get_baseline_output_dir(baseline_type, model_name)

    return baseline_type, model_name, base_path


def find_files(base_path: Path, data_id: str) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Locate PNG and JSON files for given data_id in base_path.

    Args:
        base_path: Base directory to search in
        data_id: Data item identifier

    Returns:
        Tuple of (png_path, json_path), where either can be None if not found
    """
    sample_dir = base_path / data_id
    png_path = sample_dir / "render.png"
    json_path = sample_dir / "scene.json"

    if not png_path.exists():
        legacy_png_path = base_path / f"{data_id}.png"
        png_path = legacy_png_path
    if not json_path.exists():
        legacy_json_path = base_path / f"{data_id}.json"
        json_path = legacy_json_path

    return (
        png_path if png_path.exists() else None,
        json_path if json_path.exists() else None
    )


def refine_single_item(
    data_id: str,
    manifest_path: Path,
    image_path: Path,
    base_path: Path,
    iterations: int = 3,
    output_suffix: str = "_refined",
    temperature: float = 0.3,
    max_tokens: int = 4000
) -> Dict[str, Any]:
    """
    Execute multi-iteration refinement on a single data item.

    Args:
        data_id: Data item identifier
        manifest_path: Path to initial JSON manifest
        image_path: Path to initial PNG image
        base_path: Output directory
        iterations: Number of refinement rounds (default: 3)
        output_suffix: Output filename suffix (default: "_refined")
        temperature: VLM temperature (default: 0.3)
        max_tokens: VLM max tokens (default: 4000)

    Returns:
        Dictionary with:
            - status: "success" or "failed"
            - iterations_completed: Number of iterations completed
            - final_manifest: Path to final manifest (if success)
            - final_image: Path to final image (if success)
            - error: Error message (if failed)
    """
    try:
        # Initialize workflow
        from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow

        print(f"  [Init] Creating IterativeRefinerWorkflow with {iterations} iterations...")
        workflow = IterativeRefinerWorkflow()

        output_dir = str(base_path / f"{data_id}{output_suffix}_refiner")

        # Run refinement (handles iterations internally via LangGraph)
        result_state = workflow.run(
            manifest_path=str(manifest_path),
            image_path=str(image_path),
            output_dir=output_dir,
            max_iterations=iterations,
            canvas_library="excalidraw",
            emit_markdown=True,
        )

        # Check for failures
        if result_state.status == "failed":
            error_msg = "; ".join(result_state.errors) if result_state.errors else "Unknown error"
            print(f"  [Failed] Refinement failed: {error_msg}")
            return {
                "data_id": data_id,
                "status": "failed",
                "iterations_completed": result_state.current_iteration,
                "error": error_msg
            }

        # Copy refined outputs to final files
        final_manifest = base_path / f"{data_id}{output_suffix}_final.json"
        final_image = base_path / f"{data_id}{output_suffix}_final.png"

        if result_state.refined_manifest_path:
            shutil.copy(result_state.refined_manifest_path, final_manifest)
        if result_state.refined_image_path:
            shutil.copy(result_state.refined_image_path, final_image)

        print(f"  [Complete] Final output: {final_manifest.name}")

        return {
            "data_id": data_id,
            "status": "success",
            "iterations_completed": result_state.current_iteration,
            "final_manifest": str(final_manifest),
            "final_image": str(final_image)
        }

    except Exception as e:
        error_msg = f"Exception during refinement: {str(e)}"
        print(f"  [Error] {error_msg}")
        return {
            "data_id": data_id,
            "status": "failed",
            "iterations_completed": 0,
            "error": error_msg
        }


def main():
    """CLI entry point with argument parsing and batch processing."""
    parser = argparse.ArgumentParser(
        description="Refine already-generated baseline diagrams using IterativeRefinerWorkflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Refine direct_llm baseline
  python -m baselines.direct_llm.handydirectllmrefiner --method baselines_direct_llm_gpt-5.2 --iterations 3

  # Refine code_mermaid baseline with limit
  python -m baselines.direct_llm.handydirectllmrefiner --method baselines_code_mermaid_gemini-3-pro --limit 10

  # Process specific range
  python -m baselines.direct_llm.handydirectllmrefiner --method baselines_pixel_flux-2-flex --start 10 --limit 5
        """
    )

    parser.add_argument(
        "--method",
        required=True,
        help="Method name (e.g., baselines_direct_llm_gpt-5.2, baselines_code_mermaid_gemini-3-pro)"
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=3,
        help="Number of refinement iterations (default: 3)"
    )
    parser.add_argument(
        "--dataset",
        default="dataset/test/data.json",
        help="Dataset JSON path (default: dataset/test/data.json)"
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Start index (0-based, default: 0)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max items to process (default: 0 = all)"
    )
    parser.add_argument(
        "--output-suffix",
        default="_refined",
        help="Output filename suffix (default: _refined)"
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="Environment file path (default: .env)"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="VLM temperature (default: from REFINER_LLM_TEMPERATURE or 0.3)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="VLM max tokens (default: from REFINER_LLM_MAX_TOKENS or 4000)"
    )

    args = parser.parse_args()

    # Load environment variables from .env file
    env_path = PROJECT_ROOT / args.env
    ensure_env_loaded()
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"Loaded environment from: {env_path}")
    else:
        print(f"[Warning] Environment file not found: {env_path}")
        print(f"          Will use existing environment variables")

    print("=" * 80)
    print("Handy Direct LLM Refiner")
    print("=" * 80)

    # Resolve VLM parameters from CLI > env > defaults
    vlm_temperature = args.temperature if args.temperature is not None else float(os.getenv("REFINER_LLM_TEMPERATURE", "0.3"))
    vlm_max_tokens = args.max_tokens if args.max_tokens is not None else int(os.getenv("REFINER_LLM_MAX_TOKENS", "4000"))

    # Display VLM configuration
    print("\nVLM Configuration:")
    print(f"  Provider: {os.getenv('REFINER_LLM_MODEL_PROVIDER', 'NOT SET')}")
    print(f"  Model: {os.getenv('REFINER_LLM_MODEL_NAME', 'NOT SET')}")
    print(f"  Endpoint: {os.getenv('REFINER_LLM_ENDPOINT_URL', 'NOT SET')}")
    print(f"  API Key: {'***' + os.getenv('REFINER_LLM_API_KEY', '')[-8:] if os.getenv('REFINER_LLM_API_KEY') else 'NOT SET'}")
    print(f"  Temperature: {vlm_temperature}")
    print(f"  Max Tokens: {vlm_max_tokens}")

    # Step 1: Parse method to get base path
    try:
        baseline_type, model_name, base_path = parse_method_path(args.method)
        os.environ["REFINER_LLM_MODEL_NAME"] = model_name
        print(f"Method: {args.method}")
        print(f"  Baseline Type: {baseline_type}")
        print(f"  Model Name: {model_name}")
        print(f"  Base Path: {base_path}")
    except ValueError as e:
        print(f"[Error] {e}")
        return 1

    # Check base path exists
    if not base_path.exists():
        print(f"[Error] Base path does not exist: {base_path}")
        print(f"        Make sure you've run the baseline generation first.")
        return 1

    # Step 2: Load dataset
    dataset_path = PROJECT_ROOT / args.dataset
    if not dataset_path.exists():
        print(f"[Error] Dataset not found: {dataset_path}")
        return 1

    print(f"Dataset: {dataset_path}")

    try:
        with open(dataset_path, 'r', encoding='utf-8') as f:
            dataset = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[Error] Failed to parse dataset JSON: {e}")
        return 1

    if not isinstance(dataset, list):
        print(f"[Error] Dataset must be a JSON array")
        return 1

    total = len(dataset)
    print(f"Total items in dataset: {total}")

    # Step 3: Apply start/limit filtering
    if args.start > 0:
        if args.start >= total:
            print(f"[Error] Start index {args.start} exceeds dataset size {total}")
            return 1
        dataset = dataset[args.start:]
        print(f"Starting from index: {args.start}")

    if args.limit > 0:
        dataset = dataset[:args.limit]
        print(f"Processing {len(dataset)} items")
    else:
        print(f"Processing all {len(dataset)} items from start")

    print(f"Refinement iterations: {args.iterations}")
    print("=" * 80)

    # Step 4: Check VLM configuration
    try:
        print("\n[Pre-check] Verifying VLM configuration...")
        from evo_diagram.core.llm_factory import LLMFactory

        LLMFactory.create_for_role(
            "refiner",
            temperature=vlm_temperature,
            max_tokens=vlm_max_tokens
        )
        print("[Pre-check] VLM configuration OK")
    except ValueError as e:
        print(f"[Error] VLM configuration missing: {e}")
        print("        Please set REFINER_LLM_* environment variables")
        return 1

    # Step 5: Process each data item
    results: List[Dict[str, Any]] = []
    success_count = 0
    failed_count = 0
    skipped_count = 0

    for idx, item in enumerate(dataset):
        data_id = item.get("id")
        if not data_id:
            print(f"\n[Progress] {idx + 1}/{len(dataset)} - [Skip] No 'id' field in item")
            skipped_count += 1
            continue

        print(f"\n[Progress] {idx + 1}/{len(dataset)} (ID: {data_id})")

        # Find files
        png_path, json_path = find_files(base_path, data_id)

        if not png_path or not json_path:
            missing = []
            if not png_path:
                missing.append("PNG")
            if not json_path:
                missing.append("JSON")
            print(f"  [Skip] Missing files: {', '.join(missing)}")
            skipped_count += 1
            continue

        print(f"  [Found] PNG: {png_path.name}")
        print(f"  [Found] JSON: {json_path.name}")

        # Refine
        result = refine_single_item(
            data_id=data_id,
            manifest_path=json_path,
            image_path=png_path,
            base_path=base_path,
            iterations=args.iterations,
            output_suffix=args.output_suffix,
            temperature=vlm_temperature,
            max_tokens=vlm_max_tokens
        )

        results.append(result)

        if result["status"] == "success":
            success_count += 1
        else:
            failed_count += 1

    # Step 6: Print summary
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"Total processed: {len(results)}")
    print(f"  Success: {success_count}")
    print(f"  Failed: {failed_count}")
    print(f"  Skipped: {skipped_count}")
    print("=" * 80)

    # Print failed items details
    if failed_count > 0:
        print("\nFailed items:")
        for result in results:
            if result["status"] == "failed":
                print(f"  - {result['data_id']}: {result.get('error', 'Unknown error')}")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
