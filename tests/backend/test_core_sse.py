from __future__ import annotations

from app.core.sse import format_sse_event, parse_sse_event


def test_format_sse_event_serializes_json_object_payload():
    chunk = format_sse_event("result", {"request_id": "req_1", "text": "hello"})

    assert chunk == 'event: result\ndata: {"request_id": "req_1", "text": "hello"}\n\n'


def test_format_sse_event_preserves_unicode_payloads():
    chunk = format_sse_event("message", {"text": "\u8bbe\u8ba1"})

    assert "\\u8bbe" not in chunk


def test_parse_sse_event_reads_event_name_and_json_object_payload():
    event = parse_sse_event(
        'event: result\ndata: {"request_id": "req_1", "schema_blob": {}}\n\n'
    )

    assert event is not None
    assert event.event == "result"
    assert event.data == {"request_id": "req_1", "schema_blob": {}}


def test_parse_sse_event_accepts_multiline_json_data_payloads():
    event = parse_sse_event(
        'event: result\ndata: {"request_id": "req_1",\n'
        'data: "schema_blob": {}}\n\n'
    )

    assert event is not None
    assert event.data == {"request_id": "req_1", "schema_blob": {}}


def test_parse_sse_event_rejects_missing_or_non_object_json_payloads():
    assert parse_sse_event("data: {}\n\n") is None
    assert parse_sse_event("event: result\n\n") is None
    assert parse_sse_event("event: result\ndata: not-json\n\n") is None
    assert parse_sse_event("event: result\ndata: []\n\n") is None
