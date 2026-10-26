"""Render sequence chronology as lifelines and message rows, never graph routes."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from evo_diagram.agentic_system.common.node_icons import sync_node_icons
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.generation_stage.layout.element_shape_estimator import _estimate_text_dimensions
from .converter import _excalidraw_defaults, _generate_excalidraw_id
from .normalizer import normalize_excalidraw_manifest


def render_sequence_messages(manifest: dict, structure: dict) -> dict:
    """Preserve participant order, exact message labels and sequence_idx.

    The graph nodes represent participant headers. Lifelines are derived visual
    elements, not extra source facts. Transparent lane frames retain group
    membership for editing/auditing without duplicating the actor headings.
    This function is also used when refinement rebuilds connector geometry.
    """
    structure = unwrap_structure_instantiation(structure)
    output = deepcopy(manifest)
    meta = output.setdefault('_meta', {})
    id_map = meta.setdefault('id_map', {})
    nodes = structure.get('nodes', [])
    edges = sorted(structure.get('edges', []), key=lambda edge: edge['sequence_idx'])
    by_id = {element['id']: element for element in output['elements']}
    old_messages = {(item.get('meta') or {}).get('semantic_edge_id'): item
                    for item in output['elements'] if item.get('type') == 'arrow'}
    old_labels = {(item.get('meta') or {}).get('semantic_edge_id'): item
                  for item in output['elements'] if item.get('type') == 'text'
                  and (item.get('meta') or {}).get('semantic_edge_id')}
    headers = {node['id']: by_id.get(id_map.get(node['id'])) for node in nodes}
    if any(header is None for header in headers.values()):
        raise ValueError('Sequence diagram is missing a participant header')
    actor_ids = [node.get('actor_id', node['id']) for node in nodes]
    if len(set(actor_ids)) != len(actor_ids):
        raise ValueError('Sequence diagrams require one semantic node per participant; activations are visual annotations')
    old_arrow_ids = {item['id'] for item in output['elements'] if item.get('type') == 'arrow'}
    removed_ids = {item['id'] for item in output['elements']
                   if item.get('type') == 'arrow' or item.get('containerId') in old_arrow_ids
                   or (item.get('meta') or {}).get('sequence_role') in {'lifeline', 'message_label'}}
    output['elements'] = [item for item in output['elements'] if item['id'] not in removed_ids]
    meta['id_map'] = id_map = {key: value for key, value in id_map.items() if value not in removed_ids}
    for item in output['elements']:
        item['boundElements'] = [bound for bound in item.get('boundElements') or []
                                 if bound.get('id') not in removed_ids]
    sync_node_icons(output)
    payloads = meta.get('edge_data', {})
    labels = {}
    spacing = max((float(header['width']) + 64 for header in headers.values()), default=240)
    indices = {node['id']: i for i, node in enumerate(nodes)}
    for edge in edges:
        payload = payloads.get(edge['id'], {})
        label = edge.get('label') or edge.get('relation') or ''
        if isinstance(label, dict):
            label = label.get('text', '')
        font_size = float((payload.get('label') or {}).get('fontSize', 14)) if isinstance(payload.get('label'), dict) else 14
        font_size = float(old_labels.get(edge['id'], {}).get('fontSize', font_size))
        dimensions = _estimate_text_dimensions(str(label), font_size)
        labels[edge['id']] = (str(label), font_size, dimensions)
        distance = abs(indices[edge['source']] - indices[edge['target']])
        if distance:
            spacing = max(spacing, (dimensions['width'] + 48) / distance)
    first_header = headers[nodes[0]['id']]
    left = float(first_header['x']) + float(first_header['width']) / 2 - spacing / 2
    top = min(float(header['y']) for header in headers.values())
    header_height = max(float(header['height']) for header in headers.values())
    centers = {}
    for index, node in enumerate(nodes):
        header = headers[node['id']]
        center_x = left + spacing / 2 + index * spacing
        dx = center_x - (float(header['x']) + float(header['width']) / 2)
        header.update(x=center_x - float(header['width']) / 2, y=top, height=header_height, angle=0)
        for item in output['elements']:
            if item.get('containerId') == header['id']:
                item['x'] += dx
                item['y'] = top + (header_height - float(item['height'])) / 2
        centers[node['id']] = center_x
    sync_node_icons(output)
    row_height = max([64.0] + [float(dimensions['height']) + 36 for _, _, dimensions in labels.values()])
    first_y = top + header_height + 56
    bottom = first_y + row_height * max(len(edges) - 1, 0) + 48
    # Lane backgrounds are navigation only; headers already carry their labels.
    for group in structure.get('groups', []):
        members = group.get('members', [])
        member = next((member for member in members if member in centers), None)
        for key in (group['id'], group['id'] + ':background'):
            frame = by_id.get(id_map.get(key))
            if frame is not None and member is not None:
                frame.update(x=centers[member] - spacing / 2, y=top - 16,
                             width=spacing, height=bottom - top + 32, opacity=0, is_group=True)
                for item in output['elements']:
                    if item.get('containerId') == frame['id']:
                        item['opacity'] = 0
        title = by_id.get(id_map.get(group['id'] + ':title'))
        if title is not None:
            title.update(opacity=0, x=centers.get(member, left), y=top)
    for node in nodes:
        semantic_id = node['id'] + ':lifeline'
        line_id = _generate_excalidraw_id(['sequence', semantic_id])
        id_map[semantic_id] = line_id
        output['elements'].append({
            **_excalidraw_defaults(['sequence', semantic_id]), 'id': line_id, 'type': 'line',
            'x': centers[node['id']], 'y': top + header_height, 'width': 0,
            'height': bottom - top - header_height, 'points': [[0, 0], [0, bottom - top - header_height]],
            'strokeColor': '#94A3B8', 'backgroundColor': 'transparent', 'strokeStyle': 'dashed',
            'strokeWidth': 1, 'roughness': 0, 'roundness': None,
            'startArrowhead': None, 'endArrowhead': None,
            'meta': {'sequence_role': 'lifeline', 'actor_id': node['id']},
        })
    for index, edge in enumerate(edges):
        label, font_size, dimensions = labels[edge['id']]
        payload = payloads.get(edge['id'], {})
        previous = old_messages.get(edge['id'], {})
        x1, x2 = centers[edge['source']], centers[edge['target']]
        y = first_y + index * row_height
        points = [[0, 0], [x2 - x1, 0]]
        if edge['source'] == edge['target']:
            # A self-message has a short rectangular return, consuming one row.
            points = [[0, 0], [max(88, dimensions['width'] + 24), 0],
                      [max(88, dimensions['width'] + 24), 24], [0, 24]]
        arrow_id = _generate_excalidraw_id(['sequence-message', edge['id']])
        id_map[edge['id']] = arrow_id
        kind = str(edge.get('message_kind') or edge.get('message_type') or '').lower()
        stroke_style = 'dashed' if kind in {'return', 'reply', 'response'} else previous.get('strokeStyle', payload.get('strokeStyle', 'solid'))
        output['elements'].append({
            **_excalidraw_defaults(['sequence-message', edge['id']]), 'id': arrow_id, 'type': 'arrow',
            'x': x1, 'y': y, 'width': max(abs(point[0]) for point in points),
            'height': max(point[1] for point in points), 'points': points,
            'strokeColor': previous.get('strokeColor', payload.get('strokeColor', '#475569')),
            'strokeWidth': previous.get('strokeWidth', payload.get('strokeWidth', 1.5)),
            'strokeStyle': stroke_style, 'roughness': 0, 'roundness': None, 'elbowed': False,
            'startArrowhead': None, 'endArrowhead': 'triangle', 'startBinding': None, 'endBinding': None,
            'meta': {'semantic_edge_id': edge['id'], 'source': edge['source'], 'target': edge['target'],
                     'sequence_idx': edge['sequence_idx']},
        })
        if label:
            text_id = _generate_excalidraw_id(['sequence-label', edge['id']])
            id_map[edge['id'] + ':label'] = text_id
            label_center = (x1 + x2) / 2 if x1 != x2 else x1 + points[1][0] / 2
            output['elements'].append({
                **_excalidraw_defaults(['sequence-label', edge['id']]), 'id': text_id, 'type': 'text',
                'x': label_center - dimensions['width'] / 2, 'y': y - dimensions['height'] - 8,
                'width': dimensions['width'], 'height': dimensions['height'],
                'text': label, 'originalText': label, 'fontSize': font_size, 'fontFamily': 2,
                'strokeColor': old_labels.get(edge['id'], {}).get('strokeColor', '#1E293B'),
                'textAlign': 'center', 'verticalAlign': 'middle',
                'containerId': None, 'autoResize': True, 'lineHeight': 1.2,
                'meta': {'sequence_role': 'message_label', 'semantic_edge_id': edge['id']},
            })
    return normalize_excalidraw_manifest(output)
