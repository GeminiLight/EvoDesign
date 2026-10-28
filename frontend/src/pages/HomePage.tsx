import { useBrowserModelLabel } from '../hooks/useBrowserModelLabel';
import '../styles/home.css';
import { useHostedModel } from '../hooks/useHostedModel';
import { loadModelConfig } from '../services/browser/modelConfig';
import { BROWSER_MODE, openModelSettings } from '../services/browser/runtime';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, FolderClock, GitBranch, Network, Pencil, Star, Trash2, Waypoints, Workflow } from 'lucide-react';
import { DiagramPromptComposer } from '../components/DiagramPromptComposer';
import { Header } from '../components/Header';
import { RecentProjectPreview } from '../components/Home/RecentProjectPreview';
import { useToast } from '../components/toastContext';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { deleteProject, fetchRecentDiagrams } from '../services/backendApi';
import { loadFavoriteProjectIds, saveFavoriteProjectIds } from '../services/projectPreferences';
import { GUEST_IMPORT_COMPLETED_EVENT } from '../services/guestImportService';
import type { DiagramType } from '../types/api';
import type { RecentDiagram } from '../types/app';
import { pillIdToDiagramType, defaultConfigs, getDiagramTypeLabel } from '../constants/app';

const HOME_PROJECT_FETCH_LIMIT = 100;
const HOME_RECENT_DISPLAY_LIMIT = 8;

const getHomeProjectKey = (project: RecentDiagram) => (
  project.project_id || project.request_id || project.diagram_id
);

const fetchHomeProjects = async (authIdentity: string | null): Promise<RecentDiagram[]> => {
  const pinnedIds = new Set(loadFavoriteProjectIds(authIdentity));
  const missingPinnedIds = new Set(pinnedIds);
  const projects: RecentDiagram[] = [];
  const seenProjectIds = new Set<string>();
  let offset = 0;

  while (true) {
    const page = await fetchRecentDiagrams(authIdentity ?? '', {
      limit: HOME_PROJECT_FETCH_LIMIT,
      offset,
    });

    page.forEach((project) => {
      const projectKey = getHomeProjectKey(project);
      missingPinnedIds.delete(projectKey);
      if (seenProjectIds.has(projectKey)) return;
      seenProjectIds.add(projectKey);
      projects.push(project);
    });

    if (
      pinnedIds.size === 0
      || missingPinnedIds.size === 0
      || page.length < HOME_PROJECT_FETCH_LIMIT
    ) {
      return projects;
    }

    offset += HOME_PROJECT_FETCH_LIMIT;
  }
};

export const HomePage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { showToast } = useToast();
  const { user } = useBackendAuth();
  const { t, language } = useLanguage();
  const zh = language === 'zh';
  const hosted = useHostedModel();
  const modelLabel = useBrowserModelLabel(t);
  const isSharedModel = BROWSER_MODE && loadModelConfig().source === 'hosted';
  const authIdentity = user?.user_id ?? null;
  const activeAuthIdentityRef = useRef<string | null>(authIdentity);
  const previousAuthIdentityRef = useRef<string | null | undefined>(undefined);
  const pinnedAuthIdentityRef = useRef<string | null>(authIdentity);
  const skipNextPinnedSaveRef = useRef(false);
  const loadRequestRef = useRef(0);
  const lastAutoLoadAuthIdentityRef = useRef<string | null | undefined>(undefined);
  const [prompt, setPrompt] = useState('');
  const [promptFocusRequest, setPromptFocusRequest] = useState(0);
  const [recentProjects, setRecentProjects] = useState<RecentDiagram[]>([]);
  const [loadStatus, setLoadStatus] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedPillId, setSelectedPillId] = useState('adaptive');
  const [modelIndex, setModelIndex] = useState(0);
  const [canvasIndex, setCanvasIndex] = useState(0);
  const [activeHomeTab, setActiveHomeTab] = useState<'recent' | 'pinned'>('recent');
  const [pinnedProjectIds, setPinnedProjectIds] = useState<string[]>(() => loadFavoriteProjectIds(authIdentity));
  const [projectPendingDelete, setProjectPendingDelete] = useState<RecentDiagram | null>(null);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  activeAuthIdentityRef.current = authIdentity;

  // Pre-fill prompt from landing page navigation state
  useEffect(() => {
    const initialPrompt = location.state?.initialPrompt;
    if (typeof initialPrompt === 'string' && initialPrompt.trim()) {
      setPrompt(initialPrompt);
      // Clear navigation state to avoid re-filling on re-render
      window.history.replaceState({}, document.title);
    }
  }, [location.state]);

  useEffect(() => {
    if (pinnedAuthIdentityRef.current === authIdentity) return;
    skipNextPinnedSaveRef.current = true;
    setPinnedProjectIds(loadFavoriteProjectIds(authIdentity));
    pinnedAuthIdentityRef.current = authIdentity;
  }, [authIdentity]);

  useEffect(() => {
    if (pinnedAuthIdentityRef.current !== authIdentity) return;
    if (skipNextPinnedSaveRef.current) {
      skipNextPinnedSaveRef.current = false;
      return;
    }
    saveFavoriteProjectIds(authIdentity, pinnedProjectIds);
  }, [authIdentity, pinnedProjectIds]);

  useEffect(() => {
    const previousAuthIdentity = previousAuthIdentityRef.current;
    if (previousAuthIdentity !== undefined && previousAuthIdentity !== authIdentity) {
      loadRequestRef.current += 1;
      setRecentProjects([]);
      setLoadError(null);
      setLoadStatus('loading');
      setActiveHomeTab('recent');
      setProjectPendingDelete(null);
      setDeletingProjectId(null);
    }
    previousAuthIdentityRef.current = authIdentity;
  }, [authIdentity]);

  const loadRecent = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    const requestAuthIdentity = activeAuthIdentityRef.current;
    const isCurrentRequest = () => (
      loadRequestRef.current === requestId
      && activeAuthIdentityRef.current === requestAuthIdentity
    );

    setLoadStatus('loading');
    setLoadError(null);
    try {
      const data = await fetchHomeProjects(requestAuthIdentity);
      if (!isCurrentRequest()) return;
      setRecentProjects(data);
      setLoadStatus('ready');
      setProjectPendingDelete((pendingProject) => (
        pendingProject && data.some((item) => getHomeProjectKey(item) === getHomeProjectKey(pendingProject))
          ? pendingProject
          : null
      ));
    } catch (error) {
      if (!isCurrentRequest()) return;
      console.warn('Recent projects are unavailable:', error);
      setLoadError(t('home.loadFailed'));
      setLoadStatus('failed');
    }
  }, [t]);

  useEffect(() => {
    if (lastAutoLoadAuthIdentityRef.current === authIdentity) return;
    lastAutoLoadAuthIdentityRef.current = authIdentity;
    void loadRecent();
  }, [authIdentity, loadRecent]);

  useEffect(() => {
    const handleGuestImportCompleted = () => {
      void loadRecent();
    };

    window.addEventListener(GUEST_IMPORT_COMPLETED_EVENT, handleGuestImportCompleted);
    return () => {
      window.removeEventListener(GUEST_IMPORT_COMPLETED_EVENT, handleGuestImportCompleted);
    };
  }, [loadRecent]);

  const handlePillClick = (pillId: string, prefix: string) => {
    setSelectedPillId(pillId);
    if (!prompt.trim()) {
      setPrompt(prefix + ' ');
    }
  };

  const enhancePrompt = () => {
    const value = prompt.trim();
    if (!value) return;

    const enhanced = [
      value,
      t('home.enhancePromptInstruction'),
    ].join('\n\n');

    setPrompt(enhanced);
  };

  const handleStartCreation = () => {
    const promptText = prompt.trim();
    if (!promptText) return;

    const canvasLibrary = canvasOptions[canvasIndex].id;
    const llmConfigId = modelOptions[modelIndex].id;

    // Navigate to workspace for a review step before generation starts.
    navigate('/workspace', {
      state: {
        initialPrompt: promptText,
        initialDiagramType: selectedDiagramType,
        initialLlmConfigId: llmConfigId,
        initialCanvasMode: canvasLibrary,
        initialSource: 'home',
        preflightGeneration: true,
        preflightKind: 'startup',
      },
    });
  };

  const pills = [
    { id: 'adaptive', label: t('home.pillAdaptiveLabel'), prefix: t('home.pillAdaptivePrefix'), icon: '✨' },
    { id: 'flow', label: t('home.pillFlowLabel'), prefix: t('home.pillFlowPrefix'), icon: '🔄' },
    { id: 'architecture', label: t('home.pillArchitectureLabel'), prefix: t('home.pillArchitecturePrefix'), icon: '🏗️' },
    { id: 'sequence', label: t('home.pillSequenceLabel'), prefix: t('home.pillSequencePrefix'), icon: '⏱️' },
    { id: 'mindmap', label: t('home.pillMindMapLabel'), prefix: t('home.pillMindMapPrefix'), icon: '🧠' },
  ];

  const morePills = [
    { id: 'entity', label: t('home.pillEntityLabel'), prefix: t('home.pillEntityPrefix'), icon: '🗄️' },
    { id: 'state', label: t('home.pillStateLabel'), prefix: t('home.pillStatePrefix'), icon: '🚦' },
    { id: 'gantt', label: t('home.pillGanttLabel'), prefix: t('home.pillGanttPrefix'), icon: '📊' },
    { id: 'class', label: t('home.pillClassLabel'), prefix: t('home.pillClassPrefix'), icon: '📦' },
  ];


  const modelOptions = defaultConfigs.map((c) => ({ id: c.id, label: modelLabel }));

  const canvasOptions: Array<{ id: 'tldraw' | 'excalidraw'; label: string }> = [
    { id: 'excalidraw', label: t('home.canvasExcalidraw') },
    ...(!BROWSER_MODE ? [{ id: 'tldraw' as const, label: t('home.canvasTldraw') }] : []),
  ];

  const selectedDiagramType: DiagramType = pillIdToDiagramType[selectedPillId] ?? 'automated';
  const getProjectKey = getHomeProjectKey;
  const getProjectTitle = (project: RecentDiagram) => project.summary || project.prompt || t('home.untitledDiagram');
  const isInitialLoading = loadStatus === 'loading' && recentProjects.length === 0;
  const isRefreshingProjects = loadStatus === 'loading' && recentProjects.length > 0;
  const isLoadFailedWithoutData = loadStatus === 'failed' && recentProjects.length === 0;
  const isEmptyWorkspace = loadStatus === 'ready' && recentProjects.length === 0;

  const visibleProjects = activeHomeTab === 'pinned'
    ? recentProjects.filter((project) => pinnedProjectIds.includes(getProjectKey(project)))
    : recentProjects.slice(0, HOME_RECENT_DISPLAY_LIMIT);
  const hiddenRecentCount = activeHomeTab === 'recent'
    ? Math.max(recentProjects.length - visibleProjects.length, 0)
    : 0;
  const recentContinuationText = t('home.recentContinuation')
    .replace('{shown}', String(visibleProjects.length))
    .replace('{total}', String(recentProjects.length));
  const recentContinuationHint = t('home.recentContinuationHint')
    .replace('{count}', String(hiddenRecentCount));

  const starterTemplates = [
    { label: t('home.starterArchitecture'), prompt: t('home.sampleMicroservice'), pillId: 'architecture', Icon: Network, accent: 'text-cyan-700 dark:text-cyan-300' },
    { label: t('home.starterSequence'), prompt: t('landing.exampleSequence'), pillId: 'sequence', Icon: Workflow, accent: 'text-indigo-600 dark:text-indigo-300' },
    { label: t('home.starterFlow'), prompt: t('home.sampleTraining'), pillId: 'flow', Icon: GitBranch, accent: 'text-violet-600 dark:text-violet-300' },
    { label: t('home.starterAgents'), prompt: t('home.sampleBrowser'), pillId: 'mindmap', Icon: Waypoints, accent: 'text-teal-700 dark:text-teal-300' },
  ];

  const handleStarterTemplate = (template: (typeof starterTemplates)[number]) => {
    setSelectedPillId(template.pillId);
    setPrompt(template.prompt);
    setPromptFocusRequest(value => value + 1);
  };

  const handleOpenProject = (project: RecentDiagram) => {
    navigate('/workspace', { state: { pendingLoadProject: project } });
  };

  const handleViewAllProjects = () => {
    navigate(activeHomeTab === 'pinned' ? '/projects?scope=favorites' : '/projects');
  };

  const handleTogglePin = (project: RecentDiagram) => {
    const projectKey = getProjectKey(project);
    const isPinned = pinnedProjectIds.includes(projectKey);
    setPinnedProjectIds((prev) => (
      prev.includes(projectKey)
        ? prev.filter((id) => id !== projectKey)
        : [...prev, projectKey]
    ));
    showToast(
      isPinned ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite'),
      'success',
    );
  };


  const handleDeleteProject = async (project: RecentDiagram) => {
    const projectKey = getProjectKey(project);
    const requestAuthIdentity = activeAuthIdentityRef.current;
    const isCurrentIdentity = () => activeAuthIdentityRef.current === requestAuthIdentity;
    setDeletingProjectId(projectKey);

    try {
      await deleteProject(projectKey);
      if (!isCurrentIdentity()) return;
      setRecentProjects((prev) => prev.filter((item) => getProjectKey(item) !== projectKey));
      setPinnedProjectIds((prev) => prev.filter((id) => id !== projectKey));
      setProjectPendingDelete(null);
      showToast(t('home.deleteSuccess'), 'success');
    } catch (error) {
      if (!isCurrentIdentity()) return;
      console.warn('Project delete failed:', error);
      showToast(t('home.deleteFailed'), 'error');
    } finally {
      if (isCurrentIdentity()) {
        setDeletingProjectId(null);
      }
    }
  };

  return (
    <div className="studio-home min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      <Header />

      <main id="main-content" className="flex-1 flex flex-col items-center px-5 py-8 sm:px-8 sm:py-12 max-w-6xl mx-auto w-full">
        {/* Hero Section - AI Creation Launcher */}
        <div className="home-intro w-full max-w-4xl flex flex-col items-start text-left mb-8 mt-1 sm:mt-5">
          <p className="home-eyebrow mb-5 text-[11px] font-semibold tracking-[0.2em] text-indigo-600 dark:text-indigo-300"><span aria-hidden="true" />EVODESIGN STUDIO</p>
          <h1 className="home-headline mb-4 max-w-3xl font-display text-[2.25rem] font-semibold leading-[1.14] tracking-[-0.04em] text-slate-900 dark:text-slate-100 sm:text-5xl">
            {t('home.title')}
          </h1>
          <p className="mb-7 max-w-xl text-sm leading-7 text-slate-500 dark:text-slate-400 sm:mb-8 sm:text-base">
            {t('home.subtitle')}
          </p>

          <div className="w-full relative group">
            <DiagramPromptComposer
              prompt={prompt}
              promptFocusRequest={promptFocusRequest}
              onPromptChange={setPrompt}
              onGenerate={handleStartCreation}
              onEnhance={enhancePrompt}
              onSelectPill={(pill) => handlePillClick(pill.id, pill.prefix)}
              selectedPillId={selectedPillId}
              pills={pills}
              morePills={morePills}
              modelOptions={modelOptions}
              modelIndex={modelIndex}
              onModelChange={setModelIndex}
              canvasOptions={canvasOptions}
              canvasIndex={canvasIndex}
              onCanvasChange={setCanvasIndex}
              attachTitle={t('home.attachComingSoonTitle')}
              enhanceTitle={t('home.enhancePrompt')}
              generateTitle={t('home.reviewSetup')}
              actionLabel={t('home.reviewSetup')}
              variant="home"
              leadingContent={BROWSER_MODE ? <button type="button" onClick={openModelSettings} className="home-model-button" aria-label={`${t('browser.modelSettings')}: ${modelLabel}`}>
                <span className={`home-model-dot ${isSharedModel ? 'is-ready' : ''}`} aria-hidden="true" />
                <span className="truncate">{hosted.status === 'loading' && !loadModelConfig().model ? (zh ? '正在连接模型…' : 'Connecting…') : modelLabel}</span>
                <span className="home-model-caption">{isSharedModel ? (zh ? '默认体验' : 'Shared demo') : (zh ? '模型设置' : 'Settings')}</span>
              </button> : <span className="pl-2 text-xs text-slate-500">{modelLabel}</span>}
              moreLabel={t('home.pillMoreLabel')}
              isGenerating={false}
              progress={null}
              t={t}
              disableGenerate={!prompt.trim()}
            />

          </div>

          <section className="home-starters mt-6 w-full text-left" aria-labelledby="home-starter-templates-title">
            <div className="mb-2 flex items-baseline gap-4 px-1">
              <h2 id="home-starter-templates-title" className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t('home.starterTemplatesTitle')}
              </h2>
            </div>
            <div className="flex flex-wrap gap-x-2 gap-y-1">
              {starterTemplates.map(({ Icon, ...template }) => (
                <button
                  key={template.pillId}
                  type="button"
                  title={template.prompt}
                  aria-label={`${t('home.useAsDraft')}: ${template.label}`}
                  onClick={() => handleStarterTemplate({ ...template, Icon })}
                  className="group flex min-h-10 min-w-0 items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors duration-200 hover:bg-indigo-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 motion-reduce:transition-none dark:hover:bg-indigo-400/[0.08]"
                >
                  <Icon className={`h-4 w-4 shrink-0 ${template.accent}`} strokeWidth={1.6} aria-hidden="true" />
                  <span className="flex-1 text-[13px] font-medium leading-5 text-slate-600 group-hover:text-slate-900 dark:text-slate-300 dark:group-hover:text-white">{template.label}</span>
                  <ArrowUpRight className="hidden h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform duration-200 min-[380px]:block motion-safe:group-hover:-translate-y-0.5 motion-safe:group-hover:translate-x-0.5 motion-reduce:transition-none dark:text-slate-500" aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        </div>

        {/* Recent Projects Grid */}
        <section className="home-projects w-full max-w-4xl border-t border-slate-200/70 pt-5 dark:border-white/[0.07]" aria-label={t('home.recentProjects')}>
          {!isEmptyWorkspace && <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{t('home.recentProjects')}</h2>
            {recentProjects.length > 0 && <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex items-center gap-1" role="group" aria-label={t('home.recentProjects')}>
                <button
                  type="button"
                  onClick={() => setActiveHomeTab('recent')}
                  aria-pressed={activeHomeTab === 'recent'}
                  className={`min-h-11 rounded-md px-3 py-1.5 text-sm font-semibold transition ${
                    activeHomeTab === 'recent'
                      ? 'bg-white text-brand-700 shadow-sm dark:bg-slate-800 dark:text-brand-300'
                      : 'text-slate-500 hover:bg-white/50 cursor-pointer dark:text-slate-400 dark:hover:bg-slate-800/50'
                  }`}
                >
                  {t('home.recentTab')}
                </button>
                <button
                  type="button"
                  onClick={() => setActiveHomeTab('pinned')}
                  aria-pressed={activeHomeTab === 'pinned'}
                  className={`min-h-11 rounded-md px-3 py-1.5 text-sm font-medium transition ${
                    activeHomeTab === 'pinned'
                      ? 'bg-white text-brand-700 shadow-sm dark:bg-slate-800 dark:text-brand-300'
                      : 'text-slate-500 hover:bg-white/50 cursor-pointer dark:text-slate-400 dark:hover:bg-slate-800/50'
                  }`}
                >
                  {t('home.pinnedTab')}
                </button>
              </div>
              <button
                type="button"
                onClick={handleViewAllProjects}
                className="inline-flex min-h-11 items-center rounded-lg px-2 text-sm font-medium text-brand-700 hover:text-brand-800 dark:text-brand-400 dark:hover:text-brand-300"
              >
                {t('home.viewAllProjects')} →
              </button>
            </div>}
          </div>}

          {loadError && recentProjects.length > 0 && (
            <div className="mb-6 rounded-2xl border border-red-200/80 bg-red-50/80 px-4 py-3 text-sm text-red-700 backdrop-blur dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div role="alert">
                  <p className="font-medium">{loadError}</p>
                  <p className="mt-1 text-xs text-red-600/80 dark:text-red-200/80">{t('home.loadFailedHint')}</p>
                </div>
                <button
                  type="button"
                  onClick={() => { void loadRecent(); }}
                  className="inline-flex min-h-11 items-center justify-center rounded-lg border border-red-200 bg-white/70 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-white dark:border-red-500/30 dark:bg-slate-900/70 dark:text-red-200 dark:hover:bg-slate-900"
                >
                  {t('common.retry')}
                </button>
              </div>
            </div>
          )}

          {isRefreshingProjects && (
            <div role="status" aria-live="polite" className="mb-4 rounded-xl border border-brand-200/70 bg-brand-50/65 px-4 py-2 text-sm font-medium text-brand-700 backdrop-blur dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200">
              {t('home.refreshingProjects')}
            </div>
          )}

          {isInitialLoading ? (
            <div role="status" aria-label={t('common.loading')} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {[1, 2].map((i) => (
                <div key={i} className="h-20 motion-safe:animate-pulse rounded-xl bg-slate-100 dark:bg-slate-900" />
              ))}
            </div>
          ) : visibleProjects.length > 0 ? (
            <>
              <div className="grid grid-cols-1 gap-x-7 sm:grid-cols-2">
                {visibleProjects.map((project) => {
                  const projectKey = getProjectKey(project);
                  const isPinned = pinnedProjectIds.includes(projectKey);

                  return (
                    <article key={projectKey} className="home-project-row group">
                      <button type="button" onClick={() => handleOpenProject(project)} className="home-project-open" aria-label={getProjectTitle(project)}>
                        <span className="home-project-thumb"><RecentProjectPreview project={project} title={getProjectTitle(project)} unavailableLabel={t('home.previewUnavailable')} /></span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-slate-800 dark:text-slate-200">{getProjectTitle(project)}</span>
                          <span className="mt-1.5 block truncate text-[11px] text-slate-500 dark:text-slate-400">{getDiagramTypeLabel(project.diagram_type, t)} · {new Date(project.updated_at || project.created_at).toLocaleDateString(language === 'zh' ? 'zh-CN' : 'en-US')}</span>
                        </span>
                      </button>
                      <div className="flex shrink-0 items-center">
                        <button type="button" className="home-project-action" title={t('home.actionEdit')} aria-label={`${t('home.actionEdit')}: ${getProjectTitle(project)}`} onClick={() => handleOpenProject(project)}><Pencil size={14} /></button>
                        <button type="button" className={`home-project-action ${isPinned ? 'text-violet-600 dark:text-violet-300' : ''}`} title={isPinned ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')} aria-label={isPinned ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')} aria-pressed={isPinned} onClick={() => handleTogglePin(project)}><Star size={14} className={isPinned ? 'fill-current' : ''} /></button>
                        <button type="button" className="home-project-action hover:text-rose-600 dark:hover:text-rose-300" title={t('home.actionDelete')} aria-label={`${t('home.actionDelete')}: ${getProjectTitle(project)}`} onClick={() => setProjectPendingDelete(project)}><Trash2 size={14} /></button>
                      </div>
                    </article>
                  );
                })}
              </div>

              {hiddenRecentCount > 0 && (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <span title={recentContinuationHint}>{recentContinuationText}</span>
                  <button type="button" onClick={handleViewAllProjects} className="inline-flex min-h-10 items-center gap-2 font-medium text-indigo-600 dark:text-indigo-300">{t('home.viewAllProjects')}<ArrowRight size={14} /></button>
                </div>
              )}
            </>
          ) : isLoadFailedWithoutData ? (
            <div role="alert" className="rounded-2xl border border-red-200/80 bg-red-50/80 p-6 text-center backdrop-blur-xl dark:border-red-500/30 dark:bg-red-500/10">
              <h3 className="text-lg font-semibold text-red-800 dark:text-red-200">{loadError}</h3>
              <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-red-700/80 dark:text-red-200/80">
                {t('home.loadFailedHint')}
              </p>
              <button
                type="button"
                onClick={() => { void loadRecent(); }}
                className="mt-5 inline-flex min-h-11 items-center justify-center rounded-lg border border-red-200 bg-white/75 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-white dark:border-red-500/30 dark:bg-slate-900/70 dark:text-red-200 dark:hover:bg-slate-900"
              >
                {t('common.retry')}
              </button>
            </div>
          ) : activeHomeTab === 'pinned' && recentProjects.length > 0 ? (
            <div className="flex items-start gap-3 py-4 text-sm text-slate-500 dark:text-slate-400">
              <Star className="mt-0.5 h-5 w-5 shrink-0 text-violet-400" aria-hidden="true" />
              <div><p className="font-medium text-slate-700 dark:text-slate-300">{t('home.pinnedEmptyTitle')}</p>
                <p className="mt-1">{t('home.pinnedEmptyHint')}</p></div>
            </div>
          ) : (
            <div className="flex items-center justify-center gap-2.5 px-2 py-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
              <FolderClock className="h-[18px] w-[18px] shrink-0 text-slate-400 dark:text-slate-500" strokeWidth={1.6} aria-hidden="true" />
              <p>{t('home.emptyWorkspaceHint')}</p>
            </div>
          )}
        </section>

        <div className="mt-8 pb-4 text-center text-xs tracking-wide text-slate-500 dark:text-slate-400">
          {t('home.brandPoweredBy')}
        </div>
      </main>

      <ConfirmDialog
        open={projectPendingDelete !== null}
        title={t('home.actionDelete')}
        description={projectPendingDelete ? t('home.deleteConfirm').replace('{name}', getProjectTitle(projectPendingDelete)) : ''}
        confirmLabel={t('common.delete')}
        cancelLabel={t('common.cancel')}
        tone="danger"
        busy={projectPendingDelete ? deletingProjectId === getProjectKey(projectPendingDelete) : false}
        onCancel={() => {
          if (!deletingProjectId) {
            setProjectPendingDelete(null);
          }
        }}
        onConfirm={() => {
          if (projectPendingDelete) {
            void handleDeleteProject(projectPendingDelete);
          }
        }}
      />
    </div>
  );
};
