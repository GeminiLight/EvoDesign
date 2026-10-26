from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.local_edit_service import (
    LOCAL_EDIT_INVALID_SCHEMA_DETAIL,
    LOCAL_EDIT_INVALID_SELECTION_DETAIL,
    LOCAL_EDIT_UNSUPPORTED_CANVAS_DETAIL,
    LocalEditResult,
    LocalEditResponseError,
    LocalEditService,
    LocalEditValidationError,
)


class FakeLlm:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response_text)


def test_local_editor_respects_configured_model_temperature(monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.local_edit_service.create_backend_llm", lambda **kw: calls.append(kw))
    LocalEditService()._create_llm()
    # Some deployed models only accept temperature=1; shared config owns it.
    assert calls == [{"max_tokens": 8192}]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    '{"elements": [{"id": "n2", "x": 900}]}',
    '{"elements": [{"id": "n1"}, {"id": "n1"}]}',
    '{"elements": [null]}',
    '{"elements": [{"id": "n1", "x": "far right"}]}',
    '{"elements": [], "deleted_ids": ["n2"]}',
])
async def test_local_edit_rejects_unsafe_delta(response):
    service = LocalEditService(llm=FakeLlm(response))
    with pytest.raises(LocalEditResponseError):
        await service.edit_local(
            {"elements": [{"id": "n1", "x": 0}, {"id": "n2", "x": 100}]},
            ["n1"], "Move selected node", "excalidraw",
        )


@pytest.mark.asyncio
async def test_local_edit_merges_partial_updates_and_requires_explicit_deletion():
    service = LocalEditService(llm=FakeLlm('{"elements": [{"id": "n1", "x": 20}]}'))
    result = await service.edit_local(
        {"elements": [{"id": "n1", "x": 0, "text": "Keep label", "type": "rectangle"},
                      {"id": "n2", "x": 100}]},
        ["n1", "n2"], "Move n1", "excalidraw",
    )
    assert result.operation_type == "update"
    assert result.modified_nodes["elements"][0]["text"] == "Keep label"
    assert result.modified_nodes.get("deleted_ids", []) == []


@pytest.mark.asyncio
async def test_local_edit_accepts_explicit_selected_deletion():
    service = LocalEditService(llm=FakeLlm('{"elements": [], "deleted_ids": ["n1"]}'))
    result = await service.edit_local({"elements": [{"id": "n1"}]}, ["n1"], "Delete it", "excalidraw")
    assert result.operation_type == "delete"
    assert result.modified_nodes["deleted_ids"] == ["n1"]


@pytest.mark.asyncio
async def test_local_edit_rejects_tldraw_key_id_mismatch_and_unselected_collision():
    for records in ['{"shape:1": {"id": "shape:2"}}', '{"shape:2": {"id": "shape:2"}}']:
        service = LocalEditService(llm=FakeLlm('{"records": ' + records + '}'))
        with pytest.raises(LocalEditResponseError):
            await service.edit_local(
                {"records": {key: {"id": key, "typeName": "shape"} for key in ["shape:1", "shape:2"]}},
                ["shape:1"], "Move selected shape", "tldraw",
            )


@pytest.mark.asyncio
async def test_edit_local_uses_injected_llm_and_selected_excalidraw_nodes():
    llm = FakeLlm(
        """
        ```json
        {"elements": [{"id": "n1", "x": 120, "customData": {"nested": true}}]}
        ```
        """
    )
    service = LocalEditService(llm=llm)

    result = await service.edit_local(
        current_schema={
            "elements": [
                {"id": "n1", "x": 0, "text": "Keep"},
                {"id": "n2", "x": 50, "text": "Do not include"},
            ]
        },
        selected_node_ids=["n1"],
        instruction="Move it right",
        canvas_library="excalidraw",
    )

    assert isinstance(result, LocalEditResult)
    assert result.operation_type == "update"
    assert result.modified_nodes["elements"][0]["id"] == "n1"
    assert result.modified_nodes["elements"][0]["customData"] == {"nested": True}
    assert len(llm.prompts) == 1
    assert '"id": "n1"' in llm.prompts[0]
    assert '"id": "n2"' not in llm.prompts[0]


@pytest.mark.asyncio
async def test_edit_local_rejects_missing_selected_nodes_without_calling_llm():
    llm = FakeLlm('{"elements": []}')
    service = LocalEditService(llm=llm)

    with pytest.raises(LocalEditValidationError, match="No nodes found") as exc_info:
        await service.edit_local(
            current_schema={"elements": [{"id": "n1"}]},
            selected_node_ids=["missing"],
            instruction="Move it",
            canvas_library="excalidraw",
        )

    assert exc_info.value.public_detail == LOCAL_EDIT_INVALID_SELECTION_DETAIL
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_edit_local_handles_tldraw_document_store_and_detects_add_operation():
    llm = FakeLlm(
        '{"records": {'
        '"shape:1": {"id": "shape:1", "typeName": "shape"},'
        '"shape:2": {"id": "shape:2", "typeName": "shape"}'
        "}}"
    )
    service = LocalEditService(llm=llm)

    result = await service.edit_local(
        current_schema={
            "document": {
                "store": {
                    "shape:1": {"id": "shape:1", "typeName": "shape"},
                    "page:1": {"id": "page:1", "typeName": "page"},
                    "asset:1": {"id": "asset:1", "typeName": "asset"},
                }
            }
        },
        selected_node_ids=["shape:1", "asset:1", "page:1"],
        instruction="Duplicate the shape",
        canvas_library="tldraw",
    )

    assert isinstance(result, LocalEditResult)
    assert result.operation_type == "add"
    assert set(result.modified_nodes["records"]) == {"shape:1", "shape:2"}
    assert "asset:1" not in llm.prompts[0]
    assert "page:1" not in llm.prompts[0]


def test_parse_response_rejects_wrong_canvas_shape():
    service = LocalEditService(llm=FakeLlm("{}"))

    with pytest.raises(LocalEditResponseError, match="records"):
        service._parse_response('{"elements": []}', "tldraw")


def test_parse_response_rejects_invalid_llm_json_without_echoing_response():
    service = LocalEditService(llm=FakeLlm("{}"))

    with pytest.raises(LocalEditResponseError) as exc_info:
        service._parse_response(
            "provider trace includes secret-token but no JSON",
            "excalidraw",
        )

    assert "valid JSON" in str(exc_info.value)
    assert "secret-token" not in str(exc_info.value)


def test_validate_canvas_library_rejects_unknown_canvas():
    service = LocalEditService(llm=FakeLlm("{}"))

    with pytest.raises(
        LocalEditValidationError,
        match="Unsupported canvas library",
    ) as exc_info:
        service._validate_canvas_library("unknown")

    assert exc_info.value.public_detail == LOCAL_EDIT_UNSUPPORTED_CANVAS_DETAIL


def test_validate_canvas_library_uses_generation_canvas_normalization():
    service = LocalEditService(llm=FakeLlm("{}"))

    assert service._validate_canvas_library(" TLDraw ") == "tldraw"
    assert service._validate_canvas_library(" EXCALIDRAW ") == "excalidraw"


@pytest.mark.asyncio
async def test_edit_local_rejects_a_non_list_elements_field_as_client_error():
    """A malformed client schema is a 400, not an unhandled 500."""
    llm = FakeLlm('{"elements": []}')
    service = LocalEditService(llm=llm)

    with pytest.raises(LocalEditValidationError) as exc_info:
        await service.edit_local(
            current_schema={"elements": {"a": 1}},
            selected_node_ids=["n1"],
            instruction="make it blue",
            canvas_library="excalidraw",
        )

    assert exc_info.value.public_detail == LOCAL_EDIT_INVALID_SCHEMA_DETAIL
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_edit_local_ignores_non_dict_elements_entries():
    llm = FakeLlm('{"elements": [{"id": "n1", "x": 5}]}')
    service = LocalEditService(llm=llm)

    result = await service.edit_local(
        current_schema={"elements": ["not-an-element", {"id": "n1", "x": 0}]},
        selected_node_ids=["n1"],
        instruction="move it",
        canvas_library="excalidraw",
    )

    assert result.modified_nodes["elements"][0]["id"] == "n1"


@pytest.mark.asyncio
async def test_local_edit_rejects_malformed_tldraw_store_before_calling_model():
    llm = FakeLlm('{"records": {}}')
    with pytest.raises(LocalEditValidationError):
        await LocalEditService(llm=llm).edit_local({"store": ["bad"]}, ["a"], "Move", "tldraw")
    assert llm.prompts == []
