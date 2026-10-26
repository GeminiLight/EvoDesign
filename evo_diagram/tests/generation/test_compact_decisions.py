"""Compact model output must expand without changing semantics or validation."""
from copy import deepcopy

import pytest

from evo_diagram.agentic_system.generation_stage.compact_decisions import (
    expand_layout_output, expand_styling_output, use_compact_decisions,
)
from evo_diagram.agentic_system.generation_stage.layout.layout_agent import LayoutAgent
from evo_diagram.agentic_system.generation_stage.layout.state import WorkflowState as LayoutState
from evo_diagram.agentic_system.generation_stage.styling.styling_agent import StylingAgent
from evo_diagram.agentic_system.generation_stage.styling.state import WorkflowState as StylingState


def structure():
    return {"chart_type": "flowchart", "nodes": [
        {"id": "start", "label": "Start", "class": "terminator"},
        {"id": "check", "label": "Ready?", "class": "decision"},
    ], "groups": [], "edges": [
        {"id": "forward", "source": "start", "target": "check"},
        {"id": "retry", "source": "check", "target": "start", "label": "No"},
    ]}


def style_output():
    return {"specification": {"visual_paradigm": "flowchart"}, "instantiation": {
        "format": "style_templates_v1",
        "styles": {"blue": {"shape": "ellipse", "strokeColor": "#1E40AF",
                            "backgroundColor": "#DBEAFE", "label": {"fontSize": 18, "fontFamily": 2}}},
        "elements": {"start": "blue", "check": {"style": "blue", "shape": "diamond", "label": {"fontSize": 16}},
                     "retry": {"strokeColor": "#7C3AED"},
                     "start:icon": {"type": "icon", "props": {"icon": "notification_important", "color": "#1E40AF"}}},
        "edge_default": {"strokeColor": "#334155"}}}


def styled(icons=True, output=None):
    agent = object.__new__(StylingAgent)
    agent.use_icons, agent._system_prompt = icons, "system"
    agent.invoke_with_history = lambda messages: deepcopy(output or style_output())
    return agent.run(StylingState(structure_instantiation=structure())).styling_instantiation


def layout_output():
    return {"specification": {}, "instantiation": {
        "start": [100, 100, 180, 80], "check": [90, 300, 200, 110],
        "forward": ["bottom", "top"], "retry": ["left", "left", {"routing": "curved"}],
    }}


def laid_out(output=None):
    agent = object.__new__(LayoutAgent)
    agent._system_prompt = "system"
    agent.invoke_with_history = lambda messages: deepcopy(output or layout_output())
    return agent.run(LayoutState(structure_instantiation=structure(), styling_instantiation=styled())).layout_instantiation


def test_templates_preserve_typography_labels_shapes_and_edge_colors():
    result = styled()
    assert result['start']['label'] == {'text': 'Start', 'fontSize': 18, 'fontFamily': 2}
    assert result['check']['label'] == {'text': 'Ready?', 'fontSize': 16, 'fontFamily': 2}
    assert result['check']['shape'] == 'diamond'
    assert result['start']['shape'] == 'ellipse'
    assert result['retry'] == {'strokeColor': '#7C3AED'}
    assert result['forward'] == {'strokeColor': '#334155'}
    assert 'start:icon' in result
    assert 'start:icon' not in styled(False)


def test_compact_layout_preserves_edge_identity_branches_return_ports_and_styles():
    result = laid_out()
    assert result['retry']['start'] == {'elementId': 'check', 'side': 'left'}
    assert result['retry']['end'] == {'elementId': 'start', 'side': 'left'}
    assert result['retry']['routing'] == 'curved'
    assert result['retry']['label']['text'] == 'No'
    assert result['retry']['strokeColor'] == '#7C3AED'
    assert result['start']['x'] == 100
    assert result['check']['w'] == 200
    assert result['start']['label']['fontSize'] == 18


def test_template_and_tuple_expansion_do_not_mutate_inputs_or_share_objects():
    out, graph = style_output(), structure()
    before, graph_before = deepcopy(out), deepcopy(graph)
    expanded = expand_styling_output(out, graph)
    expanded['instantiation']['start']['label']['fontSize'] = 99
    assert out == before and graph == graph_before
    assert expanded['instantiation']['check']['label']['fontSize'] == 16
    out = layout_output()
    before = deepcopy(out)
    expanded = expand_layout_output(out, graph)
    expanded['instantiation']['retry']['start']['elementId'] = 'changed'
    assert out == before and graph == graph_before


@pytest.mark.parametrize('canvas,chart,expected', [
    ('excalidraw', 'flowchart', True), ('tldraw', 'flowchart', False),
    ('excalidraw', 'architecture', False), ('excalidraw', 'sequence_diagram', False),
])
def test_selection_is_bounded_to_excalidraw_flowcharts(canvas, chart, expected):
    assert use_compact_decisions({'instantiation': {'chart_type': chart}}, canvas) is expected


def test_legacy_objects_still_work_with_full_canonical_validation():
    style = expand_styling_output(style_output(), structure())
    assert styled(output=style) == styled()
    layout = expand_layout_output(layout_output(), structure())
    assert laid_out(output=layout) == laid_out()


@pytest.mark.parametrize('mutation,match', [
    (lambda i: i.update(format='unknown'), 'format'),
    (lambda i: i.update(unexpected=True), 'fields'),
    (lambda i: i['elements'].update(start='missing'), 'reference'),
    (lambda i: i['styles']['blue']['label'].update(text='Shared label'), 'text'),
    (lambda i: i['elements'].update(phantom='blue'), 'Unknown styling id'),
    (lambda i: i['elements'].pop('check'), 'Missing styling'),
    (lambda i: i['elements']['check'].update(x=20), 'Layout-owned|layout-owned|geometry'),
    (lambda i: i['edge_default'].update(routing='curved'), 'strokeColor'),
    (lambda i: i.pop('edge_default'), 'Missing styling'),
])
def test_malformed_styles_fail_instead_of_silent_repair(mutation, match):
    out = style_output(); mutation(out['instantiation'])
    with pytest.raises(ValueError, match=match):
        styled(output=out)


@pytest.mark.parametrize('mutation,match', [
    (lambda i: i.pop('retry'), 'Missing layout'),
    (lambda i: i.update(phantom=[0, 0, 20, 20]), 'Unknown layout id'),
    (lambda i: i.update(start=[1, 2, 3]), 'x,y,w,h'),
    (lambda i: i.update(retry=['left']), 'two sides'),
    (lambda i: i.update(retry=['wrong', 'left']), 'side'),
    (lambda i: i.update(retry=['left', 'left', {'start': {'elementId': 'start'}}]), 'options'),
    (lambda i: i.update(retry={'start': {'elementId': 'start', 'side': 'left'},
                              'end': {'elementId': 'check', 'side': 'left'}}), 'source|target|endpoint'),
])
def test_layout_rejects_missing_edges_invalid_geometry_and_reversed_endpoints(mutation, match):
    out = layout_output(); mutation(out['instantiation'])
    with pytest.raises(ValueError, match=match):
        laid_out(output=out)


def test_label_injection_preserves_custom_text_and_partial_font_overrides():
    out = style_output()
    out['instantiation']['elements']['check']['label'] = {'text': 'Approved?', 'fontSize': 20}
    assert styled(output=out)['check']['label'] == {'text': 'Approved?', 'fontSize': 20, 'fontFamily': 2}


def test_groups_and_titles_keep_text_and_native_geometry():
    graph = structure()
    graph['groups'] = [{'id': 'lane', 'label': 'Review Team', 'members': ['start', 'check']}]
    out = style_output()
    out['instantiation']['styles']['group'] = {
        'shape': 'rectangle', 'strokeColor': '#334155', 'backgroundColor': 'transparent'}
    out['instantiation']['styles']['heading'] = {
        'shape': 'text', 'label': {'fontSize': 20, 'strokeColor': '#334155'}}
    out['instantiation']['elements'].update({'lane:background': 'group', 'lane:title': 'heading'})
    agent = object.__new__(StylingAgent)
    agent.use_icons, agent._system_prompt = True, 'system'
    agent.invoke_with_history = lambda messages: out
    styles = agent.run(StylingState(structure_instantiation=graph)).styling_instantiation
    assert styles['lane:title']['label'] == {'text': 'Review Team', 'fontSize': 20, 'strokeColor': '#334155'}
    boxes = layout_output()
    boxes['instantiation'].update({'lane:background': [60, 40, 280, 410], 'lane:title': [80, 50, 200, 30]})
    layout = expand_layout_output(boxes, graph)['instantiation']
    merged = object.__new__(LayoutAgent)._merge_layout_with_styling(layout, styles, structure_instantiation=graph)
    assert merged['lane:background']['backgroundColor'] == 'transparent'
    assert merged['lane:title']['label']['text'] == 'Review Team'
    assert merged['lane:title']['w'] == 200


def test_legacy_node_named_format_does_not_collide_with_protocol_marker():
    out = {'specification': {}, 'instantiation': {'format': {'shape': 'rectangle'}}}
    assert expand_styling_output(out, {'nodes': [{'id': 'format'}]}) == out


def test_wrapped_structure_restores_exact_labels_without_dropping_typography():
    agent = object.__new__(StylingAgent)
    agent.use_icons, agent._system_prompt = True, 'system'
    agent.invoke_with_history = lambda messages: style_output()
    state = agent.run(StylingState(structure_instantiation={'instantiation': structure()}))
    assert state.styling_instantiation == styled()


@pytest.mark.parametrize('label', [None, 'bad', 8, []])
def test_template_label_requires_an_object(label):
    out = style_output(); out['instantiation']['styles']['blue']['label'] = label
    with pytest.raises(ValueError, match='label must be an object'):
        styled(output=out)


def test_compact_branch_label_fallback_preserves_requested_typography():
    out = layout_output()
    out['instantiation']['retry'][2]['label'] = {'fontSize': 20, 'strokeColor': '#1E40AF'}
    assert laid_out(output=out)['retry']['label'] == {
        'text': 'No', 'fontSize': 20, 'strokeColor': '#1E40AF'}
