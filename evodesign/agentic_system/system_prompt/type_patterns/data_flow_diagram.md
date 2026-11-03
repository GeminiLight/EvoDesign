## Data Flow Diagram

### Common
- Best for data flow and processing procedures.
- Identity signal: external entities and stores connected through labeled process flows.

#### Visual Pattern
External entities at edges, processes in center, data stores between them:

```
  ┌──────────┐
  │ Customer │
  └────┬─────┘
       │
       ▼ order
    ┌──────┐
    │Verify│
    └──┬───┘
       │
   ┌───┴────┐
   │Inventory│◄──────┐
   └────┬───┘       │
        │            │
        ► Ship ──────┘
       │
       ▼
    ┌──────┐
    │Payment│
    └──┬───┘
       │
       ▼
  ┌──────────┐
  │ Warehouse│
  └──────────┘
```

### Structure
- Use separate roles for external entities, processes, and data stores.
- Data flow is expressed by directed, labeled arrows.
- Processes mediate movement and transformation of data between actors and stores.
- [Budget] external entities + processes + data stores; no phase bands; one edge per drawn data flow (≈ n to n+2)
- [Edge Rules] Expected count: n to n+2 where n = node count. Every edge MUST carry a label (the data name or trigger). NO unlabeled data flows.

#### DFD Levels
- **Context (Level 0)**: Single process, external entities only
- **Level 1**: Main processes, data stores appear
- **Level 2+**: Detailed sub-processes

### Styling
- Use rectangles for external entities and ellipses for processes.
- Use specially styled rectangles for data stores.
- Attach readable labels to arrows to name the data being transferred.

### Layout
- Place external entities around the perimeter and keep processes near the center.
- Route labeled flows to preserve readability around the central process area.
- Make source-to-destination data movement visually obvious.
- [Geometry] Top-to-bottom or left-to-right. Processes as rectangles, data stores as parallel lines, external entities as rectangles. Data flows as labeled arrows.

#### Layout Tips
- External entities at edges
- Processes in center
- Data stores between related processes
- Label every arrow with data name
