"""Check real-model matrix outputs against source facts, independently of the critic."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re


def normalized(text):
    return ' '.join(str(text or '').lower().split())


def check(case, result, icons):
    structure = result['thought_trace']['structure_instantiation']
    scene = result['schema_blob']
    elements = {element['id']: element for element in scene['elements']
                if not element.get('isDeleted') and element.get('opacity', 100) > 0}
    id_map = scene.get('_meta', {}).get('id_map', {})
    nodes = {node['id']: node['label'] for node in structure['nodes']}
    errors = []
    expected_labels = Counter(map(normalized, case['labels']))
    actual_labels = Counter(map(normalized, nodes.values()))
    if actual_labels != expected_labels:
        errors.append({'nodes': {'missing': list((expected_labels - actual_labels).elements()),
                                 'extra': list((actual_labels - expected_labels).elements())}})
    expected_edges = Counter((normalized(a), normalized(b)) for a, b in case['edges'])
    actual_edges = Counter((normalized(nodes.get(edge['source'], edge['source'])),
                            normalized(nodes.get(edge['target'], edge['target']))) for edge in structure['edges'])
    if actual_edges != expected_edges:
        errors.append({'edges': {'missing': list((expected_edges - actual_edges).elements()),
                                 'extra': list((actual_edges - expected_edges).elements())}})
    rendered_labels = {normalized(element.get('originalText', element.get('text', '')))
                       for element in elements.values() if element.get('type') == 'text'}
    missing_visible = [label for label in case['labels'] if normalized(label) not in rendered_labels]
    if missing_visible:
        errors.append({'missing_visible_labels': missing_visible})
    icon_elements = [element for element in elements.values() if element.get('type') == 'image']
    inverse = {value: key for key, value in id_map.items()}
    icon_hosts = []
    for icon in icon_elements:
        host_id = icon.get('customData', {}).get('evoDesignIcon', {}).get('hostId')
        host = elements.get(host_id)
        icon_hosts.append(normalized(nodes.get(inverse.get(host_id), host_id)))
        if not host:
            errors.append({'orphan_icon': icon['id']})
            continue
        if not (host['x'] <= icon['x'] <= icon['x'] + icon['width'] <= host['x'] + host['width']
                and host['y'] <= icon['y'] <= icon['y'] + icon['height'] <= host['y'] + host['height']):
            errors.append({'icon_outside_host': icon['id']})
        asset = scene.get('files', {}).get(icon.get('fileId'), {})
        if not asset.get('dataURL', '').startswith('data:image/svg+xml'):
            errors.append({'unembedded_icon': icon['id']})
    expected_icons = Counter(map(normalized, case['icon_labels'])) if icons else Counter()
    if Counter(icon_hosts) != expected_icons:
        errors.append({'icon_hosts': {'expected': list(expected_icons.elements()), 'actual': icon_hosts}})
    arrows = {element.get('meta', {}).get('semantic_edge_id'): element
              for element in elements.values() if element.get('type') == 'arrow'}
    if set(arrows) != {edge['id'] for edge in structure['edges']}:
        errors.append({'rendered_edge_ids': list(arrows)})
    if case['diagram_type'] == 'sequence_diagram':
        ordered = sorted(structure['edges'], key=lambda edge: edge.get('sequence_idx', -1))
        headers = sorted((element for node_id in nodes if (element := elements.get(id_map.get(node_id)))),
                         key=lambda element: element['x'] + element['width'] / 2)
        if [normalized(nodes[inverse[header['id']]]) for header in headers] != list(map(normalized, case['labels'])):
            errors.append({'participant_order': [inverse[header['id']] for header in headers]})
        directed_messages = [(normalized(nodes[edge['source']]), normalized(nodes[edge['target']])) for edge in ordered]
        if directed_messages != [(normalized(a), normalized(b)) for a, b in case['edges']]:
            errors.append({'message_endpoints_in_order': directed_messages})
        labels = [normalized(re.sub(r'^\d+[.):]\s*', '', edge.get('label', edge.get('relation', '')))) for edge in ordered]
        if labels != list(map(normalized, case['messages'])):
            errors.append({'message_order': labels})
        ys = []
        for index, edge in enumerate(ordered, 1):
            arrow = arrows.get(edge['id'], {})
            if index in case.get('return_messages', []) and arrow.get('strokeStyle') != 'dashed':
                errors.append({'return_style': edge['id']})
            points = arrow.get('points', [])
            heights = [arrow.get('y', 0) + point[1] for point in points]
            if not heights or max(heights) - min(heights) > 1:
                errors.append({'non_horizontal_message': edge['id']})
            ys.append(sum(heights) / len(heights) if heights else 0)
        if any(a >= b for a, b in zip(ys, ys[1:])):
            errors.append({'rendered_message_order': ys})
        lifelines = [element for element in elements.values()
                     if element.get('type') == 'line' and element.get('strokeStyle') == 'dashed']
        if len(lifelines) != len(case['labels']):
            errors.append({'lifeline_count': len(lifelines)})
    if case['diagram_type'] == 'flowchart':
        for node_id, label in nodes.items():
            if label.endswith('?') and elements.get(id_map.get(node_id), {}).get('type') != 'diamond':
                errors.append({'decision_shape': label})
        for source, target, label in case.get('branch_labels', []):
            matching = [edge for edge in structure['edges']
                        if normalized(nodes[edge['source']]) == normalized(source)
                        and normalized(nodes[edge['target']]) == normalized(target)]
            if len(matching) != 1 or normalized(matching[0].get('label')) != normalized(label):
                errors.append({'branch_label': [source, target, label]})
                continue
            arrow_id = arrows.get(matching[0]['id'], {}).get('id')
            texts = [element for element in elements.values()
                     if element.get('type') == 'text' and element.get('containerId') == arrow_id]
            if len(texts) != 1 or normalized(texts[0].get('originalText', texts[0].get('text'))) != normalized(label):
                errors.append({'rendered_branch_label': [source, target, label]})
    return {'passed': not errors, 'errors': errors, 'nodes': len(nodes),
            'edges': len(structure['edges']), 'icons': len(icon_elements)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    cases = json.loads(Path(__file__).with_name('diagram_matrix_cases.json').read_text())
    checks = {}
    for case in cases:
        for icons in (False, True):
            name = case['id'] + ('_icons' if icons else '_plain')
            path = args.output / name / 'result.json'
            if path.exists():
                checks[name] = check(case, json.loads(path.read_text()), icons)
            else:
                checks[name] = {'passed': False, 'errors': ['No delivered result']}
    (args.output / 'semantic_checks.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(json.dumps(checks, indent=2))
