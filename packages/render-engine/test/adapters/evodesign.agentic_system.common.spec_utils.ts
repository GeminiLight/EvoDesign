import type { Adapter } from '../parity/functions.test.ts';
import { bindWithFloats } from '../py/raw_floats.ts';

const MODULE = 'evodesign.agentic_system.common.spec_utils';

export default {
  // The result is json.dumps text: Python writes integral floats as "100.0",
  // which JSON.parse in the shared harness collapses to 100. Re-bind the
  // arguments with floats kept as PyFloat (the port's float marker). Mutation
  // is not compared because the re-bound args hold PyFloat markers; the
  // function never mutates its inputs.
  build_assistant_content: {
    args: (_bound, vector) => bindWithFloats(MODULE, 'build_assistant_content', vector),
    checkMutation: false,
  },
} satisfies Record<string, Adapter>;
