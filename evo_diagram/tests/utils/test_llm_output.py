"""Tests for LLM output JSON parsing helpers."""

import json

import pytest

from evo_diagram.utils.llm_output import convert_json_output


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

    with pytest.raises(json.JSONDecodeError, match="Expected response to be exactly"):
        convert_json_output('```json\n{"ok": true}\n```', strict_response=True)
