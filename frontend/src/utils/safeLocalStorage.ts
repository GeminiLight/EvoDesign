/**
 * Guarded localStorage access, symmetric with the `canUseSessionStorage()`
 * guards in the draft services.
 *
 * When the browser is set to "block all cookies and site data", merely touching
 * `window.localStorage` throws a SecurityError. Startup-time reads run inside
 * `useState` initializers at the root of the app, so an unguarded throw there
 * takes down the whole render tree and the user gets a blank page.
 */

const canUseLocalStorage = (): boolean => {
  try {
    return typeof window !== 'undefined' && Boolean(window.localStorage);
  } catch {
    return false;
  }
};

export const readLocalStorage = (key: string): string | null => {
  if (!canUseLocalStorage()) return null;

  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
};

export const writeLocalStorage = (key: string, value: string): boolean => {
  if (!canUseLocalStorage()) return false;

  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
};

export const removeLocalStorage = (key: string): boolean => {
  if (!canUseLocalStorage()) return false;

  try {
    window.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
};
