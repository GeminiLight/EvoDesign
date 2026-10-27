export interface BrowserModelConfig {
  baseUrl: string;
  model: string;
  apiKey: string;
  rememberKey: boolean;
  refine: boolean;
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

export function loadModelConfig(): BrowserModelConfig {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    const session = JSON.parse(sessionStorage.getItem(SESSION_KEY) || '{}');
    const baseUrl = typeof saved.baseUrl === 'string' ? saved.baseUrl : emptyModelConfig.baseUrl;
    return {
      baseUrl, model: typeof saved.model === 'string' ? saved.model : '',
      apiKey: saved.rememberKey === true && typeof saved.apiKey === 'string' ? saved.apiKey
        : session.baseUrl === baseUrl && typeof session.apiKey === 'string' ? session.apiKey : '',
      rememberKey: saved.rememberKey === true, refine: saved.refine !== false,
    };
  } catch {
    return { ...emptyModelConfig };
  }
}

export function saveModelConfig(config: BrowserModelConfig) {
  completionUrl(config.baseUrl);
  const value = { ...config, baseUrl: config.baseUrl.trim(), model: config.model.trim(), apiKey: config.apiKey.trim() };
  if (!value.model) throw new Error('Enter a model identifier.');
  // Persist only with an explicit opt-in. No key enters project snapshots or URLs.
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({ ...value, apiKey: value.rememberKey ? value.apiKey : '' }));
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ baseUrl: value.baseUrl, apiKey: value.rememberKey ? '' : value.apiKey }));
}

export function forgetModelKey() {
  const config = loadModelConfig();
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({ ...config, apiKey: '', rememberKey: false }));
  sessionStorage.removeItem(SESSION_KEY);
}

export function parseModelJson(text: string): unknown {
  const clean = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  try { return JSON.parse(clean); } catch { throw new Error('The model did not return valid diagram JSON. Try again or choose a model with reliable JSON output.'); }
}

export async function callBrowserModel(
  config: BrowserModelConfig, system: string, user: string, signal?: AbortSignal, maxTokens = 8192,
): Promise<string> {
  if (!config.model.trim()) throw new Error('Configure your model in Model settings first.');
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => controller.abort(new Error('The model request timed out.')), 180_000);
  try {
    const response = await fetch(completionUrl(config.baseUrl), {
      method: 'POST', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
      headers: { 'Content-Type': 'application/json', ...(config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}) },
      body: JSON.stringify({ model: config.model, messages: [{ role: 'system', content: system }, { role: 'user', content: user }], max_tokens: maxTokens, stream: false }),
      signal: controller.signal,
    });
    if (!response.ok) {
      // Do not echo upstream bodies: they may include prompts, credentials or HTML.
      const hint = response.status === 401 || response.status === 403 ? 'Check your API key and model access.'
        : response.status === 429 ? 'Provider quota or rate limit reached. Try again later.'
          : response.status === 404 ? 'Check the API base URL and model identifier.' : 'Check your provider settings and try again.';
      throw new Error(`Model request failed (${response.status}). ${hint}`);
    }
    const body = await response.text();
    if (body.length > 2_000_000) throw new Error('The model response is too large. Use a smaller diagram.');
    const data = JSON.parse(body);
    const message = data?.choices?.[0]?.message;
    if (typeof message?.content !== 'string' || !message.content.trim()) throw new Error('The model returned no text. Choose a chat-completions compatible model.');
    if (data.choices[0].finish_reason === 'length') throw new Error('The model output was truncated. Simplify the diagram or choose a model with a larger output limit.');
    return message.content;
  } catch (error) {
    if (controller.signal.aborted) throw new Error(signal?.aborted ? 'Generation cancelled by user.' : 'The model request timed out. Try a smaller diagram.');
    if (error instanceof TypeError) throw new Error('Cannot reach this model from the browser. Check the URL, network and provider CORS support. No request is forwarded through an EvoDesign server.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
