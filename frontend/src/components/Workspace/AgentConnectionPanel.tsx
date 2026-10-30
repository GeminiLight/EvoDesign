import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Check, CheckCircle2, ChevronRight, CircleDot, Clock3, Copy, FolderOpen, History, Layers, Link2, Loader2, Maximize2, Minimize2, MousePointer2, Plus, RefreshCcw, ShieldCheck, Terminal, Unplug, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useLanguage } from '../../i18n/LanguageProvider';
import { agentErrorMessage, agentPreviewUrl, savedDocumentPreviewUrl, agentRequest, projectAgentPath, proposalPath, readAgentDocument,
  type AgentCheckpoint, type AgentConnection, type AgentDocument, type AgentProposal } from '../../services/agentApi';
import { API_BASE_URL } from '../../services/httpClient';
import { BROWSER_MODE } from '../../services/browser/runtime';
import '../../styles/agent-collaboration.css';

type Props = {
  open: boolean; onClose: () => void; projectId?: string; projectTitle?: string; signedIn: boolean; canvas: string;
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
  const [imageReady, setImageReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<'candidates' | 'connections' | 'history'>('candidates');
  const [showAll, setShowAll] = useState(false);
  const [fullSize, setFullSize] = useState(false);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const epoch = useRef(0);
  const selectionRevision = useRef(0);
  const refreshing = useRef<number | null>(null);
  const hasLoaded = useRef(false);
  const available = Boolean(!BROWSER_MODE && signedIn && projectId && canvas === 'excalidraw');
  const prefix = projectId ? projectAgentPath(projectId) : '';
  const refresh = useCallback(async () => {
    if (!available || !projectId || refreshing.current === epoch.current) return;
    const generation = epoch.current;
    const selectionAtStart = selectionRevision.current;
    refreshing.current = generation;
    setLoading(!hasLoaded.current);
    try {
      const [conn, candidates, history] = await Promise.all([
        agentRequest<AgentConnection[]>(`/agent/connections?project_id=${encodeURIComponent(projectId)}`),
        agentRequest<AgentProposal[]>(`${prefix}/agent-proposals`),
        agentRequest<AgentCheckpoint[]>(`${prefix}/agent-history?limit=100`),
      ]);
      if (epoch.current !== generation) return;
      hasLoaded.current = true;
      setConnections(conn); setProposals(candidates); setCheckpoints(history.filter(item => item.is_checkpoint));
      if (selectionAtStart === selectionRevision.current) {
        setSelected(current => current ? candidates.find(item => item.proposal_id === current.proposal_id) ?? current : null);
      }
      setRefreshError(null);
    } catch (reason) { if (epoch.current === generation) setRefreshError(agentErrorMessage(reason, t)); }
    finally { if (refreshing.current === generation) refreshing.current = null; if (epoch.current === generation) setLoading(false); }
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
    selectionRevision.current += 1;
    setBusy(true); setError(null); setNotice(null);
    try { await task(); }
    catch (reason) { if (epoch.current === generation) setError(agentErrorMessage(reason, t)); }
    finally { if (epoch.current === generation) { selectionRevision.current += 1; setBusy(false); void refresh(); } }
  };
  const review = async (candidate: AgentProposal) => {
    const generation = epoch.current;
    selectionRevision.current += 1;
    setSelected(candidate); setImage(null); setImageReady(false); setFullSize(false);
    const next = await agentRequest<AgentProposal>(proposalPath(projectId!, candidate.proposal_id), {}, 50000);
    if (generation !== epoch.current) return;
    setSelected(next);
    if (next.status === 'ready' || next.status === 'committed') {
      const url = await agentPreviewUrl(projectId!, next.proposal_id);
      if (generation === epoch.current) setImage(url); else URL.revokeObjectURL(url);
    }
  };
  const statusLabel = (value: string) => t(`agent.${value === 'checking' ? 'checkingStatus' : value === 'rejected' ? 'rejectStatus' : value === 'approved' ? 'approvedStatus' : value}`);
  const candidateStatus = (candidate: AgentProposal) => {
    if (['queued', 'checking', 'ready'].includes(candidate.status) && candidate.expires_at * 1000 <= Date.now()) return 'expired';
    if (candidate.status === 'ready' && candidate.base_version !== (pending?.version ?? version)) return 'conflicted';
    return candidate.status;
  };
  const command = `evodesign connect --server ${API_BASE_URL}`;
  const guideUrl = `https://github.com/GeminiLight/EvoDesign/blob/main/docs/agent-collaboration${language === 'zh' ? '.zh-CN' : ''}.md`;
  const liveConnections = connections.filter(conn => conn.status === 'active' && conn.expires_at * 1000 > Date.now());
  const toReview = proposals.filter(candidate => ['ready', 'queued', 'checking', 'failed'].includes(candidateStatus(candidate)));
  const visibleProposals = showAll ? proposals : toReview;
  const copyCommand = () => { void act(async () => { await navigator.clipboard.writeText(command); setCopied(true); }); };
  const badge = (status: string) => <span className="agent-status" data-status={status}><span />{statusLabel(status)}</span>;
  const workflow = <div className="agent-workflow" aria-hidden="true">
    <div><span><Terminal size={23} /></span><small>{t('agent.yourAgent')}</small></div><ArrowRight size={19} />
    <div className="agent-workflow-center"><span><Layers size={25} /></span><small>EvoDesign</small></div><ArrowRight size={19} />
    <div><span><MousePointer2 size={23} /></span><small>{t('agent.yourCanvas')}</small></div>
  </div>;
  return <dialog ref={dialog} className="workspace-settings-dialog agent-dialog" aria-labelledby="agent-dialog-title"
    onCancel={onClose} onClose={() => { if (open && !dialog.current?.open) onClose(); }}
    onKeyDown={event => event.stopPropagation()} onKeyUp={event => event.stopPropagation()}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <header className="agent-panel-header">
      <div className="agent-panel-identity"><span className="agent-symbol"><Terminal size={23} aria-hidden="true" /></span>
        <div><span className="agent-eyebrow">EvoDesign · {t('agent.collaboration')}</span><h2 id="agent-dialog-title">{t('agent.title')}</h2></div>
      </div>
      <button className="studio-icon-button" type="button" onClick={onClose} aria-label={t('agent.close')}><X size={19} /></button>
    </header>
    {available && <div className="agent-project-strip"><span title={props.projectTitle}><FolderOpen size={14} aria-hidden="true" />{props.projectTitle}</span><span className="agent-version">v{version ?? '—'}</span><span className="agent-strip-connection"><i data-connected={liveConnections.length > 0} />{liveConnections.length ? t('agent.active') : t('agent.noConnectionShort')}</span></div>}
    {available && <nav className="agent-tabs" aria-label={t('agent.collaboration')}>
      <button type="button" aria-pressed={tab === 'candidates'} onClick={() => setTab('candidates')}><Layers size={16} />{t('agent.proposals')}<span>{toReview.length}</span></button>
      <button type="button" aria-pressed={tab === 'connections'} onClick={() => setTab('connections')}><Link2 size={16} />{t('agent.connections')}<span>{liveConnections.length}</span></button>
      <button type="button" aria-pressed={tab === 'history'} onClick={() => setTab('history')}><History size={16} />{t('agent.checkpoints')}</button>
      <button type="button" className="agent-tab-refresh" disabled={loading || busy} onClick={() => { void refresh(); }} aria-label={t('agent.refresh')} title={t('agent.refresh')}><RefreshCcw size={16} className={loading ? 'animate-spin' : ''} /></button>
    </nav>}
    <div className="agent-panel-body">
      {!available ? <div className="agent-welcome">{workflow}<span className="agent-eyebrow">{t('agent.bringAgent')}</span><h3>{t('agent.intro')}</h3>
        <p>{BROWSER_MODE ? t('agent.browserOnly') : !signedIn ? t('agent.signInHint') : t('agent.chooseProject')}</p>
        <div className="agent-actions">{!BROWSER_MODE && !signedIn && <Link className="agent-button agent-primary" to={`/auth/email?returnTo=${encodeURIComponent(`/workspace${projectId ? `?project=${projectId}` : ''}`)}`}>{t('agent.signIn')}<ArrowRight size={16} /></Link>}
          <a className="agent-button" href={guideUrl} target="_blank" rel="noreferrer">{t('agent.guide')}<ArrowUpRight size={15} /></a></div>
      </div> : <>
        {pending && <SavedVersionConflict key={pending.version} document={pending} busy={busy} blocked={blocked} adopt={adopt} downloadDraft={downloadDraft} />}
        {tab === 'candidates' && <div className={`agent-review-layout${fullSize ? ' is-expanded' : ''}`}>
          <aside className="agent-candidate-sidebar" aria-label={t('agent.proposals')}>
            <div className="agent-list-filter"><button type="button" aria-pressed={!showAll} onClick={() => setShowAll(false)}>{t('agent.needsReview')} <span>{toReview.length}</span></button><button type="button" aria-pressed={showAll} onClick={() => setShowAll(true)}>{t('agent.allCandidates')} <span>{proposals.length}</span></button></div>
            <div className="agent-candidate-list">
              {loading && !proposals.length && <div className="agent-empty-small" role="status"><Loader2 size={22} className="animate-spin" />{t('common.loading')}</div>}
              {!loading && !visibleProposals.length && <div className="agent-empty-small"><CheckCircle2 size={25} /><strong>{t(proposals.length ? 'agent.caughtUp' : 'agent.noProposalsTitle')}</strong><p>{t('agent.noProposals')}</p>{proposals.length > 0 && <button className="agent-button" type="button" onClick={() => setShowAll(true)}>{t('agent.viewPast')}</button>}</div>}
              {visibleProposals.map(candidate => <button key={candidate.proposal_id} className="agent-candidate-card" type="button" aria-label={`${t('agent.preview')} ${candidate.proposal_id.slice(0, 8)}`} aria-pressed={selected?.proposal_id === candidate.proposal_id} disabled={busy} onClick={() => { void act(() => review(candidate)); }}>
                <div>{badge(candidateStatus(candidate))}<ChevronRight size={14} /></div><strong>{t('agent.candidateLabel')} <code>{candidate.proposal_id.slice(0, 8)}</code></strong><small>v{candidate.base_version}<span>·</span>{candidate.changed_ids.length} {t('agent.changedElements')}</small>
              </button>)}
            </div>
            <button type="button" className="agent-sidebar-connect" onClick={() => setTab('connections')}><Plus size={15} />{t('agent.connectAgent')}<ArrowUpRight size={14} /></button>
          </aside>
          <section className="agent-review-main" aria-label={t('agent.preview')}>
            {selected ? <>
              <div className="agent-review-toolbar"><div><span className="agent-eyebrow">{t('agent.visualReview')}</span><h3>{t('agent.candidateLabel')} <code>{selected.proposal_id.slice(0, 8)}</code></h3></div>{badge(candidateStatus(selected))}</div>
              <div className="agent-preview-stage" data-zoomed={fullSize}>
                {image ? <img className="agent-preview" src={image} alt={t('agent.preview')} onLoad={() => setImageReady(true)} onError={() => { setImageReady(false); setError(t('agent.previewUnavailable')); }} /> : <div className="agent-empty-small">{busy || ['queued', 'checking'].includes(selected.status) ? <><Loader2 size={26} className="animate-spin" /><p role="status">{t('agent.checking')}</p></> : <><Layers size={30} /><p>{t(selected.status === 'failed' ? 'agent.remakeFailed' : 'agent.previewUnavailable')}</p></>}</div>}
              </div>
              <div className="agent-preview-caption"><span>{t('agent.baseVersion')} <b>{selected.base_version}</b><span className="agent-caption-dot">·</span>{selected.changed_ids.length} {t('agent.changedElements')}</span>{image && <button type="button" className="agent-text-button" aria-pressed={fullSize} onClick={() => setFullSize(value => !value)}>{fullSize ? <Minimize2 size={14} /> : <Maximize2 size={14} />}{t(fullSize ? 'agent.fitPreview' : 'agent.actualSize')}</button>}</div>
              {selected.status === 'ready' && <details className="agent-check-report"><summary><ShieldCheck size={15} />{t('agent.checksPassed')}<ChevronRight size={13} /></summary><p>{t('agent.notVisuallyReviewed')}</p>{selected.report.message && <p>{selected.report.message}</p>}{selected.report.issues?.map((issue, index) => <p key={index}>{issue.message}</p>)}</details>}
              {dirty && <p className="agent-inline-warning">{t('agent.savedFirst')}</p>}
              {candidateStatus(selected) === 'conflicted' && <p className="agent-inline-warning">{t('agent.errors.version_conflict')}</p>}
              <div className="agent-review-footer"><span className="agent-muted">{candidateStatus(selected) === 'ready' ? t('agent.reviewBeforeApply') : t('agent.savedDesignKept')}</span><div className="agent-actions">
                {!['committed', 'rejected'].includes(selected.status) && <button className="agent-button" type="button" disabled={busy} onClick={() => { void act(async () => { setSelected(await agentRequest<AgentProposal>(`${proposalPath(projectId!, selected.proposal_id)}/reject`, { method: 'POST' })); setNotice(t('agent.rejected')); }); }}>{t('agent.reject')}</button>}
                {candidateStatus(selected) === 'ready' && <button className="agent-button agent-primary" type="button" disabled={busy || dirty || blocked || !imageReady} onClick={() => { void act(async () => { const next = await agentRequest<AgentProposal>(`${proposalPath(projectId!, selected.proposal_id)}/commit`, { method: 'POST' }); setSelected(next); setNotice(t('agent.accepted')); refreshCanvas(); }); }}>{busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}{t('agent.accept')}</button>}
                {['queued', 'checking'].includes(selected.status) && <button className="agent-button" type="button" disabled={busy} onClick={() => { void act(() => review(selected)); }}>{t('agent.refresh')}</button>}
                {selected.status === 'committed' && <button className="agent-button agent-primary" type="button" onClick={onClose}>{t('agent.backToCanvas')}<ArrowRight size={15} /></button>}
              </div></div>
            </> : <div className="agent-review-empty">{workflow}<span className="agent-eyebrow">{t('agent.visualReview')}</span><h3>{t(toReview.length ? 'agent.chooseCandidate' : 'agent.roomForIdeas')}</h3><p>{t(toReview.length ? 'agent.chooseCandidateHint' : 'agent.emptyReviewHint')}</p><button type="button" className="agent-button agent-primary" disabled={busy} onClick={() => { if (toReview.length) void act(() => review(toReview[0])); else if (liveConnections.length) onClose(); else setTab('connections'); }}>{t(toReview.length ? 'agent.preview' : liveConnections.length ? 'agent.backToCanvas' : 'agent.connectAgent')}<ArrowRight size={15} /></button></div>}
          </section>
        </div>}
        {tab === 'connections' && <div className="agent-connection-layout">
          <section className="agent-setup"><span className="agent-eyebrow">{t('agent.bringAgent')}</span><h3>{t('agent.connectAgent')}</h3><p className="agent-muted">{t('agent.setupIntro')}</p>
            <div className="agent-terminal"><div className="agent-terminal-bar"><span><i /><i /><i /></span><small>{t('agent.connectCommand')}</small></div><div className="agent-terminal-command"><code><span>$ </span>{command}</code><button type="button" aria-label={t(copied ? 'agent.copied' : 'agent.copy')} onClick={copyCommand}>{copied ? <Check size={17} /> : <Copy size={17} />}</button></div></div>
            <ol className="agent-setup-steps"><li><span>1</span><div><strong>{t('agent.setupStep1')}</strong><p>{t('agent.setupStep1Hint')}</p></div></li><li><span>2</span><div><strong>{t('agent.setupStep2')}</strong><p>{t('agent.setupStep2Hint')}</p></div></li><li><span>3</span><div><strong>{t('agent.setupStep3')}</strong><p>{t('agent.setupStep3Hint')}</p></div></li></ol>
            <a className="agent-guide" href={guideUrl} target="_blank" rel="noreferrer">{t('agent.guide')}<ArrowUpRight size={14} /></a>
          </section>
          <section className="agent-connected-list"><div className="agent-section-title"><h3>{t('agent.connections')}</h3><span className="agent-count">{liveConnections.length}</span></div>
            {!connections.length && <div className="agent-empty-small"><Link2 size={27} /><strong>{t('agent.noConnectionShort')}</strong><p>{t('agent.noConnections')}</p></div>}
            {connections.map(conn => <article key={conn.connection_id} className="agent-connection-card"><div className="agent-connection-heading"><span className="agent-device-icon"><Terminal size={18} /></span><div><strong>{conn.name}</strong>{badge(conn.expires_at * 1000 < Date.now() && conn.status !== 'revoked' ? 'expired' : conn.status)}</div></div>
              <div className="agent-connection-details"><span><ShieldCheck size={14} />{t(conn.can_commit ? 'agent.canCommit' : 'agent.readOnly')}</span><span><Clock3 size={14} />{t('agent.expires')} {new Date(conn.expires_at * 1000).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span></div>
              {conn.status === 'active' && conn.expires_at * 1000 > Date.now() && <button className="agent-button agent-share-button" type="button" disabled={busy || blocked || Boolean(pending) || selectedIds.length === 0} onClick={() => { void act(async () => { const selection = [...selectedIds]; if (!await save()) throw new Error('Save failed'); const doc = await readAgentDocument(projectId!); await agentRequest(`/agent/connections/${conn.connection_id}/context`, { method: 'PUT', body: JSON.stringify({ version: doc.version, selected_ids: selection, locked_ids: doc.constraints.locked_ids }) }); setNotice(t('agent.shared')); }); }}><MousePointer2 size={15} />{t('agent.shareSelection')} ({selectedIds.length})</button>}
              {conn.status !== 'revoked' && <div className="agent-revoke">{revokeId === conn.connection_id ? <><p>{t('agent.confirmDisconnect')}</p><div className="agent-actions"><button className="agent-button" type="button" disabled={busy} onClick={() => { void act(async () => { await agentRequest(`/agent/connections/${conn.connection_id}`, { method: 'DELETE' }); setRevokeId(null); }); }}>{t('agent.disconnect')}</button><button className="agent-text-button" type="button" onClick={() => setRevokeId(null)}>{t('agent.keepConnection')}</button></div></> : <button className="agent-text-button" type="button" disabled={busy} onClick={() => setRevokeId(conn.connection_id)}><Unplug size={13} />{t('agent.disconnect')}</button>}</div>}
            </article>)}
            {!selectedIds.length && <p className="agent-selection-hint"><MousePointer2 size={15} />{t('agent.selectFirst')}</p>}
          </section>
        </div>}
        {tab === 'history' && <section className="agent-history"><div className="agent-history-intro"><span className="agent-symbol"><History size={23} /></span><div><h3>{t('agent.history')}</h3><p>{t('agent.restoreHint')}</p></div></div>
          {!checkpoints.length && <div className="agent-empty-small"><Clock3 size={28} /><p>{t('agent.noCheckpoints')}</p></div>}
          {checkpoints.map(item => <article key={item.snapshot_id} className="agent-history-row"><span className="agent-history-node"><CircleDot size={17} /></span><div><strong>{t(item.edit_source === 'AGENT' ? 'agent.historyAgent' : item.edit_source === 'RESTORE' ? 'agent.historyRestore' : item.edit_source === 'AI_GEN' ? 'agent.historyGeneration' : 'agent.historyCanvas')}</strong><p>{new Date(item.created_at + (item.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US')}<code>{item.snapshot_id.slice(0, 8)}</code></p></div><button className="agent-button" type="button" disabled={busy || dirty || blocked} onClick={() => { void act(async () => { const doc = await readAgentDocument(projectId!); const candidate = await agentRequest<AgentProposal>(`${prefix}/restore-proposals`, { method: 'POST', body: JSON.stringify({ snapshot_id: item.snapshot_id, base_version: doc.version, operation_id: crypto.randomUUID() }) }); setTab('candidates'); setShowAll(true); await review(candidate); }); }}>{t('agent.restore')}<ArrowRight size={14} /></button></article>)}
        </section>}
      </>}
    </div>
    <footer className="agent-panel-footer">{error || refreshError ? <div className="agent-footer-alert" role="alert">{error || refreshError}<button type="button" className="agent-text-button" onClick={() => { setError(null); void refresh(); }}>{t('agent.retry')}</button></div> : notice ? <div className="agent-footer-notice" role="status"><CheckCircle2 size={15} />{notice}</div> : <span><ShieldCheck size={14} />{t('agent.projectScoped')}</span>}<a className="agent-guide" href={guideUrl} target="_blank" rel="noreferrer">{t('agent.guide')}<ArrowUpRight size={13} /></a></footer>
  </dialog>;
}
