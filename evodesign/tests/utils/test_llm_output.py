"""Tests for LLM output JSON parsing helpers."""

import json

import pytest

from evodesign.utils.llm_output import convert_json_output


def test_convert_json_output_parses_prose_wrapped_array_of_objects():
    output = (
        'Here are edits: [{"op":"a","id":"n1","payload":{}},'
        '{"op":"b","id":"n2","payload":{}}]'
    )

    assert convert_json_output(output) == [
        {"op": "a", "id": "n1", "payload": {}},
        {"op": "b", "id": "n2", "payload": {}},
    ]


def test_convert_json_output_keeps_prose_wrapped_object_as_dict():
    output = 'Result: {"edits":[{"op":"a","id":"n1"}],"ok":true}'

    assert convert_json_output(output) == {
        "edits": [{"op": "a", "id": "n1"}],
        "ok": True,
    }


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('```json\n{"ok": true}\n```', {"ok": True}),
        ('<response>{"ok": true}</response>', {"ok": True}),
    ],
)
def test_convert_json_output_preserves_wrapped_object_compatibility(output, expected):
    assert convert_json_output(output) == expected


def test_convert_json_output_strict_accepts_exact_json_only():
    assert convert_json_output('{"ok": true}', strict_response=True) == {"ok": True}

    with pytest.raises(json.JSONDecodeError, match="Expected response to be exactly"):
        convert_json_output('Result: {"ok": true}', strict_response=True)

    # A response that is exactly one fenced block is still exactly one value.
    assert convert_json_output('```json\n{"ok": true}\n```', strict_response=True) == {"ok": True}
    assert convert_json_output('  ```\n[1, 2]\n```\n', strict_response=True) == [1, 2]
    assert convert_json_output('```json\n{"code": "a ``` b"}\n```', strict_response=True) == {"code": "a ``` b"}

    for text in ('Here you go:\n```json\n{"ok": true}\n```',
                 '```json\n{"ok": true}\n```\nHope this helps',
                 '```json\n{"ok": true}\n```\n```json\n{"ok": false}\n```'):
        with pytest.raises(json.JSONDecodeError, match="Expected response to be exactly"):
            convert_json_output(text, strict_response=True)


@pytest.mark.parametrize("text", [
    'Label with trailing comma, }',
    'list, ]',
    'quoted "key": value',
    'a 1 "b": 2',
    'double,, comma',
])
def test_fix_json_string_never_rewrites_string_contents(text):
    import json as _json

    from evodesign.utils.llm_output import fix_json_string

    payload = '{"label": ' + _json.dumps(text) + ', "n": 1,}'
    assert _json.loads(fix_json_string(payload)) == {"label": text, "n": 1}


@pytest.mark.parametrize("broken,expected", [
    ('{"a": 1,}', {"a": 1}),
    ('[1, 2,,]', [1, 2]),
    ('{"a": 1 "b": 2}', {"a": 1, "b": 2}),
    ('{"a": "v"\n"b": {"c": [1]} "d": 3}', {"a": "v", "b": {"c": [1]}, "d": 3}),
])
def test_fix_json_string_repairs_structural_commas(broken, expected):
    import json as _json

    from evodesign.utils.llm_output import fix_json_string

    assert _json.loads(fix_json_string(broken)) == expected


def test_lenient_parse_prefers_a_later_outermost_object_over_a_nested_one():
    output = (
        'Draft: {"meta": {"id": 1}, "items": [1 2]} '
        'Final: {"meta": {"id": 2}, "items": [1, 2]}'
    )
    assert convert_json_output(output) == {"meta": {"id": 2}, "items": [1, 2]}


def test_lenient_parse_falls_back_to_nested_object_when_nothing_else_parses():
    assert convert_json_output('Result: {"meta": {"id": 1}, "items": [1 2]}') == {"id": 1}
