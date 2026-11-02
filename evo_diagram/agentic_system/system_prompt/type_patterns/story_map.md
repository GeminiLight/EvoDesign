## Story Map

### Common
- Best for planning a product by the user's journey: the activities in order across the top, the stories under each, sliced into releases.
- Identity signal: a row of activities across the top, stories in columns beneath them, and horizontal release bands cutting across.

#### Visual Pattern
```
 [Browse]      [Choose]       [Pay]          [Track]       ← activities
┌ Release 1 (MVP) ──────────────────────────────────────────┐
│ [Search]     [Add to cart]  [Card payment] [Order status] │
└───────────────────────────────────────────────────────────┘
┌ Release 2 ────────────────────────────────────────────────┐
│ [Filters]    [Wishlist]     [Wallets]      [Push alerts]  │
└───────────────────────────────────────────────────────────┘
```

### Structure
- Activities: 3-7 nodes with `class: "activity"`, in the order the user
  does them. Activities belong to no group.
- Stories: nodes that each carry `activity` (the id of the activity they
  serve) and belong to exactly one release group.
- Releases: one group per release slice, 1-4, in delivery order. Use the
  source's names ("MVP", "Release 2"); when it gives priorities instead of
  releases, use them as the slices ("Must", "Should", "Could").
- Keep 1-4 stories per activity per release. An activity may have no story
  in a release.
- Choose `story_map` when the source plans work by user activity and
  release. A plain backlog without activities is a `kanban`; dated tasks
  are a `gantt`.
- [Budget] activities (3-7) + stories (≤ 24); one group per release (1-4); [] edges
- [Edge Rules] Expected count: 0. Column means "serves this activity", band means "ships in this release"; never draw arrows.

### Styling
- Activities use one stronger card style; stories use a lighter card style.
- Release bands use very light fills that differ slightly from one release
  to the next, the first release the strongest.

### Layout
- Primary family: Activity grid.
- Give every activity one column of equal width; put the activities in a
  row across the top.
- Stack the release bands below the activity row, each spanning all
  columns, the same width, 16px apart, in delivery order. Each band's height
  fits its tallest column of stories.
- Inside a band, place each story in its activity's column, stacked top
  down. Put the release name at the band's top-left.
- [Geometry] Activity row across the top, one equal column per activity. Full-width release bands below in delivery order. Each story sits in its activity's column inside its release band. NO arrows.
