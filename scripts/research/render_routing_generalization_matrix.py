#!/usr/bin/env python3
"""Render non-domain-specific fixtures through the shared route planner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    add_excalidraw_arrows_to_manifest,
)
from evo_diagram.agentic_system.render_engine.excalidraw.converter import (
    InstantiationToExcalidrawConverter,
)
from evo_diagram.agentic_system.render_engine.excalidraw.zorder_repair import repair_zorder
from evo_diagram.agentic_system.render_engine.shared.edge_crossing_detector import (
    detect_crossings,
)
from evo_diagram.canvas_environment import normalize_manifest, render_png_result


def _crossing_flowchart() -> tuple[Dict[str, Any], Dict[str, Any]]:
    structure = {
        "chart_type": "flowchart",
        "nodes": [
            {"id": "intake", "label": "Request Intake"},
            {"id": "delivery", "label": "Delivery"},
            {"id": "review", "label": "Review"},
            {"id": "archive", "label": "Archive"},
        ],
        "edges": [
            {
                "id": "delivery_path",
                "source": "intake",
                "target": "delivery",
            },
            {
                "id": "audit_path",
                "source": "review",
                "target": "archive",
            },
        ],
    }
    layout = {
        "intake": {
            "type": "rectangle",
            "x": 20,
            "y": 220,
            "w": 160,
            "h": 60,
            "label": {"text": "Request Intake"},
        },
        "delivery": {
            "type": "rectangle",
            "x": 820,
            "y": 220,
            "w": 160,
            "h": 60,
            "label": {"text": "Delivery"},
        },
        "review": {
            "type": "rectangle",
            "x": 320,
            "y": 120,
            "w": 160,
            "h": 60,
            "label": {"text": "Review"},
        },
        "archive": {
            "type": "rectangle",
            "x": 320,
            "y": 320,
            "w": 160,
            "h": 60,
            "label": {"text": "Archive"},
        },
        "delivery_path": {
            "start": {"elementId": "intake", "side": "right"},
            "end": {"elementId": "delivery", "side": "left"},
        },
        "audit_path": {
            "start": {"elementId": "review", "side": "bottom"},
            "end": {"elementId": "archive", "side": "top"},
        },
    }
    return structure, layout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=REPOSITORY_ROOT / "examples" / "routing_generalization_matrix",
    )
    args = parser.parse_args()

    structure, layout = _crossing_flowchart()
    manifest = InstantiationToExcalidrawConverter(
        layout_instantiation=layout,
        structure_instantiation=structure,
    ).convert()
    manifest = add_excalidraw_arrows_to_manifest(manifest, structure)
    manifest = repair_zorder(manifest)
    normalize_manifest(manifest, canvas_library="excalidraw")

    case_dir = args.output_dir / "flowchart"
    case_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = case_dir / "diagram_manifest.json"
    png_path = case_dir / "diagram_manifest.png"
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
        raise RuntimeError(result.error or "Failed to render flowchart fixture")

    visible_arrows = [
        element
        for element in manifest.get("elements", [])
        if isinstance(element, dict)
        and element.get("type") == "arrow"
        and float(element.get("opacity", 100) or 0) > 0
    ]
    print(f"flowchart: crossings={len(detect_crossings(visible_arrows))}: {png_path}")


if __name__ == "__main__":
    main()
