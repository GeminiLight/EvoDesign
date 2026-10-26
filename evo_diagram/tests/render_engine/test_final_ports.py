"""Final routes must retain readable, collision-free incoming ports."""

from copy import deepcopy

import pytest

from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    _absolute_arrow_points,
    _path_parallel_channel_penalty,
    _separate_final_channels,
    _spread_final_target_ports,
)


def _incoming_routes():
    # A reroute changed the upper edge onto a face already occupied by a
    # lower edge. The earlier per-face allocation no longer describes them.
    paths = [
        [[240, 76], [192, 76], [192, 326], [160, 326]],
        [[320, 244], [320, 342], [160, 342]],
    ]
    arrows = [
        {"id": f"route-{index}", "type": "arrow", "x": 0, "y": 0,
         "points": points, "meta": {"source": f"source-{index}", "target": "shared"}}
        for index, points in enumerate(paths)
    ]
    contexts = {
        arrow["id"]: {
            "target_ref": "shared", "end_side": "right",
            "target_bbox": {"x": 0, "y": 300, "w": 160, "h": 52},
            "source_bbox": {"x": 240, "y": 50 if index == 0 else 192, "w": 160, "h": 52},
            "obstacles": [],
        }
        for index, arrow in enumerate(arrows)
    }
    return arrows, contexts


@pytest.mark.parametrize("spacing,expected_gap", [(32, 32), (0, 16), (80, 36)])
def test_final_incoming_ports_keep_spacing_inside_compact_node(spacing, expected_gap):
    arrows, contexts = _incoming_routes()
    starts = [_absolute_arrow_points([arrow])[0] for arrow in arrows]
    _spread_final_target_ports(arrows, contexts, spacing)
    paths = [_absolute_arrow_points([arrow]) for arrow in arrows]
    assert [points[0] for points in paths] == starts
    assert paths[1][-1][1] - paths[0][-1][1] == expected_gap
    for points in paths:
        assert points[-1][0] == 160
        assert 308 <= points[-1][1] <= 344
        assert points[-2][0] > points[-1][0]
        assert points[-2][1] == points[-1][1]
        assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:]))


@pytest.mark.parametrize("blocker", ["node", "edge", "direct"])
def test_final_port_spacing_preserves_safe_route_when_adjustment_is_blocked(blocker):
    arrows, contexts = _incoming_routes()
    if blocker == "node":
        contexts["route-0"]["obstacles"] = [(170, 307, 20, 6)]
    elif blocker == "edge":
        arrows.append({"id": "unrelated", "type": "arrow", "x": 0, "y": 0,
                       "points": [[180, 300], [180, 320]],
                       "meta": {"source": "other-source", "target": "other-target"}})
    else:
        arrows[1]["points"] = [[320, 342], [160, 342]]
    before = deepcopy(arrows)
    _spread_final_target_ports(arrows, contexts, 32)
    assert arrows == before


@pytest.mark.parametrize("blocked", [False, True])
def test_final_parallel_channels_separate_only_when_surrounding_space_allows(blocked):
    arrows, contexts = _incoming_routes()
    arrows[0]["points"] = [[240, 76], [192, 76], [192, 310], [160, 310]]
    arrows[1]["points"] = [[240, 218], [200, 218], [200, 342], [160, 342]]
    if blocked:
        for context in contexts.values():
            context["obstacles"] = [(168, 260, 20, 20), (204, 260, 28, 20)]
    before = deepcopy(arrows)
    initial_penalty = _path_parallel_channel_penalty(_absolute_arrow_points([arrows[0]]), arrows[1:])
    assert initial_penalty > 0
    _separate_final_channels(arrows, contexts)
    if blocked:
        assert arrows == before
    else:
        assert _path_parallel_channel_penalty(_absolute_arrow_points([arrows[0]]), arrows[1:]) == 0
        for old, new in zip(before, arrows):
            old_points, new_points = _absolute_arrow_points([old]), _absolute_arrow_points([new])
            assert new_points[0] == old_points[0]
            assert new_points[-1] == old_points[-1]
