// Parity adapter for render_engine.excalidraw.converter (WP04).
import type { Adapter } from '../parity/functions.test.ts';
import { useVirtualIconRoot } from './evodesign.agentic_system.common.icon_assets.ts';

export default {
  // The only vector comes from test_excalidraw_icon_conversion, which
  // monkeypatches icon_assets_root to an empty tmp dir so the SVG lookup
  // raises. Reproduce that with an empty virtual icon root (WP02 helper).
  _icon_to_data_url: {
    args: (bound) => {
      useVirtualIconRoot({});
      // The call raises, so a result hook would never run: restore the real
      // file system once the synchronous replay of this vector is done.
      queueMicrotask(() => useVirtualIconRoot(null));
      return bound;
    },
  },
} satisfies Record<string, Adapter>;
