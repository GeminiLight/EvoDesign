#!/usr/bin/env python3
"""Re-run deterministic concept-map composition on a saved manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evo_diagram.agentic_system.common.semantic_ids import id_map_from_manifest
from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    rebuild_excalidraw_arrows,
)
from evo_diagram.agentic_system.render_engine.excalidraw.radial_concept_compactor import (
    compact_concept_map_layout,
)
from evo_diagram.agentic_system.render_engine.excalidraw.zorder_repair import repair_zorder
from evo_diagram.canvas_environment import normalize_manifest, render_png_result


def _load_object(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def _label_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        text = value.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _derive_structure(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Recover the semantic graph embedded in id_map and edge_data."""
    id_map = id_map_from_manifest(manifest)
    node_render_ids = {
        semantic_id: render_id
        for semantic_id, render_id in id_map.items()
        if not semantic_id.endswith((":background", ":title", ":label", ":icon"))
        and not semantic_id.startswith("edge:")
    }
    labels_by_container = {
        str(element.get("containerId")): str(element.get("text", ""))
        for element in manifest.get("elements", [])
        if isinstance(element, Mapping)
        and element.get("type") == "text"
        and element.get("containerId")
    }

    metadata = manifest.get("_meta")
    edge_data = metadata.get("edge_data") if isinstance(metadata, Mapping) else None
    if not isinstance(edge_data, Mapping):
        raise ValueError("Saved manifest has no _meta.edge_data to reconstruct structure")

    edges = []
    outgoing: Dict[str, list[str]] = {node_id: [] for node_id in node_render_ids}
    for edge_id, payload in edge_data.items():
        if not isinstance(edge_id, str) or not isinstance(payload, Mapping):
            continue
        start = payload.get("start")
        end = payload.get("end")
        source = start.get("elementId") if isinstance(start, Mapping) else None
        target = end.get("elementId") if isinstance(end, Mapping) else None
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        edge = {"id": edge_id, "source": source, "target": target}
        label = _label_text(payload.get("label"))
        if label:
            edge["label"] = label
        edges.append(edge)
        outgoing.setdefault(source, []).append(target)

    core_id = next(
        (
            node_id for node_id in node_render_ids if node_id.endswith("_core")
        ),
        None,
    )
    if core_id is None:
        def reachable_count(start: str) -> int:
            seen = {start}
            frontier = list(outgoing.get(start, []))
            while frontier:
                node_id = frontier.pop()
                if node_id in seen:
                    continue
                seen.add(node_id)
                frontier.extend(outgoing.get(node_id, []))
            return len(seen) - 1

        core_id = max(
            node_render_ids,
            key=lambda node_id: (
                reachable_count(node_id),
                len(set(outgoing.get(node_id, []))),
                -list(node_render_ids).index(node_id),
            ),
        )
    anchor_ids = set(outgoing.get(core_id, []))
    nodes = []
    for node_id, render_id in node_render_ids.items():
        if node_id == core_id:
            node_class = "core_concept"
        elif node_id in anchor_ids:
            node_class = "branch_anchor"
        else:
            node_class = "concept"
        nodes.append({
            "id": node_id,
            "label": labels_by_container.get(render_id, node_id.replace("_", " ").title()),
            "class": node_class,
        })
    return {"chart_type": "concept_map", "nodes": nodes, "edges": edges, "groups": []}


def _apply_current_edge_styles(manifest: Dict[str, Any]) -> None:
    """Make replay output match the normal new-manifest render path."""
    metadata = manifest.get("_meta")
    edge_data = metadata.get("edge_data") if isinstance(metadata, Mapping) else None
    if not isinstance(edge_data, Mapping):
        return
    style_keys = (
        "strokeColor",
        "strokeWidth",
        "strokeStyle",
        "opacity",
        "roughness",
        "startArrowhead",
        "endArrowhead",
    )
    for element in manifest.get("elements", []):
        if not isinstance(element, dict) or element.get("type") != "arrow":
            continue
        arrow_meta = element.get("meta")
        edge_id = arrow_meta.get("semantic_edge_id") if isinstance(arrow_meta, Mapping) else None
        payload = edge_data.get(edge_id) if isinstance(edge_id, str) else None
        if not isinstance(payload, Mapping):
            continue
        for key in style_keys:
            if key in payload:
                element[key] = payload[key]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--structure", type=Path)
    args = parser.parse_args()

    manifest = _load_object(args.source)
    structure = _load_object(args.structure) if args.structure else _derive_structure(manifest)
    manifest = compact_concept_map_layout(manifest, structure)
    manifest = rebuild_excalidraw_arrows(manifest, structure)
    _apply_current_edge_styles(manifest)
    manifest = repair_zorder(manifest)
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
