## Gantt

### Common
- Best for project progress and task scheduling.
- Identity signal: a time axis with horizontal duration bars.

#### Visual Pattern
```
  Task      │ W1 │ W2 │ W3 │ W4 │
────────────┼────┼────┼────┼────┤
Design      │████│████│    │    │
Development │    │████│████│████│
Testing     │    │    │    │████│
```

### Structure
- Tasks are the primary units and can be grouped by phase or workstream.
- Tasks may carry a duration field that drives bar width.
- Dependency edges encode task ordering and should not form circular dependencies.
- Task status is a meaningful semantic field alongside timing.
- [Budget] tasks/events; 0 groups (or 1 per time track / phase band if source demands); [] edges unless explicit dependency arrows in source
- [Edge Rules] Expected count: 0. The time axis encodes dependency. Only emit edges if source explicitly names dependency arrows.

### Styling
- Use rectangles or bars for tasks.
- Differentiate task status with color, such as not started, in progress, and completed.
- Keep time scales visible at the top.
- Bar width should reflect duration rather than arbitrary box sizing.

### Layout
- [Detailed Layout Instructions]
  - `nodes[*].start_ts` + `nodes[*].end_ts` present → **timeline layout**: map the min→max time range onto the x-axis; stack overlapping tasks vertically in y-bands.
- Primary family: Temporal.
- Place the time axis horizontally across the top and stack tasks vertically below it.
- Position bars proportionally along the time axis and scale width by duration.
- Avoid bars extending beyond the defined timeline bounds.
- [Geometry] Timeline layout: map min→max time range onto x-axis. Stack overlapping tasks vertically in y-bands. Task bars span start→end timestamps.
