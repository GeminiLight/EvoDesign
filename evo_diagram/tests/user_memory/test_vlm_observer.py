from __future__ import annotations

import json

import pytest

from evo_diagram.user_memory.extractors.vlm_observer import VLMImageObserver


def _observer_without_model() -> VLMImageObserver:
    return object.__new__(VLMImageObserver)


def _valid_payload() -> dict:
    category = {
        "description": "User adjusted spacing",
        "magnitude": "moderate",
        "affected_properties": ["x", "y"],
    }
    return {
        "structural_changes": category,
        "styling_changes": category,
        "layout_changes": category,
        "semantic_changes": category,
        "overall_intent": "Improve readability",
    }


def test_vlm_observer_parses_valid_json_response():
    observation = _observer_without_model()._parse_vlm_response(
        json.dumps(_valid_payload())
    )

    assert observation.overall_intent == "Improve readability"
    assert observation.layout_changes.magnitude == "moderate"


def test_vlm_observer_rejects_non_json_response():
    with pytest.raises(ValueError, match="Failed to parse VLM response as JSON"):
        _observer_without_model()._parse_vlm_response("not valid json")


def test_vlm_observer_rejects_schema_invalid_response():
    payload = _valid_payload()
    payload["layout_changes"] = {
        "description": "Invalid magnitude",
        "magnitude": "unknown",
        "affected_properties": [],
    }

    with pytest.raises(ValueError, match="Failed to create VisualObservation"):
        _observer_without_model()._parse_vlm_response(json.dumps(payload))


def test_vlm_observer_requires_overall_intent():
    payload = _valid_payload()
    del payload["overall_intent"]

    with pytest.raises(ValueError, match="Failed to create VisualObservation"):
        _observer_without_model()._parse_vlm_response(json.dumps(payload))

    payload["overall_intent"] = " "
    with pytest.raises(ValueError, match="Failed to create VisualObservation"):
        _observer_without_model()._parse_vlm_response(json.dumps(payload))
