/// <reference lib="dom" />
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { chromium } from 'playwright';
import { compareEvent, compareResult, loadWebRun, WebNormalizer } from '../test/harness/web_runs.ts';
import { compareImages, contentRecord, jsonDiff } from '../test/harness/cassette.ts';

const root = resolve(import.meta.dirname, '../../..');
const frontend = join(root, 'frontend');
const url = 'http://127.0.0.1:5178';
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--mode', 'browser', '--host', '127.0.0.1', '--port', '5178', '--strictPort'], { cwd: frontend, stdio: 'pipe' });
let log = '';
child.stdout.on('data', d => { log += d; }); child.stderr.on('data', d => { log += d; });
const reports: unknown[] = [];
const hosted = process.argv.includes('--hosted');
let browser;
try {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${url}/test-pages/pipeline-worker.html`)).ok) break; } catch { /* starting */ }
    if (child.exitCode !== null) throw new Error(log);
    await new Promise(r => setTimeout(r, 200));
  }
  browser = await chromium.launch({ headless: true });
  const names = hosted ? ['sm_course_ty1__web_nocritic'] : ['flow_x1__web', 'flow_h1__web_router', 'hcai_demo__web_refine'];
  for (const name of names) {
    const run = loadWebRun(name);
    const page = await browser.newPage();
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    let calls = 0;
    let firstDiff: string | undefined;
    await page.route(hosted ? '**/api/model' : 'https://llm.example.test/**', async route => {
      const input = route.request().postDataJSON();
      if (hosted && input.task === 'start_run') {
        await route.fulfill({ json: { token: 'offline-run-token' } });
        return;
      }
      const expected = run.cassette[calls++];
      try {
        assert.ok(expected, `unexpected model call ${calls}`);
        assert.ok(!('error' in expected.response), 'This smoke case must have successful recorded responses.');
        assert.equal(route.request().headers().authorization, hosted ? undefined : 'Bearer fake-browser-key');
        if (hosted) assert.equal(input.runToken, 'offline-run-token');
        const roles: Record<string, string> = { system: 'system', user: 'human', assistant: 'ai', tool: 'tool' };
        const actualMessages = input.messages.map((m: Record<string, unknown>) => ({ type: roles[String(m.role)], content: contentRecord(m.content) }));
        const diffs: string[] = [];
        jsonDiff(expected.request.messages, actualMessages, '$.messages', diffs, 1,
          (e, a, path) => compareImages(e, a, path, run.dir, []));
        if (diffs.length) firstDiff ??= `call ${calls}: ${diffs[0]}`;
        const tool_calls = expected.response.tool_calls?.map(c => ({ id: c.id, type: 'function', function: { name: c.name, arguments: JSON.stringify(c.args) } }));
        const message = { role: 'assistant', content: expected.response.content ?? '', ...(tool_calls?.length ? { tool_calls } : {}) };
        if (input.stream) {
          const chunk = { id: 'replay', object: 'chat.completion.chunk', choices: [{ index: 0, delta: message, finish_reason: null }] };
          await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify(chunk)}\n\ndata: [DONE]\n\n` });
        } else await route.fulfill({ json: { id: 'replay', choices: [{ index: 0, message, finish_reason: 'stop' }] } });
      } catch (error) { firstDiff ??= String(error); await route.abort(); }
    });
    await page.goto(`${url}/test-pages/pipeline-worker.html`);
    await page.waitForFunction(() => (window as any).__workerReady, null, { timeout: 60000 });
    const config = { source: hosted ? 'hosted' : 'custom', supportsVision: !hosted, model: 'cassette-model', baseUrl: 'https://llm.example.test/v1', apiKey: 'fake-browser-key', refine: true, rememberKey: false };
    const outcome = await page.evaluate(async ({ request, config }) => (window as any).__runWorker(request, config), { request: run.input.request, config });
    assert.equal(firstDiff, undefined, firstDiff);
    assert.equal(calls, run.cassette.length);
    assert.deepEqual(errors, []);
    const normalizer = new WebNormalizer('/tmp');
    const normalized = (value: unknown) => normalizer.value(JSON.parse(JSON.stringify(value)));
    for (const [i, event] of outcome.events.entries()) {
      const expected = run.events[i];
      const diffs = compareEvent(expected, { event: event.event, data: normalized(event.data), llm_calls: expected?.llm_calls ?? 0 }, i);
      assert.deepEqual(diffs, [], `${name}: ${diffs[0]}`);
    }
    assert.equal(outcome.events.length, run.events.length);
    assert.deepEqual(compareResult(run.result, { result: normalized(outcome.result) as any, error: null }), []);
    const expectedElements = (run.result.result?.schema_blob as any).elements;
    const restoredExpected = await page.evaluate(elements => (window as any).__restoreExpected(elements), expectedElements);
    assert.deepEqual(outcome.canvasElements.map((e: any) => [e.id, e.type, e.x, e.y, e.width, e.height]),
      restoredExpected.map((e: any) => [e.id, e.type, e.x, e.y, e.width, e.height]));
    assert.ok(await page.evaluate(async ({ request, config }) => (window as any).__cancelWorker(request, config), { request: run.input.request, config }));
    reports.push({ case: name, calls, events: outcome.events.length, elements: expectedElements.length, cancellation: true });
    console.log(`OK ${name}: ${calls} model calls, ${outcome.events.length} events, ${expectedElements.length} canvas elements`);
    await page.close();
  }
} finally { await browser?.close(); child.kill(); }
mkdirSync(join(root, 'packages/render-engine/reports'), { recursive: true });
writeFileSync(join(root, 'packages/render-engine/reports/' + (hosted ? 'shared-worker-smoke.json' : 'browser-smoke.json')), JSON.stringify(reports, null, 2));
