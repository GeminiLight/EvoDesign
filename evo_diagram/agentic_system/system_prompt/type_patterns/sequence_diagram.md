## Sequence Diagram

### Common
- Identity: participant headers in a horizontal row, dashed vertical lifelines,
  and horizontal messages ordered from top to bottom.
- Preserve every source message, including multiple messages between the same
  participants, returns and self-calls. Never summarize away chronological steps.

### Structure
- Emit exactly one node per participant, in the requested left-to-right order.
- Every participant node has a non-empty `actor_id`, normally equal to its `id`.
- Emit one group per actor lane; its members contain that participant node.
- Emit one edge per message. Each has a unique non-negative `sequence_idx`, a
  readable `label`, and the actual sender/receiver as `source`/`target`.
- For repeated endpoint pairs use distinct canonical edge IDs with numeric suffixes.
- Set `message_kind: "return"` for reply/return messages and `"synchronous"` for
  ordinary calls. Preserve a user-specified dashed style on other messages.
- Activations and lifelines are derived visual annotations, not extra semantic
  nodes. Do not invent message/event boxes or edges for lifelines.
- When a semantic ledger is present, include `evidence_basis` and `relation` on
  every edge; labels can add message numbers without changing the predicate.

### Styling
- Participant headers are readable rectangles with light fills and dark strokes.
- Optional icons belong inside selected participant headers, never on messages.
  Explicit user coverage overrides the default sparse icon preference.
- Lane groups use quiet or transparent backgrounds; avoid duplicate headings.
- Edge labels are subordinate to participant labels. Use dashed return arrows.

### Layout
- Keep participant headers aligned on one top row, in Structure node order.
- Give each participant enough width for its label and optional compact icon.
- Supply valid header/lane geometry and canonical edge endpoints. The Excalidraw
  renderer derives lifelines and message rows from `sequence_idx`; generic graph
  waypoints cannot express this chronology and are not used for message routing.
- Allow the time axis to grow with message count. Do not force a fixed height
  that would compress messages into overlapping rows. Use at least 64 px per
  message by default and additional space for multi-line labels and self-calls.
- Refinement must preserve participant order, chronology, labels, directions,
  and return styles; it must not connect all messages back to the headers.
