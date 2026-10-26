## Orgchart

### Common
- Best for organizational structures and hierarchies.
- Identity signal: a top-down tree with clear levels.

#### Visual Pattern
```
         ┌─────────┐
         │   CEO   │
         └────┬────┘
     ┌────────┼────────┐
┌────┴────┐ ┌─┴─┐ ┌────┴────┐
│  CTO    │ │CFO│ │  COO    │
└────┬────┘ └───┘ └────┬────┘
     │                 │
┌────┴────┐       ┌────┴────┐
│Engineer │       │  Ops    │
└─────────┘       └─────────┘
```

### Structure
- Represent people or positions as nodes within a clear reporting hierarchy.
- Use reporting-line edges from higher rank to lower rank.
- Preserve distinct rank levels so seniority remains obvious.
- [Budget] parent + children; 0 groups (emits []); n−1 parent→child edges only
- [Edge Rules] Expected count: exactly n−1 (reporting lines only). NO labels on edges.

### Styling
- Use rectangles uniformly for people or position nodes.
- Reflect rank or seniority through color depth and size.
- Keep reporting-line connectors visually simple and consistent.

### Layout
- [Detailed Layout Instructions]
  - `nodes[*].parent_id` present → **radial-tree layout**: root at canvas center; each depth level forms a ring; each subtree gets an angular slice sized by its leaf count.
- Primary family: Layered / Hierarchical.
- Use a strict tree-like structure flowing top-to-bottom.
- Align siblings cleanly within the same level.
- Use vertical downward connectors to reinforce reporting lines.
- [Geometry] Strict tree layout flowing top-to-bottom. Align siblings within same level. Use vertical downward connectors for reporting lines.
- [Edge Routing] Reporting-line edges use `straight` routing with vertical `bottom`→`top` ports. Never use `curved` for orgchart edges — straight vertical lines reinforce the reporting hierarchy.
