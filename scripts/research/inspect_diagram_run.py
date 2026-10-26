"""Read a full pipeline run and print comparable geometry and semantic evidence.

Usage: python -m scripts.research.inspect_diagram_run <run-directory>
This tool never alters generation artifacts and does not replace visual review.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from math import hypot
from pathlib import Path
from typing import Any

from PIL import Image

from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.render_engine.shared.edge_crossing_detector import detect_crossings
from evo_diagram.agentic_system.verification_stage.checks.aggregator import run_all_checks
from evo_diagram.agentic_system.verification_stage.checks.finding import summarize_findings


def inspect_run(run_dir: Path) -> dict[str, Any]:
    """Summarize the actual final manifest plus the original semantic graph."""
    manifest_path = run_dir / 'final_diagram_manifest.json'
    image_path = run_dir / 'rendered_diagram.png'
    structure_path = run_dir / '1_structure/structure_instantiation.json'
    if not structure_path.exists():
        structure_path = run_dir / '1_unified/structure_instantiation.json'
    layout_path = run_dir / '3_layout/layout_instantiation.json'
    manifest = json.loads(manifest_path.read_text())
    structure = unwrap_structure_instantiation(json.loads(structure_path.read_text()))
    layout = json.loads(layout_path.read_text()) if layout_path.exists() else None
    elements = [
        element for element in manifest.get('elements', [])
        if not element.get('isDeleted') and float(element.get('opacity', 100)) > 0
    ]
    arrows = [element for element in elements if element.get('type') == 'arrow']
    arrow_ids = {element['id'] for element in arrows}
    visible_semantic_edges = {
        (element.get('meta') or {}).get('semantic_edge_id') for element in arrows
    } - {None}
    arrows_by_semantic_id = {
        (element.get('meta') or {}).get('semantic_edge_id'): element for element in arrows
    }
    label_distances = []
    for element in elements:
        if element.get('type') != 'text':
            continue
        semantic_id = (element.get('meta') or {}).get('semantic_edge_id')
        arrow = arrows_by_semantic_id.get(semantic_id) if semantic_id else None
        if arrow is None:
            continue
        left, top = element.get('x', 0), element.get('y', 0)
        right, bottom = left + element.get('width', 0), top + element.get('height', 0)
        points = [(arrow.get('x', 0) + x, arrow.get('y', 0) + y) for x, y in arrow.get('points', [])]
        distances = []
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            if abs(ay - by) < 1e-6:
                distances.append(hypot(max(min(ax, bx) - right, left - max(ax, bx), 0), max(top - ay, ay - bottom, 0)))
            elif abs(ax - bx) < 1e-6:
                distances.append(hypot(max(left - ax, ax - right, 0), max(min(ay, by) - bottom, top - max(ay, by), 0)))
        if distances:
            label_distances.append({'edge': semantic_id, 'text': element.get('text'), 'distance': round(min(distances), 1)})
    edge_length = sum(
        hypot(b[0] - a[0], b[1] - a[1])
        for arrow in arrows
        for a, b in zip(arrow.get('points', []), arrow.get('points', [])[1:])
    )
    xs, ys = [], []
    for element in elements:
        x, y = element.get('x', 0), element.get('y', 0)
        if element.get('type') in {'arrow', 'line'}:
            xs.extend(x + point[0] for point in element.get('points', []))
            ys.extend(y + point[1] for point in element.get('points', []))
        else:
            xs.extend([x, x + element.get('width', 0)])
            ys.extend([y, y + element.get('height', 0)])
    findings = run_all_checks(
        manifest, structure, layout_instantiation=layout,
        skip_categories=["layout_audit"] if structure_path.parent.name == '1_unified' else None,
    )
    nodes = structure.get('nodes', [])
    edges = structure.get('edges', [])
    labels = {node['id']: node.get('label', node['id']) for node in nodes}
    with Image.open(image_path) as image:
        image_size = list(image.size)
    return {
        'run_directory': str(run_dir.resolve()),
        'png': str(image_path.resolve()),
        'png_size': image_size,
        'nodes': len(nodes),
        'semantic_edges': len(edges),
        'visible_arrows': len(arrows),
        'edge_labels': sum(
            element.get('type') == 'text' and (
                element.get('containerId') in arrow_ids
                or (element.get('meta') or {}).get('semantic_arrow_id') in arrow_ids
                or (element.get('meta') or {}).get('semantic_edge_id') in visible_semantic_edges
            )
            for element in elements
        ),
        'visible_bounds': [round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)],
        'total_edge_length': round(edge_length, 1),
        'max_label_distance': max((label['distance'] for label in label_distances), default=0),
        'distant_labels': [label for label in label_distances if label['distance'] > 32],
        'crossings': detect_crossings(arrows),
        'objective_summary': summarize_findings(findings),
        'finding_categories': dict(Counter(finding.category for finding in findings)),
        'findings': [finding.to_dict() for finding in findings],
        'node_labels': list(labels.values()),
        'relations': [
            {
                'id': edge.get('id'),
                'source': labels.get(edge.get('source'), edge.get('source')),
                'predicate': edge.get('label', edge.get('relation')),
                'target': labels.get(edge.get('target'), edge.get('target')),
                'type': edge.get('relation_type'),
                'directionality': edge.get('directionality'),
                'evidence': edge.get('evidence_basis'),
            }
            for edge in edges
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_run(args.run_dir), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
