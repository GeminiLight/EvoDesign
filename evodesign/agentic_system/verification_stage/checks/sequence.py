"""Independent sequence identity and chronology checks on the rendered scene."""
from __future__ import annotations

from .finding import Finding, Severity


def check_sequence(manifest: dict, structure: dict | None) -> list[Finding]:
    if not structure or structure.get('chart_type') != 'sequence_diagram':
        return []
    elements = {element['id']: element for element in manifest.get('elements', [])
                if not element.get('isDeleted') and element.get('opacity', 100) > 0}
    id_map = manifest.get('_meta', {}).get('id_map', {})
    arrows = {element.get('meta', {}).get('semantic_edge_id'): element for element in elements.values()
              if element.get('type') == 'arrow'}
    findings = []

    def fail(message, element_id=None):
        findings.append(Finding(category='sequence/chronology', severity=Severity.MAJOR,
                                message=message, element_id=element_id))

    centers, tops = {}, []
    for node in structure.get('nodes', []):
        header = elements.get(id_map.get(node['id']))
        if not header:
            fail(f"Missing sequence participant: {node['label']}")
            continue
        centers[node['id']] = header['x'] + header['width'] / 2
        tops.append(header['y'])
        lines = [element for element in elements.values() if element.get('type') == 'line'
                 and element.get('strokeStyle') == 'dashed'
                 and abs(element.get('x', 0) - centers[node['id']]) <= 2
                 and abs(element.get('y', 0) - header['y'] - header['height']) <= 2
                 and element.get('height', 0) > 0 and abs(element.get('width', 0)) <= 2]
        if len(lines) != 1:
            fail(f"Participant {node['label']} needs one vertical dashed lifeline", header['id'])
    if tops and max(tops) - min(tops) > 2:
        fail('Sequence participant headers must share the same top row')
    previous_bottom = float('-inf')
    for edge in sorted(structure.get('edges', []), key=lambda item: item.get('sequence_idx', -1)):
        arrow = arrows.get(edge['id'])
        if arrow is None:
            fail(f"Missing sequence message: {edge['id']}")
            continue
        points = [(arrow['x'] + point[0], arrow['y'] + point[1]) for point in arrow.get('points', [])]
        if len(points) < 2:
            fail('Sequence message has no usable geometry', arrow['id'])
            continue
        top, bottom = min(y for _, y in points), max(y for _, y in points)
        if top <= previous_bottom + 2:
            fail('Sequence messages are not in distinct chronological rows', arrow['id'])
        previous_bottom = bottom
        if edge['source'] != edge['target'] and bottom - top > 2:
            fail('Sequence message must be horizontal between lifelines', arrow['id'])
        for point, endpoint in [(points[0], edge['source']), (points[-1], edge['target'])]:
            if endpoint in centers and abs(point[0] - centers[endpoint]) > 2:
                fail('Sequence message is disconnected from its participant lifeline', arrow['id'])
        kind = str(edge.get('message_kind') or edge.get('message_type') or '').lower()
        if kind in {'return', 'reply', 'response'} and arrow.get('strokeStyle') != 'dashed':
            fail('Sequence return message must use a dashed arrow', arrow['id'])
    return findings
