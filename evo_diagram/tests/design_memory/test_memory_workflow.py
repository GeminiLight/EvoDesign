from __future__ import annotations

import copy
import json

import pytest

from evo_diagram.design_memory.memory_workflow import (
    TEXT_FIELDS,
    MemoryStorageWorkflow,
    _normalize_knowledge_item,
)


def _workflow() -> MemoryStorageWorkflow:
    return object.__new__(MemoryStorageWorkflow)


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _full_item(**overrides):
    """An item satisfying the KnowledgeEntry write-side contract.

    All four textual fields (title, description, content, when_to_use) are
    required; individual tests override or drop fields from this baseline.
    """
    item = {
        "title": "Use stable lanes",
        "description": "Stable lanes make ownership easy to follow.",
        "content": "Keep related steps in the same lane.",
        "when_to_use": "When drawing swimlane flowcharts.",
    }
    item.update(overrides)
    return item


def test_load_knowledge_items_generates_stable_content_ids(tmp_path):
    first = [
        _full_item(tags={"domain": ["workflow"], "diagram_type": ["flowchart"]}),
        _full_item(
            title="Group ownership",
            description="Ownership is clearer when co-located.",
            content="Put owners close to the assets they control.",
            when_to_use="When diagramming organisational structure.",
            tags={"domain": ["architecture"], "diagram_type": ["class"]},
        ),
    ]
    _write_json(tmp_path / "guideline.json", first)

    first_ids = {
        item["title"]: item["id"]
        for item in _workflow().load_knowledge_items(str(tmp_path))["guideline"]
    }

    _write_json(tmp_path / "guideline.json", list(reversed(first)))
    second_ids = {
        item["title"]: item["id"]
        for item in _workflow().load_knowledge_items(str(tmp_path))["guideline"]
    }

    assert first_ids == second_ids
    assert all(item_id.startswith("guideline_") for item_id in first_ids.values())
    assert len(set(first_ids.values())) == 2


def test_generated_id_ignores_tag_list_order():
    item_a = _full_item(tags={"domain": ["workflow", "operations"]})
    item_b = _full_item(tags={"domain": ["operations", "workflow"]})

    normalized_a = _normalize_knowledge_item(
        item_a,
        design_type="guideline",
        source_file="guideline.json",
        index=0,
    )
    normalized_b = _normalize_knowledge_item(
        item_b,
        design_type="guideline",
        source_file="guideline.json",
        index=0,
    )

    assert normalized_a["id"] == normalized_b["id"]


def test_normalize_knowledge_item_does_not_mutate_raw_item():
    raw_item = _full_item()
    original = copy.deepcopy(raw_item)

    normalized = _normalize_knowledge_item(
        raw_item,
        design_type="guideline",
        source_file="guideline.json",
        index=0,
    )

    assert raw_item == original
    assert normalized["id"].startswith("guideline_")
    assert normalized["tags"] == {}
    assert normalized["design_type"] == "guideline"


def test_load_knowledge_items_rejects_mismatched_design_type(tmp_path):
    _write_json(
        tmp_path / "guideline.json",
        [_full_item(id="g1", design_type="strategy")],
    )

    with pytest.raises(ValueError, match="does not match file layer 'guideline'"):
        _workflow().load_knowledge_items(str(tmp_path))


def test_load_knowledge_items_rejects_non_object_items(tmp_path):
    _write_json(
        tmp_path / "guideline.json",
        [_full_item(), "bad"],
    )

    with pytest.raises(ValueError, match="guideline item 1: expected object"):
        _workflow().load_knowledge_items(str(tmp_path))


@pytest.mark.parametrize(
    "tags",
    [
        ["workflow"],
        {"domain": "workflow"},
        {"domain": ["workflow", 3]},
        {"custom": {"nested": "value"}},
    ],
)
def test_load_knowledge_items_rejects_invalid_tags_schema(tmp_path, tags):
    _write_json(tmp_path / "guideline.json", [_full_item(tags=tags)])

    with pytest.raises(ValueError, match="tags"):
        _workflow().load_knowledge_items(str(tmp_path))


# ── KnowledgeEntry write-side contract: all four text fields required ────


@pytest.mark.parametrize("missing_field", TEXT_FIELDS)
def test_normalize_rejects_item_missing_any_required_field(missing_field):
    """Three of four fields present is still rejected, naming the missing one."""
    item = _full_item(id="g1")
    del item[missing_field]

    with pytest.raises(ValueError) as exc_info:
        _normalize_knowledge_item(
            item,
            design_type="guideline",
            source_file="guideline.json",
            index=0,
        )

    message = str(exc_info.value)
    assert missing_field in message
    assert "guideline item 0" in message


@pytest.mark.parametrize("missing_field", TEXT_FIELDS)
def test_normalize_rejects_blank_required_field(missing_field):
    item = _full_item(id="g1", **{missing_field: "   "})

    with pytest.raises(ValueError) as exc_info:
        _normalize_knowledge_item(
            item,
            design_type="guideline",
            source_file="guideline.json",
            index=0,
        )

    assert missing_field in str(exc_info.value)


def test_normalize_error_identifies_source_item_id_and_title():
    """The error must point at the offending item, not just the file."""
    item = _full_item(id="g-42", title="Compact grouping")
    del item["when_to_use"]

    with pytest.raises(ValueError) as exc_info:
        _normalize_knowledge_item(
            item,
            design_type="guideline",
            source_file="guideline.json",
            index=3,
        )

    message = str(exc_info.value)
    assert "'g-42'" in message
    assert "Compact grouping" in message
    assert "when_to_use" in message
    assert "guideline.json guideline item 3" in message


def test_normalize_error_lists_every_missing_field_at_once():
    with pytest.raises(ValueError) as exc_info:
        _normalize_knowledge_item(
            {"title": "Only a title"},
            design_type="strategy",
            source_file="strategy.json",
            index=0,
        )

    message = str(exc_info.value)
    for field in ("description", "content", "when_to_use"):
        assert field in message


def test_load_knowledge_items_rejects_item_without_all_textual_fields(tmp_path):
    """Corpus-level check: one incomplete item fails the whole load (fail-fast)."""
    _write_json(
        tmp_path / "guideline.json",
        [
            _full_item(id="g1"),
            {
                "id": "g2",
                "title": "Incomplete guideline",
                "content": "Missing description and when_to_use.",
            },
        ],
    )

    with pytest.raises(ValueError) as exc_info:
        _workflow().load_knowledge_items(str(tmp_path))

    message = str(exc_info.value)
    assert "guideline item 1" in message
    assert "'g2'" in message
    assert "Incomplete guideline" in message
    assert "description" in message
    assert "when_to_use" in message


def test_load_knowledge_items_rejects_duplicate_ids_before_storage(tmp_path):
    _write_json(
        tmp_path / "guideline.json",
        [
            _full_item(id="g1"),
            _full_item(
                id="g1",
                title="Use stable lanes again",
                description="Duplicate id must be rejected.",
                content="Keep related steps in the same lane again.",
                when_to_use="When drawing swimlane flowcharts again.",
            ),
        ],
    )

    with pytest.raises(ValueError, match="duplicate id 'g1'"):
        _workflow().load_knowledge_items(str(tmp_path))
