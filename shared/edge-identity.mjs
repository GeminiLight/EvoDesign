const encoder = new TextEncoder();
const validIp = value => typeof value === 'string' && value.length <= 64 && /^[0-9a-f:.]+$/i.test(value);

async function key(secret, usage) {
  return crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, [usage]);
}

/** A short-lived proof of the IP supplied by our Cloudflare ingress. */
export async function signEdgeIdentity(ip, secret, now = Date.now()) {
  const stamp = String(Math.floor(now / 1000));
  const signature = await crypto.subtle.sign('HMAC', await key(secret, 'sign'), encoder.encode(`${stamp}:${ip}`));
  return `${stamp}.${Array.from(new Uint8Array(signature), byte => byte.toString(16).padStart(2, '0')).join('')}`;
}

export async function visitorIp(request, secret, now = Date.now()) {
  const fallback = request.headers.get('x-real-ip') || 'unknown';
  if (!secret) return fallback;
  const ip = request.headers.get('x-evodesign-client-ip');
  const proof = request.headers.get('x-evodesign-client-proof') || '';
  const match = /^(\d{10})\.([0-9a-f]{64})$/.exec(proof);
  if (!validIp(ip) || !match || Math.abs(now / 1000 - Number(match[1])) > 90) return fallback;
  const bytes = Uint8Array.from(match[2].match(/../g), hex => parseInt(hex, 16));
  const verified = await crypto.subtle.verify('HMAC', await key(secret, 'verify'), bytes, encoder.encode(`${match[1]}:${ip}`));
  return verified ? ip : fallback;
}
