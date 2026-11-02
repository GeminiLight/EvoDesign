from evo_diagram.agentic_system.render_engine.excalidraw.converter import InstantiationToExcalidrawConverter
from evo_diagram.agentic_system.render_engine.excalidraw.design_theme import apply_design_theme


NODES = [{'id': 'start', 'label': '提交退款申请', 'class': 'start'},
         {'id': 'check', 'label': '校验订单状态', 'class': 'process'},
         {'id': 'shipped', 'label': '订单是否已发货?', 'class': 'decision'}]
SHAPES = {'start': 'ellipse', 'check': 'rectangle', 'shipped': 'diamond'}
STYLE = {n['id']: {'backgroundColor': '#D2E9E7', 'strokeColor': '#367E8A'} for n in NODES}


def scene():
    layout = {n['id']: {'shape': SHAPES[n['id']], 'label': {'text': n['label']}, 'x': 0, 'y': i * 120,
                        'w': 160, 'h': 60, **STYLE[n['id']]} for i, n in enumerate(NODES)}
    result = InstantiationToExcalidrawConverter(layout).convert()
    result['elements'].append({'id': 'arrow-1', 'type': 'arrow', 'x': 80, 'y': 60, 'points': [[0, 0], [0, 60]],
                               'strokeColor': '#1e1e1e', 'endArrowhead': 'arrow', 'boundElements': [],
                               'meta': {'semantic_edge_id': 'edge:start2check', 'source': 'start', 'target': 'check'}})
    return result


def structure(chart_type='flowchart'):
    return {'chart_type': chart_type, 'nodes': NODES,
            'edges': [{'id': 'edge:start2check', 'source': 'start', 'target': 'check'}]}


def test_architecture_and_other_types_are_left_alone():
    base = scene()
    assert apply_design_theme(base, structure('architecture'), STYLE) is base
    assert apply_design_theme(base, structure('venn'), STYLE) is base


def test_explicit_dna_and_native_locks_bypass_automatic_visual_treatment():
    import json
    from evo_diagram.agentic_system.render_engine.excalidraw.architecture_design_system import apply_architecture_design_system
    from evo_diagram.tests.render_engine.test_architecture_design_system import manifest, structure as arch_structure
    for apply, base, data in ((apply_design_theme, scene(), structure()),
                              (apply_architecture_design_system, manifest(), arch_structure())):
        assert apply(base, data, design_constraints=json.dumps({'user_design_preferences': 'Use exactly #ff0000'})) is base
        base['elements'][0]['locked'] = True
        assert apply(base, data) is base


def test_mindmap_routing_keeps_native_binding_and_repositions_edge_labels():
    base = scene()
    arrow = base['elements'][-1]
    arrow['width'], arrow['height'] = 0, 60
    base['elements'].append({'id': 'edge-label', 'type': 'text', 'containerId': arrow['id'],
                             'x': 1000, 'y': 1000, 'width': 40, 'height': 20, 'text': 'belongs'})
    themed = apply_design_theme(base, structure('mindmap'))
    by_id = {e['id']: e for e in themed['elements']}
    assert by_id[arrow['id']]['startBinding']['elementId'] == themed['_meta']['id_map']['start']
    assert by_id[arrow['id']]['endBinding']['elementId'] == themed['_meta']['id_map']['check']
    assert by_id['edge-label']['x'] != 1000


def test_flowchart_keeps_shapes_and_takes_the_shared_treatment():
    themed = apply_design_theme(scene(), structure(), STYLE)
    id_map = themed['_meta']['id_map']
    elements = {e['id']: e for e in themed['elements']}
    assert [elements[id_map[n['id']]]['type'] for n in NODES] == ['ellipse', 'rectangle', 'diamond']
    host = elements[id_map['check']]
    assert host['backgroundColor'] == '#D2E9E7' and host['strokeColor'] == '#367E8A'
    assert host['strokeWidth'] == 1.5 and host['roughness'] == 0
    labels = [e for e in themed['elements'] if e['type'] == 'text' and e.get('containerId') == host['id']]
    assert labels and all(t['strokeColor'] == '#1F2937' for t in labels)
    arrow = elements['arrow-1']
    assert arrow['endArrowhead'] == 'triangle' and arrow['strokeColor'] == '#367E8A'


def test_undirected_and_uml_heads_keep_their_meaning():
    base = scene()
    base['elements'][-1].update({'endArrowhead': None})
    base['elements'].append({'id': 'arrow-2', 'type': 'arrow', 'x': 0, 'y': 0, 'points': [[0, 0], [0, 60]],
                             'endArrowhead': 'triangle_outline', 'startArrowhead': 'diamond',
                             'boundElements': [], 'meta': {'source': 'check', 'target': 'shipped'}})
    elements = {e['id']: e for e in apply_design_theme(base, structure('class_diagram'), STYLE)['elements']}
    assert elements['arrow-1']['endArrowhead'] is None
    assert (elements['arrow-2']['endArrowhead'], elements['arrow-2']['startArrowhead']) == ('triangle_outline', 'diamond')


def test_area_types_keep_more_of_their_colour():
    link = apply_design_theme(scene(), structure('flowchart'))
    area = apply_design_theme(scene(), structure('funnel'))
    host = lambda s: next(e for e in s['elements'] if e['id'] == s['_meta']['id_map']['check'])
    assert host(area)['backgroundColor'] < host(link)['backgroundColor']


def test_er_links_are_drawn_without_direction():
    elements = apply_design_theme(scene(), structure('er_diagram'), STYLE)['elements']
    assert all(e['endArrowhead'] is None and e['startArrowhead'] is None for e in elements if e['type'] == 'arrow')


def test_flowchart_emphasis_and_no_title():
    nodes = [dict(n) for n in NODES]
    nodes[2]['emphasis'] = 'primary'
    data = {**structure(), 'nodes': nodes, 'title': '退款流程'}
    themed = apply_design_theme(scene(), data, STYLE)
    elements = {e['id']: e for e in themed['elements']}
    id_map = themed['_meta']['id_map']
    assert elements[id_map['shipped']]['strokeWidth'] > elements[id_map['check']]['strokeWidth']
    assert not any(e.get('text') == '退款流程' for e in themed['elements'])


def test_flowchart_main_path_follows_the_positive_branch():
    from evo_diagram.agentic_system.render_engine.excalidraw.design_theme import _main_path
    nodes = [{'id': i} for i in ('s', 'd', 'ok', 'no', 'end')]
    nodes[0]['class'] = 'start'
    edges = [{'id': 'a', 'source': 's', 'target': 'd'},
             {'id': 'b', 'source': 'd', 'target': 'no', 'label': '否'},
             {'id': 'c', 'source': 'd', 'target': 'ok', 'label': '是'},
             {'id': 'e', 'source': 'ok', 'target': 'end'},
             {'id': 'f', 'source': 'no', 'target': 'end'},
             {'id': 'g', 'source': 'end', 'target': 's'}]
    assert _main_path(nodes, edges) == {'a', 'c', 'e'}


def test_off_path_flowchart_links_step_back():
    data = {**structure(), 'edges': structure()['edges'] + [
        {'id': 'edge:check2shipped', 'source': 'check', 'target': 'shipped'}]}
    themed = apply_design_theme(scene(), data, STYLE)
    arrow = {e['id']: e for e in themed['elements']}['arrow-1']
    assert arrow['strokeWidth'] > 1.5 and arrow['opacity'] == 100


def test_mindmap_links_are_straight_and_headless_from_facing_sides():
    from evo_diagram.agentic_system.render_engine.excalidraw.design_theme import _branch_points
    parent = {'x': 0, 'y': 0, 'width': 100, 'height': 40}
    assert _branch_points(parent, {'x': 200, 'y': 10, 'width': 80, 'height': 40}) == [(100, 20), (200, 30)]
    # A child above its parent and barely beside it is reached from the top edge.
    assert _branch_points(parent, {'x': -90, 'y': -120, 'width': 80, 'height': 40}) == [(50, 0), (-50, -80)]
    data = {**structure('mindmap'), 'nodes': [dict(n) for n in NODES]}
    themed = apply_design_theme(scene(), data, STYLE)
    arrow = {e['id']: e for e in themed['elements']}['arrow-1']
    assert arrow['endArrowhead'] is None and len(arrow['points']) == 2


def test_quadrant_axis_names_are_plain_captions():
    nodes = [dict(n) for n in NODES]
    nodes[1]['class'] = 'axis'
    themed = apply_design_theme(scene(), {**structure('quadrant'), 'nodes': nodes, 'edges': []}, STYLE)
    elements = {e['id']: e for e in themed['elements']}
    id_map = themed['_meta']['id_map']
    axis, item = elements[id_map['check']], elements[id_map['shipped']]
    assert axis['strokeColor'] == axis['backgroundColor'] == 'transparent'
    assert item['strokeColor'] != 'transparent'


def test_cycle_steps_are_linked_straight_and_keep_their_arrowheads():
    themed = apply_design_theme(scene(), {**structure('cycle'), 'nodes': [dict(n) for n in NODES]}, STYLE)
    arrow = {e['id']: e for e in themed['elements']}['arrow-1']
    assert arrow['endArrowhead'] == 'triangle' and len(arrow['points']) == 2 and arrow['elbowed'] is False


def test_journey_feelings_form_one_headless_line():
    base = scene()
    arrow = base['elements'][-1]
    arrow.update(points=[[0, 0], [0, 30], [40, 30], [40, 60]], elbowed=True, endArrowhead='dot')
    themed = apply_design_theme(base, {**structure('user_journey'), 'nodes': [dict(n) for n in NODES]}, STYLE)
    arrow = {e['id']: e for e in themed['elements']}['arrow-1']
    assert arrow['endArrowhead'] is None and len(arrow['points']) == 2 and arrow['elbowed'] is False


def test_cycle_links_keep_a_start_head_and_fall_back_to_bindings():
    base = scene()
    arrow = base['elements'][-1]
    id_map = base['_meta']['id_map']
    arrow.update(meta={}, startArrowhead='arrow', elbowed=True, points=[[0, 0], [0, 30], [0, 60]],
                 startBinding={'elementId': id_map['start']}, endBinding={'elementId': id_map['check']})
    themed = apply_design_theme(base, {**structure('cycle'), 'nodes': [dict(n) for n in NODES]}, STYLE)
    arrow = {e['id']: e for e in themed['elements']}['arrow-1']
    assert arrow['startArrowhead'] and arrow['endArrowhead']
    assert len(arrow['points']) == 2 and arrow['elbowed'] is False
