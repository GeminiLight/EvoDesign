import { describe, expect, it } from 'vitest';
import { LLMFactory } from '../../src/core/llm_factory.ts';
import { capturingFetch, factoryArgs, loadJson, perform, requestDiff, type CapturedRequest, type HttpCase } from './http_harness.ts';

const reference = loadJson<{ requests: { tag: string; requests: CapturedRequest[] }[] }>('http_parity_py.json');
describe('Python / browser OpenAI HTTP parity', () => {
  for (const test of loadJson<HttpCase[]>('http_cases.json')) {
    it(test.tag, async () => {
      const transport = capturingFetch();
      const args = factoryArgs({ ...test.factory, http_client: transport.fetch });
      const model = await LLMFactory.create(...args);
      await perform(model, test.call);
      const py = reference.requests.find(r => r.tag === test.tag)!;
      expect(transport.captured.length).toBe(py.requests.length);
      for (let i = 0; i < py.requests.length; i++) expect(requestDiff(py.requests[i], transport.captured[i])).toBeNull();
    });
  }
});

import { BaseAgent, _set_clock, _is_retryable_exception, _is_permanent_http_error, _is_provider_quota_exhausted, _status_code_from_exception, DEFAULT_TRANSPORT_ATTEMPTS } from '../../src/core/base_agent.ts';
import { okResponse, type RetryCase, type RetryRecord } from './http_harness.ts';

const pyRetries = loadJson<{ retries: RetryRecord[] }>('http_parity_py.json').retries;
function scenario(name: string, body: Record<string, unknown>, init?: RequestInit): Response | Promise<Response> {
  if (name === 'ok') return okResponse(body);
  if (name === 'timeout') return new Promise((_, reject) => {
    const abort = () => reject(new DOMException('aborted', 'AbortError'));
    if (init?.signal?.aborted) abort(); else init?.signal?.addEventListener('abort', abort, { once: true });
  });
  if (name === 'connect') throw Object.assign(new TypeError('fetch failed'), { cause: { code: 'ECONNREFUSED' } });
  if (name === 'empty_stream') return new Response('data: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
  if (name === 'bad_sse') return new Response('data: {"id":"x","choices":[{"index":0,"delta":{"content":"hi"}}]}\n\ndata: {not json\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
  if (name === 'error_in_stream') return new Response('data: {"error":{"message":"stream_read_error: upstream closed","type":"server_error"}}\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
  if (name === 'null_choices') return Response.json({ id: 'x', object: 'chat.completion', choices: null });
  if (name === 's502_html') return new Response('<html>bad gateway</html>', { status: 502 });
  const status = Number(name.slice(1, 4));
  const messages: Record<string, Record<string, string>> = {
    s429q: { message: 'You exceeded your current quota', type: 'insufficient_quota', code: 'insufficient_quota' },
    s429: { message: 'Rate limit reached', type: 'requests', code: 'rate_limit_exceeded' },
    s503: { message: 'Service unavailable', type: 'server_error' }, s500: { message: 'overloaded' },
    s408: { message: 'request timeout' }, s409: { message: 'conflict' }, s401: { message: 'bad key', code: 'invalid_api_key' },
    s403: { message: 'forbidden' }, s400: { message: 'bad request' }, s404: { message: 'no model' }, s422: { message: 'unprocessable' },
  };
  return Response.json({ error: messages[name] }, { status });
}
describe('Python / browser retry behaviour', () => {
  for (const test of loadJson<RetryCase[]>('retry_cases.json')) it(test.tag, async () => {
    const sleeps: number[] = [];
    _set_clock({ sleep: async seconds => { sleeps.push(seconds); } });
    try {
      const transport = capturingFetch((body, i, init) => scenario(test.sequence[Math.min(i, test.sequence.length - 1)], body, init));
      const model = await LLMFactory.create(...factoryArgs({ model: 'm', model_provider: 'openai', api_key: 'k-test', base_url: 'https://llm.example.test/v1',
        ...test.factory, ...(test.sequence.includes('timeout') ? { timeout: 0.005 } : {}), http_client: transport.fetch }));
      const agent = Object.create(BaseAgent.prototype) as BaseAgent;
      agent.transport_attempts = test.transport_attempts ?? DEFAULT_TRANSPORT_ATTEMPTS;
      agent.call_deadline_seconds = 0;
      let outcome: Record<string, unknown>;
      try {
        const result = await agent._transport_call(() => model.invoke('hi')) as { content: unknown };
        outcome = { ok: true, content: result.content };
      } catch (error) {
        outcome = { ok: false, retryable: _is_retryable_exception(error), permanent: _is_permanent_http_error(error), quota: _is_provider_quota_exhausted(error), status: _status_code_from_exception(error) };
        if (test.sequence.includes('timeout')) expect((error as Error).constructor.name).toBe('OpenAITimeoutError');
        if (test.tag === 'empty_stream_always') expect((error as Error).constructor.name).toBe('ValueError');
      }
      const expected = pyRetries.find(r => r.tag === test.tag)!;
      const { type: _type, ...pyOutcome } = expected.outcome;
      expect(outcome).toEqual(pyOutcome);
      expect(transport.captured.length).toBe(expected.requests);
      expect(sleeps).toEqual(expected.sleeps);
    } finally { _set_clock(null); }
  });
});
