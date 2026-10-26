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

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.callbacks import BaseCallbackManager

from evo_diagram.agentic_system.common.skill_loader import EVODIAGRAM_SKILL_SYSTEM_PROMPT
from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
)
from evo_diagram.core.base_agent import BaseAgent
from evo_diagram.utils.llm_output import preprocess_response
from .sidecar import validate_semantic_sidecar
from .state import UnifiedWorkflowState
from .transport_journal import NativeStreamJournal
from .continuation import invoke_native_scene


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
  Phase 3 — Layout Composition ({_CANVAS_VIEWPORT_LABEL} hard canvas limit,
             profile-first composition, organizer-first placement, derive
             group bounds from children, self-audit)

Then output a single Excalidraw clipboard JSON object plus a semantic sidecar.
Do NOT emit any "specification" / "instantiation" wrapper — go straight to
the scene envelope below.

### OUTPUT FORMAT (strict) ###
Return EXACTLY this top-level shape, with keys in the shown order and no extra keys:
{{
  "type": "excalidraw/clipboard",
  "elements": [ ... ],
  "files": {{}},
  "appState": {{"viewBackgroundColor": "<canvas hex from PALETTE>", "gridSize": null}},
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
Author the visual decisions only. Every element MUST include:
  id (unique string), type, x, y, width, height, strokeColor, backgroundColor.
Include groupIds for related elements, and style overrides where meaningful.
The runtime supplies these omitted defaults: angle=0, fillStyle=solid,
strokeWidth=1.5, strokeStyle=solid, roughness=0, opacity=100, groupIds=[],
roundness=null, plus stable seed/version/versionNonce, index, isDeleted=false,
frameId=null, link=null, locked=false, updated, and reciprocal boundElements.
OMIT that repeated metadata from your output. Explicit visual overrides are
preserved. Never omit actual geometry, semantic IDs, or relation endpoints.

Type-specific additions:
- rectangle / ellipse / diamond: use `roundness: {{"type": 3}}` for rounded rects,
  `null` for sharp corners.
- text: text, fontSize (16-24 typical),
  textAlign ("left"|"center"|"right"),
  verticalAlign ("top"|"middle"|"bottom"), containerId (string or null),
  fontFamily only when different from Helvetica (2). Runtime supplies
  originalText=text, autoResize=true, lineHeight=1.25.
- arrow: points (array of `[dx, dy]` relative to x/y; first point is [0,0]),
  startBinding ({{"elementId":"...","focus":0,"gap":5}} or null),
  endBinding (same shape or null),
  startArrowhead (null|"arrow"|"triangle"|"dot"),
  endArrowhead (null|"arrow"|"triangle"|"dot"),
  elbowed (bool).
- arrow elements MUST include `meta.semantic_edge_id` matching an edge id from
  `_meta.structure_instantiation.edges[*].id`.

### SEMANTIC SIDECAR CONTRACT ###
`_meta.structure_instantiation` uses the exact same semantic graph contract as
the multiagent Structure stage:
- canonical `chart_type` from the supported diagram type registry
- every node has `id`, `label`, and `class`
- every edge has `id`, `source`, and `target`, with id format
  `edge:{{source_id}}2{{target_id}}`
- every edge endpoint references an existing node
- type-specific fields are mandatory when applicable (for example
  `parent_id` for mindmap/tree/orgchart, `row`/`col` for matrix,
  `actor_id`/`sequence_idx` for sequence diagrams, `start_ts`/`end_ts` for gantt)

For `concept_map`, include the complete contract on the first response:
- Every node has `branch_id`: the `core_concept` uses null, each
  `branch_anchor` uses its own id, and other nodes use their owning anchor id.
  Ownership describes the source grouping; a cross-group fact never changes it.
- Every edge has a readable `label`, `relation_type`, `directionality`, and
  `evidence_basis`. The ONLY relation types are `hierarchy`, `composition`,
  `exemplification`, `dependency`, `causal`, and `association`. Use `causal`
  for enabling/improvement predicates; retain the precise meaning in `label`.
  Do not invent compound enum values.
- `directionality` is exactly `directed` or `undirected`; choose it from the
  source predicate. A weak or symmetric association is not automatically causal.
- `evidence_basis` is exactly `explicit` or `structural`. EVERY explicit edge
  also requires `evidence`: a short source phrase supporting that specific
  subject, predicate, and object. Preserve source qualifiers and collective
  subjects. Structural organizer edges may omit evidence.
- An explicit hierarchy, composition, or exemplification is still a source
  fact. Preserve it along with dependency and causal facts; never reclassify
  facts as structural merely to simplify the drawing.

`_meta.id_map` maps every semantic node id and edge id to its Excalidraw
element id. Semantic groups may map either the group id itself or the
`<group_id>:background` companion id to the rendered group frame. Additional
companion keys are allowed only for real semantic bases:
`<node_or_group_or_edge_id>:title`, `:label`, `:icon`, or `:background`.
If a semantic edge is rendered as an arrow, the arrow's `meta.semantic_edge_id`
MUST equal that semantic edge id. This sidecar is not optional: verifier and
render audit use it to prove semantic coverage.
Map every visible relation label with `<edge_id>:label`. A standalone relation
label may use containerId=null; the runtime derives its semantic ownership from
this explicit mapping so later geometry edits preserve the label and its style.

### BINDING / GROUP INVARIANTS ###
1. Every element's `id` MUST be unique across the scene.
2. Stable seed, versionNonce, and editor bookkeeping are supplied by code.
3. Arrow bindings and text containerId MUST reference real element IDs.
   The runtime derives reciprocal boundElements; do not repeat them.
4. Set containerId on bound text to its owning element. Standalone group
   titles use `containerId: null` and live outside their group's bounds so
   they render above the container.
5. Related elements (lane background + title + children) share the same
   `groupIds` array (e.g. `["group-marketing"]`). Group membership implies
   belonging — do NOT draw arrows just to signal containment.
6. Use ONLY colours from the injected PALETTE card. Set `viewBackgroundColor`
   to its `canvas` value, use `border_default` for neutral structure, and pair
   every fill with the matching stroke from the same family. Do not import the
   legacy Excalidraw default palette or raw primary colours.

### COMPOSITION BUDGET ###
`{_CANVAS_VIEWPORT_LABEL}` is a safety boundary, NOT a target size. Before
placing elements, choose the smallest profile that fits readable labels:
- compact `1200x800`: up to 8 ordinary nodes
- wide `1600x900`: 9-16 nodes, architecture layers, timelines, or swimlanes
- large `2400x1600`: more than 16 nodes or genuinely long labels
Use 70-90% of the chosen profile in the dominant direction. Keep outer margins
40-80 px, ordinary node gaps 40-80 px, and group padding 32-64 px. Upgrade one
profile only when the content cannot fit at readable sizes; never spread a
small diagram across the full hard limit.

For architecture diagrams, use draw.io-like compact components: Helvetica 18,
ordinary rectangles approximately 180-300 px wide and 56-72 px high, sized to
their labels rather than forced to one oversized width. Use a white canvas,
light role fill plus darker matching border, and visually quiet group surfaces.
Primary dependency flow uses neutral solid 2 px connectors with a filled
triangle end; dashed coloured connectors are reserved for cross-cutting,
feedback, or other secondary relations. Prefer orthogonal paths with at most
2-3 bends and never use double-headed arrows unless the relation is genuinely
bidirectional.

### COLOUR HIERARCHY ###
- Keep one resting family on at least half of ordinary nodes.
- Reserve the strongest family for one or two primary anchors, not every node.
- Use at most two supporting families unless distinct categories require more.
- Group surfaces must be lighter and quieter than their child nodes.
- Connector colours encode meaning; routine edges use `border_default` or
  `accent_edge` consistently rather than inheriting arbitrary node colours.

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
        self.stream_journal = NativeStreamJournal()
        if isinstance(model.callbacks, BaseCallbackManager):
            callbacks = model.callbacks.copy()
            callbacks.add_handler(self.stream_journal)
        else:
            callbacks = [*(model.callbacks or []), self.stream_journal]
        super().__init__(
            model=model.model_copy(update={"callbacks": callbacks}),
            tools=tools,
            system_prompt=EVODIAGRAM_SKILL_SYSTEM_PROMPT,
            task_prompt=UNIFIED_TASK_PROMPT,
            **kwargs,
        )
        self.full_domain_knowledge = full_domain_knowledge

    def _invoke_with_retry(self, input_prompt: dict) -> Any:
        return invoke_native_scene(self._agent, input_prompt, self.stream_journal)

    def invoke_with_history(self, messages: list, tools: Optional[list] = None) -> Any:
        if tools is not None:
            return super().invoke_with_history(messages, tools=tools)
        prompt = {"messages": [
            message for message in messages
            if not (message.get("role") == "system" and message.get("content") == self._system_prompt)
        ]}
        for attempt in range(self.json_retry_attempts):
            raw_output = self._invoke_with_retry(prompt)
            self._last_raw_output = raw_output
            try:
                return preprocess_response(
                    raw_output, only_text=True, exclude_think=self.exclude_think,
                    json_output=self.jsonalize_output, strict_json_output=self.strict_json_output,
                )
            except json.JSONDecodeError:
                if attempt + 1 == self.json_retry_attempts:
                    raise

    def run(self, state: UnifiedWorkflowState) -> UnifiedWorkflowState:
        journal_directory = (
            Path(state.validation_report_path).parent / "transport"
            if state.validation_report_path else None
        )
        self.stream_journal.configure(journal_directory, new_scene=not state.generation_attempts)
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
        if state.validation_error and state.generation_attempts:
            previous = state.generation_attempts[-1]
            messages = [
                {"role": "system", "content": self._system_prompt},
                *self._build_prompt(input_dict)["messages"],
                {"role": "assistant", "content": json.dumps(previous["output"], ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        "The scene failed executable validation at "
                        f"{previous['stage']}: {state.validation_error}\n"
                        "Correct the specific contract errors in this current scene. "
                        "Preserve source facts, stable semantic IDs, and unaffected layout "
                        "and styling. Return the complete corrected scene JSON, with no prose. "
                        "Do not omit facts or weaken validation to make the scene pass."
                    ),
                },
            ]
            logger.info("[UnifiedGenerator] Repairing scene from validation feedback...")
            raw_output = self.invoke_with_history(messages)
        else:
            logger.info("[UnifiedGenerator] Invoking LLM (single-shot)...")
            raw_output = self.invoke(input_dict)
        state.candidate_output = deepcopy(raw_output)

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
