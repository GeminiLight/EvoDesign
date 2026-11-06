// WP30: TS side of the HTTP request / retry parity (Python side:
// tools/wp30/record_http.py). Both sides run the same cases
// (test/models/http_cases.json, retry_cases.json) through their production
// model construction with a captured transport: Python an httpx
// MockTransport, TS a fetch function. Nothing leaves the process.

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { AIMessage, HumanMessage, SystemMessage, ToolMessage, type BaseMessage } from '@langchain/core/messages';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { createAgent } from 'langchain';
import { isTransportHeader } from '../../src/models/openai_chat.ts';

export const HERE = dirname(fileURLToPath(import.meta.url));
export const IMG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
export const TOOL = {
  type: 'function',
  function: {
    name: 'get_weather',
    description: 'Get the weather for a city',
    parameters: { type: 'object', properties: { city: { type: 'string' } }, required: ['city'] },
  },
};

export interface HttpCase { tag: string; call: string; factory: Record<string, unknown> }
export interface RetryCase { tag: string; sequence: string[]; factory?: Record<string, unknown>; transport_attempts?: number }
export interface CapturedRequest { method: string; url: string; headers: Record<string, string>; body: Record<string, unknown> }
export interface RetryRecord { tag: string; outcome: Record<string, unknown>; requests: number; sleeps: number[] }

export const loadJson = <T>(name: string): T => JSON.parse(readFileSync(join(HERE, name), 'utf-8')) as T;

const SSE_OK = 'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{"role":"assistant","content":"ok"},"finish_reason":null}]}\n\n'
  + 'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
  + 'data: [DONE]\n\n';
const JSON_OK = { id: 'x', object: 'chat.completion', created: 1, model: 'm', choices: [{ index: 0, message: { role: 'assistant', content: 'ok' }, finish_reason: 'stop' }] };

export function okResponse(body: Record<string, unknown>): Response {
  if (body.stream) return new Response(SSE_OK, { status: 200, headers: { 'content-type': 'text/event-stream' } });
  return Response.json(JSON_OK);
}

export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

/** A fetch that records each request and answers with *respond*. */
export function capturingFetch(respond: (body: Record<string, unknown>, index: number, init?: RequestInit) => Response | Promise<Response> = okResponse) {
  const captured: CapturedRequest[] = [];
  const fetchImpl: FetchLike = async (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => { headers[key.toLowerCase()] = value; });
    const text = typeof init?.body === 'string' ? init.body : init?.body ? new TextDecoder().decode(init.body as ArrayBuffer) : '{}';
    const body = JSON.parse(text || '{}') as Record<string, unknown>;
    captured.push({ method: init?.method ?? 'GET', url, headers, body });
    return respond(body, captured.length - 1, init);
  };
  return { captured, fetch: fetchImpl };
}

export function messagesFor(call: string): BaseMessage[] {
  switch (call) {
    case 'vision':
      return [new SystemMessage('sys 中文'), new HumanMessage({ content: [{ type: 'text', text: 'hi' }, { type: 'image_url', image_url: { url: IMG, detail: 'high' } }] })];
    case 'text':
    case 'json_mode':
      return [new SystemMessage('Return JSON only.'), new HumanMessage('只要 JSON：{"a": 1}')];
    case 'history':
      return [new SystemMessage('sys'), new HumanMessage('first'), new AIMessage('{"a": 1'), new HumanMessage('Your previous response could not be parsed as JSON.')];
    case 'tools':
    case 'tool_choice_named':
      return [new HumanMessage('Weather in Paris?')];
    case 'tool_roundtrip':
      return [
        new HumanMessage('Weather in Paris?'),
        new AIMessage({ content: '', tool_calls: [{ id: 'call_1', name: 'get_weather', args: { city: 'Paris' }, type: 'tool_call' }] }),
        new ToolMessage({ content: 'sunny', tool_call_id: 'call_1' }),
        new HumanMessage('thanks'),
      ];
    default:
      throw new Error(`unknown call ${call}`);
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function perform(model: BaseChatModel, call: string): Promise<any> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const m = model as any;
  switch (call) {
    case 'vision':
    case 'text':
    case 'history':
      return m.invoke(messagesFor(call));
    case 'tools':
    case 'tool_roundtrip':
      return m.bindTools([TOOL]).invoke(messagesFor(call));
    case 'tool_choice_named':
      return m.bindTools([TOOL], { tool_choice: 'get_weather' }).invoke(messagesFor(call));
    case 'json_mode':
      return m.withConfig({ response_format: { type: 'json_object' } }).invoke(messagesFor(call));
    case 'agent': {
      const agent = createAgent({ model, tools: [], systemPrompt: new SystemMessage('sys 中文') } as unknown as Parameters<typeof createAgent>[0]);
      return agent.invoke({ messages: [{ role: 'user', content: [{ type: 'text', text: 'hi' }, { type: 'image_url', image_url: { url: IMG } }] }] } as never);
    }
    default:
      throw new Error(`unknown call ${call}`);
  }
}

/** Positional ``LLMFactory.create`` from a Python kwargs dict. */
export function factoryArgs(raw: Record<string, unknown>): [string, string, number | null, string | null, string | null, number | null, number, number | null, Record<string, unknown>] {
  const { model, model_provider, temperature, base_url, api_key, timeout, max_retries, max_tokens, ...kwargs } = raw;
  return [
    model as string, model_provider as string,
    temperature === undefined ? 0 : (temperature as number | null),
    (base_url as string | undefined) ?? null, (api_key as string | undefined) ?? null,
    timeout === undefined ? 1200 : (timeout as number | null),
    (max_retries as number | undefined) ?? 0,
    (max_tokens as number | undefined) ?? null,
    kwargs,
  ];
}

// ── comparison ──────────────────────────────────────────────────────────

/** JSON values equal (numbers by value: Python ``1.0`` == JS ``1``); key order ignored. */
export function jsonDiff(a: unknown, b: unknown, path = ''): string | null {
  if (typeof a === 'number' && typeof b === 'number') return a === b ? null : `${path || '<root>'}: ${a} != ${b}`;
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') {
    return a === b ? null : `${path || '<root>'}: ${JSON.stringify(a)?.slice(0, 160)} != ${JSON.stringify(b)?.slice(0, 160)}`;
  }
  if (Array.isArray(a) !== Array.isArray(b)) return `${path}: array/object mismatch`;
  if (Array.isArray(a)) {
    const bb = b as unknown[];
    if (a.length !== bb.length) return `${path}: length ${a.length} != ${bb.length}`;
    for (let i = 0; i < a.length; i++) {
      const d = jsonDiff(a[i], bb[i], `${path}[${i}]`);
      if (d) return d;
    }
    return null;
  }
  const ao = a as Record<string, unknown>; const bo = b as Record<string, unknown>;
  const keys = [...new Set([...Object.keys(ao), ...Object.keys(bo)])].sort();
  for (const key of keys) {
    if (!(key in ao)) return `${path}.${key}: missing in python (ts=${JSON.stringify(bo[key])?.slice(0, 160)})`;
    if (!(key in bo)) return `${path}.${key}: missing in ts (python=${JSON.stringify(ao[key])?.slice(0, 160)})`;
    const d = jsonDiff(ao[key], bo[key], `${path}.${key}`);
    if (d) return d;
  }
  return null;
}

export const comparableHeaders = (headers: Record<string, string>): Record<string, string> =>
  Object.fromEntries(Object.entries(headers).filter(([name]) => !isTransportHeader(name)).sort(([a], [b]) => a.localeCompare(b)));

/** First difference between a Python and a TS request (method, URL, non-transport headers, body). */
export function requestDiff(py: CapturedRequest, ts: CapturedRequest, opts: { ignoreUrl?: boolean; ignoreAuth?: boolean } = {}): string | null {
  if (py.method !== ts.method) return `method: ${py.method} != ${ts.method}`;
  if (!opts.ignoreUrl && py.url !== ts.url) return `url: ${py.url} != ${ts.url}`;
  const ph = comparableHeaders(py.headers); const th = comparableHeaders(ts.headers);
  if (opts.ignoreAuth) { delete ph.authorization; delete th.authorization; }
  const h = jsonDiff(ph, th, 'headers');
  if (h) return h;
  return jsonDiff(py.body, ts.body, 'body');
}
