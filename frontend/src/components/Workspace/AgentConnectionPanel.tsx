import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Copy, Loader2, RefreshCcw, Terminal, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useLanguage } from '../../i18n/LanguageProvider';
import { agentErrorMessage, agentPreviewUrl, savedDocumentPreviewUrl, agentRequest, projectAgentPath, proposalPath, readAgentDocument,
  type AgentCheckpoint, type AgentConnection, type AgentDocument, type AgentProposal } from '../../services/agentApi';
import { API_BASE_URL } from '../../services/httpClient';
import { BROWSER_MODE } from '../../services/browser/runtime';
import '../../styles/agent-collaboration.css';

type Props = {
  open: boolean; onClose: () => void; projectId?: string; signedIn: boolean; canvas: string;
  selectedIds: string[]; dirty: boolean; blocked: boolean; version: number | null;
  save: () => Promise<boolean>; pending: AgentDocument | null;
  adopt: () => Promise<boolean>; downloadDraft: () => void; refreshCanvas: () => void;
};

function SavedVersionConflict({ document, busy, blocked, adopt, downloadDraft }: {
  document: AgentDocument; busy: boolean; blocked: boolean; adopt: () => Promise<boolean>; downloadDraft: () => void;
}) {
  const { t } = useLanguage();
  const [image, setImage] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [confirm, setConfirm] = useState(false);
  const [adopting, setAdopting] = useState(false);
  useEffect(() => {
    let active = true;
    let url: string | null = null;
    const controller = new AbortController();
    void savedDocumentPreviewUrl(document.project_id, document.version, controller.signal).then(value => {
      url = value;
      if (active) setImage(value); else URL.revokeObjectURL(value);
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [document.project_id, document.version, retry]);
  return <section className="agent-notice" aria-label={t('agent.newVersion')}>
    <strong>{t('agent.newVersion')} v{document.version}</strong><p>{t('agent.draftSafe')}</p>
    {image && <img className="agent-preview" src={image} alt={`${t('agent.currentVersion')} ${document.version}`} onLoad={() => setReady(true)} onError={() => setFailed(true)} />}
    {!ready && !failed && <p role="status">{t('agent.checking')}</p>}
    {failed && <p role="alert">{t('agent.requestFailed')} <button className="agent-button" type="button" onClick={() => { setFailed(false); setRetry(value => value + 1); }}>{t('agent.retry')}</button></p>}
    <div className="agent-actions"><button className="agent-button" type="button" onClick={downloadDraft}>{t('agent.downloadDraft')}</button>
      <button className="agent-button" type="button" disabled={busy || blocked || !ready || adopting} onClick={() => setConfirm(true)}>{t('agent.adopt')}</button></div>
    {confirm && <div><p>{t('agent.confirmAdopt')}</p><div className="agent-actions">
      <button className="agent-button agent-primary" type="button" disabled={busy || blocked || adopting} onClick={() => {
        setAdopting(true);
        void adopt().then(() => setConfirm(false)).catch(() => setFailed(true)).finally(() => setAdopting(false));
      }}>{t('agent.confirm')}</button>
      <button className="agent-button" type="button" disabled={adopting} onClick={() => setConfirm(false)}>{t('agent.cancel')}</button>
    </div></div>}
  </section>;
}

export function AgentConnectionPanel(props: Props) {
  const { open, onClose, projectId, signedIn, canvas, selectedIds, dirty, blocked, version, save, pending, adopt, downloadDraft, refreshCanvas } = props;
  const { t, language } = useLanguage();
  const dialog = useRef<HTMLDialogElement>(null);
  const [connections, setConnections] = useState<AgentConnection[]>([]);
  const [proposals, setProposals] = useState<AgentProposal[]>([]);
  const [checkpoints, setCheckpoints] = useState<AgentCheckpoint[]>([]);
  const [selected, setSelected] = useState<AgentProposal | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const epoch = useRef(0);
  const refreshing = useRef(false);
  const available = Boolean(!BROWSER_MODE && signedIn && projectId && canvas === 'excalidraw');
  const prefix = projectId ? projectAgentPath(projectId) : '';
  const refresh = useCallback(async () => {
    if (!available || !projectId || refreshing.current) return;
    refreshing.current = true;
    const generation = epoch.current;
    setLoading(true);
    try {
      const [conn, candidates, history] = await Promise.all([
        agentRequest<AgentConnection[]>(`/agent/connections?project_id=${encodeURIComponent(projectId)}`),
        agentRequest<AgentProposal[]>(`${prefix}/agent-proposals`),
        agentRequest<AgentCheckpoint[]>(`${prefix}/agent-history?limit=100`),
      ]);
      if (epoch.current !== generation) return;
      setConnections(conn); setProposals(candidates); setCheckpoints(history.filter(item => item.is_checkpoint));
    } catch (reason) { if (epoch.current === generation) setError(agentErrorMessage(reason, t)); }
    finally { refreshing.current = false; if (epoch.current === generation) setLoading(false); }
  }, [available, prefix, projectId, t]);
  useEffect(() => {
    if (!open) return;
    const modal = dialog.current;
    modal?.showModal();
    const before = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { modal?.close(); document.body.style.overflow = before; };
  }, [open]);
  useEffect(() => {
    const generation = ++epoch.current;
    if (!open) return;
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 4000);
    return () => { epoch.current = generation + 1; window.clearInterval(timer); };
  }, [open, projectId, refresh]);
  useEffect(() => () => { if (image) URL.revokeObjectURL(image); }, [image]);

  const act = async (task: () => Promise<void>) => {
    const generation = epoch.current;
    setBusy(true); setError(null); setNotice(null);
    try { await task(); }
    catch (reason) { if (epoch.current === generation) setError(agentErrorMessage(reason, t)); }
    finally { if (epoch.current === generation) { setBusy(false); void refresh(); } }
  };
  const review = async (candidate: AgentProposal) => {
    const generation = epoch.current;
    setSelected(candidate); setImage(null);
    const next = await agentRequest<AgentProposal>(proposalPath(projectId!, candidate.proposal_id), {}, 50000);
    if (generation !== epoch.current) return;
    setSelected(next);
    if (next.status === 'ready' || next.status === 'committed') {
      const url = await agentPreviewUrl(projectId!, next.proposal_id);
      if (generation === epoch.current) setImage(url); else URL.revokeObjectURL(url);
    }
  };
  const statusLabel = (value: string) => t(`agent.${value === 'checking' ? 'checkingStatus' : value === 'rejected' ? 'rejectStatus' : value === 'approved' ? 'approvedStatus' : value}`);
  const command = `evodesign connect --server ${API_BASE_URL}`;
  return <dialog ref={dialog} className="workspace-settings-dialog agent-dialog" aria-labelledby="agent-dialog-title"
    onCancel={onClose} onClose={() => { if (open && !dialog.current?.open) onClose(); }}
    onKeyDown={event => event.stopPropagation()} onKeyUp={event => event.stopPropagation()}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <header className="agent-panel-header"><div><h2 id="agent-dialog-title"><Terminal size={18} aria-hidden="true" />{t('agent.title')}</h2><p>{t('agent.intro')}</p></div>
      <button className="studio-icon-button" type="button" onClick={onClose} aria-label={t('agent.close')}><X size={18} /></button></header>
    <div className="agent-panel-body">
      {BROWSER_MODE ? <p>{t('agent.browserOnly')}</p> : !signedIn ? <Link className="agent-button" to="/auth/email?returnTo=%2Fworkspace">{t('agent.signIn')}</Link>
        : !available ? <p>{t('agent.chooseProject')}</p> : <>
          <div className="agent-command"><div><span className="agent-muted">{t('agent.connectCommand')}</span><code>{command}</code></div>
            <button className="studio-icon-button" type="button" aria-label={t(copied ? 'agent.copied' : 'agent.copy')} onClick={() => { void act(async () => { await navigator.clipboard.writeText(command); setCopied(true); }); }}>{copied ? <Check size={17} /> : <Copy size={17} />}</button></div>
          <div className="agent-section-title"><span>{t('agent.currentVersion')} {version ?? '—'}</span><button className="agent-button" type="button" disabled={loading || busy} onClick={() => { void refresh(); }}><RefreshCcw size={14} />{t('agent.refresh')}</button></div>
          {pending && <SavedVersionConflict key={pending.version} document={pending} busy={busy} blocked={blocked}
            adopt={adopt} downloadDraft={downloadDraft} />}
          <section><h3>{t('agent.connections')}</h3>{!connections.length && <p className="agent-muted">{t('agent.noConnections')}</p>}
            {connections.map(conn => <div key={conn.connection_id} className="agent-list-row"><div><strong>{conn.name}</strong><p className="agent-muted">{statusLabel(conn.expires_at * 1000 < Date.now() ? 'expired' : conn.status)} · {t(conn.can_commit ? 'agent.canCommit' : 'agent.readOnly')}</p></div>
              <div className="agent-actions">{conn.status === 'active' && conn.expires_at * 1000 > Date.now() && <button className="agent-button" type="button" disabled={busy || blocked || selectedIds.length === 0} onClick={() => { void act(async () => {
                const selection = [...selectedIds];
                if (!await save()) throw new Error('Save failed');
                const doc = await readAgentDocument(projectId!);
                await agentRequest(`/agent/connections/${conn.connection_id}/context`, { method: 'PUT', body: JSON.stringify({ version: doc.version, selected_ids: selection, locked_ids: doc.constraints.locked_ids }) });
                setNotice(t('agent.shared'));
              }); }}>{t('agent.shareSelection')} ({selectedIds.length})</button>}
                {conn.status !== 'revoked' && <button className="agent-button" type="button" disabled={busy} onClick={() => { void act(async () => { await agentRequest(`/agent/connections/${conn.connection_id}`, { method: 'DELETE' }); }); }}>{t('agent.disconnect')}</button>}</div></div>)}
            {!selectedIds.length && <p className="agent-muted">{t('agent.selectFirst')}</p>}
          </section>
          <section><h3>{t('agent.proposals')}</h3>{loading && !proposals.length && <Loader2 size={18} className="animate-spin" aria-label={t('common.loading')} />}
            {!loading && !proposals.length && <p className="agent-muted">{t('agent.noProposals')}</p>}
            {selected ? <div className="agent-review"><div className="agent-section-title"><button className="agent-button" type="button" disabled={busy} onClick={() => { setSelected(null); setImage(null); }}>{t('agent.back')}</button><span>{statusLabel(selected.status)}</span></div>
              <p className="agent-muted">{t('agent.baseVersion')} {selected.base_version} · {t('agent.changedElements')}: {selected.changed_ids.length}</p>
              {image && <img className="agent-preview" src={image} alt={t('agent.preview')} />}
              {busy && !image && <p role="status">{t('agent.checking')}</p>}
              {selected.status === 'ready' && <p className="agent-muted">{t('agent.notVisuallyReviewed')}</p>}
              {selected.report.message && <p>{selected.report.message}</p>}
              {selected.report.issues?.map((issue, index) => <p key={index} className="agent-muted">{issue.message}</p>)}
              {dirty && <p>{t('agent.savedFirst')}</p>}
              <div className="agent-actions">{selected.status === 'ready' && <button className="agent-button agent-primary" type="button" disabled={busy || dirty || blocked} onClick={() => { void act(async () => {
                const next = await agentRequest<AgentProposal>(`${proposalPath(projectId!, selected.proposal_id)}/commit`, { method: 'POST' });
                setSelected(next); setNotice(t('agent.accepted')); refreshCanvas();
              }); }}>{t('agent.accept')}</button>}
              {['queued', 'checking'].includes(selected.status) && <button className="agent-button" type="button" disabled={busy} onClick={() => { void act(() => review(selected)); }}>{t('agent.refresh')}</button>}
              {selected.status === 'failed' && <p role="alert">{t('agent.remakeFailed')}</p>}
              {!['committed', 'rejected'].includes(selected.status) && <button className="agent-button" type="button" disabled={busy} onClick={() => { void act(async () => {
                setSelected(await agentRequest<AgentProposal>(`${proposalPath(projectId!, selected.proposal_id)}/reject`, { method: 'POST' })); setNotice(t('agent.rejected'));
              }); }}>{t('agent.reject')}</button>}</div>
            </div> : proposals.map(candidate => <div key={candidate.proposal_id} className="agent-list-row"><div><strong>{statusLabel(candidate.status)}</strong><p className="agent-muted">{t('agent.baseVersion')} {candidate.base_version} · {candidate.changed_ids.length} {t('agent.changedElements')}</p></div>
              <button className="agent-button" type="button" disabled={busy} onClick={() => { void act(() => review(candidate)); }}>{t('agent.preview')}</button></div>)}
          </section>
          <details><summary>{t('agent.history')}</summary><p className="agent-muted">{t('agent.restoreHint')}</p>{!checkpoints.length && <p>{t('agent.noCheckpoints')}</p>}
            {checkpoints.map(item => <div key={item.snapshot_id} className="agent-list-row"><div><strong>{item.edit_source}</strong><p className="agent-muted">{new Date(item.created_at + (item.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US')}</p></div>
              <button className="agent-button" type="button" disabled={busy || dirty || blocked} onClick={() => { void act(async () => {
                const doc = await readAgentDocument(projectId!);
                const candidate = await agentRequest<AgentProposal>(`${prefix}/restore-proposals`, { method: 'POST', body: JSON.stringify({ snapshot_id: item.snapshot_id, base_version: doc.version, operation_id: crypto.randomUUID() }) });
                await review(candidate);
              }); }}>{t('agent.restore')}</button></div>)}
          </details>
        </>}
      {error && <p className="agent-notice" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <a className="agent-guide" href="https://github.com/GeminiLight/EvoDesign/blob/main/docs/agent-collaboration.md" target="_blank" rel="noreferrer">{t('agent.guide')}</a>
    </div>
  </dialog>;
}
