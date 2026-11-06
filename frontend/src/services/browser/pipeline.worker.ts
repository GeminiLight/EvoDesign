/// <reference lib="webworker" />
import { runBrowserDiagram, type PngRenderRequest, type PngRenderResult } from '@evodesign/render-engine';
import type { BrowserModelConfig } from './modelConfig';

const scope = self as unknown as DedicatedWorkerGlobalScope;
let sequence = 0;
const renders = new Map<number, { resolve: (value: PngRenderResult) => void; reject: (error: Error) => void }>();
let running = false;
scope.onmessage = async ({ data }) => {
  if (data.type === 'rendered') {
    const pending = renders.get(data.id);
    renders.delete(data.id);
    if (data.error) pending?.reject(new Error(data.error)); else pending?.resolve(data.output);
    return;
  }
  if (data.type !== 'run' || running) return;
  running = true;
  const config = data.config as BrowserModelConfig;
  const hosted = config.source === 'hosted';
  try {
    const result = await runBrowserDiagram(data.request, config, {
      settings: { auto_refine_enabled: config.refine },
      engine: { enable_critic: config.supportsVision !== false },
      modelStreaming: !hosted,
      onEvent: (name, payload) => scope.postMessage({ type: 'event', name, payload }),
      renderer: { name: 'browser-main-thread', render: (request: PngRenderRequest) => new Promise<PngRenderResult>((resolve, reject) => {
        const id = sequence++;
        renders.set(id, { resolve, reject });
        scope.postMessage({ type: 'render', id, request });
      }) },
      ...(hosted ? { fetch: async (_input: RequestInfo | URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body));
        // Shared requests are non-streaming; every engine call belongs to one
        // signed run. Custom model credentials never enter this route.
        body.stream = false;
        const response = await fetch('/api/model', { method: 'POST', credentials: 'omit', redirect: 'error', referrerPolicy: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, runToken: data.runToken }), signal: init?.signal });
        return response;
      } } : {}),
    });
    scope.postMessage({ type: 'result', result });
  } catch {
    // Provider bodies may contain keys or private prompts. Never forward them.
    scope.postMessage({ type: 'error', message: 'The model could not complete this diagram. Check model access, quota and browser connectivity, then retry.' });
  }
};
