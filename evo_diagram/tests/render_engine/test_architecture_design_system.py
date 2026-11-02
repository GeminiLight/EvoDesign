import base64
import copy

from evo_diagram.agentic_system.common.node_icons import CARD_KEY, ICON_KEY, sync_node_icons
from evo_diagram.agentic_system.render_engine.excalidraw.architecture_design_system import (
    apply_architecture_design_system,
)
from evo_diagram.agentic_system.render_engine.excalidraw.converter import InstantiationToExcalidrawConverter
from evo_diagram.agentic_system.render_engine.shared.render_audit import audit_excalidraw_manifest


NODES = [
    {'id': 'web', 'label': 'Web', 'sublabel': '浏览器 / H5', 'role': 'client'},
    {'id': 'app', 'label': 'App', 'sublabel': 'iOS / Android', 'role': 'client'},
    {'id': 'gw', 'label': 'API 网关', 'sublabel': '路由 / 认证 / 限流', 'role': 'api'},
    {'id': 'users', 'label': '用户服务', 'sublabel': '用户管理', 'role': 'service'},
    {'id': 'orders', 'label': '订单服务', 'sublabel': '订单创建', 'role': 'service'},
    {'id': 'db', 'label': 'MySQL', 'sublabel': '分库分表', 'role': 'database'},
    {'id': 'cache', 'label': 'Redis', 'sublabel': '热点缓存'},
]
EDGES = [('web', 'gw'), ('app', 'gw'), ('gw', 'users'), ('gw', 'orders'),
         ('users', 'db'), ('orders', 'db'), ('users', 'cache'), ('orders', 'cache')]


def structure(chart_type='architecture'):
    return {
        'chart_type': chart_type,
        'nodes': copy.deepcopy(NODES),
        'edges': [{'id': f'edge:{s}2{t}', 'source': s, 'target': t} for s, t in EDGES],
        'groups': [],
    }


def manifest():
    layout = {}
    for index, node in enumerate(NODES):
        layout[node['id']] = {'shape': 'ellipse' if node['id'] == 'db' else 'rectangle',
                              'label': {'text': node['label']}, 'x': 100 + index * 50, 'y': 100,
                              'w': 160, 'h': 60, 'strokeColor': '#333333', 'backgroundColor': '#EEEEEE'}
        layout[node['id'] + ':icon'] = {'shape': 'icon', 'props': {'icon': 'outline_monitor'},
                                      'x': 100, 'y': 100, 'w': 26, 'h': 26}
    layout['data_layer:background'] = {'shape': 'rectangle', 'x': 0, 'y': 0, 'w': 900, 'h': 400}
    layout['data_layer:title'] = {'shape': 'text', 'label': {'text': 'Data'}, 'x': 10, 'y': 10, 'w': 80, 'h': 20}
    scene = InstantiationToExcalidrawConverter(layout).convert()
    for source, target in EDGES:
        scene['elements'].append({'id': f'arrow-{source}-{target}', 'type': 'arrow', 'x': 0, 'y': 0,
                                  'points': [[0, 0], [10, 10]], 'boundElements': [],
                                  'meta': {'semantic_edge_id': f'edge:{source}2{target}'}})
    return scene


def cards(scene):
    id_map = scene['_meta']['id_map']
    elements = {e['id']: e for e in scene['elements']}
    return {node['id']: elements[id_map[node['id']]] for node in NODES}


def arrow_paths(scene):
    return [[(a['x'] + px, a['y'] + py) for px, py in a['points']]
            for a in scene['elements'] if a['type'] == 'arrow']


def test_non_architecture_scene_is_untouched():
    scene = manifest()
    assert apply_architecture_design_system(scene, structure('flowchart')) is scene


def test_semantic_boundaries_labels_and_feedback_loops_use_the_complete_native_scene():
    for addition in ('group', 'label', 'loop'):
        data, base = structure(), manifest()
        if addition == 'group':
            data['groups'] = [{'id': 'data_layer', 'label': 'EU private data', 'members': ['db', 'cache']}]
        elif addition == 'label':
            data['edges'][0]['label'] = 'HTTPS request'
        else:
            data['edges'].append({'id': 'retry', 'source': 'gw', 'target': 'gw'})
        assert apply_architecture_design_system(base, data) is base


def test_incomplete_many_to_many_relations_do_not_get_joined_into_a_complete_bus():
    base, data = manifest(), structure()
    data['edges'] = [e for e in data['edges'] if (e['source'], e['target']) not in
                     {('users', 'cache'), ('orders', 'db')}]
    assert apply_architecture_design_system(base, data) is base


def test_icons_off_and_intentional_partial_coverage_are_preserved():
    base = manifest()
    keep_host = base['_meta']['id_map']['web']
    base['elements'] = [e for e in base['elements'] if e['type'] != 'image' or
                        e['customData'][ICON_KEY]['hostId'] == keep_host]
    scene = apply_architecture_design_system(base, structure())
    assert len([e for e in scene['elements'] if e['type'] == 'image']) == 1
    base['elements'] = [e for e in base['elements'] if e['type'] != 'image']
    assert not any(e['type'] == 'image' for e in apply_architecture_design_system(base, structure())['elements'])


def test_refiner_geometry_edits_keep_card_parts_together_and_sync_is_idempotent():
    from evo_diagram.agentic_system.common.node_icons import sync_node_icons
    scene = apply_architecture_design_system(manifest(), structure())
    host = cards(scene)['web']
    before = {e['id']: copy.deepcopy(e) for e in scene['elements']}
    host['x'] += 20
    host['y'] += 30
    sync_node_icons(scene, host['id'])
    by_id = {e['id']: e for e in scene['elements']}
    for key in ('titleId', 'sublabelId', 'iconId'):
        eid = host['customData'][CARD_KEY][key]
        assert by_id[eid]['x'] == before[eid]['x']+20
        assert by_id[eid]['y'] == before[eid]['y']+30
    stable = copy.deepcopy(scene)
    sync_node_icons(scene, host['id'])
    assert scene == stable


def test_long_cjk_labels_wrap_inside_cards_without_truncating_source_text():
    data = structure()
    data['nodes'][0]['label'] = '这是一个必须完整保留的很长的中文架构节点标题用于测试自动换行和边界'
    data['nodes'][0]['sublabel'] = '详细说明也需要完整保留且不能越过卡片的右边界'
    data['title'] = 'An architecture title that is deliberately longer than forty characters'
    scene = apply_architecture_design_system(manifest(), data)
    host = cards(scene)['web']
    text = [e for e in scene['elements'] if e['type'] == 'text' and e.get('groupIds') == host['groupIds']]
    assert {t['originalText'] for t in text} == {data['nodes'][0]['label'], data['nodes'][0]['sublabel']}
    assert all(t['x'] >= host['x'] and t['x']+t['width'] <= host['x']+host['width']+0.01 for t in text)
    assert all(t['y'] >= host['y'] and t['y']+t['height'] <= host['y']+host['height']+0.01 for t in text)
    assert any(e.get('text') == data['title'] for e in scene['elements'])


def test_cards_share_one_size_and_carry_icon_title_and_sublabel():
    scene = apply_architecture_design_system(manifest(), structure())
    hosts = cards(scene)
    assert len({(h['width'], h['height']) for h in hosts.values()}) == 1
    for node in NODES:
        host = hosts[node['id']]
        assert host['type'] == 'rectangle' and host['customData'][CARD_KEY]
        group = host['groupIds']
        members = [e for e in scene['elements'] if e.get('groupIds') == group and e is not host]
        icons = [e for e in members if e['type'] == 'image']
        texts = sorted((e for e in members if e['type'] == 'text'), key=lambda e: e['y'])
        assert len(icons) == 1 and icons[0]['fileId'] in scene['files']
        assert icons[0]['customData'][ICON_KEY]['name'].startswith('outline_')
        assert [t['text'] for t in texts] == [node['label'], node['sublabel']]
        assert texts[0]['fontSize'] > texts[1]['fontSize']
        assert all(t['x'] >= icons[0]['x'] + icons[0]['width'] for t in texts)


def test_roles_place_tiers_left_to_right_with_storage_below():
    hosts = cards(apply_architecture_design_system(manifest(), structure()))
    assert hosts['web']['x'] == hosts['app']['x'] < hosts['gw']['x'] < hosts['users']['x']
    assert hosts['users']['x'] == hosts['orders']['x']
    main_bottom = max(h['y'] + h['height'] for k, h in hosts.items() if k not in {'db', 'cache'})
    assert hosts['db']['y'] == hosts['cache']['y'] > main_bottom


def test_orphaned_backgrounds_are_replaced_by_tier_decorations():
    scene = apply_architecture_design_system(manifest(), structure())
    texts = [e['text'] for e in scene['elements'] if e['type'] == 'text']
    assert 'Data' not in texts
    assert 'data_layer:background' not in scene['_meta']['id_map']


def test_connectors_are_orthogonal_and_avoid_unrelated_cards():
    scene = apply_architecture_design_system(manifest(), structure())
    boxes = [(h['x'], h['y'], h['x'] + h['width'], h['y'] + h['height']) for h in cards(scene).values()]
    paths = arrow_paths(scene)
    assert len(paths) == len(EDGES)
    for path in paths:
        for (x1, y1), (x2, y2) in zip(path, path[1:]):
            assert x1 == x2 or y1 == y2
            for left, top, right, bottom in boxes:
                inside = (min(x1, x2) < right - 1 and max(x1, x2) > left + 1
                          and min(y1, y2) < bottom - 1 and max(y1, y2) > top + 1)
                assert not inside


def test_bidirectional_pair_becomes_one_double_headed_connector():
    data = structure()
    data['edges'] = [e for e in data['edges'] if e['source'] == 'web']
    data['edges'].append({'id': 'edge:gw2web', 'source': 'gw', 'target': 'web'})
    scene = apply_architecture_design_system(manifest(), data)
    arrows = [a for a in scene['elements'] if a['type'] == 'arrow']
    pair = [a for a in arrows if {a['meta']['source'], a['meta']['target']} == {'web', 'gw'}]
    assert len(pair) == 1 and pair[0]['startArrowhead'] and pair[0]['endArrowhead']


def test_merged_duplicate_and_reverse_edges_still_count_as_rendered():
    data = structure()
    data['edges'] = [e for e in data['edges'] if e['source'] == 'web']
    data['edges'] += [{'id': 'edge:gw2web', 'source': 'gw', 'target': 'web'},
                      {'id': 'edge:web2gw_1', 'source': 'web', 'target': 'gw'}]
    scene = apply_architecture_design_system(manifest(), data)
    report = audit_excalidraw_manifest(scene, data)
    assert not [w for w in report.warnings if 'Missing Structure edge ids' in w]


def test_icon_sync_leaves_design_system_cards_alone():
    scene = apply_architecture_design_system(manifest(), structure())
    before = copy.deepcopy(scene['elements'])
    sync_node_icons(scene)
    assert scene['elements'] == before


def test_layout_agent_tier_plan_is_executed_in_order():
    plan = {'tier_plan': {'columns': [['app', 'web'], ['gw'], ['orders', 'users']],
                          'bottom_row': ['cache', 'db']}}
    scene = apply_architecture_design_system(manifest(), structure(), layout_specification=plan)
    hosts = cards(scene)
    assert hosts['app']['y'] < hosts['web']['y'] and hosts['app']['x'] == hosts['web']['x']
    assert hosts['orders']['y'] < hosts['users']['y']
    assert hosts['cache']['x'] < hosts['db']['x']
    assert scene['_meta']['architecture_design_system']['tier_plan_source'] == 'layout_agent'


def test_incomplete_tier_plan_falls_back_to_roles():
    plan = {'tier_plan': {'columns': [['web'], ['gw']], 'bottom_row': ['db']}}
    scene = apply_architecture_design_system(manifest(), structure(), layout_specification=plan)
    assert scene['_meta']['architecture_design_system']['tier_plan_source'] == 'fallback'
    hosts = cards(scene)
    assert hosts['web']['x'] < hosts['gw']['x'] < hosts['users']['x']


def test_card_colours_come_from_the_style_agent_family():
    styling = {node['id']: {'backgroundColor': '#D8E6D1', 'strokeColor': '#56765A'} for node in NODES}
    scene = apply_architecture_design_system(manifest(), structure(), layout_instantiation=styling)
    host = cards(scene)['users']
    assert host['backgroundColor'] == '#D8E6D1' and host['strokeColor'] == '#56765A'
    icon = next(e for e in scene['elements'] if e['type'] == 'image' and e['groupIds'] == host['groupIds'])
    svg = base64.b64decode(scene['files'][icon['fileId']]['dataURL'].split(',')[1]).decode()
    assert '#56765A' in svg
    arrows = [a for a in scene['elements'] if a['type'] == 'arrow' and a['meta']['source'] == 'users']
    assert arrows and all(a['strokeColor'] == '#56765A' for a in arrows)
    assert scene['_meta']['architecture_design_system']['colour_source'] == 'style_agent'


def test_plan_read_as_rows_is_rejected():
    plan = {'pattern_specific_layout_blueprint': {'tier_plan': {
        'columns': [['web', 'gw', 'users'], ['app', 'orders']], 'bottom_row': ['db', 'cache']}}}
    scene = apply_architecture_design_system(manifest(), structure(), layout_specification=plan)
    assert scene['_meta']['architecture_design_system']['tier_plan_source'] == 'fallback'


def test_plan_nested_in_layout_blueprint_is_accepted():
    plan = {'pattern_specific_layout_blueprint': {'tier_plan': {
        'columns': [['web', 'app'], ['gw'], ['users', 'orders']], 'bottom_row': ['db', 'cache']}}}
    scene = apply_architecture_design_system(manifest(), structure(), layout_specification=plan)
    assert scene['_meta']['architecture_design_system']['tier_plan_source'] == 'layout_agent'


def test_bottom_chain_retains_native_routing_when_a_shared_bus_would_add_relations():
    nodes = [{'id': 'gw', 'label': 'Gateway', 'sublabel': 'entry', 'role': 'gateway'},
             {'id': 'svc', 'label': 'Engine', 'sublabel': 'decide', 'role': 'service'},
             {'id': 'db', 'label': 'MySQL', 'sublabel': 'rules', 'role': 'database'},
             {'id': 'cache', 'label': 'Redis', 'sublabel': 'features', 'role': 'cache'},
             {'id': 'mq', 'label': 'Kafka', 'sublabel': 'results', 'role': 'queue'},
             {'id': 'dw', 'label': 'Hive', 'sublabel': 'warehouse', 'role': 'database'},
             {'id': 'job', 'label': 'Spark', 'sublabel': 'reports', 'role': 'database'},
             {'id': 'mon', 'label': 'Prometheus', 'sublabel': 'metrics', 'role': 'observability'}]
    pairs = [('gw', 'svc'), ('svc', 'db'), ('svc', 'cache'), ('svc', 'mq'), ('mq', 'dw'),
             ('dw', 'job'), ('svc', 'mon')]
    layout = {n['id']: {'shape': 'rectangle', 'label': {'text': n['label']}, 'x': 0, 'y': 0, 'w': 100, 'h': 50}
              for n in nodes}
    scene = InstantiationToExcalidrawConverter(layout).convert()
    data = {'chart_type': 'architecture', 'nodes': nodes, 'groups': [],
            'edges': [{'id': f'edge:{s}2{t}', 'source': s, 'target': t} for s, t in pairs]}
    assert apply_architecture_design_system(scene, data) is scene


def test_plan_flowing_right_to_left_is_mirrored():
    plan = {'tier_plan': {'columns': [['users', 'orders'], ['gw'], ['web', 'app']],
                          'bottom_row': ['db', 'cache']}}
    hosts = cards(apply_architecture_design_system(manifest(), structure(), layout_specification=plan))
    assert hosts['web']['x'] < hosts['gw']['x'] < hosts['users']['x']


def test_pipeline_stacked_in_one_column_is_laid_out_left_to_right():
    nodes = [{'id': f's{i}', 'label': f'Stage {i}', 'sublabel': 'step', 'role': 'service'} for i in range(6)]
    nodes.insert(0, {'id': 'in', 'label': 'Input', 'sublabel': 'source', 'role': 'client'})
    pairs = [('in', 's0')] + [(f's{i}', f's{i + 1}') for i in range(5)]
    layout = {n['id']: {'shape': 'rectangle', 'label': {'text': n['label']}, 'x': 0, 'y': 0, 'w': 100, 'h': 50}
              for n in nodes}
    scene = InstantiationToExcalidrawConverter(layout).convert()
    data = {'chart_type': 'architecture', 'nodes': nodes, 'groups': [],
            'edges': [{'id': f'edge:{s}2{t}', 'source': s, 'target': t} for s, t in pairs]}
    plan = {'tier_plan': {'columns': [['in'], [f's{i}' for i in range(6)]], 'bottom_row': []}}
    scene = apply_architecture_design_system(scene, data, layout_specification=plan)
    elements = {e['id']: e for e in scene['elements']}
    xs = [elements[scene['_meta']['id_map'][f's{i}']]['x'] for i in range(6)]
    assert xs == sorted(xs) and len(set(xs)) == 6


def test_output_planned_before_its_sources_moves_to_the_end():
    plan = {'tier_plan': {'columns': [['web', 'app', 'users'], ['gw'], ['orders']],
                          'bottom_row': ['db', 'cache']}}
    data = structure()
    next(n for n in data['nodes'] if n['id'] == 'users')['role'] = 'client'  # e.g. a report viewer
    data['edges'] = [{'id': f'edge:{s}2{t}', 'source': s, 'target': t}
                     for s, t in [('web', 'gw'), ('app', 'gw'), ('gw', 'orders'), ('orders', 'users'),
                                  ('orders', 'db'), ('orders', 'cache')]]
    hosts = cards(apply_architecture_design_system(manifest(), data, layout_specification=plan))
    assert hosts['users']['x'] > hosts['orders']['x'] > hosts['gw']['x'] > hosts['web']['x']


def _scene(nodes, pairs, plan):
    layout = {n['id']: {'shape': 'rectangle', 'label': {'text': n['label']}, 'x': 0, 'y': 0, 'w': 100, 'h': 50}
              for n in nodes}
    scene = InstantiationToExcalidrawConverter(layout).convert()
    data = {'chart_type': 'architecture', 'nodes': nodes, 'groups': [],
            'edges': [{'id': f'edge:{s}2{t}', 'source': s, 'target': t} for s, t in pairs]}
    return apply_architecture_design_system(scene, data, layout_specification={'tier_plan': plan})


def _trunk_xs(scene, sources):
    xs = set()
    for arrow in scene['elements']:
        if arrow['type'] == 'arrow' and arrow['meta']['source'] in sources:
            points = [(arrow['x'] + px, arrow['y'] + py) for px, py in arrow['points']]
            xs |= {p[0] for p, q in zip(points, points[1:]) if p[0] == q[0]}
    return xs


def test_fan_out_keeps_one_trunk_with_a_junction_dot():
    nodes = [{'id': i, 'label': i.upper(), 'sublabel': 'x', 'role': 'service'} for i in ('a', 'c', 'd', 'e')]
    scene = _scene(nodes, [('a', 'c'), ('a', 'd'), ('a', 'e')], {'columns': [['a'], ['c', 'd', 'e']], 'bottom_row': []})
    assert len(_trunk_xs(scene, {'a'})) == 1
    dots = [e for e in scene['elements'] if (e.get('customData') or {}).get('evoDesignJunction')]
    assert dots and all(e['width'] < 10 for e in dots)
    again = apply_architecture_design_system(scene, {'chart_type': 'architecture', 'nodes': nodes, 'groups': [],
        'edges': [{'id': f'edge:{s}2{t}', 'source': s, 'target': t} for s, t in [('a', 'c'), ('a', 'd'), ('a', 'e')]]})
    assert len([e for e in again['elements'] if (e.get('customData') or {}).get('evoDesignJunction')]) == len(dots)


def test_junction_dots_are_not_reported_as_nodes_by_verification():
    from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
        check_edge_node_intersections, check_node_overlap)
    scene = apply_architecture_design_system(manifest(), structure())
    assert any((e.get('customData') or {}).get('evoDesignJunction') for e in scene['elements'])
    assert check_edge_node_intersections(scene) == [] and check_node_overlap(scene) == []


def _decorations(scene, kind):
    return [e for e in scene['elements'] if (e.get('customData') or {}).get('evoDesignDecoration') == kind]


def test_emphasis_marks_primary_and_mutes_side_nodes():
    data = structure()
    data['nodes'][3]['emphasis'] = 'primary'
    data['nodes'][6]['emphasis'] = 'muted'
    hosts = cards(apply_architecture_design_system(manifest(), data))
    assert hosts['users']['strokeWidth'] > hosts['orders']['strokeWidth']
    assert hosts['cache']['backgroundColor'] == '#F8FAFC'


def test_zone_bands_hug_their_cards_and_never_repeat_a_name():
    nodes = [{'id': 'c', 'label': 'App', 'sublabel': 'x', 'role': 'client'},
             {'id': 'g', 'label': 'Gateway', 'sublabel': 'x', 'role': 'gateway'},
             {'id': 's1', 'label': 'S1', 'sublabel': 'x', 'role': 'service'},
             {'id': 's2', 'label': 'S2', 'sublabel': 'x', 'role': 'service'},
             {'id': 's3', 'label': 'S3', 'sublabel': 'x', 'role': 'service'},
             {'id': 'm', 'label': 'Model Gateway', 'sublabel': 'x', 'role': 'gateway'}]
    scene = _scene(nodes, [('c', 'g'), ('g', 's1'), ('g', 's2'), ('g', 's3'), ('s1', 'm')],
                   {'columns': [['c'], ['g'], ['s1', 's2', 's3'], ['m']], 'bottom_row': []})
    labels = [t['text'] for t in _decorations(scene, 'zone_label')]
    assert len(labels) == len(set(labels)) and 'External' in labels
    bands = sorted(_decorations(scene, 'zone'), key=lambda e: e['x'])
    assert bands[0]['height'] < bands[2]['height']


def test_title_sits_above_the_diagram_and_is_ignored_by_verification():
    from evo_diagram.agentic_system.verification_stage.checks.collision_detection import (
        check_edge_node_intersections, check_node_overlap)
    data = structure()
    data['title'] = '电商系统架构'
    scene = apply_architecture_design_system(manifest(), data)
    [title] = _decorations(scene, 'title')
    assert title['text'] == '电商系统架构'
    assert title['y'] < min(h['y'] for h in cards(scene).values())
    assert check_edge_node_intersections(scene) == [] and check_node_overlap(scene) == []


def test_zone_names_beside_the_tier_plan_are_used():
    spec = {'pattern_specific_layout_blueprint': {
        'tier_plan': {'columns': [['app', 'web'], ['gw'], ['orders', 'users']], 'bottom_row': ['cache', 'db']},
        'column_labels': ['接入端', '网关层', '业务服务'], 'bottom_label': '数据存储'}}
    scene = apply_architecture_design_system(manifest(), structure(), layout_specification=spec)
    labels = {t['text'] for t in _decorations(scene, 'zone_label')}
    assert labels == {'接入端', '网关层', '业务服务', '数据存储'}


def test_main_path_connectors_lead_and_side_ones_step_back():
    data = structure()
    data['nodes'][2]['emphasis'] = 'primary'
    scene = apply_architecture_design_system(manifest(), data)
    arrows = [e for e in scene['elements'] if e['type'] == 'arrow']
    main = [a for a in arrows if 'gw' in (a['meta']['source'], a['meta']['target'])]
    side = [a for a in arrows if a not in main]
    assert main and all(a['strokeWidth'] > 1.5 and a['opacity'] == 100 for a in main)
    assert side and all(a['opacity'] < 100 for a in side)
