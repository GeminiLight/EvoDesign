/** An expired account canvas is never an anonymous guest canvas. */
export function workspaceAuthTransition(previous: string | null, current: string | null, expiredOwner: string | null) {
  if (expiredOwner && current === expiredOwner) return 'resume';
  if (!expiredOwner && previous === null && current !== null) return 'guest-upgrade';
  return 'reset';
}

export function canRestoreWorkspaceDraft(owner: string | null, projectId: string | undefined, current: string) {
  if (owner) return owner === current;
  // Legacy drafts without an owner may only restore genuinely local work.
  return !projectId || projectId.startsWith('guest_');
}
