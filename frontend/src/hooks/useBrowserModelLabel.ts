import { useSyncExternalStore } from 'react';
import { loadModelConfig } from '../services/browser/modelConfig';
import { BROWSER_MODE, MODEL_CONFIG_EVENT } from '../services/browser/runtime';
import { useHostedModel } from './useHostedModel';

function subscribe(update: () => void) {
  if (!BROWSER_MODE) return () => {};
  window.addEventListener(MODEL_CONFIG_EVENT, update);
  window.addEventListener('storage', update);
  return () => {
    window.removeEventListener(MODEL_CONFIG_EVENT, update);
    window.removeEventListener('storage', update);
  };
}

export function useBrowserModelLabel(t: (key: string) => string): string {
  useHostedModel();
  const model = useSyncExternalStore(subscribe, () => BROWSER_MODE ? loadModelConfig().model.trim() : '', () => '');
  return BROWSER_MODE ? model || t('browser.yourModel') : t('home.serverModel');
}
