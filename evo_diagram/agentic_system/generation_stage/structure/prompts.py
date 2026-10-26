"""Structure stage task prompt."""

from __future__ import annotations

from evo_diagram.agentic_system.common.task_prompts import (
    _RUNTIME_INPUTS_TAIL,
    _STRUCTURE_CONTRACT,
    COMPACT_JSON_OUTPUT,
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

(c) **Extract source-grounded entities to fill the budget.** List candidate nodes
with stable snake_case ids (labels 2–4 words max). For each candidate ask both
"which slot in my chart_type budget does this fill?" and "where is this concept
supported by the source?" If it fills no slot, drop it; if it has no source
support, never invent it. For types with hard counts (matrix rows×cols, pyramid
3–6 levels, venn 2–3 sets), stop once budget is full. **Groups are the most
commonly over-extracted category** — only add when the chart_type's organizer is
group-based (swimlane lanes, architecture layers, sequence actor lanes). Do not
invent groups to park entities the type can't place. **EXCEPTION: For ER and
class diagrams, extract ALL entities and ALL relationships — aim for
completeness, not minimalism.**

(d) **Edge decision — type-gated.** If step (b) said `edges: []`, EMIT ZERO EDGES and skip to (e). A matrix/venn/pyramid with edges is a bug, not a feature — do not "preserve" relations the source text implies. If the type allows edges:
     - Apply the 3-check Visual Necessity Filter: irreplaceable / not implied by
       another **semantic edge** / adds clarity. `branch_id`, a frame, or physical
       containment is not a semantic edge and must never be used to discard an
       explicit source fact.
     - Build a source-grounded triple before emitting each edge: `(subject,
       predicate, object)`. Give it an evidence basis: `explicit` when the source
       states the relationship, or `structural` when it only expresses the
       document's declared organization. Plausible world knowledge is neither
       category and MUST be dropped.
     - Keep semantic facts separate from presentation organizers. A branch,
       section, layer, or category title is a navigation device unless the
       source itself makes it the subject or object of the claim. It MUST NOT
       replace an entity in an explicit triple merely to make the graph look
       tidier. For example, "Machine Learning is a subset of Artificial
       Intelligence" becomes `Artificial Intelligence --has subtype--> Machine
       Learning`, never `Theory Section --includes--> Machine Learning`.
       `branch_id` already assigns a concept to its visual section; it does not
       require an invented anchor-to-concept edge.
       A core node is allowed to participate directly in source-explicit domain
       relationships with descendants. Only its document-organization edges
       are restricted to branch anchors. Before committing the fact ledger,
       revisit every source clause mentioning the core and verify its real
       endpoints survived; an organizer path is never a replacement for that
       fact. Use the source clause itself as evidence, not a rewritten sentence
       that changes its subject into the section title.
     - Classify the predicate before choosing its wording: `hierarchy`,
       `composition`, `exemplification`, `dependency`, `causal`, `association`,
       `flow`, `temporal`, or `conditional`. Preserve source strength and
       modality: "linked to", "associated with", "may", and "often" MUST NOT
       become `causes`, `raises`, `requires`, or another stronger claim.
     - Decide directionality independently from relation type. Emit
       `directionality=directed` when the source establishes an ordered subject
       and object (subtype, containment, example, dependency, enabling, causal,
       flow). Emit `directionality=undirected` for symmetric wording such as
       "associated with", "linked to", "related to", or "connected with".
       Never turn a symmetric association into a one-way arrow merely because
       the JSON edge must list a source and target.
     - Run the sentence test: reading `source --label--> target` as a sentence
       must be grammatical and source-faithful. If the predicate naturally reads
       in the opposite direction, reverse the endpoints or choose a directionally
       correct label. Check subject-verb agreement as part of this test: plural
       `Technologies` takes `improve`, not `improves`; when a short label cannot
       remain grammatical, preserve a compact source phrase such as `enables
       improvement in`. Never emit category→example with the label `exemplifies`;
       use category→example `has example`, or example→category `exemplifies`.
     - Resolve list scope and coordination. A heading followed by "including
       A, B, C" creates membership edges only; it does not create causal edges
       among siblings. A predicate applying to "all" listed members may expand
       to each member, but only when the source explicitly gives that scope.
       Resolve pronouns and demonstratives such as "they", "these systems", or
       "these challenges" before building triples. Prefer the nearest compatible
       antecedent; when it denotes a whole named category, connect the category,
       and when it explicitly denotes every list member, expand the predicate to
       those members. Do not silently switch between category scope and member
       scope.
     - Preserve source-explicit intermediate categories before applying the
       node budget. If the source says "metrics such as A and B", retain the
       Metrics node with `Metrics --has example--> A/B`; do not flatten A/B
       directly under an outer section. The same applies to concerns, phases,
       capabilities, and other named list governors.
     - Prefer one truthful collection-level edge when the source predicate has
       an explicit collective subject and a matching collection node exists.
       "All applications contribute to X" should normally be
       `Applications --contribute to--> X`, not N duplicate member edges. Only
       expand to members when the source separately predicates each member or
       when no faithful collection node exists.
     - Classify each cross-boundary relation: adjacent handoff (into next neighbor), long-span transfer (across multiple organizers), convergence (many→one), or feedback return (back to earlier). Each class needs different spatial treatment.
     - Run a **parallel-edge audit**: for every pair sharing both endpoints, make an explicit keep-or-merge decision — semantically distinct (different triggers/messages/timings) → keep both; semantic duplicates → merge into one (combine labels with " / ", max 3 pieces). Silent duplication is a top readability failure mode.

(e) **Type-Appropriateness Sanity Check.** Verify the extracted graph FITS the chart_type, not that it covers every mention in the text:
- Entity count within the type budget? (exception: ER/class diagrams aim for completeness)
- Groups used only when the type's organizer is group-based?
- Edge count in expected range? (mindmap/tree → exactly n−1; flowchart/state → ~n+branches; sequence → one per message; architecture → every explicitly requested dependency; ER → one per association). A presentation budget must never remove an explicitly requested component or relation.
- No dangling entities that exist only because the source mentioned them?
- No group created to "park" an entity the chart_type can't place?
- Would a viewer instantly recognize the diagram type from the extracted structure?
- Build a final two-column audit in hidden reasoning: every `explicit` edge must
  map to one source claim with the same resolved subject and object; every source
  claim selected for the diagram must map back to an edge. Organizer edges are
  audited separately and must use `evidence_basis=structural`. If an organizer
  and an entity both need edges from the core, retain both: they express document
  organization and domain semantics respectively, not duplicate facts.

(f) Commit: any change to (a)–(e) during emission means you must restart the chain, not patch mid-way.
For EVERY diagram type, if you emit fact_ledger / organizer_ledger, each corresponding
edge MUST include evidence_basis (explicit / structural) and relation equal to the
ledger predicate. The optional visible label may be shorter or omitted. This also
applies to architecture, sequence and flowchart edges; it is not concept-map-only.

Emit the JSON only after all steps are complete.

### CURRENT TASK: Structure Generation (Stage 1 of 3) ###

The overriding principle is **Source-Faithful, Diagram-Type-Aware Extraction**.
The selected `chart_type` controls which supported facts earn visual space; it
never licenses changing, strengthening, reversing, or inventing a fact. Missing
a minor entity can be an acceptable budget trade-off. A false relation is never
acceptable, even when it would make the chosen diagram look more connected.

**EXCEPTION — Data Model Types (ER, Class Diagram):** For ER diagrams and class diagrams, the goal is COMPLETENESS, not minimalism. These are data models — every entity, attribute, and relationship mentioned in the source text must appear. Missing an entity breaks the data model's integrity. When `chart_type` is `er_diagram` or `class_diagram`, extract ALL entities and ALL relationships described in the source text.

**CHEN NOTATION FOR ER DIAGRAMS:** When `chart_type` is `er_diagram`, relationships MUST be created as separate DIAMOND nodes (class: `"relationship"`), NOT as edge labels. For example, if the source says "Customer initiates Deposit", you must create three nodes: `entity_customer` (entity), `rel_initiates` (relationship diamond), `entity_deposit` (entity), and two edges: `entity_customer → rel_initiates` and `rel_initiates → entity_deposit`. The edge labels carry cardinality (1:N, M:N). A relationship node's label should be the verb (initiates, routes, owns, etc.).

Output format — a single JSON object with exactly two top-level keys:
- `specification`: your Phase-1 diagnosis. Include at least
  `diagram_paradigm`, `semantic_typology`, `topological_invariants`, `schema_extensions`.
  **`diagram_paradigm` MUST include a `type_budget` sub-field** recording the one-liner from (b) — this is the contract Styling and Layout will inherit.
  For relationship-bearing chart types, `semantic_typology` MUST include two
  separate ledgers:
  - `fact_ledger`: one entry per selected source claim, each with
    `subject_id`, `predicate`, `object_id`, and short `evidence`;
  - `organizer_ledger`: document/presentation organization only, with
    `source_id`, `label`, and `target_id`.
  Every `fact_ledger` entry maps to exactly one instantiation edge with
  `evidence_basis=explicit`, and every explicit edge maps back to one fact entry.
  Every organizer entry maps to an edge with `evidence_basis=structural`.
  Preserve the ledger predicate verbatim in that edge's `relation` field,
  even when its visual `label` is omitted or shortened (for example, "Yes").
  `relation` records meaning; `label` controls visible text. Do not erase
  semantic predicates to reduce visual clutter.
  Never move an entry between ledgers just because one mapping is easier to
  lay out.
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
- `concept_map`: every node carries `branch_id`: the core uses `null`, each
  `branch_anchor` uses its own id, and every descendant uses the id of its
  owning branch anchor. For a flat concept network with no taxonomy branches,
  use `branch_id: null` on all nodes; do not invent branch anchors.
  Branch ownership is layout metadata, not a substitute
  for or inference from a causal/dependency edge. Every `edges[*]` carries
  `relation_type` using one of
  `hierarchy`, `composition`, `exemplification`, `dependency`, `causal`, or
  `association`, `directionality` (`directed` or `undirected`), plus
  `evidence_basis` (`explicit` or `structural`). For an
  explicit semantic edge, also include a short `evidence` phrase copied or
  tightly compressed from the source. Structural organizer edges may omit
  `evidence`. `relation_type` describes the domain predicate; `evidence_basis`
  describes why the edge exists. An explicit `hierarchy`, `composition`, or
  `exemplification` edge is still a source fact and MUST NOT be treated as a
  disposable organizer edge.

For all other chart_types, omit these fields entirely (do not emit `null` or
`""` — just skip the field). `edge.source`/`edge.target` is still the
authoritative adjacency list; `parent_id` / `row`/`col` / `actor_id` are
layout hints that supplement it, not replace it.

**CRITICAL: Your entire response must be a single raw JSON object. Do NOT wrap it in markdown code blocks, do NOT add explanatory text before or after, do NOT use ```json fences. Start your response with { and end with }. Any non-JSON text will cause a parsing failure.**
"""
    + _RUNTIME_INPUTS_TAIL
    + _STRUCTURE_CONTRACT
    + COMPACT_JSON_OUTPUT
    + """
Final ledger check: when a ledger is emitted, EVERY corresponding edge must
include `evidence_basis` and a `relation` copied exactly from its ledger
predicate. A short visible `label` such as Yes/No, or an omitted visible label,
does not replace these fields. Verify this before returning the JSON.
"""
).strip()

__all__ = ["STRUCTURE_TASK_PROMPT"]
