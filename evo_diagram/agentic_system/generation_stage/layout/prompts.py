"""Layout stage task prompt."""

from __future__ import annotations

from evo_diagram.agentic_system.common.task_prompts import (
    _RUNTIME_INPUTS_TAIL,
    _LAYOUT_CONTRACT,
)
from evo_diagram.canvas_runtime import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
)

_CANVAS_VIEWPORT_LABEL = (
    f"{CANVAS_DEFAULT_VIEWPORT_WIDTH} x {CANVAS_DEFAULT_VIEWPORT_HEIGHT}"
)

LAYOUT_TASK_PROMPT = (
    f"""
### REASONING PROTOCOL (complete these steps in your hidden thinking channel, in order, before emitting JSON) ###
(a) Read upstream `[Diagnosis]` blocks — note `diagram_paradigm` and `visual_paradigm`. Your `canvas_use_plan` MUST reflect the paradigm (radial for mindmap, grid for matrix, lanes for swimlane, etc.). Budget the {_CANVAS_VIEWPORT_LABEL} viewport accordingly.
(b) Pick the pattern-specific placement grammar (organizer-first for containment; anchor-first for radial; flow-first for directed).
(c) Assign coordinates node-by-node. For groups, compute rectangle from children — never guess.
(d) **Pick edge port sides — this is a DISCRETE 4-choose-1 per endpoint, not a coordinate computation.**
     For each edge, apply the SIDE SELECTION RULES from the OUTPUT CONTRACT (axis-dominant + face-toward-other-endpoint). The rule is deterministic: compute dx/dy from source/target centers, pick sides by dominant axis, and apply independently per edge so convergence naturally spreads across different target faces.
     You do NOT compute waypoints or exact arrow coordinates. You pick 2 discrete sides per edge and the renderer handles the rest. **`routing` is auto-derived by the renderer from the side pair when omitted** (straight for opposite-axis, elbowed for perpendicular, curved for same-face or upward feedback). The renderer's auto-derive fires as fallback — explicit override is respected but not required. **Type-specific rules in your stage knowledge take priority when present** (e.g., mindmap → `"curved"`, architecture vertical backbone → `"straight"`, feedback → `"curved"`).
(e) **Pre-emission design review** — answer each question in your hidden thinking; silent failure on any one is the top visual-quality bug:

     Q1 [Label collision]: List every pair of edge labels in your output. Are their rendered text boxes at least one text-line-height apart? If two or more labels share a near-identical midpoint, you MUST either (i) shorten the labels, (ii) reroute one edge's path so its mid-segment is elsewhere, or (iii) drop a semantically redundant edge — BEFORE emitting. Do not leave the conflict for downstream to fix.

     Q2 [Visual separation]: For every pair of adjacent rectangles (sibling nodes OR sibling group frames), ask: would a reader see TWO distinct shapes, or accidentally read them as ONE merged shape? Borders touching with zero gap read as merged — widen the gap until separation is unambiguous. NOTE: grid / matrix / lane / timeline layouts use grid lines themselves for separation; there a near-zero gap is correct. Judge by visual effect, not a fixed pixel value.

     Q3 [Stacking order]: Group frames paint OVER elements emitted later in the JSON. Emit group frames FIRST (their keys appear first in the `instantiation` object), then nodes / icons, then standalone text. Re-scan your key order: does any group frame appear AFTER one of its children? If yes, reorder before emitting.

     Q4 [Side-selection audit]: For every edge, re-read its two side choices and confirm each side faces the other endpoint (no wrong-half-plane assignments, e.g. `target.side="top"` when source is clearly below target). A deterministic renderer-side audit will fix obvious errors, but getting it right here avoids silent overrides.

     Q5 [Cross self-check]: Check for edge crossings and rank ordering. If the diagram has groups, prioritize placing nodes inside their group bounds. For every pair of edges (e_i, e_j): would their line segments from source.side midpoint to target.side midpoint intersect (excluding shared endpoints)? If your answer to any pair is "yes", adjust node positions to eliminate the crossing. Also verify nodes within the same rank/layer are left-to-right ordered so that most edges flow forward (left-to-right or top-to-bottom) rather than backward.

     Also numerically verify: every group bbox contains all its children; peer organizers are aligned; no two node rectangles overlap; every edge has both `start` and `end` port objects.
(f) Commit. Emit JSON only after the self-audit in (e) passes.

### PHASE 3 LAYOUT DIAGNOSTIC FRAMEWORK ###

**Canvas Planning**:
- Viewport: {_CANVAS_VIEWPORT_LABEL} available (use proportionally to complexity)
- Footprint: let narrative complexity determine spread
- Primary axis: choose dominant reading direction
- Local axis: may differ from global axis inside organizers
- **Viewport overflow**: If content exceeds the {_CANVAS_VIEWPORT_LABEL} viewport, scale proportionally. Do NOT emit elements outside the viewport bounds.
- **Text overflow**: When a node's label exceeds its width, word-wrap within the node. Do NOT truncate with ellipsis or reduce font size — the node's `w`/`h` are computed from the label length, so overflow should not occur if dimensions are sized correctly. If it still occurs, increase `w` rather than clipping text.

**Organizer-First Placement** — For containment-based diagrams:
1. Determine parent region positions FIRST
2. Decide extent per axis (content-driven vs equalized vs full-span)
3. Ensure peer organizers share appropriate boundaries
4. Then place children within

**Within-Organizer Flow Grammar** — Relations staying inside one organizer follow local progression. The exact rule depends on the diagram type (see the `[Geometry]` section in your stage knowledge for the current chart_type). Typical patterns: top-to-bottom within lanes, left-to-right within layers, outward from center in radial.

**Cross-Boundary Edge Grammar** — Relations crossing organizers:
- Adjacent handoff: short horizontal/vertical jump
- Long-span transfer: set `routing` to `"elbowed"` and let the renderer derive the path
- Convergence: multiple paths entering one organizer
- Feedback return: uses secondary corridor, does not cross main path

**Group Boundary Derivation** — NEVER guess group sizes. Always derive from children:
1. Calculate bounding box of all children in the group
2. Add title clearance at top (~40-50px)
3. Add side padding (~20-30px)
4. Background MUST contain ALL children
5. Verify numerically: every child's x,y,w,h is inside the group

**10-Point Self-Audit** — Before finalizing, verify:
1. Diagram identity visible — would a viewer instantly recognize the type?
2. Organizer grammar preserved — are lanes/layers/regions the primary visual structure?
3. Within-organizer progression clear — does local flow read correctly?
4. Cross-boundary relations clear — do handoffs/transfers look different from local flow?
5. Group containment valid — does every group numerically contain its children?
6. Canvas balance — is content spread appropriately, not clustered in one corner?
7. No clipped content — all elements within viewport?
8. Branch readability — are branches visually separate from main path?
9. Label readability — can all text be read without overlap?
10. No orphaned elements — does every element belong to a visible structure?

### CURRENT TASK: Layout Generation (Stage 3 of 3) ###

Apply Phase 3 (Layout Composition) using the diagnostic framework above.
The upstream Structure and Styling outputs above each carry a `[Diagnosis]`
slot committing to paradigm, topology, and visual system. **Inherit** those
commitments — your `canvas_use_plan` and `anchor_assignments` MUST be
consistent with the upstream `diagram_paradigm` and `visual_paradigm`. Your
job here is geometry only, but every coordinate must reinforce the upstream
diagnosis, not re-derive it.

- Canvas plan within the {_CANVAS_VIEWPORT_LABEL} viewport.
- **Use chart-type-specific layout algorithms when upstream nodes carry the corresponding optional fields** (see Structure's OPTIONAL PER-TYPE FIELDS section — these hints short-circuit the need to reconstruct topology from edges). If none apply, fall back to the generic organizer-first placement below.
- Organizer-first placement for containment-based families; derive group rectangles from children, not by guess.
- Within-organizer flow grammar vs cross-boundary edge grammar (adjacent handoff, long-span transfer, convergence, feedback return).
- For every edge, pick a discrete `side` on each endpoint per the SIDE SELECTION RULES (OUTPUT CONTRACT §). Arrowheads default to `null` / `"arrow"`; `routing` is auto-derived by the renderer from the side pair when omitted (straight / elbowed / curved). Explicit override is respected. You do NOT emit `waypoints` — the renderer computes the path. Preserve styled edge colours exactly.
- Numerically verify group containment and peer-organizer alignment before emitting instantiation.

Output format — a single JSON object with exactly two top-level keys:
- `specification`: your Phase-3 plan. Include at least
  `canvas_use_plan`, `pattern_specific_layout_blueprint`, `anchor_assignments`,
  `boundary_derivation`, `layout_self_audit`.
- `instantiation`: coordinates keyed by the exact ids from the Styling output. Nodes
  and groups carry integer `x`, `y`, `w`, `h`. Edge entries carry `start` and `end` as
  `{{{{elementId, side}}}}` objects (required), plus optional `label`, `routing`,
  `startArrowhead`, `endArrowhead`. No `waypoints`.

### ELEMENT SIZE HINTS ###
Use these as minimum node dimensions when assigning `w`/`h`; larger sizes are
allowed when needed for containment, balance, or wrapping.
{{{{size_hints}}}}

**Cross-Stage Field Mapping**: Upstream Structure uses `source`/`target` for edge endpoints; Layout uses `start`/`end`. They map 1-to-1: `edge.source` → `start.elementId`, `edge.target` → `end.elementId`.

**CRITICAL: Your entire response must be a single raw JSON object. Do NOT wrap it in markdown code blocks, do NOT add explanatory text before or after, do NOT use ```json fences. Start your response with {{{{ and end with }}}}. Any non-JSON text will cause a parsing failure.**
"""
    + _RUNTIME_INPUTS_TAIL
    + _LAYOUT_CONTRACT
).strip()

__all__ = ["LAYOUT_TASK_PROMPT"]
