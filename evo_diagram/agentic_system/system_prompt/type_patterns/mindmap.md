## Mindmap

### Common
- Best for concept relationships and knowledge structures.
- Identity signal: a central node with radiating branches.

#### Visual Pattern: Radial Layout
Central node at visual center; branches radiate outward evenly:

```
              ┌───────┐
              │Sales  │
              └───┬───┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
┌───┴───┐   ┌────┴────┐   ┌────┴────┐
│Online │   │ CENTRAL │   │Retail   │
└───┬───┘   │  IDEA   │   └────┬────┘
    │       └────┬────┘        │
┌───┴───┐        │        ┌────┴────┐
│Web    │   ┌────┴────┐   │In-store│
└───────┘   │Product  │   └────────┘
            └─────────┘
```

### Structure
- Use a central topic node with radiating main branches and secondary branch nodes.
- Main branches define the first semantic split of the topic, and deeper nodes express hierarchy beneath each branch.
- Main branches can be partial rather than exhaustive, with the center node outside branches. Do NOT emit groups for mindmaps.
- [Budget] parent + children; 0 groups (emits []); n−1 parent→child edges only, NO lateral links
- [Edge Rules] Expected count: exactly n−1 (parent→child only). NO labels on edges. NO lateral/sibling links.

### Styling
- Use an ellipse for the central topic and rectangles for branch nodes.
- Reflect hierarchy through size and color depth.
- Assign a distinct color family to each main branch, and let descendants inherit that family with decreasing intensity.
- The central node should carry the largest font and strongest visual weight, and edges should feel smooth and organic.

#### Color Strategy — use the current palette
- Center: strongest fill from the primary palette family (blue or violet)
- Level 1 branches: one distinct color family per branch
- Level 2+: lighter shades of the parent branch family

#### Branch Styling
- Use curved lines (multiple points) for organic feel
- Thicker lines closer to center (`strokeWidth: 4` → `2` → `1`)
- Branches spread at 45-60° angles

#### Element Sizes
| Level | Font Size | Shape Size | Stroke Width |
|-------|-----------|------------|--------------|
| Center | 28-36 | 180x100 | 4 |
| Level 1 | 20-24 | 140x70 | 2 |
| Level 2 | 16-18 | 100x50 | 2 |
| Level 3 | 14-16 | 80x40 | 1 |

### Layout
- [Detailed Layout Instructions]
  - `nodes[*].parent_id` present → **radial-tree layout**: root at canvas center; each depth level forms a ring; each subtree gets an angular slice sized by its leaf count.
- Primary family: Radial.
- Place the central node at the visual center and distribute main branches evenly around it.
- Expand outward by levels using increasing radius or ring distance.
- Avoid collapsing all branches onto one side of the center.
- [Geometry] Radial layout. Root at canvas center. Each depth level forms a ring. Each subtree gets an angular slice sized by its leaf count. NO lateral links.
- [Edge Routing — MANDATORY] Every edge MUST set `"routing": "curved"`. This is NOT optional. Mindmap branches are organic curves, not straight or elbowed lines — the smooth bezier shape is what makes a mindmap visually identifiable. Do NOT rely on auto-derivation: the canonical mindmap edge connects aligned faces (e.g. center.right→branch.left), which would otherwise default to `straight` and produce a sharp, charts-style diagram. Setting `routing: "curved"` explicitly on every edge is the only way to guarantee the radial-mindmap aesthetic.
