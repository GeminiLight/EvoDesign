# Parity adapters

Optional per-module overrides for `test/parity/functions.test.ts`. File name:
`<python module>.ts`, e.g. `evodesign.agentic_system.render_engine.excalidraw.converter.ts`.

```ts
import type { Adapter } from '../parity/functions.test.ts';

export default {
  // Class methods: point at an exported wrapper.
  'InstantiationToExcalidrawConverter.convert': { skip: 'covered by stage parity (self is not serializable)' },
  // A tuple-keyed dict ported as Map<string, …>: convert before comparing.
  _group_index: { result: (actual) => Object.fromEntries(actual as Map<string, unknown>) },
} satisfies Record<string, Adapter>;
```

Every `skip` needs a reason and must be listed in `migration/notes/<WP>.md`.
