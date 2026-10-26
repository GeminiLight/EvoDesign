"""Excalidraw-specific styling contract."""

from .base import SHARED_STYLING_RULES, SHARED_DO_DONTS

_EXCALIDRAW_SPECIFIC_RULES = """
**Excalidraw-specific rules:**

- Styling owns visual attributes only. Do NOT emit geometry (`x`, `y`, `w`, `h`, `width`, `height`, `min_width`, `min_height`).
- Colors: use `strokeColor` and `backgroundColor` at top level as `#RRGGBB` hex strings.
- Optional style fields:
  `fillStyle` (`"solid"` / `"hachure"` / `"cross-hatch"`),
  `strokeWidth` (`1` / `2` / `4`),
  `strokeStyle` (`"solid"` / `"dashed"` / `"dotted"`),
  `roughness` (`0` / `1` / `2`),
  `opacity` (0-100).
- **Shape types (4 native only):**
  `"rectangle"`, `"ellipse"`, `"diamond"`, `"triangle"`.
  Excalidraw does NOT support pentagon, hexagon, octagon, star, cloud, or arrow shapes.
  If you need arrow shapes, use TLDraw canvas instead.
- Edge color: `strokeColor` at top level (hex).
- Group `:background`: use `backgroundColor` with `canvas` hex or `"transparent"`.
"""

_EXCALIDRAW_DO_DONTS = """
❌ DON'T emit geometry in Styling:
     `{"n1": {"x": 100, "y": 100, "width": 160, "height": 60, "strokeColor": "#003366"}}`
✅ DO emit only visual styling:
     `{"n1": {"shape": "rectangle", "label": {"text": "Node"}, "strokeColor": "#003366", "backgroundColor": "#DBEAFE"}}`

❌ DON'T use named colours or partial hex:
     `"strokeColor": "red"`, `"strokeColor": "1e1e1e"`
✅ DO use 6-digit hex with `#`:
     `"strokeColor": "#003366"`, `"backgroundColor": "#DBEAFE"`

❌ DON'T nest colour or shape fields inside `props`:
     `{"n1": {"props": {"strokeColor": "#000", "shape": "ellipse"}}}`
✅ DO keep them at the top level of the id entry:
     `{"n1": {"shape": "ellipse", "strokeColor": "#000000", "backgroundColor": "#DBEAFE"}}`

❌ DON'T use shapes other than rectangle / ellipse / diamond / triangle.
     pentagon, hexagon, octagon, star, cloud, arrowLeft/Right/Up/Down are NOT supported in Excalidraw.
     Use TLDraw canvas if you need those shapes.
✅ DO use only the 4 native shapes: `rectangle`, `ellipse`, `diamond`, `triangle`.

❌ DON'T emit routing/waypoints/start/end at this stage — they belong to Layout.
❌ DON'T emit `min_width` / `min_height`; those are Layout-internal size hints.
"""

_EXCALIDRAW_REMINDER = """
### REMINDER (re-check before emitting) ###
Every node + group has `shape` (native only: `rectangle`/`ellipse`/`diamond`/`triangle`);
`:title` has `shape: "text"` + non-empty `label.text`;
`specification.color_and_stroke_system.palette_name` is the palette slug (e.g. `"slate_pro"`);
`family_assignments` covers every node id;
every node's `backgroundColor` is the `fill` of its assigned fill_family AND `strokeColor`
is the SAME family's `stroke` (no cross-pairing, no dark fills);
edges use `border_default` or `accent_edge`;
group `:background` uses `canvas` or `transparent`;
all colours are `#RRGGBB` hex at the top level;
no geometry or size hints are present;
the instantiation is a flat id-keyed map;
no id is renamed/prefixed.
Excalidraw supports exactly 4 shapes: rectangle, ellipse, diamond, triangle.
All other geo values will render as rectangle — choose a supported shape for semantic accuracy.
"""

EXCALIDRAW_STYLING_CONTRACT = (
    SHARED_STYLING_RULES
    + _EXCALIDRAW_SPECIFIC_RULES
    + SHARED_DO_DONTS
    + _EXCALIDRAW_DO_DONTS
    + _EXCALIDRAW_REMINDER
)
