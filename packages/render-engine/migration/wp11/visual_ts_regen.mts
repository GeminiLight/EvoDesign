import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
const ROOT = '/Users/zhanyi/Code/EvoDesign/packages/render-engine';
const { renderExcalidrawManifest } = await import(join(ROOT, 'src/render_engine/workflow.ts'));
let same = 0, n = 0; const diff: string[] = [];
for (const f of readdirSync(join(ROOT, 'fixtures/stages')).filter((x) => x.endsWith('.json') && !x.startsWith('_'))) {
  const fx = JSON.parse(readFileSync(join(ROOT, 'fixtures/stages', f), 'utf-8'));
  const now = JSON.stringify(renderExcalidrawManifest(fx.input));
  const disk = readFileSync(join(ROOT, 'reports/visual', fx.case, 'ts.json'), 'utf-8');
  n++; if (now === disk) same++; else diff.push(fx.case);
}
console.log({ n, same, diff: diff.slice(0, 10) });
