from __future__ import annotations

from app.services.diagram_schema_inspection import (
    CONNECTOR_COLLECTION_KEYS,
    NODE_COLLECTION_KEYS,
    count_schema_collection,
    first_schema_collection,
    tldraw_arrow_terminals,
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


def test_schema_collection_helpers_support_tldraw_editor_snapshots():
    # getSnapshot(editor.store) and the TLDraw converter save document.store.
    schema = {
        "document": {
            "store": {
                "shape:a": {"id": "shape:a", "typeName": "shape", "type": "geo"},
                "shape:b": {"id": "shape:b", "typeName": "shape", "type": "geo"},
                "shape:arrow": {"id": "shape:arrow", "typeName": "shape", "type": "arrow"},
                "page:page": {"id": "page:page", "typeName": "page"},
            },
            "schema": {"schemaVersion": 2},
        },
        "session": {},
    }

    assert count_schema_collection(schema, NODE_COLLECTION_KEYS) == 2
    assert count_schema_collection(schema, CONNECTOR_COLLECTION_KEYS) == 1


def test_schema_collection_helpers_prefer_document_store_then_root_store():
    def geo(shape_id: str) -> dict:
        return {"id": shape_id, "typeName": "shape", "type": "geo"}

    both = {
        "document": {
            "store": {"shape:a": geo("shape:a")},
            "records": {"shape:old": geo("shape:old")},
        }
    }
    nested_and_root = {
        "document": {"store": {"shape:a": geo("shape:a")}},
        "store": {"shape:old": geo("shape:old")},
    }
    root = {
        "store": {"shape:a": geo("shape:a"), "shape:b": geo("shape:b")},
        "schema": {},
    }

    assert first_schema_collection(both, NODE_COLLECTION_KEYS) == [geo("shape:a")]
    assert first_schema_collection(nested_and_root, NODE_COLLECTION_KEYS) == [
        geo("shape:a")
    ]
    assert count_schema_collection(root, NODE_COLLECTION_KEYS) == 2


def test_tldraw_arrow_terminals_read_binding_records():
    def binding(binding_id: str, to_id: str, terminal: str, kind: str = "arrow") -> dict:
        return {
            "id": binding_id,
            "typeName": "binding",
            "type": kind,
            "fromId": "shape:arrow",
            "toId": to_id,
            "props": {"terminal": terminal},
        }

    store = {
        "shape:arrow": {"id": "shape:arrow", "typeName": "shape", "type": "arrow"},
        "binding:start": binding("binding:start", "shape:a", "start"),
        "binding:end": binding("binding:end", "shape:b", "end"),
        "binding:other": binding("binding:other", "shape:c", "end", kind="custom"),
    }

    assert tldraw_arrow_terminals({"document": {"store": store}}) == {
        "shape:arrow": {"start": "shape:a", "end": "shape:b"},
    }
    assert tldraw_arrow_terminals({"elements": []}) == {}
    assert tldraw_arrow_terminals(None) == {}
