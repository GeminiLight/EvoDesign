import base64
import copy
import json

import pytest

from evo_diagram.agentic_system.common.node_icons import ICON_KEY, sync_node_icons
from evo_diagram.agentic_system.render_engine.excalidraw.converter import InstantiationToExcalidrawConverter
from evo_diagram.agentic_system.render_engine.excalidraw.shape_size_fitter import fit_shape_sizes_to_text
from evo_diagram.agentic_system.refinement_stage.fixers.primitives import op_set_position, op_set_size, op_set_style
from evo_diagram.agentic_system.verification_stage.checks.node_icons import check_node_icons


def scene():
    layout = {'node': {'shape': 'rectangle', 'label': {'text': 'Analyze'}, 'x': 100, 'y': 100,
                       'w': 200, 'h': 64, 'strokeColor': '#6354A3', 'backgroundColor': '#DAD4EE'},
              'node:icon': {'type': 'icon', 'props': {'icon': 'analytics', 'color': 'blue'}}}
    return fit_shape_sizes_to_text(InstantiationToExcalidrawConverter(layout).convert())


def parts(manifest):
    return tuple(next(e for e in manifest['elements'] if e['type'] == kind) for kind in ('rectangle','text','image'))


def test_bundled_icon_needs_no_download_and_matches_exact_node_color(monkeypatch):
    from evo_diagram.agentic_system.render_engine.excalidraw import converter
    monkeypatch.setattr(converter, 'require_icon_svg_path', lambda *a,**k: pytest.fail('Unexpected external asset lookup'))
    manifest = scene()
    node, text, icon = parts(manifest)
    assert icon['width'] == icon['height'] == 26
    assert icon['groupIds'] == node['groupIds'] == text['groupIds']
    assert icon['customData'][ICON_KEY]['hostId'] == node['id']
    svg = base64.b64decode(manifest['files'][icon['fileId']]['dataURL'].split(',')[1]).decode()
    assert '#6354A3' in svg
    assert svg.startswith('<svg ')  # Native Excalidraw rejects namespace-prefixed roots.
    assert check_node_icons(manifest, 'excalidraw') == []


def test_move_keeps_icon_and_label_with_node():
    manifest = scene()
    node,text,icon = parts(manifest)
    old = [e['x'] for e in (node,text,icon)]
    assert op_set_position(manifest,node['id'],{'x':node['x']+100,'y':node['y']+50})[0]
    assert [e['x']-x for e,x in zip((node,text,icon),old)] == [100,100,100]
    assert check_node_icons(manifest,'excalidraw') == []


@pytest.mark.parametrize('width,height', [(200,64),(90,25),(350,120)])
def test_resize_preserves_separate_content_areas(width,height):
    manifest = scene()
    node,text,icon = parts(manifest)
    assert op_set_size(manifest,node['id'],{'width':width,'height':height})[0]
    assert text['x'] >= icon['x']+icon['width']+9
    assert text['x']+text['width'] <= node['x']+node['width']
    assert check_node_icons(manifest,'excalidraw') == []


def test_recolor_preserves_portable_svg():
    manifest = scene()
    node,_,icon = parts(manifest)
    old_file = icon['fileId']
    op_set_style(manifest,node['id'],{'strokeColor':'#2255AA'})
    assert icon['fileId'] != old_file
    svg = base64.b64decode(manifest['files'][icon['fileId']]['dataURL'].split(',')[1]).decode()
    assert '#2255AA' in svg and '#6354A3' not in svg
    assert check_node_icons(json.loads(json.dumps(manifest)),'excalidraw') == []


def test_native_duplicate_resolves_new_group_not_stale_custom_host_id():
    manifest = scene()
    node,text,icon = parts(manifest)
    clone = copy.deepcopy(manifest['elements'])
    mapping = {e['id']:e['id']+'copy' for e in clone}
    for e in clone:
        e['id'] = mapping[e['id']]
        e['x'] += 400
        e['groupIds'] = ['copied-group']
        if e.get('containerId'): e['containerId'] = mapping[e['containerId']]
    manifest['elements'].extend(clone)
    sync_node_icons(manifest)
    cloned_icon = next(e for e in clone if e['type']=='image')
    assert cloned_icon['customData'][ICON_KEY]['hostId'] == mapping[node['id']]
    assert cloned_icon['x'] == icon['x']+400
    assert check_node_icons(manifest,'excalidraw') == []


def test_deleted_host_deletes_companion_but_leaves_ordinary_images():
    manifest = scene()
    node,_,icon = parts(manifest)
    ordinary = dict(icon, id='ordinary', customData={}, groupIds=[])
    manifest['elements'].append(ordinary)
    node['isDeleted'] = True
    sync_node_icons(manifest)
    assert icon['isDeleted']
    assert not ordinary['isDeleted']


def test_checks_detect_asset_ownership_and_text_overlap():
    manifest = scene()
    node,text,icon = parts(manifest)
    icon['x'] = text['x']
    manifest['files'] = {}
    assert {f.category for f in check_node_icons(manifest,'excalidraw')} == {'icon/text_overlap','icon/missing_asset'}
    manifest['elements'].remove(node)
    assert {f.category for f in check_node_icons(manifest,'excalidraw')} == {'icon/missing_host'}


def test_reconciliation_is_idempotent_and_rotation_stays_contained():
    manifest = scene()
    node,_,_ = parts(manifest)
    node['angle'] = 0.4
    sync_node_icons(manifest)
    assert check_node_icons(manifest,'excalidraw') == []
    before = copy.deepcopy(manifest)
    sync_node_icons(manifest)
    assert before == manifest


def test_refiner_cannot_detach_or_erase_icons_after_native_save_drops_semantic_map():
    from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
    from evo_diagram.agentic_system.refinement_stage.state import EditOp
    manifest = scene()
    manifest.pop('_meta')
    _,_,icon = parts(manifest)
    _,outcomes = apply_edits(manifest, [EditOp(op='delete_element',id=icon['id'],payload={},source='llm',rationale='cleanup')])
    assert not outcomes[0].applied
    assert not icon['isDeleted']


def test_ellipse_icons_stay_inside_curved_boundary_after_resize_move_and_rotation():
    manifest = scene()
    node, text, icon = parts(manifest)
    node.update(type='ellipse', width=90, height=64, angle=0.4)
    sync_node_icons(manifest)
    assert node['type'] == 'ellipse'
    assert check_node_icons(manifest, 'excalidraw') == []
    before = copy.deepcopy(manifest)
    sync_node_icons(manifest)
    assert manifest == before
    assert op_set_position(manifest, node['id'], {'x': 400, 'y': 200})[0]
    assert check_node_icons(manifest, 'excalidraw') == []
    node['angle'] = 0
    sync_node_icons(manifest)
    icon.update(x=node['x'], y=node['y'])
    assert 'icon/outside_host' in {f.category for f in check_node_icons(manifest, 'excalidraw')}
