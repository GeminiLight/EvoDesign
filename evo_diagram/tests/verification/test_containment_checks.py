from evo_diagram.agentic_system.verification_stage.checks.containment import (
    check_group_bbox_contains_children,
    check_swimlane_lane_membership,
)


def _element(element_id, *, x, y, width, height, element_type="rectangle"):
    return {
        "id": element_id,
        "type": element_type,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def test_group_bbox_check_reports_child_bbox_escape():
    manifest = {
        "_meta": {"id_map": {"g1:background": "g1_bg", "node1": "n1"}},
        "elements": [
            _element("g1_bg", x=0, y=0, width=100, height=100),
            _element("n1", x=80, y=80, width=40, height=40),
        ],
    }

    findings = check_group_bbox_contains_children(
        manifest,
        {"chart_type": "flowchart"},
    )

    assert len(findings) == 1
    assert findings[0].category == "containment/group_bbox"
    assert findings[0].element_id == "n1"
    assert findings[0].location["group_id"] == "g1"


def test_group_bbox_check_resolves_direct_group_frame_mapping():
    manifest = {
        "_meta": {"id_map": {"g1": "g1_bg", "node1": "n1"}},
        "elements": [
            _element("g1_bg", x=0, y=0, width=100, height=100),
            _element("n1", x=80, y=80, width=40, height=40),
        ],
    }

    findings = check_group_bbox_contains_children(
        manifest,
        {
            "chart_type": "flowchart",
            "groups": [{"id": "g1", "members": ["node1"]}],
        },
    )

    assert len(findings) == 1
    assert findings[0].location["group_id"] == "g1"


def test_group_bbox_check_ignores_deleted_group_background_and_child():
    deleted_background_manifest = {
        "_meta": {"id_map": {"g1:background": "g1_bg", "node1": "n1"}},
        "elements": [
            {
                **_element("g1_bg", x=0, y=0, width=100, height=100),
                "isDeleted": True,
            },
            _element("n1", x=80, y=80, width=40, height=40),
        ],
    }
    deleted_child_manifest = {
        "_meta": {"id_map": {"g1:background": "g1_bg", "node1": "n1"}},
        "elements": [
            _element("g1_bg", x=0, y=0, width=100, height=100),
            {
                **_element("n1", x=80, y=80, width=40, height=40),
                "isDeleted": True,
            },
        ],
    }

    assert check_group_bbox_contains_children(
        deleted_background_manifest,
        {"chart_type": "flowchart"},
    ) == []
    assert check_group_bbox_contains_children(
        deleted_child_manifest,
        {"chart_type": "flowchart"},
    ) == []


def test_swimlane_check_reports_node_escaped_all_lanes():
    manifest = {
        "_meta": {"id_map": {"lane1:background": "lane1_bg", "node1": "n1"}},
        "elements": [
            _element("lane1_bg", x=0, y=0, width=300, height=100),
            _element("n1", x=40, y=150, width=80, height=30),
        ],
    }

    findings = check_swimlane_lane_membership(
        manifest,
        {"chart_type": "swimlane"},
    )

    assert len(findings) == 1
    assert findings[0].category == "containment/swimlane_lane"
    assert "escaped the lane system" in findings[0].message


def test_swimlane_explicit_membership_overrides_centroid_assignment():
    manifest = {
        "_meta": {
            "id_map": {
                "lane1:background": "lane1_bg",
                "lane2:background": "lane2_bg",
                "node1": "n1",
            }
        },
        "elements": [
            _element("lane1_bg", x=0, y=0, width=300, height=100),
            _element("lane2_bg", x=0, y=100, width=300, height=100),
            _element("n1", x=40, y=120, width=80, height=40),
        ],
    }
    structure = {
        "chart_type": "swimlane",
        "groups": [
            {"id": "lane1", "members": ["node1"]},
            {"id": "lane2", "members": []},
        ],
    }

    findings = check_swimlane_lane_membership(manifest, structure)

    assert len(findings) == 1
    assert findings[0].category == "containment/swimlane_lane"
    assert findings[0].location["lane_id"] == "lane1"
def test_concept_branch_membership_survives_moving_frame_to_another_branch():
    from evo_diagram.agentic_system.verification_stage.checks.containment import (
        check_group_bbox_contains_children,
    )

    structure = {"chart_type": "concept_map", "nodes": [
        {"id": "theory", "class": "branch_anchor", "branch_id": "theory"},
        {"id": "practice", "class": "branch_anchor", "branch_id": "practice"},
        {"id": "model", "class": "concept", "branch_id": "theory"},
    ]}
    manifest = {"_meta": {"id_map": {
        "theory:background": "frame1", "practice:background": "frame2", "model": "m",
    }}, "elements": [
        {"id": "frame1", "type": "rectangle", "x": 0, "y": 200, "width": 200, "height": 100},
        {"id": "frame2", "type": "rectangle", "x": 0, "y": 0, "width": 200, "height": 100},
        {"id": "m", "type": "rectangle", "x": 30, "y": 20, "width": 100, "height": 50},
    ]}
    findings = check_group_bbox_contains_children(manifest, structure)
    assert len(findings) == 1
    assert findings[0].element_id == "m"
    assert findings[0].location["group_id"] == "theory"
