"""CLI for the iterative refiner.

Usage:
    python -m evo_diagram.agentic_system.refinement_stage \\
        --manifest path/to/diagram_manifest.json \\
        --image    path/to/rendered_diagram.png \\
        [--canvas-library excalidraw] \\
        [--structure path/to/structure_instantiation.json] \\
        [--layout path/to/layout_instantiation.json] \\
        [--verifier-report path/to/verifier_report.json] \\
        [--output-dir path] \\
        [--max-iterations 3] \\
        [--no-rerender] \\
        [--markdown] \\
        [--verbose]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from evo_diagram.canvas_runtime import VALID_CANVAS_LIBRARIES, normalize_canvas_library

logger = logging.getLogger(__name__)
SUPPORTED_CLI_CANVAS_LIBRARIES = ("excalidraw",)


def _load_environment() -> bool:
    try:
        from evo_diagram.utils.env_loader import ensure_env_loaded

        ensure_env_loaded()
        return True
    except Exception as exc:
        logger.error("Could not load EvoDiagram environment variables: %s", exc)
        return False


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="evo_diagram.agentic_system.refinement_stage",
        description=(
            "Verifier-driven Excalidraw diagram refiner. Runs deterministic "
            "fixers and a single VLM call per iteration, re-renders the PNG, "
            "and loops until findings converge or max_iterations exhausted."
        ),
    )
    p.add_argument(
        "--manifest",
        required=True,
        help="Path to diagram_manifest.json (the post-arrow Excalidraw scene).",
    )
    p.add_argument(
        "--image",
        required=True,
        help="Path to rendered_diagram.png (sent to the VLM, never read by Claude).",
    )
    p.add_argument(
        "--canvas-library",
        choices=VALID_CANVAS_LIBRARIES,
        default=None,
        help=(
            "Canvas manifest type. The iterative refiner currently supports "
            "Excalidraw only; TLDraw manifests are rejected at the CLI boundary."
        ),
    )
    p.add_argument(
        "--structure",
        default=None,
        help="Optional path to structure_instantiation.json. Enables chart-type-aware fixers.",
    )
    p.add_argument(
        "--layout",
        default=None,
        help=(
            "Optional path to layout_instantiation.json. When omitted the "
            "layout_audit check does NOT run (it needs layout input, and no "
            "fixer can synthesise one), and refiner_report.json records it "
            "under skipped_objective_checks."
        ),
    )
    p.add_argument(
        "--verifier-report",
        default=None,
        help=(
            "Path to a pre-existing verifier_report.json (containing the "
            "subjective critique). Defaults to <manifest_dir>/verifier_report.json."
        ),
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Where to write refined manifest / image / report. Defaults to manifest's parent.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Max refinement iterations.",
    )
    p.add_argument(
        "--no-rerender",
        action="store_true",
        help="Skip PNG re-render between iterations (faster; LLM sees the original image).",
    )
    p.add_argument(
        "--markdown",
        action="store_true",
        help="Also write refiner_report.md.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging (INFO level).",
    )
    return p.parse_args(argv)


def _infer_canvas_library_from_manifest(manifest_path: Path) -> str:
    """Infer obvious canvas manifests without forcing the input to exist."""
    if not manifest_path.exists():
        return "excalidraw"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "excalidraw"
    if not isinstance(data, dict):
        return "excalidraw"

    manifest_type = str(data.get("type") or "").lower()
    if manifest_type.startswith("excalidraw"):
        return "excalidraw"
    if manifest_type.startswith("tldraw"):
        return "tldraw"
    if "document" in data or "store" in data or "schema" in data:
        return "tldraw"
    return "excalidraw"


def _resolve_canvas_library(args: argparse.Namespace, manifest_path: Path) -> str:
    canvas_library = (
        normalize_canvas_library(args.canvas_library)
        if args.canvas_library
        else _infer_canvas_library_from_manifest(manifest_path)
    )
    if canvas_library not in SUPPORTED_CLI_CANVAS_LIBRARIES:
        supported = ", ".join(SUPPORTED_CLI_CANVAS_LIBRARIES)
        raise ValueError(
            "IterativeRefinerWorkflow currently supports Excalidraw manifests "
            f"only; got canvas_library={canvas_library!r}. Supported: {supported}."
        )
    return canvas_library


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if not _load_environment():
        return 2

    from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow

    manifest_file = Path(args.manifest).resolve()
    try:
        canvas_library = _resolve_canvas_library(args, manifest_file)
    except ValueError as exc:
        logger.error("%s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    manifest_path = str(manifest_file)
    image_path = str(Path(args.image).resolve())
    structure_path = str(Path(args.structure).resolve()) if args.structure else None
    layout_path = str(Path(args.layout).resolve()) if args.layout else None
    verifier_report_path = (
        str(Path(args.verifier_report).resolve()) if args.verifier_report else None
    )
    output_dir = str(Path(args.output_dir).resolve()) if args.output_dir else None

    workflow = IterativeRefinerWorkflow()
    state = workflow.run(
        manifest_path=manifest_path,
        image_path=image_path,
        verifier_report_path=verifier_report_path,
        structure_path=structure_path,
        layout_path=layout_path,
        output_dir=output_dir,
        canvas_library=canvas_library,
        max_iterations=args.max_iterations,
        skip_rerender_between_iterations=args.no_rerender,
        emit_markdown=args.markdown,
    )

    print("=" * 70)
    print(f"Verifier-Refiner — status: {state.status}")
    print(f"Manifest:   {manifest_path}")
    print(f"Image:      {image_path}")
    print(f"Iterations: {state.current_iteration}/{state.max_iterations}"
          f" (converged={state.converged})")
    if state.termination_reason:
        print(f"Termination: {state.termination_reason}")
    if state.skipped_objective_checks:
        print("Objective checks NOT run:")
        for skipped in state.skipped_objective_checks:
            print(f"  - {skipped}")
    if state.refined_manifest_path:
        print(f"Refined manifest: {state.refined_manifest_path}")
    if state.refined_image_path:
        print(f"Refined image:    {state.refined_image_path}")
    if state.refiner_report_path:
        print(f"Report:           {state.refiner_report_path}")

    if state.iteration_logs:
        print()
        print("Per-iteration findings (severity counts):")
        for log in state.iteration_logs:
            before = ", ".join(f"{k}={v}" for k, v in log.findings_before.items())
            after = ", ".join(f"{k}={v}" for k, v in log.findings_after.items())
            print(
                f"  iter {log.iteration}: "
                f"det={len(log.deterministic_edits)} "
                f"llm={len(log.llm_edits)} "
                f"render_ok={log.rerender_ok}"
            )
            print(f"           before: {before}")
            print(f"           after:  {after}")

    if state.errors:
        print()
        print("Errors:")
        for err in state.errors:
            print(f"  - {err}")

    print("=" * 70)
    return 0 if state.status == "reported" and state.converged else 1


if __name__ == "__main__":
    sys.exit(main())
