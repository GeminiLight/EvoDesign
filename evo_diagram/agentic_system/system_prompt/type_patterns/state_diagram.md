## State Diagram

### Common
- Best for state transitions and lifecycles.
- Identity signal: lifecycle states connected by labeled transitions.

#### Visual Pattern
States as rounded rectangles, initial state as solid ellipse, end state as double ellipse:
```
      ◉               ◎
   Initial          End
     │               ▲
     │ login         │ logout
     ▼               │
  ┌─────────┐        │
  │  Idle   │        │
  └────┬────┘        │
       │ submit      │
  ┌────┴────┐        │
  │ Active  │◄───────┘
  └────┬────┘  retry
       │ complete
       ▼
  ┌─────────┐
  │ Success │
  └────┬────┘
       │
       ▼
      ◎
     End
```

### Structure
- Use distinct roles for states, the initial state, and the end state.
- Transitions should carry labels for trigger conditions when needed.
- The semantics center on lifecycle transitions rather than generic process sequencing.
- [Budget] process steps + decisions; 0-2 phase bands; one edge per drawn transition (≈ n to n+branches)
- [Edge Rules] Expected count: n to n+branches. Every edge carries a label (the trigger/event). Forward transitions use straight routing; self-loops and reverse/feedback transitions MUST use routing: 'curved'.

### Styling
- Use rounded rectangles for states.
- Use a solid ellipse for the initial state and a double ellipse (concentric) for the end state.
- Keep transition labels readable on or near the arrows.

### Layout
- Arrange states according to the logical flow of transitions.
- Do not compress all states into a single timeline-like row when loops or alternate transitions exist; use a two-dimensional arrangement with dedicated loop corridors.
- Keep the initial and terminal pseudo-states compact and visually distinct from normal states.
- Leave enough space for alternate paths or loops where necessary.
- Reserve explicit space above or below the main progression for feedback loops so reverse transitions do not overlap the primary path.
- Preserve enough vertical and horizontal spread that the diagram reads as a lifecycle state graph rather than a flattened process strip.
- Preserve a readable lifecycle progression through the diagram.
- [Geometry] States as rectangles or rounded-rectangles. Transitions as labeled arrows. Start/end with ellipses. Arrange in lifecycle flow. Forward transitions: straight. Self-loops and feedback returns: curved.
