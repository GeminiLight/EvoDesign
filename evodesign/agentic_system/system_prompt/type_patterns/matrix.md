## Matrix

### Common
- Best for multi-dimensional comparison.
- Identity signal: a labeled grid with row/column semantics.

#### Visual Pattern
```
            │ Fast │ Slow │
────────────┼──────┼──────┤
High Impact │  A   │  B   │
Low Impact  │  C   │  D   │
```

### Structure
- Use explicit row and column semantics so every cell has clear ownership.
- Cells represent the intersection of row and column categories.
- Avoid unlabeled axes or ambiguous cell meaning.
- [Budget] 1 per cell (≤ rows × cols); 0 groups (grid is the organizer); [] edges
- [Edge Rules] Expected count: 0. Cells communicate by position.

### Styling
- Use rectangles to create a structured grid.
- Use darker or more prominent headers to distinguish the axes.
- Use cell colors or shades to encode values when needed.

### Layout
- [Detailed Layout Instructions]
  - `nodes[*].row` + `nodes[*].col` present → **grid snap**: uniform row heights and column widths; a node with row=r and col=c lands at approximately `(x0 + c*cell_w, y0 + r*cell_h)`.
- Primary family: Grid / Matrix.
- Align rows and columns precisely.
- Keep cell sizing and spacing consistent across the grid.
- Preserve strong axis readability so comparisons are easy to scan.
- [Geometry] Uniform grid. Rows × columns. Cell labels centered. Grid lines are the organizer — NO connecting arrows. Row/column headers at edges.
