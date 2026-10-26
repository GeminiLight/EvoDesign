from __future__ import annotations

import base64

import pytest

from app.services import thumbnail_service
from app.services.thumbnail_service import (
    ThumbnailGenerationError,
    _get_fill,
    generate_svg_thumbnail,
)


def _decode_svg(data_uri: str) -> str:
    prefix = "data:image/svg+xml;base64,"
    assert data_uri.startswith(prefix)
    return base64.b64decode(data_uri.removeprefix(prefix)).decode()


def test_generate_svg_thumbnail_renders_nodes_edges_and_escaped_labels():
    data_uri = generate_svg_thumbnail(
        {
            "elements": [
                {
                    "id": "a",
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 50,
                    "text": "<Start>",
                    "backgroundColor": "#abcdef",
                },
                {
                    "id": "b",
                    "geometry": {"left": 180, "top": 100, "w": 120, "h": 60},
                    "label": {"text": "Finish"},
                    "fill": "#123456",
                },
                {
                    "type": "arrow",
                    "startBinding": {"elementId": "a"},
                    "endBinding": {"elementId": "b"},
                },
            ]
        }
    )

    svg = _decode_svg(data_uri)

    assert "&lt;Start&gt;" in svg
    assert "<Start>" not in svg
    assert 'marker-end="url(#ah)"' in svg
    assert "#abcdef" in svg
    assert "#123456" in svg


def test_generate_svg_thumbnail_renders_persisted_collection_aliases():
    data_uri = generate_svg_thumbnail(
        {
            "blocks": [
                {"id": "a", "x": 0, "y": 0, "width": 100, "height": 50},
                {"id": "b", "x": 180, "y": 100, "width": 120, "height": 60},
            ],
            "arrows": [
                {"source": "a", "target": "b"},
            ],
        }
    )

    svg = _decode_svg(data_uri)

    assert 'marker-end="url(#ah)"' in svg
    assert "No preview" not in svg


def test_generate_svg_thumbnail_renders_tldraw_root_records():
    data_uri = generate_svg_thumbnail(
        {
            "records": {
                "shape:a": {
                    "id": "shape:a",
                    "typeName": "shape",
                    "type": "geo",
                    "x": 0,
                    "y": 0,
                    "props": {"w": 100, "h": 50, "text": "Start"},
                },
                "shape:b": {
                    "id": "shape:b",
                    "typeName": "shape",
                    "type": "geo",
                    "x": 180,
                    "y": 100,
                    "props": {"w": 120, "h": 60, "text": "Finish"},
                },
                "shape:arrow": {
                    "id": "shape:arrow",
                    "typeName": "shape",
                    "type": "arrow",
                    "props": {
                        "start": {"type": "binding", "boundShapeId": "shape:a"},
                        "end": {"type": "binding", "boundShapeId": "shape:b"},
                    },
                },
            }
        },
        canvas_engine="tldraw",
    )

    svg = _decode_svg(data_uri)

    assert "Start" in svg
    assert "Finish" in svg
    assert 'marker-end="url(#ah)"' in svg
    assert "No preview" not in svg


def test_generate_svg_thumbnail_renders_tldraw_document_records():
    data_uri = generate_svg_thumbnail(
        {
            "document": {
                "records": {
                    "shape:a": {
                        "id": "shape:a",
                        "typeName": "shape",
                        "type": "geo",
                        "x": 0,
                        "y": 0,
                        "props": {"w": 100, "h": 50, "text": "Nested"},
                    }
                }
            }
        },
        canvas_engine="tldraw",
    )

    svg = _decode_svg(data_uri)

    assert "Nested" in svg
    assert "No preview" not in svg


def test_generate_svg_thumbnail_returns_placeholder_for_invalid_geometry():
    data_uri = generate_svg_thumbnail(
        {
            "elements": [
                {
                    "id": "bad",
                    "x": "not-a-number",
                    "y": 0,
                    "width": 100,
                    "height": 50,
                    "label": "Bad",
                },
                {
                    "id": "also-bad",
                    "x": 0,
                    "y": 0,
                    "width": -10,
                    "height": 50,
                    "label": "Negative",
                },
            ]
        }
    )

    svg = _decode_svg(data_uri)

    assert "No preview" in svg
    assert "Bad" not in svg
    assert "Negative" not in svg


def test_generate_svg_thumbnail_keeps_labels_and_fills_with_their_own_nodes():
    """Dropping an unparseable node must not shift later labels and fills."""
    data_uri = generate_svg_thumbnail(
        {
            "elements": [
                {
                    "id": "broken",
                    "x": "not-a-number",
                    "y": 0,
                    "width": 100,
                    "height": 50,
                    "label": "Dropped",
                    "fill": "#111111",
                },
                {
                    "id": "a",
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 50,
                    "label": "First",
                    "fill": "#222222",
                },
                {
                    "id": "b",
                    "x": 180,
                    "y": 100,
                    "width": 120,
                    "height": 60,
                    "label": "Second",
                    "fill": "#333333",
                },
            ]
        }
    )

    svg = _decode_svg(data_uri)

    assert "Dropped" not in svg
    assert "#111111" not in svg
    assert (
        svg.index("#222222")
        < svg.index("First")
        < svg.index("#333333")
        < svg.index("Second")
    )


def test_generate_svg_thumbnail_raises_typed_error_on_render_failures(monkeypatch):
    def fail_render(schema_blob, canvas_engine):
        raise ValueError("renderer failed")

    monkeypatch.setattr(thumbnail_service, "_render", fail_render)

    with pytest.raises(ThumbnailGenerationError, match="thumbnail render failed"):
        generate_svg_thumbnail({"elements": []})


def test_get_fill_accepts_hex_colors_only():
    assert _get_fill({"fill": "#abc"}, 0) == "#abc"
    assert _get_fill({"fill": " #aabbcc "}, 0) == "#aabbcc"
    assert _get_fill({"fill": '#fff" onload="alert(1)'}, 0) == "#dbeafe"
    assert _get_fill({"fill": "red"}, 1) == "#e0e7ff"
