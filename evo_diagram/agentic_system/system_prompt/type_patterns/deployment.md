## Deployment

### Common
- Best for where software runs: which artifacts are deployed on which hosts, inside which zones, and how they connect.
- Identity signal: nested environment boxes (region, zone, cluster or host) holding the deployed artifacts, with a few labelled connections.

#### Visual Pattern
```
┌ Region us-east-1 ──────────────────────────────────────┐
│ ┌ Zone A ───────────────┐   ┌ Zone B ───────────────┐  │
│ │ ┌ node-1 ───────────┐ │   │ ┌ node-2 ───────────┐ │  │
│ │ │ [api ×2]  [worker]│ │   │ │ [api ×2]          │ │  │
│ │ └─────────┬─────────┘ │   │ └─────────┬─────────┘ │  │
│ └───────────┼───────────┘   └───────────┼───────────┘  │
│             └──── 5432/tcp ──▶ [Postgres primary] ◀────┘│
└────────────────────────────────────────────────────────┘
```

### Structure
- Environments are groups: region, zone, cluster, host or VM, nested with
  `parent_group_id`, 2-4 levels deep.
- List each artifact in the `members` of its innermost environment only.
  An outer environment contains its inner ones through their
  `parent_group_id`; never repeat their artifacts in its own `members`.
- Artifacts are nodes placed in the innermost environment that runs them:
  services, containers, databases, queues. Keep replica counts in the label
  ("api ×3") instead of drawing copies.
- Draw only the connections the source names, from caller to callee. Label
  them with the port or protocol when the source gives one ("443/https",
  "5432").
- Choose `deployment` when the source says where things run (hosts,
  clusters, zones, regions). Components and request flow without placement
  are `architecture`; devices and links are `network_topology`; containment
  with no connections is `nested`.
- [Budget] artifacts (3-14); one group per environment (2-4 levels deep); only named connections (usually ≤ n)
- [Edge Rules] Expected count: only named connections. Labels carry the port or protocol when stated; otherwise none.

### Styling
- Environment boxes use thin borders and very light fills that darken one
  step per nesting level; their titles are small and quiet.
- Artifacts use cards with an icon for their kind (service, database,
  queue, cache).
- Connections are thin arrows in one ink; label text is small.

### Layout
- Primary family: Containment with links.
- Size each environment from its contents, innermost first: 24px side
  padding and about 40px at the top for the title.
- Sibling environments sit side by side with tops aligned, mirrored when
  they hold the same artifacts (e.g. two zones), so replication reads at a
  glance.
- Shared resources (a database used by every zone) sit below or between
  the environments that use them, inside the narrowest environment that
  holds them.
- Route connections as elbowed paths that cross as few boundaries as
  possible.
- [Geometry] Nested environment boxes, siblings side by side with tops aligned. Artifacts inside their innermost environment. Shared resources centred below their users. Elbowed, labelled connections.
