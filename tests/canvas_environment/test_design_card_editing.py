"""Generated design cards remain editable through the public CLI contract."""
import copy

import pytest

from evo_diagram.canvas_environment.editing import EditError, apply_operations, assert_preserves_locks
from evo_diagram.agentic_system.render_engine.excalidraw.architecture_design_system import apply_architecture_design_system
from evo_diagram.tests.render_engine.test_architecture_design_system import manifest, structure


def card_scene():
    scene = apply_architecture_design_system(manifest(), structure())
    host_id = scene['_meta']['id_map']['web']
    host = next(e for e in scene['elements'] if e['id'] == host_id)
    return scene, host


def test_cli_rename_updates_the_visible_native_title_without_duplicate_labels():
    scene, host = card_scene()
    original = copy.deepcopy(scene)
    result, changed = apply_operations(scene, [{'op': 'set_text', 'id': host['id'], 'text': 'Browser'}], scope=[host['id']])
    title_id = host['customData']['evoDesignCard']['titleId']
    assert changed == [title_id]
    assert next(e for e in result['elements'] if e['id'] == title_id)['text'] == 'Browser'
    assert not any(e.get('text') == 'Web' for e in result['elements'])
    assert scene == original


def test_moving_a_card_moves_its_companions_and_bound_connector_endpoints():
    scene, host = card_scene()
    bound = {b['id'] for b in host['boundElements']}
    result, changed = apply_operations(scene, [{'op': 'move_node', 'id': host['id'],
        'x': host['x']+20, 'y': host['y']+30}], scope=[host['id'], *bound])
    before = {e['id']: e for e in scene['elements']}
    after = {e['id']: e for e in result['elements']}
    parts = host['customData']['evoDesignCard']
    for eid in (host['id'], parts['titleId'], parts['iconId'], parts['sublabelId']):
        assert after[eid]['x'] == before[eid]['x']+20
        assert after[eid]['y'] == before[eid]['y']+30
        assert eid in changed
    for eid in bound:
        if before[eid]['type'] == 'arrow':
            assert after[eid]['startBinding']['elementId'] == host['id']
            assert after[eid]['x'] == before[eid]['x']+20
    assert set(changed) <= {host['id'], *bound, parts['iconId'], parts['sublabelId']}


def test_moving_without_connector_scope_is_rejected():
    scene, host = card_scene()
    with pytest.raises(EditError, match='Required scope'):
        apply_operations(scene, [{'op': 'move_node', 'id': host['id'], 'x': 400, 'y': 300}], scope=[host['id']])


def test_a_locked_card_protects_its_subtitle_and_embedded_icon_file():
    scene, host = card_scene()
    host['locked'] = True
    parts = host['customData']['evoDesignCard']
    with pytest.raises(EditError, match='locked'):
        apply_operations(scene, [{'op': 'set_text', 'id': parts['sublabelId'], 'text': 'Changed'}])
    candidate = copy.deepcopy(scene)
    icon = next(e for e in candidate['elements'] if e['id'] == parts['iconId'])
    candidate['files'][icon['fileId']]['dataURL'] = 'replaced'
    with pytest.raises(EditError, match='locked image'):
        assert_preserves_locks(scene, candidate)


def test_cascading_delete_removes_every_card_part_and_native_connector():
    scene, host = card_scene()
    parts = host['customData']['evoDesignCard']
    result, changed = apply_operations(scene, [{'op': 'delete_node', 'id': host['id'], 'cascade': True}])
    deleted = {e['id'] for e in result['elements'] if e.get('isDeleted')}
    assert {host['id'], parts['titleId'], parts['iconId'], parts['sublabelId']} <= deleted
    assert {b['id'] for b in host['boundElements']} <= deleted
    assert deleted <= set(changed)
    before = {e['id']: e for e in scene['elements']}
    after = {e['id']: e for e in result['elements']}
    for eid in set(changed) - deleted:
        expected = {**before[eid], 'boundElements': [b for b in before[eid]['boundElements'] if b['id'] not in deleted]}
        assert {k: v for k, v in after[eid].items() if k not in {'version', 'versionNonce'}} == {
            k: v for k, v in expected.items() if k not in {'version', 'versionNonce'}}
