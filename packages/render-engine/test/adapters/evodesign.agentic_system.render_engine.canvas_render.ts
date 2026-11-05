import type { Adapter } from '../parity/functions.test.ts';

export default {
  render_canvas: { skip: 'async (Promise) and drives the live renderer page; replayed by the WP14 render check (notes/WP14.md) and parity:runs' },
} satisfies Record<string, Adapter>;
