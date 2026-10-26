## Flowchart

### Common
- Best for processes, steps, and decision logic.
- Identity signal: sequential boxes connected by directional arrows.
- Identity risk: if abstract control language gets expanded into extra helper nodes, or if retry loops visually overpower the main path, the result stops reading as a clear deliverable flowchart.

#### Standard Flowchart Symbols
| Shape | Meaning | Excalidraw Type |
|-------|---------|-----------------|
| Rounded rectangle | Start/End (Terminal) | `rectangle` with `roundness` |
| Rectangle | Process/Action | `rectangle` |
| Diamond | Decision | `diamond` |
| Parallelogram | Input/Output | `rectangle` rotated or use lines |
| Circle | Connector/Reference | `ellipse` |

#### Visual Pattern: Standard Process Flow
Continuous spine with decision diamonds:

```
   ┌──────┐
   │ Start│
   └──┬───┘
      │
      ▼
   ┌──────┐     Yes     ┌──────┐
   │Check │────────────►│Process│
   │ Age? │             └──┬───┘
   └──┬───┘                │
      │ No                 ▼
      ▼                 ┌──────┐
   ┌──────┐             │ Save │
   │Reject│             └──┬───┘
   └──────┘                │
                            ▼
                         ┌──────┐
                         │ End  │
                         └──────┘
```

### Structure
- Use terminator-like start/end nodes, process steps, and decision nodes as the core semantic roles.
- Arrows connect nodes in a directional sequence and should stay anchored to elements.
- Decision nodes should branch into multiple conditional paths, and branch edges can carry labels such as Yes/No.
- Avoid orphan nodes without incoming or outgoing flow context.
- When the source uses abstract governance language such as validation, evaluation, control, monitoring, or access enforcement, do not automatically materialize each verb as a separate visible helper node; prefer the explicitly named user-facing steps, outcomes, and decisions unless the text clearly separates an additional step.
- Do not insert a generic error router, generic account-status gateway, or second-order helper check when the source already names the concrete outcomes that matter to the reader.
- Do not invent feedback loops from a successful end state back to login, start, or reset unless the source explicitly describes a logout, restart, or cyclical session reset path.
- [Budget] process steps + decisions; 0-2 phase bands if source clearly segments; one edge per drawn transition (≈ n to n+branches)
- [Edge Rules] Expected count: n to n+branches. Decision branch edges carry Yes/No labels. Non-decision edges: no label.

### Styling
- Use ellipses for Start/End nodes, rectangles for process steps, and diamonds for decisions.
- Use blue as the primary palette.
- Highlight decision points with orange.
- Keep directional arrows and any decision labels visually readable.
- Recovery or retry paths may use a warning or error accent, but they should remain visually secondary to the primary happy-path spine rather than dominating the whole page.

#### Color Coding for Flowcharts — use the current palette
- Start/End: green family
- Process: blue family
- Decision: yellow family
- Error/Exception: red family

### Layout
- Primary family: Flow.
- Arrange the diagram top-to-bottom or left-to-right with a clear directional path.
- Keep the primary spine continuous. Decision nodes should stay on or immediately adjacent to the main spine instead of jumping to a distant side zone.
- Decision branches should diverge cleanly from the main axis.
- Place branch targets near their branch corridor so conditional edges do not create long diagonal jumps or long return-to-spine detours.
- When logic rejoins, place merge or end nodes near the natural convergence area and prefer short, legible branch connectors over decorative spread.
- Merge paths should converge back to the main flow when the logic rejoins.
- Keep the success path as the dominant readable spine, and place failure or recovery branches beside the specific decision that produced them instead of introducing a new central branch tower or secondary decision stack.
- If several recovery outcomes return to the same checkpoint, route them through one outer retry corridor on a side of the diagram so the return geometry does not stack over the center of the main path.
- Keep downstream checks local to the step that truly introduces them, but do not split one compact path into extra helper stages unless the source explicitly separates those stages.
- [Geometry] Top-to-bottom or left-to-right. Keep primary spine continuous. Decision branches diverge cleanly from main axis. Merge paths converge back to main flow. Place branch targets near their branch corridor.
