import type { Adapter } from '../parity/functions.test.ts';

export default {
  main: {
    skip: 'async (IterativeRefinerWorkflow.run, WP23); the recorded pytest calls monkeypatch _load_environment / IterativeRefinerWorkflow with fakes. CLI checked by hand (notes/WP22.md)',
  },
} satisfies Record<string, Adapter>;
