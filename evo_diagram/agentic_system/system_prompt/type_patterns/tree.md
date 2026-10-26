## Tree

### Common
- Best for hierarchical structures and classification relationships.
- Identity signal: a root with branching descendants.

#### Visual Pattern
```
              ┌─────────┐
              │  Root   │
              └────┬────┘
        ┌──────────┼──────────┐
   ┌────┴────┐ ┌───┴───┐ ┌───┴───┐
   │Branch A │ │BranchB│ │BranchC│
   └────┬────┘ └───────┘ └───┬───┘
   ┌────┴────┐           ┌───┴───┐
   │ Leaf A1 │           │Leaf C1│
   └─────────┘           └───────┘
```

### Structure
- Use a root node with branching child nodes below it.
- Represent parent-child relationships explicitly with downward connectors.
- Depth and ancestry are the core semantics of the diagram.
- [Budget] parent + children; 0 groups (emits []); n−1 parent→child edges only, NO lateral links
- [Edge Rules] Expected count: exactly n−1 (parent→child only). NO labels on edges. NO lateral links.

### Styling
- Use an ellipse for the root node and rectangles for all other nodes.
- Reflect depth through color gradients when useful.
- Keep parent-to-child connectors visually direct and unambiguous.

### Layout
- [Detailed Layout Instructions]
  - `nodes[*].parent_id` present → **radial-tree layout**: root at canvas center; each depth level forms a ring; each subtree gets an angular slice sized by its leaf count.
- Primary family: Layered / Hierarchical.
- Place the root node at the top and distribute children below it.
- Evenly spread child nodes within each level.
- Balance branches so subtrees remain readable.
- [Geometry] Radial or top-to-bottom tree layout. Root at top or center. Children at next level. Align siblings. NO lateral links.
- [Edge Routing] Parent→child edges default to `straight` (top-to-bottom) or `curved` (radial). Use `curved` for radial layouts; `straight` for top-to-bottom layouts.
