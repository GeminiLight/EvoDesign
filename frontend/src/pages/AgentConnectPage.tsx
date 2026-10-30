import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, Check, Clock3, Layers, Loader2, MousePointer2, Plus, ShieldCheck, Terminal } from 'lucide-react';
import { Header } from '../components/Header';
import { AuthPanel } from '../features/auth/AuthPanel';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { agentErrorMessage, agentRequest, type AgentConnection } from '../services/agentApi';
import { createBlankCanvasProject, fetchRecentDiagrams } from '../services/backendApi';
import { BROWSER_MODE } from '../services/browser/runtime';
import { createId, initialRequest } from '../constants/app';
import '../styles/agent-collaboration.css';

export function AgentConnectPage() {
  const { user, loading: authLoading } = useBackendAuth();
  const { t, language } = useLanguage();
  const location = useLocation();
  const id = new URLSearchParams(location.search).get('id');
  const [connection, setConnection] = useState<AgentConnection | null>(null);
  const [projects, setProjects] = useState<Array<{ id: string; title: string }>>([]);
  const [selected, setSelected] = useState('');
  const [code, setCode] = useState('');
  const [canCommit, setCanCommit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!user || !id || BROWSER_MODE) return;
    let active = true;
    const controller = new AbortController();
    void Promise.all([
      agentRequest<AgentConnection>(`/agent/connections/${encodeURIComponent(id)}`, { signal: controller.signal }),
      fetchRecentDiagrams(user.user_id, { limit: 100 }),
    ]).then(([conn, items]) => {
      if (!active) return;
      const choices = items.filter(item => item.canvas_library === 'excalidraw' && item.project_id)
        .map(item => ({ id: item.project_id!, title: item.summary || t('workspace.untitledProject') }));
      setConnection(conn);
      setProjects(choices);
      setSelected(previous => choices.some(item => item.id === previous) ? previous : choices[0]?.id ?? '');
      setError(null);
    }).catch(reason => { if (active) setError(agentErrorMessage(reason, t)); });
    return () => { active = false; controller.abort(); };
  }, [id, user, retry, t]);

  const createBlank = async () => {
    setBusy(true); setError(null);
    try {
      const project = await createBlankCanvasProject({ ...initialRequest, id: createId('manual') }, t('workspace.untitledProject'));
      if (!project.project_id) throw new Error('Project could not be created');
      const projectId = project.project_id;
      setProjects(items => [{ id: projectId, title: t('workspace.untitledProject') }, ...items]);
      setSelected(projectId);
    } catch (reason) { setError(agentErrorMessage(reason, t)); }
    finally { setBusy(false); }
  };
  const approve = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!id || !selected) return;
    setBusy(true); setError(null);
    try {
      await agentRequest(`/agent/connections/${encodeURIComponent(id)}/approve`, { method: 'POST', body: JSON.stringify({
        user_code: code.trim(), project_id: selected, can_commit: canCommit,
      }) });
      setApproved(true);
    } catch (reason) { setError(agentErrorMessage(reason, t)); }
    finally { setBusy(false); }
  };
  const guideUrl = `https://github.com/GeminiLight/EvoDesign/blob/main/docs/agent-collaboration${language === 'zh' ? '.zh-CN' : ''}.md`;
  const isApproved = approved || ['approved', 'active'].includes(connection?.status ?? '');
  const expired = connection && !isApproved && (connection.status !== 'pending' || connection.expires_at * 1000 <= Date.now());
  return <div className="studio-shell min-h-screen">
    <Header variant="studio" />
    <main id="main-content" className="agent-connect-page">
      <div className="agent-pair-layout">
        <section className="agent-pair-story"><span className="agent-eyebrow">EvoDesign · {t('agent.pairEyebrow')}</span><h1>{t('agent.pairTitle')}</h1><p>{t('agent.pairIntro')}</p>
          <div className="agent-workflow" aria-hidden="true"><div><span><Terminal size={23} /></span><small>{t('agent.pairStepConnect')}</small></div><ArrowRight size={19} /><div className="agent-workflow-center"><span><Layers size={25} /></span><small>{t('agent.pairStepReview')}</small></div><ArrowRight size={19} /><div><span><MousePointer2 size={23} /></span><small>{t('agent.pairStepRefine')}</small></div></div>
          <a className="agent-guide" href={guideUrl} target="_blank" rel="noreferrer">{t('agent.guide')}<ArrowUpRight size={14} /></a>
        </section>
        <section className="agent-pair-card" aria-label={t('agent.approveTitle')}>
          {BROWSER_MODE ? <div className="agent-pair-success"><span><Layers size={26} /></span><h2>{t('agent.approveTitle')}</h2><p>{t('agent.browserOnly')}</p><a className="agent-button agent-primary" href={guideUrl} target="_blank" rel="noreferrer">{t('agent.guide')}<ArrowUpRight size={15} /></a></div>
            : authLoading ? <div className="agent-empty-small" role="status"><Loader2 className="animate-spin" />{t('agent.pairLoading')}</div>
            : !user ? <AuthPanel returnTo={location.pathname + location.search} />
            : isApproved ? <div className="agent-pair-success" role="status"><span><Check size={28} aria-hidden="true" /></span><h2>{t('agent.pairSuccessTitle')}</h2><p>{t('agent.pairSuccessHint')}</p><Link className="agent-button agent-primary" to={`/workspace?project=${encodeURIComponent(connection?.project_id || selected)}`}>{t('nav.workspace')}<ArrowRight size={15} /></Link></div>
            : expired || !id ? <div className="agent-pair-success"><span><Clock3 size={26} /></span><h2>{t('agent.pairUnavailable')}</h2><a className="agent-button" href={guideUrl} target="_blank" rel="noreferrer">{t('agent.guide')}<ArrowUpRight size={15} /></a></div>
            : <><h2>{t('agent.pairFormTitle')}</h2><form onSubmit={event => { void approve(event); }}>
              {connection ? <div className="agent-pair-device"><span className="agent-device-icon"><Terminal size={18} /></span><div><span className="agent-eyebrow">{t('agent.pairAgentLabel')}</span><strong>{connection.name}</strong></div></div> : !error && <p role="status">{t('agent.pairLoading')}</p>}
              {error && <div role="alert" className="agent-notice"><p>{error}</p><button type="button" className="agent-button" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></div>}
              <label className="agent-field">{t('agent.code')}<input className="agent-code-input" aria-describedby="pair-code-hint" autoComplete="off" autoCapitalize="characters" spellCheck={false} required placeholder="A1B2C3D4" minLength={8} maxLength={8} pattern="[a-fA-F0-9]{8}" value={code} onChange={event => setCode(event.target.value.toUpperCase())} disabled={busy} /><small id="pair-code-hint">{t('agent.pairCodeHint')}</small></label>
              <div className="agent-project-choice"><label className="agent-field">{t('agent.project')}<select aria-describedby="pair-project-hint" value={selected} onChange={event => setSelected(event.target.value)} disabled={busy || !projects.length} required>{!projects.length && <option value="">{t('agent.chooseProject')}</option>}{projects.map(project => <option key={project.id} value={project.id}>{project.title}</option>)}</select><small id="pair-project-hint">{t('agent.pairProjectHint')}</small></label><button className="agent-text-button" type="button" disabled={busy} onClick={() => { void createBlank(); }}><Plus size={13} />{t('agent.createProject')}</button></div>
              <fieldset className="agent-permission-field" disabled={busy}><legend>{t('agent.pairPermissionTitle')}</legend>
                <label className="agent-permission-option"><input type="radio" name="agent-permission" value="review" checked={!canCommit} onChange={() => setCanCommit(false)} /><span><strong>{t('agent.pairReviewTitle')}</strong><small>{t('agent.pairReviewHint')}</small></span></label>
                <label className="agent-permission-option"><input type="radio" name="agent-permission" value="submit" checked={canCommit} onChange={() => setCanCommit(true)} /><span><strong>{t('agent.pairDirectTitle')}</strong><small>{t('agent.pairDirectHint')}</small></span></label>
              </fieldset>
              <button type="submit" className="agent-button agent-primary agent-pair-submit" disabled={busy || !selected || !connection || connection.status !== 'pending' || connection.expires_at * 1000 <= Date.now()}>{busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <ShieldCheck size={16} />}{t('agent.approve')}<ArrowRight size={15} /></button>
              <p className="agent-pair-duration"><Clock3 size={13} />{t('agent.pairDuration')}</p>
            </form></>}
        </section>
      </div>
    </main>
  </div>;
}
