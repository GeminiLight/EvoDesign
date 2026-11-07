// Visual parity report (MIGRATION_PLAN.md §3 level ③).
//
// For every fixtures/stages/<case>.json:
//   reports/visual/<case>/ts.json      TS final manifest (renderExcalidrawManifest)
//   reports/visual/<case>/python.json  Python final snapshot (last stage)
// then renders both with the ONE Python renderer (tools/render_visual.py,
// sequential, EXCALIDRAW_RENDER_URL on port 3001), pixel-diffs them and writes
// reports/visual/index.html (failed cases first, relative image paths).
//
// Usage: npm run render [-- --case <substring>] [--skip-render]
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { FIXTURES, PACKAGE_ROOT } from '../test/harness/fixtures.ts';
import { renderExcalidrawManifest } from '../src/render_engine/workflow.ts';

const REPO = resolve(PACKAGE_ROOT, '../..');
const OUT = join(PACKAGE_ROOT, 'reports/visual');
const RENDER_URL = process.env.EXCALIDRAW_RENDER_URL ?? 'http://127.0.0.1:3001/renderers/excalidraw';

const argv = process.argv.slice(2);
const option = (name: string) => {
  const index = argv.indexOf(`--${name}`);
  return index >= 0 ? argv[index + 1] : undefined;
};
const caseFilter = option('case');
const skipRender = argv.includes('--skip-render');

interface Snapshot { node: string; diagram_manifest: unknown }
interface StageCase { case: string; input: Record<string, unknown>; snapshots: Snapshot[]; error: unknown }
interface IndexEntry { case: string; chart_type: string | null }
interface VisualResult {
  case: string; python_error?: string | null; ts_error?: string | null; error?: string;
  diff_percent?: number; changed_pixels?: number; identical?: boolean;
  python_size?: [number, number]; ts_size?: [number, number];
}

const stageDir = join(FIXTURES, 'stages');
const chartTypes = new Map(
  (JSON.parse(readFileSync(join(stageDir, '_index.json'), 'utf-8')) as IndexEntry[]).map((e) => [e.case, e.chart_type]),
);
const files = readdirSync(stageDir)
  .filter((name) => name.endsWith('.json') && !name.startsWith('_') && (!caseFilter || name.includes(caseFilter)))
  .sort();

// 1. Manifests.
const tsErrors = new Map<string, string>();
const cases: string[] = [];
for (const file of files) {
  const fixture = JSON.parse(readFileSync(join(stageDir, file), 'utf-8')) as StageCase;
  const dir = join(OUT, fixture.case);
  mkdirSync(dir, { recursive: true });
  const last = fixture.snapshots[fixture.snapshots.length - 1];
  writeFileSync(join(dir, 'python.json'), JSON.stringify(last?.diagram_manifest ?? null));
  try {
    writeFileSync(join(dir, 'ts.json'), JSON.stringify(renderExcalidrawManifest(fixture.input)));
  } catch (error) {
    tsErrors.set(fixture.case, String((error as Error).message).slice(0, 300));
    writeFileSync(join(dir, 'ts.json'), 'null');
  }
  cases.push(fixture.case);
}
console.log(`wrote ${cases.length} manifest pairs to ${OUT}`);

// 2. Render + diff with the Python renderer (sequential).
if (!skipRender) {
  const run = spawnSync(
    join(REPO, '.venv/bin/python'),
    [join(PACKAGE_ROOT, 'tools/render_visual.py'), OUT, ...(caseFilter ? cases : [])],
    { cwd: REPO, stdio: 'inherit', env: { ...process.env, PYTHONPATH: REPO, EXCALIDRAW_RENDER_URL: RENDER_URL } },
  );
  if (run.status !== 0) {
    console.error('render_visual.py failed');
    process.exitCode = 1;
  }
}

// 3. index.html.
const resultsPath = join(OUT, 'results.json');
const visual = new Map<string, VisualResult>(
  existsSync(resultsPath)
    ? (JSON.parse(readFileSync(resultsPath, 'utf-8')) as VisualResult[]).map((r) => [r.case, r])
    : [],
);
const stagesPath = join(PACKAGE_ROOT, 'reports/stages.json');
const stages = new Map<string, { ok: boolean; firstDivergence?: { node: string } }>(
  existsSync(stagesPath)
    ? (JSON.parse(readFileSync(stagesPath, 'utf-8')) as { cases: { case: string; ok: boolean; firstDivergence?: { node: string } }[] }).cases.map((c) => [c.case, c])
    : [],
);

const allCases = [...new Set([...readdirSync(OUT).filter((n) => existsSync(join(OUT, n, 'ts.json')))])].sort();
const rows = allCases.map((name) => {
  const v = visual.get(name);
  const s = stages.get(name);
  const renderError = tsErrors.get(name) ?? v?.error ?? v?.python_error ?? v?.ts_error ?? null;
  const stageOk = s ? s.ok : null;
  const pixelOk = v?.identical === true;
  const failed = stageOk === false || !pixelOk || renderError !== null;
  return { name, v, s, renderError, stageOk, pixelOk, failed, chart: chartTypes.get(name) ?? '' };
});
rows.sort((a, b) => Number(b.failed) - Number(a.failed)
  || (b.v?.diff_percent ?? 100) - (a.v?.diff_percent ?? 100)
  || (a.name < b.name ? -1 : 1));

const esc = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const identical = rows.filter((r) => r.pixelOk).length;
const stagePass = rows.filter((r) => r.stageOk === true).length;
const failedRows = rows.filter((r) => r.failed).length;

const body = rows.map((r) => {
  const img = (file: string) => existsSync(join(OUT, r.name, file))
    ? `<a href="${esc(r.name)}/${file}"><img loading="lazy" src="${esc(r.name)}/${file}" alt="${file}"></a>`
    : '<span class="muted">—</span>';
  const diff = r.v?.diff_percent === undefined ? 'n/a' : `${r.v.diff_percent.toFixed(4)}%`;
  const stage = r.stageOk === null ? '<span class="muted">not run</span>'
    : r.stageOk ? '<span class="ok">pass</span>'
      : `<span class="bad">diverges at ${esc(r.s?.firstDivergence?.node ?? '?')}</span>`;
  const sizes = r.v?.python_size ? `${r.v.python_size.join('×')} / ${r.v.ts_size?.join('×')}` : '';
  return `<tr class="${r.failed ? 'failed' : ''}">
<td><div class="case">${esc(r.name)}</div><div class="muted">${esc(r.chart)}</div>${r.renderError ? `<div class="bad small">${esc(r.renderError)}</div>` : ''}</td>
<td>${img('python.png')}</td><td>${img('ts.png')}</td><td>${img('diff.png')}</td>
<td class="num"><span class="${r.pixelOk ? 'ok' : 'bad'}">${diff}</span><div class="muted small">${sizes}</div></td>
<td>${stage}</td></tr>`;
}).join('\n');

const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Render Parity Gallery</title>
<style>
:root { --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --line:#e7e5e4; --ok:#15803d; --bad:#b91c1c; --card:#fff; --failbg:#fef2f2; }
@media (prefers-color-scheme: dark) { :root { --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --line:#44403c; --ok:#4ade80; --bad:#f87171; --card:#292524; --failbg:#3b1d1d; } }
body { margin:0; padding:16px; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; }
h1 { font-size:20px; margin:0 0 4px; }
.summary { margin:0 0 16px; color:var(--muted); }
.wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; background:var(--card); }
th, td { border-bottom:1px solid var(--line); padding:8px; vertical-align:top; text-align:left; }
th { position:sticky; top:0; background:var(--card); }
tr.failed { background:var(--failbg); }
img { max-width:260px; max-height:200px; background:#fff; border:1px solid var(--line); }
.case { font-weight:600; word-break:break-all; }
.muted { color:var(--muted); } .small { font-size:12px; }
.ok { color:var(--ok); font-weight:600; } .bad { color:var(--bad); font-weight:600; }
.num { font-variant-numeric:tabular-nums; white-space:nowrap; }
</style></head><body>
<h1>Python vs TypeScript render parity</h1>
<p class="summary">${rows.length} cases · pixel-identical ${identical}/${rows.length} · stage parity (chained) ${stagePass}/${rows.length} · ${failedRows} flagged (shown first).
Both PNGs come from the same Python renderer (render_canvas, ${esc(RENDER_URL)}); diff = share of pixels where any RGBA channel differs. Generated ${new Date().toISOString()}.</p>
<div class="wrap"><table>
<thead><tr><th>Case</th><th>Python</th><th>TS</th><th>Diff</th><th>Diff %</th><th>Stage parity</th></tr></thead>
<tbody>
${body}
</tbody></table></div>
</body></html>
`;
writeFileSync(join(OUT, 'index.html'), html);
console.log(`index.html: ${identical}/${rows.length} pixel-identical, ${stagePass}/${rows.length} stage parity, ${failedRows} flagged`);
