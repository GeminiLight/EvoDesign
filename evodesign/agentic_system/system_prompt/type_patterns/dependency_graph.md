## Dependency Graph

### Common
- Best for what depends on what: packages, services, tasks or requirements, including shared prerequisites and cycles.
- Identity signal: directed arrows from each item to the items it needs, arranged in layers by depth.

#### Visual Pattern
```
┌──────┐   ┌──────┐
│ web  │   │ cli  │          (dependents)
└──┬───┘   └──┬───┘
   ▼          ▼
   ┌──────────┐
   │   core   │──────┐
   └────┬─────┘      ▼
        ▼        ┌──────┐
   ┌────────┐    │ log  │   (prerequisites)
   │ utils  │    └──────┘
   └────────┘
```

### Structure
- One node per item the source names. Every edge points from the dependent
  to its prerequisite (`web → core` means web depends on core).
- Keep only direct dependencies the source states. Drop an edge implied by a
  longer path (if a→b and b→c, do not add a→c) unless the source names it.
- Keep a cycle when the source describes one; it is usually the point of the
  diagram.
- Shared prerequisites (several items depending on one) are expected; never
  duplicate a node to avoid fan-in.
- Use 0-3 groups only when the source assigns items to packages, teams or
  repositories.
- Choose `dependency_graph` over `tree` whenever any item has two dependents
  or the source names a cycle.
- [Budget] items (4-14); 0-3 groups for packages; one edge per direct dependency
- [Edge Rules] Expected count: one per stated dependency. Direction: dependent → prerequisite. No labels unless the source qualifies the dependency (e.g. "optional", "dev only").

### Styling
- Items share one card style; give items with no dependents (the entry points)
  and items with no prerequisites (the foundations) distinct but quiet tints.
- Edges are thin, single-headed arrows in one ink.
- Optional or dev-only dependencies use dashed lines.

### Layout
- Primary family: Layered DAG.
- Assign each item a depth: items nothing depends on sit in the top row;
  each prerequisite sits at least one row below everything that depends on it.
- Order items within a row to minimise crossings; centre a shared
  prerequisite under its dependents.
- Edges run downward. A cycle's back edge routes around the side as an
  elbowed path rather than through other nodes.
- [Geometry] Layered top-to-bottom: dependents above prerequisites, one row per depth, rows evenly spaced. Edges point downward; back edges in a cycle route around the side.
