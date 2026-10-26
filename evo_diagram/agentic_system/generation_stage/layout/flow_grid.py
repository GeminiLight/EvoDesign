"""Compile model-chosen flowchart cells into measured, non-overlapping boxes.

The model owns rows, columns and every edge port. This only removes pixel
arithmetic for ungrouped flows; canonical geometry remains the escape hatch.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math

from evo_diagram.canvas_runtime import CANVAS_DEFAULT_VIEWPORT_HEIGHT, CANVAS_DEFAULT_VIEWPORT_WIDTH
from .element_shape_estimator import estimate_element_sizes
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation


def supports_flow_grid(structure: dict, styling: dict, runtime_directives: str = '') -> bool:
    nodes = structure.get('nodes') or []
    if structure.get('chart_type') != 'flowchart' or structure.get('groups') or not 1 <= len(nodes) <= 32:
        return False
    if runtime_directives.strip():
        # Only the known empty request context is eligible. Existing geometry,
        # locks and arbitrary refinement directives retain the original path.
        prefix = '=== RUNTIME DIRECTIVES (HIGHEST PRIORITY) ===\n'
        if not runtime_directives.startswith(prefix):
            return False
        try:
            context = json.loads(runtime_directives[len(prefix):])
        except ValueError:
            return False
        if context != {'locked_nodes': [], 'current_schema': None}:
            return False
    node_ids = {node['id'] for node in nodes}
    allowed = node_ids | {edge['id'] for edge in structure.get('edges', [])} | {key + ':icon' for key in node_ids}
    return set(styling) <= allowed and node_ids <= set(styling)


def flow_grid_sizes(structure: dict, styling: dict) -> dict[str, tuple[int, int]]:
    estimated = estimate_element_sizes(styling, structure)
    sizes = {}
    for node in structure['nodes']:
        entry = estimated[node['id']]
        shape = entry.get('shape', entry.get('type', 'rectangle'))
        inflate = {'diamond': 1.4, 'ellipse': 1.2}.get(shape, 1.0)
        sizes[node['id']] = (
            max(160, math.ceil(entry.get('min_width', 120) * inflate + 40)),
            max(88 if shape == 'diamond' else 64, math.ceil(entry.get('min_height', 24) * inflate + 30)),
        )
    return sizes


def expand_flow_grid(output: dict, structure: dict, styling: dict) -> dict:
    structure = unwrap_structure_instantiation(structure)
    inst = output.get('instantiation') if isinstance(output, dict) else None
    if not isinstance(inst, dict) or inst.get('format') != 'flow_grid_v1':
        return output
    if not supports_flow_grid(structure, styling):
        raise ValueError('Flow grid requires an ungrouped flowchart with no standalone annotations.')
    if set(inst) != {'format', 'nodes', 'edges'} or not isinstance(inst['nodes'], dict) or not isinstance(inst['edges'], dict):
        raise ValueError('Flow grid requires exactly format, nodes and edges maps.')
    sizes = flow_grid_sizes(structure, styling)
    if set(inst['nodes']) != set(sizes) or set(inst['edges']) != {edge['id'] for edge in structure.get('edges', [])}:
        raise ValueError('Flow grid must cover every exact node and edge ID once.')
    cells = {}
    for node_id, cell in inst['nodes'].items():
        if (not isinstance(cell, list) or len(cell) != 2
                or any(type(value) is not int or not 0 <= value < len(sizes) for value in cell)):
            raise ValueError('Flow grid cells must be bounded non-negative integer [column,row] pairs.')
        if tuple(cell) in cells.values():
            raise ValueError('Flow grid nodes cannot share a cell.')
        cells[node_id] = tuple(cell)
    widths = {col: max(sizes[key][0] for key, cell in cells.items() if cell[0] == col)
              for col, _ in cells.values()}
    heights = {row: max(sizes[key][1] for key, cell in cells.items() if cell[1] == row)
               for _, row in cells.values()}
    # Empty cells remain explicit routing space, never silently compacted away.
    columns, rows = {}, {}
    x = y = 80
    for col in range(max(widths) + 1):
        width = widths.get(col, 160)
        columns[col] = x + width / 2
        x += width + 120
    for row in range(max(heights) + 1):
        height = heights.get(row, 64)
        rows[row] = y + height / 2
        y += height + 64
    if x - 120 + 80 > CANVAS_DEFAULT_VIEWPORT_WIDTH or y - 64 + 80 > CANVAS_DEFAULT_VIEWPORT_HEIGHT:
        raise ValueError('Flow grid exceeds canvas safety bounds; use a more compact plan or canonical boxes.')
    expanded = deepcopy(inst['edges'])
    for key, (col, row) in cells.items():
        width, height = sizes[key]
        expanded[key] = [columns[col] - width / 2, rows[row] - height / 2, width, height]
    result = deepcopy(output)
    result['instantiation'] = expanded
    return result
