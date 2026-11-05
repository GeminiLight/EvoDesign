// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { CassetteSession } from '../../test/harness/cassette.ts';
import { loadRun } from '../../test/harness/runs.ts';
const { runRecordedPipeline } = await import('../../src/agentic_system/main.ts');
const run = loadRun('flow_x1__multi');
const session = new CassetteSession(run.dir);
const work = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/wp25/dm'; rmSync(work, { recursive: true, force: true }); mkdirSync(join(work, 'out'), { recursive: true });
writeFileSync(join(work, 'dataset.json'), JSON.stringify([run.input.item]));
const argv = run.input.argv.filter((a) => a !== '--no-design-memory').map((a) => a.split('<OUT>').join(work));
try {
  const r = await runRecordedPipeline(run.input as never, { chatModelFactory: session.chatModelFactory(), outputDir: join(work, 'out'), datasetPath: join(work, 'dataset.json'), argv, env: run.input.env, rendererUrl: 'http://127.0.0.1:3001/renderers/excalidraw' });
  const res = (r as any);
  console.log('calls', session.calls.length, 'mismatch', JSON.stringify(session.mismatch));
  console.log(JSON.stringify({ success: res.success, design_memory_enabled: res.design_memory_enabled, design_memory_degraded: res.design_memory_degraded, design_memory_errors: res.design_memory_errors }).slice(0, 600));
} catch (e) { console.log('ERR', String(e).slice(0, 400), 'calls', session.calls.length, JSON.stringify(session.mismatch)?.slice(0, 500)); }
