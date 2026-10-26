from __future__ import annotations

import re

import pytest

from evo_diagram.agentic_system.common.domain_knowledge_loader import (
    build_stage_knowledge,
)
from evo_diagram.agentic_system.generation_stage.layout.prompts import (
    LAYOUT_TASK_PROMPT,
)
from evo_diagram.agentic_system.generation_stage.structure.prompts import (
    STRUCTURE_TASK_PROMPT,
)
from evo_diagram.agentic_system.generation_stage.styling.prompts import (
    STYLING_TASK_PROMPT,
    build_styling_task_prompt,
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
    assert "{{viewport_plan}}" in LAYOUT_TASK_PROMPT
    assert "Preferred logical viewport" not in LAYOUT_TASK_PROMPT
    assert "3000x2500" not in LAYOUT_TASK_PROMPT
    assert "3000 x 2500" not in LAYOUT_TASK_PROMPT
    assert "3000×2500" not in LAYOUT_TASK_PROMPT


# Same pattern ``evo_diagram.core.base_agent._render_template`` uses to find
# placeholders. Anything shaped like ``{{identifier}}`` is a template slot; every
# other ``{{`` in a prompt is a literal double brace that reaches the model.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")


def _literal_double_braces(text: str) -> int:
    """Count ``{{`` runs that are not template placeholders."""
    return _PLACEHOLDER_RE.sub("", text).count("{{")


def test_layout_prompt_keeps_template_placeholders_after_f_string_rendering():
    # The f-string must still emit the real placeholder for the renderer...
    assert "{{size_hints}}" in LAYOUT_TASK_PROMPT
    # ...but must not emit literal double braces anywhere else. The JSON
    # instruction has to ask for `{`/`}`, not `{{`/`}}`: the stage agents run with
    # strict_json_output=True, so a response wrapped in double braces is not
    # parseable JSON and burns every retry before raising.
    assert "Start your response with { and end with }" in LAYOUT_TASK_PROMPT
    assert "Start your response with {{ and end with }}" not in LAYOUT_TASK_PROMPT

    rendered = _render_template(
        LAYOUT_TASK_PROMPT,
        {
            "size_hints": "- n1: min 120 x 60",
            "viewport_plan": "Preferred logical viewport: 1200 x 800",
        },
    )

    assert "- n1: min 120 x 60" in rendered
    assert "{{size_hints}}" not in rendered
    assert "Preferred logical viewport: 1200 x 800" in rendered
    assert "{{viewport_plan}}" not in rendered
    assert "Start your response with { and end with }" in rendered
    # Remaining ``{{...}}`` may only be unsupplied template slots, never literals.
    assert _literal_double_braces(rendered) == 0


@pytest.mark.parametrize(
    ("prompt_name", "prompt"),
    [
        ("STRUCTURE_TASK_PROMPT", STRUCTURE_TASK_PROMPT),
        ("STYLING_TASK_PROMPT", STYLING_TASK_PROMPT),
        ("LAYOUT_TASK_PROMPT", LAYOUT_TASK_PROMPT),
    ],
)
def test_stage_prompts_have_no_literal_double_braces(prompt_name, prompt):
    """No stage prompt may ship literal ``{{`` to the model.

    Nothing calls ``str.format`` on these prompts, so doubling a brace is never
    an escape — it is shipped verbatim and teaches the model to emit invalid
    JSON. Only ``{{identifier}}`` template slots are allowed.
    """
    assert _literal_double_braces(prompt) == 0, prompt_name


@pytest.mark.parametrize("canvas_library", ["excalidraw", "tldraw"])
def test_styling_contracts_have_no_literal_double_braces(canvas_library):
    prompt = build_styling_task_prompt(
        use_icons=True,
        canvas_library=canvas_library,
    )

    assert _literal_double_braces(prompt) == 0
    # The JSON examples still have to be brace-balanced after de-escaping.
    stripped = _PLACEHOLDER_RE.sub("", prompt)
    assert stripped.count("{") == stripped.count("}")


def test_stage_prompt_placeholders_all_resolve():
    """Every placeholder a stage prompt declares must be substitutable."""
    values = {
        "stage_knowledge": "SK",
        "design_expertise": "DE",
        "runtime_directives": "RD",
        "text_content": "TC",
        "user_query": "UQ",
        "content_area": "CA",
        "size_hints": "SH",
        "viewport_plan": "VP",
        "selected_palette": "SP",
    }

    for prompt in (STRUCTURE_TASK_PROMPT, STYLING_TASK_PROMPT, LAYOUT_TASK_PROMPT):
        rendered = _render_template(prompt, values)
        leftover = sorted(set(_PLACEHOLDER_RE.findall(rendered)))
        assert leftover == [], leftover


# The canonical edge id format every stage must demonstrate identically.
# ``{source_id}`` / ``{target_id}`` are prose metavariables, never template
# slots: they are not in any variables dict, so ``_render_template`` returns a
# doubled form unchanged and the model is shown ``edge:{{source_id}}2{{...}}``
# — a different id format from the one the Structure contract teaches.
_EDGE_ID_FORMAT = "edge:{source_id}2{target_id}"
_DOUBLED_EDGE_ID_FORMAT = "edge:{{source_id}}2{{target_id}}"


@pytest.mark.parametrize(
    ("prompt_name", "prompt"),
    [
        ("STRUCTURE_TASK_PROMPT", STRUCTURE_TASK_PROMPT),
        ("LAYOUT_TASK_PROMPT", LAYOUT_TASK_PROMPT),
        ("UNIFIED_TASK_PROMPT", UNIFIED_TASK_PROMPT),
    ],
)
def test_prompts_demonstrate_one_consistent_edge_id_format(prompt_name, prompt):
    """Structure, Layout and the one-shot prompt must teach the same id format."""
    assert _EDGE_ID_FORMAT in prompt, prompt_name
    assert _DOUBLED_EDGE_ID_FORMAT not in prompt, prompt_name


def test_unified_prompt_keeps_runtime_canvas_and_template_placeholders():
    viewport_label = (
        f"{CANVAS_DEFAULT_VIEWPORT_WIDTH}x{CANVAS_DEFAULT_VIEWPORT_HEIGHT}"
    )

    assert viewport_label in UNIFIED_TASK_PROMPT
    assert "3000x2500" not in UNIFIED_TASK_PROMPT
    assert "3000 x 2500" not in UNIFIED_TASK_PROMPT
    assert "{{diagram_context}}" in UNIFIED_TASK_PROMPT
    assert "{{stage_knowledge}}" in UNIFIED_TASK_PROMPT
    assert "edge:{source_id}2{target_id}" in UNIFIED_TASK_PROMPT
    assert "compact `1200x800`" in UNIFIED_TASK_PROMPT
    assert "wide `1600x900`" in UNIFIED_TASK_PROMPT
    assert "large `2400x1600`" in UNIFIED_TASK_PROMPT
    assert "<canvas hex from PALETTE>" in UNIFIED_TASK_PROMPT
    assert "#a5d8ff" not in UNIFIED_TASK_PROMPT

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
    # Every declared slot resolves; nothing placeholder-shaped survives.
    assert _PLACEHOLDER_RE.findall(rendered) == []
    assert _literal_double_braces(rendered) == 0


def test_concept_map_contract_budgets_space_and_color_by_semantic_branch():
    structure_knowledge = build_stage_knowledge("concept_map", "structure")
    layout_knowledge = build_stage_knowledge("concept_map", "layout")
    styling_knowledge = build_stage_knowledge("concept_map", "styling")

    assert "core_concept -> branch_anchor" in structure_knowledge
    assert "ownership is already encoded by `branch_id`" in structure_knowledge
    assert "anchor-to-descendant edge" in structure_knowledge
    assert "source-explicit `core_concept -> descendant` fact" in structure_knowledge
    assert "no ownership-only descendant edges" in structure_knowledge
    assert "two or more sibling" in structure_knowledge
    assert "not invent broad" in structure_knowledge
    assert "shortest source-faithful noun phrase" in structure_knowledge
    assert "must use the concise label `organized into`" in structure_knowledge
    assert "Healthcare Applications" not in structure_knowledge
    assert "AI Infrastructure" not in structure_knowledge
    assert "node count + 0.5 * internal edge count" in layout_knowledge
    assert "unequal branches" in layout_knowledge
    assert "equal quadrants" in layout_knowledge
    assert "one coherent rounded-rectangle family" in styling_knowledge
    assert "one distinct palette family" in styling_knowledge
    assert "descendant inherits its branch family's fill/stroke pair" in styling_knowledge.lower()
    assert "do not switch hue by leaf-node class" in styling_knowledge


def test_styling_prompt_uses_compact_role_driven_typography():
    assert "group titles 18-20" in STYLING_TASK_PROMPT
    assert "ordinary node labels 16-18" in STYLING_TASK_PROMPT
    assert "edge labels 12-13" in STYLING_TASK_PROMPT
    assert "lineHeight 1.15-1.25" in STYLING_TASK_PROMPT
    assert "at most two text sizes inside a local group" in STYLING_TASK_PROMPT


def test_structure_prompt_requires_source_grounded_relation_triples():
    assert "Source-Faithful, Diagram-Type-Aware Extraction" in STRUCTURE_TASK_PROMPT
    assert "source-grounded triple" in STRUCTURE_TASK_PROMPT
    assert "evidence_basis" in STRUCTURE_TASK_PROMPT
    assert "Plausible world knowledge" in STRUCTURE_TASK_PROMPT
    assert "MUST NOT" in STRUCTURE_TASK_PROMPT
    assert "never licenses changing, strengthening, reversing" in STRUCTURE_TASK_PROMPT
    assert "`fact_ledger`" in STRUCTURE_TASK_PROMPT
    assert "`organizer_ledger`" in STRUCTURE_TASK_PROMPT
    assert "maps to exactly one instantiation edge" in STRUCTURE_TASK_PROMPT
    assert '"Correctly extracted from text" is irrelevant' not in STRUCTURE_TASK_PROMPT


def test_concept_map_contract_defines_relation_direction_and_strength():
    structure_knowledge = build_stage_knowledge("concept_map", "structure")

    assert "subject-predicate-object triple" in structure_knowledge
    assert "relation_type" in structure_knowledge
    assert "category -> example, `has example`" in structure_knowledge
    assert "dependent -> prerequisite, `depends on`" in structure_knowledge
    assert "do not strengthen weak" in structure_knowledge
    assert "does not establish relationships" in structure_knowledge
    assert "among the listed siblings" in structure_knowledge
    assert "prefer one edge from" in structure_knowledge
    assert "source-explicit intermediate categories" in structure_knowledge
    assert "`contributes to transforming`" in structure_knowledge
