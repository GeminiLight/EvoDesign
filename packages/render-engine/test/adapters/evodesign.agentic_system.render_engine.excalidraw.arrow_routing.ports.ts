// Parity adapter for render_engine.excalidraw.arrow_routing.ports (WP07).
import type { Adapter } from '../parity/functions.test.ts';
import { DiagramContext } from '../../src/render_engine/excalidraw/arrow_routing/context.ts';

export default {
  // Fixtures decode the DiagramContext dataclass as a plain object of its
  // fields; the port reads the ``is_architecture`` property, so rebuild it.
  _plan_edges: {
    args: (bound) => {
      const args = [...bound];
      args[5] = DiagramContext.from_fields(args[5] as Record<string, unknown>);
      return args;
    },
  },
} satisfies Record<string, Adapter>;
