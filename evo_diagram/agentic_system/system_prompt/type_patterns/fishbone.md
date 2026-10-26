## Fishbone

### Common
- Best for causal analysis and root cause decomposition.
- Identity signal: a main spine with alternating cause branches converging on an effect.

#### Visual Pattern
Left-to-right spine with alternating cause branches converging on effect:
```
                          ┌─────────┐
                          │ Effect  │
                          └────┬────┘
                               ▲
                               │
    ┌──────────────────────────┘
    │
    ├─ Cause 1
   ╱
CatA
   ╲
    ├─ Cause 2
    │
════╪══════════════════════════════════►
    │
    ├─ Cause 3
   ╱
CatB
   ╲
    ├─ Cause 4
    │
    └─ Cause 5
```

### Structure
- Use one effect or result node at the head of the spine.
- Cause-category nodes connect directly to the main spine.
- Sub-cause nodes connect to their parent cause category, not directly to the spine or effect node.
- The diagram should encode causal decomposition rather than generic network linking.
- [Budget] causes; 0 groups (fishbone spine drawn in layout); labeled relation per link
- [Edge Rules] Expected count: labeled relation per link. Labels carry cause category or sub-cause.

### Styling
- Use a thick arrow as the main spine and thinner arrows for branches.
- Use different colors for major branches to distinguish categories.
- Main spine edges should use heavier stroke than category bones, and sub-cause branches should be thinner still.
- Text-only or very light-weight nodes can be used so the causal skeleton stays dominant.

### Layout
- Primary family: Spine / Causal.
- Use a left-to-right horizontal spine.
- Distribute cause branches alternately above and below the spine.
- Place sub-causes off their parent branch at a shallower angle and preserve regular spacing between major categories.
- [Geometry] Spine drawn horizontally (or vertically). Main cause categories branch off spine at angles. Sub-causes branch off category lines. Effect/result at spine head.
