## Concept Map

### Common
- Best for concept relationships and semantic links.
- Identity signal: concept nodes connected by labeled relationships.

#### Visual Pattern
```
          ┌───────────┐
          │  Climate  │
          └─────┬─────┘
                │ drives
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌───────┐   ┌───────┐   ┌───────┐
│ Temp  │   │ Rain  │   │ Wind  │
└───────┘   └───────┘   └───────┘
```

### Structure
- Use separate roles for core concepts and secondary concepts.
- Relationships should be labeled with semantic meaning rather than left as unlabeled adjacency.
- Concept importance may be hierarchical, but the meaning is carried mainly by the labeled links.
- [Budget] concepts; 0 groups; labeled relation per link
- [Edge Rules] Expected count: labeled relation per link. Labels carry relation verb (≤3 words). NO generic direction verbs (next/then/leads to).

### Styling
- Use ellipses for core concepts and rectangles for secondary concepts.
- Reflect importance through size and color.
- Keep relationship labels prominent enough to explain the semantic link.

### Layout
- Primary family: Radial.
- Keep core concepts near the center and distribute related concepts around them.
- Allow enough edge clearance for labeled relationships.
- Avoid collapsing the map into a single linear path when multiple semantic branches exist.
- [Geometry] Free-form layout. Central concept prominent. Related concepts arranged around it. Labeled edges show relationships.

