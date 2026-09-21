## Architecture

### Common
- Best for system architecture and layered design.
- Identity signal: layered components and bounded system regions.

#### Visual Pattern: Layered Architecture
Stack components vertically with clear boundaries:

```
┌─────────────────────────────────────────┐
│           Presentation Layer            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│  │   Web   │  │ Mobile  │  │   API   │  │
│  └─────────┘  └─────────┘  └─────────┘  │
├─────────────────────────────────────────┤
│            Business Layer               │
│  ┌─────────────────────────────────┐    │
│  │         Service Logic           │    │
│  └─────────────────────────────────┘    │
├─────────────────────────────────────────┤
│              Data Layer                 │
│  ┌─────────┐         ┌─────────┐        │
│  │   DB    │         │  Cache  │        │
│  └─────────┘         └─────────┘        │
└─────────────────────────────────────────┘
```

**Layer colors (top to bottom) — use the current palette:**
- Presentation: blue family
- Business: green family
- Data: violet family

#### Visual Pattern: Microservices Pattern
Independent services with API gateway:

```
                    ┌─────────────┐
                    │   Clients   │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │ API Gateway │
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐
    │  Service A  │ │  Service B  │ │  Service C  │
    └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
           │               │               │
    ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐
    │    DB A     │ │    DB B     │ │    DB C     │
    └─────────────┘ └─────────────┘ └─────────────┘
```

### Structure
- Use explicit system layers such as presentation, business/application, and data.
- Every node should belong to exactly one architecture layer group, with no unassigned components.
- Request flow and dependency flow should not violate declared layer order without an explicit exception.
- Some nodes may carry technology annotations such as a tech_stack field.
- [Budget] components; one group per layer/zone (2-5); backbone layer-to-layer flows (≈ n-1 to n+2) plus AT MOST one cross-cutting/infrastructure connection per layer. Layer containment organizes components but does NOT replace backbone flows. Omit minor utility dependencies that would create a radiating star from infrastructure nodes.
- [Edge Rules] Expected count: n-1 to n+3 where n = component count. Draw arrows for: (1) sequential layer-to-layer data flows (presentation→service→business→data), (2) same-layer lateral handoffs. For cross-cutting/infrastructure (security, logging, communication, etc.): draw ONLY from upper-layer components TO infrastructure nodes, NEVER the reverse. Limit to at most one such edge per layer. Do NOT draw radiating stars where one infrastructure node connects to 3+ upper-layer components — this produces unreadable overlapping long horizontal lines.
- **[CRITICAL] No skip-layer connections**: A component in layer N may ONLY connect to components in layer N+1 (the immediately adjacent layer below). NEVER draw an edge that skips a layer (e.g. Presentation → Data bypassing Business). If the text describes a dependency that logically spans two layers, insert an intermediate component in the skipped layer or break it into two sequential edges (A→B→C). Skip-layer edges create long diagonal arrows that cross intermediate group frames and destroy the visual layer separation.

### Styling
- Use compact, text-fitted components rather than giving every node the same
  oversized width. At Helvetica 18, ordinary components should usually be
  `180-300px` wide and `56-72px` high.
- Use a white canvas. Pair a light fill with a darker stroke from the same
  semantic family; keep all text dark and high-contrast.
- Render layer/group boundaries as very pale surfaces with a thin solid stroke.
  They must be quieter than their children and must not look like primary nodes.
- Use solid filled rectangles for internal components or services.
- Primary dependency arrows use a neutral solid `2px` line and one filled
  triangle at the target. Reserve dashed coloured arrows for cross-cutting or
  secondary relations; do not use double-headed arrows without bidirectional
  semantics.

#### Component Shapes by Type
| Component | Shape | Color family |
|-----------|-------|--------------|
| User/Client | Ellipse or stick figure | blue |
| Service/API | Rectangle | green |
| Database | Ellipse (cylinder look) | violet |
| Queue/Message | Rectangle with wavy side | yellow |
| External System | Rectangle with double border | grey |
| Load Balancer | Diamond | light-blue |

### Layout
- Primary family: Layered / Hierarchical.
- Use a layered top-to-bottom arrangement.
- Maintain stable left-to-right local ordering inside a layer.
- Sidebar or cross-cutting groups can sit outside the main stack when needed.
- [Geometry] Horizontal layer bands with dashed borders. Components within layers as solid-fill rectangles. Color-code by tier. Draw backbone layer-to-layer flows and same-layer handoffs. For cross-cutting/infrastructure: draw sparse horizontal stubs from upper-layer components toward a sidebar group, at most one per layer. Layer containment organizes but does not replace backbone flows.

#### Side Selection Rules (architecture-specific)
Apply to EVERY edge independently. The side choice determines both readability and whether edges pile up:

**Layer-to-layer backbone flows (primary vertical data flow):**
- Source is ABOVE target → `source.side = "bottom"`, `target.side = "top"`
- Source is BELOW target (feedback/exception only) → `source.side = "top"`, `target.side = "bottom"`
- **NEVER** use `left`/`right` for primary vertical backbone flows — this creates unnecessary L-bends and breaks the visual layer stack.

**Same-layer lateral handoffs:**
- Source is LEFT of target → `source.side = "right"`, `target.side = "left"`
- Source is RIGHT of target → `source.side = "left"`, `target.side = "right"`

**Cross-cutting / infrastructure edges (to sidebar group):**
- Source (upper-layer component) → `source.side = "right"` (pointing outward toward sidebar)
- Target (infrastructure node in sidebar) → `target.side = "left"` (receiving from main stack)

#### Routing Rules (architecture-specific)
Emit an explicit `routing` field on every edge. Do NOT rely on auto-derivation.

| Edge category | `routing` value | When to use |
|--------------|-----------------|-------------|
| Vertical backbone (layer N → layer N+1, direct downward) | `"straight"` | Source is directly above target with minimal horizontal offset. Straight vertical lines are the most readable for primary data flows. |
| Cross-layer offset flow | `"elbowed"` | Source and target are vertically adjacent but horizontally offset by more than one component width. The elbow auto-routes around intermediate shapes. |
| Same-layer lateral handoff | `"elbowed"` | Horizontal handoff between peers. Elbowed lines with bottom→top side pairs are cleaner than long horizontal straight lines that cross group boundaries. |
| Cross-cutting / infrastructure stub | `"elbowed"` | Short horizontal stub from component to sidebar. Keeps the stub visually distinct from backbone flows. |
| Feedback / reverse flow (upward) | `"curved"` | Any edge that goes upward (target above source). Curved lines pull the path outside the main downward progression and avoid overlapping primary flows. |
| Self-loop (component to itself) | `"curved"` | A component calling itself or an internal cycle. |

#### Spacing and Anti-Overlap Rules
- **Component horizontal gap**: Use a consistent `48-80px` gap between adjacent components. Large gaps make the diagram read as disconnected islands.
- **Layer vertical corridor**: Keep `48-72px` of usable routing space between component rows or adjacent layer bands. Expand only where a real fan-out needs another channel.
- **Max fan-out from a single node**: A single component should NOT be the source of more than 3 outgoing edges. If a component genuinely connects to 4+ targets, split it into a sub-layer or bus/bar node that fans out cleanly.
- **No bidirectional edge pairs on the same side**: If A→B and B→A both exist, route them with DIFFERENT side pairs:
  - A→B: `source.side="bottom"`, `target.side="top"`, `routing="straight"`
  - B→A: `source.side="right"`, `target.side="right"`, `routing="curved"` (same-face loop-back, pulls outward)
  Do NOT draw both as `bottom→top` — they will completely overlap into one line.
- **Group frame padding**: Use `28-40px` side/bottom padding and enough top padding for one compact title row. Tight group frames clip routes, while very large frames dilute hierarchy.
