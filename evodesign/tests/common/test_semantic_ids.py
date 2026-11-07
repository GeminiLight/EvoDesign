from __future__ import annotations

import pytest

from evodesign.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    companion_base_id,
    companion_id,
    ensure_no_integer_like_semantic_ids,
    group_frame_render_id,
    id_map_from_manifest,
    integer_like_semantic_ids,
    is_integer_like_id,
    resolve_group_id_map,
    reverse_id_map,
    reverse_base_id_map,
    semantic_id_base,
)


def test_companion_id_round_trip():
    semantic_id = companion_id("g_lane", BACKGROUND_SUFFIX)

    assert semantic_id == "g_lane:background"
    assert companion_base_id(semantic_id) == "g_lane"
    assert semantic_id_base(semantic_id) == "g_lane"
    assert semantic_id_base("n_task") == "n_task"


def test_companion_id_rejects_unknown_suffix():
    with pytest.raises(ValueError, match="Unknown semantic companion suffix"):
        companion_id("n_task", ":thumbnail")


def test_id_map_from_manifest_filters_to_string_pairs():
    manifest = {
        "_meta": {
            "id_map": {
                "n1": "shape1",
                "n2": None,
                123: "shape3",
                "n4": 4,
                "n5:icon": "icon5",
            }
        }
    }

    assert id_map_from_manifest(manifest) == {
        "n1": "shape1",
        "n5:icon": "icon5",
    }


def test_group_id_map_resolves_background_and_title_entries():
    resolved = resolve_group_id_map(
        {
            "g_lane:background": "lane-bg",
            "g_lane:title": "lane-title",
            "n1": "shape1",
        }
    )

    assert resolved.background_by_group == {"g_lane": "lane-bg"}
    assert resolved.title_by_group == {"g_lane": "lane-title"}
    assert resolved.background_ids == {"lane-bg"}
    assert resolved.title_ids == {"lane-title"}


def test_group_frame_render_id_prefers_direct_then_background_alias():
    assert group_frame_render_id({"g_lane": "lane-direct"}, "g_lane") == "lane-direct"
    assert (
        group_frame_render_id({"g_lane:background": "lane-bg"}, "g_lane")
        == "lane-bg"
    )
    assert group_frame_render_id({"g_lane": "lane-direct"}, "") is None


def test_reverse_base_id_map_strips_companion_suffixes():
    assert reverse_base_id_map(
        {
            "n1": "shape1",
            companion_id("n1", ICON_SUFFIX): "icon1",
            "g_lane:background": "lane-bg",
        }
    ) == {
        "shape1": "n1",
        "icon1": "n1",
        "lane-bg": "g_lane",
    }


def test_reverse_id_map_preserves_raw_semantic_ids():
    assert reverse_id_map(
        {
            "g_lane:background": "lane-bg",
            "g_lane:title": "lane-title",
        }
    ) == {
        "lane-bg": "g_lane:background",
        "lane-title": "g_lane:title",
    }


# Shared with packages/render-engine/test/parity/integer-ids.test.ts: both
# implementations must classify these ids and word the error identically.
INTEGER_LIKE_CASES = [
    ("0", True), ("7", True), ("42", True), ("4294967294", True),
    ("4294967295", False), ("01", False), ("-1", False), ("1.0", False),
    ("1e3", False), (" 1", False), ("", False), ("n1", False), ("1a", False),
    ("１", False), ("٣", False), (7, False), (None, False),
]


@pytest.mark.parametrize(("value", "expected"), INTEGER_LIKE_CASES)
def test_is_integer_like_id_matches_js_array_index(value, expected):
    assert is_integer_like_id(value) is expected


def test_integer_like_semantic_ids_reports_structure_then_layout_keys():
    structure = {
        "nodes": [{"id": "n_a"}, {"id": "2"}, {"id": "1"}],
        "edges": [{"id": "edge:2to1"}],
        "groups": [{"id": "10"}],
    }
    layout = {"n_a": {}, "2": {}, "1": {}, "10": {}, "3": {}, "2:icon": {}}
    assert integer_like_semantic_ids(structure, layout) == ["2", "1", "10", "3"]
    assert integer_like_semantic_ids(None, None) == []
    with pytest.raises(ValueError) as excinfo:
        ensure_no_integer_like_semantic_ids(structure, layout)
    assert str(excinfo.value) == (
        "Semantic ids must not be bare integers (got '2', '1', '10', '3'); "
        "use descriptive ids such as 'n_login'."
    )
