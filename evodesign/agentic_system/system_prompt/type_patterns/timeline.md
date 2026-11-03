## Timeline

### Common
- Best for historical events and development history.
- Identity signal: a chronological axis with ordered milestones and event cards.
- If you find yourself laying milestones on a vertical stack or putting them at non-uniform y values, the layout is wrong — re-anchor everything to the horizontal axis.

#### Visual Pattern
Event cards alternate above and below the axis:
```
   ┌─────┐         ┌─────┐
   │Evt A│         │Evt C│
   └──┬──┘         └──┬──┘
      │               │
──────●───────●───────●───────●──────►
   2020      2021    2022    2023
              │               │
           ┌──┴──┐         ┌──┴──┐
           │ M 2 │         │ M 4 │
           └─────┘         └─────┘
```

### Structure
- Use time points or milestones along a main chronological axis.
- Event nodes can carry date-like fields that determine temporal order.
- Chronology should remain monotonic along the axis.
- Edges between milestones are normally NONE — the axis itself encodes succession. Add explicit arrows only if the source names a specific transition between two events.
- [Budget] tasks/events; 0 groups; [] edges unless explicit dependency arrows in source
- [Edge Rules] Expected count: 0. The axis encodes succession. Only emit edges if source explicitly names transitions.

### Styling
- Use a single horizontal line or thin rectangle (h=4..8, solid fill) as the main axis — make it visually dominant.
- Use IDENTICAL ellipses/circles (same diameter, 36-60px) to mark every milestone.
- Use rectangles or rounded rectangles to display event detail cards. Cards must look distinct from milestones (different shape AND different fill).
- Use a short vertical line (no arrowhead) to connect each event card to its milestone.

### Layout
- Primary family: Temporal. The axis IS the chart — place the axis first, then derive every other coordinate from it.
- Axis geometry: axis_y ≈ canvas_h / 2; axis_x_start ≈ side_margin + 200; axis_x_end ≈ canvas_w - side_margin - 200. The axis is horizontal, left-to-right, oldest event on the left.
- Milestone markers sit ON the axis: marker.y = axis_y - marker.h/2. ALL markers share one y and one diameter. Markers are EVEN-spaced along x: marker_k.x = axis_x_start + k * step - marker.w/2 where step = (axis_x_end - axis_x_start) / (n_markers - 1).
- Event cards alternate above and below the axis with FIXED offsets: even-index card.y = axis_y - card_offset - card.h (above), odd-index card.y = axis_y + card_offset (below). card_offset ≈ 100-150. All above-cards share one y; all below-cards share one y.
- Card horizontally centered on its marker: card.x = marker.x + marker.w/2 - card.w/2. card_w MUST be ≤ step (otherwise cards collide).
- Each milestone has a date/time label (font 14-16) next to or under its marker — never omit it. The date is the marker's identity.
- [Geometry] Axis IS the chart — place axis first. axis_y = canvas_h/2. Milestones (ellipses) sit ON the axis, evenly spaced. Event cards alternate above/below axis. Connect cards to markers with short vertical lines. Card width ≤ marker-to-marker step.
