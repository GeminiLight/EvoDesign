// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3). TS twin of provider_requests.py.
import { readFileSync } from 'node:fs';
import { HumanMessage, SystemMessage } from '@langchain/core/messages';
for (const k of Object.keys(process.env)) if (/^(OPENAI|LLM_|ANTHROPIC|NVIDIA)/.test(k)) delete process.env[k];
const { LLMFactory } = await import('../../src/core/llm_factory.ts');
const [port, configPath] = process.argv.slice(2);
const IMG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
for (const raw of JSON.parse(readFileSync(configPath, 'utf-8')) as Record<string, unknown>[]) {
  const { tag, model, model_provider, temperature, api_key, timeout, max_retries, max_tokens, ...kwargs } = raw;
  const m = await LLMFactory.create(model as string, model_provider as string, (temperature as number) ?? 0, `http://127.0.0.1:${port}/${tag}/v1`,
    (api_key as string) ?? null, (timeout as number) ?? 1200, (max_retries as number) ?? 0, (max_tokens as number) ?? null, kwargs);
  await m.invoke([new SystemMessage('sys 中文'), new HumanMessage({ content: [{ type: 'text', text: 'hi' }, { type: 'image_url', image_url: { url: IMG, detail: 'high' } }] })]);
}
console.log('ok');
