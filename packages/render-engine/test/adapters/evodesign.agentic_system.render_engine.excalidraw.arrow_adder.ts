// Parity adapter for render_engine.excalidraw.arrow_adder (WP07).
import type { Adapter } from '../parity/functions.test.ts';
import { DiagramContext } from '../../src/render_engine/excalidraw/arrow_routing/context.ts';
import { PortTotals } from '../../src/render_engine/excalidraw/arrow_routing/ports.ts';

type Dict = Record<string, unknown>;

// Fixtures decode dataclasses as plain objects of their fields (tuple-keyed
// counters as Map with array keys). The port reads ``DiagramContext``
// properties and ``PortTotals`` defaultdicts, so rebuild the instances.
function rebuild(totalsIndex: number | null, diagramIndex: number | null) {
  return (bound: unknown[]): unknown[] => {
    const args = [...bound];
    if (totalsIndex !== null) args[totalsIndex] = PortTotals.from_fields(args[totalsIndex] as Dict);
    if (diagramIndex !== null) args[diagramIndex] = DiagramContext.from_fields(args[diagramIndex] as Dict);
    return args;
  };
}

export default {
  _route_edge: { args: rebuild(1, null) },
  _route_context: { args: rebuild(1, 2) },
  _keeps_edge_label: { args: rebuild(null, 2) },
} satisfies Record<string, Adapter>;
