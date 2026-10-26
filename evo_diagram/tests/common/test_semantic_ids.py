from __future__ import annotations

import pytest

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    companion_base_id,
    companion_id,
    group_frame_render_id,
    id_map_from_manifest,
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
