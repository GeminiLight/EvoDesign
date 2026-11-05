import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
const ROOT = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/';
const { compare } = await import(ROOT + 'test/harness/compare.ts');
const workflow = await import(ROOT + 'src/render_engine/workflow.ts');
const dir = process.argv[2];
let ok = 0, n = 0, tol = 0, ko = 0; const bad: any[] = [];
for (const file of readdirSync(dir).filter((f) => f.endsWith('.json')).sort()) {
  const fx = JSON.parse(readFileSync(join(dir, file), 'utf-8'));
  n++;
  let state = workflow.createWorkflowState(structuredClone(fx.input));
  let failed: any = null;
  for (const [i, [node, run]] of workflow.excalidrawNodes().entries()) {
    const e = fx.snapshots[i];
    try { state = run(state); } catch (err: any) {
      if (!e && fx.error?.node === node) { break; }
      failed = { node, threw: String(err).slice(0, 200), pyError: fx.error }; break;
    }
    if (!e) { failed = { node, why: 'python raised here but TS did not', pyError: fx.error }; break; }
    const r = compare({ l: e.layout_instantiation, m: e.diagram_manifest, v: e.validation_report }, { l: state.layout_instantiation, m: state.diagram_manifest, v: state.validation_report ?? null }, 6);
    tol += r.tolerated; ko += r.keyOrder.length;
    if (r.diffs.length) { failed = { node, diffs: r.diffs }; break; }
  }
  if (failed) bad.push({ case: fx.case, ...failed }); else ok++;
}
console.log(JSON.stringify({ n, ok, tolerated: tol, keyOrderPaths: ko, bad }, null, 1));
