import assert from 'node:assert/strict';
import { createServer, request as httpRequest } from 'node:http';
import { test } from 'node:test';
import { createLocalModelMiddleware } from '../server/localDemo.mjs';
import { createModelHandler } from '../../api/model.mjs';

async function serve(handle, run) {
  const middleware = createLocalModelMiddleware(handle);
  const server = createServer((req, res) => { void middleware(req, res, () => { res.writeHead(404); res.end('next'); }); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try { await run(base); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test('local discovery mounts only the model route and never returns a credential', async () => {
  await serve(createModelHandler({}), async base => {
    assert.deepEqual(await (await fetch(`${base}/api/model`)).json(), { available: false, model: 'glm-5.3-flash' });
    assert.equal((await fetch(`${base}/api/other`)).status, 404);
  });
});
test('the local adapter retains the production model, budget and same-origin checks', async () => {
  const env = { DEMO_GLM_API_KEY: 'private-key', DEMO_REDIS_URL: 'https://budget.example', DEMO_REDIS_TOKEN: 'private-budget' };
  const calls = [];
  const handle = createModelHandler(env, async (url, options) => {
    const body = JSON.parse(options.body); calls.push({ url, body });
    if (url === env.DEMO_REDIS_URL) return Response.json({ result: 1 });
    return Response.json({ choices: [{ message: { content: 'OK' }, finish_reason: 'stop' }] });
  });
  await serve(handle, async base => {
    const request = { method: 'POST', headers: { Origin: base, 'Content-Type': 'application/json', 'x-real-ip': 'forged-client-ip' }, body: JSON.stringify({ task: 'check', prompt: 'Connection test.', maxTokens: 1 }) };
    const response = await fetch(`${base}/api/model`, request);
    assert.equal(response.status, 200);
    const text = await response.text();
    assert.ok(text.includes('OK') && !text.includes('private'));
    assert.equal(calls.length, 3);
    assert.equal(calls[1].body.model, 'glm-5.3-flash');
    assert.equal(calls[1].body.max_tokens, 256);
    assert.ok(!JSON.stringify(calls[0].body).includes('forged-client-ip'));
    assert.equal((await fetch(`${base}/api/model`, { ...request, headers: { ...request.headers, Origin: 'https://foreign.example' } })).status, 403);
    assert.equal(calls.length, 3);
  });
});
test('foreign Host and oversized bodies never reach the handler', async () => {
  let count = 0;
  await serve(async () => { count++; return Response.json({}); }, async base => {
    const status = await new Promise((resolve, reject) => {
      const req = httpRequest(`${base}/api/model`, { headers: { Host: 'foreign.example' } }, res => { res.resume(); resolve(res.statusCode); });
      req.on('error', reject); req.end();
    });
    assert.equal(status, 403);
    assert.equal((await fetch(`${base}/api/model`, { method: 'POST', body: 'x'.repeat(100001) })).status, 413);
    assert.equal(count, 0);
  });
});

test('local budgets keep reservations, cap concurrency and visitors, and expire leases', async () => {
  const { createLocalBudget } = await import('../server/localDemo.mjs');
  let now = 0;
  const store = createLocalBudget(() => now);
  const input = { reserved: 70, id: 'one', visitor: 'local', dailyTokens: 100, concurrency: 1, visitorRequests: 2 };
  assert.equal(store.reserve(input), 1);
  assert.equal(store.reserve({ ...input, id: 'busy', reserved: 1 }), -1);
  store.release('one');
  assert.equal(store.reserve({ ...input, id: 'over', reserved: 40 }), 0);
  assert.equal(store.reserve({ ...input, id: 'two', reserved: 20 }), 1);
  store.release('two');
  assert.equal(store.reserve({ ...input, id: 'visitor-limit', reserved: 1 }), -2);
  now = 86400000;
  assert.equal(store.reserve({ ...input, id: 'new-day' }), 1);
  now += 150001;
  assert.equal(store.reserve({ ...input, id: 'expired-lease', reserved: 1 }), 1);
});
test('local Coding setup needs no Redis and uses only the server-selected BigModel endpoint', async () => {
  const { createLocalBudget, localModelEndpoint } = await import('../server/localDemo.mjs');
  const endpoint = localModelEndpoint('https://open.bigmodel.cn/api/coding/paas/v4/');
  assert.equal(endpoint, 'https://open.bigmodel.cn/api/coding/paas/v4/chat/completions');
  for (const invalid of ['http://open.bigmodel.cn/api/paas/v4', 'https://foreign.example/api/paas/v4', 'https://open.bigmodel.cn/api/paas/v4?key=x', 'https://user:pass@open.bigmodel.cn/api/paas/v4', 'https://open.bigmodel.cn/other']) {
    assert.throws(() => localModelEndpoint(invalid));
  }
  const calls = [];
  const handler = createModelHandler({ DEMO_GLM_API_KEY: 'local-private-key' }, async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return Response.json({ choices: [{ message: { content: 'OK' }, finish_reason: 'stop' }] });
  }, { endpoint, budget: createLocalBudget() });
  await serve(handler, async base => {
    assert.equal((await (await fetch(`${base}/api/model`)).json()).available, true);
    const response = await fetch(`${base}/api/model`, { method: 'POST', headers: { Origin: base, 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: 'check', prompt: 'Test', endpoint: 'https://foreign.example', model: 'different' }) });
    assert.equal(response.status, 200);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, endpoint);
    assert.equal(calls[0].body.model, 'glm-5.3-flash');
  });
});
