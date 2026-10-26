from __future__ import annotations

from evo_diagram.agentic_system.render_engine.shared.normalization import (
    detect_group_frame_ids,
)
from evo_diagram.agentic_system.render_engine.excalidraw.zorder_repair import repair_zorder


def test_group_frame_detection_uses_title_sibling_id_map_signal():
    elements = [
        {
            "id": "frame1",
            "type": "rectangle",
            "x": 0,
            "y": 0,
            "width": 500,
            "height": 180,
        },
        {
            "id": "child1",
            "type": "rectangle",
            "x": 80,
            "y": 80,
            "width": 160,
            "height": 60,
        },
        {
            "id": "title1",
            "type": "text",
            "x": 20,
            "y": 20,
            "width": 220,
            "height": 32,
            "text": "Service Boundary Layer",
        },
        {
            "id": "child2",
            "type": "rectangle",
            "x": 280,
            "y": 80,
            "width": 160,
            "height": 60,
        },
    ]
    id_map = {
        "service_layer": "frame1",
        "service_layer:title": "title1",
        "service_api": "child1",
        "service_worker": "child2",
    }

    frame_ids = detect_group_frame_ids(elements, structural=True, id_map=id_map)

    assert frame_ids == {"frame1"}
    assert "title1" not in frame_ids


def test_zorder_repair_treats_title_sibling_as_group_frame_signal():
    manifest = {
        "type": "excalidraw",
        "_meta": {
            "id_map": {
                "service_layer": "frame1",
                "service_layer:title": "title1",
                "service_api": "child1",
            }
        },
        "elements": [
            {
                "id": "child1",
                "type": "rectangle",
                "x": 80,
                "y": 80,
                "width": 160,
                "height": 60,
                "index": "a00000",
            },
            {
                "id": "frame1",
                "type": "rectangle",
                "x": 0,
                "y": 0,
                "width": 500,
                "height": 180,
                "index": "a00001",
            },
            {
                "id": "title1",
                "type": "text",
                "x": 20,
                "y": 20,
                "width": 220,
                "height": 32,
                "index": "a00002",
            },
        ],
    }

    repaired = repair_zorder(manifest)

    assert [element["id"] for element in repaired["elements"]] == [
        "frame1",
        "child1",
        "title1",
    ]
    assert [element["index"] for element in repaired["elements"]] == [
        "e00000",
        "e00001",
        "e00002",
    ]


def test_zorder_repair_places_arrows_above_nodes_and_icons_below_text():
    manifest = {
        "type": "excalidraw",
        "elements": [
            {"id": "arrow", "type": "arrow", "index": "a00000"},
            {"id": "text", "type": "text", "index": "a00001"},
            {"id": "icon", "type": "image", "index": "a00002"},
            {
                "id": "node",
                "type": "rectangle",
                "x": 0,
                "y": 0,
                "width": 120,
                "height": 60,
                "index": "a00003",
            },
        ],
    }

    repaired = repair_zorder(manifest)

    assert [element["id"] for element in repaired["elements"]] == [
        "node",
        "icon",
        "arrow",
        "text",
    ]
