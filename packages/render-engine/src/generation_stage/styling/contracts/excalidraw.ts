// Ported from evodesign/agentic_system/generation_stage/styling/contracts/excalidraw.py — keep in sync.
// Excalidraw-specific styling contract.
// String constants are generated verbatim from the Python source (ast literal values).

import { SHARED_DO_DONTS, SHARED_STYLING_RULES } from './base.ts';

export const _EXCALIDRAW_SPECIFIC_RULES = "\n**Excalidraw-specific rules:**\n\n- Styling owns visual attributes only. Do NOT emit geometry (`x`, `y`, `w`, `h`, `width`, `height`, `min_width`, `min_height`).\n- Colors: use `strokeColor` and `backgroundColor` at top level as `#RRGGBB` hex strings.\n- Optional style fields:\n  `fillStyle` (`\"solid\"` / `\"hachure\"` / `\"cross-hatch\"`),\n  `strokeWidth` (`1` / `2` / `4`),\n  `strokeStyle` (`\"solid\"` / `\"dashed\"` / `\"dotted\"`),\n  `roughness` (`0` / `1` / `2`),\n  `opacity` (0-100).\n- **Shape types (4 native only):**\n  `\"rectangle\"`, `\"ellipse\"`, `\"diamond\"`, `\"triangle\"`.\n  Excalidraw does NOT support pentagon, hexagon, octagon, star, cloud, or arrow shapes.\n  If you need arrow shapes, use TLDraw canvas instead.\n- Edge color: `strokeColor` at top level (hex).\n- Group `:background`: use `backgroundColor` with `canvas` hex or `\"transparent\"`.\n";

export const _EXCALIDRAW_DO_DONTS = "\n❌ DON'T emit geometry in Styling:\n     `{\"n1\": {\"x\": 100, \"y\": 100, \"width\": 160, \"height\": 60, \"strokeColor\": \"#003366\"}}`\n✅ DO emit only visual styling:\n     `{\"n1\": {\"shape\": \"rectangle\", \"label\": {\"text\": \"Node\"}, \"strokeColor\": \"#003366\", \"backgroundColor\": \"#DBEAFE\"}}`\n\n❌ DON'T use named colours or partial hex:\n     `\"strokeColor\": \"red\"`, `\"strokeColor\": \"1e1e1e\"`\n✅ DO use 6-digit hex with `#`:\n     `\"strokeColor\": \"#003366\"`, `\"backgroundColor\": \"#DBEAFE\"`\n\n❌ DON'T nest colour or shape fields inside `props`:\n     `{\"n1\": {\"props\": {\"strokeColor\": \"#000\", \"shape\": \"ellipse\"}}}`\n✅ DO keep them at the top level of the id entry:\n     `{\"n1\": {\"shape\": \"ellipse\", \"strokeColor\": \"#000000\", \"backgroundColor\": \"#DBEAFE\"}}`\n\n❌ DON'T use shapes other than rectangle / ellipse / diamond / triangle.\n     pentagon, hexagon, octagon, star, cloud, arrowLeft/Right/Up/Down are NOT supported in Excalidraw.\n     Use TLDraw canvas if you need those shapes.\n✅ DO use only the 4 native shapes: `rectangle`, `ellipse`, `diamond`, `triangle`.\n\n❌ DON'T emit routing/waypoints/start/end at this stage — they belong to Layout.\n❌ DON'T emit `min_width` / `min_height`; those are Layout-internal size hints.\n";

export const _EXCALIDRAW_REMINDER = "\n### REMINDER (re-check before emitting) ###\nEvery node + group has `shape` (native only: `rectangle`/`ellipse`/`diamond`/`triangle`);\n`:title` has `shape: \"text\"` + non-empty `label.text`;\n`specification.color_and_stroke_system.palette_name` is the palette slug (e.g. `\"slate_pro\"`);\n`family_assignments` covers every node id;\nevery node's `backgroundColor` is the `fill` of its assigned fill_family AND `strokeColor`\nis the SAME family's `stroke` (no cross-pairing, no dark fills);\nedges use `border_default` or `accent_edge`;\ngroup `:background` uses `canvas` or `transparent`;\nall colours are `#RRGGBB` hex at the top level;\nno geometry or size hints are present;\nthe instantiation is a flat id-keyed map;\nno id is renamed/prefixed.\nExcalidraw supports exactly 4 shapes: rectangle, ellipse, diamond, triangle.\nAll other geo values will render as rectangle — choose a supported shape for semantic accuracy.\n";

export const EXCALIDRAW_STYLING_CONTRACT = (
  SHARED_STYLING_RULES
  + _EXCALIDRAW_SPECIFIC_RULES
  + SHARED_DO_DONTS
  + _EXCALIDRAW_DO_DONTS
  + _EXCALIDRAW_REMINDER
);
