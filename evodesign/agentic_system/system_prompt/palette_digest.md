# Available Palette Identities

20 palettes. Each palette is identified by a snake_case slug (the `key` column). The styling agent receives the full detailed card for whichever key the Router selects.

Do not present every palette as equally recommended. Prefer Tier A for ambiguous/general requests, Tier B for a clear style or domain cue, Tier C only when the source text explicitly calls for that mood. Avoid raw primary-color, neon, rainbow, and default chart looks unless the user's content truly requires them.

## Palette Catalog / 色板总览

| tier | key | display_name | 中文名 | color direction | use this when |
|---|---|---|---|---|---|
| Tier A / 推荐优先 | `blush_sage` | Blush Sage | 柔粉鼠尾草 | muted rose, sand, sage, cyan, indigo | General refined diagrams, AI workflows, method comparisons, polished explanatory figures. |
| Tier A / 推荐优先 | `ocean_glass` | Ocean Glass | 清透海玻璃 | teal, seafoam, blue-gray, sand, coral | Systems, pipelines, agents, trade-offs, data flow, and calm technical narratives. |
| Tier A / 推荐优先 | `lilac_ash` | Lilac Ash | 丁香灰 | lilac, mauve, ash, coral, berry | Human evaluation, qualitative findings, preference maps, survey and mixed-result diagrams. |
| Tier A / 推荐优先 | `cool_mist` | Cool Mist | 冷雾 | cyan, mist blue, blue, lavender, violet | Pure cool-tone maps, ordered conditions, density-style structures, calm analytical diagrams. |
| Tier A / 推荐优先 | `aurora_cool` | Aurora Cool | 冷极光 | mint, aqua, blue, violet, orchid | Modern cold-tone AI, network, heatmap-like, embedding, and exploratory system diagrams. |
| Tier B / 风格明确 | `blossom_warm` | Blossom Warm | 暖花绽放 | peach, coral, muted yellow, tan, taupe | Warm human-centered flows, preference, onboarding, qualitative panels, positive affect. |
| Tier B / 风格明确 | `sunset_mute` | Sunset Mute | 柔和日落 | cream, peach, coral, rose, berry | Before-after stories, gains/losses, milestones, warm emphasis without loud primaries. |
| Tier B / 保守精致 | `porcelain_editorial` | Porcelain Editorial | 编辑瓷色 | blue, mauve, sage, ochre, lavender | Refined categorical diagrams, executive explainers, publication-safe neutral style. |
| Tier B / 工程稳重 | `slate_pro` | Slate Pro | 专业石板 | slate, blue, cyan, amber, rose | Engineering authority: software architecture, ERD, API references, technical specs. |
| Tier B / 企业冷静 | `ibm_carbon_blue` | IBM Carbon Blue | IBM 碳蓝 | blue, teal, violet, magenta, cool gray | Enterprise SaaS, system-of-record, regulated industries; IBM-Carbon polish. |
| Tier B / 医疗领域 | `clinical_mint` | Clinical Mint | 临床薄荷 | teal, mint, sky, amber, alert red | Clinical pathways, hospital workflows, lab protocols, biotech-pharma processes. |
| Tier B / 生态领域 | `forest_eco` | Forest Eco Soft | 柔和森林 | sage, moss, earth, clay, sky | ESG, agriculture, sustainability, circular economy; softened earth tones. |
| Tier B / 商务克制 | `tableau_muted` | Tableau Muted | Tableau 柔和 | muted blue, teal, orange, red, violet | BI dashboards, KPI rollups, multi-series Gantt, executive analytics. |
| Tier B / 产品冷色 | `saas_indigo_neon` | SaaS Indigo Soft | 柔和靛蓝 SaaS | indigo, cyan, violet, slate, emerald | Modern SaaS and AI products when a cooler product identity is needed. |
| Tier C / 特定场景 | `soft_pastel` | Soft Pastel Refined | 精修粉彩 | pink, sky, lilac, mint, peach | Brainstorming, workshops, journal-style maps; pretty but low hierarchy. |
| Tier C / 特定场景 | `coral_warmth` | Coral Warmth | 珊瑚暖调 | coral, peach, cream, teal, rose | Customer journeys, marketing funnels, lifestyle brands, B2C onboarding. |
| Tier C / 特定场景 | `corporate_navy_gold` | Corporate Navy Gold | 企业海军金 | navy, gold, neutral, sky, rose | Board decks, M&A, banking, legal; boardroom gravitas. Can read old-fashioned. |
| Tier C / 特定场景 | `playful_primary` | Playful Soft | 柔和童趣 | sky, leaf, butter, peach, rose | Friendly education and onboarding; softened from primary-color defaults. |
| Accessibility / 无障碍 | `okabe_ito_cvd_safe` | Okabe-Ito CVD-Safe | Okabe-Ito 色盲友好 | blue, green, vermillion, yellow, sky, magenta | Scientific publications, accessibility-critical diagrams, audit-grade documentation. |
| Accessibility / 分类备用 | `colorbrewer_set2` | ColorBrewer Set2 | ColorBrewer Set2 | teal, peach, periwinkle, pink, lime | BPMN swimlanes, multi-actor sequences, qualitative categorical taxonomies. |

## Recommended Default Order

- General polished diagrams: `blush_sage`, then `ocean_glass`, then `lilac_ash`.
- Technical systems, agents, pipelines: `ocean_glass`, then `slate_pro`, then `aurora_cool`.
- Cool analytical direction: `cool_mist` or `aurora_cool`.
- Warm human direction: `blossom_warm` or `sunset_mute`.
- Conservative executive/report direction: `porcelain_editorial`, then `slate_pro`, then `tableau_muted`.
- Healthcare/clinical: `clinical_mint`.
- Sustainability/agriculture: `forest_eco`.
- Accessibility-critical categorical diagrams: `okabe_ito_cvd_safe`; use `colorbrewer_set2` when categorical distinction matters but strict CVD priority is not stated.

## Routing Rules

- If the user gives no palette preference, avoid Tier C unless the text itself clearly signals that style.
- For generic hard, technical, or abstract user text, route to `ocean_glass` or `blush_sage` rather than old corporate/product defaults.
- Use `slate_pro` when engineering authority matters; use `ocean_glass` when the same content should feel more contemporary and less austere.
- Use `saas_indigo_neon` only for explicit SaaS/AI product polish. It is softened, but still reads as product identity.
- Use `corporate_navy_gold` only when the user or content wants boardroom, banking, legal, or M&A gravitas; otherwise it may feel dated.
- Use `playful_primary` only for education, children, beginner onboarding, or explicitly playful requests.
- Use `soft_pastel` for brainstorming and low-stakes ideation; do not use it for diagrams that need strong hierarchy.
- Never choose a palette because it is colorful. Choose it because the color semantics make the diagram easier to read.

## Design Principles

- Keep fills light and strokes dark.
- Prefer coordinated low-to-medium saturation palettes with one or two precise accents.
- Avoid unmodified default palettes, raw primary triads, rainbow gradients, and high-saturation neon.
- Use color semantically: method, condition, sign, magnitude, role, or emphasis.
- Keep the same role-color mapping across a diagram set.
- Do not rely on color alone; pair color with shape, position, label, or line style when meaning is important.
- Use fewer strong colors as the diagram becomes denser.
