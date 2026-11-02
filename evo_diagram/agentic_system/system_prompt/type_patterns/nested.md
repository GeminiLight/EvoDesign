## Nested

### Common
- Best for hierarchy expressed as scope: what sits inside what.
- Identity signal: boxes drawn inside boxes, the outermost scope enclosing everything.

#### Visual Pattern
```
┌ Organization ─────────────────────────────┐
│ ┌ Workspace ──────────────┐ ┌ Billing ──┐ │
│ │ ┌ Project ────────────┐ │ │ [Invoice] │ │
│ │ │ [Board]  [Document] │ │ └───────────┘ │
│ │ └─────────────────────┘ │               │
│ └─────────────────────────┘               │
└───────────────────────────────────────────┘
```

### Structure
- Model every scope that contains something as a group, and every leaf item
  as a node. Nest groups with `parent_group_id`; a top-level scope has none.
- Use 2-4 levels of nesting and 3-10 leaf nodes. Deeper hierarchies belong in
  a `tree`; containment is what makes this type worth drawing.
- Every leaf node is a member of the innermost scope that holds it, and
  every scope except the outermost has exactly one parent scope. List a
  leaf only in that innermost scope's `members`; an outer scope contains
  inner ones through their `parent_group_id` and never repeats their leaves.
- A scope with no leaves of its own must contain at least one child scope;
  drop empty scopes.
- Choose `nested` over `tree` when the source says "inside", "within",
  "belongs to" or "scoped to"; choose `tree` when it says "reports to",
  "is a kind of" or lists children without scope.
- [Budget] leaf items (3-10); one group per scope (2-4 levels deep); [] edges
- [Edge Rules] Expected count: 0. Containment carries the relation; never draw arrows from a scope to its contents.

### Styling
- Tint scopes from light (outermost) to slightly darker (innermost) within
  one palette family, so depth is readable at a glance.
- Scope titles sit at the top-left inside each boundary, smaller and quieter
  than leaf labels.
- Leaf nodes use one card style and stay the most prominent ink on the page.

### Layout
- Primary family: Containment.
- Place the innermost scopes first, size each scope from its contents, then
  wrap it in its parent: 24px side padding and about 40px at the top for the
  title.
- Sibling scopes sit side by side with at least 24px between them; align
  their tops.
- Leaves inside one scope form one row, or a compact grid when there are more
  than four.
- [Geometry] Concentric containment. Each scope's box encloses all of its children with uniform padding and a title band at the top. Siblings side by side, tops aligned. NO arrows.
