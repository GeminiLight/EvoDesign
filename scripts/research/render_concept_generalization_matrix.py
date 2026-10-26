#!/usr/bin/env python3
"""Render topic-agnostic concept-map fixtures through the production algorithm."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    add_excalidraw_arrows_to_manifest,
)
from evo_diagram.agentic_system.render_engine.excalidraw.converter import (
    InstantiationToExcalidrawConverter,
)
from evo_diagram.agentic_system.render_engine.excalidraw.radial_concept_compactor import (
    compact_concept_map_layout,
)
from evo_diagram.agentic_system.render_engine.excalidraw.zorder_repair import repair_zorder
from evo_diagram.canvas_environment import normalize_manifest, render_png_result


def _case(
    name: str,
    root: tuple[str, str],
    branches: Mapping[str, tuple[str, Iterable[tuple[str, str]]]],
    cross_edges: Iterable[tuple[str, str, str, str]],
    *,
    mark_roles: bool,
) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = [{"id": root[0], "label": root[1]}]
    if mark_roles:
        nodes[0]["class"] = "core_concept"
    edges: List[Dict[str, Any]] = []
    for branch_index, (branch_id, (branch_label, members)) in enumerate(branches.items()):
        branch = {"id": branch_id, "label": branch_label}
        if mark_roles:
            branch["class"] = "branch_anchor"
        nodes.append(branch)
        edges.append({
            "id": f"root_{branch_index}",
            "source": root[0],
            "target": branch_id,
            "label": "organized into",
        })
        for member_index, (member_id, member_label) in enumerate(members):
            nodes.append({"id": member_id, "label": member_label})
            edges.append({
                "id": f"{branch_id}_{member_index}",
                "source": branch_id,
                "target": member_id,
                "label": "includes",
            })
    for edge_id, source, target, label in cross_edges:
        edges.append({"id": edge_id, "source": source, "target": target, "label": label})
    return {"name": name, "chart_type": "concept_map", "nodes": nodes, "edges": edges}


CASES = [
    _case(
        "software_delivery",
        ("delivery", "Product Delivery"),
        {
            "discover": ("Discover", [("research", "Research"), ("insights", "Insights")]),
            "build": ("Build", [("design", "Design"), ("development", "Development"), ("testing", "Testing")]),
            "operate": ("Operate", [("deploy", "Deploy"), ("observe", "Observe"), ("improve", "Improve")]),
        },
        [
            ("research_insights", "research", "insights", "produces"),
            ("insights_design", "insights", "design", "informs"),
            ("design_development", "design", "development", "guides"),
            ("development_testing", "development", "testing", "verified by"),
            ("testing_deploy", "testing", "deploy", "releases"),
            ("observe_improve", "observe", "improve", "drives"),
        ],
        mark_roles=False,
    ),
    _case(
        "resilient_city",
        ("city", "Resilient City"),
        {
            "mobility": ("Mobility", [("transit", "Public Transit"), ("walking", "Walking"), ("cycling", "Cycling")]),
            "energy": ("Energy", [("solar", "Solar"), ("storage", "Storage"), ("grid", "Smart Grid")]),
            "water": ("Water", [("supply", "Supply"), ("reuse", "Reuse")]),
            "community": ("Community", [("housing", "Housing"), ("health", "Public Health"), ("parks", "Parks")]),
            "governance": ("Governance", [("planning", "Planning"), ("funding", "Funding")]),
        },
        [
            ("solar_grid", "solar", "grid", "feeds"),
            ("storage_grid", "storage", "grid", "stabilizes"),
            ("planning_transit", "planning", "transit", "prioritizes"),
            ("parks_health", "parks", "health", "supports"),
        ],
        mark_roles=True,
    ),
    _case(
        "learning_program",
        ("program", "Learning Program"),
        {
            "curriculum": ("Curriculum", [("concepts", "Core Concepts"), ("projects", "Projects"), ("assessment", "Assessment")]),
            "experience": ("Experience", [("coaching", "Coaching"), ("practice", "Practice"), ("feedback", "Feedback")]),
        },
        [
            ("projects_practice", "projects", "practice", "creates"),
            ("feedback_assessment", "feedback", "assessment", "improves"),
        ],
        mark_roles=False,
    ),
]


def _layout(structure: Mapping[str, Any]) -> Dict[str, Any]:
    layout: Dict[str, Any] = {}
    for index, node in enumerate(structure["nodes"]):
        layout[node["id"]] = {
            "type": "ellipse" if index < 6 else "rectangle",
            "x": 40.0 + index * 92.0,
            "y": 40.0 + (index % 3) * 70.0,
            "w": max(160.0, min(240.0, len(node["label"]) * 10.0 + 48.0)),
            "h": 54.0,
            "label": {"text": node["label"]},
        }
    for edge in structure["edges"]:
        layout[edge["id"]] = {
            "type": "arrow",
            "start": {"elementId": edge["source"], "side": "right"},
            "end": {"elementId": edge["target"], "side": "left"},
            "label": {"text": edge["label"]},
        }
    return layout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=REPOSITORY_ROOT / "examples" / "concept_generalization_matrix",
    )
    args = parser.parse_args()

    for case in CASES:
        structure = {key: value for key, value in case.items() if key != "name"}
        manifest = InstantiationToExcalidrawConverter(
            layout_instantiation=_layout(structure),
            structure_instantiation=structure,
        ).convert()
        manifest = compact_concept_map_layout(manifest, structure)
        manifest = add_excalidraw_arrows_to_manifest(manifest, structure)
        manifest = repair_zorder(manifest)
        normalize_manifest(manifest, canvas_library="excalidraw")

        case_dir = args.output_dir / str(case["name"])
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
            raise RuntimeError(result.error or f"Failed to render {case['name']}")
        strategy = manifest.get("_meta", {}).get("concept_layout_selection", {}).get("strategy")
        print(f"{case['name']}: {strategy}: {png_path}")


if __name__ == "__main__":
    main()
