"""UnifiedGenerator — single LLM call that emits a full Excalidraw scene.

Context: the 3-stage pipeline has a strong methodology but pays 3x input
tokens (each stage re-reads the 50K skill system prompt) and is vulnerable to
format drift between stages. This agent is the experimental alternative: one
LLM call, the same skill system prompt, but a single task prompt asking for
the final Excalidraw clipboard JSON directly.

The LLM still performs the three-phase diagnostic internally; we just skip
the serialisation round-trip between stages. Deterministic post-processors
(group fitter, validator) still run afterwards — they work on the native
Excalidraw schema so they don't care which stage produced the elements.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.agentic_system.common.skill_loader import EVODIAGRAM_SKILL_SYSTEM_PROMPT
from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
)
from evo_diagram.core.base_agent import BaseAgent
from .sidecar import validate_semantic_sidecar
from .state import UnifiedWorkflowState


_REQUIRED_TOP_LEVEL_KEYS = {"type", "elements", "files", "appState", "_meta"}

logger = logging.getLogger(__name__)

_CANVAS_VIEWPORT_LABEL = (
    f"{CANVAS_DEFAULT_VIEWPORT_WIDTH}x{CANVAS_DEFAULT_VIEWPORT_HEIGHT}"
)

UNIFIED_TASK_PROMPT = f"""
### CURRENT TASK: One-shot Diagram Generation (Unified mode) ###

Apply ALL three phases from the methodology in your system prompt as internal
thinking before writing JSON:
  Phase 1 — Structural Diagnosis (family, organizer, entities, edges w/ Visual
             Necessity Filter, calibration anchor)
  Phase 2 — Visual System Design (recognition anchor, shape language, colour
             system, typography, role hierarchy)
  Phase 3 — Layout Composition ({_CANVAS_VIEWPORT_LABEL} canvas, organizer-first placement,
             derive group bounds from children, self-audit)

Then output a single Excalidraw clipboard JSON object plus a semantic sidecar.
Do NOT emit any "specification" / "instantiation" wrapper — go straight to
the scene envelope below.

### OUTPUT FORMAT (strict) ###
Return EXACTLY this top-level shape (keys in any order, no extra keys):
{{
  "type": "excalidraw/clipboard",
  "elements": [ ... ],
  "files": {{}},
  "appState": {{"viewBackgroundColor": "#ffffff", "gridSize": null}},
  "_meta": {{
    "structure_instantiation": {{
      "chart_type": "<canonical diagram_type>",
      "nodes": [
        {{"id": "n_semantic_id", "label": "Node label", "class": "semantic role"}}
      ],
      "edges": [
        {{"id": "edge:n_source2n_target", "source": "n_source", "target": "n_target"}}
      ],
      "groups": []
    }},
    "id_map": {{
      "n_semantic_id": "<matching Excalidraw element id>",
      "edge:n_source2n_target": "<matching arrow element id>"
    }}
  }}
}}

### ELEMENT CONTRACT ###
Every element MUST include these common fields:
  id (unique string), type, x, y, width, height, angle,
  strokeColor, backgroundColor, fillStyle, strokeWidth, strokeStyle,
  roughness, opacity, groupIds (array), boundElements (array or null),
  frameId (null), index (string like "a0","a1"...), roundness (object or null),
  seed (int), version (int), versionNonce (int),
  isDeleted (false), link (null), locked (false).

Type-specific additions:
- rectangle / ellipse / diamond: use `roundness: {{"type": 3}}` for rounded rects,
  `null` for sharp corners.
- text: text, originalText (same as text), fontSize (16-24 typical),
  fontFamily (2 = Helvetica — default), textAlign ("left"|"center"|"right"),
  verticalAlign ("top"|"middle"|"bottom"), containerId (string or null),
  autoResize (true), lineHeight (1.25).
- arrow: points (array of `[dx, dy]` relative to x/y; first point is [0,0]),
  startBinding ({{"elementId":"...","focus":0,"gap":5}} or null),
  endBinding (same shape or null),
  startArrowhead (null|"arrow"|"dot"), endArrowhead (null|"arrow"|"dot"),
  elbowed (bool).
- arrow elements MUST include `meta.semantic_edge_id` matching an edge id from
  `_meta.structure_instantiation.edges[*].id`.

### SEMANTIC SIDECAR CONTRACT ###
`_meta.structure_instantiation` uses the exact same semantic graph contract as
the multiagent Structure stage:
- canonical `chart_type` from the supported diagram type registry
- every node has `id`, `label`, and `class`
- every edge has `id`, `source`, and `target`, with id format
  `edge:{{{{source_id}}}}2{{{{target_id}}}}`
- every edge endpoint references an existing node
- type-specific fields are mandatory when applicable (for example
  `parent_id` for mindmap/tree/orgchart, `row`/`col` for matrix,
  `actor_id`/`sequence_idx` for sequence diagrams, `start_ts`/`end_ts` for gantt)

`_meta.id_map` maps every semantic node id and edge id to its Excalidraw
element id. Semantic groups may map either the group id itself or the
`<group_id>:background` companion id to the rendered group frame. Additional
companion keys are allowed only for real semantic bases:
`<node_or_group_or_edge_id>:title`, `:label`, `:icon`, or `:background`.
If a semantic edge is rendered as an arrow, the arrow's `meta.semantic_edge_id`
MUST equal that semantic edge id. This sidecar is not optional: verifier and
render audit use it to prove semantic coverage.

### BINDING / GROUP INVARIANTS ###
1. Every element's `id` MUST be unique across the scene.
2. Every `seed` and `versionNonce` SHOULD be unique (use large random ints).
3. If an arrow binds to a shape, the shape's `boundElements` MUST contain
   `{{"id": "<arrow-id>", "type": "arrow"}}`. Bidirectional consistency is a
   hard requirement — missing one side corrupts rendering.
4. If a text element has `containerId` set, the container's `boundElements`
   MUST include `{{"id": "<text-id>", "type": "text"}}`. Standalone group
   titles use `containerId: null` and live outside their group's bounds so
   they render above the container.
5. Related elements (lane background + title + children) share the same
   `groupIds` array (e.g. `["group-marketing"]`). Group membership implies
   belonging — do NOT draw arrows just to signal containment.
6. Use the Excalidraw colour palette (backgrounds: #a5d8ff, #b2f2bb, #ffec99,
   #ffc9c9, #e9ecef, #d0bfff, #99e9f2; strokes: #1e1e1e, #1971c2, #2f9e44,
   #f08c00, #e03131, #9c36b5). Pair light backgrounds with matching strokes.

### ZERO-BLOAT DISCIPLINE ###
- Apply the Visual Necessity Filter to every edge before adding it.
- Relationships implied by group membership, layer containment, or spatial
  proximity MUST NOT become arrows.
- No ghost nodes, no empty containers, no redundant edges.

### DIAGRAM CONTEXT ###
{{{{diagram_context}}}}

### DOMAIN KNOWLEDGE (all stages) ###
{{{{stage_knowledge}}}}

### PALETTE ###
{{{{palette_card}}}}

### DESIGN EXPERTISE ###
{{{{design_expertise}}}}

### RUNTIME DIRECTIVES ###
{{{{runtime_directives}}}}

### INPUTS ###
text_content:
{{{{text_content}}}}

user_query:
{{{{user_query}}}}

Return ONLY the JSON object. No markdown fences, no prose, no specification
wrapper.
""".strip()


class UnifiedGenerator(BaseAgent):
    """One-shot Excalidraw generator. Skips the structure/styling/layout split.

    Inputs: ``text_content``, ``user_query``, optional ``design_expertise`` and
    ``runtime_directives``.
    Output: a complete Excalidraw clipboard dict assigned to
    ``state.diagram_manifest``.
    """

    def __init__(
        self,
        model: BaseChatModel,
        tools: Optional[List[Any]] = None,
        full_domain_knowledge: bool = True,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("strict_json_output", True)
        super().__init__(
            model=model,
            tools=tools,
            system_prompt=EVODIAGRAM_SKILL_SYSTEM_PROMPT,
            task_prompt=UNIFIED_TASK_PROMPT,
            **kwargs,
        )
        self.full_domain_knowledge = full_domain_knowledge

    def run(self, state: UnifiedWorkflowState) -> UnifiedWorkflowState:
        # Build type knowledge if diagram_type is available (Router output or
        # caller-provided).  When absent the LLM must infer from text alone.
        diagram_type = state.diagram_type or ""
        from evo_diagram.agentic_system.common.domain_knowledge_loader import (
            build_diagram_context,
            build_stage_knowledge,
        )
        diagram_context = build_diagram_context(diagram_type) if diagram_type else ""
        # Unified mode sees ALL stage rules since a single LLM call must do
        # structure + styling + layout internally. Respect the config toggle
        # so A/B experiments can compare full vs stage-specific knowledge.
        stage_knowledge = build_stage_knowledge(
            diagram_type, stage=None, full_mode=self.full_domain_knowledge
        )

        # Palette card
        palette_card = ""
        if state.palette_key:
            from evo_diagram.agentic_system.common.domain_knowledge_loader import get_selected_palette
            palette_card = get_selected_palette(state.palette_key)
            if not palette_card:
                raise ValueError(f"Unknown palette_key: {state.palette_key!r}")

        input_dict = {
            "text_content": state.text_content or "",
            "user_query": state.user_query or "",
            "diagram_context": diagram_context or "N/A",
            "stage_knowledge": stage_knowledge or "N/A",
            "palette_card": palette_card or "N/A",
            "design_expertise": state.design_expertise or "N/A",
            "runtime_directives": state.runtime_directives or "N/A",
        }
        logger.info("[UnifiedGenerator] Invoking LLM (single-shot)...")
        raw_output = self.invoke(input_dict)

        # Capture the last raw LLM output string for debugging / token audit.
        if hasattr(self, "_last_raw_output") and self._last_raw_output is not None:
            state.raw_llm_output = str(self._last_raw_output)

        if not isinstance(raw_output, dict):
            raise ValueError(
                f"UnifiedGenerator expected a dict from LLM; got {type(raw_output).__name__}"
            )

        top_level_keys = set(raw_output)
        missing_keys = _REQUIRED_TOP_LEVEL_KEYS - top_level_keys
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise ValueError(
                f"UnifiedGenerator output missing required top-level key(s): {missing}"
            )
        extra_keys = top_level_keys - _REQUIRED_TOP_LEVEL_KEYS
        if extra_keys:
            extra = ", ".join(sorted(extra_keys))
            raise ValueError(
                f"UnifiedGenerator output has unexpected top-level key(s): {extra}"
            )
        if raw_output.get("type") != "excalidraw/clipboard":
            raise ValueError(
                "UnifiedGenerator output 'type' must be 'excalidraw/clipboard'"
            )
        if not isinstance(raw_output["elements"], list):
            raise ValueError(
                "UnifiedGenerator output 'elements' must be a list; "
                f"got {type(raw_output['elements']).__name__}"
            )
        if not isinstance(raw_output["files"], dict):
            raise ValueError("UnifiedGenerator output 'files' must be a dict")
        if not isinstance(raw_output["appState"], dict):
            raise ValueError("UnifiedGenerator output 'appState' must be a dict")

        structure_instantiation = validate_semantic_sidecar(raw_output)
        state.structure_instantiation = structure_instantiation
        state.diagram_manifest = raw_output
        return state
