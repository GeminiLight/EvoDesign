// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
// WP25 temporary audit script (deleted after use): replay all runs, keep TS outputs,
// count snapshot tolerated numbers / key-order differences.
import { mkdirSync, rmSync, writeFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { CassetteSession } from '../../test/harness/cassette.ts';
import { compare } from '../../test/harness/compare.ts';
import { Normalizer, RUNS, expectedValue, instrumentSnapshots, loadRun, setSnapshotSink, toPlain } from '../../test/harness/runs.ts';
const OUT = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/wp25/runs_out';
const { runRecordedPipeline } = await import('../../src/agentic_system/main.ts');
await instrumentSnapshots();
const names = readdirSync(RUNS).filter((n) => !n.startsWith('_') && statSync(join(RUNS, n)).isDirectory()).sort();
const summary: Record<string, unknown>[] = [];
for (const name of names) {
  const run = loadRun(name);
  const session = new CassetteSession(run.dir);
  const work = join(OUT, name); rmSync(work, { recursive: true, force: true });
  const outputDir = join(work, 'out'); mkdirSync(outputDir, { recursive: true });
  const datasetPath = join(work, 'dataset.json');
  writeFileSync(datasetPath, JSON.stringify([run.input.item], null, 2));
  const normalizer = new Normalizer(work);
  let i = 0; let tolerated = 0; const keyOrder: string[] = []; let diffs = 0;
  setSnapshotSink((_s, _g, node, value) => {
    const exp = run.snapshots[i++]; if (!exp) return;
    const c = compare(expectedValue(exp), normalizer.value(toPlain(value)));
    tolerated += c.tolerated; diffs += c.diffs.length; if (c.keyOrder.length) keyOrder.push(node + ':' + c.keyOrder.slice(0, 3).join(','));
  });
  let err = null;
  try {
    await runRecordedPipeline(run.input as never, { chatModelFactory: session.chatModelFactory(), outputDir, datasetPath,
      argv: run.input.argv.map((a) => a.split('<OUT>').join(work)), env: run.input.env, rendererUrl: 'http://127.0.0.1:3001/renderers/excalidraw' });
  } catch (e) { err = String(e).slice(0, 200); }
  setSnapshotSink(null);
  summary.push({ name, work, snapshots: i, tolerated, keyOrder, diffs, err, calls: session.calls.length });
  console.log(name, i, tolerated, keyOrder.length, diffs, err ? 'ERR' : '');
}
writeFileSync(join(OUT, 'summary.json'), JSON.stringify(summary, null, 1));
