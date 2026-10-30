from __future__ import annotations

from evo_diagram.agentic_system.generation_stage.layout.prompts import (
    LAYOUT_TASK_PROMPT,
)
from evo_diagram.agentic_system.generation_stage.unified.generator import (
    UNIFIED_TASK_PROMPT,
)
from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
)
from evo_diagram.core.base_agent import _render_template


def test_layout_prompt_uses_runtime_canvas_size_without_legacy_bounds():
    viewport_label = (
        f"{CANVAS_DEFAULT_VIEWPORT_WIDTH} x {CANVAS_DEFAULT_VIEWPORT_HEIGHT}"
    )

    assert viewport_label in LAYOUT_TASK_PROMPT
    assert "3000x2500" not in LAYOUT_TASK_PROMPT
    assert "3000 x 2500" not in LAYOUT_TASK_PROMPT
    assert "3000×2500" not in LAYOUT_TASK_PROMPT


def test_layout_prompt_keeps_template_placeholders_after_f_string_rendering():
    assert "{{size_hints}}" in LAYOUT_TASK_PROMPT
    assert "Start your response with {{ and end with }}" in LAYOUT_TASK_PROMPT

    rendered = _render_template(
        LAYOUT_TASK_PROMPT,
        {"size_hints": "- n1: min 120 x 60"},
    )

    assert "- n1: min 120 x 60" in rendered
    assert "{{size_hints}}" not in rendered
    assert "Start your response with {{ and end with }}" in rendered


def test_unified_prompt_keeps_runtime_canvas_and_template_placeholders():
    viewport_label = (
        f"{CANVAS_DEFAULT_VIEWPORT_WIDTH}x{CANVAS_DEFAULT_VIEWPORT_HEIGHT}"
    )

    assert viewport_label in UNIFIED_TASK_PROMPT
    assert "3000x2500" not in UNIFIED_TASK_PROMPT
    assert "3000 x 2500" not in UNIFIED_TASK_PROMPT
    assert "{{diagram_context}}" in UNIFIED_TASK_PROMPT
    assert "{{stage_knowledge}}" in UNIFIED_TASK_PROMPT
    assert "edge:{{source_id}}2{{target_id}}" in UNIFIED_TASK_PROMPT

    rendered = _render_template(
        UNIFIED_TASK_PROMPT,
        {
            "diagram_context": "DIAGRAM_CONTEXT_SENTINEL",
            "stage_knowledge": "STAGE_KNOWLEDGE_SENTINEL",
            "palette_card": "PALETTE_SENTINEL",
            "design_expertise": "DESIGN_EXPERTISE_SENTINEL",
            "runtime_directives": "RUNTIME_DIRECTIVES_SENTINEL",
            "text_content": "TEXT_SENTINEL",
            "user_query": "QUERY_SENTINEL",
        },
    )

    assert "DIAGRAM_CONTEXT_SENTINEL" in rendered
    assert "STAGE_KNOWLEDGE_SENTINEL" in rendered
    assert "PALETTE_SENTINEL" in rendered
    assert "DESIGN_EXPERTISE_SENTINEL" in rendered
    assert "RUNTIME_DIRECTIVES_SENTINEL" in rendered
    assert "TEXT_SENTINEL" in rendered
    assert "QUERY_SENTINEL" in rendered
    assert "{{diagram_context}}" not in rendered
    assert "edge:{{source_id}}2{{target_id}}" in rendered
