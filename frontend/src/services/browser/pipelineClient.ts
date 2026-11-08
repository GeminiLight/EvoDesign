import type { BrowserModelConfig } from './modelConfig';
import { completionUrl } from './modelConfig';
import { isSharedModelQuota, readSharedModelQuota } from './sharedModelQuota';
import { ApiError } from '../httpClient';
import type { PngRenderRequest } from '@evodesign/render-engine';

function quotaError(code: string): ApiError {
  return new ApiError('The shared model allowance has been reached.', 429, undefined, code);
}

/** A fresh worker per generation isolates engine globals and releases memory. */
export async function runPipelineWorker(request: Record<string, unknown>, config: BrowserModelConfig,
  onEvent: (name: string, payload: Record<string, unknown>) => void, signal?: AbortSignal): Promise<Record<string, unknown>> {
  signal?.throwIfAborted();
  const hosted = config.source === 'hosted';
  const baseUrl = hosted ? 'https://shared.invalid/v1' : completionUrl(config.baseUrl).replace(/\/chat\/completions$/, '');
  let runToken: string | undefined;
  if (hosted) {
    // Use the same route as inference so the regional proxy signs both requests.
    const response = await fetch('/api/model', { method: 'POST', credentials: 'omit',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ task: 'start_run' }), signal });
    if (!response.ok) {
      const code = await readSharedModelQuota(response);
      if (code) throw quotaError(code);
      throw new Error('The shared generation allowance is unavailable. Retry later or connect your own model.');
    }
    const body = await response.json();
    if (typeof body.token !== 'string') throw new Error('The shared model returned an invalid generation token.');
    runToken = body.token;
  }
  signal?.throwIfAborted();
  const worker = new Worker(new URL('./pipeline.worker.ts', import.meta.url), { type: 'module' });
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error?: unknown, value?: Record<string, unknown>) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener('abort', abort);
      worker.terminate();
      if (error) reject(error); else resolve(value!);
    };
    const abort = () => finish(new DOMException('Generation cancelled by user.', 'AbortError'));
    signal?.addEventListener('abort', abort, { once: true });
    worker.onerror = (event) => { event.preventDefault(); finish(new Error('The diagram engine could not start. Reload and try again.')); };
    worker.onmessage = async ({ data }) => {
      if (settled) return;
      try {
        if (data.type === 'event') onEvent(data.name, data.payload);
        else if (data.type === 'render') {
          const { pipelineRenderer } = await import('./pipelineRenderer');
          const output = await pipelineRenderer.render({ ...data.request as PngRenderRequest, signal });
          if (!settled) worker.postMessage({ type: 'rendered', id: data.id, output }, [output.png.buffer as ArrayBuffer]);
        } else if (data.type === 'shared-model-quota' && isSharedModelQuota(data.code)) {
          finish(quotaError(data.code));
        } else if (data.type === 'result') {
          if (!data.result) finish(new Error('The diagram pipeline ended without a result.'));
          else finish(undefined, data.result);
        } else if (data.type === 'error') finish(new Error(data.message));
      } catch (error) {
        if (data.type === 'render' && !settled) worker.postMessage({ type: 'rendered', id: data.id, error: error instanceof Error ? error.message : 'PNG export failed.' });
        else finish(error);
      }
    };
    worker.postMessage({ type: 'run', request, config: { ...config, baseUrl }, runToken });
    if (signal?.aborted) abort();
  });
}
