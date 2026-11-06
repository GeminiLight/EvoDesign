// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
for (const k of Object.keys(process.env)) if (/^(OPENAI|LLM_|ANTHROPIC)/.test(k)) delete process.env[k];
import { readFileSync } from 'node:fs';
const { LLMFactory } = await import('../../src/core/llm_factory.ts');
const ba = await import('../../src/core/base_agent.ts');
const py = JSON.parse(readFileSync('/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/wp25/provider_errors_py.json', 'utf-8'));
let same = 0;
for (const sc of Object.keys(py)) {
  const m = await LLMFactory.create('m', 'openai', 0, 'http://127.0.0.1:18765/' + sc + '/v1', null, 1);
  let rec: Record<string, unknown>;
  try { const r = await m.invoke('hi'); rec = { ok: true, content: r.content }; }
  catch (e) { rec = { type: (e as Error).constructor.name + '/' + (e as Error).name, retryable: ba._is_retryable_exception(e), permanent: ba._is_permanent_http_error(e), quota: ba._is_provider_quota_exhausted(e), status: ba._status_code_from_exception(e) }; }
  const p = py[sc];
  const eq = p.ok ? rec.ok === true && rec.content === p.content : ['retryable', 'permanent', 'quota', 'status'].every((k) => rec[k] === p[k]);
  if (eq) same++;
  console.log(eq ? 'SAME' : 'DIFF', sc, JSON.stringify(rec), eq ? '' : 'py=' + JSON.stringify(p));
}
console.log(same + '/' + Object.keys(py).length);
