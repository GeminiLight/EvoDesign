"""The rubric must not name a specific rendering technology.

Naming one turns a quality judgement into a technology penalty: a diagram is
capped because of the tool that produced it rather than because of an observable
property of the image. The caps themselves stay; only the trigger must be
something any renderer can hit.
"""

from __future__ import annotations

import re

import pytest

from evaluation.prompts.metric_prompts_merged import (
    METRIC_PROMPTS,
    get_prompt,
)


# Renderers and diagram tools that appear in this project's methods or baselines.
FORBIDDEN_TECHNOLOGY_NAMES = [
    "mermaid",
    "excalidraw",
    "tldraw",
    "graphviz",
    "plantuml",
    "tikz",
    "d2",
    "matplotlib",
]


@pytest.mark.parametrize("metric_name", sorted(METRIC_PROMPTS))
@pytest.mark.parametrize("technology", FORBIDDEN_TECHNOLOGY_NAMES)
def test_prompts_do_not_name_a_rendering_technology(metric_name, technology):
    prompt = METRIC_PROMPTS[metric_name]
    pattern = re.compile(rf"\b{re.escape(technology)}\b", re.IGNORECASE)

    assert not pattern.search(prompt), (
        f"{metric_name} prompt names the renderer {technology!r}; scoring caps "
        f"must be triggered by observable image properties instead"
    )


@pytest.mark.parametrize("metric_name", sorted(METRIC_PROMPTS))
def test_prompts_still_format_with_context(metric_name):
    rendered = get_prompt(metric_name, context="SOURCE TEXT")

    assert "SOURCE TEXT" in rendered
    assert '"score"' in rendered
    assert "{context}" not in rendered


@pytest.mark.parametrize(
    "expected_cap",
    [
        "styling-related scores must be at most 2",
        "content_dimension must be at most 3",
        "visual_aesthetics and styling_fitness must be at most 2",
        "score 1-2 on cognitive_ease",
    ],
)
def test_quality_caps_are_preserved(expected_cap):
    """Neutralising the trigger must not silently remove the penalty."""
    joined = "\n".join(METRIC_PROMPTS.values())

    assert expected_cap in joined
