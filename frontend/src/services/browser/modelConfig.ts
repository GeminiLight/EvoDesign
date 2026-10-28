import { getHostedModel } from './hostedModel';
export { checkHostedModel } from './hostedModel';

export interface BrowserModelConfig {
  source?: 'hosted' | 'custom';
  baseUrl: string;
  model: string;
  apiKey: string;
  rememberKey: boolean;
  refine: boolean;
  reasoningEffort?: 'low' | 'medium' | 'high';
}

const SETTINGS_KEY = 'evodesign.browser-model.v1';
const SESSION_KEY = 'evodesign.browser-key.v1';
export const emptyModelConfig: BrowserModelConfig = {
  baseUrl: 'https://api.openai.com/v1', model: '', apiKey: '', rememberKey: false, refine: true,
};

export function completionUrl(baseUrl: string): string {
  const url = new URL(baseUrl.trim());
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) || url.username || url.password || url.search || url.hash) {
    throw new Error('Use an HTTPS API base URL without credentials, query parameters or fragments.');
  }
  url.pathname = url.pathname.replace(/\/+$/, '');
  if (!url.pathname.endsWith('/chat/completions')) url.pathname += '/chat/completions';
  return url.href;
}

export function loadCustomModelConfig(): BrowserModelConfig {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    const session = JSON.parse(sessionStorage.getItem(SESSION_KEY) || '{}');
    const baseUrl = typeof saved.baseUrl === 'string' ? saved.baseUrl : emptyModelConfig.baseUrl;
    return {
      source: 'custom', baseUrl, model: typeof saved.model === 'string' ? saved.model : '',
      apiKey: saved.rememberKey === true && typeof saved.apiKey === 'string' ? saved.apiKey
        : session.baseUrl === baseUrl && typeof session.apiKey === 'string' ? session.apiKey : '',
      rememberKey: saved.rememberKey === true, refine: saved.refine !== false,
      reasoningEffort: ['low', 'medium', 'high'].includes(saved.reasoningEffort) ? saved.reasoningEffort : undefined,
    };
  } catch {
    return { ...emptyModelConfig };
  }
}

export function loadModelConfig(): BrowserModelConfig {
  const custom = loadCustomModelConfig();
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    if (saved.source === 'custom' || (saved.source !== 'hosted' && custom.model)) return custom;
    if (getHostedModel().status === 'available') return {
      ...emptyModelConfig, source: 'hosted', baseUrl: '/api/model', model: getHostedModel().model, refine: saved.refine !== false,
    };
  } catch { /* Storage may be disabled. */ }
  return custom;
}

export function saveModelConfig(config: BrowserModelConfig) {
  if (config.source === 'hosted') {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ ...saved, source: 'hosted', refine: config.refine }));
    return;
  }
  completionUrl(config.baseUrl);
  const value = { ...config, source: 'custom', baseUrl: config.baseUrl.trim(), model: config.model.trim(), apiKey: config.apiKey.trim() };
  if (!value.model) throw new Error('Enter a model identifier.');
  // Persist only with an explicit opt-in. No key enters project snapshots or URLs.
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({ ...value, apiKey: value.rememberKey ? value.apiKey : '' }));
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ baseUrl: value.baseUrl, apiKey: value.rememberKey ? '' : value.apiKey }));
}

export function forgetModelKey() {
  const config = loadCustomModelConfig();
  const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({ ...config, source: saved.source, apiKey: '', rememberKey: false }));
  sessionStorage.removeItem(SESSION_KEY);
}

export function parseModelJson(text: string): unknown {
  const clean = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  try { return JSON.parse(clean); } catch { throw new Error('The model did not return valid diagram JSON. Try again or choose a model with reliable JSON output.'); }
}

type Completion = { message?: { content?: unknown }; finish_reason?: string };

function waitForRetry(seconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const finish = () => { signal.removeEventListener('abort', abort); resolve(); };
    const timer = setTimeout(finish, seconds * 1000);
    const abort = () => { clearTimeout(timer); reject(signal.reason); };
    signal.addEventListener('abort', abort, { once: true });
  });
}

async function requestCompletion(
  config: BrowserModelConfig, system: string, user: string, signal: AbortSignal | undefined,
  maxTokens: number, timeoutMs: number, onWait?: (seconds: number) => void, task: 'diagram' | 'edit' | 'check' = 'diagram',
): Promise<Completion> {
  if (!config.model.trim()) throw new Error('Configure your model in Model settings first.');
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => controller.abort(new Error('The model request timed out.')), timeoutMs);
  try {
    const hosted = config.source === 'hosted';
    const send = () => fetch(hosted ? '/api/model' : completionUrl(config.baseUrl), {
      method: 'POST', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
      headers: { 'Content-Type': 'application/json', ...(!hosted && config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}) },
      body: JSON.stringify(hosted ? { task, prompt: user, maxTokens } : { model: config.model, messages: [{ role: 'system', content: system }, { role: 'user', content: user }], max_tokens: maxTokens, stream: false,
        ...(config.reasoningEffort ? { reasoning_effort: config.reasoningEffort } : {}) }),
      signal: controller.signal,
    });
    let response = await send();
    const wait = Number(response.headers.get('Retry-After'));
    // Retry only an explicit, short provider cooldown, once. Never retry a charge,
    // ambiguous network failure, or a payment response without Retry-After.
    if ((response.status === 429 || response.status === 402) && wait > 0 && wait <= 60) {
      await response.body?.cancel();
      onWait?.(Math.ceil(wait));
      await waitForRetry(wait, controller.signal);
      onWait?.(0);
      response = await send();
    }
    if (!response.ok) {
      // Do not echo upstream bodies: they may include prompts, credentials or HTML.
      const retryAfter = Number(response.headers.get('Retry-After'));
      const hint = hosted ? response.status === 429
        ? 'The shared model is busy or its demo allowance has been reached. Retry later or connect your own model in Model settings.'
        : 'The shared model is temporarily unavailable. Retry later or connect your own model in Model settings.'
        : (response.status === 402 || response.status === 429) && retryAfter > 0 && retryAfter <= 3600
        ? `Provider request limit reached. Retry in ${Math.ceil(retryAfter)} seconds.`
        : response.status === 402 ? 'Check your provider balance or free-tier allowance.'
        : response.status === 401 || response.status === 403 ? 'Check your API key and model access.'
        : response.status === 429 ? 'Provider quota or rate limit reached. Try again later.'
          : response.status === 404 ? 'Check the API base URL and model identifier.' : 'Check your provider settings and try again.';
      throw new Error(`Model request failed (${response.status}). ${hint}`);
    }
    const body = await response.text();
    if (body.length > 2_000_000) throw new Error('The model response is too large. Use a smaller diagram.');
    let data;
    try { data = JSON.parse(body); } catch { throw new Error('The provider returned an invalid response. Check the API URL and try again.'); }
    // Some providers report an error inside a successful HTTP response.
    if (data?.error) throw new Error('The provider could not complete this request. Check its availability, model access and quota.');
    const choice = data?.choices?.[0];
    if (!choice || typeof choice !== 'object') throw new Error('The provider returned no completion. Check the model and Chat Completions API URL.');
    return choice;
  } catch (error) {
    if (controller.signal.aborted) throw new Error(signal?.aborted ? 'Generation cancelled by user.' : 'The model request timed out. Try a smaller diagram.');
    if (error instanceof TypeError) throw new Error(config.source === 'hosted' ? 'Cannot reach the shared model. Retry later or connect your own model in Model settings.' : 'Cannot reach this model from the browser. Check the URL, network and provider CORS support. No request is forwarded through an EvoDesign server.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export async function callBrowserModel(
  config: BrowserModelConfig, system: string, user: string, signal?: AbortSignal, maxTokens = 8192, onWait?: (seconds: number) => void, task: 'diagram' | 'edit' = 'diagram',
): Promise<string> {
  const choice = await requestCompletion(config, system, user, signal, maxTokens, 180_000, onWait, task);
  // Reasoning models may exhaust their output budget before producing any text.
  if (choice.finish_reason === 'length') throw new Error('The model exhausted its output budget. Simplify the diagram or choose a model that needs less reasoning.');
  if (typeof choice.message?.content !== 'string' || !choice.message.content.trim()) throw new Error('The model returned no text. Choose a chat-completions compatible model.');
  return choice.message.content;
}

export async function testBrowserModelConnection(config: BrowserModelConfig, signal?: AbortSignal): Promise<'ready' | 'limited'> {
  const choice = await requestCompletion(config, 'Reply with OK.', 'Connection test.', signal, 256, 60_000, undefined, 'check');
  if (choice.finish_reason === 'length') return 'limited';
  if (typeof choice.message?.content !== 'string' || !choice.message.content.trim()) throw new Error('The model returned no text. Choose a chat-completions compatible model.');
  return 'ready';
}
