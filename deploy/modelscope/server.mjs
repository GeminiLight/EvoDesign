import { createServer } from 'node:http';
import { createReadStream } from 'node:fs';
import { stat, readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createModelHandler } from '../../api/model.mjs';

const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.wasm': 'application/wasm' };

/** Production adapter for the same browser build and bounded model handler. */
export function createStudioServer({ env = process.env, root = resolve('static'), handle = createModelHandler(env) } = {}) {
  const origin = new URL(env.STUDIO_PUBLIC_ORIGIN || 'http://127.0.0.1:7860').origin;
  const base = resolve(root);
  return createServer(async (req, res) => {
    const controller = new AbortController();
    res.once('close', () => { if (!res.writableEnded) controller.abort(); });
    const send = (status, body, headers = {}) => {
      res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers });
      res.end(JSON.stringify(body));
    };
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    // ModelScope displays the application inside its Studio iframe.
    res.setHeader('Content-Security-Policy', "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn https://modelscope.ai https://www.modelscope.ai");
    try {
      const url = new URL(req.url, origin);
      if (url.pathname === '/api/health') {
        if (req.method !== 'GET' && req.method !== 'HEAD') { send(405, { error: 'Use GET.' }); return; }
        send(200, { ok: true, region: 'cn', revision: env.APP_REVISION || 'local' }); return;
      }
      if (url.pathname === '/api/model') {
        const headers = new Headers();
        for (const name of ['content-type', 'origin', 'referer']) {
          if (typeof req.headers[name] === 'string') headers.set(name, req.headers[name]);
        }
        // The managed Studio ingress supplies x-real-ip. Never accept the
        // leftmost entry of a client-controlled X-Forwarded-For chain.
        headers.set('x-real-ip', req.headers['x-real-ip'] || req.socket.remoteAddress || 'unknown');
        const method = req.method || 'GET';
        let body;
        if (method === 'POST') {
          if (Number(req.headers['content-length']) > 100_000) { req.resume(); send(413, { error: { code: 'input', message: 'Request too large.' } }); return; }
          const chunks = []; let size = 0;
          for await (const chunk of req.iterator({ destroyOnReturn: false })) {
            size += chunk.length;
            if (size > 100_000) { req.resume(); send(413, { error: { code: 'input', message: 'Request too large.' } }); return; }
            chunks.push(chunk);
          }
          body = Buffer.concat(chunks);
        }
        const result = await handle(new Request(new URL('/api/model', origin), { method, headers, body, signal: controller.signal }));
        if (res.destroyed) return;
        res.writeHead(result.status, Object.fromEntries(result.headers));
        res.end(Buffer.from(await result.arrayBuffer())); return;
      }
      if (url.pathname.startsWith('/api/')) { send(404, { error: 'Not found.' }); return; }
      if (req.method !== 'GET' && req.method !== 'HEAD') { send(405, { error: 'Use GET.' }, { Allow: 'GET, HEAD' }); return; }
      let path;
      try { path = decodeURIComponent(url.pathname); } catch { send(400, { error: 'Invalid URL.' }); return; }
      let file = resolve(base, `.${path}`);
      if (file !== base && !file.startsWith(`${base}/`)) { send(404, { error: 'Not found.' }); return; }
      let info;
      try { info = await stat(file); } catch { /* Route fallback below. */ }
      if (!info?.isFile()) {
        if (extname(path) || path.startsWith('/assets/') || path.startsWith('/brand/')) { send(404, { error: 'Not found.' }); return; }
        file = resolve(base, 'index.html'); info = await stat(file);
      }
      res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream', 'Content-Length': info.size,
        'Cache-Control': file.includes('/assets/') ? 'public, max-age=31536000, immutable' : 'no-cache' });
      if (req.method === 'HEAD') res.end();
      else createReadStream(file).on('error', () => res.destroy()).pipe(res);
    } catch {
      if (!res.headersSent) send(500, { error: 'The workspace is temporarily unavailable.' });
      else res.destroy();
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  // Fail before accepting traffic if the static release is incomplete.
  await readFile(resolve('static/index.html'));
  createStudioServer().listen(Number(process.env.PORT || 7860), '0.0.0.0', () => console.log('EvoDesign listening on port 7860'));
}
