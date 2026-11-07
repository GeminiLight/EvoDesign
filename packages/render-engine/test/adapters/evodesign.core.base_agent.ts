import type { Adapter } from '../parity/functions.test.ts';
import type { Vector } from '../harness/fixtures.ts';
import { _CallBudget, _set_clock } from '../../src/core/base_agent.ts';

// ``_CallBudget`` methods: self is the dataclass's field dict. elapsed/remaining
// read time.monotonic(); the recorded result fixes the clock reading at call
// time (now = started_at + elapsed, or started_at + deadline - remaining), so
// the adapter pins the clock there and checks the arithmetic around it.
function budgetFrom(fields: Record<string, unknown>): _CallBudget {
  return new _CallBudget(
    fields.deadline_seconds as number | null,
    fields.retries_left as number,
    fields.started_at as number,
    fields.retries_used as number,
  );
}

function pinClock(now: number | null): void {
  _set_clock(now === null ? null : { monotonic: () => now });
}

const method = (exportName: string, now: (fields: Record<string, number>, vector: Vector) => number | null): Adapter => ({
  exportName,
  args: (bound, vector) => {
    const fields = bound[0] as Record<string, number>;
    pinClock(now(fields, vector));
    return [budgetFrom(fields), ...bound.slice(1)];
  },
});

export default {
  // check(): every recorded call happened well inside the 1800 s deadline.
  '_CallBudget.check': method('_CallBudget_check', (fields) => fields.started_at),
  '_CallBudget.elapsed_seconds': method('_CallBudget_elapsed_seconds', (fields, vector) => fields.started_at + (vector.result as number)),
  '_CallBudget.remaining_seconds': method('_CallBudget_remaining_seconds', (fields, vector) => fields.started_at + fields.deadline_seconds - (vector.result as number)),
  // Python returns None; the TS port is void.
  charge_llm_run_budget: { result: (actual) => actual ?? null },
} satisfies Record<string, Adapter>;
