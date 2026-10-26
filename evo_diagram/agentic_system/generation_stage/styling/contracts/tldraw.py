"""TLDraw-specific styling contract."""

from .base import SHARED_STYLING_RULES, SHARED_DO_DONTS

_TLDRaw_SPECIFIC_RULES = """
**TLDraw-specific rules:**

- Styling owns visual attributes only. Do NOT emit geometry (`x`, `y`, `w`, `h`, `width`, `height`, `min_width`, `min_height`, or `props.w` / `props.h`).
- Shape type: ALL shape nodes use `"type": "geo"`. Differentiate via `props.geo`:
  `"rectangle"`, `"ellipse"`, `"diamond"`, `"triangle"`, `"pentagon"`, `"hexagon"`,
  `"octagon"`, `"star"`, `"cloud"`, `"arrowLeft"`, `"arrowRight"`, `"arrowUp"`, `"arrowDown"`.
- Colors: use `props.color` with TLDraw color names:
  `black`, `grey`, `light-violet`, `violet`, `blue`, `light-blue`,
  `yellow`, `orange`, `green`, `light-green`, `light-red`, `red`, `white`.
  Common forbidden values: `purple` → `violet`, `gray` → `grey`, `circle` → `ellipse`.
- Fill: `props.fill` — `"none"`, `"semi"`, `"solid"`, `"pattern"`.
- Dash: `props.dash` — `"draw"`, `"solid"`, `"dashed"`, `"dotted"`.
- Font: `props.font` — `"draw"`, `"sans"`, `"serif"`, `"mono"`.
- Text alignment: `props.align` (`"start"` / `"middle"` / `"end"`),
  `props.verticalAlign` (`"start"` / `"middle"` / `"end"`).
- Size: `props.size` — `"s"`, `"m"`, `"l"`, `"xl"`.
- Edge color: `props.color` inside the edge entry (same TLDraw color names).
- Group `:background`: use `props.color` set to `"white"` or `"black"`.
"""

_TLDRaw_DO_DONTS = """
❌ DON'T emit geometry in Styling:
     `{"n1": {"type": "geo", "x": 100, "y": 100, "props": {"w": 186, "h": 62, "geo": "rectangle"}}}`
✅ DO emit only visual styling:
     `{"n1": {"type": "geo", "label": {"text": "Node Label"}, "props": {"geo": "rectangle", "color": "blue", "fill": "none", "dash": "draw", "size": "m", "font": "draw"}}}`

❌ DON'T use hex colors or Excalidraw property names:
     `"strokeColor": "#003366"`, `"backgroundColor": "#DBEAFE"`
✅ DO use TLDraw color names in `props.color`:
     `"props": {"color": "blue", "fill": "none"}`

❌ DON'T use `"type": "rectangle"` or `"type": "ellipse"` — those are Excalidraw types.
✅ DO use `"type": "geo"` with `props.geo` to specify the shape:
     `{"type": "geo", "props": {"geo": "rectangle", ...}}`

❌ DON'T put `strokeColor`/`backgroundColor` at the top level.
✅ DO put all styling inside `props`:
     `{"n1": {"type": "geo", "props": {"geo": "ellipse", "color": "green", "fill": "semi", ...}}}`
❌ DON'T emit `min_width` / `min_height`; those are Layout-internal size hints.
"""

_TLDRaw_REMINDER = """
### REMINDER (re-check before emitting) ###
Every node + group has `type: "geo"` with `props.geo`; every `:title` has
`type: "text"` + non-empty `label.text`; `specification.color_and_stroke_system.palette_name`
is the palette slug (e.g. `"slate_pro"`); `family_assignments` covers every node id; every node's `props.color` is a valid
TLDraw color name from its assigned fill_family; `props.fill` is set; edges use
`props.color` with a valid TLDraw color; the instantiation is a flat id-keyed map;
no id is renamed/prefixed; no geometry or size hints are present.
"""

TLDRAW_STYLING_CONTRACT = (
    SHARED_STYLING_RULES
    + _TLDRaw_SPECIFIC_RULES
    + SHARED_DO_DONTS
    + _TLDRaw_DO_DONTS
    + _TLDRaw_REMINDER
)
