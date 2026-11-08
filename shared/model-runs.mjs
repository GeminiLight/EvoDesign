import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';

export const RUN_TTL = 900;
const CALL_LIMIT = 40;
const TOKEN_LIMIT = 400_000;
export function visitorTokenLimit(dailyTokens, configuredLimit) {
  const fairShare = Math.floor(dailyTokens / 5);
  const limit = Number(configuredLimit);
  return Number.isSafeInteger(limit) && limit > 0 ? Math.min(limit, fairShare) : fairShare;
}
export const VISITOR_QUOTA_MESSAGE = 'This visitor’s shared model allowance has been reached for today. Connect your own model to continue.';
export const ISSUE_RUN_SCRIPT = `
local now=tonumber(redis.call('TIME')[1])
local day=math.floor(now/86400)
local visitor=KEYS[1]..':day:'..day..':visitor:'..ARGV[2]
if tonumber(redis.call('GET',visitor) or '0')>=tonumber(ARGV[3]) then return -2 end
redis.call('INCR',visitor)
redis.call('EXPIREAT',visitor,(day+2)*86400)
local run=KEYS[1]..':run:'..ARGV[1]
redis.call('HSET',run,'visitor',ARGV[2],'calls',0,'tokens',0)
redis.call('EXPIRE',run,ARGV[4])
return 1`;
export const RESERVE_RUN_SCRIPT = `
local now=tonumber(redis.call('TIME')[1])
local day=math.floor(now/86400)
local run=KEYS[1]..':run:'..ARGV[7]
if redis.call('HGET',run,'visitor')~=ARGV[5] then return -3 end
if tonumber(redis.call('HGET',run,'calls') or '0')>=tonumber(ARGV[8]) then return -2 end
if tonumber(redis.call('HGET',run,'tokens') or '0')+tonumber(ARGV[1])>tonumber(ARGV[9]) then return -2 end
local counter=KEYS[1]..':day:'..day
local visitorTokens=counter..':tokens:'..ARGV[5]
local active=KEYS[1]..':active'
redis.call('ZREMRANGEBYSCORE',active,'-inf',now)
if tonumber(redis.call('GET',counter) or '0')+tonumber(ARGV[1])>tonumber(ARGV[2]) then return 0 end
if tonumber(redis.call('GET',visitorTokens) or '0')+tonumber(ARGV[1])>tonumber(ARGV[10]) then return -4 end
if redis.call('ZCARD',active)>=tonumber(ARGV[3]) then return -1 end
redis.call('HINCRBY',run,'calls',1)
redis.call('HINCRBY',run,'tokens',ARGV[1])
redis.call('INCRBY',counter,ARGV[1])
redis.call('EXPIREAT',counter,(day+2)*86400)
redis.call('INCRBY',visitorTokens,ARGV[1])
redis.call('EXPIREAT',visitorTokens,(day+2)*86400)
redis.call('ZADD',active,now+150,ARGV[4])
return 1`;

const sign = (text, secret) => createHmac('sha256', secret).update(`evodesign-run-v1:${text}`).digest('base64url');
function tokenFor(claims, secret) {
  const text = Buffer.from(JSON.stringify(claims)).toString('base64url');
  return `${text}.${sign(text, secret)}`;
}
function claimsFor(token, secret, visitor) {
  if (typeof token !== 'string' || token.length > 1024) return null;
  const parts = token.split('.');
  if (parts.length !== 2) return null;
  const expected = Buffer.from(sign(parts[0], secret));
  const supplied = Buffer.from(parts[1]);
  if (expected.length !== supplied.length || !timingSafeEqual(expected, supplied)) return null;
  try {
    const claims = JSON.parse(Buffer.from(parts[0], 'base64url').toString('utf8'));
    const now = Math.floor(Date.now() / 1000);
    if (!/^[a-f0-9-]{36}$/.test(claims.id) || claims.visitor !== visitor || !Number.isInteger(claims.exp)
      || claims.exp <= now || claims.exp > now + RUN_TTL) return null;
    return claims;
  } catch { return null; }
}

/** An allowlist for the engine's Chat Completions requests. URLs are data-only. */
export function sanitizeRunChat(input, model) {
  if (!Array.isArray(input.messages) || !input.messages.length || input.messages.length > 100) throw new Error('messages');
  const shortString = (value, max = 1000000) => typeof value === 'string' && value.length <= max;
  const messages = input.messages.map(message => {
    if (!message || !['system', 'user', 'assistant', 'tool'].includes(message.role)) throw new Error('role');
    const result = { role: message.role };
    if (shortString(message.content)) result.content = message.content;
    else if (message.content === null && message.role === 'assistant') result.content = null;
    else if (Array.isArray(message.content) && message.content.length <= 32) {
      result.content = message.content.map(part => {
        if (part?.type === 'text' && shortString(part.text)) return { type: 'text', text: part.text };
        const url = part?.image_url?.url;
        if (part?.type === 'image_url' && typeof url === 'string' && url.length <= 7_000_000
          && /^data:image\/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}$/.test(url)) {
          return { type: 'image_url', image_url: { url, ...(['auto', 'low', 'high'].includes(part.image_url.detail) ? { detail: part.image_url.detail } : {}) } };
        }
        throw new Error('content');
      });
    } else throw new Error('content');
    if (message.role === 'tool') {
      if (!shortString(message.tool_call_id, 256)) throw new Error('tool_call_id');
      result.tool_call_id = message.tool_call_id;
    }
    if (message.tool_calls !== undefined) {
      if (message.role !== 'assistant' || !Array.isArray(message.tool_calls) || message.tool_calls.length > 64) throw new Error('tool_calls');
      result.tool_calls = message.tool_calls.map(call => {
        if (!shortString(call?.id, 256) || call.type !== 'function' || !shortString(call.function?.name, 128) || !shortString(call.function?.arguments)) throw new Error('tool_call');
        return { id: call.id, type: 'function', function: { name: call.function.name, arguments: call.function.arguments } };
      });
    }
    return result;
  });
  const requested = input.max_completion_tokens ?? input.max_tokens ?? 16384;
  if (!Number.isSafeInteger(requested) || requested < 1) throw new Error('max_tokens');
  const body = { model, messages, max_tokens: Math.min(requested, 32768), stream: false, thinking: { type: 'disabled' } };
  if (typeof input.temperature === 'number' && Number.isFinite(input.temperature) && input.temperature >= 0 && input.temperature <= 2) body.temperature = input.temperature;
  if (input.tools !== undefined) {
    if (!Array.isArray(input.tools) || input.tools.length > 64 || JSON.stringify(input.tools).length > 100000) throw new Error('tools');
    body.tools = input.tools.map(tool => {
      if (tool?.type !== 'function' || !shortString(tool.function?.name, 128) || !/^[a-zA-Z0-9_-]{1,128}$/.test(tool.function.name)
        || !tool.function.parameters || typeof tool.function.parameters !== 'object') throw new Error('tool');
      return { type: 'function', function: { name: tool.function.name, parameters: tool.function.parameters,
        ...(shortString(tool.function.description, 20000) ? { description: tool.function.description } : {}) } };
    });
    if (['auto', 'none', 'required'].includes(input.tool_choice)) body.tool_choice = input.tool_choice;
    else if (input.tool_choice?.type === 'function' && shortString(input.tool_choice.function?.name, 128)) body.tool_choice = { type: 'function', function: { name: input.tool_choice.function.name } };
  }
  if (input.response_format?.type === 'json_object') body.response_format = { type: 'json_object' };
  else if (input.response_format?.type === 'json_schema' && input.response_format.json_schema && typeof input.response_format.json_schema === 'object') {
    body.response_format = { type: 'json_schema', json_schema: input.response_format.json_schema };
  }
  return body;
}

export async function handleRunRequest({ request, input, visitor, env, fetcher, options, budget, key, model, endpoint, reply, error, positive }) {
  if (input?.task === 'start_run') {
    const id = randomUUID();
    const limit = positive(env.DEMO_VISITOR_REQUESTS, 40);
    let reserved;
    try {
      reserved = options.budget ? await options.budget.issueRun({ id, visitor, visitorRequests: limit, ttl: RUN_TTL })
        : await budget(['EVAL', ISSUE_RUN_SCRIPT, 1, key, id, visitor, limit, RUN_TTL], env, fetcher);
    } catch { return error('budget', 'The shared generation allowance is unavailable.', 503); }
    if (reserved === -2) return error('visitor_quota', VISITOR_QUOTA_MESSAGE, 429);
    if (reserved !== 1) return error('budget', 'The shared generation allowance is unavailable.', 503);
    const exp = Math.floor(Date.now() / 1000) + RUN_TTL;
    return reply({ token: tokenFor({ id, visitor, exp }, env.DEMO_GLM_API_KEY), expiresAt: exp, callLimit: CALL_LIMIT, tokenLimit: TOKEN_LIMIT });
  }
  const claims = claimsFor(input?.runToken, env.DEMO_GLM_API_KEY, visitor);
  if (!claims) return error('run_token', 'Start a new diagram generation to use the shared model.', 401);
  let body;
  try { body = sanitizeRunChat(input, model); } catch { return error('input', 'The model request is invalid or too large.', 400); }
  // Base64 is an encoding, not text tokens. Reserve a conservative image
  // allowance per image plus UTF-8 text bytes and the maximum output budget.
  let imageTokens = 0;
  const messages = body.messages.map(message => {
    if (!Array.isArray(message.content)) return message;
    const content = message.content.map(part => {
      if (part.type !== 'image_url') return part;
      imageTokens += 16384;
      return { ...part, image_url: { ...part.image_url, url: '<image>' } };
    });
    return { ...message, content };
  });
  const reserved = Buffer.byteLength(JSON.stringify({ ...body, messages })) + imageTokens + body.max_tokens + 512;
  const id = randomUUID();
  let reservation;
  try {
    const dailyTokens = positive(env.DEMO_DAILY_TOKENS, 2_000_000);
    const limits = { reserved, id, visitor, runId: claims.id, dailyTokens, visitorTokens: visitorTokenLimit(dailyTokens, env.DEMO_VISITOR_DAILY_TOKENS),
      concurrency: positive(env.DEMO_CONCURRENCY, 4), callLimit: CALL_LIMIT, tokenLimit: TOKEN_LIMIT };
    reservation = options.budget ? await options.budget.reserveRun(limits)
      : await budget(['EVAL', RESERVE_RUN_SCRIPT, 1, key, reserved, limits.dailyTokens, limits.concurrency,
        id, visitor, 0, claims.id, CALL_LIMIT, TOKEN_LIMIT, limits.visitorTokens], env, fetcher);
  } catch { return error('budget', 'The shared model is temporarily unavailable.', 503); }
  if (reservation === -1) return error('busy', 'The shared model is busy. Retry shortly.', 429, { 'Retry-After': '10' });
  if (reservation === -4) return error('visitor_quota', VISITOR_QUOTA_MESSAGE, 429);
  if (reservation === 0) return error('daily_quota', 'The shared demo has reached its daily allowance. Connect your own model to continue.', 429);
  if (reservation === -2) return error('run_quota', 'This diagram has reached its shared model allowance. Simplify the prompt or use your own model.', 429);
  if (reservation === -3) return error('run_token', 'Start a new diagram generation to use the shared model.', 401);
  if (reservation !== 1) return error('budget', 'The shared model is temporarily unavailable.', 503);
  try {
    const response = await fetcher(options.endpoint || endpoint, {
      method: 'POST', headers: { Authorization: `Bearer ${env.DEMO_GLM_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body), redirect: 'error', signal: AbortSignal.any([request.signal, AbortSignal.timeout(120000)]),
    });
    if (!response.ok) return error('provider', 'The shared model could not complete this request.', response.status === 429 ? 429 : 502);
    const text = await response.text();
    if (text.length > 2_000_000) throw new Error('response size');
    const result = JSON.parse(text);
    const choice = result?.choices?.[0];
    if (result.error || !choice || (typeof choice.message?.content !== 'string' && !Array.isArray(choice.message?.tool_calls))) throw new Error('completion');
    return reply({ choices: [{ message: { role: 'assistant', content: choice.message.content ?? null,
      ...(choice.message.tool_calls ? { tool_calls: choice.message.tool_calls } : {}) }, finish_reason: choice.finish_reason }] });
  } catch { return error('provider', 'The shared model could not complete this request.', 502); }
  finally {
    try {
      if (options.budget) await options.budget.release(id);
      else await budget(['ZREM', `${key}:active`, id], env, fetcher);
    } catch { /* Active leases expire independently. */ }
  }
}
