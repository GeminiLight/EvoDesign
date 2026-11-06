/// <reference lib="dom" />
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '../../../..');
const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error('Usage: classics-browser.ts INPUT.json OUTPUT');
const cases = JSON.parse(readFileSync(inputPath, 'utf8'));
const env = Object.fromEntries(readFileSync(join(root, '.env'), 'utf8').split('\n').flatMap(line => {
  const match = /^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(line);
  return match ? [[match[1], match[2].replace(/^(['"])(.*)\1$/, '$2')]] : [];
}));
if (!env.LLM_API_KEY) throw new Error('No configured model key.');
const config = { source: 'custom', model: env.LLM_MODEL_NAME, baseUrl: env.LLM_ENDPOINT_URL,
  apiKey: env.LLM_API_KEY, rememberKey: false, refine: true, supportsVision: true };
const provider = new URL(config.baseUrl).origin;
const port = process.env.CLASSICS_PORT ?? '5181';
const url = `http://127.0.0.1:${port}`;
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--mode', 'browser', '--host', '127.0.0.1', '--port', port, '--strictPort'],
  { cwd: join(root, 'frontend'), stdio: 'ignore' });
mkdirSync(outputPath, { recursive: true });
copyFileSync(inputPath, join(outputPath, 'inputs.json'));
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
const summaries: Record<string, unknown>[] = [];
try {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${url}/test-pages/pipeline-worker.html`)).ok) break; } catch { /* starting */ }
    if (child.exitCode !== null) throw new Error('Frontend could not start.');
    await new Promise(r => setTimeout(r, 200));
  }
  browser = await chromium.launch({ headless: true });
  for (const item of cases) {
    const directory = join(outputPath, item.id);
    mkdirSync(directory, { recursive: true });
    copyFileSync(join(root, item.baseline), join(directory, 'before.png'));
    const page = await browser.newPage();
    let calls = 0;
    const http: Record<string, unknown>[] = [];
    const diagnostics: string[] = [];
    const started = Date.now();
    // Expose local test diagnostics without changing the production worker's
    // generic, credential-safe error contract. Never print provider bodies.
    page.on('console', message => {
      if (message.text().startsWith('LOCAL_PIPELINE_DIAGNOSTIC')) {
        diagnostics.push(message.text().replaceAll(config.apiKey, '[REDACTED]'));
      }
    });
    await page.route('**/pipeline.worker.ts*', async route => {
      const response = await route.fetch();
      const source = (await response.text()).replace('catch {',
        'catch (debugError) { console.error("LOCAL_PIPELINE_DIAGNOSTIC", debugError?.stack ?? String(debugError));');
      await route.fulfill({ response, body: source });
    });
    page.on('response', async response => {
      if (!response.url().startsWith(provider) || response.request().method() !== 'POST') return;
      http.push({ status: response.status(), content_type: response.headers()['content-type'] });
    });
    await page.route(`${provider}/**`, async route => {
      if (route.request().method() === 'POST') {
        calls++;
        console.log(JSON.stringify({ case: item.id, model_call: calls, seconds: Math.round((Date.now() - started) / 1000) }));
      }
      if (calls > 40) await route.abort(); else await route.continue();
    });
    try {
      await page.goto(`${url}/test-pages/pipeline-worker.html`);
      await page.waitForFunction(() => (window as any).__workerReady, null, { timeout: 60000 });
      const request = { context: item.content, requirements: item.query, diagram_type: item.diagram_type,
        use_icons: true, canvas_library: 'excalidraw', locked_nodes: [], current_schema: null, project_id: null };
      const outcome = await page.evaluate(async ({ request, config }) => (window as any).__runWorker(request, config), { request, config });
      writeFileSync(join(directory, 'result.json'), JSON.stringify(outcome, null, 1));
      const render = await page.evaluate(async scene => (window as any).__pipelineRender(scene,
        { url: '', viewportWidth: 1200, viewportHeight: 900, timeoutMs: 30000, exportScale: 1, margin: 40 }), outcome.result.schema_blob);
      writeFileSync(join(directory, 'after.png'), Buffer.from(render.base64, 'base64'));
      const summary = { case: item.id, ok: true, seconds: (Date.now() - started) / 1000, model_calls: calls,
        generation: outcome.result.metrics_scores.generation };
      summaries.push(summary);
      console.log(JSON.stringify(summary));
    } catch {
      const events = await page.evaluate(() => (window as any).__workerEvents ?? []).catch(() => []);
      writeFileSync(join(directory, 'failure-events.json'), JSON.stringify(events, null, 1));
      const summary = { case: item.id, ok: false, seconds: (Date.now() - started) / 1000, model_calls: calls,
        error: 'Browser generation failed; no provider details logged.' };
      summaries.push(summary);
      console.log(JSON.stringify(summary));
    } finally {
      writeFileSync(join(directory, 'http.json'), JSON.stringify(http, null, 1));
      writeFileSync(join(directory, 'diagnostics.json'), JSON.stringify(diagnostics, null, 1));
      writeFileSync(join(outputPath, 'summary.json'), JSON.stringify(summaries, null, 1));
      await page.close();
    }
  }
} finally {
  await browser?.close();
  child.kill();
}
if (summaries.some(s => !s.ok)) process.exitCode = 1;
