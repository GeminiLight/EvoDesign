"""Discrete flow decisions preserve semantic and editor geometry contracts."""
from copy import deepcopy

import pytest

from evo_diagram.agentic_system.generation_stage.compact_decisions import expand_layout_output
from evo_diagram.agentic_system.generation_stage.layout.flow_grid import expand_flow_grid, supports_flow_grid
from evo_diagram.agentic_system.generation_stage.layout.layout_agent import LayoutAgent


def fixture():
    graph = {'chart_type': 'flowchart', 'nodes': [
        {'id': 'a', 'label': 'Receive a long alert'}, {'id': 'b', 'label': 'Ready?'},
        {'id': 'c', 'label': 'Retry'}], 'groups': [], 'edges': [
        {'id': 'ab', 'source': 'a', 'target': 'b'},
        {'id': 'bc', 'source': 'b', 'target': 'c', 'label': 'No'},
        {'id': 'ca', 'source': 'c', 'target': 'a'}]}
    style = {node['id']: {'shape': 'diamond' if node['id'] == 'b' else 'rectangle',
                          'label': {'text': node['label'], 'fontSize': 20, 'fontFamily': 2},
                          'strokeColor': '#123456'} for node in graph['nodes']}
    style['a:icon'] = {'type': 'icon', 'props': {'icon': 'notifications', 'color': '#123456'}}
    output = {'specification': {}, 'instantiation': {'format': 'flow_grid_v1',
              'nodes': {'a': [1, 0], 'b': [1, 1], 'c': [0, 1]},
              'edges': {'ab': ['bottom', 'top'], 'bc': ['left', 'right'], 'ca': ['left', 'left']}}}
    return graph, style, output


def test_grid_preserves_facts_styles_icons_and_nonoverlapping_measured_boxes():
    graph, style, output = fixture()
    before = deepcopy((graph, style, output))
    expanded = expand_layout_output(expand_flow_grid(output, graph, style), graph)['instantiation']
    result = LayoutAgent._merge_layout_with_styling(object.__new__(LayoutAgent), expanded, style,
                                                    structure_instantiation=graph)
    assert (graph, style, output) == before
    assert result['ab']['start'] == {'elementId': 'a', 'side': 'bottom'}
    assert result['bc']['label']['text'] == 'No'
    assert result['a:icon'] == style['a:icon']
    assert result['a']['strokeColor'] == '#123456'
    a, b, c = (result[key] for key in 'abc')
    assert a['x'] + a['w']/2 == b['x'] + b['w']/2
    assert b['y'] + b['h']/2 == c['y'] + c['h']/2
    assert a['y'] + a['h'] + 64 <= b['y']
    assert c['x'] + c['w'] + 120 <= b['x']
    assert a['w'] >= len(graph['nodes'][0]['label'])*20*0.6 + 40 + 20


@pytest.mark.parametrize('bad', [[0, 1], [-1, 0], [True, 0], [1.5, 0], [99, 0], [0], '0,0'])
def test_grid_rejects_collisions_and_invalid_cells(bad):
    graph, style, output = fixture()
    output['instantiation']['nodes']['a'] = bad
    with pytest.raises(ValueError, match='cell'):
        expand_flow_grid(output, graph, style)


@pytest.mark.parametrize('key', ['a', 'unknown'])
def test_grid_rejects_missing_and_invented_nodes(key):
    graph, style, output = fixture()
    if key == 'a':
        del output['instantiation']['nodes'][key]
    else:
        output['instantiation']['nodes'][key] = [2, 0]
    with pytest.raises(ValueError, match='exact node and edge'):
        expand_flow_grid(output, graph, style)


def test_grid_does_not_interpret_locks_groups_or_arbitrary_runtime_text():
    graph, style, _ = fixture()
    assert supports_flow_grid(graph, style)
    assert supports_flow_grid(graph, style, '=== RUNTIME DIRECTIVES (HIGHEST PRIORITY) ===\n{"locked_nodes": [], "current_schema": null}\n\n')
    assert not supports_flow_grid(graph, style, 'preserve previous coordinates')
    assert not supports_flow_grid(graph, style, 'preserve previous coordinates\n{"locked_nodes": [], "current_schema": null}')
    assert not supports_flow_grid(graph, style, 'header\n{"locked_nodes": ["a"], "current_schema": null}')
    assert not supports_flow_grid({**graph, 'groups': [{'id': 'g', 'members': ['a']}]}, style)
    assert not supports_flow_grid(graph, {**style, 'title': {'text': 'New title'}})
    assert not supports_flow_grid({**graph, 'chart_type': 'architecture'}, style)


def test_canonical_geometry_passes_through_unchanged():
    graph, style, _ = fixture()
    output = {'specification': {}, 'instantiation': {'a': [100, 100, 200, 100]}}
    assert expand_flow_grid(output, graph, style) is output


@pytest.mark.parametrize('change', ['missing_edge', 'extra_field', 'oversized_label'])
def test_grid_rejects_incomplete_or_unsafe_plans(change):
    graph, style, output = fixture()
    if change == 'missing_edge':
        del output['instantiation']['edges']['ca']
    elif change == 'extra_field':
        output['instantiation']['title'] = 'unrequested'
    else:
        style['a']['label']['text'] = 'X' * 1000
    with pytest.raises(ValueError):
        expand_flow_grid(output, graph, style)


def test_grid_preserves_explicit_empty_routing_cells():
    graph, style, output = fixture()
    output['instantiation']['nodes'] = {'a': [2, 0], 'b': [2, 2], 'c': [0, 2]}
    expanded = expand_flow_grid(output, graph, style)['instantiation']
    a, b, c = (expanded[key] for key in 'abc')
    assert b[0] - (c[0] + c[2]) >= 120 + 160 + 120
    assert b[1] - (a[1] + a[3]) >= 64 + 64 + 64
