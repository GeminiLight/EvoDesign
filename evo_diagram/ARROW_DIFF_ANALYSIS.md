# Arrow / Diagram Quality Comparison: Dev vs Baseline

## 1. Goal

Precisely compare the diagram output quality between:
- **Dev** (`evo-diagram-dev`, current branch `refactor/model-config-split`, HEAD)
- **Baseline** (`evo-diagram-baseline`, the GitHub reference implementation)

For the **same input example** (architecture example 1, ID `architecture_20251204_203338_119`), identify every visual difference, trace each difference back to its root cause in the code/algorithm design, and determine whether the dev branch has regressed relative to baseline or improved.

## 2. User's Real Intent

The user observed that "现在的箭头和之前实现的那个箭头差别那么大" (the arrows now look very different from the previous implementation). The core questions they want answered:

1. **Is arrow routing worse?** Did the `edge_router.py` / `arrow_adder.py` polyline algorithm get broken or downgraded?
2. **Is the upstream LLM output different?** Do Structure/Styling/Layout agents now emit a different graph topology, colors, or positions?
3. **Is there a render pipeline regression?** Did converter, shape_size_fitter, or normalizer introduce visual artifacts?
4. **What should be fixed?** If dev is worse, which code file and which logic needs to change to restore baseline quality?

The user explicitly does **not** want manual JSON patches. They want **algorithm design-level fixes** (prompts, converter logic, workflow orchestration).

## 3. Inputs

### 3.1 Result Artifacts (PNG + JSON)

| Source | Path |
|--------|------|
| Baseline PNG | `~/tfwang/code/evo-diagram-baseline/results/evodiagram/unknown/architecture_20251204_203338_119/4_render/diagram_manifest.png` |
| Baseline Structure | `~/tfwang/code/evo-diagram-baseline/results/evodiagram/unknown/architecture_20251204_203338_119/1_structure/structure_instantiation.json` |
| Baseline Layout | `~/tfwang/code/evo-diagram-baseline/results/evodiagram/unknown/architecture_20251204_203338_119/3_layout/layout_instantiation.json` |
| Dev PNG | `~/tfwang/code-evo-diagram-dev/results/evodiagram/gpt-5.5/architecture_20251204_203338_119_baseline-recovered/4_render/diagram_manifest.png` |
| Dev Structure | `~/tfwang/code-evo-diagram-dev/results/evodiagram/gpt-5.5/architecture_20251204_203338_119_baseline-recovered/1_structure/1_structure_instantiation.json` |
| Dev Layout | `~/tfwang/code-evo-diagram-dev/results/evodiagram/gpt-5.5/architecture_20251204_203338_119_baseline-recovered/3_layout/3_layout_instantiation.json` |

### 3.2 Codebases

| Component | Baseline Path | Dev Path |
|-----------|--------------|----------|
| Arrow adder | `evo-diagram-baseline/evo_diagram/agentic_system/render_engine/excalidraw/arrow_adder.py` | `evo-diagram-dev/evo_diagram/agentic_system/render_engine/excalidraw/arrow_adder.py` |
| Edge router | `evo-diagram-baseline/evo_diagram/agentic_system/render_engine/excalidraw/edge_router.py` | `evo-diagram-dev/evo_diagram/agentic_system/render_engine/excalidraw/edge_router.py` |
| Converter | `evo-diagram-baseline/evo_diagram/agentic_system/render_engine/excalidraw/converter.py` | `evo-diagram-dev/evo_diagram/agentic_system/render_engine/excalidraw/converter.py` |
| Layout prompts | `evo-diagram-baseline/evo_diagram/agentic_system/generation_stage/layout/prompts.py` | `evo-diagram-dev/evo_diagram/agentic_system/generation_stage/layout/prompts.py` |
| Structure prompts | `evo-diagram-baseline/evo_diagram/agentic_system/generation_stage/structure/prompts.py` | `evo-diagram-dev/evo_diagram/agentic_system/generation_stage/structure/prompts.py` |

### 3.3 Known Code Diff (Dev HEAD vs origin/main)

From prior analysis:
- `arrow_adder.py`: **0 diff** vs origin/main
- `edge_router.py`: **0 diff** vs origin/main
- `converter.py`: +14 lines (ghost parent-group skip logic)
- `layout/prompts.py`: sequence rule expanded (+7 detailed rules), ER rule added
- `structure/prompts.py`: +18 lines

## 4. Key Finding: Topology is the Root Cause

**Dev is NOT worse at arrow routing. Dev is worse at extracting the graph topology.**

### 4.1 Edge Count Difference

| Source | Edge Count | Key Missing Edges |
|--------|-----------|-------------------|
| **Baseline** | 10 | — |
| **Dev** | 6 | UI Components→UI Process; Business Workflows→Data Access; Business Components→Data Access; Business Entities→Data Access |

Baseline extracts a **complete layered DAG** with lateral connections (Presentation layer internal flow) and convergent downstream edges (all Business nodes → Data Access). Dev extracts a **simplified tree** with only the vertical backbone.

### 4.2 Why StructureAgent Drops Edges

Comparing `structure/prompts.py` baseline vs dev, the dev prompt added:

1. **Intent Decoding step**: LLM must first define "the ONE story the reader must understand." For architecture diagrams, this nudges the model toward a simplified "layered service flow" narrative, causing it to discard lateral/containment-implied connections.

2. **Stricter 3-check Visual Necessity Filter**: "irreplaceable / not implied by containment / adds clarity." The LLM (gpt-5.5) interprets:
   - `UI Components → UI Process`: "both live in Presentation Layer, so containment implies the relation → drop"
   - `Business_* → Data Access`: "layered architecture implies downstream flow → drop as redundant"

3. **Same budget rule, different obedience**: Both prompts say `architecture → ≤n/2`, but baseline's LLM ignored it (10 edges for ~10 nodes), while gpt-5.5 strictly enforces it (6 edges ≈ n/2).

**Result**: The dev StructureAgent over-pruned the architecture graph, producing a topology so sparse that the downstream Layout and Render stages have no choice but to draw a bare-bones vertical tree.

### 4.3 Visual Impact

| Aspect | Baseline | Dev (HEAD) | Root Cause |
|--------|----------|------------|------------|
| **Topology** | Full DAG (10 edges) | Sparse tree (6 edges) | StructureAgent over-pruning |
| **Arrow routing** | Mixed H/V L-shapes, compact | Mostly vertical + fan-out | Fewer edges → fewer routing opportunities |
| **Layout spacing** | Tight, layers ~200-250px | Looser, layers ~380px | LayoutAgent has fewer edges to constrain packing |
| **Edge labels** | "requests", "process" | None | StructureAgent omitted edges, so labels vanished |
| **Group fit** | Tight around 3 nodes + return edge | Large empty space | Fewer edges → less geometric constraint |

## 5. Sequence Diagram Finding (Separate Issue)

The sequence diagram quality problem is **unrelated** to the architecture edge-pruning issue.

**Root cause**: LayoutAgent generates `lane_*` elements for sequence diagrams but omits the `shape` field (`type=null, shape=null`). The converter's defensive skip logic (`if "type" not in element_data and "shape" not in element_data: continue`) discards these lanes. Without lane backgrounds and lifelines, the diagram collapses into a flat horizontal strip.

## 6. Analysis Method

1. **Structure diff**: Compare `structure_instantiation.json` edge lists → confirmed 4 missing edges.
2. **Prompt diff**: Diff baseline vs dev `structure/prompts.py` → identified Intent Decoding + Visual Necessity Filter as culprits.
3. **Code diff**: Diff baseline vs dev `arrow_adder.py` / `edge_router.py` → **0 diff**, algorithm is identical.
4. **Layout diff**: Compare positions → spacing differences are downstream effects of sparse topology.

## 7. Repair Directions

### 7.1 Architecture Edge Pruning (Priority: High)

**Option A**: Relax the Visual Necessity Filter for architecture diagrams. Add a clause:
> "For `architecture` diagrams, lateral connections within a layer AND convergent connections from multiple business nodes to a shared data layer ARE visually necessary. Do NOT drop them solely because containment implies a relationship."

**Option B**: Remove or loosen the `architecture → ≤n/2` budget. Architecture diagrams often need `n` or more edges to show full layered service flows.

**Option C**: Both A + B.

### 7.2 Sequence Lane Rendering (Priority: Medium)

**Option A**: Add schema instruction in layout prompt:
> "Each lane background MUST include `shape: 'rectangle'` and `type: 'rectangle'`."

**Option B**: Make converter fallback for `lane_*` elements (default shape=rectangle).

## 8. Open Questions

- Does baseline have sequence/ER results to compare? (Current find: only architecture in baseline results.)
- Would reverting the structure prompt's Intent Decoding step restore baseline-quality architecture diagrams?
- Is the color difference (purple vs grey) due to StylingAgent palette selection or palette definition changes?
