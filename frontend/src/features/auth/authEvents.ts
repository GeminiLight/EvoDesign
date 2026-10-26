export const AUTH_INVALIDATED_EVENT = 'evodiagram:auth-invalidated';
export const AUTH_USER_ID_STORAGE_KEY = 'auth_user_id';

export function notifyAuthInvalidated(reason: 'expired' | 'signed-out' = 'expired') {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(AUTH_INVALIDATED_EVENT, { detail: { reason } }));
}
