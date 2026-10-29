import { createModelHandler } from '../../api/model.mjs';

const loopbackHosts = new Set(['localhost', '127.0.0.1', '[::1]']);
const loopbackPeers = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1']);

/** Dev-only counters. Production still uses its shared, atomic Redis budget. */
export function createLocalBudget(clock = Date.now) {
  let day = -1;
  let used = 0;
  const visitors = new Map();
  const active = new Map();
  return {
    reserve({ reserved, id, visitor, dailyTokens, concurrency, visitorRequests }) {
      const now = clock();
      const today = Math.floor(now / 86400000);
      if (today !== day) { day = today; used = 0; visitors.clear(); }
      for (const [key, expiry] of active) if (expiry <= now) active.delete(key);
      if (used + reserved > dailyTokens) return 0;
      if ((visitors.get(visitor) || 0) >= visitorRequests) return -2;
      if (active.size >= concurrency) return -1;
      used += reserved; visitors.set(visitor, (visitors.get(visitor) || 0) + 1);
      active.set(id, now + 150000);
      return 1;
    },
    release(id) { active.delete(id); },
  };
}

export function localModelEndpoint(base = 'https://open.bigmodel.cn/api/paas/v4') {
  const url = new URL(base);
  const path = url.pathname.replace(/\/+$/, '');
  if (url.protocol !== 'https:' || url.hostname !== 'open.bigmodel.cn' || url.username || url.password || url.search || url.hash
    || !['/api/paas/v4', '/api/coding/paas/v4'].includes(path)) throw new Error('Unsupported local model endpoint.');
  url.pathname = `${path}/chat/completions`;
  return url.href;
}
const jsonError = (response, status, message) => {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
  response.end(JSON.stringify({ error: { message } }));
};

/** Mount only the existing diagram endpoint, with no generic credential proxy. */
export function createLocalModelMiddleware(handle) {
  return async (request, response, next) => {
    if (request.url?.split('?')[0] !== '/api/model') { next(); return; }
    let origin;
    try {
      origin = new URL(`http://${request.headers.host}`);
      if (!loopbackHosts.has(origin.hostname) || !loopbackPeers.has(request.socket.remoteAddress)) {
        jsonError(response, 403, 'The local model endpoint requires a loopback connection.'); return;
      }
    } catch { jsonError(response, 400, 'Invalid local request.'); return; }
    const controller = new AbortController();
    const cancel = () => { if (!response.writableEnded) controller.abort(); };
    response.once('close', cancel);
    try {
      const headers = new Headers();
      for (const name of ['content-type', 'origin']) {
        if (typeof request.headers[name] === 'string') headers.set(name, request.headers[name]);
      }
      // Client-supplied forwarded IPs never influence the shared budget identity.
      headers.set('x-real-ip', request.socket.remoteAddress);
      const method = request.method ?? 'GET';
      let body;
      if (method === 'POST') {
        const chunks = [];
        let size = 0;
        for await (const chunk of request.iterator({ destroyOnReturn: false })) {
          size += chunk.length;
          if (size > 100000) {
            request.resume(); jsonError(response, 413, 'This diagram request is too large.'); return;
          }
          chunks.push(chunk);
        }
        body = Buffer.concat(chunks);
      }
      const result = await handle(new Request(new URL('/api/model', origin), { method, headers, body, signal: controller.signal }));
      if (response.destroyed) return;
      response.writeHead(result.status, Object.fromEntries(result.headers));
      response.end(Buffer.from(await result.arrayBuffer()));
    } catch {
      if (!response.destroyed && !response.headersSent) jsonError(response, 502, 'The local demo service is unavailable.');
      else if (!response.destroyed) response.end();
    } finally { response.removeListener('close', cancel); }
  };
}

export function createLocalDemoPlugin(env) {
  if (env.DEMO_USE_ENV_PROXY === '1') process.env.NODE_USE_ENV_PROXY = '1';
  const install = server => {
    const options = { endpoint: localModelEndpoint(env.DEMO_GLM_BASE_URL), budget: createLocalBudget() };
    server.middlewares.use(createLocalModelMiddleware(createModelHandler(env, fetch, options)));
  };
  return { name: 'evodesign-local-demo', apply: 'serve', configureServer: install, configurePreviewServer: install };
}
