## Quadrant

### Common
- Best for positioning items against two scales, such as impact vs effort.
- Identity signal: two crossing axes split the plane into four named regions with items placed inside.

#### Visual Pattern
```
 Impact ▲
        │  Big bets      │  Quick wins
        │   (A)          │      (B) (C)
        ├────────────────┼────────────────
        │  Money pits    │  Fill-ins
        │       (D)      │   (E)
        └────────────────┴───────────────▶ Ease
```

### Structure
- Exactly four groups, one per quadrant, in this order: top-left, top-right,
  bottom-left, bottom-right. Each group label names the quadrant ("Quick
  wins"); use the source's names, or describe both scales ("High impact ·
  Low effort") when it gives none.
- Each item is a node that belongs to exactly one quadrant group. Use 3-12
  items; a quadrant may be empty.
- Add exactly two axis nodes with `class: "axis"`: one for the horizontal
  scale and one for the vertical scale. Label each with the scale name and
  its direction ("Ease →", "Impact ↑"). Axis nodes belong to no group.
- Choose `quadrant` when items are placed by two scales. If every cell is a
  category to fill with text, use `matrix` or `swot` instead.
- [Budget] items (3-12) + 2 axis nodes; exactly 4 quadrant groups; [] edges
- [Edge Rules] Expected count: 0. Position encodes both scales; never connect items.

### Styling
- Quadrant regions use very light fills; give the most desirable quadrant
  (usually top-right) a slightly stronger tint than the other three.
- Items are compact cards or pills, smaller than the quadrant titles.
- Axis nodes are plain text with no border.

### Layout
- Primary family: Two-axis plane.
- Draw the four quadrant regions as one 2x2 block of equal squares, at least
  320x320 each, touching along the two centre lines.
- Place the horizontal axis node centred below the block and the vertical
  axis node left of the block, vertically centred.
- Inside each quadrant, put the title at the top corner farthest from the
  centre, and spread the items so none overlap; place an item nearer the
  centre lines when the source calls it borderline.
- [Geometry] 2x2 block of equal quadrants meeting at the centre. Axis labels outside the block: horizontal below, vertical to the left. Items inside their quadrant, no overlaps. NO arrows.
