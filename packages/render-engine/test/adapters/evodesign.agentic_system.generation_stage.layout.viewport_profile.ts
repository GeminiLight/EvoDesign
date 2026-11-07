import type { Adapter } from '../parity/functions.test.ts';

export default {
  // Dataclass method: ``self`` arrives as its fields; the unbound wrapper rebuilds the instance.
  'LayoutViewportPlan.to_prompt': { exportName: 'LayoutViewportPlan_to_prompt' },
} satisfies Record<string, Adapter>;
