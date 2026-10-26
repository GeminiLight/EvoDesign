## Venn

### Common
- Best for set relationships and intersection/union.
- Identity signal: overlapping semi-transparent sets with no edges.

#### Visual Pattern
Three-set triangular arrangement with all intersection regions:
```
              ╭─────╮
             ╱   A   ╲
            │  ┌───┐  │
            │A∩B│A∩C│
             ╲ └───┘  ╲
              ╰──┬─────╯
                 │
            ┌────┴────┐
            │ A∩B∩C   │
            └────┬────┘
                 │
       ╭─────────┴─────────╮
      ╱   B        │       C  ╲
     │   ┌───┐     │      ┌───┐ │
     │  B∩A│B∩C│    │     C∩A│C∩B│
      ╲  └───┘     │      └───┘ ╲
       ╰───────────┴─────────────╯
```

### Structure
- Treat logical sets as the primary containers.
- Nodes inside sets can represent set members when needed.
- There should be zero edges; relationships are expressed through spatial overlap alone.
- Avoid replacing overlap semantics with explicit connection lines.
- [Budget] 1 per set; 0 groups; [] edges
- [Edge Rules] Expected count: 0. Set overlap is expressed by geometry.

### Styling
- Use overlapping circles or ellipses to represent sets.
- Use semi-transparent fills so intersection regions blend naturally.
- Keep set backgrounds stroke-free or extremely light so the overlap remains visually clean.
- Place set labels and element labels so they remain readable across overlap zones.

### Layout
- Primary family: Spatial-Set.
- Overlap the set shapes deliberately to create clear intersection regions.
- For two sets, offset centers to preserve overlap readability; for three sets, use a triangular arrangement.
- The intersection regions should be visually meaningful, not accidental.
- [Geometry] Overlapping circles/ellipses. 2-3 sets. Intersection areas represent shared elements. Labels in each region. NO arrows.
