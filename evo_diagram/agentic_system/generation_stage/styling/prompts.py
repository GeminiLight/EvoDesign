"""Styling stage task prompt."""

from __future__ import annotations

from evo_diagram.agentic_system.common.task_prompts import (
    _RUNTIME_INPUTS_TAIL,
)
from evo_diagram.agentic_system.generation_stage.router import DEFAULT_PALETTE_KEY
from evo_diagram.canvas_runtime import normalize_canvas_library


def _get_styling_contract(canvas_library: str = "excalidraw") -> str:
    """Return the canvas-specific styling contract for the current request."""
    canvas = normalize_canvas_library(canvas_library or "excalidraw")
    if canvas == "excalidraw":
        from evo_diagram.agentic_system.generation_stage.styling.contracts.excalidraw import EXCALIDRAW_STYLING_CONTRACT
        return EXCALIDRAW_STYLING_CONTRACT
    if canvas == "tldraw":
        from evo_diagram.agentic_system.generation_stage.styling.contracts.tldraw import TLDRAW_STYLING_CONTRACT
        return TLDRAW_STYLING_CONTRACT
    raise ValueError(f"Unknown canvas_library for styling contract: {canvas_library!r}")


STYLING_TASK_PROMPT = (
    """
### SELECTED PALETTE ###
{{selected_palette}}

### COLOR & STYLING KNOWLEDGE ###

**60-30-10 Rule** — 60% background/white space, 30% primary accent (main boxes), 10% secondary accent (highlights, decisions). Most of the canvas should be neutral; use accent colors sparingly.

**Semantic Color Meanings** (use consistently across all diagram types):
| Color | Meaning | When to use |
|-------|---------|-------------|
| Blue | Information, user-facing, input | Data sources, user actions, external inputs |
| Green | Success, output, data | Completed states, outputs, positive outcomes |
| Yellow | Decision, warning, process | Decision nodes, warnings, intermediate steps |
| Red | Error, danger, critical | Failure states, alerts, critical paths |
| Gray | Neutral, container, background | Group backgrounds, supporting elements |

**Fill + Stroke Pairing** — Always pair a light fill with a matching dark stroke from the SAME color family. Never put a dark hex on `backgroundColor` — bound text defaults to `#1e1e1e` and becomes unreadable on dark fills. Do NOT cross-pair fills and strokes from different families.

**Typography** — Font sizes: group titles 20-24, node labels 16-20, edge labels 14, annotations 12-14. Default to Helvetica font; use mono only for code/technical content.

**Geometry Boundary** — Styling does not emit x/y coordinates, width/height,
or size hints. Layout owns geometry and will derive node sizes from the
semantic labels before placing elements.

### FILL_FAMILY SELECTION GUIDE ###

For each node, pick a fill_family **by semantic role**, not at random:

| Semantic role of the node | Pick the family that feels like... |
|---|---|
| Default flow / process / generic node | the palette's first or most "neutral" family |
| Decision diamond, branch question | a warm or attention-grabbing family (amber / sunny / gold / vermillion) |
| Alert, error, critical, failure | rose / red / alert / peach |
| Information, data input, external | blue / sky / cyan / navy |
| Success, completed, output | mint / leaf / sage / emerald / green |
| Container / supporting / aggregator | neutral / cool-gray / slate / cream |
| Highlighted / focal / hub node | the palette's most accent-y family (the one closest to `accent_edge`) |

A diagram with 6-10 nodes typically uses **2-4 distinct families** — not all nodes need different colors, but using only ONE family for every node will look monotonous.

### COLOR APPLICATION TABLE ###

| Element | Field | Use the chosen palette's |
|---|---|---|
| Every node (rectangle/ellipse/diamond) | `backgroundColor` | `fill_families[chosen].fill` |
| Every node | `strokeColor` | `fill_families[chosen].stroke` (the **paired** stroke of the same family) |
| Group `:background` entries | `backgroundColor` | `canvas` (or `"transparent"`) |
| Standalone group `:title` text | `strokeColor` | `border_default` |
| Default / normal edges | `strokeColor` | `border_default` |
| Highlighted / critical edges (≤10% of edges) | `strokeColor` | `accent_edge` |

**Cohesion rules**:
- Every node's `backgroundColor` MUST equal the `fill` of one of the chosen palette's fill_families. NO exceptions, NO mixing fills from a different palette.
- Every node's `strokeColor` MUST equal the SAME family's `stroke` — do not cross-pair.
- Edges default to `border_default`; reserve `accent_edge` for at most ~10% of edges.

### REASONING PROTOCOL (complete these steps in your hidden thinking channel, in order, before emitting JSON) ###
(a) Read the upstream `[Diagnosis]` block above — note `diagram_paradigm`, `semantic_typology`, `topological_invariants`. Your `visual_paradigm` MUST be consistent with the upstream paradigm.
(b) The palette has been pre-selected by the router. Verify it fits the topic; if it doesn't, proceed anyway (the router's choice is binding). Pick a shape family (geometric / organic). Record the palette key (snake_case slug, e.g. `"slate_pro"`) as `specification.color_and_stroke_system.palette_name`.
(c) **For every node, pick exactly one fill_family from the selected palette by semantic role** (see the FILL FAMILY SELECTION GUIDE above). Apply the family: `backgroundColor = family.fill`, `strokeColor = family.stroke` — never cross-pair. Record per-node choices as `specification.color_and_stroke_system.family_assignments` (id → family.name). Edges default to `border_default`; reserve `accent_edge` for ≤10% highlighted edges.
(d) Cross-check: every `:title` has non-empty `label.text`; every node + group has `shape`; every emitted hex is one of the chosen palette's allowed values; colours are `#RRGGBB`; every edge entry has only `strokeColor`; `palette_name` is set; `family_assignments` covers every node id.
(e) Commit. Emit JSON only after (a)-(d) are all satisfied.

### PHASE 2 VISUAL DIAGNOSTIC FRAMEWORK ###

**Recognition Anchor** — What visual cue makes the diagram type instantly recognizable?
- Swimlane: visible lane boundaries with ownership titles
- Architecture: layer bands with dashed borders
- Flowchart: decision diamonds with Yes/No branches
- Sequence: lifelines descending from actor boxes

**Boundary Check** — Which nearby family could this accidentally resemble if styled too generically?
- Architecture vs generic box diagram (need layer containment)
- Swimlane vs flowchart (need explicit lane ownership)
- State diagram vs flowchart (need lifecycle transitions)

**Container Visibility Audit** — If lanes, layers, quadrants carry meaning:
- How will ownership be visually obvious?
- How will missing membership be noticeable?

**Role Hierarchy** — Which semantic roles deserve strongest visual differentiation?
- Primary: roles that define the diagram type
- Secondary: supporting roles that add context
- Tertiary: annotations, labels, minor connections

**Parent-First Surface Logic** — When containment is semantically primary, decide parent boundaries BEFORE child decoration:
- Group backgrounds: dashed stroke, light/transparent fill
- Group titles: positioned at top, larger font
- Children: solid fill, smaller than containers

**Shape Language** — Map semantic roles to shapes:
- Terminators → ellipse | Process steps → rectangle | Decisions → diamond
- Containers → rectangle (dashed stroke) | Central nodes → ellipse

**Typography** — Hierarchical sizing:
- Group titles: fontSize 20-24
- Node labels: fontSize 16-20
- Edge labels: fontSize 14
- Annotations: fontSize 12-14

### CURRENT TASK: Styling Generation (Stage 2 of 3) ###

Apply Phase 2 (Visual System Design) using the diagnostic framework above.
The upstream Structure output above includes a `[Diagnosis]` slot with Phase-1
commitments (`diagram_paradigm`, `semantic_typology`, `topological_invariants`).
**Inherit and reinforce** those commitments — do not re-derive them. Your
`visual_paradigm` MUST be consistent with the upstream `diagram_paradigm`; if
you find yourself wanting to disagree, the upstream Structure agent is wrong and
you should flag it, not silently override.

- Recognition anchor, boundary check against nearby families, container visibility audit, role hierarchy.
- Parent-first surface logic for any containment-based organizer.
- Shape language, palette-and-fill-family colour system (every fill is light, every paired stroke is dark — see the catalog's Step 4), typography.
- Edge styling is color-only at this stage — routing, ports, waypoints, arrowheads, and labels belong to Layout.

Output format — a single JSON object with exactly two top-level keys:
- `specification`: your Phase-2 design. Include at least
  `visual_paradigm`, `shape_and_icon_system`, `color_and_stroke_system`, `typography_and_hierarchy`.
  **`color_and_stroke_system` MUST include**:
    - `palette_name` — the slug of the selected palette (one of the valid `palette_keys` from the digest, e.g. `"blush_sage"` or `"slate_pro"`).
    - `family_assignments` — flat dict `{{ "<node_id>": "<family.name>", ... }}` covering every node id (NOT edge or group ids).
- `instantiation`: styling entries keyed by element id from the Structure output.
  **Every node and group MUST declare a `shape` field** (`"rectangle"` / `"ellipse"` /
  `"diamond"`); standalone group-title entries (id suffix `:title`) use
  `"shape": "text"`. Edge entries contain colour only; group entries may use
  `:background` and `:title` sub-keys.

**CRITICAL: Your entire response must be a single raw JSON object. Do NOT wrap it in markdown code blocks, do NOT add explanatory text before or after, do NOT use ```json fences. Start your response with {{ and end with }}. Any non-JSON text will cause a parsing failure.**
"""
    + _RUNTIME_INPUTS_TAIL
).strip()


_ICON_INSTRUCTIONS = """

### ICON GENERATION (OPTIONAL ENHANCEMENT) ###

For key nodes, add a companion `<node_id>:icon` entry to make the diagram more visually informative.
You MUST use Material Design icon names from the curated list below — do NOT invent icon names.

**Icon entry format** — for a node with id `n1`, add a companion key `n1:icon`:
```
"n1:icon": {"type": "icon", "props": {"icon": "person", "color": "#1e1e1e"}}
```

**Valid icon names by semantic role** (pick ONE per node based on its meaning):

| Node role | Valid icon names |
|-----------|-----------------|
| Person / User / Actor | `person`, `group`, `account_circle`, `supervisor_account` |
| Process / Task / Workflow | `settings`, `autorenew`, `sync`, `engineering` |
| Decision / Condition | `help`, `question_mark`, `fork_right` |
| Data / Database / Storage | `dns`, `folder`, `inventory_2`, `data_object` |
| Cloud / API / Network | `cloud`, `api`, `dns`, `hub`, `language` |
| Security / Auth / Lock | `security`, `lock`, `shield`, `verified_user` |
| Code / Dev / Tech | `code`, `terminal`, `developer_mode`, `bug_report` |
| Communication / Message | `mail`, `chat`, `forum`, `send` |
| Analytics / Chart / Metric | `analytics`, `bar_chart`, `insights`, `speed` |
| File / Document | `description`, `article`, `insert_drive_file` |
| Warning / Error / Alert | `warning`, `error`, `report_problem`, `notification_important` |
| Success / Check / Done | `check_circle`, `task_alt`, `done_all` |
| Idea / Innovation | `lightbulb`, `auto_awesome`, `rocket_launch` |
| Science / Research | `science`, `biotech`, `psychology` |
| Management / Operations | `build`, `dashboard`, `manage_accounts`, `assignment` |
| Device / Hardware | `devices`, `memory`, `router`, `device_hub` |
| Transport / Movement | `local_shipping`, `directions`, `flight` |
| Finance / Money | `account_balance`, `payments`, `trending_up` |
| Time / Schedule | `schedule`, `timer`, `event`, `calendar_today` |
| Link / Connection | `link`, `share`, `public`, `cable` |

**Rules**:
- Only add icons to PRIMARY nodes (≤60% of all nodes). Skip groups, edges, titles, annotations.
- The `icon` value MUST be exactly one of the names from the table above (snake_case, no spaces).
- Icon `color` MUST be the SAME hex value as the node's `strokeColor` (e.g. if node has `"strokeColor": "#1E40AF"`, the icon must use `"color": "#1E40AF"`). Do NOT use "black" — copy the strokeColor hex literally.
- Do NOT add icons to edge labels, group backgrounds, or `:title` text elements.
"""


def build_styling_task_prompt(
    use_icons: bool = False,
    palette_key: str | None = None,
    canvas_library: str = "excalidraw",
) -> str:
    """Assemble the full styling task prompt with canvas-specific contract.

    Args:
        use_icons: Whether to include icon generation instructions.
        palette_key: Slug of the router-selected palette (e.g. ``"blush_sage"``).
            Must be a valid palette catalog key. The generation workflow
            supplies the default palette when the router is disabled. Omitting
            the argument uses ``DEFAULT_PALETTE_KEY``; explicitly passing an
            empty string is treated as invalid input.
        canvas_library: Target canvas backend for the styling schema contract.
    """
    prompt = STYLING_TASK_PROMPT
    from evo_diagram.agentic_system.common.domain_knowledge_loader import get_selected_palette
    resolved_palette_key = DEFAULT_PALETTE_KEY if palette_key is None else palette_key
    selected_palette = get_selected_palette(resolved_palette_key)
    if not selected_palette:
        raise ValueError(f"Unknown or missing palette_key: {palette_key!r}")
    prompt = prompt.replace("{{selected_palette}}", selected_palette)
    if use_icons:
        prompt += _ICON_INSTRUCTIONS
    prompt += "\n\n" + _get_styling_contract(canvas_library)
    return prompt


__all__ = ["STYLING_TASK_PROMPT", "_ICON_INSTRUCTIONS", "build_styling_task_prompt"]
