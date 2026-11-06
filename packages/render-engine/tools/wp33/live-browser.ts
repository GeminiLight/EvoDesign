/// <reference lib="dom" />
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';
const root = resolve(import.meta.dirname, '../../../..');
const env = Object.fromEntries(readFileSync(join(root, '.env'), 'utf8').split('\n').flatMap(line => {
  const match = /^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(line);
  return match ? [[match[1], match[2].replace(/^(['"])(.*)\1$/, '$2')]] : [];
}));
if (!env.LLM_API_KEY) throw new Error('No configured model key.');
const baseUrl = env.LLM_ENDPOINT_URL;
const provider = new URL(baseUrl).origin;
const config = { source: 'custom', model: env.LLM_MODEL_NAME, baseUrl, apiKey: env.LLM_API_KEY, rememberKey: false, refine: true, supportsVision: true };
const url = 'http://127.0.0.1:5177';
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--mode', 'browser', '--host', '127.0.0.1', '--port', '5177', '--strictPort'], { cwd: join(root, 'frontend'), stdio: 'ignore' });
const out = join(root, 'packages/render-engine/migration/wp33/browser'); mkdirSync(out, { recursive: true });
let browser;
let calls = 0;
const started = Date.now();
try {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${url}/test-pages/pipeline-worker.html`)).ok) break; } catch { /* starting */ }
    if (child.exitCode !== null) throw new Error('Frontend could not start.');
    await new Promise(r => setTimeout(r, 200));
  }
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.route(`${provider}/**`, async route => {
    if (route.request().method() === 'POST') calls++;
    if (calls > 40) await route.abort(); else await route.continue();
  });
  await page.goto(`${url}/test-pages/pipeline-worker.html`);
  await page.waitForFunction(() => (window as any).__workerReady, null, { timeout: 60000 });
  const request = { context: 'A customer submits an order. The payment service authorizes payment. If payment fails, ask the customer to retry. If payment succeeds, the warehouse ships the parcel and the customer receives a confirmation.', requirements: 'Create a clear flowchart with every branch.', locked_nodes: [], current_schema: null, canvas_library: 'excalidraw', use_icons: false, diagram_type: 'flow' };
  const outcome = await page.evaluate(async ({ request, config }) => (window as any).__runWorker(request, config), { request, config });
  writeFileSync(join(out, 'result.json'), JSON.stringify(outcome, null, 1));
  const render = await page.evaluate(async scene => (window as any).__pipelineRender(scene, { url: '', viewportWidth: 1200, viewportHeight: 900, timeoutMs: 30000, exportScale: 1, margin: 40 }), outcome.result.schema_blob);
  writeFileSync(join(out, 'diagram.png'), Buffer.from(render.base64, 'base64'));
  const summary = { side: 'browser', seconds: (Date.now() - started) / 1000, model_calls: calls, ok: true, generation: outcome.result.metrics_scores.generation };
  writeFileSync(join(out, 'summary.json'), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify({ side: 'browser', calls, ok: true, seconds: summary.seconds }));
} catch {
  const summary = { side: 'browser', model_calls: calls, ok: false, seconds: (Date.now() - started) / 1000, error: 'Browser model generation failed; inspect local provider access, CORS and generation events.' };
  writeFileSync(join(out, 'summary.json'), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(summary)); process.exitCode = 1;
} finally { await browser?.close(); child.kill(); }
