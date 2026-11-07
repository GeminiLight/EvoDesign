import type { Adapter } from '../parity/functions.test.ts';
import { _FIXERS } from '../../src/refinement_stage/fixers/deterministic.ts';

// pytest ``test_run_all_deterministic_fixers_raises_named_error`` monkeypatches
// ``deterministic._FIXERS`` with ``(("failing", failing_fixer),)`` where the
// fixer raises ``RuntimeError("boom")``. Reproduce that patch for the vector
// that recorded it and restore the real table for every other vector.
const ORIGINAL_FIXERS = [..._FIXERS];

export default {
  // ``_by_id`` is ported as a Map (element ids may look like integers, and a
  // plain object would reorder them); compare it as the Python dict.
  _by_id: { result: (actual) => Object.fromEntries(actual as Map<string, unknown>) },
  run_all_deterministic_fixers: {
    args: (bound, vector) => {
      _FIXERS.splice(0, _FIXERS.length, ...ORIGINAL_FIXERS);
      if (vector.raises && String(vector.message ?? '').includes("'failing'")) {
        _FIXERS.splice(0, _FIXERS.length, ['failing', () => { throw new Error('boom'); }]);
      }
      return bound;
    },
  },
} satisfies Record<string, Adapter>;
