from __future__ import annotations

from evo_diagram.core.base_agent import BaseAgent
from evo_diagram.user_memory.extractors.llm_preference_agent import (
    FEW_SHOT_EXAMPLES,
    LLMPreferenceExtractionAgent,
    TASK_PROMPT,
)
from evo_diagram.user_memory.schemas.diff_schemas import GuidedDiff, ShapeAddition, ShapeDeletion
from evo_diagram.user_memory.schemas.observation_schemas import CategoryObservation, VisualObservation


def _observation() -> VisualObservation:
    category = CategoryObservation(
        description="User adjusted structure",
        magnitude="moderate",
        affected_properties=["members"],
    )
    return VisualObservation(
        structural_changes=category,
        styling_changes=category,
        layout_changes=category,
        semantic_changes=category,
        overall_intent="Organize related nodes",
    )


def _agent_without_model() -> LLMPreferenceExtractionAgent:
    agent = object.__new__(LLMPreferenceExtractionAgent)
    agent.min_confidence = 0.7
    return agent


def test_preference_prompt_renders_context_and_few_shot_examples():
    agent = _agent_without_model()
    agent._task_prompt = TASK_PROMPT
    input_dict = {
        "diagram_type": "class",
        "content_area": "Software Engineering",
        "vertical_domain": "backend",
        "user_query": "show auth module",
        "few_shot_examples": FEW_SHOT_EXAMPLES,
        "overall_intent": "Group authentication components",
        "structural_changes_desc": "Added an auth group",
        "structural_magnitude": "moderate",
        "styling_changes_desc": "No styling changes",
        "styling_magnitude": "minor",
        "layout_changes_desc": "No layout changes",
        "layout_magnitude": "minor",
        "changes_formatted": "**Added group:auth:**",
    }

    prompt = BaseAgent._build_prompt(agent, input_dict)["messages"][0]["content"]

    assert "{diagram_type}" not in prompt
    assert "{{diagram_type}}" not in prompt
    assert "**Diagram Type**: class" in prompt
    assert "Example 1: Styling - Entity Color Preference" in prompt
    assert "**Added group:auth:**" in prompt


def test_preference_extraction_processes_addition_only_diff():
    agent = _agent_without_model()
    captured = {}

    def fake_invoke(input_dict):
        captured["input"] = input_dict
        return [
            {
                "preference_text": "User prefers grouping authentication-related nodes into modules",
                "agent_category": "Structure",
                "applies_to": {"diagram_type": "class", "element_type": "group"},
                "confidence": 0.9,
                "design_rationale": "Grouping clarifies module boundaries",
                "evidence_summary": "Added group:auth with authentication nodes",
            }
        ]

    agent.invoke = fake_invoke
    observation = _observation()
    diff = GuidedDiff(
        visual_observation=observation,
        additions=[
            ShapeAddition(
                shape_id="group:auth",
                shape_type="group",
                properties={"members": ["node:login", "node:token"]},
                related_observation="structural",
            )
        ],
    )

    result = agent.extract_preferences(
        visual_observation=observation,
        guided_diff=diff,
        task_context={"diagram_type": "class", "content_area": "Software Engineering"},
    )

    assert result.status == "succeeded"
    assert len(result.preferences) == 1
    assert captured["input"]["few_shot_examples"] == FEW_SHOT_EXAMPLES
    assert "Added group:auth" in captured["input"]["changes_formatted"]
    assert "node:login" in captured["input"]["changes_formatted"]


def test_preference_extraction_processes_deletion_only_diff():
    agent = _agent_without_model()
    captured = {}

    def fake_invoke(input_dict):
        captured["input"] = input_dict
        return []

    agent.invoke = fake_invoke
    observation = _observation()
    diff = GuidedDiff(
        visual_observation=observation,
        deletions=[
            ShapeDeletion(
                shape_id="node:obsolete",
                shape_type="geo",
                properties={"text": "Obsolete"},
                related_observation="structural",
            )
        ],
    )

    result = agent.extract_preferences(
        visual_observation=observation,
        guided_diff=diff,
        task_context={"diagram_type": "class"},
    )

    assert result.status == "no_preferences"
    assert result.preferences == []
    assert "Deleted node:obsolete" in captured["input"]["changes_formatted"]
    assert "Obsolete" in captured["input"]["changes_formatted"]


def test_preference_extraction_reports_failed_status_on_llm_error():
    agent = _agent_without_model()

    def fail_invoke(_input_dict):
        raise RuntimeError("model unavailable")

    agent.invoke = fail_invoke
    observation = _observation()
    diff = GuidedDiff(
        visual_observation=observation,
        additions=[
            ShapeAddition(
                shape_id="group:auth",
                shape_type="group",
                properties={"members": ["node:login"]},
                related_observation="structural",
            )
        ],
    )

    result = agent.extract_preferences(
        visual_observation=observation,
        guided_diff=diff,
        task_context={"diagram_type": "class"},
    )

    assert result.status == "failed"
    assert result.preferences == []
    assert result.errors == ["RuntimeError: model unavailable"]


def test_preference_extraction_reports_failed_status_for_malformed_llm_text():
    agent = _agent_without_model()
    agent.invoke = lambda _input_dict: "I found a preference but not as JSON"
    observation = _observation()
    diff = GuidedDiff(
        visual_observation=observation,
        additions=[
            ShapeAddition(
                shape_id="group:auth",
                shape_type="group",
                properties={"members": ["node:login"]},
                related_observation="structural",
            )
        ],
    )

    result = agent.extract_preferences(
        visual_observation=observation,
        guided_diff=diff,
        task_context={"diagram_type": "class"},
    )

    assert result.status == "failed"
    assert result.preferences == []
    assert "ValueError: LLM output did not contain a JSON preference array" in result.errors


def test_preference_extraction_reports_failed_status_for_unexpected_llm_dict():
    agent = _agent_without_model()
    agent.invoke = lambda _input_dict: {"items": []}
    observation = _observation()
    diff = GuidedDiff(
        visual_observation=observation,
        additions=[
            ShapeAddition(
                shape_id="group:auth",
                shape_type="group",
                properties={"members": ["node:login"]},
                related_observation="structural",
            )
        ],
    )

    result = agent.extract_preferences(
        visual_observation=observation,
        guided_diff=diff,
        task_context={"diagram_type": "class"},
    )

    assert result.status == "failed"
    assert result.preferences == []
    assert "ValueError: LLM output dict must contain a 'preferences' field" in result.errors


def test_preference_extraction_reports_failed_status_when_all_items_are_invalid():
    agent = _agent_without_model()
    agent.invoke = lambda _input_dict: [{"preference_text": "missing required fields"}]
    observation = _observation()
    diff = GuidedDiff(
        visual_observation=observation,
        additions=[
            ShapeAddition(
                shape_id="group:auth",
                shape_type="group",
                properties={"members": ["node:login"]},
                related_observation="structural",
            )
        ],
    )

    result = agent.extract_preferences(
        visual_observation=observation,
        guided_diff=diff,
        task_context={"diagram_type": "class"},
    )

    assert result.status == "failed"
    assert result.preferences == []
    assert result.errors[0].startswith(
        "ValueError: LLM returned preference objects, but none matched the schema"
    )
