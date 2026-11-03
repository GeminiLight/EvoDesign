## Swimlane

### Common
- Best for cross-role processes and responsibility division.
- Identity signal: parallel lanes combining ownership and flow.

#### Visual Pattern
Nodes aligned on horizontal centerline within each lane:
```
┌─────────────────────────────────────────┐
│ User │ [Request] ──► [Approve]          │
├─────────────────────────────────────────┤
│System│ [Process] ──► [Notify]           │
├─────────────────────────────────────────┤
│  DB  │ [Store]                         │
└─────────────────────────────────────────┘
```

### Structure
- Each lane represents a role or department and acts as an explicit ownership container.
- All nodes, including terminators, should belong to exactly one lane.
- Activities and decisions are connected by arrows, and handoff edges may cross lanes.
- No orphan nodes should sit outside the lane system.
- [Budget] process steps; one group per actor (3-6 lanes max); edges for handoffs + in-lane progression
- [Edge Rules] Expected count: handoffs + in-lane progression. Cross-lane edges only for handoffs. In-lane edges for progression. Cross-lane handoff edges MAY carry a short label (≤3 words, e.g. 'Submit Order', 'Notify'). In-lane progression edges: no label.

### Styling
- Use rectangles or frames to define swimlanes.
- Use rectangles for activities and diamonds for decisions.
- Keep lane boundaries visually explicit so ownership remains clear.

### Layout
- [Detailed Layout Instructions]
  - `chart_type=="swimlane"` with non-empty `groups` → **horizontal swimlane layout — geometric uniformity is mandatory**:
      1. **All lane backgrounds share the SAME `w` AND the SAME `h`.** Pick lane height proportional to content density: if content is sparse (3-5 nodes per lane), use ~380-450px; if dense (6+ nodes), reduce to ~300-350px. Lane width spans the canvas (e.g. 2400-2600 px). All lanes use these IDENTICAL dimensions — never let one lane be "tall enough for its content" and another shorter.
      2. **Lanes stack vertically with NO gap.** lane_k.y = lane_0.y + k * lane_h, all sharing the same lane.x (e.g. 100). Lane order matches the order of `groups[*]` in Structure output.
      3. **Within each lane, all nodes share a horizontal centerline.** Compute mid_y = lane.y + lane.h/2; every node in the lane has its y set so the node's vertical center equals mid_y (i.e. node.y = mid_y - node.h/2), with at most ±25 px stagger to avoid edge overlap on convergence. Nodes must NOT cascade diagonally down the canvas — that breaks swimlane semantics and reads as a flowchart.
      4. **Within each lane, distribute nodes evenly along the x-axis** in chronological / process order (derive from edges via topological sort restricted to the lane). Spacing: first node at x = lane.x + 80; subsequent nodes spaced uniformly so the last node's right edge stays ≤ lane.x + lane.w - 80. Aim for `≥ 60 px` gap between adjacent nodes.
      5. **Lane title (`{{{group_id}}}:title`)** sits in the top-left of its lane background: `x = lane.x + 16`, `y = lane.y + 12`, `w ≈ 200`, `h ≈ 28`. Same title geometry across all lanes.
      6. **Cross-lane handoff edges**: source.side and target.side per the standard SIDE SELECTION RULES; the edge will route from one lane's node down/up into another lane's node. Don't try to manually shape these — the renderer handles it.
      The discipline above is non-negotiable: swimlane visual identity comes from HOMOGENEOUS lane geometry. Heterogeneous lane sizes or staggered y-positions look like a generic flowchart, not a swimlane.
- Primary family: Containerized Flow / Banded Flow with HORIZONTAL lanes by default.
- Pick lane geometry FIRST, then place every node by its lane membership. Do NOT freestyle node positions and try to fit lanes around them.
- All lanes MUST share identical width AND identical height — never size lanes to their content. Derive lane_h from content density: use canvas_h/num_lanes for ≥5 lanes; for 3-4 lanes use a fixed ~380-450px proportional to the actual node count. Lane_w spanning the canvas (~2400-2600px), then apply those exact same dimensions to every lane.
- Lanes stack vertically with NO gap (lane_k.y = top_margin + k * lane_h) and share the same lane.x. The lane background's geometry IS the lane.
- LANE CONTAINMENT IS NON-NEGOTIABLE: every node n with parent lane MUST satisfy lane.y <= n.y AND n.y + n.h <= lane.y + lane.h. The canonical placement is node.y = lane.y + lane.h/2 - node.h/2 (lane horizontal centerline). A ±25px stagger is allowed ONLY when an arrow collision demands it.
- If you ever find a node with y outside its parent lane's [lane.y, lane.y+lane.h] band, the layout is broken — re-derive the y from the centerline formula. y values like 20, 180, 340, 500 are flowchart-rank values and break lane membership.
- Within a lane, nodes are spaced EVENLY along x in chronological / process order with >=60px gaps. The first node in the process starts around lane.x + 200 to clear the title block.
- Lane titles sit in the top-left of their lane background (x = lane.x + 16, y = lane.y + 12, fixed size).
- Cross-lane handoff edges use orthogonal routing; the renderer derives the path from start/end side choices. start.side / end.side should be top / bottom for vertical handoff, right / left for in-lane progression.
- [Geometry] Geometry first: all lanes share identical lane_h and lane_w. Derive lane_h from content density (canvas_h/num_lanes for many lanes, ~380-450px for sparse lanes). Lanes stack vertically with NO gap: lane_k.y = top_margin + k * lane_h. Every node centerline: n.y = lane.y + lane.h/2 - n.h/2. Nodes spaced ≥60px in process order. First node at lane.x + ~200. Lane title at (lane.x+16, lane.y+12). Self-check: lane.y ≤ n.y AND n.y + n.h ≤ lane.y + lane.h.
