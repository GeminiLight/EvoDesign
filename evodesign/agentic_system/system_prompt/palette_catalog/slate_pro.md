## slate_pro

**display_name:** Slate Pro

**digest:** Engineering authority — software architecture, ERD, API references, technical specs.

**mood:** The quiet authority of a senior engineer's whiteboard — calm slate gradients with one decisive blue accent.

**use_when:** Engineering content where authority matters more than warmth: software architecture, ERD, sequence diagrams, technical specs, internal infra docs, API references. Anywhere `this person knows what they're doing` should read off the page without ornament.

**avoid_when:** Marketing and lifestyle content (reads as cold), kid-facing education (lacks warmth), healthcare patient UI (too austere), creative brainstorming (too disciplined). When playful, organic, or emotional tones matter more than authority, pick a warmer palette.

**reference_anchors:** GitHub docs, Stripe API reference, Linear engineering blog, Datadog architecture diagrams, Confluence engineering pages.

**balance_guidance:** Most nodes (>=60%) should land in the slate family — that is the resting voice. Reserve blue for <=2 focal nodes the eye should find first. Cyan, amber, and rose are accent families for differentiated semantic roles (info, decision, alert) and together should cover <=30% of nodes. If half the diagram is blue, the diagram has lost its quiet center.

**common_mistakes:** Painting every process step blue (blue is the focal accent, not the default). Using rose for routine errors (reserve it for genuinely critical failures). Mixing slate with grays from another palette (slate IS the neutral here — do not import substitutes).

**canvas:** `#F8FAFC`
**border_default:** `#0F172A`
**accent_edge:** `#2563EB`

### Fill Families

| name | fill | stroke | voice |
|------|------|--------|-------|
| slate | `#E2E8F0` | `#334155` | Resting tone — most nodes land here. The default voice of the diagram, where a reader's eye should rest. |
| blue | `#DBEAFE` | `#1E40AF` | The single decisive accent — focal nodes, primary-flow anchor, the one thing the eye should find first. Use sparingly. |
| cyan | `#CFFAFE` | `#155E75` | Information and data nodes — external inputs, observability, metrics, logs. |
| amber | `#FEF3C7` | `#92400E` | Decisions and warnings — branching points, conditional gates, `requires attention` nodes. |
| rose | `#FFE4E6` | `#9F1239` | Reserved for true failure or critical-path errors. If you find yourself reaching for rose for a routine condition, prefer amber. |
