#!/usr/bin/env python3
"""Re-run deterministic architecture polish passes on a saved manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evo_diagram.agentic_system.render_engine.excalidraw.architecture_style_normalizer import (
    normalize_architecture_style,
)
from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    rebuild_excalidraw_arrows,
)
from evo_diagram.agentic_system.render_engine.excalidraw.layered_layout_compactor import (
    compact_architecture_layout,
)
from evo_diagram.canvas_environment import normalize_manifest, render_png_result


def _load_manifest(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a manifest object in {path}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--renderer-only",
        action="store_true",
        help="Preserve saved geometry and apply only the style normalizer before rendering.",
    )
    parser.add_argument(
        "--rebuild-arrows-only",
        action="store_true",
        help="Preserve saved node geometry while rebuilding deterministic arrow routes.",
    )
    args = parser.parse_args()
    if args.renderer_only and args.rebuild_arrows_only:
        parser.error("--renderer-only and --rebuild-arrows-only are mutually exclusive")

    manifest = _load_manifest(args.source)
    structure = manifest.get("_meta", {}).get("structure_instantiation")
    if not isinstance(structure, dict):
        raise ValueError("Manifest is missing _meta.structure_instantiation")

    if not args.renderer_only:
        if not args.rebuild_arrows_only:
            manifest = compact_architecture_layout(manifest, structure)
        manifest = rebuild_excalidraw_arrows(manifest, structure)
    manifest = normalize_architecture_style(manifest, structure)
    normalize_manifest(manifest, canvas_library="excalidraw")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "diagram_manifest.json"
    png_path = args.output_dir / "diagram_manifest.png"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result = render_png_result(
        manifest,
        str(png_path),
        canvas_library="excalidraw",
    )
    if not result.ok:
        raise RuntimeError(result.error or "Renderer failed without an error message")
    print(manifest_path)
    print(png_path)


if __name__ == "__main__":
    main()
