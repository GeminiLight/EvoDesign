import { useBrowserModelLabel } from '../hooks/useBrowserModelLabel';
import '../styles/home.css';
import { useHostedModel } from '../hooks/useHostedModel';
import { loadModelConfig } from '../services/browser/modelConfig';
import { BROWSER_MODE, openModelSettings } from '../services/browser/runtime';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Box, ChevronDown, FolderClock, GitBranch, Network, Star, Workflow } from 'lucide-react';
import { DiagramPromptComposer } from '../components/DiagramPromptComposer';
import { Header } from '../components/Header';
import { HomeProjectTile } from '../components/Home/HomeProjectTile';
import { CreationSketch } from '../components/Home/CreationSketch';
import { HOME_REFERENCE_ACCEPT, HomeReferenceError, promptWithReference, readHomeReference } from '../utils/homeReference';
import type { HomeReference } from '../utils/homeReference';
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
const HOME_RECENT_DISPLAY_LIMIT = 6;

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
  const [reference, setReference] = useState<HomeReference | null>(null);
  const [referenceLoading, setReferenceLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
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
    if (!prompt.trim() || referenceLoading) return;
    const promptText = promptWithReference(prompt, reference, language);

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

  const visibleProjects = activeHomeTab === 'pinned'
    ? recentProjects.filter((project) => pinnedProjectIds.includes(getProjectKey(project))).slice(0, HOME_RECENT_DISPLAY_LIMIT)
    : recentProjects.slice(0, HOME_RECENT_DISPLAY_LIMIT);
  const starterTemplates = [
    { label: t('home.shortcutArchitecture'), prompt: t('home.sampleMicroservice'), pillId: 'architecture', Icon: Network, accent: 'blue' },
    { label: t('home.shortcutFlow'), prompt: t('home.sampleTraining'), pillId: 'flow', Icon: GitBranch, accent: 'violet' },
    { label: t('home.shortcutSequence'), prompt: t('landing.exampleSequence'), pillId: 'sequence', Icon: Workflow, accent: 'teal' },
  ];

  const handleReferenceFile = async (file: File | undefined) => {
    if (!file) return;
    setReferenceLoading(true);
    try {
      setReference(await readHomeReference(file));
      setPromptFocusRequest(value => value + 1);
    } catch (error) {
      const reason = error instanceof HomeReferenceError ? error.reason : 'invalidText';
      showToast(t(`home.referenceError_${reason}`), 'error');
    } finally {
      setReferenceLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

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
    <div className="studio-home min-h-screen">
      <Header variant="studio" />
      <main id="main-content" className="home-main">
        <section className="home-intro" aria-labelledby="home-heading">
          <h1 id="home-heading" className="home-headline">{t('home.titleLead')}<span>{t('home.titleAccent')}</span></h1>
          <div className="home-launcher">
            <input ref={fileInputRef} type="file" accept={HOME_REFERENCE_ACCEPT} hidden aria-label={t('home.addReference')} onChange={event => { void handleReferenceFile(event.target.files?.[0]); }} />
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
              attachTitle={t('home.referenceFormats')}
              onAttachmentClick={() => fileInputRef.current?.click()}
              attachedFileName={reference?.name}
              onRemoveAttachment={() => { setReference(null); setPromptFocusRequest(value => value + 1); }}
              enhanceTitle={t('home.enhancePrompt')}
              generateTitle={t('home.reviewSetup')}
              variant="home"
              leadingContent={BROWSER_MODE ? <button type="button" onClick={openModelSettings} className="home-model-button" aria-label={`${t('browser.modelSettings')}: ${modelLabel}`}>
                <Box size={17} className={isSharedModel && hosted.status === 'available' ? 'is-ready' : ''} aria-hidden="true" />
                <span className="truncate">{hosted.status === 'loading' && !loadModelConfig().model ? (zh ? '正在连接…' : 'Connecting…') : modelLabel}</span>
                <ChevronDown size={13} aria-hidden="true" />
              </button> : <span className="home-model-button"><Box size={17} aria-hidden="true" /><span className="truncate">{modelLabel}</span></span>}
              moreLabel={t('home.pillMoreLabel')}
              t={t}
              isDisabled={referenceLoading}
              disableGenerate={!prompt.trim() || referenceLoading}
            />
            {referenceLoading && <span className="home-reference-status" role="status">{t('home.readingReference')}</span>}
            <CreationSketch referenceLabel={t('home.sketchReference')} diagramLabel={t('home.sketchDiagram')} />
          </div>
          <section className="home-starters" aria-label={t('home.starterTemplatesTitle')}>
            {starterTemplates.map(({ Icon, ...template }) => (
              <button key={template.pillId} type="button" title={template.prompt} onClick={() => handleStarterTemplate({ ...template, Icon })} className={`home-shortcut ${template.accent}`}>
                <Icon size={26} strokeWidth={1.5} aria-hidden="true" /><span>{template.label}</span><ArrowRight size={16} aria-hidden="true" />
              </button>
            ))}
          </section>
        </section>

        <section className="home-projects" aria-labelledby="home-projects-heading">
          <div className="home-projects-heading">
            <div className="home-projects-heading-start">
              <h2 id="home-projects-heading">{t('home.continueCreating')}</h2>
              {recentProjects.length > 0 && <div className="home-project-filters" role="group" aria-label={t('home.recentProjects')}>
                <button type="button" onClick={() => setActiveHomeTab('recent')} aria-pressed={activeHomeTab === 'recent'}>{t('home.recentTab')}</button>
                <button type="button" onClick={() => setActiveHomeTab('pinned')} aria-pressed={activeHomeTab === 'pinned'}>{t('home.pinnedTab')}</button>
              </div>}
            </div>
            {recentProjects.length > 0 && <button type="button" onClick={handleViewAllProjects} className="home-view-all">{t('home.viewAllShort')}<ArrowRight size={15} aria-hidden="true" /></button>}
          </div>
          {loadError && recentProjects.length > 0 && <div role="alert" className="home-load-error"><span>{loadError}</span><button type="button" onClick={() => { void loadRecent(); }}>{t('common.retry')}</button></div>}
          {isRefreshingProjects && <p role="status" className="home-reference-status">{t('home.refreshingProjects')}</p>}
          {isInitialLoading ? (
            <div className="home-project-grid" role="status" aria-label={t('common.loading')}>{[1, 2, 3].map(i => <div key={i} className="home-project-skeleton" />)}</div>
          ) : visibleProjects.length > 0 ? (
            <div className="home-project-grid">
              {visibleProjects.map(project => <HomeProjectTile
                key={getProjectKey(project)}
                project={project}
                title={getProjectTitle(project)}
                metadata={`${getDiagramTypeLabel(project.diagram_type, t)} · ${new Date(project.updated_at || project.created_at).toLocaleDateString(language === 'zh' ? 'zh-CN' : 'en-US', { year: 'numeric', month: 'short', day: 'numeric' })}`}
                pinned={pinnedProjectIds.includes(getProjectKey(project))}
                onOpen={() => handleOpenProject(project)}
                onTogglePin={() => handleTogglePin(project)}
                onDelete={() => setProjectPendingDelete(project)}
                t={t}
              />)}
            </div>
          ) : isLoadFailedWithoutData ? (
            <div role="alert" className="home-project-empty"><p>{loadError}</p><p>{t('home.loadFailedHint')}</p><button type="button" onClick={() => { void loadRecent(); }}>{t('common.retry')}</button></div>
          ) : (
            <div className="home-project-empty">
              {activeHomeTab === 'pinned' && recentProjects.length > 0 ? <><Star size={20} strokeWidth={1.5} aria-hidden="true" /><p>{t('home.pinnedEmptyHint')}</p></> : <><FolderClock size={20} strokeWidth={1.5} aria-hidden="true" /><p>{t('home.emptyWorkspaceHint')}</p></>}
            </div>
          )}
        </section>
        <p className="home-footer">{t('home.brandPoweredBy')}</p>
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
