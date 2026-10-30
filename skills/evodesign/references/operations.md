# Editing operations

Read the current document first. Use the saved version and `constraints.constraints_hash` verbatim. A minimal complete input is:

```json
{
  "protocol_version": 1,
  "base_version": 12,
  "constraints_hash": "sha256:replace-with-current-hash",
  "scope": {"kind": "elements", "element_ids": ["encoder"]},
  "operations": [{"op":"set_text", "id":"encoder", "text":"Feature encoder"}]
}
```

The IDs, version and hash above are placeholders. Add `context_version` from a current published selection when using that handoff. Without a shared selection, explicit IDs from the user's task can define the scope. `scope:{kind:"project"}` is appropriate for a new graph or authorized whole-project task; it never overrides locks.

Supported operations:

| Operation | Properties |
|---|---|
| `add_node` | `id`, `shape` (rectangle/ellipse/diamond; rectangle by default), `x`, `y`, positive `width`/`height`, optional `text` |
| `connect` | unique `id`, `from`, `to`, optional `text`; endpoints exist or are added earlier in the batch |
| `set_text` | `id`, `text`; a container ID resolves its bound label |
| `move_node` | `id`, absolute `x`, `y`; bound labels and affected connector endpoints move consistently |
| `set_style` | `id`, `style` with `fill`, `stroke`, `stroke_width`, `text_color`; colors are six-digit hex or transparent |
| `delete_node` | `id`, explicit `cascade` boolean; true also deletes dependent labels/connectors |

One batch contains 1–100 operations. Use stable IDs, finite coordinates within ±100000, positive sizes and stroke widths up to 10. Keep text below 10000 characters. Unknown properties and native JSON paths are unsupported.

The actual affected set includes bound text and connector references. A node's bound label is included in its semantic scope. Modifying an existing connector or neighboring node's binding list requires that element in the scope too. If the server reports `scope_violation`, inspect the required IDs and the task before preparing a revised scope; do not automatically widen to the project.

For a blank graph, use project scope and add nodes before their connections. Readability comes from a small, coherent set of entities and meaningful edges, not from exporting arbitrary scene JSON. Preserve user layout during local edits; there is no automatic global layout operation in v1.

Element scope edits existing objects and may create their bound text. Adding standalone nodes or new connections requires project scope in v1; use it only when the user's task authorizes those additions. Do not expand the scope just to bypass a shared selection.

`locked_element`, `context_stale`, `constraints_changed`, and `version_conflict` require fresh context or user action. Do not repair these by manipulating a version or constraint hash in an old request. A candidate that renders can still have geometric issues or incorrect content; use its report and actual image.
