import { signEdgeIdentity } from '../../shared/edge-identity.mjs';

const COOKIE = 'evodesign_route';
const choices = new Set(['auto', 'global', 'cn']);
const routeCookie = value => `${COOKIE}=${value}; Path=/; Max-Age=${value === 'auto' ? 0 : 31536000}; Secure; HttpOnly; SameSite=Lax`;
const redirect = (target, cookie) => new Response(null, { status: 302, headers: {
  Location: target, 'Cache-Control': 'private, no-store', ...(cookie ? { 'Set-Cookie': routeCookie(cookie) } : {}),
  'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
} });

// A tiny same-origin check protects existing browser-only projects and DNA.
// Their contents never leave the device. This loads no application bundle.
export function entryGate(globalUrl, chinaUrl, cookie) {
  const nonce = crypto.randomUUID().replaceAll('-', '');
  const script = `let keep=true;try{keep=['evodiagram_guest_diagrams','evodiagram_guest_dna','evodesign.browser-model.v1'].some(k=>{const v=localStorage.getItem(k);return v&&v!=='[]'&&v!=='{}'&&v!=='null'})}catch{}location.replace(keep?${JSON.stringify(globalUrl)}:${JSON.stringify(chinaUrl)});`;
  return new Response(`<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EvoDesign</title><style>body{margin:0;display:grid;place-content:center;min-height:100dvh;background:#fafaff;color:#6c6580;font:14px system-ui}a{color:#6255d6;margin:12px}</style><p>正在选择访问线路…</p><script nonce="${nonce}">${script}</script><noscript><a href="${globalUrl}">国际工作台 / Global</a><a href="${chinaUrl}">国内工作台 / China</a></noscript></html>`, {
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'private, no-store',
      'Content-Security-Policy': `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; frame-ancestors 'none'`,
      'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff', ...(cookie ? { 'Set-Cookie': routeCookie(cookie) } : {}) },
  });
}

export function createRouter(fetcher = fetch) {
  return async (request, env) => {
    const url = new URL(request.url);
    if (url.origin !== env.MAIN_ORIGIN) return new Response('Not found', { status: 404 });
    const selected = url.searchParams.get('region');
    const cookie = request.headers.get('cookie')?.split(';').map(value => value.trim()).find(value => value.startsWith(`${COOKIE}=`))?.split('=')[1];
    const entry = (url.pathname === '/' || url.pathname === '/home') && !url.searchParams.has('project');
    const navigation = request.method === 'GET' && (request.headers.get('sec-fetch-mode') === 'navigate' || request.headers.get('accept')?.includes('text/html'));
    let preferenceCookie;
    if (entry && navigation && env.AUTO_ROUTE_ENABLED === '1') {
      if (choices.has(selected)) {
        if (selected === 'cn') return redirect(env.CHINA_URL, selected);
        // Automatic is not a choice of China: existing browser data still
        // keeps the visitor on this origin.
        if (selected === 'auto' && request.cf?.country === 'CN') return entryGate(`${env.MAIN_ORIGIN}/?region=global`, env.CHINA_URL, selected);
        // Keep the explicit choice in the landing URL as a fallback when
        // cookies are disabled; otherwise /home could enter a redirect loop.
        if (url.pathname !== '/home') return redirect(`${env.MAIN_ORIGIN}/home?region=${selected}`, selected);
        preferenceCookie = routeCookie(selected);
      } else if (cookie === 'cn') return redirect(env.CHINA_URL);
      else if (cookie !== 'global' && request.cf?.country === 'CN') {
        // Existing data stays on its original origin, even on a later visit.
        return entryGate(`${env.MAIN_ORIGIN}/?region=global`, env.CHINA_URL);
      }
    }
    const headers = new Headers(request.headers);
    headers.delete('x-evodesign-client-ip'); headers.delete('x-evodesign-client-proof');
    if (url.pathname === '/api/model' && env.DEMO_EDGE_IP_SECRET) {
      const ip = request.headers.get('cf-connecting-ip');
      if (ip && ip.length <= 64 && /^[0-9a-f:.]+$/i.test(ip)) {
        headers.set('x-evodesign-client-ip', ip);
        headers.set('x-evodesign-client-proof', await signEdgeIdentity(ip, env.DEMO_EDGE_IP_SECRET));
      }
    }
    // A same-zone route fetch reaches the Vercel origin defined by DNS;
    // no HTML rewriting or credential forwarding to a third-party host.
    const response = await fetcher(new Request(request, { headers, redirect: 'manual' }));
    if (!preferenceCookie) return response;
    const result = new Response(response.body, response);
    result.headers.append('Set-Cookie', preferenceCookie);
    result.headers.set('Cache-Control', 'private, no-store');
    return result;
  };
}

export default { fetch: createRouter() };
