from __future__ import annotations

from app.services.diagram_schema_inspection import (
    CONNECTOR_COLLECTION_KEYS,
    NODE_COLLECTION_KEYS,
    count_schema_collection,
    first_schema_collection,
)


def test_first_schema_collection_returns_first_supported_list():
    schema = {
        "elements": "not-a-list",
        "nodes": [{"id": "n1"}],
        "shapes": [{"id": "ignored"}],
    }

    assert first_schema_collection(schema, NODE_COLLECTION_KEYS) == [{"id": "n1"}]


def test_schema_collection_helpers_support_persisted_connector_aliases():
    assert count_schema_collection(
        {"arrows": [{"id": "a1"}, {"id": "a2"}]},
        CONNECTOR_COLLECTION_KEYS,
    ) == 2
    assert count_schema_collection(
        {"relations": [{"id": "r1"}]},
        CONNECTOR_COLLECTION_KEYS,
    ) == 1


def test_schema_collection_helpers_support_root_tldraw_records():
    schema = {
        "records": {
            "shape:a": {"id": "shape:a", "typeName": "shape", "type": "geo"},
            "shape:b": {"id": "shape:b", "typeName": "shape", "type": "text"},
            "shape:arrow": {"id": "shape:arrow", "typeName": "shape", "type": "arrow"},
            "asset:1": {"id": "asset:1", "typeName": "asset"},
        }
    }

    assert count_schema_collection(schema, NODE_COLLECTION_KEYS) == 2
    assert count_schema_collection(schema, CONNECTOR_COLLECTION_KEYS) == 1
    assert first_schema_collection(schema, NODE_COLLECTION_KEYS) == [
        {"id": "shape:a", "typeName": "shape", "type": "geo"},
        {"id": "shape:b", "typeName": "shape", "type": "text"},
    ]


def test_schema_collection_helpers_support_document_tldraw_records():
    schema = {
        "document": {
            "records": {
                "shape:a": {"id": "shape:a", "typeName": "shape", "type": "geo"},
                "shape:arrow": {
                    "id": "shape:arrow",
                    "typeName": "shape",
                    "type": "arrow",
                },
            }
        },
        "records": {
            "shape:ignored": {
                "id": "shape:ignored",
                "typeName": "shape",
                "type": "geo",
            }
        },
    }

    assert count_schema_collection(schema, NODE_COLLECTION_KEYS) == 1
    assert count_schema_collection(schema, CONNECTOR_COLLECTION_KEYS) == 1


def test_schema_collection_helpers_ignore_non_dict_schema_blobs():
    assert first_schema_collection(None, NODE_COLLECTION_KEYS) == []
    assert count_schema_collection([], CONNECTOR_COLLECTION_KEYS) == 0
