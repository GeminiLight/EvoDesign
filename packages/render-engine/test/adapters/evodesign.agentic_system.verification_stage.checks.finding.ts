import type { Adapter } from '../parity/functions.test.ts';

export default {
  // ``self`` is recorded as the model's fields; the wrapper rebuilds the Finding.
  'Finding.to_dict': { exportName: 'Finding_to_dict' },
} satisfies Record<string, Adapter>;
