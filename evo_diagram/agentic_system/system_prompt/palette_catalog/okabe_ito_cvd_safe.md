## okabe_ito_cvd_safe

**display_name:** Okabe-Ito CVD-Safe

**digest:** Scientific publications, accessibility-critical diagrams, audit-grade documentation.

**mood:** The colorblind-safe gold standard — Wong/Okabe-Ito hues at light tints. For scientific publications and audit-critical diagrams.

**use_when:** Scientific publications, accessibility-critical diagrams, regulatory submissions, audit-grade documentation, color-blind-readable infographics — anywhere CVD safety is a hard requirement.

**avoid_when:** Brand and marketing content (looks generic), creative/playful contexts (lacks character), entertainment (clinical), anywhere a richer mood matters more than universal legibility.

**reference_anchors:** Wong 2011 Nature Methods paper, the original Okabe-Ito colorblind-safe palette, NIH style-guide figures, IEEE journal figure standards.

**balance_guidance:** Use families to encode actual data dimensions, not aesthetic variation. Blue, green, vermillion, yellow, sky, and magenta each carry a stable semantic anchor. Reserve magenta and vermillion for high-emphasis (their luminance differs most from each other for CVD viewers). Black border_default keeps everything readable.

**common_mistakes:** Substituting `close-by` colors from other palettes (CVD safety is verified at exactly these hexes). Using the palette for warm/cold mood signaling (it's engineered for distinguishability, not mood). Adding a 7th color outside the family list.

**canvas:** `#FFFFFF`
**border_default:** `#000000`
**accent_edge:** `#7C2D12`

### Fill Families

| name | fill | stroke | voice |
|------|------|--------|-------|
| blue | `#BFDBFE` | `#1E3A8A` | Wong-1 — primary categorical voice, often `control` or baseline group. |
| green | `#BBF7D0` | `#064E3B` | Wong-3 — second category, often `treatment` or success outcome. |
| vermillion | `#FED7AA` | `#7C2D12` | Wong-5 — high-emphasis warning category. CVD-distinct from green and blue. |
| yellow | `#FEF08A` | `#713F12` | Wong-4 — accent, often `intermediate` or third category. |
| sky | `#BAE6FD` | `#0C4A6E` | Wong-2 — secondary information, supporting category, lighter blue lane. |
| magenta | `#FBCFE8` | `#831843` | Wong-6 — alternate high-emphasis. Vermillion's CVD-distinct partner. |
