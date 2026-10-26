## Concept Map

### Common
- Best for concept relationships and semantic links.
- Identity signal: concept nodes connected by labeled relationships.

#### Visual Pattern
```
          ┌───────────┐
          │  Climate  │
          └─────┬─────┘
                │ drives
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌───────┐   ┌───────┐   ┌───────┐
│ Temp  │   │ Rain  │   │ Wind  │
└───────┘   └───────┘   └───────┘
```

### Structure
- Use exactly one `core_concept`. Its document-organization edges connect to
  `branch_anchor` nodes. Source-explicit semantic edges may connect the core
  directly to any concept, including a descendant inside a branch. Such a link
  does not promote that concept to `branch_anchor` or change its `branch_id`.
  Descendants use stable branch-local classes; semantic adjacency never defines
  the document's branch structure.
- Encode ownership separately from relationship semantics. Set `branch_id` to
  `null` on the core, to the anchor's own id on each `branch_anchor`, and to the
  owning anchor id on every descendant. A dependency, causal, or association
  edge may cross branches but must never determine or change `branch_id`.
- Keep descendant labels as the shortest source-faithful noun phrase. Do not
  repeat words already supplied by the branch anchor: under `Customer Outcomes`,
  use `Retention`, not `Customer Retention Outcome`; do not add qualifiers that
  the source did not state.
- Build document organization as `core_concept -> branch_anchor`. Descendant
  ownership is already encoded by `branch_id` and does not require an
  anchor-to-descendant edge. Add an anchor-to-descendant edge only when the
  source explicitly states that membership, example, or other relationship.
  Never suppress a source-explicit `core_concept -> descendant` fact merely
  because the descendant visually belongs to a branch: a domain relationship
  and a navigation path are different information. Transitive reduction applies
  only to edges with `evidence_basis=structural`, never to explicit facts.
- Every `core_concept -> branch_anchor` edge describes the same organizational
  partition and must use the concise label `organized into`. Never label these
  structural links with inferred causal phrases such as `raises`, `requires`,
  `depends on`, `frames`, or `realized through`.
- Relationships should be labeled with semantic meaning rather than left as
  unlabeled adjacency. Every edge must first be represented as a source-grounded
  subject-predicate-object triple. Emit `relation_type` and `evidence_basis` so
  downstream validation can distinguish organization from semantic claims.
- Emit `directionality=directed` for ordered predicates and
  `directionality=undirected` for symmetric associations such as `linked to`,
  `associated with`, `related to`, and `connected with`. The required JSON
  source/target fields do not by themselves imply an arrowhead.
- Use this direction contract consistently:
  - hierarchy: broader -> narrower, `has subtype`
  - composition/membership: container -> member, `includes` or `contains`
  - exemplification: category -> example, `has example`
  - dependency: dependent -> prerequisite, `depends on`
  - causal/enabling: cause or enabler -> outcome, use the source's verb
  - association: keep source reading order, `associated with` or the source's
    equally weak wording
  The label must make a truthful sentence when read from source to target.
  It must also agree grammatically with the visible subject label; preserve a
  slightly longer source phrase when shortening it would break that sentence.
  `Category -> Example: exemplifies` is backwards and forbidden.
- Add a branch-anchor relation only when the source explicitly makes that
  branch/category the subject of the relation. Visual placement inside the
  branch is represented by `branch_id`, not by a synthetic `includes` edge. Do
  not invent broad `affects`, `shapes`, or `relates` links merely because a
  concept is globally relevant. When two or more sibling examples converge on
  one outcome, keep that outcome in their branch unless the source explicitly
  assigns it elsewhere.
- Preserve the source's relation semantics. Use concise containment words such as
  `includes` or `contains`, dependency words such as `depends on`, example words
  such as `has example`, and causal words such as `enables`, `improves`, or
  `transforms` only when the source makes that causal claim. Do not invent vague
  substitutes such as `ranks` or `categorizes`, and do not strengthen weak
  association language into causality. Words such as `linked`, `associated`,
  `may`, and `often` preserve uncertainty; they never justify `causes`, `raises`,
  or `requires`.
- A list introduced by `including`, `such as`, or a colon establishes membership
  or examples under its governing concept. It does not establish relationships
  among the listed siblings. Expand one predicate across several siblings only
  when coordination such as `all`, `each`, or an equivalent construction gives
  the predicate that scope. When a named collection node faithfully denotes the
  collective subject (for example, "all applications"), prefer one edge from
  that collection to the outcome over several duplicate member-to-outcome edges.
  Expand to member edges only when the source makes separate member-level claims
  or the members differ in predicate or target.
- Preserve source-explicit intermediate categories that govern a scoped list,
  especially constructions such as "performance metrics such as efficiency and
  accuracy". Do not flatten the examples directly under a broader branch when
  the intermediate category carries the list scope or participates in another
  relation.
- Keep the source predicate's force in the label. `contributes to transforming`
  is weaker and more collective than `transforms`; `helps`, `may enable`,
  `often linked to`, and similar qualified predicates must retain their
  qualifying words rather than being shortened into stronger causal verbs.
- Before finalizing, audit every source clause that predicates a relationship
  of the core concept. Keep its actual subject and object in the fact ledger
  even when an organizer path already reaches the same descendant. For example,
  `Methods` organizing a `Statistics` section and `Regression` being a subtype
  of `Methods` are separate claims. Never rewrite the subtype as section
  membership. Check the original clause, not a paraphrase invented for evidence.
- Concept importance may be hierarchical, but the meaning is carried mainly by the labeled links.
- [Budget] concepts; 0 groups; one structural core-to-anchor edge per primary
  branch, no ownership-only descendant edges, and source-explicit semantic links
  regardless of whether they are branch-local or cross-branch
- [Edge Rules] Expected count: labeled relation per link. Labels carry relation verb (≤3 words). NO generic direction verbs (next/then/leads to).

### Styling
- Use one coherent rounded-rectangle family for the core concept, first-level
  branch anchors, and descendants. Do not use wide ellipses or capsule shapes
  merely to signal importance; reserve ellipses for concepts whose semantics
  are genuinely cyclic, continuous, or start/end-like.
- Prefer a title-bar treatment for a global core and compact section-header
  treatment for branch anchors. Differentiate hierarchy with size, fill,
  border weight, and containment before introducing another geometry.
- Reflect importance through size and color: the central concept should be about
  1.4-1.7x the visual area of a leaf, and first-level branch anchors about
  1.15-1.35x. Keep peer leaves compact and consistently sized.
- Assign one distinct palette family to each first-level semantic branch. Every
  descendant inherits its branch family's fill/stroke pair even when its local
  role differs (for example, a metric inside an operational branch stays in
  that branch's color family). Use size, shape, or a lighter fill for
  hierarchy within the branch; do not switch hue by leaf-node class.
- A node with cross-branch edges keeps the color of the branch that contains it;
  use edge emphasis, not an unrelated node color, to show the cross-link.
- Keep relationship labels prominent enough to explain the semantic link.

### Layout
- Primary family: grouped composition. Compare a compact radial candidate with
  stacked bands or a balanced panel grid, and select using canvas aspect ratio,
  group alignment, edge salience, and crossing count rather than area alone.
- When four or more stable first-level branches exist, prefer explicit visual
  regions. A global core may become a top title bar while branch anchors act as
  section headers; containment can then replace repeated core-to-branch arrows.
- For a genuinely radial candidate, keep the core near the center and distribute
  related concepts around it.
- Allow enough edge clearance for labeled relationships.
- Avoid collapsing the map into a single linear path when multiple semantic branches exist.
- Before choosing sectors, compute a branch load for every first-level branch:
  `node count + 0.5 * internal edge count + 1.0 * cross-branch edge endpoints`.
  Allocate angular span and footprint in proportion to that load. A branch with
  twice the load must receive visibly more room; do not force unequal branches
  into equal quadrants.
- Keep branch reading order stable from the source structure. Reorder branches
  only when the crossing or edge-length reduction is material; never infer a
  fixed position from topic-specific words. Load weighting changes each sector's
  available span and depth without changing branch ownership.
- Place each branch anchor at the mouth of its sector and its descendants farther
  outward. Preserve a clear radial corridor from the center to every branch
  anchor, plus a whitespace corridor between neighboring sectors for long-span
  relations and their labels.
- Keep branch-local fan-out edges inside their sector. Route cross-branch edges
  through the whitespace between sectors or around the outer perimeter; never
  thread them through a dense fan of branch-local nodes.
- After assigning positions, explicitly simulate every labeled edge using its
  selected endpoint faces. If two non-shared edges cross, move the lower-load
  branch's leaf or change its face assignment before emitting. A concept map
  with zero node overlap but many edge crossings is not an acceptable layout.
- [Geometry] Free-form layout. Central concept prominent. Related concepts arranged around it. Labeled edges show relationships.
