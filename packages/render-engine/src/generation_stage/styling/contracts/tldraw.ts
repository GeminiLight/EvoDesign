// Ported from evodesign/agentic_system/generation_stage/styling/contracts/tldraw.py — keep in sync.
// TLDraw-specific styling contract.
// String constants are generated verbatim from the Python source (ast literal values).

import { SHARED_DO_DONTS, SHARED_STYLING_RULES } from './base.ts';

export const _TLDRaw_SPECIFIC_RULES = "\n**TLDraw-specific rules:**\n\n- Styling owns visual attributes only. Do NOT emit geometry (`x`, `y`, `w`, `h`, `width`, `height`, `min_width`, `min_height`, or `props.w` / `props.h`).\n- Shape type: ALL shape nodes use `\"type\": \"geo\"`. Differentiate via `props.geo`:\n  `\"rectangle\"`, `\"ellipse\"`, `\"diamond\"`, `\"triangle\"`, `\"pentagon\"`, `\"hexagon\"`,\n  `\"octagon\"`, `\"star\"`, `\"cloud\"`, `\"arrowLeft\"`, `\"arrowRight\"`, `\"arrowUp\"`, `\"arrowDown\"`.\n- Colors: use `props.color` with TLDraw color names:\n  `black`, `grey`, `light-violet`, `violet`, `blue`, `light-blue`,\n  `yellow`, `orange`, `green`, `light-green`, `light-red`, `red`, `white`.\n  Common forbidden values: `purple` → `violet`, `gray` → `grey`, `circle` → `ellipse`.\n- Fill: `props.fill` — `\"none\"`, `\"semi\"`, `\"solid\"`, `\"pattern\"`.\n- Dash: `props.dash` — `\"draw\"`, `\"solid\"`, `\"dashed\"`, `\"dotted\"`.\n- Font: `props.font` — `\"draw\"`, `\"sans\"`, `\"serif\"`, `\"mono\"`.\n- Text alignment: `props.align` (`\"start\"` / `\"middle\"` / `\"end\"`),\n  `props.verticalAlign` (`\"start\"` / `\"middle\"` / `\"end\"`).\n- Size: `props.size` — `\"s\"`, `\"m\"`, `\"l\"`, `\"xl\"`.\n- Edge color: `props.color` inside the edge entry (same TLDraw color names).\n- Group `:background`: use `props.color` set to `\"white\"` or `\"black\"`.\n";

export const _TLDRaw_DO_DONTS = "\n❌ DON'T emit geometry in Styling:\n     `{\"n1\": {\"type\": \"geo\", \"x\": 100, \"y\": 100, \"props\": {\"w\": 186, \"h\": 62, \"geo\": \"rectangle\"}}}`\n✅ DO emit only visual styling:\n     `{\"n1\": {\"type\": \"geo\", \"label\": {\"text\": \"Node Label\"}, \"props\": {\"geo\": \"rectangle\", \"color\": \"blue\", \"fill\": \"none\", \"dash\": \"draw\", \"size\": \"m\", \"font\": \"draw\"}}}`\n\n❌ DON'T use hex colors or Excalidraw property names:\n     `\"strokeColor\": \"#003366\"`, `\"backgroundColor\": \"#DBEAFE\"`\n✅ DO use TLDraw color names in `props.color`:\n     `\"props\": {\"color\": \"blue\", \"fill\": \"none\"}`\n\n❌ DON'T use `\"type\": \"rectangle\"` or `\"type\": \"ellipse\"` — those are Excalidraw types.\n✅ DO use `\"type\": \"geo\"` with `props.geo` to specify the shape:\n     `{\"type\": \"geo\", \"props\": {\"geo\": \"rectangle\", ...}}`\n\n❌ DON'T put `strokeColor`/`backgroundColor` at the top level.\n✅ DO put all styling inside `props`:\n     `{\"n1\": {\"type\": \"geo\", \"props\": {\"geo\": \"ellipse\", \"color\": \"green\", \"fill\": \"semi\", ...}}}`\n❌ DON'T emit `min_width` / `min_height`; those are Layout-internal size hints.\n";

export const _TLDRaw_REMINDER = "\n### REMINDER (re-check before emitting) ###\nEvery node + group has `type: \"geo\"` with `props.geo`; every `:title` has\n`type: \"text\"` + non-empty `label.text`; `specification.color_and_stroke_system.palette_name`\nis the palette slug (e.g. `\"slate_pro\"`); `family_assignments` covers every node id; every node's `props.color` is a valid\nTLDraw color name from its assigned fill_family; `props.fill` is set; edges use\n`props.color` with a valid TLDraw color; the instantiation is a flat id-keyed map;\nno id is renamed/prefixed; no geometry or size hints are present.\n";

export const TLDRAW_STYLING_CONTRACT = (
  SHARED_STYLING_RULES
  + _TLDRaw_SPECIFIC_RULES
  + SHARED_DO_DONTS
  + _TLDRaw_DO_DONTS
  + _TLDRaw_REMINDER
);
