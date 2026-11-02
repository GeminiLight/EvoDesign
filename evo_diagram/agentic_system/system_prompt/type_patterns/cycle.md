## Cycle

### Common
- Best for reinforcing loops and recurring processes where the last step feeds the first, such as a flywheel or a release cycle.
- Identity signal: steps arranged on a ring with arrows running in one direction around it.

#### Visual Pattern
```
            ┌──────────┐
       ┌───▶│ Traffic  │────┐
       │    └──────────┘    ▼
 ┌──────────┐          ┌──────────┐
 │ Lower    │ (Growth) │ Sellers  │
 │ prices   │          └────┬─────┘
 └──────────┘               │
       ▲    ┌──────────┐    │
       └────│ Selection│◀───┘
            └──────────┘
```

### Structure
- 3-8 step nodes in the order the loop runs. Edges connect each step to the
  next, and the last step back to the first: every step has exactly one
  outgoing and one incoming ring edge.
- A driver the source names that feeds the loop but is not fed by it (e.g.
  "more selection attracts traffic" when nothing in the loop produces
  selection) is an entry node with `class: "entry"` and one edge into the
  step it drives. Never drop it, and never force it onto the ring.
- Optionally add one hub node with `class: "hub"` for what the loop builds
  up or keeps turning (e.g. "Growth", "Customer experience"). The hub has no
  edges.
- Label steps as short actions or states (2-4 words). Edges carry no
  labels; anything that passes between two steps belongs in the step label.
- If the process has a clear start and end and only sometimes repeats, use a
  `flowchart` with a return edge instead.
- [Budget] steps (3-8) + optional 1 hub + entry nodes (0-2); 0 groups; one edge per step (n edges, closing the loop) + one per entry node
- [Edge Rules] Expected count: n + entries where n = step count; the last ring edge returns to the first step; each entry node has one edge into the ring. All edges run in the same direction. NO labels.

### Styling
- Steps share one card style. The hub is larger and uses the accent family.
- Arrows are curved or follow the ring, all with the same weight.

### Layout
- Primary family: Radial ring.
- Place the steps evenly on a circle, clockwise, the first step at the top.
  Use a radius large enough that neighbouring cards keep at least 40px apart.
- Put the hub, if any, at the centre of the circle.
- Put each entry node outside the ring, next to the step it drives.
- Route each edge along the ring from one step to the next with `routing:
  "curved"`; no edge crosses the centre.
- [Geometry] Steps evenly spaced on a circle, clockwise from the top. Hub at the centre. Edges follow the ring between neighbours, all in one direction, none crossing the centre.
