import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
const ROOT = '/Users/zhanyi/Code/EvoDesign/packages/render-engine';
const { compare } = await import(join(ROOT, 'test/harness/compare.ts'));
const workflow = await import(join(ROOT, 'src/render_engine/workflow.ts'));
const dir = join(ROOT, 'fixtures/stages');
let totalTol = 0, totalKO = 0, exactCases = 0, n = 0, maxDelta = 0;
const perCase: any[] = [];
function maxdiff(a: any, b: any): number {
  if (typeof a === 'number' && typeof b === 'number') return a === b ? 0 : Math.abs(a - b);
  if (Array.isArray(a) && Array.isArray(b)) { let m = 0; for (let i = 0; i < Math.min(a.length, b.length); i++) m = Math.max(m, maxdiff(a[i], b[i])); return m; }
  if (a && b && typeof a === 'object' && typeof b === 'object') { let m = 0; for (const k of Object.keys(a)) m = Math.max(m, maxdiff(a[k], b[k])); return m; }
  return 0;
}
for (const file of readdirSync(dir).filter((f) => f.endsWith('.json') && !f.startsWith('_'))) {
  const fx = JSON.parse(readFileSync(join(dir, file), 'utf-8'));
  let state = workflow.createWorkflowState(structuredClone(fx.input));
  let tol = 0, ko = 0, md = 0;
  for (const [i, [node, run]] of workflow.excalidrawNodes().entries()) {
    state = run(state);
    const e = fx.snapshots[i];
    const exp = { l: e.layout_instantiation, m: e.diagram_manifest, v: e.validation_report };
    const act = { l: state.layout_instantiation, m: state.diagram_manifest, v: state.validation_report ?? null };
    const r = compare(exp, act, 1000);
    if (r.diffs.length) console.log('DIFF', file, node, r.diffs.slice(0, 2));
    tol += r.tolerated; ko += r.keyOrder.length; md = Math.max(md, maxdiff(exp, act));
  }
  n++; totalTol += tol; totalKO += ko; maxDelta = Math.max(maxDelta, md);
  if (md === 0) exactCases++;
  if (tol || ko || md) perCase.push({ file, tol, ko, md });
}
console.log(JSON.stringify({ n, exactCases, totalTol, totalKO, maxDelta, perCase: perCase.slice(0, 40) }, null, 1));
