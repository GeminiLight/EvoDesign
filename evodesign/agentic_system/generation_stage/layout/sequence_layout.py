"""Initial sequence geometry from participant sizes and semantic chronology.

Excalidraw's sequence renderer owns message rows and lifelines. There is no
useful free-form coordinate decision for another model call to make here.
"""
from __future__ import annotations

from .element_shape_estimator import _estimate_text_dimensions


def sequence_layout_geometry(structure: dict, styling: dict) -> dict:
    nodes = structure.get('nodes') or []
    if not nodes:
        raise ValueError('Sequence diagrams require at least one participant')
    widths = {node['id']: max(120.0, styling[node['id']].get('min_width', 120) + 40)
              for node in nodes}
    heights = {node['id']: max(64.0, styling[node['id']].get('min_height', 24) + 30)
               for node in nodes}
    gap = max(widths.values()) + 64
    layout = {node['id']: {'x': 100 + index * gap, 'y': 80,
                          'w': widths[node['id']], 'h': max(heights.values())}
              for index, node in enumerate(nodes)}
    indices = {node['id']: index for index, node in enumerate(nodes)}
    for edge in structure.get('edges') or []:
        forward = indices[edge['source']] <= indices[edge['target']]
        layout[edge['id']] = {
            'start': {'elementId': edge['source'], 'side': 'right' if forward else 'left'},
            'end': {'elementId': edge['target'], 'side': 'left' if forward else 'right'},
        }
    for group in structure.get('groups') or []:
        members = [layout[key] for key in group.get('members', []) if key in widths]
        if not members:
            raise ValueError(f"Sequence lane {group['id']!r} must contain a participant")
        left = min(item['x'] for item in members) - 16
        right = max(item['x'] + item['w'] for item in members) + 16
        for key in (group['id'], group['id'] + ':background'):
            if key in styling:
                layout[key] = {'x': left, 'y': 64, 'w': right-left,
                               'h': max(heights.values()) + 128 + 64 * len(structure.get('edges') or [])}
        title_key = group['id'] + ':title'
        if title_key in styling:
            dims = _estimate_text_dimensions(str(group.get('label') or ''), 18)
            layout[title_key] = {'x': left + 8, 'y': 40, 'w': max(1, dims['width']),
                                 'h': max(24, dims['height'])}
    return layout
