## User Journey

### Common
- Best for what one person does across the stages of an experience, and how each stage feels.
- Identity signal: stage columns left to right, with the person's actions above and a feeling curve below.

#### Visual Pattern
```
 Discover      │ Sign up        │ First use      │ Renew
 [Sees ad]     │ [Fills form]   │ [Imports data] │ [Gets invoice]
 [Reads blog]  │ [Verifies mail]│ [Hits error]!  │ [Pays]
───────────────┼────────────────┼────────────────┼──────────────
  ● curious ───┼──● hopeful     │                │   ● relieved
               │         ╲      │                │  ╱
               │          ╲─────┼──● frustrated ─┼─╱
```

### Structure
- One group per stage, 3-7 stages, in the order the person lives them. The
  group label is the stage name.
- Each stage holds 1-3 action nodes (what the person does, 2-5 words) and
  exactly one feeling node with `class: "feeling"`, a short label for the
  feeling ("Frustrated", "Hopeful") and an integer `score` from 1 (worst)
  to 5 (best). Use the source's words for the feeling; when it gives none,
  infer the score from what it says happens and keep the label neutral.
- Mark an action the source calls a problem, delay or complaint with
  `class: "pain"`.
- Edges connect each stage's feeling node to the next stage's feeling node
  and nothing else; together they draw the feeling curve.
- Choose `user_journey` when the source follows one person or persona and
  says how they feel. Several actors handing work to each other is a
  `swimlane`.
- [Budget] stages (3-7) × (1-3 actions + 1 feeling); one group per stage; edges between consecutive feeling nodes only (stages − 1)
- [Edge Rules] Expected count: stages − 1, feeling node to the next feeling node. Drawn without arrowheads. NO labels.

### Styling
- Stage columns share one very light fill; action nodes share one card style.
- Pain actions use a warm warning tint (red or orange family) so problems
  stand out.
- Feeling nodes are small pills; colour them from a cool tint at score 5 to
  a warm tint at score 1.

### Layout
- Primary family: Stage columns.
- Stage columns share one width and one height and sit side by side with no
  gap; stage names sit at the top of each column.
- Stack the actions in the upper part of the column.
- Start the feeling band 40px below the tallest action stack and make it
  about 200px tall; end every column 24px below the band. Never leave empty
  space between the actions and the feelings.
- Place each feeling node centred in its column at a height set by its
  score: score 5 at the top of the band, score 1 at the bottom.
- [Geometry] Equal stage columns left to right, as short as the content allows. Actions stacked at the top of each column. Feeling band (≈200px) directly below the tallest action stack; feeling nodes placed by score (5 high, 1 low), joined left to right into one curve.
