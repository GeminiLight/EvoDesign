import { createHmac, randomUUID } from 'node:crypto';
import { PLAN_PROMPT, EDIT_PROMPT } from '../shared/diagram-prompts.mjs';

const MODEL = 'glm-5.3-flash';
const ENDPOINT = 'https://open.bigmodel.cn/api/paas/v4/chat/completions';
const BUDGET_KEY = 'evodesign:{demo-budget}';
const SYSTEMS = { diagram: PLAN_PROMPT, edit: EDIT_PROMPT, check: 'Reply with OK.' };
const positive = (value, fallback) => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : fallback;

// One atomic reservation across all function instances; only anonymous counters
// are stored. Failed requests retain their reservation, so retries cannot overspend.
export const RESERVE_SCRIPT = `
local now=tonumber(redis.call('TIME')[1])
local day=math.floor(now/86400)
local counter=KEYS[1]..':day:'..day
local visitor=counter..':visitor:'..ARGV[5]
local active=KEYS[1]..':active'
redis.call('ZREMRANGEBYSCORE',active,'-inf',now)
if tonumber(redis.call('GET',counter) or '0')+tonumber(ARGV[1])>tonumber(ARGV[2]) then return 0 end
if tonumber(redis.call('GET',visitor) or '0')>=tonumber(ARGV[6]) then return -2 end
if redis.call('ZCARD',active)>=tonumber(ARGV[3]) then return -1 end
redis.call('INCRBY',counter,ARGV[1])
redis.call('EXPIREAT',counter,(day+2)*86400)
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

export function createModelHandler(env = process.env, fetcher = fetch) {
  return async function handle(request) {
    const configured = Boolean(env.DEMO_GLM_API_KEY && env.DEMO_REDIS_URL && env.DEMO_REDIS_TOKEN);
    if (request.method === 'GET') return reply({ available: configured, model: MODEL });
    if (request.method !== 'POST') return error('method', 'Use POST.', 405, { Allow: 'GET, POST' });
    const origin = request.headers.get('origin');
    if (origin && origin !== new URL(request.url).origin) return error('origin', 'Use the EvoDesign workspace.', 403);
    if (!configured) return error('setup', 'The shared model is unavailable. Connect your own model in Model settings.', 503);
    if (!request.headers.get('content-type')?.startsWith('application/json')) return error('input', 'Send diagram JSON.', 415);
    let input;
    try {
      if (Number(request.headers.get('content-length')) > 100_000) throw new Error();
      const text = await request.text();
      if (new TextEncoder().encode(text).length > 100_000) throw new Error();
      input = JSON.parse(text);
    } catch { return error('input', 'This diagram request is too large or invalid.', 400); }
    if (!input || !Object.hasOwn(SYSTEMS, input.task) || typeof input.prompt !== 'string' || !input.prompt.trim()) {
      return error('input', 'Choose a diagram task and provide its content.', 400);
    }
    const maxTokens = input.task === 'check' ? 256 : Math.min(8192, positive(input.maxTokens, 8192));
    const system = SYSTEMS[input.task];
    const reserved = new TextEncoder().encode(system + input.prompt).length + maxTokens + 512;
    const id = randomUUID();
    // Vercel overwrites x-real-ip; never trust a client-supplied forwarded chain.
    const ip = request.headers.get('x-real-ip') || 'unknown';
    const day = Math.floor(Date.now() / 86_400_000);
    const visitor = createHmac('sha256', env.DEMO_GLM_API_KEY).update(`${day}:${ip}`).digest('hex').slice(0, 24);
    let reservation;
    try {
      reservation = await budget(['EVAL', RESERVE_SCRIPT, 1, BUDGET_KEY, reserved,
        positive(env.DEMO_DAILY_TOKENS, 2_000_000), positive(env.DEMO_CONCURRENCY, 4), id,
        visitor, positive(env.DEMO_VISITOR_REQUESTS, 40)], env, fetcher);
    } catch { return error('budget', 'The shared model is temporarily unavailable. Retry later or use your own model.', 503); }
    if (reservation === -1) return error('busy', 'The shared model is busy. Retry shortly or use your own model.', 429, { 'Retry-After': '10' });
    if (reservation === 0 || reservation === -2) return error('quota', 'Today’s demo allowance has been reached. Connect your own model to continue.', 429);
    if (reservation !== 1) return error('budget', 'The shared model is temporarily unavailable.', 503);
    try {
      const response = await fetcher(ENDPOINT, {
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
      try { await budget(['ZREM', `${BUDGET_KEY}:active`, id], env, fetcher); }
      catch { /* The lease expires independently after the request deadline. */ }
    }
  };
}

export default { fetch: createModelHandler() };
