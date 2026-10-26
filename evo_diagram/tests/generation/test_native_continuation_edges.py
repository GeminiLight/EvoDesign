import json

from evo_diagram.agentic_system.generation_stage.unified.continuation import complete_scene_prefix


def test_checkpoint_with_finished_elements_array_preserves_top_level_prefix():
    scene = {
        "type": "excalidraw/clipboard",
        "elements": [{"id": "a", "type": "rectangle"}],
        "files": {},
    }
    text = json.dumps(scene)[:-1]
    prefix = complete_scene_prefix(text)
    assert json.loads(prefix + '}') == {
        "type": "excalidraw/clipboard",
        "elements": [{"id": "a", "type": "rectangle"}],
        "files": {},
    }


def test_checkpoint_does_not_treat_nested_partial_array_as_complete_element():
    partial = '{"type":"excalidraw/clipboard","elements":[{"id":"a","points":[[0,0],'
    assert complete_scene_prefix(partial) == '{"type":"excalidraw/clipboard","elements":['


def test_checkpoint_does_not_find_elements_key_inside_string_values():
    assert complete_scene_prefix('{"note":"the \\"elements\\" array [ is truncated') == ""
