import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import vm from 'node:vm';
import { createStudioServer } from '../../deploy/modelscope/server.mjs';
import { createRouter, entryGate } from '../../deploy/routing/worker.mjs';
import { signEdgeIdentity, visitorIp } from '../../shared/edge-identity.mjs';

const env = { MAIN_ORIGIN: 'https://evodesign.aurax.live', CHINA_URL: 'https://modelscope.cn/studios/GeminiLight/EvoDesign?mode=full', AUTO_ROUTE_ENABLED: '1' };
const request = (path = '/', country = 'CN', headers = {}) => {
  const req = new Request(`${env.MAIN_ORIGIN}${path}`, { headers: { Accept: 'text/html', ...headers } });
  Object.defineProperty(req, 'cf', { value: { country } });
  return req;
};

test('entry routing respects explicit choice, remembers it, and never redirects canvas, API or assets', async () => {
  const seen = [];
  const router = createRouter(async req => { seen.push(req); return new Response('origin'); });
  const automatic = await router(request(), env);
  assert.equal(automatic.status, 200);
  assert.match(await automatic.text(), /localStorage/);
  for (const path of ['/workspace?project=guest_a', '/projects', '/dna', '/assets/app.js', '/api/model', '/home?project=guest_a']) {
    assert.equal(await (await router(request(path), env)).text(), 'origin');
  }
  for (const country of ['US', 'HK', 'TW', null]) assert.equal(await (await router(request('/', country), env)).text(), 'origin');
  const selected = await router(request('/?region=cn', 'US'), env);
  assert.equal(selected.status, 302);
  assert.equal(selected.headers.get('location'), env.CHINA_URL);
  assert.match(selected.headers.get('set-cookie'), /cn;.*HttpOnly/);
  const stay = await router(request('/home', 'CN', { Cookie: 'evodesign_route=global' }), env);
  assert.equal(await stay.text(), 'origin');
  const reset = await router(request('/?region=auto', 'US'), env);
  assert.match(reset.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal(await (await router(request('/home?region=global', 'CN'), env)).text(), 'origin');
  assert.equal(await (await router(request(), { ...env, AUTO_ROUTE_ENABLED: '0' })).text(), 'origin');
  assert.equal((await router(new Request('https://evil.example/'), env)).status, 404);
  assert.ok(seen.length > 0);
});

test('same-origin gate keeps existing and unreadable data; empty browsers take the China route', async () => {
  const body = await entryGate('https://evodesign.aurax.live/?region=global', env.CHINA_URL).text();
  const script = body.match(/<script nonce="[^"]+">([^]*?)<\/script>/)[1];
  for (const [stored, expected] of [[null, env.CHINA_URL], ['[]', env.CHINA_URL], ['[{"project_id":"guest_a"}]', 'https://evodesign.aurax.live/?region=global'], ['unreadable', 'https://evodesign.aurax.live/?region=global']]) {
    let destination;
    vm.runInNewContext(script, { localStorage: { getItem: key => key === 'evodiagram_guest_diagrams' ? stored : null }, location: { replace: value => { destination = value; } } });
    assert.equal(destination, expected);
  }
  let blocked;
  vm.runInNewContext(script, { localStorage: { getItem: () => { throw Error('blocked'); } }, location: { replace: value => { blocked = value; } } });
  assert.equal(blocked, 'https://evodesign.aurax.live/?region=global');
});

test('proxy identity is signed, expires and cannot be supplied by an untrusted client', async () => {
  const secret = 'test-only-edge-secret'; const ip = '203.0.113.8';
  const now = Date.now(); const proof = await signEdgeIdentity(ip, secret, now);
  const signed = new Request('https://evodesign.aurax.live/api/model', { headers: { 'x-real-ip': '192.0.2.1', 'x-evodesign-client-ip': ip, 'x-evodesign-client-proof': proof } });
  assert.equal(await visitorIp(signed, secret, now), ip);
  assert.equal(await visitorIp(signed, 'wrong-key', now), '192.0.2.1');
  assert.equal(await visitorIp(signed, secret, now + 91000), '192.0.2.1');
  assert.equal(await visitorIp(signed, ''), '192.0.2.1');
  let forwarded;
  await createRouter(async req => { forwarded = req; return new Response('OK'); })(request('/api/model', 'CN', {
    'cf-connecting-ip': ip, 'x-evodesign-client-ip': 'spoofed', 'x-evodesign-client-proof': 'spoofed',
  }), { ...env, DEMO_EDGE_IP_SECRET: secret });
  assert.equal(await visitorIp(forwarded, secret), ip);
  await createRouter(async req => { forwarded = req; return new Response('OK'); })(request('/api/model', 'CN', {
    'x-evodesign-client-ip': ip, 'x-evodesign-client-proof': proof,
  }), env);
  assert.equal(forwarded.headers.has('x-evodesign-client-proof'), false);
});

test('Studio serves SPA routes and real assets; bounded API preserves origin rejection', async () => {
  const root = await mkdtemp(join(tmpdir(), 'evodesign-studio-test-'));
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'index.html'), '<html>EvoDesign</html>');
  await writeFile(join(root, 'assets/app.js'), 'export const app = true;');
  const server = createStudioServer({ env: { STUDIO_PUBLIC_ORIGIN: 'https://geminilight-evodesign.ms.show' }, root });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const path of ['/', '/home', '/workspace?project=guest_a', '/dna']) {
      const response = await fetch(base + path);
      assert.equal(response.status, 200); assert.match(await response.text(), /EvoDesign/);
      assert.match(response.headers.get('content-security-policy'), /https:\/\/modelscope.cn/);
      assert.equal(response.headers.get('x-frame-options'), null);
    }
    assert.match((await fetch(base + '/assets/app.js')).headers.get('cache-control'), /immutable/);
    for (const path of ['/assets/missing.js', '/brand/missing.svg', '/api/missing']) assert.equal((await fetch(base + path)).status, 404);
    assert.deepEqual(await (await fetch(base + '/api/model')).json(), { available: false, model: 'glm-5.3-flash' });
    assert.equal((await fetch(base + '/api/model', { method: 'POST', headers: { Origin: 'https://evil.example', 'Content-Type': 'application/json' }, body: '{}' })).status, 403);
    assert.equal((await fetch(base + '/api/model', { method: 'POST', headers: { Origin: 'https://geminilight-evodesign.ms.show', 'Content-Type': 'application/json' }, body: '{}' })).status, 503);
    assert.equal((await fetch(base + '/api/model', { method: 'POST', body: 'x'.repeat(100001) })).status, 413);
  } finally { await new Promise(resolve => server.close(resolve)); await rm(root, { recursive: true, force: true }); }
});
