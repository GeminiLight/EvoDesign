/** Static hosting uses browser-owned credentials and local projects. */
export const BROWSER_MODE = import.meta.env.VITE_RUNTIME_MODE === 'browser';
// Off until the China workspace and entry routing pass release checks.
export const REGION_SWITCH = BROWSER_MODE && import.meta.env.VITE_REGION_SWITCH === '1';
export const MODEL_SETTINGS_EVENT = 'evodesign:model-settings';
export const MODEL_CONFIG_EVENT = 'evodesign:model-config-changed';

export function openModelSettings() {
  window.dispatchEvent(new Event(MODEL_SETTINGS_EVENT));
}
