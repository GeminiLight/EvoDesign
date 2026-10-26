# Optional node icons

The workspace's **Create diagram** dialog offers **Add node icons** for
Excalidraw. It is off by default and available to every user tier. Leaving it
off deterministically removes model-produced icon entries before layout. An
enabled request permits the styling model to choose icons; an explicit user
request for no icons is also included in the styling instructions.

The request field is `use_icons: boolean`, default `false`, on both generation
endpoints. The value is forwarded through the generation service, engine
adapter and programmatic workflow constructor. Retried browser requests retain
the option in their generation metadata. Regenerating a reopened scene preserves
its active node icons; a new creation dialog uses its explicit checkbox choice. CLI/config callers continue to use
`AgenticSystemConfig.use_icons`.

## Visual and editing behavior

- The existing styling call chooses a trusted icon name together with node
  styling, with no separate model call for icon selection.
- Sparse coverage (usually at most half of nodes) is the default design advice;
  explicitly requested coverage takes priority. Rectangles, participant headers
  and terminal ellipses qualify; decision diamonds, edges and group titles do not.
  Ellipse companions fit inside an inscribed content rectangle, preserving the
  curved boundary during generation, resizing and native editing.
- Icons use 26 canvas units, or a smaller size for very short nodes, and match
  the host's exact stroke color. Labels remain text and have a separate content
  area with at least 10 units between icon and label.
- Nodes, labels and icons share a native selection group. `customData.evoDesignIcon`
  records the companion's name and host ID. Group membership resolves native
  copies whose custom host ID has not yet been rewritten.
- Geometry and color changes reconcile companions in both refinement and the
  editor. Too-small nodes expand to preserve readable content. Ordinary images
  are never treated as node icons just because they happen to sit inside a box.
- Selecting one icon-bearing node exposes a compact icon chooser. Replacing or
  removing an icon is undoable. Removing it recenters its label.
- SVGs are embedded in the scene's `files`; saved scenes and exports do not
  need an icon CDN. The 74-name catalog and upstream license are packaged in
  `common/assets` and shared with the frontend.

The current compact-icon web control targets Excalidraw, the canvas supporting
the complete automatic refinement loop. The existing TLDraw icon integration
and its optional full-asset setup are unchanged.

## Quality checks

Objective verification reports missing hosts/assets, icon-label overlap and
icons outside their hosts. Automatic refinement cannot independently move,
resize or delete a generated icon; it edits the host instead. Checks operate
on explicit ownership, including after native saves discard `_meta.id_map`.

When review identifies an explicitly requested missing icon, the refiner can
use `set_icon` on its host node. It accepts only the bundled catalog, keeps the
bound text and native group, embeds the exact host-colored SVG, and rebuilds
connectors if the host needs more space. It cannot target decision diamonds,
group backgrounds or locked hosts. Existing optional-icon constraints and final
quality verification still apply. See the [missing-icon recovery and layout
stability validation](layout-stability-20261024.md) for a real failure/recovery.

Regression coverage:

```sh
python -m pytest evo_diagram/tests/render_engine/test_node_icons.py
npm run test:icons --prefix frontend
```

The [three-family real-model matrix](diagram-matrix-validation.md) checks icon
on/off generation, exact source facts, sequence refinement and native exports.

The browser geometry tests cover movement, resizing, duplicate groups, recolor,
replacement, deletion, undo-style restoration, idempotence and ordinary-image
isolation. The frontend quality gate runs these tests alongside lint/build.

## Native editor compatibility

Generated Excalidraw order keys use valid fractional integers (`e00000`, ...).
The web importer upgrades old `a00000`-style keys in array order; these legacy
keys could display normally but fail on duplication. Native `.excalidraw`
exports use the standard `excalidraw` type and version 2, with embedded SVG
assets using an unprefixed root. Companion repairs run after native actions
and stay outside undo history, so one undo restores an icon removal.

## Real-model and browser validation (2026-10-16)

- A web request with icons enabled used two design-memory entries and produced
  eight nodes with four icons. Engine time: 271.366 seconds; critic: 9.0/10;
  objective findings: zero. Automatic refinement correctly skipped this clean
  result.
- A separate, deliberately displaced copy exercised the actual model refiner
  and final critic: 100.11 seconds, one iteration, four applied edits, serious
  findings 4 → 0. Scores 5.5 → 6.5; this is a fault-recovery check, not evidence
  that the perturbed copy should replace the clean 9.0 result.
- The renderer now preserves original horizontal spacing when text/icon growth
  separates nodes, leaving room for connector labels. Re-rendering the same
  model layout passed all objective checks; a fresh critic scored it 8.7/10.
- Native browser checks covered drag, resize, recolor, icon replacement,
  duplication with new host ownership, removal and one-step undo, embedded
  PNG/SVG export and reopening the editable scene. Local artifacts are kept
  outside the repository and are not published with the source.
