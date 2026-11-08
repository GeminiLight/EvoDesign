import { handleRunRequest, visitorTokenLimit, VISITOR_QUOTA_MESSAGE } from '../shared/model-runs.mjs';
import { createHmac, randomUUID } from 'node:crypto';
import { EDIT_PROMPT } from '../shared/diagram-prompts.mjs';
import { visitorIp } from '../shared/edge-identity.mjs';

const MODEL = 'glm-5.3-flash';
const ENDPOINT = 'https://open.bigmodel.cn/api/paas/v4/chat/completions';
const BUDGET_KEY = 'evodesign:{demo-budget}';
const SYSTEMS = { edit: EDIT_PROMPT, check: 'Reply with OK.' };
const positive = (value, fallback) => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : fallback;

// One atomic reservation across all function instances; only anonymous counters
// are stored. Failed requests retain their reservation, so retries cannot overspend.
export const RESERVE_SCRIPT = `
local now=tonumber(redis.call('TIME')[1])
local day=math.floor(now/86400)
local counter=KEYS[1]..':day:'..day
local visitor=counter..':visitor:'..ARGV[5]
local visitorTokens=counter..':tokens:'..ARGV[5]
local active=KEYS[1]..':active'
redis.call('ZREMRANGEBYSCORE',active,'-inf',now)
if tonumber(redis.call('GET',counter) or '0')+tonumber(ARGV[1])>tonumber(ARGV[2]) then return 0 end
if tonumber(redis.call('GET',visitor) or '0')>=tonumber(ARGV[6]) then return -2 end
if tonumber(redis.call('GET',visitorTokens) or '0')+tonumber(ARGV[1])>tonumber(ARGV[7]) then return -4 end
if redis.call('ZCARD',active)>=tonumber(ARGV[3]) then return -1 end
redis.call('INCRBY',counter,ARGV[1])
redis.call('EXPIREAT',counter,(day+2)*86400)
redis.call('INCRBY',visitorTokens,ARGV[1])
redis.call('EXPIREAT',visitorTokens,(day+2)*86400)
redis.call('INCR',visitor)
redis.call('EXPIREAT',visitor,(day+2)*86400)
redis.call('ZADD',active,now+150,ARGV[4])
return 1`;

async function budget(args, env, fetcher) {
  const response = await fetcher(env.DEMO_REDIS_URL, {
    method: 'POST', headers: { Authorization: `Bearer ${env.DEMO_REDIS_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(args), signal: AbortSignal.timeout(5000), cache: 'no-store', redirect: 'error',
  });
  if (!response.ok) throw new Error('Budget unavailable');
  const data = await response.json();
  if (data.error) throw new Error('Budget unavailable');
  return data.result;
}

const reply = (data, status = 200, extra = {}) => Response.json(data, {
  status, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...extra },
});
const error = (code, message, status, extra) => reply({ error: { code, message } }, status, extra);
function requestOrigin(request) {
  const origin = request.headers.get('origin');
  if (origin) return origin;
  try { return new URL(request.headers.get('referer') || '').origin; } catch { return null; }
}

async function readBoundedBody(request, limit) {
  if (Number(request.headers.get('content-length')) > limit) throw new Error('body size');
  if (!request.body) return '';
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); throw new Error('body size'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder().decode(bytes);
}

export function createModelHandler(env = process.env, fetcher = fetch, options = {}) {
  return async function handle(request) {
    const configured = Boolean(env.DEMO_GLM_API_KEY && (options.budget || (env.DEMO_REDIS_URL && env.DEMO_REDIS_TOKEN)));
    if (request.method === 'GET') return reply({ available: configured, model: MODEL });
    if (request.method !== 'POST') return error('method', 'Use POST.', 405, { Allow: 'GET, POST' });
    // Browsers send Origin on every POST; fall back to Referer for older
    // clients. A request carrying neither (curl, scripts) is not from the
    // workspace and must not spend the shared budget.
    if (requestOrigin(request) !== new URL(request.url).origin) return error('origin', 'Use the EvoDesign workspace.', 403);
    if (!configured) return error('setup', 'The shared model is unavailable. Connect your own model in Model settings.', 503);
    if (!request.headers.get('content-type')?.startsWith('application/json')) return error('input', 'Send diagram JSON.', 415);
    let input;
    try {
      const text = await readBoundedBody(request, 8_000_000);
      input = JSON.parse(text);
    } catch { return error('input', 'This diagram request is too large or invalid.', 400); }
    const ip = await visitorIp(request, env.DEMO_EDGE_IP_SECRET);
    const day = Math.floor(Date.now() / 86_400_000);
    const visitor = createHmac('sha256', env.DEMO_GLM_API_KEY).update(`${day}:${ip}`).digest('hex').slice(0, 24);
    if (input?.task === 'start_run' || input?.runToken || Array.isArray(input?.messages)) {
      return handleRunRequest({ request, input, visitor, env, fetcher, options, budget, key: BUDGET_KEY, model: MODEL, endpoint: ENDPOINT, reply, error, positive });
    }
    if (new TextEncoder().encode(JSON.stringify(input)).length > 100000) return error('input', 'This diagram request is too large.', 400);
    if (!input || !Object.hasOwn(SYSTEMS, input.task) || typeof input.prompt !== 'string' || !input.prompt.trim()) {
      return error('input', 'Choose a diagram task and provide its content.', 400);
    }
    const maxTokens = input.task === 'check' ? 256 : Math.min(8192, positive(input.maxTokens, 8192));
    const system = SYSTEMS[input.task];
    const reserved = new TextEncoder().encode(system + input.prompt).length + maxTokens + 512;
    const id = randomUUID();
    // Direct traffic uses Vercel's overwritten x-real-ip. Our Cloudflare
    // ingress signs its real client IP so proxy users do not share one limit.
    let reservation;
    try {
      const dailyTokens = positive(env.DEMO_DAILY_TOKENS, 2_000_000);
      const limits = { reserved, id, visitor, dailyTokens, visitorTokens: visitorTokenLimit(dailyTokens, env.DEMO_VISITOR_DAILY_TOKENS),
        concurrency: positive(env.DEMO_CONCURRENCY, 4), visitorRequests: positive(env.DEMO_VISITOR_REQUESTS, 40) };
      reservation = options.budget ? await options.budget.reserve(limits)
        : await budget(['EVAL', RESERVE_SCRIPT, 1, BUDGET_KEY, reserved,
          limits.dailyTokens, limits.concurrency, id, visitor, limits.visitorRequests, limits.visitorTokens], env, fetcher);
    } catch { return error('budget', 'The shared model is temporarily unavailable. Retry later or use your own model.', 503); }
    if (reservation === -1) return error('busy', 'The shared model is busy. Retry shortly or use your own model.', 429, { 'Retry-After': '10' });
    if (reservation === -4 || reservation === -2) return error('visitor_quota', VISITOR_QUOTA_MESSAGE, 429);
    if (reservation === 0) return error('daily_quota', 'The shared demo has reached its daily allowance. Connect your own model to continue.', 429);
    if (reservation !== 1) return error('budget', 'The shared model is temporarily unavailable.', 503);
    try {
      const response = await fetcher(options.endpoint || ENDPOINT, {
        method: 'POST', headers: { Authorization: `Bearer ${env.DEMO_GLM_API_KEY}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: MODEL, messages: [{ role: 'system', content: system }, { role: 'user', content: input.prompt }],
          max_tokens: maxTokens, stream: false, thinking: { type: 'disabled' },
          ...(input.task !== 'check' ? { response_format: { type: 'json_object' } } : {}) }),
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(120_000)]), redirect: 'error',
      });
      if (!response.ok) return error('provider', 'The shared model could not complete this request. Retry later or use your own model.', response.status === 429 ? 429 : 502);
      const data = await response.json();
      const choice = data?.choices?.[0];
      if (data.error || !choice || typeof choice.message?.content !== 'string') return error('provider', 'The shared model returned no diagram. Please retry.', 502);
      // Return only the completion. Provider metadata and credentials stay server-side.
      return reply({ choices: [{ message: { role: 'assistant', content: choice.message.content }, finish_reason: choice.finish_reason }] });
    } catch { return error('timeout', 'The shared model request timed out or was interrupted. Please retry.', 504); }
    finally {
      try {
        if (options.budget) await options.budget.release(id);
        else await budget(['ZREM', `${BUDGET_KEY}:active`, id], env, fetcher);
      }
      catch { /* The lease expires independently after the request deadline. */ }
    }
  };
}

export default { fetch: createModelHandler() };
