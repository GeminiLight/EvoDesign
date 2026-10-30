import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Check, Loader2, Terminal } from 'lucide-react';
import { Header } from '../components/Header';
import { AuthPanel } from '../features/auth/AuthPanel';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { agentErrorMessage, agentRequest, type AgentConnection } from '../services/agentApi';
import { createBlankCanvasProject, fetchRecentDiagrams } from '../services/backendApi';
import { BROWSER_MODE } from '../services/browser/runtime';
import '../styles/agent-collaboration.css';

export function AgentConnectPage() {
  const { user, loading: authLoading } = useBackendAuth();
  const { t } = useLanguage();
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
      const project = await createBlankCanvasProject(t('workspace.untitledProject'));
      if (!project.project_id) throw new Error('Project could not be created');
      setProjects(items => [{ id: project.project_id, title: t('workspace.untitledProject') }, ...items]);
      setSelected(project.project_id);
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
  return <div className="studio-shell min-h-screen">
    <Header variant="studio" />
    <main id="main-content" className="agent-connect-page">
      <Terminal size={28} aria-hidden="true" />
      <h1>{t('agent.approveTitle')}</h1>
      {BROWSER_MODE ? <p>{t('agent.browserOnly')}</p> : authLoading ? <Loader2 className="animate-spin" aria-label={t('common.loading')} />
        : !user ? <AuthPanel returnTo={location.pathname + location.search} />
        : approved ? <div role="status"><Check size={24} aria-hidden="true" /><p>{t('agent.approved')}</p>
          <Link className="agent-button" to={`/workspace?project=${encodeURIComponent(selected)}`}>{t('nav.workspace')}</Link></div>
          : <form onSubmit={event => { void approve(event); }}>
            <p>{connection?.name || t('agent.approveHint')}</p>
            <p className="agent-muted">{t('agent.approveHint')}</p>
            {error && <div role="alert" className="agent-notice"><p>{error}</p><button type="button" className="agent-button" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></div>}
            <label className="agent-field">{t('agent.code')}<input autoComplete="off" autoCapitalize="characters" required
              minLength={8} maxLength={8} pattern="[a-fA-F0-9]{8}" value={code} onChange={event => setCode(event.target.value.toUpperCase())} disabled={busy} /></label>
            <label className="agent-field">{t('agent.project')}<select value={selected} onChange={event => setSelected(event.target.value)} disabled={busy || !projects.length} required>
              {!projects.length && <option value="">{t('agent.chooseProject')}</option>}
              {projects.map(project => <option key={project.id} value={project.id}>{project.title}</option>)}
            </select></label>
            <button className="agent-button" type="button" disabled={busy} onClick={() => { void createBlank(); }}>{t('agent.createProject')}</button>
            <label className="agent-checkbox"><input type="checkbox" checked={canCommit} onChange={event => setCanCommit(event.target.checked)} disabled={busy} />{t('agent.permission')}</label>
            <p className="agent-muted">{t('agent.permissionHint')}</p>
            <button type="submit" className="agent-button agent-primary" disabled={busy || !selected || !connection || connection.status !== 'pending' || connection.expires_at * 1000 <= Date.now()}>
              {busy && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}{t('agent.approve')}</button>
          </form>}
    </main>
  </div>;
}
