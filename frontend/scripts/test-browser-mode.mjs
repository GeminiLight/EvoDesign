import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { test, beforeEach, afterEach } from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temp = mkdtempSync(path.join(tmpdir(), 'evodesign-browser-'));
async function load(relative) {
  const output = path.join(temp, path.basename(relative) + '.mjs');
  execFileSync(path.join(root, 'node_modules/.bin/esbuild'), [path.join(root, relative),
    '--bundle', '--format=esm', '--platform=node', '--external:@excalidraw/excalidraw',
    '--define:import.meta.env={"VITE_RUNTIME_MODE":"browser"}', `--outfile=${output}`, '--log-level=error']);
  return import(pathToFileURL(output).href);
}
const model = await load('src/services/browser/modelConfig.ts');
const { normalizePlan, layoutPlan, preservesContent } = await load('src/services/browser/diagramPlan.ts');
const { sanitizeEdit } = await load('src/services/browser/diagramService.ts');
const { preserveLockedElements } = await load('src/services/browser/scene.ts');
const { mergeDeltaIntoSchema } = await load('src/utils/app.ts');
const { isGuest } = await load('src/services/guestStorage.ts');
const { getStoredAuthToken } = await load('src/services/httpClient.ts');
rmSync(temp, { recursive: true });
const fetchBefore = globalThis.fetch;
const storage = () => { const data = new Map(); return { getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k), clear: () => data.clear() }; };
beforeEach(() => { globalThis.localStorage = storage(); globalThis.sessionStorage = storage(); });
afterEach(() => { globalThis.fetch = fetchBefore; });
const config = { baseUrl: 'https://model.example/v1', model: 'my-model', apiKey: 'test-secret', rememberKey: false, refine: true };
test('credentials stay tab-local by default and are never reused for a changed endpoint', () => {
  model.saveModelConfig(config);
  assert.equal(model.loadModelConfig().apiKey, config.apiKey);
  assert.ok(!localStorage.getItem('evodesign.browser-model.v1').includes(config.apiKey));
  sessionStorage.clear();
  assert.equal(model.loadModelConfig().apiKey, '');
  model.saveModelConfig({ ...config, rememberKey: true });
  assert.equal(model.loadModelConfig().apiKey, config.apiKey);
  model.saveModelConfig({ ...config, baseUrl: 'https://second.example/v1', apiKey: '' });
  assert.equal(model.loadModelConfig().apiKey, '');
  model.forgetModelKey();
  assert.equal(model.loadModelConfig().model, config.model);
  assert.equal(model.loadModelConfig().apiKey, '');
});
test('browser mode ignores old server login tokens', () => {
  localStorage.setItem('auth_token', 'old-token');
  assert.equal(isGuest(), true); assert.equal(getStoredAuthToken(), null);
});
test('endpoints require HTTPS, except loopback, and never accept URL credentials', () => {
  assert.equal(model.completionUrl('https://provider.example/v1/'), 'https://provider.example/v1/chat/completions');
  assert.equal(model.completionUrl('http://localhost:11434/v1/chat/completions'), 'http://localhost:11434/v1/chat/completions');
  for (const url of ['http://provider.example/v1', 'https://secret@provider.example', 'https://provider.example?key=secret', 'javascript:alert(1)', 'https://provider.example/#key']) assert.throws(() => model.completionUrl(url));
});
test('model calls use only the chosen provider and omit cookies, redirects and referrers', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, 'https://model.example/v1/chat/completions');
    assert.equal(options.credentials, 'omit'); assert.equal(options.redirect, 'error'); assert.equal(options.referrerPolicy, 'no-referrer');
    assert.equal(options.headers.Authorization, 'Bearer test-secret');
    assert.equal(JSON.parse(options.body).model, 'my-model'); assert.ok(!options.body.includes('test-secret'));
    return new Response(JSON.stringify({ choices: [{ message: { content: '{"ok":true}' }, finish_reason: 'stop' }] }));
  };
  assert.deepEqual(model.parseModelJson(await model.callBrowserModel(config, 'system', 'prompt')), { ok: true });
});
test('upstream error bodies never reveal keys or prompts, and CORS errors are actionable', async () => {
  globalThis.fetch = async () => new Response('secret-key-and-private-prompt', { status: 401 });
  await assert.rejects(model.callBrowserModel(config, 'system', 'prompt'), e => /401/.test(e.message) && !/secret-key/.test(e.message));
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(model.callBrowserModel(config, '', ''), /CORS/);
});
test('aborted requests and truncated output are reported instead of silently rendered', async () => {
  const controller = new AbortController(); controller.abort();
  globalThis.fetch = async (_, options) => { options.signal.throwIfAborted(); };
  await assert.rejects(model.callBrowserModel(config, '', '', controller.signal), /cancelled/);
  globalThis.fetch = async () => new Response(JSON.stringify({ choices: [{ message: { content: '{"nodes":' }, finish_reason: 'length' }] }));
  await assert.rejects(model.callBrowserModel(config, '', ''), /truncated/);
});
const sample = () => ({ title: 'Retry workflow', kind: 'graph', direction: 'TB', nodes: [
  { id: 'a', label: 'Start' }, { id: 'b', label: 'Request approved?', shape: 'diamond' }, { id: 'c', label: 'Notify user' },
], edges: [{ source: 'a', target: 'b' }, { source: 'b', target: 'c', label: 'Yes' }, { source: 'b', target: 'a', label: 'Retry' }] });
test('untrusted plans reject missing endpoints, duplicate IDs and excessive size', () => {
  for (const data of [{ ...sample(), edges: [{ source: 'a', target: 'missing' }] }, { ...sample(), nodes: [{ id: 'a', label: 'A' }, { id: 'a', label: 'B' }] }, { ...sample(), nodes: Array.from({ length: 61 }, (_, i) => ({ id: String(i), label: 'Node' })) }]) assert.throws(() => normalizePlan(data));
  const plan = normalizePlan({ ...sample(), nodes: [{ id: 'a', label: '<script>plain text</script>', color: 'url(secret)', image: 'https://tracker' }], edges: [] });
  assert.equal(plan.nodes[0].color, '#e0e7ff'); assert.equal(plan.nodes[0].image, undefined);
});
test('cyclic graph layouts have finite, nonoverlapping nodes with icons on and off', () => {
  for (const icons of [false, true]) {
    const plan = normalizePlan(sample()); plan.nodes[0].icon = 'database';
    const layout = layoutPlan(plan, icons);
    assert.equal(layout.edges.length, 3);
    for (const node of layout.nodes) {
      for (const key of ['x', 'y', 'width', 'height']) assert.ok(Number.isFinite(node[key]));
      for (const other of layout.nodes.filter(n => n.id !== node.id)) assert.ok(node.x + node.width <= other.x || other.x + other.width <= node.x || node.y + node.height <= other.y || other.y + other.height <= node.y);
    }
    for (const edge of layout.edges) assert.ok(edge.points.length >= 2 && edge.points.every(p => Number.isFinite(p.x) && Number.isFinite(p.y)));
  }
});
test('sequence messages stay chronological, including self messages and replies', () => {
  const plan = normalizePlan({ ...sample(), kind: 'sequence', edges: [{ source: 'a', target: 'b' }, { source: 'b', target: 'b' }, { source: 'b', target: 'a' }] });
  const layout = layoutPlan(plan, false);
  assert.ok(layout.edges[0].points[0].y < layout.edges[1].points[0].y);
  assert.ok(layout.edges[1].points[0].y < layout.edges[2].points[0].y);
  assert.equal(layout.edges[1].points.length, 4);
  assert.equal(preservesContent(plan, { ...plan, edges: [...plan.edges].reverse() }), false);
  assert.equal(preservesContent(plan, { ...plan, nodes: [...plan.nodes].reverse() }), false);
});
test('review cannot drop nodes, branches or repeated connections', () => {
  const plan = normalizePlan(sample());
  assert.equal(preservesContent(plan, normalizePlan(sample())), true);
  assert.equal(preservesContent(plan, { ...plan, edges: plan.edges.slice(1) }), false);
  assert.equal(preservesContent({ ...plan, edges: [...plan.edges, plan.edges[0]] }, plan), false);
});
test('local edits are scoped to selection and bound text; URLs and unrelated objects are rejected', () => {
  const source = { elements: [{ id: 'a', type: 'rectangle', x: 0, width: 200 }, { id: 'label', type: 'text', containerId: 'a', text: 'Before' }, { id: 'other', type: 'rectangle', x: 20 }] };
  const request = { current_schema: source, selected_node_ids: ['a'] };
  const patch = sanitizeEdit({ elements: [{ id: 'label', text: 'After', link: 'https://tracker' }, { id: 'other', x: 999 }, { id: 'new', text: 'Unexpected' }] }, request);
  const merged = mergeDeltaIntoSchema(source, patch, 'excalidraw', ['a']);
  assert.equal(merged.elements.find(e => e.id === 'label').text, 'After');
  assert.equal(merged.elements.find(e => e.id === 'other').x, 20);
  assert.equal(patch.elements[0].link, undefined); assert.equal(merged.elements.length, 3);
  assert.throws(() => sanitizeEdit({ elements: [{ id: 'other', x: 999 }] }, request));
});
test('locked node, its label, icon and files survive regeneration without duplicate companions', () => {
  const old = { elements: [{ id: 'a', type: 'rectangle', x: 5 }, { id: 'old-label', type: 'text', containerId: 'a' }, { id: 'old-icon', type: 'image', customData: { evoDesignIcon: { hostId: 'a' } } }], files: { old: {} } };
  const next = { elements: [{ id: 'a', type: 'rectangle', x: 500 }, { id: 'new-label', containerId: 'a' }, { id: 'new-icon', customData: { evoDesignIcon: { hostId: 'a' } } }, { id: 'b', type: 'rectangle' }], files: { new: {} } };
  const result = preserveLockedElements(next, old, ['a']);
  assert.deepEqual(result.elements.map(e => e.id), ['b', 'a', 'old-label', 'old-icon']);
  assert.equal(result.elements.find(e => e.id === 'a').x, 5); assert.deepEqual(Object.keys(result.files), ['new', 'old']);
});
