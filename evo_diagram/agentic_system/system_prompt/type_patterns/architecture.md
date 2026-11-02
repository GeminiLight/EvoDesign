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
- **When the source names few or no components** (a one-line request such as
  "画一个短视频推荐系统的架构图"), design the typical architecture of that
  system: 5-8 standard components (clients, entry, the core services of that
  domain, their stores) with the usual flows. Never answer with a single
  system node or a placeholder sublabel such as "待补充".
- **When the source names more than 12 components, choose by priority:**
    - keep first: the main request and data path — entry points, the core
      business services, and the stores and queues they read or write;
    - merge next: peripheral siblings of the same kind become one node whose
      sublabel lists them ("Prometheus / Grafana / Jaeger" -> one
      observability node, "APNs / Twilio / SendGrid" -> one notification
      provider). Core business services are never merged into one node
      ("Core Services" is a collective noun): keep the 3-5 services the main
      flow passes through as separate, named nodes;
    - drop last-mile infrastructure first: deployment and hosting (Kubernetes,
      CI/CD, availability zones), tracing and logging, and secondary services
      that the main path does not call.
  Never drop a store, a queue or a core service while keeping an auxiliary
  one.
- **Every node has at least one edge.** A component the source mentions but
  never connects is either merged into the node it belongs to or dropped.
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
- **Visual priority.** Emit a top-level `title`: the diagram's subject in at
  most 6 words (CJK: 12 characters), in the source language. Give each node an
  optional `emphasis`:
    - `"primary"` for the one or two components the diagram is about (the
      core service, the engine, the agent loop), so the reader's eye lands
      there first;
    - `"muted"` for peripheral infrastructure the main flow does not depend on
      (monitoring, logging, CI/CD, notification providers);
    - omit it for everything else. Never mark more than two nodes primary.
- **Language (strict).** `label` and `sublabel` use the language of the source
  content, even though these instructions and your specification are in
  English: a Chinese source gets Chinese labels ("用户服务", not "User
  Service"). Technology names (Redis, Kafka, MySQL) stay as written.
- **People.** Add an `actor` node only when the source describes who uses the
  system and that information is not already captured; otherwise fold people
  into a client's sublabel ("学生 / 老师").
- **No groups.** Emit `groups: []`. Tiers come from `role`; layer frames add
  boxes without adding information. Only emit a group when the source names an
  explicit trust or deployment boundary (VPC, on-premise vs cloud).
- **Edges.** Draw each explicit dependency or flow once, in the direction the
  data or request travels. Chain entry layers in request order: clients ->
  CDN / WAF / load balancer -> API gateway -> services; when an edge layer
  exists, clients connect to it, not directly to the gateway. When the source
  states a tier-level fact ("services
  store data in MySQL"), connect each relevant service to the store; the
  renderer bundles parallel edges into one shared trunk. Edges carry no visible
  `label` unless a protocol or data name is essential (at most 3 words).
  Before emitting, ask: can I remove any edge without losing a fact the source
  states? If yes, remove it. Keep at most (number of nodes + 4) edges; each
  pair of nodes is connected at most once.

### Styling
- **Colour strategy is yours; the card treatment is fixed.** Each node renders
  as a card whose light fill, mid border, icon and outgoing connectors are all
  derived from the one palette family you assign to it. Choose families by
  architectural role, not decoration:
    - one family per role group (clients, gateways, data stores, external
      systems), so the reader can scan roles by colour;
    - give sibling services distinct families when the palette allows, so
      parallel services stay distinguishable;
    - reserve the palette's accent family for the single focal node (usually
      the gateway or the core service); never use it on more than two nodes.
- Emit `backgroundColor` = family fill and `strokeColor` = family stroke for
  every node, and record the choice in `family_assignments`. Do not invent
  colours outside the palette.
- Use rectangles for every component; role is carried by colour and icon,
  not by shape.
- Edges carry colour only; the renderer colours each connector with its
  source node's family.

### Layout
- **Tier plan (required).** Emit `tier_plan` as a top-level key of
  `specification`. A column is one vertical stack of nodes of the same tier;
  `columns[0]` is the leftmost column; `bottom_row` is one horizontal row
  under all columns. Every node id appears exactly once. The renderer
  executes this plan with fixed card sizes and orthogonal routing, so the plan
  is the layout decision that matters. Example for web + app clients, a
  gateway, three services and three stores:
  `"tier_plan": {"columns": [["web", "app"], ["api_gateway"],
  ["user_service", "order_service", "payment_service"]],
  "bottom_row": ["mysql", "redis", "kafka"]}`.
  Never put clients or gateways in the same column as services or stores.
  Also emit `column_labels` (one short tier name per column, e.g. "接入层",
  "服务层", or a pipeline stage such as "生成") and `bottom_label` (e.g.
  "数据层"), in the source language; adjacent columns with the same label are
  drawn as one zone.
- Read the request flow left to right: people (if any), clients, entry points
  (gateway, load balancer), services and workers, then side systems such as
  models or third-party providers. Put data stores, caches, queues, search and
  observability in `bottom_row`. A CDN or WAF in front of the gateway gets
  its own column before the gateway.
- `bottom_row` holds at most 5 nodes and only shared infrastructure. A node
  that consumes from another bottom-row node (a warehouse fed by a queue, a
  batch job reading the warehouse, an alert channel fed by monitoring) is part
  of a flow: put that chain in the last column, top to bottom in flow order.
- Order nodes inside a column and along the bottom row so that connected
  nodes face each other: a service that writes a store sits above or next to
  it, and sources of the same fan-in sit together. This is what keeps shared
  trunks short and crossings rare. When two nodes in one column are
  connected, list the source first.
- A person who only receives results (an alert recipient) belongs in the last
  column, below the system that notifies them, not before the clients.
- Keep each column to at most 5 nodes; if a tier has more, the structure is
  too dense and should have merged nodes.
- A method or pipeline (stages that hand work to each other, as in a paper's
  framework figure) reads left to right: give each stage, or each group of
  parallel stages, its own column in flow order. Never stack a whole pipeline
  in one column. Use at most 5 columns: stages of one phase (e.g. the agents
  of one generation step) share a column, top to bottom in order. The final
  output goes in the last column, never before the input.
- Instantiation coordinates must follow the same plan (columns left to
  right, bottom row below), so the scene stays coherent if the plan is not
  executed.
