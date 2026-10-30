"""Structure stage task prompt."""

from __future__ import annotations

from evo_diagram.agentic_system.common.task_prompts import (
    _RUNTIME_INPUTS_TAIL,
    _STRUCTURE_CONTRACT,
)

STRUCTURE_TASK_PROMPT = (
    """
### REASONING PROTOCOL (complete in your hidden thinking channel, in order, before emitting JSON) ###
(a) **Intent Decoding.** What is the ONE story the reader must understand after seeing this diagram? Name it in one sentence before doing anything else. This story drives every subsequent decision.

(a2) **Lock `chart_type` and its calibration anchor.** Declare the most likely `chart_type` and a confidence signal (high/med/low). If med/low, name the runner-up and pick one — do NOT carry ambiguity into extraction. Simultaneously identify the primary organizer and what makes the type instantly recognizable:
     - Lane (swimlane: parallel ownership columns) | Layer (architecture: horizontal band containment) | Axis (timeline/gantt: ordered progression)
     - Level (tree/orgchart/pyramid: hierarchical depth) | Cell (matrix/SWOT: uniform grid, NO arrows) | Set region (Venn: overlapping areas)
     - Center (mindmap: radial tree from root, NO lateral links) | Spine (fishbone)

(b) **Fetch the Type-Driven Budget** (from the TYPE BUDGET section in your stage knowledge below):
     - Which node slots does this chart_type render well, and how many (cells / levels / actors / layers)?
     - Does this chart_type use groups? (matrix/mindmap/tree/pyramid/venn/swot → NO, emit `groups: []`)
     - Does this chart_type use edges? (matrix/swot/venn/pyramid/funnel/gantt/timeline/most infographic → NO, emit `edges: []` regardless of what the source text says; mindmap/tree/orgchart → exactly n−1; architecture → only named flows)
     State the budget as a one-liner: `"type=X → nodes≤N, groups=G, edges=E"`. This is the contract for the rest of this turn.

(c) **Extract entities to fill the budget, not to cover the text.** List candidate nodes with stable snake_case ids (labels 2–4 words max). For each candidate: "which slot in my chart_type budget does this fill?" — if "none", drop it silently. For types with hard counts (matrix rows×cols, pyramid 3–6 levels, venn 2–3 sets), stop once budget is full. **Groups are the most commonly over-extracted category** — only add when the chart_type's organizer is group-based (swimlane lanes, architecture layers, sequence actor lanes). Do not invent groups to park entities the type can't place. **EXCEPTION: For ER and class diagrams, extract ALL entities and ALL relationships — aim for completeness, not minimalism.**

(d) **Edge decision — type-gated.** If step (b) said `edges: []`, EMIT ZERO EDGES and skip to (e). A matrix/venn/pyramid with edges is a bug, not a feature — do not "preserve" relations the source text implies. If the type allows edges:
     - Apply the 3-check Visual Necessity Filter: irreplaceable / not implied by containment / adds clarity.
     - Classify each cross-boundary relation: adjacent handoff (into next neighbor), long-span transfer (across multiple organizers), convergence (many→one), or feedback return (back to earlier). Each class needs different spatial treatment.
     - Run a **parallel-edge audit**: for every pair sharing both endpoints, make an explicit keep-or-merge decision — semantically distinct (different triggers/messages/timings) → keep both; semantic duplicates → merge into one (combine labels with " / ", max 3 pieces). Silent duplication is a top readability failure mode.

(e) **Type-Appropriateness Sanity Check.** Verify the extracted graph FITS the chart_type, not that it covers every mention in the text:
- Entity count within the type budget? (exception: ER/class diagrams aim for completeness)
- Groups used only when the type's organizer is group-based?
- Edge count in expected range? (mindmap/tree → exactly n−1; flowchart/state → ~n+branches; sequence → one per message; architecture → ≤n/2; ER → one per association)
- No dangling entities that exist only because the source mentioned them?
- No group created to "park" an entity the chart_type can't place?
- Would a viewer instantly recognize the diagram type from the extracted structure?

(f) Commit: any change to (a)–(e) during emission means you must restart the chain, not patch mid-way.

Emit the JSON only after all steps are complete.

### CURRENT TASK: Structure Generation (Stage 1 of 3) ###

The overriding principle is **Diagram-Type-First Extraction**: entities, groups, and edges serve the chosen `chart_type`, not the source text. "Correctly extracted from text" is irrelevant — "visually appropriate for this chart_type" is the goal. Missing a minor entity is acceptable; overfitting entities/groups/edges the chart_type can't gracefully display is not.

**EXCEPTION — Data Model Types (ER, Class Diagram):** For ER diagrams and class diagrams, the goal is COMPLETENESS, not minimalism. These are data models — every entity, attribute, and relationship mentioned in the source text must appear. Missing an entity breaks the data model's integrity. When `chart_type` is `er_diagram` or `class_diagram`, extract ALL entities and ALL relationships described in the source text.

**CHEN NOTATION FOR ER DIAGRAMS:** When `chart_type` is `er_diagram`, relationships MUST be created as separate DIAMOND nodes (class: `"relationship"`), NOT as edge labels. For example, if the source says "Customer initiates Deposit", you must create three nodes: `entity_customer` (entity), `rel_initiates` (relationship diamond), `entity_deposit` (entity), and two edges: `entity_customer → rel_initiates` and `rel_initiates → entity_deposit`. The edge labels carry cardinality (1:N, M:N). A relationship node's label should be the verb (initiates, routes, owns, etc.).

Output format — a single JSON object with exactly two top-level keys:
- `specification`: your Phase-1 diagnosis. Include at least
  `diagram_paradigm`, `semantic_typology`, `topological_invariants`, `schema_extensions`.
  **`diagram_paradigm` MUST include a `type_budget` sub-field** recording the one-liner from (b) — this is the contract Styling and Layout will inherit.
- `instantiation`: the concrete semantic graph with
  `chart_type`, `nodes`, `edges`, `groups`. `edges` and `groups` MAY be empty arrays when the type budget says so — do NOT include placeholder entries.

### OPTIONAL PER-TYPE FIELDS (emit when `chart_type` matches; omit otherwise) ###
The core `id` + `label` + `class` contract is mandatory for every chart_type.
When your diagnosis identifies one of the following chart_types, **additionally**
enrich each node/edge with the type-specific field listed below. These hints
give the downstream Layout agent a native layout algorithm hook (radial tree,
grid snap, actor lanes, timeline) instead of forcing it to reconstruct the
topology from a flat edge list.

- `mindmap`: every `nodes[*]` carries `parent_id` (id of its direct parent node; root's `parent_id` is `null`).
- `tree` / `orgchart`: every `nodes[*]` carries `parent_id` (same convention as mindmap).
- `matrix`: every `nodes[*]` carries `row` (0-indexed int) and `col` (0-indexed int).
- `sequence_diagram`: every `nodes[*]` carries `actor_id` (string, which actor lane it belongs to), and every `edges[*]` carries `sequence_idx` (0-indexed timeline order).
- `gantt`: every `nodes[*]` carries `start_ts` and `end_ts` (ISO-like strings or consistent integer units).

For all other chart_types, omit these fields entirely (do not emit `null` or
`""` — just skip the field). `edge.source`/`edge.target` is still the
authoritative adjacency list; `parent_id` / `row`/`col` / `actor_id` are
layout hints that supplement it, not replace it.

**CRITICAL: Your entire response must be a single raw JSON object. Do NOT wrap it in markdown code blocks, do NOT add explanatory text before or after, do NOT use ```json fences. Start your response with {{ and end with }}. Any non-JSON text will cause a parsing failure.**
"""
    + _RUNTIME_INPUTS_TAIL
    + _STRUCTURE_CONTRACT
).strip()

__all__ = ["STRUCTURE_TASK_PROMPT"]
