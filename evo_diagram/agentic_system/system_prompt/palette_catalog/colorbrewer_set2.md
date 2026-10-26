## colorbrewer_set2

**display_name:** ColorBrewer Set2

**digest:** BPMN swimlanes, multi-actor sequences, qualitative categorical taxonomies.

**mood:** The data scientist's qualitative palette — perceptually balanced, print-safe, AA-legible at all hues.

**use_when:** BPMN swimlanes (each lane gets a distinct color), multi-actor sequence diagrams, qualitative-data visualizations, taxonomy and categorization charts — anywhere distinct categories must remain instantly distinguishable.

**avoid_when:** Hierarchical content (no inherent ordering), narrative flows (no clear focal point), branded or marketing content (reads as research-paper neutral). When you need to express weight or hierarchy, pick a palette with a designated focal accent.

**reference_anchors:** matplotlib qualitative palettes, Tableau categorical defaults, BPMN.io examples, scientific paper figures (Nature, Science, PNAS).

**balance_guidance:** Each category gets ONE family — that is the whole point. 5 families = 5 maximum categories. Don't subdivide a family for sub-categories; pick a different palette if you need ordinal data. Border_default for default edges; accent_edge (teal) for cross-category links.

**common_mistakes:** Using two families for the `same` semantic category (dilutes the categorical signal). Painting all nodes from one family then sprinkling another (defeats the qualitative purpose). Combining with another palette's colors — Set2 only.

**canvas:** `#FFFFFF`
**border_default:** `#252525`
**accent_edge:** `#00695C`

### Fill Families

| name | fill | stroke | voice |
|------|------|--------|-------|
| teal | `#B2DFDB` | `#00695C` | Category 1 — typically the primary actor, first lane, or first qualitative class. |
| peach | `#FFCCBC` | `#BF360C` | Category 2 — second actor, second lane, or second qualitative class. |
| periwinkle | `#C5CAE9` | `#283593` | Category 3 — third actor, third lane, or third qualitative class. |
| pink | `#F8BBD0` | `#AD1457` | Category 4 — fourth actor, fourth lane, or fourth qualitative class. |
| lime | `#DCEDC8` | `#33691E` | Category 5 — fifth actor, fifth lane, or fifth qualitative class. |
