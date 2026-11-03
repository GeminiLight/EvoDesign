## Layer Stack

### Common
- Best for abstraction levels where each level is built on the one below it.
- Identity signal: full-width horizontal bands stacked from top to bottom, no flow arrows.

#### Visual Pattern
```
┌───────────────────────────────────────┐
│ Applications   [Web]  [Mobile]  [CLI] │
├───────────────────────────────────────┤
│ Services       [Auth]  [Billing]      │
├───────────────────────────────────────┤
│ Platform       [Kubernetes]  [Queue]  │
├───────────────────────────────────────┤
│ Infrastructure [Compute]  [Storage]   │
└───────────────────────────────────────┘
```

### Structure
- One group per layer, 3-6 layers. Order groups from the most user-facing or
  abstract layer (first) to the foundation (last); the order is the meaning.
- Each layer group holds the parts the source names for that layer, 1-5 per
  layer. A layer the source names without parts holds one node that repeats
  the layer's role in a few words (e.g. "Bare-metal servers"), never a
  placeholder.
- Every node belongs to exactly one layer. A component that spans several
  layers belongs to the lowest layer that owns it.
- Use a layer stack only when the source describes "sits on", "built on" or
  "provides to the layer above". If the source describes requests or data
  moving between components, use `architecture` instead.
- When the source states how the layers relate ("each layer only uses the
  one below", "requests go down, events come up"), add one node with
  `class: "axis"` whose label states that rule in at most 8 words. It
  belongs to no group. Omit it when the source states no such rule.
- [Budget] parts per layer (1-5) + optional 1 rule caption; one group per layer (3-6); [] edges
- [Edge Rules] Expected count: 0. Vertical order encodes "built on"; never draw arrows between layers.

### Styling
- Give each layer its own palette family; adjacent layers never share a
  family, so a reader can tell the layers apart at a glance.
- Parts inside a layer share one card style; the band title carries the
  layer name.
- Keep band borders thin; the bands should touch or nearly touch.

### Layout
- Primary family: Banded stack.
- All bands share the same x, the same width and the same height; stack them
  top to bottom in group order with a gap of at most 8px.
- Put the layer title at the left of its band, vertically centred, and lay
  the parts out left to right after it, evenly spaced and vertically centred.
- Size the shared band width from the layer with the most parts.
- Place the rule caption, if any, as plain text to the right of the stack,
  vertically centred on it.
- [Geometry] Stacked full-width bands, one per layer, equal width and height, top-to-bottom in group order. Layer title at the band's left; parts in one row inside the band. NO arrows.
