export interface AuthUser {
  user_id: string;
  email: string;
  username: string;
  avatar_url?: string;
  auth_provider: string;
}

const nonEmptyString = (value: unknown): string | null => (
  typeof value === 'string' && value.trim() ? value : null
);

/**
 * Normalizes an auth user from an API response or the cached profile.
 *
 * The response is typed by the generated contract but never validated, so a
 * user without an email (OAuth providers may omit it) or with null fields must
 * not crash session restore. Returns null only when there is no usable user id.
 */
export function normalizeAuthUser(raw: unknown): AuthUser | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const value = raw as Record<string, unknown>;
  const userId = nonEmptyString(value.user_id);
  if (!userId) return null;

  const email = nonEmptyString(value.email) ?? '';
  const username = nonEmptyString(value.username)
    ?? nonEmptyString(email.split('@')[0])
    ?? userId;

  return {
    user_id: userId,
    email,
    username,
    avatar_url: nonEmptyString(value.avatar_url) ?? undefined,
    auth_provider: nonEmptyString(value.auth_provider) ?? 'email',
  };
}
