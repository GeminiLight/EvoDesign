## Architecture

### Common
- Best for system architecture and layered design.
- Identity signal: layered components and bounded system regions.

#### Visual Pattern: Layered Architecture (legacy, groups only when the source names boundaries)
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
- **Design system.** The renderer draws architecture diagrams with a fixed design system: every node
  becomes a card with an icon, a name and a one-line sublabel, placed by `role`
  into tiers (people | clients | gateways | services | side systems, with data and
  infrastructure as a bottom row). Structure only decides *what* exists.

- **Deletion first.** Every node is a distinct component the reader needs. Two
  things that always travel together are one node. Target 5-9 nodes; never more
  than 12. Keep every component the source explicitly names. Never create a node
  for a collective noun that refers to other nodes ("services", "all clients",
  "backend"); connect the members it refers to instead.
- **Every node carries:**
    - `label`: the component name, 1-4 words (CJK: at most 8 characters). Use the
      source's own name ("API 网关", "Redis"), not a generic category.
    - `sublabel`: what it does or what it runs on, at most 6 words (CJK: at most
      12 characters), parts joined with " / " (e.g. "路由 / 认证 / 限流",
      "MySQL / 分库分表", "iOS / Android"). Derive it from the source; when the
      source only names a component or technology, its typical responsibility
      is allowed and preferred over a restatement of the name ("Redis" ->
      "热点缓存", "用户服务" -> "用户管理 / 认证", not "用户业务"). A sublabel
      never introduces a new component.
    - `role`: exactly one of `actor` (a person or team), `client` (UI, app,
      device, dashboard), `gateway` (gateway, load balancer, proxy, broker
      endpoint that receives traffic), `service`, `worker` (pipeline, stream or
      batch job), `model` (AI/ML model), `database`, `cache`, `queue`,
      `storage`, `search`, `observability`, `external` (third-party system).
    - `icon`: one name from this list that best depicts the node:
      outline_globe, outline_smartphone, outline_monitor, outline_laptop,
      outline_user, outline_users, outline_network, outline_waypoints,
      outline_shield, outline_server, outline_database, outline_layers,
      outline_zap, outline_hard_drive, outline_archive, outline_message_square,
      outline_radio, outline_cloud, outline_box, outline_package,
      outline_credit_card, outline_wallet, outline_file_text,
      outline_shopping_cart, outline_bell, outline_search, outline_chart_column,
      outline_activity, outline_lock, outline_key_round, outline_cpu,
      outline_brain, outline_bot, outline_workflow, outline_git_branch,
      outline_mail, outline_settings, outline_folder, outline_image,
      outline_video, outline_map_pin, outline_truck, outline_store,
      outline_receipt, outline_clipboard_list, outline_gauge, outline_scale,
      outline_container, outline_terminal, outline_code, outline_send,
      outline_split, outline_blocks, outline_boxes, outline_cable, outline_route,
      outline_webhook, outline_app_window.
- **Language.** `label` and `sublabel` use the language of the source content.
  Technology names (Redis, Kafka, MySQL) stay as written.
- **People.** Add an `actor` node only when the source describes who uses the
  system and that information is not already captured; otherwise fold people
  into a client's sublabel ("学生 / 老师").
- **No groups.** Emit `groups: []`. Tiers come from `role`; layer frames add
  boxes without adding information. Only emit a group when the source names an
  explicit trust or deployment boundary (VPC, on-premise vs cloud).
- **Edges.** Draw each explicit dependency or flow once, in the direction the
  data or request travels. When the source states a tier-level fact ("services
  store data in MySQL"), connect each relevant service to the store; the
  renderer bundles parallel edges into one shared trunk. Edges carry no visible
  `label` unless a protocol or data name is essential (at most 3 words).
  Before emitting, ask: can I remove any edge without losing a fact the source
  states? If yes, remove it.

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
- **High fan-out**: Preserve all requested outgoing dependencies. For four or more targets, spread ports and route parallel corridors; do not invent a bus node or split a source component merely to reduce its fan-out.
- **No bidirectional edge pairs on the same side**: If A→B and B→A both exist, route them with DIFFERENT side pairs:
  - A→B: `source.side="bottom"`, `target.side="top"`, `routing="straight"`
  - B→A: `source.side="right"`, `target.side="right"`, `routing="curved"` (same-face loop-back, pulls outward)
  Do NOT draw both as `bottom→top` — they will completely overlap into one line.
- **Group frame padding**: Use `28-40px` side/bottom padding and enough top padding for one compact title row. Tight group frames clip routes, while very large frames dilute hierarchy.
