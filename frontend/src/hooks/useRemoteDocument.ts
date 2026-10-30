import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { agentRequest, projectAgentPath, readAgentDocument, type AgentDocument } from '../services/agentApi';
import { remoteDocumentDecision } from '../utils/remoteDocumentPolicy';

type Options = {
  projectId?: string; identity: string | null; versionRef: RefObject<number | null>;
  snapshotRef: RefObject<string | null>; busy: boolean;
  isSaving: () => boolean; isDirty: () => boolean; pause: () => void;
  apply: (document: AgentDocument, discardDraft: boolean) => boolean;
};

export function useRemoteDocument(options: Options) {
  const { projectId, identity } = options;
  const latest = useRef(options);
  latest.current = options;
  const [pending, setPending] = useState<AgentDocument | null>(null);
  const [offline, setOffline] = useState(false);
  const pendingRef = useRef<AgentDocument | null>(null);
  const refreshRef = useRef<() => void>(() => {});
  const epochRef = useRef(0);
  const knownHead = useRef<{ version: number; snapshot: string | null } | null>(null);

  useEffect(() => {
    const epoch = ++epochRef.current;
    pendingRef.current = null;
    knownHead.current = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    let delay = 2000;
    let running = false;
    const current = () => epochRef.current === epoch && latest.current.projectId === projectId && latest.current.identity === identity;
    const clearPending = () => { pendingRef.current = null; setPending(null); };
    async function poll() {
      if (!projectId || !identity || !current() || running || document.hidden) return;
      running = true;
      clearTimeout(timer);
      controller = new AbortController();
      try {
        const head = await agentRequest<{ version: number; snapshot_id: string | null }>(
          `${projectAgentPath(projectId)}/document/head`, { signal: controller.signal });
        if (!current()) return;
        delay = 2000;
        setOffline(false);
        const state = latest.current;
        const known = state.versionRef.current;
        if (known != null && head.version <= known) {
          if (head.version === known) knownHead.current = { version: known, snapshot: head.snapshot_id };
          clearPending();
          setOffline(false);
          return;
        }
        const historical = Boolean(knownHead.current && knownHead.current.version === known
          && knownHead.current.snapshot !== state.snapshotRef.current);
        const decision = remoteDocumentDecision({ incoming: head.version, known,
          saving: state.isSaving(), dirty: state.isDirty(), blocked: state.busy, historical });
        if (decision === 'wait' || decision === 'ignore') return;
        const doc = pendingRef.current?.version === head.version ? pendingRef.current
          : await readAgentDocument(projectId, controller.signal);
        if (!current()) return;
        // The canvas may have changed during the document fetch.
        const now = latest.current;
        const finalDecision = remoteDocumentDecision({ incoming: doc.version, known: now.versionRef.current,
          saving: now.isSaving(), dirty: now.isDirty(), blocked: now.busy,
          historical: Boolean(knownHead.current && knownHead.current.version === now.versionRef.current
            && knownHead.current.snapshot !== now.snapshotRef.current) });
        if (finalDecision === 'ignore') { clearPending(); return; }
        if (finalDecision === 'apply' && now.apply(doc, false)) {
          knownHead.current = { version: doc.version, snapshot: doc.snapshot_id };
          clearPending();
        } else if (finalDecision === 'conflict' || finalDecision === 'history') {
          now.pause();
          pendingRef.current = doc;
          setPending(prev => prev?.version === doc.version ? prev : doc);
        }
        setOffline(false);
        delay = 2000;
      } catch (error) {
        if (current() && !(error instanceof DOMException && error.name === 'AbortError')) {
          setOffline(true);
          delay = Math.min(delay * 2, 30000);
        }
      } finally {
        running = false;
        if (current()) timer = setTimeout(() => { void poll(); }, delay);
      }
    }
    refreshRef.current = () => { if (current()) { clearTimeout(timer); void poll(); } };
    const resume = () => { if (!document.hidden) refreshRef.current(); else clearTimeout(timer); };
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('online', resume);
    void poll();
    return () => {
      epochRef.current = epoch + 1;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('online', resume);
    };
  }, [projectId, identity]);

  const adopt = useCallback(async () => {
    const ctx = latest.current;
    const epoch = epochRef.current;
    if (!ctx.projectId || ctx.busy || ctx.isSaving()) return false;
    const doc = await readAgentDocument(ctx.projectId);
    if (epoch !== epochRef.current || latest.current.projectId !== ctx.projectId || latest.current.identity !== ctx.identity
      || latest.current.busy || latest.current.isSaving() || doc.version < (latest.current.versionRef.current ?? 0)) return false;
    if (pendingRef.current && pendingRef.current.version !== doc.version) {
      pendingRef.current = doc;
      setPending(doc);
      return false;
    }
    if (!latest.current.apply(doc, true)) return false;
    knownHead.current = { version: doc.version, snapshot: doc.snapshot_id };
    pendingRef.current = null;
    setPending(null);
    return true;
  }, []);

  return { pending: pending?.project_id === options.projectId ? pending : null, offline,
    refresh: useCallback(() => refreshRef.current(), []), adopt };
}
