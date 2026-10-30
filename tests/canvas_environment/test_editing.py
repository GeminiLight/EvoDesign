import copy

import pytest

from evo_diagram.canvas_environment import EditError, apply_operations, assert_preserves_locks


def scene():
    return apply_operations({'elements': []}, [
        {'op': 'add_node', 'id': 'a', 'x': 0, 'y': 0, 'width': 160, 'height': 80, 'text': 'Input'},
        {'op': 'add_node', 'id': 'b', 'x': 300, 'y': 0, 'width': 160, 'height': 80, 'text': 'Encoder'},
        {'op': 'connect', 'id': 'edge', 'from': 'a', 'to': 'b'},
    ])[0]


def test_text_edit_preserves_manual_geometry_and_unrelated_records():
    original = scene()
    untouched = copy.deepcopy(original)
    updated, changed = apply_operations(original, [{'op': 'set_text', 'id': 'a', 'text': 'Features'}], scope=['a'])
    assert original == untouched
    assert changed == ['a-label']
    assert next(e for e in updated['elements'] if e['id'] == 'a-label')['text'] == 'Features'
    assert next(e for e in updated['elements'] if e['id'] == 'b') == next(e for e in original['elements'] if e['id'] == 'b')


def test_move_requires_explicit_connector_scope_and_keeps_other_endpoint():
    original = scene()
    op = [{'op': 'move_node', 'id': 'a', 'x': 20, 'y': 50}]
    with pytest.raises(EditError, match='Required scope: edge'):
        apply_operations(original, op, scope=['a'])
    updated, changed = apply_operations(original, op, scope=['a', 'edge'])
    edge = next(e for e in updated['elements'] if e['id'] == 'edge')
    assert [edge['x']+edge['points'][-1][0], edge['y']+edge['points'][-1][1]] == [300, 40]
    assert set(changed) == {'a', 'a-label', 'edge'}


@pytest.mark.parametrize('op', [
    {'op': 'set_text', 'id': 'a', 'text': 'Changed'},
    {'op': 'set_style', 'id': 'a', 'style': {'fill': '#ffffff'}},
    {'op': 'delete_node', 'id': 'a', 'cascade': True},
])
def test_locked_semantic_node_protects_its_text_and_dependencies(op):
    original = scene()
    with pytest.raises(EditError) as error:
        apply_operations(original, [op], locked=['a'])
    assert error.value.code == 'locked_element'


def test_delete_removes_references_and_keeps_other_node():
    updated, changed = apply_operations(scene(), [{'op': 'delete_node', 'id': 'a', 'cascade': True}])
    elements = {e['id']: e for e in updated['elements']}
    assert elements['a']['isDeleted'] and elements['a-label']['isDeleted'] and elements['edge']['isDeleted']
    assert not elements['b']['isDeleted']
    assert elements['b']['boundElements'] == [{'id': 'b-label', 'type': 'text'}]


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, 100001])
def test_rejects_nonfinite_or_unbounded_geometry(value):
    with pytest.raises(EditError):
        apply_operations(scene(), [{'op': 'move_node', 'id': 'a', 'x': value, 'y': 0}])


def test_raw_generation_cannot_bypass_locked_parent_labels_or_image_data():
    original = scene()
    original['elements'][0]['locked'] = True
    assert_preserves_locks(original, copy.deepcopy(original))
    candidate = copy.deepcopy(original)
    next(e for e in candidate['elements'] if e['id'] == 'a-label')['text'] = 'Changed by generator'
    with pytest.raises(EditError, match='locked element'):
        assert_preserves_locks(original, candidate)
    image = {'elements': [{'id': 'image', 'locked': True, 'fileId': 'file'}],
             'files': {'file': {'dataURL': 'original'}}}
    candidate = copy.deepcopy(image)
    candidate['files']['file']['dataURL'] = 'changed'
    with pytest.raises(EditError, match='locked image'):
        assert_preserves_locks(image, candidate)


def test_vertical_connections_use_facing_ports_and_labels_are_centered():
    result, _ = apply_operations({'elements': []}, [
        {'op': 'add_node', 'id': 'top', 'x': 0, 'y': 0, 'width': 200, 'height': 100, 'text': 'Top'},
        {'op': 'add_node', 'id': 'bottom', 'x': 0, 'y': 300, 'width': 200, 'height': 100, 'text': 'Bottom'},
        {'op': 'connect', 'id': 'down', 'from': 'top', 'to': 'bottom'},
    ])
    by_id = {e['id']: e for e in result['elements']}
    arrow = by_id['down']
    assert (arrow['x'], arrow['y']) == (100, 100)
    assert arrow['points'] == [[0, 0], [0, 200]]
    label = by_id['top-label']
    assert label['y'] + label['height']/2 == 50
