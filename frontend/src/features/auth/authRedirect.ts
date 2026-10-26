const AUTH_RETURN_TO_STORAGE_KEY = 'evodiagram_auth_return_to';
const DEFAULT_AUTH_RETURN_TO = '/home';

export const normalizeAuthReturnTo = (value: unknown): string | null => {
  if (typeof value !== 'string') return null;

  const trimmed = value.trim();
  if (!trimmed.startsWith('/') || trimmed.startsWith('//')) return null;
  if (trimmed === '/auth' || trimmed.startsWith('/auth/')) return null;

  return trimmed;
};

export const rememberAuthReturnTo = (value: unknown): string | null => {
  const returnTo = normalizeAuthReturnTo(value);
  if (!returnTo) return null;

  try {
    sessionStorage.setItem(AUTH_RETURN_TO_STORAGE_KEY, returnTo);
  } catch {
    // Session storage may be unavailable in private or restricted contexts.
  }

  return returnTo;
};

export const resolveAuthReturnTo = (
  value?: unknown,
  fallback = DEFAULT_AUTH_RETURN_TO,
): string => {
  const directReturnTo = normalizeAuthReturnTo(value);
  if (directReturnTo) return directReturnTo;

  try {
    return normalizeAuthReturnTo(sessionStorage.getItem(AUTH_RETURN_TO_STORAGE_KEY))
      ?? fallback;
  } catch {
    return fallback;
  }
};

export const consumeAuthReturnTo = (
  value?: unknown,
  fallback = DEFAULT_AUTH_RETURN_TO,
): string => {
  const returnTo = resolveAuthReturnTo(value, fallback);

  try {
    sessionStorage.removeItem(AUTH_RETURN_TO_STORAGE_KEY);
  } catch {
    // Session storage may be unavailable in private or restricted contexts.
  }

  return returnTo;
};
