# Layout Workflow Notes

This directory owns the Layout stage in the Structure -> Styling -> Layout
generation pipeline.

## Current Flow

```text
LayoutWorkflow
  -> estimate_sizes
  -> LayoutAgent
  -> END
```

The old dagre baseline prepass and baseline validator are not part of the
current workflow. Layout quality is enforced through the Layout prompt,
`validate_layout_instantiation()`, render/audit checks, and optional refinement.

## Size Hints

`element_shape_estimator.py` exposes `estimate_element_sizes()`. It copies the
Styling instantiation and adds integer `min_width` / `min_height` hints only to
canonical Structure node ids.

It intentionally skips:

- groups,
- edges,
- icon companion entries,
- metadata keys,
- underscore icon ids.

The estimator uses label text, font size, script-aware character width, and the
presence of a canonical `<node_id>:icon` companion to reserve enough horizontal
budget for left-aligned icons. It does not assign final `x/y/w/h`, does not
derive group frames, and does not add padding that belongs to the render-stage
shape fitter.

## Layout Agent

`layout_agent.py` continues the shared `conversation_history` from Structure
and Styling. It renders `LAYOUT_TASK_PROMPT` with:

- original text/query,
- stage knowledge,
- design expertise,
- runtime directives,
- `size_hints` from `estimate_element_sizes()`.

The LLM output must be a flat id-keyed map. `LayoutAgent` validates that map
against Structure/Styling ids, then merges geometry and edge ports back onto
the styled entries.

## Contract

- Nodes and groups carry integer `x`, `y`, `w`, `h`.
- Edges carry `start` and `end` port objects using exact Structure ids.
- Icons use canonical `<node_id>:icon` ids only.
- `waypoints` are rejected; renderer arrow logic derives paths from side pairs.

Focused checks:

```bash
.venv/bin/python -m pytest \
  evo_diagram/tests/generation/test_element_shape_estimator.py \
  evo_diagram/tests/generation/test_layout_agent_contract.py \
  evo_diagram/tests/render_engine/test_render_workflow_canvas.py -q
```
