import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readLocalStorage, writeLocalStorage } from '../utils/safeLocalStorage';
import { closeWorkspaceDocument, openWorkspaceDocument, parseWorkspaceDocuments,
  type WorkspaceDocument, type WorkspaceDocumentContext } from '../utils/workspaceDocuments';

/** Persist only document identifiers; conversation and viewport stay in memory. */
export function useWorkspaceDocuments(owner: string | null) {
  const storageKey = `evodesign.workspace.tabs:${encodeURIComponent(owner ?? 'guest')}`;
  const initial = useMemo(() => parseWorkspaceDocuments(readLocalStorage(storageKey)), [storageKey]);
  const [state, setState] = useState({ owner, documents: initial });
  const documents = state.owner === owner ? state.documents : initial;
  const contexts = useRef({ owner, values: new Map<string, WorkspaceDocumentContext>() });

  useEffect(() => {
    writeLocalStorage(storageKey, JSON.stringify(documents.filter(document => document.projectId)));
  }, [documents, storageKey]);

  const open = useCallback((document: WorkspaceDocument) => {
    setState(previous => {
      const documents = openWorkspaceDocument(previous.owner === owner ? previous.documents : initial, document);
      return previous.owner === owner && documents === previous.documents ? previous : { owner, documents };
    });
  }, [initial, owner]);
  const close = useCallback((key: string) => {
    setState(previous => ({ owner, documents: closeWorkspaceDocument(previous.owner === owner ? previous.documents : initial, key, '').documents }));
    if (contexts.current.owner === owner) contexts.current.values.delete(key);
  }, [initial, owner]);
  const remember = useCallback((key: string, context: WorkspaceDocumentContext) => {
    if (contexts.current.owner !== owner) contexts.current = { owner, values: new Map() };
    contexts.current.values.set(key, context);
  }, [owner]);
  const recall = useCallback((key: string) => contexts.current.owner === owner ? contexts.current.values.get(key) : undefined, [owner]);

  return { documents, open, close, remember, recall };
}
