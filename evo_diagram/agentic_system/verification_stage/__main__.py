"""CLI entry point for the verifier workflow.

Usage:
    python -m evo_diagram.agentic_system.verification_stage \\
        --manifest path/to/diagram_manifest.json \\
        --image    path/to/rendered_diagram.png \\
        [--canvas-library excalidraw|tldraw] \\
        [--structure path/to/structure_instantiation.json] \\
        [--layout path/to/layout_instantiation.json] \\
        [--source-text "original input text"] \\
        [--output-dir path] \\
        [--no-critic] \\
        [--markdown]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from evo_diagram.canvas_environment.config import CanvasEnvironmentConfig
from evo_diagram.canvas_runtime import VALID_CANVAS_LIBRARIES, normalize_canvas_library

# Ensure .env is loaded before LLM client construction.
try:
    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()
except Exception:
    # The verifier should still work without the env loader (e.g. when env
    # vars are exported in the shell). Fall through silently.
    pass

from .workflow import VerifierWorkflow


def _resolve_canvas_library(explicit_value: str | None) -> str:
    """Resolve verifier canvas with CLI > settings/env > Excalidraw fallback."""
    if explicit_value:
        return normalize_canvas_library(explicit_value)

    try:
        return CanvasEnvironmentConfig.from_settings().normalized_canvas_library()
    except FileNotFoundError:
        return "excalidraw"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="evo_diagram.agentic_system.verification_stage",
        description=(
            "Run objective + subjective verification on an EvoDiagram render. "
            "Objective checks read the manifest JSON. Subjective critique is "
            "performed by a remote VLM that receives the PNG via the soxio API."
        ),
    )
    p.add_argument(
        "--manifest",
        required=True,
        help="Path to diagram_manifest.json (the rendered canvas scene).",
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
            "Canvas backend used to validate the manifest schema. "
            "Defaults to settings.yaml / CANVAS_LIBRARY."
        ),
    )
    p.add_argument(
        "--structure",
        default=None,
        help=(
            "Optional path to structure_instantiation.json. Enables chart-type-"
            "aware checks (e.g. swimlane lane membership) and feeds chart_type "
            "to the VLM."
        ),
    )
    p.add_argument(
        "--layout",
        default=None,
        help=(
            "Optional path to layout_instantiation.json. Enables layout-aware "
            "objective checks without relying on a structure-path-relative fallback."
        ),
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Where to write verifier_report.json. Defaults to the manifest's "
            "parent directory."
        ),
    )
    p.add_argument(
        "--source-text",
        default=None,
        help=(
            "Original input text that the diagram was generated from. "
            "Passed to the VLM critic for context-aware evaluation."
        ),
    )
    p.add_argument(
        "--no-critic",
        action="store_true",
        help="Skip the VLM critic call (only run objective checks).",
    )
    p.add_argument(
        "--skip-checks",
        type=str,
        default=None,
        help=(
            "Comma-separated list of check categories to skip. "
            "Matches against the check function's category prefix. "
            "Available: schema, render_audit, layout_audit, binding, "
            "containment/group_bbox, containment/swimlane_lane, "
            "collision/node_overlap, collision/edge_crossing, collision/out_of_canvas."
        ),
    )
    p.add_argument(
        "--markdown",
        action="store_true",
        help="Also write a verifier_report.md alongside the JSON report.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging (INFO level).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    manifest_path = str(Path(args.manifest).resolve())
    image_path = str(Path(args.image).resolve())
    structure_path = str(Path(args.structure).resolve()) if args.structure else None
    layout_path = str(Path(args.layout).resolve()) if args.layout else None
    output_dir = str(Path(args.output_dir).resolve()) if args.output_dir else None
    skip_checks = (
        [c.strip() for c in args.skip_checks.split(",") if c.strip()]
        if args.skip_checks
        else []
    )
    canvas_library = _resolve_canvas_library(args.canvas_library)

    workflow = VerifierWorkflow()
    state = workflow.run(
        manifest_path=manifest_path,
        image_path=image_path,
        canvas_library=canvas_library,
        structure_path=structure_path,
        layout_path=layout_path,
        source_text=args.source_text,
        output_dir=output_dir,
        skip_critic=args.no_critic,
        skip_checks=skip_checks,
        emit_markdown=args.markdown,
    )

    # Console summary (don't dump full report — the JSON is the source of truth).
    print("=" * 70)
    print(f"Verifier — status: {state.status}")
    print(f"Manifest: {manifest_path}")
    print(f"Image:    {image_path}")
    if state.report_path:
        print(f"Report:   {state.report_path}")
    summary = state.objective_summary or {}
    print(
        "Objective: "
        + ", ".join(
            f"{k}={summary.get(k, 0)}"
            for k in ("critical", "major", "minor", "info", "total")
        )
    )
    if state.critique is not None:
        c = state.critique
        print(
            f"Subjective: structure={c.structure.score:.1f} "
            f"styling={c.styling.score:.1f} "
            f"layout={c.layout.score:.1f} "
            f"overall={c.overall_score:.1f}"
        )
        if c.summary:
            print(f"  Summary: {c.summary}")
    elif args.no_critic:
        print("Subjective: (skipped)")
    else:
        print("Subjective: (failed — see errors)")

    if state.errors:
        print("\nErrors:")
        for err in state.errors:
            print(f"  - {err}")

    print("=" * 70)
    return state.cli_exit_code


if __name__ == "__main__":
    sys.exit(main())
