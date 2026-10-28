import { BROWSER_MODE, MODEL_CONFIG_EVENT } from './runtime';

export type HostedModelState = { status: 'loading' | 'available' | 'unavailable'; model: string };
let state: HostedModelState = { status: 'loading', model: 'glm-5.3-flash' };
let pending: Promise<void> | undefined;
const listeners = new Set<() => void>();
export const getHostedModel = () => state;
export const subscribeHostedModel = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };

export function checkHostedModel(): Promise<void> {
  if (!BROWSER_MODE) return Promise.resolve();
  if (pending) return pending;
  pending = (async () => {
    let next: HostedModelState = { status: 'unavailable', model: 'glm-5.3-flash' };
    try {
      const response = await fetch('/api/model', { signal: AbortSignal.timeout(8000), cache: 'no-store', credentials: 'omit' });
      if (response.ok && response.headers.get('content-type')?.includes('application/json')) {
        const data = await response.json();
        if (data.available === true && typeof data.model === 'string') next = { status: 'available', model: data.model };
      }
    } catch { /* Static/self-hosted editions retain the user's own model path. */ }
    state = next;
    listeners.forEach(listener => listener());
    window.dispatchEvent(new Event(MODEL_CONFIG_EVENT));
  })().finally(() => { pending = undefined; });
  return pending;
}
