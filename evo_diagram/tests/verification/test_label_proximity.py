from copy import deepcopy

from evo_diagram.agentic_system.verification_stage.checks.label_proximity import check_edge_label_proximity


def test_label_distance_uses_own_connector_not_nearby_unrelated_edge():
    manifest = {"elements": [
        {"id": "own", "type": "arrow", "x": 0, "y": 100,
         "points": [[0, 0], [300, 0]], "meta": {"semantic_edge_id": "fact"}},
        {"id": "other", "type": "arrow", "x": 0, "y": 0,
         "points": [[0, 0], [300, 0]]},
        {"id": "label", "type": "text", "x": 80, "y": 8, "width": 100, "height": 16,
         "fontSize": 12, "meta": {"semantic_edge_id": "fact"}},
    ]}
    findings = check_edge_label_proximity(manifest)
    assert len(findings) == 1
    assert findings[0].location["arrow_id"] == "own"
    assert findings[0].location["distance"] == 76
    assert findings[0].severity == "major"

    drifting = deepcopy(manifest)
    drifting["elements"][-1]["y"] = 44
    findings = check_edge_label_proximity(drifting)
    assert findings[0].location["distance"] == 40
    assert findings[0].severity == "minor"

    nearby = deepcopy(manifest)
    nearby["elements"][-1]["y"] = 76
    assert check_edge_label_proximity(nearby) == []

    bound = deepcopy(manifest)
    bound["elements"][-1]["containerId"] = "own"
    assert check_edge_label_proximity(bound) == []

    hidden = deepcopy(manifest)
    hidden["elements"][0]["opacity"] = 0
    assert check_edge_label_proximity(hidden) == []
