## Kanban

### Common
- Best for work in progress: which items sit in which state right now, with limits and blocked items.
- Identity signal: equal columns named by workflow state, each holding a stack of cards.

#### Visual Pattern
```
┌ To do ─────┐┌ In progress 3/4 ┐┌ Review ─────┐┌ Done ──────┐
│ [Login UI] ││ [Search API]    ││ [Billing]   ││ [Onboard]  │
│ [Exports]  ││ [Dark mode] ⛔  ││             ││ [Alerts]   │
│            ││ [SSO]           ││             ││            │
└────────────┘└─────────────────┘└─────────────┘└────────────┘
```

### Structure
- One group per workflow state, 3-6 states, in the order work moves. The
  group label is the state name; when the source gives a WIP limit, append
  the number of items you place in that column and the limit ("In progress
  3/4" for three items under a limit of four). Count the items; never copy
  the limit as the count.
- Each work item is a node in exactly one state: a short title (2-5 words).
  Keep the source's owner or tag only when it gives one, as a second line.
- Mark an item the source calls blocked, stuck or waiting with
  `class: "blocked"`.
- Use at most 20 items. Never invent items to fill an empty column; an empty
  column stays empty.
- Choose `kanban` for a snapshot of where items are. Steps one item goes
  through over time are a `flowchart`; scheduled dates are a `gantt`.
- [Budget] items (3-20); one group per state (3-6); [] edges
- [Edge Rules] Expected count: 0. Column position is the state; never draw arrows between cards or columns.

### Styling
- Columns share one very light fill and a thin border; cards share one
  white or light card style.
- Blocked cards use a warm warning tint and a stronger border.
- The column holding the most active work (usually "In progress") may use
  a slightly stronger column tint.

### Layout
- Primary family: Column board.
- Columns share one width and one height, side by side with a 16px gap,
  tops aligned. Size the height from the fullest column.
- State names (and limits) sit at the top of each column.
- Cards stack top to bottom inside their column, full column width minus
  16px padding, 12px apart, in the order the source lists them.
- [Geometry] Equal-width, equal-height columns left to right in workflow order. Cards stacked top-down inside each column. NO arrows.
