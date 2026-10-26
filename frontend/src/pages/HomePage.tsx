import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Pencil, Star, Trash2 } from 'lucide-react';
import { DiagramPromptComposer } from '../components/DiagramPromptComposer';
import { Header } from '../components/Header';
import { RecentProjectPreview } from '../components/Home/RecentProjectPreview';
import { DiagramTypeOutline } from '../components/DiagramTypeOutline';
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
  const { t } = useLanguage();
  const authIdentity = user?.user_id ?? null;
  const activeAuthIdentityRef = useRef<string | null>(authIdentity);
  const previousAuthIdentityRef = useRef<string | null | undefined>(undefined);
  const pinnedAuthIdentityRef = useRef<string | null>(authIdentity);
  const skipNextPinnedSaveRef = useRef(false);
  const loadRequestRef = useRef(0);
  const lastAutoLoadAuthIdentityRef = useRef<string | null | undefined>(undefined);
  const [prompt, setPrompt] = useState('');
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

  const startFromExample = (content: string) => {
    const promptText = content.trim();
    const llmConfigId = modelOptions[modelIndex].id;
    const canvasMode = canvasOptions[canvasIndex].id;
    navigate('/workspace', {
      state: {
        initialPrompt: promptText,
        initialDiagramType: selectedDiagramType,
        initialLlmConfigId: llmConfigId,
        initialCanvasMode: canvasMode,
        initialSource: 'home',
        preflightGeneration: true,
        preflightKind: 'startup',
      },
    });
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


  const modelOptions = defaultConfigs.map((c) => ({ id: c.id, label: t('home.serverModel') }));

  const canvasOptions: Array<{ id: 'tldraw' | 'excalidraw'; label: string }> = [
    { id: 'excalidraw', label: t('home.canvasExcalidraw') },
    { id: 'tldraw', label: t('home.canvasTldraw') },
  ];

  const selectedDiagramType: DiagramType = pillIdToDiagramType[selectedPillId] ?? 'automated';
  const getProjectKey = getHomeProjectKey;
  const getProjectTitle = (project: RecentDiagram) => project.summary || project.prompt || t('home.untitledDiagram');
  const isInitialLoading = loadStatus === 'loading' && recentProjects.length === 0;
  const isRefreshingProjects = loadStatus === 'loading' && recentProjects.length > 0;
  const isLoadFailedWithoutData = loadStatus === 'failed' && recentProjects.length === 0;

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

  const examples = [
    { text: t('home.sampleMicroservice'), outline: 'architecture' },
    { text: t('home.sampleTraining'), outline: 'flowchart' },
    { text: t('home.sampleBrowser'), outline: 'mindmap' },
  ] as const;
  const starterTemplates = [
    {
      label: t('home.pillArchitectureLabel'),
      prompt: t('home.sampleMicroservice'),
      pillId: 'architecture',
      outline: 'architecture',
    },
    {
      label: t('home.pillSequenceLabel'),
      prompt: t('landing.exampleSequence'),
      pillId: 'sequence',
      outline: 'sequence',
    },
    {
      label: t('home.pillFlowLabel'),
      prompt: t('home.sampleTraining'),
      pillId: 'flow',
      outline: 'flowchart',
    },
    {
      label: t('home.pillMindMapLabel'),
      prompt: t('home.sampleBrowser'),
      pillId: 'mindmap',
      outline: 'mindmap',
    },
  ] as const;

  const handleStarterTemplate = (template: (typeof starterTemplates)[number]) => {
    setSelectedPillId(template.pillId);
    setPrompt(template.prompt);
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
    <div className="bg-soft-mesh dark:bg-soft-mesh-dark min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      <Header />

      <main id="main-content" className="flex-1 flex flex-col items-center px-4 py-8 sm:py-10 max-w-6xl mx-auto w-full">
        {/* Hero Section - AI Creation Launcher */}
        <div className="w-full max-w-4xl flex flex-col items-center text-center mb-10 mt-1">
          <p className="mb-4 text-xs font-semibold tracking-[0.16em] text-brand-700 dark:text-brand-300">EVODESIGN STUDIO</p>
          <h1 className="mb-3 max-w-2xl font-display text-3xl font-semibold leading-tight text-slate-900 dark:text-slate-100 sm:mb-4 sm:text-4xl">
            {t('home.title')}
          </h1>
          <p className="mb-6 max-w-2xl text-base leading-relaxed text-slate-600 dark:text-slate-300 sm:mb-8 sm:text-lg">
            {t('home.subtitle')}
          </p>

          <div className="w-full relative group">
            <DiagramPromptComposer
              prompt={prompt}
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
              moreLabel={t('home.pillMoreLabel')}
              isGenerating={false}
              progress={null}
              t={t}
              disableGenerate={!prompt.trim()}
            />

          </div>

          <section className="mt-8 w-full text-left" aria-labelledby="home-starter-templates-title">
            <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 id="home-starter-templates-title" className="text-sm font-bold text-slate-900 dark:text-slate-100">
                  {t('home.starterTemplatesTitle')}
                </h2>
                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {t('home.starterTemplatesHint')}
                </p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {starterTemplates.map((template) => (
                <button
                  key={template.label}
                  type="button"
                  onClick={() => handleStarterTemplate(template)}
                  className="group overflow-hidden rounded-2xl border border-white/80 bg-white/80 text-left shadow-sm backdrop-blur-xl transition-all hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-[0_16px_32px_rgba(49,93,130,0.14)] dark:border-white/10 dark:bg-slate-900/78 dark:hover:border-brand-500"
                >
                  <div className="h-16 border-b border-slate-100 bg-slate-50/80 px-3 py-2 text-brand-400 dark:border-slate-800 dark:bg-slate-950/80 dark:text-brand-500">
                    <DiagramTypeOutline kind={template.outline} />
                  </div>
                  <div className="p-3">
                    <p className="text-xs font-bold text-brand-600 dark:text-brand-300">{template.label}</p>
                    <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-700 dark:text-slate-200">{template.prompt}</p>
                    <span className="mt-3 inline-flex items-center text-xs font-semibold text-slate-500 transition group-hover:text-brand-600 dark:text-slate-400 dark:group-hover:text-brand-300">
                      {t('home.useAsDraft')} →
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </section>
        </div>

        {/* Recent Projects Grid */}
        <div className="w-full">
          <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100">{t('home.recentProjects')}</h2>
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex items-center rounded-lg border border-white/70 bg-white/70 p-0.5 backdrop-blur-md dark:border-white/10 dark:bg-slate-900/75" role="tablist" aria-label={t('home.recentProjects')}>
                <button
                  type="button"
                  onClick={() => setActiveHomeTab('recent')}
                  role="tab"
                  aria-selected={activeHomeTab === 'recent'}
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
                  role="tab"
                  aria-selected={activeHomeTab === 'pinned'}
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
            </div>
          </div>

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
            <div role="status" aria-label={t('common.loading')} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-64 animate-pulse rounded-2xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"></div>
              ))}
            </div>
          ) : visibleProjects.length > 0 ? (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                {visibleProjects.map((project) => {
                  const projectKey = getProjectKey(project);
                  const isPinned = pinnedProjectIds.includes(projectKey);

                  return (
                    <article
                      key={projectKey}
                      className="group relative flex h-64 flex-col overflow-hidden rounded-2xl border border-white/70 bg-white/70 backdrop-blur-xl transition-all hover:border-brand-300 hover:shadow-[0_20px_40px_rgba(148,163,184,0.24)] dark:border-white/10 dark:bg-slate-900/75 dark:hover:border-brand-500/70 dark:hover:shadow-[0_14px_28px_rgba(2,6,23,0.5)]"
                    >
                      {/* Thumbnail Area */}
                      <div className="relative flex-1 overflow-hidden bg-slate-50 dark:bg-slate-800/50">
                        <button
                          type="button"
                          onClick={() => handleOpenProject(project)}
                          className="absolute inset-0 z-10 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-300"
                          aria-label={getProjectTitle(project)}
                        />
                        <RecentProjectPreview
                          project={project}
                          title={getProjectTitle(project)}
                          unavailableLabel={t('home.previewUnavailable')}
                        />

                        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-slate-950/45 via-slate-900/5 to-transparent opacity-70 transition-opacity group-hover:opacity-100 dark:from-slate-950/70" />

                        <div className="absolute inset-x-3 bottom-3 z-20 flex items-center justify-between gap-2 transition-opacity fine:opacity-0 fine:group-hover:opacity-100 fine:group-focus-within:opacity-100">
                          <button
                            type="button"
                            className="inline-flex min-h-11 items-center gap-2 rounded-full bg-white/95 px-3 py-2 text-sm font-semibold text-slate-800 shadow-sm transition hover:bg-white dark:bg-slate-900/95 dark:text-slate-100"
                            title={t('home.actionEdit')}
                            onClick={() => handleOpenProject(project)}
                          >
                            <Pencil className="h-4 w-4" />
                            {t('home.actionEdit')}
                          </button>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              className={`inline-flex h-11 w-11 items-center justify-center rounded-full shadow-sm transition ${
                                isPinned
                                  ? 'bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-500/20 dark:text-amber-300 dark:hover:bg-amber-500/30'
                                  : 'bg-white/95 text-slate-700 hover:text-brand-600 dark:bg-slate-900/95 dark:text-slate-200 dark:hover:text-brand-400'
                              } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950`}
                              title={isPinned ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')}
                              aria-label={isPinned ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')}
                              aria-pressed={isPinned}
                              onClick={() => handleTogglePin(project)}
                            >
                              <Star className={`h-4 w-4 ${isPinned ? 'fill-current' : ''}`} />
                            </button>
                            <button
                              type="button"
                              className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/95 text-red-600 shadow-sm transition hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 focus-visible:ring-offset-2 dark:bg-slate-900/95 dark:text-red-400 dark:hover:bg-red-500/15 dark:focus-visible:ring-offset-slate-950"
                              title={t('home.actionDelete')}
                              aria-label={t('home.actionDelete')}
                              onClick={() => setProjectPendingDelete(project)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>

                        <div className="absolute left-3 top-3 z-20">
                          <span className="inline-flex items-center rounded-full bg-slate-950/65 px-2.5 py-1 text-[11px] font-medium text-white backdrop-blur dark:bg-slate-900/80">
                            {project.diagram_type}
                          </span>
                          {isPinned && (
                            <span className="ml-2 inline-flex items-center rounded-full bg-amber-100/90 px-2.5 py-1 text-[11px] font-semibold text-amber-700 backdrop-blur dark:bg-amber-500/20 dark:text-amber-300">
                              {t('home.pinnedTab')}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Card Info */}
                      <div className="p-4">
                        <h3 className="mb-1 truncate font-semibold text-slate-900 dark:text-slate-100">
                          {getProjectTitle(project)}
                        </h3>
                        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                          <span className="truncate pr-3">{getDiagramTypeLabel(project.diagram_type, t)}</span>
                          <span>{new Date(project.updated_at || project.created_at).toLocaleDateString()}</span>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>

              {hiddenRecentCount > 0 && (
                <div className="mt-6 rounded-2xl border border-brand-200/70 bg-brand-50/70 px-4 py-4 backdrop-blur-xl dark:border-brand-500/30 dark:bg-brand-500/10">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-brand-800 dark:text-brand-200">
                        {recentContinuationText}
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
                        {recentContinuationHint}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleViewAllProjects}
                      className="btn-primary min-h-11 w-full justify-center gap-1.5 text-sm sm:w-auto"
                    >
                      {t('home.viewAllProjects')}
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
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
          ) : activeHomeTab === 'pinned' ? (
            <div className="rounded-2xl border border-dashed border-slate-200/70 bg-white/65 p-6 backdrop-blur-xl dark:border-slate-700 dark:bg-slate-900/75">
              <div className="text-center">
                <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100">{t('home.pinnedEmptyTitle')}</h3>
                <p className="mt-1 text-slate-500 dark:text-slate-400">{t('home.pinnedEmptyHint')}</p>
              </div>
            </div>
          ) : recentProjects.length > 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200/70 bg-white/65 p-6 backdrop-blur-xl dark:border-slate-700 dark:bg-slate-900/75">
              <div className="text-center">
                <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100">{t('home.noProjectsTitle')}</h3>
                <p className="mt-1 text-slate-500 dark:text-slate-400">{t('home.noProjectsHint')}</p>
              </div>
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed border-slate-200/70 bg-white/65 p-6 backdrop-blur-xl dark:border-slate-700 dark:bg-slate-900/75">
              <div className="mb-4 text-center">
                <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100">{t('home.noProjectsTitle')}</h3>
                <p className="mt-1 text-slate-500 dark:text-slate-400">{t('home.noProjectsHint')}</p>
              </div>

              <div>
                <p className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">{t('home.tryExamples')}</p>
                <div className="grid gap-3 md:grid-cols-3">
                  {examples.map((item) => (
                    <button
                      key={item.text}
                      type="button"
                      onClick={() => startFromExample(item.text)}
                      className="group relative overflow-hidden rounded-xl border border-white/70 bg-white/70 text-left text-sm text-slate-700 backdrop-blur-md transition-all hover:border-brand-300 hover:bg-brand-50/40 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200 dark:hover:border-brand-500 dark:hover:bg-brand-500/10"
                    >
                      <div className="relative h-[120px] flex items-center justify-center overflow-hidden bg-slate-50/50 dark:bg-slate-800/60 border-b border-slate-100/50 dark:border-slate-700/50">
                        <div className="w-full px-4 text-brand-400 opacity-50 dark:text-brand-500 dark:opacity-40">
                          <DiagramTypeOutline kind={item.outline} />
                        </div>
                      </div>
                      <div className="px-4 py-3">
                        <p className="line-clamp-2">{item.text}</p>
                        <span className="mt-2 inline-block text-xs font-medium text-brand-600 dark:text-brand-400 group-hover:underline">{t('home.tryExamples')} →</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

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
