import { AIMessage } from '@langchain/core/messages';
import { expect, it } from 'vitest';
import { sample_and_vote } from '../../src/common/self_consistency.ts';
import { setPlatform } from '../../src/py/platform.ts';
import { platform as browserPlatform } from '../../src/py/platform_browser.ts';

it('keeps each concurrent sample’s transport retries across JSON repair', async () => {
  setPlatform({ createAsyncContext: browserPlatform.createAsyncContext });
  const { BaseAgent, LLMResponseError, _set_clock } = await import('../../src/core/base_agent.ts');
  setPlatform(null);
  _set_clock({ monotonic: () => 0, sleep: async () => {} });
  let releaseFirst!: () => void;
  let releaseSecond!: () => void;
  const first = new Promise<void>(resolve => { releaseFirst = resolve; });
  const second = new Promise<void>(resolve => { releaseSecond = resolve; });
  const attempts = [0, 0, 0];
  let firstCalls = 0;
  let secondCalls = 0;
  let nextSample = 0;
  const agent = Object.create(BaseAgent.prototype);
  Object.assign(agent, {
    _tools: [], jsonalize_output: true, strict_json_output: true,
    json_retry_attempts: 2, exclude_think: true, transport_attempts: 2, call_deadline_seconds: 0,
    _model: {
      async invoke(messages: { content: string }[]) {
        const sample = Number(messages[0].content);
        const attempt = ++attempts[sample];
        if (attempt === 1) {
          if (++firstCalls === attempts.length) releaseFirst();
          await first;
          return new AIMessage('malformed JSON');
        }
        if (attempt === 2) {
          if (++secondCalls === attempts.length) releaseSecond();
          await second;
          throw new LLMResponseError('malformed provider response');
        }
        return new AIMessage(JSON.stringify({ chart_type: sample === 0 ? 'flowchart' : 'architecture' }));
      },
    },
  });

  try {
    const [, winner] = await sample_and_vote(
      () => agent.invoke_with_history([{ role: 'user', content: String(nextSample++) }]),
      {}, attempts.length, 'chart_type', output => [null, output],
    );
    expect(attempts).toEqual([3, 3, 3]);
    expect(winner).toEqual({ chart_type: 'architecture' });
  } finally {
    _set_clock(null);
  }
}, 5000);
