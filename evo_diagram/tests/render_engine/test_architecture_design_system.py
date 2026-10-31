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
        'groups': [{'id': 'data_layer', 'label': 'Data', 'members': ['db', 'cache']}],
    }


def manifest():
    layout = {}
    for index, node in enumerate(NODES):
        layout[node['id']] = {'shape': 'ellipse' if node['id'] == 'db' else 'rectangle',
                              'label': {'text': node['label']}, 'x': 100 + index * 50, 'y': 100,
                              'w': 160, 'h': 60, 'strokeColor': '#333333', 'backgroundColor': '#EEEEEE'}
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


def test_group_frames_and_edge_labels_are_removed():
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
    data['edges'].append({'id': 'edge:gw2web', 'source': 'gw', 'target': 'web'})
    scene = apply_architecture_design_system(manifest(), data)
    arrows = [a for a in scene['elements'] if a['type'] == 'arrow']
    pair = [a for a in arrows if {a['meta']['source'], a['meta']['target']} == {'web', 'gw'}]
    assert len(pair) == 1 and pair[0]['startArrowhead'] and pair[0]['endArrowhead']


def test_merged_duplicate_and_reverse_edges_still_count_as_rendered():
    data = structure()
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
    assert host['backgroundColor'] == '#EDF4EA' and host['strokeColor'] == '#AABAAC'
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
