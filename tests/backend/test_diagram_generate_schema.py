from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.diagram_generate import DiagramGenerateRequest, DiagramLocalEditRequest


def test_generate_request_rejects_unknown_top_level_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DiagramGenerateRequest(
            context="A to B",
            canvas_library="excalidraw",
            unexpected=True,
        )


def test_generate_request_keeps_current_schema_payload_permissive():
    request = DiagramGenerateRequest(
        context="A to B",
        canvas_library="excalidraw",
        current_schema={
            "elements": [{"id": "n1", "custom_key": {"nested": True}}],
            "future_editor_payload": ["ok"],
        },
    )

    assert request.current_schema == {
        "elements": [{"id": "n1", "custom_key": {"nested": True}}],
        "future_editor_payload": ["ok"],
    }


def test_generate_request_normalizes_canvas_library():
    request = DiagramGenerateRequest(
        context="A to B",
        canvas_library=" TLDraw ",
    )

    assert request.canvas_library == "tldraw"


def test_icons_are_optional_and_accept_only_explicit_booleans():
    assert DiagramGenerateRequest(context="A to B", canvas_library="excalidraw").use_icons is False
    assert DiagramGenerateRequest(context="A to B", canvas_library="excalidraw", use_icons=True).use_icons is True
    with pytest.raises(ValidationError):
        DiagramGenerateRequest(context="A to B", canvas_library="excalidraw", use_icons="false")


def test_generate_request_rejects_unknown_canvas_library():
    with pytest.raises(ValidationError, match="Unsupported canvas library"):
        DiagramGenerateRequest(
            context="A to B",
            canvas_library="unknown",
        )


def test_generate_request_requires_explicit_canvas_library():
    with pytest.raises(ValidationError) as exc_info:
        DiagramGenerateRequest(context="A to B")

    assert ("canvas_library",) in {
        tuple(error["loc"]) for error in exc_info.value.errors()
    }


def test_local_edit_request_normalizes_canvas_library_like_generate_request():
    request = DiagramLocalEditRequest(
        current_schema={"records": {}},
        selected_node_ids=["shape:1"],
        instruction="Move it right",
        canvas_library=" TLDraw ",
    )

    assert request.canvas_library == "tldraw"


def test_local_edit_request_rejects_unknown_canvas_library_like_generate_request():
    with pytest.raises(ValidationError, match="Unsupported canvas library"):
        DiagramLocalEditRequest(
            current_schema={"elements": []},
            selected_node_ids=["node-1"],
            instruction="Make it blue",
            canvas_library="unknown",
        )


def test_local_edit_request_rejects_unknown_top_level_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DiagramLocalEditRequest(
            current_schema={"elements": []},
            selected_node_ids=["node-1"],
            instruction="Make it blue",
            canvas_library="excalidraw",
            unexpected=True,
        )


def test_local_edit_request_keeps_current_schema_payload_permissive():
    request = DiagramLocalEditRequest(
        current_schema={
            "document": {"store": {"shape:1": {"custom": ["ok"]}}},
            "future_editor_payload": {"nested": True},
        },
        selected_node_ids=["shape:1"],
        instruction="Move it right",
        canvas_library="tldraw",
    )

    assert request.current_schema == {
        "document": {"store": {"shape:1": {"custom": ["ok"]}}},
        "future_editor_payload": {"nested": True},
    }


def test_local_edit_request_requires_explicit_canvas_library():
    with pytest.raises(ValidationError) as exc_info:
        DiagramLocalEditRequest(
            current_schema={"elements": []},
            selected_node_ids=["node-1"],
            instruction="Make it blue",
        )

    assert ("canvas_library",) in {
        tuple(error["loc"]) for error in exc_info.value.errors()
    }
