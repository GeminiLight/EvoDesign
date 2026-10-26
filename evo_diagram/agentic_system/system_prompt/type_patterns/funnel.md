## Funnel

### Common
- Best for conversion and screening processes.
- Identity signal: stacked stages narrowing downward.

#### Visual Pattern
Stages narrow downward; NO arrows between stages:

```
┌─────────────────────────────┐
│         Awareness           │
├─────────────────────────────┤
│        ┌─────────┐          │
│        │ Interest│          │
│        └────┬────┘          │
│             │               │
│        ┌────┴────┐          │
│        │ Decision│          │
│        └────┬────┘          │
│             │               │
│           ┌─┴─┐             │
│           │Buy│             │
│           └───┘             │
└─────────────────────────────┘
```

### Structure
- Use staged levels to represent filtering or conversion through a process.
- Stages can carry quantity or percentage labels.
- The semantic flow moves from broad intake to narrow outcome.
- [Budget] 1 per level (3-6); 0 groups; [] edges
- [Edge Rules] Expected count: 0. Stages communicate by geometry.

### Styling
- Use rectangular or banded stages that narrow toward the bottom.
- Use gradients to show the conversion process across stages.
- Keep stage-level numeric annotations visible.

### Layout
- Center the composition vertically.
- Decrease stage width from top to bottom to form the funnel shape.
- Align labels so the stage-to-stage drop-off remains easy to compare.
- [Geometry] Stacked stages, widest at top, narrowest at bottom. 3-6 stages. Each stage is a trapezoid or horizontal band. Labels centered. NO arrows between stages.
