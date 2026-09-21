"""
Shared Task-Prompt Components
=============================

Per-stage task prompts live in their respective workflow directories:
  - ``generation_stage/structure/prompts.py``  → ``STRUCTURE_TASK_PROMPT``
  - ``generation_stage/styling/prompts.py``    → ``STYLING_TASK_PROMPT``
  - ``generation_stage/layout/prompts.py``     → ``LAYOUT_TASK_PROMPT``

This module keeps only the **shared building blocks** (runtime-inputs tail and
stage-specific output contracts) so the contracts are defined once and reused
by every stage prompt.

Placeholder contract (``{{var}}`` with ``str.replace``):
  - ``{{stage_knowledge}}``: system-built per-type knowledge from
    type_patterns/*.md (common, structure, styling, layout rules).
    Computed by ``build_stage_knowledge()``.
  - ``{{design_expertise}}``: optional external knowledge (ChromaDB, user
    preferences); may be empty.
  - ``{{text_content}}``: the source text being diagrammed.
  - ``{{user_query}}``: the user's intent string (may be empty / 'N/A').
  - ``{{content_area}}``: optional domain / subject-area hint (may be empty /
    'N/A').
  - ``{{runtime_directives}}``: optional per-request override context the
    caller treats as highest priority. Today it carries either an incremental-
    edit snapshot (locked node ids + current canvas schema) or refiner
    feedback from a prior iteration. May be empty.

Prompt physics
--------------
Each final prompt is assembled as::

    <stage-specific task description>
      + <_RUNTIME_INPUTS_TAIL: optional knowledge + inputs>
      + <stage OUTPUT CONTRACT + DO/DON'T + REMINDER>

The OUTPUT CONTRACT deliberately sits at the END of the prompt (closest to
the generation step) to counteract the "lost-in-the-middle" attention
degradation in long LLM contexts — the hardest constraints get the freshest
attention. Each contract also carries 2-3 DO/DON'T pairs targeting historical
failure modes (edge id drift, label.text omission, width/height vs w/h,
etc.) because LLMs track contrastive examples far better than imperative
prose.
"""

from __future__ import annotations


# Shared tail appended to every task prompt so runtime inputs always land in a
# predictable place. Using a single source keeps formatting consistent.
_RUNTIME_INPUTS_TAIL = """

### STAGE KNOWLEDGE ###
{{stage_knowledge}}

### DESIGN EXPERTISE ###
{{design_expertise}}

### RUNTIME DIRECTIVES ###
These per-request directives have the highest priority after the output
contract. Follow them when present; if empty, ignore this section.
{{runtime_directives}}

### INPUTS ###
text_content:
{{text_content}}

user_query:
{{user_query}}

content_area:
{{content_area}}
"""


# ---------------------------------------------------------------------------
# Stage-specific OUTPUT CONTRACT blocks (placed at the very end of each prompt,
# after INPUTS, so they're the last thing the LLM sees before generating).
# Each block: numbered hard-rules → DO/DON'T pairs → one-line REMINDER.
# ---------------------------------------------------------------------------

_STRUCTURE_CONTRACT = """

### OUTPUT CONTRACT (follow exactly — downstream Styling/Layout stages key off these ids) ###
1. Every node MUST have a unique `id` (e.g. `n1`, `node_root`, `participant_user`). Use
   stable snake-case identifiers; never rely on position alone.
2. Every edge MUST have a unique explicit `id` field, not only `source`/`target`. Use the
   format `edge:{source_id}2{target_id}` (e.g. `edge:n_finance2n_accounting`). If multiple
   edges share the same source and target, append `_1`, `_2`, etc:
   `edge:a2b_1`, `edge:a2b_2`. Downstream stages address edges by id — omitting it
   forces them to synthesise one, which breaks id consistency across stages.
3. Every group MUST have a unique `id` and a `members` array listing its member node ids
   verbatim (use `members`, not `children` or `nodes`).
4. Edge entries include `source` and `target` pointing at node ids that exist in `nodes`.
   Do NOT introduce an edge whose endpoint is not in the node list.
5. Do NOT rename or prefix ids between `instantiation.nodes[*].id`, `edges[*].id`, and
   `groups[*].id` — the exact strings you emit here are the contract for Stages 2 and 3.
6. **Edge labels are FORBIDDEN by default. Add `edge.label` ONLY when the chart_type and the edge's role REQUIRE it.** Edge labels render as text on top of arrows, which is visual noise that the user has explicitly complained about. The rule:

   - **REQUIRED**: emit a non-empty `label` on every semantic edge —
       - `sequence_diagram` (the message text), `state_diagram` / `state_machine` (the trigger / event),
       - `er_diagram` / `class_diagram` (cardinality or relation verb),
       - `concept_map` (a directionally correct relation verb, ≤5 words;
         structural organizer edges may use `organized into`, `includes`,
         `contains`, `has subtype`, or `has example`),
       - `data_flow_diagram` (the data name or trigger),
       - `flowchart` BUT ONLY for edges OUT OF a `decision` node (the branch condition: "yes" / "no" / "approved" / "<5s"). Non-decision flowchart edges get NO label.

   - **FORBIDDEN**: emit `""` (empty string) or omit `label` entirely on every edge —
       - `mindmap`, `tree`, `orgchart`, `pyramid`, `venn`, `swot`, `funnel`, `matrix`, `fishbone`, `gantt`, `timeline` — direction / containment / hierarchy / time axis already encodes the relation; a label adds zero info and clutters the canvas.

   - **OPTIONAL** (default empty unless the label clears every quality bar below):
       - `architecture` (protocol or flow name), `network` (protocol or flow name), `swimlane` (handoff description), `infographic` (descriptive callout), dependency / call / reference diagrams.

7. **Quality bar for OPTIONAL labels** (apply to every label you emit on an OPTIONAL-class chart_type — if the label fails ANY of these, drop it):
   - **≤ 5 words.** "approves", "publishes JSON", "REST 200", "Real-time Inventory Update" are fine. "Liquidity & credit distribution to firms" is too long → drop.
   - **A relation verb, data name, protocol, or constraint** — NOT a paraphrase of the destination node. If your edge points at a node labelled "Banking" and your edge label is "Liquidity & credit distribution" (a description of what banking is), you are repeating the destination node — DROP the label.
   - **NOT a generic direction-verb** that the arrow itself encodes. The forbidden words below add zero information beyond the arrow direction. The only exception is a concept-map structural organizer edge, where a concise membership label is allowed because the relation type is part of the map's meaning:
      `next`, `then`, `after`, `before`, `follows`, `follow`, `leads to`, `leads_to`, `lead to`, `goes to`, `goes_to`, `go to`, `flows to`, `flows_to`, `flow to`, `passes to`, `passes_to`, `pass to`, `sent to`, `sent_to`, `sends to`, `is part of`, `part of`, `part_of`, `contains`, `containing`, `includes`, `including`, `has`, `have`, `is a`, `is_a`, `is an`, `uses`, `use`, `using`, `calls`, `call`, `to`, `from`, `and`, `or`, `→`, `->`, `=>`, `⇒`, `>`. NEVER emit these as a label — set `label` to `""` or omit instead.

### DO / DON'T ###
❌ DON'T use bare sequential ids like `"id": "e1"` or `"id": "e2"` — they carry zero
   semantic information and make debugging painful.
✅ DO use self-describing ids: `"id": "edge:n_finance2n_accounting"`

❌ DON'T use `children` or `nodes` for group members:
     `{{"id": "g1", "children": ["n1","n2"]}}`
✅ DO use `members`:
     `{{"id": "g1", "members": ["n1","n2"]}}`

❌ DON'T emit edges with only `source`/`target` and no `id`:
     `{{"source": "n1", "target": "n2"}}`
✅ DO include an explicit semantic id:
     `{{"id": "edge:n_start2n_step1", "source": "n_start", "target": "n_step1"}}`

❌ DON'T over-label edges. The user explicitly complained about edge-text clutter on 2026-04-25. These ARE the bad patterns we observed:

     concept_map, edge n_finance → n_accounting:
       `{{"id":"edge:n_finance2n_accounting", "source":"n_finance", "target":"n_accounting", "label":"Foundational record-keeping"}}` ← WRONG
       The label paraphrases what "Accounting" means. The destination node already says "Accounting". Adding a long descriptive label repeats the destination — drop it.

     data_flow_diagram, edge process_a → process_b:
       `{{"id":"edge:process_a2process_b", "source":"process_a", "target":"process_b", "label":"Trigger Search"}}` ← WRONG
       "Trigger Search" is a process name; processes belong on NODES, not on edges. If "Trigger Search" matters, make it a node.

     mindmap, any edge:
       `{{"id":"edge:n_root2n_branch1", "source":"n_root", "target":"n_branch1", "label":"includes"}}` ← WRONG (mindmap = no labels, ever)

     flowchart, normal flow edge (NOT out of a decision):
       `{{"id":"edge:n_start2n_step1", "source":"n_start", "target":"n_step1", "label":"next"}}` ← WRONG ("next" is direction, not info)

✅ DO leave edge.label empty (or omit it) by default. Add a short, informative label only when the chart_type REQUIRES it or the relation is genuinely non-derivable from direction:

     mindmap / tree / orgchart / pyramid / venn / swot edge:
       `{{"id":"edge:n_root2n_branch1", "source":"n_root", "target":"n_branch1"}}` (no label field)

     flowchart decision branch:
       `{{"id":"edge:n_check_age2n_minor", "source":"n_check_age", "target":"n_minor", "label":"<18"}}` (the branch condition; ≤5 words)
       `{{"id":"edge:n_check_age2n_adult", "source":"n_check_age", "target":"n_adult", "label":"≥18"}}`

     sequence_diagram message:
       `{{"id":"edge:actor_user2actor_api", "source":"actor_user", "target":"actor_api", "label":"login(creds)"}}`

     er_diagram relation:
       `{{"id":"edge:customer2order", "source":"customer", "target":"order", "label":"places 1:N"}}`

     concept_map (only when label adds info beyond direction):
       `{{"id":"edge:n_govt2n_market", "source":"n_govt", "target":"n_market", "label":"regulates"}}` (single relation verb)
       NOT `{{"label":"Government regulatory framework over private markets"}}`

     concept_map structural organizer edge:
       `{{"id":"edge:n_topic2n_example", "source":"n_topic", "target":"n_example", "label":"has example", "relation_type":"exemplification", "evidence_basis":"structural"}}`
       NOT `{{"source":"n_topic", "target":"n_example", "label":"exemplifies"}}` (the sentence direction is backwards)

Return ONLY the JSON object. No markdown fences, no prose.

### REMINDER (re-check before emitting) ###
Every node+edge+group has a stable `id`; groups use `members` (not `children`); edges carry both `id` AND `source`/`target`; node/group ids are bare semantic ids while edge ids use `edge:{source_id}2{target_id}`; **edge labels are FORBIDDEN by default — emit `label` only on REQUIRED chart_types (sequence/state/ER/class/concept-map semantics/flowchart-decision-branch) or when the label is a ≤5-word non-stop-verb relation that adds info beyond the arrow direction. Generic stop-verbs (next/then/follows/leads to/contains/has/uses/...) are forbidden except for concise concept-map structural organizer labels. Long descriptive labels that paraphrase the destination node are ALWAYS forbidden.**"""


_STYLING_CONTRACT_REMOVED = True  # Moved to generation_stage/styling/contracts/


_LAYOUT_CONTRACT = """

### OUTPUT CONTRACT (follow exactly — renderer parses these fields literally) ###
1. Reuse Structure/Styling ids verbatim, including edge ids in the canonical
   `edge:{{source_id}}2{{target_id}}` form (e.g. `edge:n_a2n_b`). Do NOT rename,
   renumber, or shorten them to `e1`/`e2`. **These ids are foreign keys
   into the Structure graph — the renderer's arrow logic looks shapes up by them.
   Renaming `reminder_received` to `n_start` (or splitting one node into two) breaks
   every downstream arrow.**

   ❌ DON'T rename Structure ids or invent extra nodes:
        Structure: `{{"id": "reminder_received", "label": "Invoice reminder received"}}`
        Layout:    `{{"n_start": {{"x": ..., "y": ...}}}}`        ← WRONG (renamed + new node)
   ✅ DO use the Structure id verbatim as the dict key:
        Layout:    `{{"reminder_received": {{"x": ..., "y": ..., "w": ..., "h": ...}}}}`
2. Each edge entry MUST have both `start` and `end` as objects of shape
   `{{ "elementId": "<node-id>", "side": "top" | "bottom" | "left" | "right" }}`.
   **`side` is a DISCRETE 4-choose-1 selection of a face on the shape — it is NOT a
   coordinate.** "top" means the top-face midpoint, "left" means the left-face midpoint,
   etc. The renderer converts the side string into the actual attach point. **Pick the
   side using the SIDE SELECTION RULES below — do not default every edge to the same
   side** (piling N arrows onto the same face is the #1 readability failure for convergence).
3. **`routing` is auto-derived by the renderer when omitted** (straight for opposite-axis faces, elbowed for perpendicular, curved for same-face or upward feedback). Explicit override is respected — use it when your intended routing differs from the auto-derived default, especially when the diagram type requires a specific style (e.g. mindmap branches → `"curved"`, architecture vertical backbone → `"straight"`, feedback → `"curved"`). Choose according to the edge's geometric relationship:
     - **`straight`** — use when source and target are aligned on the same axis AND the edge is short and unobstructed (e.g. vertical layer-to-layer backbone flows where source is directly above target). Straight lines are the most readable for primary backbone flows.
     - **`elbowed`** — default choice for most edges. Use when source and target are offset (not collinear) or when the edge must route around other shapes. Elbowed lines auto-route with L/Z bends and are the safest general-purpose choice.
     - **`curved`** — use for self-loops, feedback edges that return upward, or when the diagram type explicitly requires organic curves (e.g. mindmap branches). Curved lines produce smooth bezier shapes.
4. **Edge labels are inherited verbatim from Structure — do NOT invent labels Structure didn't emit.** If `Structure.edge.label` is empty / missing / a forbidden stop-verb (next / then / leads to / contains / has / uses / "→" / etc.), emit NO `label` field on this edge entry (or emit `{{ "text": "" }}`). Edge labels render as text on top of arrows and the user has explicitly complained about edge-text clutter — adding a label that Structure deliberately omitted re-introduces the noise. When Structure DID emit a meaningful label, copy it through verbatim under `label.text`. Keep the styled `strokeColor` from Styling — copy it through verbatim. Do NOT move routing or labels inside a nested `props` object. Do NOT emit `waypoints` — the renderer computes the arrow path from the two side choices.
5. Nodes and groups carry geometry at the top level as integers: `x`, `y`, `w`, `h`
   (NOT `width`/`height`, NOT inside `props`). All four must be present for every node,
   every group background, AND every `:title` text element. Group backgrounds must
   numerically contain their children, and each `:title` must be positioned inside or
   along the top edge of its owner group's frame — emitting a `:title` without
   `x/y/w/h` causes the renderer to stack every group label at canvas origin (0, 0),
   the #2 silent failure mode after missing `shape`.
6. Do NOT wrap elements under `nodes` / `edges` / `groups` sub-objects. The instantiation
   must be a flat id-keyed map.

### SIDE SELECTION RULES (apply to every edge independently) ###
Choose the source `side` and target `side` from the relative positions of the two
shape centers. Let `(sx, sy)` be the source center and `(tx, ty)` the target center
(screen coords — y grows DOWN, so sy < ty means source is ABOVE target):

```
dx = sx - tx         dy = sy - ty
if |dy| >= |dx|   (vertical-dominant):
    if dy < 0  (source above target):       source.side = "bottom",  target.side = "top"
    if dy >= 0 (source at/below target):    source.side = "top",     target.side = "bottom"
else              (horizontal-dominant):
    if dx < 0  (source left of target):     source.side = "right",   target.side = "left"
    if dx >= 0 (source at/right of target): source.side = "left",    target.side = "right"
```

Worked examples:
- A at (500, 100) → C at (500, 400): A is DIRECTLY ABOVE C → `source.side="bottom"`, `target.side="top"`.
- B at (100, 400) → C at (500, 400): B is DIRECTLY LEFT of C → `source.side="right"`, `target.side="left"`.
- P at (100, 100) → Q at (600, 500): dx=-500, dy=-400, |dx|>|dy| → horizontal-dominant
  → `source.side="right"`, `target.side="left"`.

**Convergence discipline:** when multiple edges end at the same target, apply the rule
to each edge independently. In the A→C + B→C example above, A→C lands on `C.top`
and B→C lands on `C.left` — different sides, no pile-up. This is the whole point of the
rule: it naturally distributes incoming arrows across the target's 4 faces.

**Same-dominant-axis multiple sources:** when two or more sources sit in the SAME
half-plane relative to the target (e.g. both A and B are above C, both landing on `C.top`),
the geometric rule above will pile them up. To avoid this, differentiate the `source.side`
of at least one edge so the paths diverge:
- Both sources above target: keep one as `source.side="bottom"`, change the other to
  `source.side="left"` or `source.side="right"` (whichever faces the source), so the two
  arrows enter the target from different angles.
- Both sources left of target: keep one as `source.side="right"`, change the other to
  `source.side="top"` or `source.side="bottom"`.

A deterministic renderer-side audit runs after your output: if a `side` you pick is in
the clearly wrong half-plane (e.g. you say `target.side="top"` but the source is below
the target), it will be overridden with the geometric choice above. So the rule is
authoritative; the LLM's role is to follow it rather than guess.

### DO / DON'T ###
❌ DON'T use `width`/`height` or nest geometry inside `props`:
     `{{"n1": {{"props": {{"x": 100, "y": 100, "width": 160, "height": 60}}}}}}`
✅ DO use top-level `x`/`y`/`w`/`h` integers:
     `{{"n1": {{"x": 100, "y": 100, "w": 160, "h": 60}}}}`

❌ DON'T omit `x`/`y`/`w`/`h` on `:title` entries — silent title entries stack at canvas origin and hide every group label under one blob:
     `{{"g_svc:title": {{"label": {{"text": "Service Layer"}}}}}}`  ← WRONG (no xywh)
✅ DO place the title inside or on the top edge of its owner group's frame:
     `{{"g_svc": {{"x": 100, "y": 360, "w": 1400, "h": 180}}}}`
     `{{"g_svc:title": {{"x": 120, "y": 370, "w": 280, "h": 28, "label": {{"text": "Service Layer"}}}}}}`

❌ DON'T default every incoming arrow to `target.side="top"` — e.g. three sources A/B/D all pointing at C with `target.side="top"` piles three arrows on C's top face:
     `{{"edge:A2C": {{..., "end": {{"elementId": "C", "side": "top"}}}}, "edge:B2C": {{..., "end": {{"elementId": "C", "side": "top"}}}}, ...}}`
✅ DO pick each `target.side` by the geometric rule — different sources naturally hit different faces:
     `{{"edge:A2C": {{..., "end": {{"elementId": "C", "side": "top"}}}},     # A above C`
     `  "edge:B2C": {{..., "end": {{"elementId": "C", "side": "left"}}}},    # B left of C`
     `  "edge:D2C": {{..., "end": {{"elementId": "C", "side": "right"}}}}}}  # D right of C`

❌ DON'T drop `start`/`end` port objects or emit them as bare strings:
     `{{"edge:n_start2n_step1": {{"start": "n_start", "end": "n_step1"}}}}`
✅ DO emit full port objects with `elementId` + `side`:
     `{{"edge:n_start2n_step1": {{"start": {{"elementId": "n_start", "side": "bottom"}}, "end": {{"elementId": "n_step1", "side": "top"}}}}}}`

❌ DON'T emit `waypoints` — the renderer routes the arrow from the two sides. Extra waypoints are rejected:
     `{{"edge:n_start2n_step1": {{..., "waypoints": [{{"x": 100, "y": 200}}, {{"x": 500, "y": 200}}]}}}}`
✅ DO trust the side + routing combo to shape the path:
     `{{"edge:n_start2n_step1": {{"start": {{...}}, "end": {{...}}, "routing": "elbowed"}}}}`

Return ONLY the JSON object. No markdown fences, no prose.

### REMINDER (re-check before emitting) ###
Every edge has `start` + `end` as `{{elementId, side}}` objects; each `side` follows the
SIDE SELECTION RULES (axis-dominant + face-toward-other-endpoint); `routing` is
auto-derived by the renderer from the side pair when omitted (straight for opposite-axis
faces, elbowed for perpendicular, curved for same-face or upward feedback) — explicit
override is respected but not required; **no `waypoints`** (renderer handles it); geometry uses
`x`/`y`/`w`/`h` at top level as integers; group backgrounds numerically contain all children."""


__all__ = [
    "_RUNTIME_INPUTS_TAIL",
    "_STRUCTURE_CONTRACT",
    # _STYLING_CONTRACT moved to generation_stage/styling/contracts/
    "_LAYOUT_CONTRACT",
]
