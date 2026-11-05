// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import { readFileSync } from 'node:fs';
import { decode } from '../../test/harness/fixtures.ts';
import { compare } from '../../test/harness/compare.ts';
import { VerifierRefinerState } from '../../src/refinement_stage/state.ts';
import { IterativeRefinerWorkflow } from '../../src/agentic_system/iterative_workflow.ts';
const lines = readFileSync('/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/wp25/_after_iteration.jsonl', 'utf-8').trim().split('\n').map((l) => JSON.parse(l));
let ok = 0;
for (const v of lines) {
  const st = new VerifierRefinerState(decode(v.args[0]) as Record<string, unknown>);
  const r = IterativeRefinerWorkflow.prototype._after_iteration.call({} as never, st);
  const after = compare(decode(v.args_after[0]), JSON.parse(JSON.stringify(st)));
  if (r === v.result && after.diffs.length === 0) ok++; else console.log('DIFF', r, v.result, after.diffs.slice(0, 2));
}
console.log(ok + '/' + lines.length);
