"""Shared styling contract rules — canvas-agnostic."""

SHARED_STYLING_RULES = """
### OUTPUT CONTRACT (follow exactly — renderer parses these fields literally) ###
1. Reuse the EXACT ids emitted by Structure for every node, group, and edge. Never
   rename ids or add prefixes. Edge ids use `edge:{source}2{target}` — reuse them verbatim.
2. **Every node and every group entry MUST declare a shape field.** Valid shape values
   are CANVAS-SPECIFIC — see the canvas-specific contract section below for the full
   list of supported shapes. The renderer silently drops any entry without a recognized
   shape field — this is the #1 failure mode if you forget it.
   - Standalone group-title entries (id suffix `:title`) MUST use `"shape": "text"` /
     `[TLDraw]` `type: "text"`.
3. For every `:title` (group title) and any other standalone text entry, put the display
   string at `label.text`. Top-level `text` and `props.text` are ignored by the renderer.
   Every `:title` entry MUST have a non-empty `label.text` derived from the matching
   structure group's `label`.
4. Edge entries contain ONLY colour for now — no routing, waypoints, start/end, or labels.
   Those belong to Layout output.
5. Do NOT wrap elements under `nodes` / `edges` / `groups` sub-objects. The instantiation
   must be a flat id-keyed map.
6. For shape elements, the displayed label also lives at `label.text` (never `props.text`).
"""

SHARED_DO_DONTS = """
### DO / DON'T ###
❌ DON'T omit the `shape` field — the renderer will silently drop the element.
✅ DO include `shape` on every node and group.

❌ DON'T put the display string at `text` or inside `props`.
✅ DO put it at `label.text`.

❌ DON'T truncate or arbitrarily shorten group titles — echoing a single fragment character is a known failure mode:
     Structure: `{"id": "g_ccc", "label": "Cross-Cutting Concerns"}`
     Styling:   `{"g_ccc:title": {"shape": "text", "label": {"text": "t"}}}`  ← WRONG
✅ DO echo the full structure `label` verbatim (or a readable abbreviation of ≥ 2 characters):
     `{"g_ccc:title": {"shape": "text", "label": {"text": "Cross-Cutting Concerns"}}}`

❌ DON'T paint nodes with the palette's `accent_edge`, `border_default`, or any dark identity hex — those are EDGE / TEXT colours, not fill colours. Putting a dark hex on `backgroundColor` causes the bound text (default `#1e1e1e`) to land on a dark fill, contrast ~1.3:1, completely unreadable.
✅ DO honor explicit user colors and design DNA over the catalog default; define a `user_custom` palette when needed. Use only `fill_families[chosen].fill` for `backgroundColor` (always light) and the SAME family's `stroke` for `strokeColor` (paired darker hue).

❌ DON'T cross-pair fills and strokes from DIFFERENT fill_families — borders must match their family's stroke:
     `{"n1": {"backgroundColor": "#DBEAFE", "strokeColor": "#92400E"}}` ← WRONG (navy fill + gold stroke)
✅ DO keep fill+stroke from the SAME family:
     `{"n1": {"backgroundColor": "#DBEAFE", "strokeColor": "#003366"}}`

❌ DON'T omit `palette_name` or `family_assignments` from `specification.color_and_stroke_system`.
✅ DO record both fields explicitly. `palette_name` is the snake_case slug (e.g. `"slate_pro"`, `"clinical_mint"`) — NOT the human-readable display name.

Return ONLY the JSON object. No markdown fences, no prose.
"""