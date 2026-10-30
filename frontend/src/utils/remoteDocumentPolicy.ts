export type RemoteDocumentState = {
  incoming: number; known: number | null; saving: boolean; dirty: boolean;
  blocked: boolean; historical: boolean;
};

export function remoteDocumentDecision(state: RemoteDocumentState): 'ignore' | 'wait' | 'conflict' | 'history' | 'apply' {
  if (state.known == null || state.incoming <= state.known) return 'ignore';
  if (state.saving || state.blocked) return 'wait';
  if (state.dirty) return 'conflict';
  if (state.historical) return 'history';
  return 'apply';
}
