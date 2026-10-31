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


def test_flowchart_keeps_shapes_and_takes_the_shared_treatment():
    themed = apply_design_theme(scene(), structure(), STYLE)
    id_map = themed['_meta']['id_map']
    elements = {e['id']: e for e in themed['elements']}
    assert [elements[id_map[n['id']]]['type'] for n in NODES] == ['ellipse', 'rectangle', 'diamond']
    host = elements[id_map['check']]
    assert host['backgroundColor'] == '#EBF5F4' and host['strokeColor'] == '#367E8A'
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
    link = apply_design_theme(scene(), structure('flowchart'), STYLE)
    area = apply_design_theme(scene(), structure('funnel'), STYLE)
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
