import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  ChevronDown,
  CircleAlert,
  Copy,
  FolderKanban,
  Grid3X3,
  List,
  Plus,
  Search,
  Star,
} from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { RecentProjectPreview } from '../components/Home/RecentProjectPreview';
import { Header } from '../components/Header';
import { ChoiceSelect } from '../components/ChoiceSelect';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { fetchRecentDiagrams } from '../services/backendApi';
import { GUEST_IMPORT_COMPLETED_EVENT } from '../services/guestImportService';
import { loadFavoriteProjectIds, saveFavoriteProjectIds } from '../services/projectPreferences';
import { getDiagramTypeLabel } from '../constants/app';
import type { DiagramType } from '../types/api';
import type { RecentDiagram } from '../types/app';

type SortMode = 'updated' | 'type' | 'agent';
type ViewMode = 'grid' | 'list';
type ProjectScope = 'all' | 'favorites';

type ProjectCard = {
  projectId: string;
  projectName: string;
  diagrams: RecentDiagram[];
  diagramCount: number;
  latestEditedAt: string;
  latestAgentVersion: string;
  latestDiagramType: DiagramType;
};

const DASHBOARD_PROJECT_PAGE_SIZE = 60;
type ProjectLoadStatus = 'loading' | 'ready' | 'failed';
type ProjectLoadMode = 'replace' | 'append';

const normalizeProjectScope = (value: string | null): ProjectScope => (
  value === 'favorites' ? 'favorites' : 'all'
);

const getProjectKeyFromDiagram = (item: RecentDiagram) => item.project_id || item.request_id;

const getRecentDiagramIdentity = (item: RecentDiagram) => (
  `${getProjectKeyFromDiagram(item)}:${item.snapshot_id || item.diagram_id || item.request_id}`
);

const getProjectDomId = (projectId: string) => projectId.replace(/[^A-Za-z0-9_-]/g, '-') || 'project';
const getProjectDetailId = (projectId: string) => `project-detail-${getProjectDomId(projectId)}`;

const mergeRecentDiagramPages = (existing: RecentDiagram[], incoming: RecentDiagram[]) => {
  const seen = new Set<string>();
  return [...existing, ...incoming].filter((item) => {
    const key = getRecentDiagramIdentity(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

export const DashboardPage = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useBackendAuth();
  const { t } = useLanguage();
  const authIdentity = user?.user_id ?? null;
  const requestedProjectScope = normalizeProjectScope(searchParams.get('scope'));

  const [loadStatus, setLoadStatus] = useState<ProjectLoadStatus>('loading');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [hasMoreProjects, setHasMoreProjects] = useState(false);
  const [isLoadingMoreProjects, setIsLoadingMoreProjects] = useState(false);
  const [recentFiles, setRecentFiles] = useState<RecentDiagram[]>([]);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('updated');
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [projectScope, setProjectScope] = useState<ProjectScope>(() => requestedProjectScope);
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [favoriteProjectIds, setFavoriteProjectIds] = useState<string[]>(() => loadFavoriteProjectIds(authIdentity));
  const [flashMessage, setFlashMessage] = useState<string | null>(null);
  const activeAuthIdentityRef = useRef<string | null>(authIdentity);
  const previousAuthIdentityRef = useRef<string | null | undefined>(undefined);
  const favoritesAuthIdentityRef = useRef<string | null>(authIdentity);
  const skipNextFavoritesSaveRef = useRef(false);
  const loadRequestRef = useRef(0);
  const lastAutoLoadAuthIdentityRef = useRef<string | null | undefined>(undefined);
  const recentFilesRef = useRef<RecentDiagram[]>([]);
  activeAuthIdentityRef.current = authIdentity;
  recentFilesRef.current = recentFiles;

  useEffect(() => {
    if (favoritesAuthIdentityRef.current === authIdentity) return;
    skipNextFavoritesSaveRef.current = true;
    setFavoriteProjectIds(loadFavoriteProjectIds(authIdentity));
    favoritesAuthIdentityRef.current = authIdentity;
  }, [authIdentity]);

  useEffect(() => {
    if (favoritesAuthIdentityRef.current !== authIdentity) return;
    if (skipNextFavoritesSaveRef.current) {
      skipNextFavoritesSaveRef.current = false;
      return;
    }
    saveFavoriteProjectIds(authIdentity, favoriteProjectIds);
  }, [authIdentity, favoriteProjectIds]);

  useEffect(() => {
    const previousAuthIdentity = previousAuthIdentityRef.current;
    if (previousAuthIdentity !== undefined && previousAuthIdentity !== authIdentity) {
      loadRequestRef.current += 1;
      setRecentFiles([]);
      setExpandedProjectId(null);
      setLoadError(null);
      setLoadMoreError(null);
      setHasMoreProjects(false);
      setIsLoadingMoreProjects(false);
      setLoadStatus('loading');
      setSearchKeyword('');
      setProjectScope(requestedProjectScope);
      setIsSearchFocused(false);
      setFlashMessage(null);
    }
    previousAuthIdentityRef.current = authIdentity;
  }, [authIdentity, requestedProjectScope]);

  useEffect(() => {
    setProjectScope((current) => (
      current === requestedProjectScope ? current : requestedProjectScope
    ));
  }, [requestedProjectScope]);

  const loadRecent = useCallback(async (mode: ProjectLoadMode = 'replace') => {
    const isAppend = mode === 'append';
    const requestId = ++loadRequestRef.current;
    const requestAuthIdentity = activeAuthIdentityRef.current;
    const offset = isAppend ? recentFilesRef.current.length : 0;
    const isCurrentRequest = () => (
      loadRequestRef.current === requestId
      && activeAuthIdentityRef.current === requestAuthIdentity
    );

    if (isAppend) {
      setIsLoadingMoreProjects(true);
      setLoadMoreError(null);
    } else {
      setLoadStatus('loading');
      setLoadError(null);
      setLoadMoreError(null);
    }

    try {
      const favoriteIdsForRequest = new Set(loadFavoriteProjectIds(requestAuthIdentity));
      const missingFavoriteIds = new Set(favoriteIdsForRequest);
      const loadedPageItems: RecentDiagram[] = [];
      let nextOffset = offset;
      let lastPageLength = 0;

      while (true) {
        const page = await fetchRecentDiagrams(requestAuthIdentity ?? '', {
          limit: DASHBOARD_PROJECT_PAGE_SIZE,
          offset: nextOffset,
        });
        loadedPageItems.push(...page);
        lastPageLength = page.length;
        page.forEach((item) => {
          missingFavoriteIds.delete(getProjectKeyFromDiagram(item));
        });

        if (
          isAppend
          || favoriteIdsForRequest.size === 0
          || missingFavoriteIds.size === 0
          || page.length < DASHBOARD_PROJECT_PAGE_SIZE
        ) {
          break;
        }

        nextOffset += DASHBOARD_PROJECT_PAGE_SIZE;
      }

      if (!isCurrentRequest()) return;
      const page = loadedPageItems;
      const currentFiles = isAppend ? recentFilesRef.current : [];
      const nextFiles = isAppend ? mergeRecentDiagramPages(currentFiles, page) : page;
      setHasMoreProjects(
        lastPageLength >= DASHBOARD_PROJECT_PAGE_SIZE
        && (!isAppend || nextFiles.length > currentFiles.length),
      );
      setRecentFiles(nextFiles);
      setLoadStatus('ready');
    } catch (error) {
      if (!isCurrentRequest()) return;
      console.warn('Dashboard projects are unavailable:', error);
      if (isAppend) {
        setLoadMoreError(t('dashboard.loadMoreFailed'));
      } else {
        setLoadError(t('dashboard.loadFailed'));
        setLoadStatus('failed');
      }
    } finally {
      if (isAppend && isCurrentRequest()) {
        setIsLoadingMoreProjects(false);
      }
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

  useEffect(() => {
    if (!flashMessage) return;
    const timer = window.setTimeout(() => setFlashMessage(null), 2200);
    return () => window.clearTimeout(timer);
  }, [flashMessage]);

  const getAgentVersion = useCallback((item: RecentDiagram) => {
    const raw = (item as RecentDiagram & { agent_version?: string | null }).agent_version;
    return raw?.trim() || t('dashboard.agentVersionDefault');
  }, [t]);

  const getFileTitle = useCallback(
    (item: RecentDiagram) => item.summary || item.prompt || t('dashboard.untitledDiagram'),
    [t],
  );

  const getActivityTime = useCallback((item: RecentDiagram) => item.updated_at || item.created_at, []);

  const formatTime = (value: string) => {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '-';
    return d.toLocaleString();
  };

  const handleCopyProjectId = async (projectId: string) => {
    try {
      await navigator.clipboard.writeText(projectId);
      setFlashMessage(t('dashboard.linkCopied'));
    } catch {
      setFlashMessage(t('dashboard.linkCopyFailed'));
    }
  };

  const projectCards = useMemo<ProjectCard[]>(() => {
    const groups = new Map<string, RecentDiagram[]>();

    recentFiles.forEach((item) => {
      const key = getProjectKeyFromDiagram(item);
      const bucket = groups.get(key) ?? [];
      bucket.push(item);
      groups.set(key, bucket);
    });

    return Array.from(groups.entries()).map(([projectId, diagrams]) => {
      const sortedDiagrams = [...diagrams].sort(
        (a, b) => new Date(getActivityTime(b)).getTime() - new Date(getActivityTime(a)).getTime(),
      );
      const latest = sortedDiagrams[0];
      const knownSnapshotCounts = sortedDiagrams
        .map((item) => item.snapshot_count)
        .filter((count): count is number => typeof count === 'number' && Number.isFinite(count));
      const diagramCount = knownSnapshotCounts.length > 0
        ? Math.max(...knownSnapshotCounts, sortedDiagrams.length)
        : sortedDiagrams.length;

      return {
        projectId,
        projectName:
          latest.summary
            || latest.prompt
            || `${t('dashboard.untitledProject')} ${projectId.slice(0, 8)}`,
        diagrams: sortedDiagrams,
        diagramCount,
        latestEditedAt: getActivityTime(latest),
        latestAgentVersion: getAgentVersion(latest),
        latestDiagramType: latest.diagram_type,
      };
    });
  }, [getActivityTime, getAgentVersion, recentFiles, t]);

  const filteredProjectCards = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase();

    const result = projectCards.filter((project) => {
      const searchable = [
        project.projectName,
        project.diagrams.map((item) => getFileTitle(item)).join(' '),
        getDiagramTypeLabel(project.latestDiagramType, t),
        project.latestAgentVersion,
      ]
        .join(' ')
        .toLowerCase();

      const keywordPass = !keyword || searchable.includes(keyword);
      if (!keywordPass) return false;

      if (projectScope === 'favorites') {
        return favoriteProjectIds.includes(project.projectId);
      }
      return true;
    });

    result.sort((a, b) => {
      if (sortMode === 'type') {
        return getDiagramTypeLabel(a.latestDiagramType, t).localeCompare(getDiagramTypeLabel(b.latestDiagramType, t));
      }
      if (sortMode === 'agent') {
        return a.latestAgentVersion.localeCompare(b.latestAgentVersion);
      }
      return new Date(b.latestEditedAt).getTime() - new Date(a.latestEditedAt).getTime();
    });

    return result;
  }, [
    favoriteProjectIds,
    getFileTitle,
    projectCards,
    projectScope,
    searchKeyword,
    sortMode,
    t,
  ]);

  useEffect(() => {
    if (filteredProjectCards.length === 0) {
      setExpandedProjectId(null);
      return;
    }

    const expandedProjectExists = expandedProjectId === null
      || filteredProjectCards.some((item) => item.projectId === expandedProjectId);
    if (!expandedProjectExists) {
      setExpandedProjectId(null);
    }
  }, [filteredProjectCards, expandedProjectId]);

  const loading = loadStatus === 'loading';
  const hasLoadedProjects = projectCards.length > 0;
  const hasSearchKeyword = searchKeyword.trim().length > 0;
  const isInitialLoading = loading && !hasLoadedProjects;
  const isRefreshingProjects = loading && hasLoadedProjects;
  const isLoadFailedWithoutData = loadStatus === 'failed' && !hasLoadedProjects;
  const isFavoritesEmptyState = hasLoadedProjects
    && projectScope === 'favorites'
    && !hasSearchKeyword
    && filteredProjectCards.length === 0;
  const showFilteredEmptyState = hasLoadedProjects
    && filteredProjectCards.length === 0
    && !isFavoritesEmptyState
    && (hasSearchKeyword || projectScope !== 'all');
  const canLoadMoreProjects = hasLoadedProjects
    && hasMoreProjects
    && !loading
    && !isLoadingMoreProjects;
  const shouldAutoLoadSearchResults = hasSearchKeyword
    && projectScope === 'all'
    && canLoadMoreProjects
    && !loadMoreError;
  const isSearchingMoreProjects = hasSearchKeyword
    && projectScope === 'all'
    && hasMoreProjects
    && (isLoadingMoreProjects || shouldAutoLoadSearchResults)
    && !loadMoreError;

  const handleLoadMoreProjects = useCallback(() => {
    if (!canLoadMoreProjects) return;
    void loadRecent('append');
  }, [canLoadMoreProjects, loadRecent]);

  useEffect(() => {
    if (!shouldAutoLoadSearchResults) return;
    void loadRecent('append');
  }, [loadRecent, recentFiles.length, shouldAutoLoadSearchResults]);

  const recentEvolutions = useMemo(
    () => [...recentFiles]
      .sort((a, b) => new Date(getActivityTime(b)).getTime() - new Date(getActivityTime(a)).getTime())
      .slice(0, 10),
    [getActivityTime, recentFiles],
  );

  const searchSuggestions = useMemo(() => {
    const recent = [...new Set(recentEvolutions.map((item) => getFileTitle(item)))].slice(0, 4);
    const hot = [
      t('diagram.flowchart'),
      t('home.pillArchitectureLabel'),
      t('diagram.sequence'),
      t('diagram.mindmap'),
    ];

    return { recent, hot };
  }, [getFileTitle, recentEvolutions, t]);

  const toggleFavoriteProject = (projectId: string) => {
    setFavoriteProjectIds((prev) => (
      prev.includes(projectId)
        ? prev.filter((id) => id !== projectId)
        : [...prev, projectId]
    ));
  };

  const handleProjectScopeChange = useCallback((nextScope: ProjectScope) => {
    setProjectScope(nextScope);
    const nextParams = new URLSearchParams(searchParams);
    if (nextScope === 'favorites') {
      nextParams.set('scope', 'favorites');
    } else {
      nextParams.delete('scope');
    }
    setSearchParams(nextParams, { replace: true });
  }, [searchParams, setSearchParams]);

  const handleClearSearch = () => {
    setSearchKeyword('');
    setLoadMoreError(null);
    setIsSearchFocused(false);
  };

  const handleClearFilters = () => {
    handleClearSearch();
    handleProjectScopeChange('all');
  };

  const handleSearchKeywordChange = useCallback((value: string) => {
    setSearchKeyword(value);
    setLoadMoreError(null);
  }, []);

  const handleOpenProject = useCallback((item: RecentDiagram) => {
    navigate('/workspace', { state: { pendingLoadProject: item } });
  }, [navigate]);

  const handleProjectCardClick = useCallback((project: ProjectCard) => {
    handleOpenProject(project.diagrams[0]);
  }, [handleOpenProject]);

  const handleProjectDetailsClick = (projectId: string) => {
    setExpandedProjectId((current) => current === projectId ? null : projectId);
  };

  const formatProjectCount = useCallback((count: number) => (
    `${count} ${t(count === 1 ? 'dashboard.projectCountSingular' : 'dashboard.projectCountPlural')}`
  ), [t]);

  const loadedProjectsStatus = useMemo(() => {
    const visible = formatProjectCount(filteredProjectCards.length);
    return hasMoreProjects ? `${visible} · ${t('dashboard.moreProjectsAvailable')}` : visible;
  }, [
    filteredProjectCards.length,
    formatProjectCount,
    hasMoreProjects,
    t,
  ]);

  const formatDiagramCount = useCallback((count: number) => (
    `${count} ${t(count === 1 ? 'dashboard.diagramCountSingular' : 'dashboard.diagramCountPlural')}`
  ), [t]);

  const projectScopeTabs: Array<{ id: ProjectScope; label: string; icon: typeof Star }> = [
    { id: 'all', label: t('dashboard.tabAllProjects'), icon: FolderKanban },
    { id: 'favorites', label: t('dashboard.tabFavorites'), icon: Star },
  ];

  const sortOptions: Array<{ id: SortMode; label: string; shortLabel: string }> = [
    { id: 'updated', label: t('dashboard.sortUpdated'), shortLabel: t('dashboard.sortUpdatedShort') },
    { id: 'type', label: t('dashboard.sortType'), shortLabel: t('dashboard.sortTypeShort') },
    { id: 'agent', label: t('dashboard.sortAgent'), shortLabel: t('dashboard.sortAgentShort') },
  ];

  return (
    <div className="studio-shell studio-library studio-projects min-h-screen flex flex-col">
      <Header variant="studio" />

      <main id="main-content" className="studio-page-main"><div className="studio-page-content">
        <section className="project-library-toolbar">
          <div className="flex items-center gap-1" role="group" aria-label={t('dashboard.projectSpaces')}>
            {projectScopeTabs.map((tab) => <button key={tab.id} type="button" aria-pressed={projectScope === tab.id}
              onClick={() => handleProjectScopeChange(tab.id)}
              className={`studio-tab ${projectScope === tab.id ? 'studio-tab-active' : ''}`}>
              <tab.icon size={14} />{tab.label}
            </button>)}
          </div>
          <div className="relative w-full sm:ml-auto sm:w-64" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setIsSearchFocused(false); }}>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input value={searchKeyword} onChange={(event) => handleSearchKeywordChange(event.target.value)}
              onFocus={() => setIsSearchFocused(true)}
              onKeyDown={(event) => { if (event.key === 'Escape') setIsSearchFocused(false); }}
              placeholder={t('dashboard.searchPlaceholder')} aria-label={t('dashboard.searchPlaceholder')}
              className="studio-search" />
            {isSearchFocused && !hasSearchKeyword && <div className="surface-overlay absolute inset-x-0 top-12 z-30 rounded-xl p-2 shadow-e3">
              {[...searchSuggestions.recent, ...searchSuggestions.hot].map((item) => <button key={item} type="button"
                onMouseDown={(event) => event.preventDefault()} onClick={() => { handleSearchKeywordChange(item); setIsSearchFocused(false); }}
                className="flex min-h-10 w-full items-center rounded-lg px-3 text-left text-xs text-slate-600 transition hover:bg-indigo-50 dark:text-slate-300 dark:hover:bg-white/5">{item}</button>)}
            </div>}
          </div>
          <ChoiceSelect label={t('dashboard.sortByLabel')} value={sortMode} menuWidth={176} align="end"
            options={sortOptions.map(option => ({ value: option.id, label: option.label }))}
            onChange={value => setSortMode(value as SortMode)} />
          <div className="flex items-center gap-0.5" role="group" aria-label={t('dashboard.viewModeLabel')}>
            {([{ id: 'list', icon: List, label: t('dashboard.viewList') }, { id: 'grid', icon: Grid3X3, label: t('dashboard.viewGrid') }] as const).map((view) => <button
              key={view.id} type="button" onClick={() => setViewMode(view.id)} aria-label={view.label} aria-pressed={viewMode === view.id}
              className={`studio-icon-button ${viewMode === view.id ? 'studio-tab-active' : ''}`}><view.icon size={16} /></button>)}
          </div>
        <button type="button" onClick={() => navigate('/workspace')} className="studio-primary project-create-action"><Plus size={16} />{t('dashboard.newProject')}</button>
        </section>

        {/* ── Flash message ── */}
        {flashMessage && (
          <div role="status" aria-live="polite" className="mb-4 rounded-xl border border-brand-200/80 bg-brand-50/65 px-4 py-2 text-sm font-medium text-brand-700 shadow-sm backdrop-blur-xl dark:border-brand-500/40 dark:bg-brand-500/20 dark:text-brand-300">
            {flashMessage}
          </div>
        )}

        {loadError && !loading && projectCards.length > 0 && (
          <section className="state-panel mb-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div role="alert">
                <p className="text-sm font-medium text-red-600 dark:text-red-300">
                  {loadError}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {t('dashboard.loadFailedStaleHint')}
                </p>
              </div>
              <button
                type="button"
                onClick={() => { void loadRecent(); }}
                className="studio-secondary dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
              >
                {t('common.retry')}
              </button>
            </div>
          </section>
        )}

        {/* ── Content ── */}
        {isRefreshingProjects && (
          <div role="status" aria-live="polite" className="mb-4 rounded-xl border border-brand-200/70 bg-brand-50/65 px-4 py-2 text-sm font-medium text-brand-700 backdrop-blur dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200">
            {t('dashboard.refreshingProjects')}
          </div>
        )}

        {isSearchingMoreProjects && (
          <div role="status" aria-live="polite" className="mb-4 rounded-xl border border-brand-200/70 bg-brand-50/65 px-4 py-2 text-sm font-medium text-brand-700 backdrop-blur dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200">
            {t('dashboard.searchingMoreProjects')}
          </div>
        )}

        {isInitialLoading ? (
          <div role="status" aria-label={t('common.loading')} className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 hero-fade-up hero-delay-2">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-44 animate-pulse rounded-2xl border border-white/60 bg-white/55 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60">
                <div className="h-16 rounded-t-2xl bg-gradient-to-br from-slate-200/40 to-slate-100/30 dark:from-slate-700/30 dark:to-slate-800/20" />
                <div className="p-4 space-y-3">
                  <div className="h-3 w-3/4 rounded-full bg-slate-200/70 dark:bg-slate-700/50" />
                  <div className="h-2.5 w-1/2 rounded-full bg-slate-200/50 dark:bg-slate-700/30" />
                  <div className="flex gap-2">
                    <div className="h-5 w-14 rounded-full bg-slate-200/50 dark:bg-slate-700/30" />
                    <div className="h-5 w-16 rounded-full bg-slate-200/50 dark:bg-slate-700/30" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : isLoadFailedWithoutData ? (
          <section role="alert" className="studio-empty-state">
            <div className="mx-auto flex max-w-xl flex-col items-center text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-red-200/80 bg-red-50 text-red-600 shadow-sm dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                <CircleAlert className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">{t('dashboard.loadFailedTitle')}</h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500 dark:text-slate-400">{t('dashboard.loadFailedEmptyHint')}</p>
              <div className="mt-5 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={() => { void loadRecent(); }}
                  className="studio-primary min-h-11 gap-2"
                >
                  {t('common.retry')}
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/workspace')}
                  className="studio-secondary min-h-11 gap-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                >
                  <Plus className="h-4 w-4" />
                  {t('dashboard.newProject')}
                </button>
              </div>
            </div>
          </section>
        ) : isFavoritesEmptyState ? (
          <section className="studio-empty-state">
            <div className="mx-auto flex max-w-xl flex-col items-center text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-amber-200/80 bg-amber-50 text-amber-600 shadow-sm dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
                <Star className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">{t('dashboard.noFavoriteProjects')}</h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500 dark:text-slate-400">
                {hasMoreProjects ? t('dashboard.favoritesMayHaveMore') : t('dashboard.noFavoriteProjectsHint')}
              </p>
              {loadMoreError && (
                <p role="alert" className="mt-3 text-xs font-medium text-red-600 dark:text-red-300">
                  {loadMoreError}
                </p>
              )}
              <div className="mt-5 flex flex-col gap-2 sm:flex-row">
                {hasMoreProjects && (
                  <button
                    type="button"
                    onClick={handleLoadMoreProjects}
                    disabled={!canLoadMoreProjects}
                    className="studio-primary min-h-11 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : t('dashboard.loadMoreProjects')}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleProjectScopeChange('all')}
                  className={`${hasMoreProjects ? 'studio-secondary dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300' : 'studio-primary'} min-h-11`}
                >
                  {t('dashboard.tabAllProjects')}
                </button>
              </div>
            </div>
          </section>
        ) : showFilteredEmptyState ? (
          <section className="studio-empty-state">
            <div className="mx-auto flex max-w-xl flex-col items-center text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-slate-200/80 bg-gradient-to-br from-slate-50 via-white to-brand-50 text-slate-500 shadow-sm dark:border-slate-700 dark:from-slate-800 dark:via-slate-900 dark:to-brand-500/10 dark:text-slate-300">
                <Search className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">{t('dashboard.noSearchResults')}</h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500 dark:text-slate-400">
                {isLoadingMoreProjects
                  ? t('dashboard.searchingMoreProjects')
                  : hasMoreProjects
                    ? t('dashboard.searchMayHaveMore')
                    : t('dashboard.noSearchResultsHint')}
              </p>
              {loadMoreError && (
                <p role="alert" className="mt-3 text-xs font-medium text-red-600 dark:text-red-300">
                  {loadMoreError}
                </p>
              )}
              <div className="mt-5 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={handleClearSearch}
                  className="studio-primary min-h-11 gap-2"
                >
                  {t('dashboard.clearSearch')}
                </button>
                {projectScope !== 'all' && (
                  <button
                    type="button"
                    onClick={handleClearFilters}
                    className="studio-secondary min-h-11 gap-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                  >
                    {t('dashboard.showAllProjects')}
                  </button>
                )}
                {hasMoreProjects ? (
                  <button
                    type="button"
                    onClick={handleLoadMoreProjects}
                    disabled={!canLoadMoreProjects}
                    className="studio-secondary min-h-11 gap-2 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                  >
                    {isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : t('dashboard.loadMoreProjects')}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => navigate('/workspace')}
                    className="studio-secondary min-h-11 gap-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                  >
                    <Plus className="h-4 w-4" />
                    {t('dashboard.newProject')}
                  </button>
                )}
              </div>
            </div>
          </section>
        ) : filteredProjectCards.length === 0 ? (
          <section className="studio-empty-state">
            <div className="mx-auto flex max-w-lg flex-col items-center text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-brand-200/80 bg-gradient-to-br from-brand-50 via-white to-indigo-50 text-brand-500 shadow-e1 dark:border-brand-500/30 dark:from-brand-500/20 dark:via-slate-900 dark:to-indigo-500/15 dark:text-brand-400">
                <FolderKanban className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">{t('dashboard.emptyEmotionalTitle')}</h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-500 dark:text-slate-400">{t('dashboard.emptyEmotionalHint')}</p>
              <button type="button" onClick={() => navigate('/insights')} className="studio-secondary mt-4">{t('studio.browseExamples')}<ArrowRight size={14} /></button>

            </div>


          </section>
        ) : (
          <section aria-label={t('dashboard.projectSpaces')}>
            <div className={viewMode === 'grid' ? 'grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3' : 'divide-y divide-slate-200/70 border-b border-slate-200/70 dark:divide-white/[0.07] dark:border-white/[0.07]'}>
              {filteredProjectCards.map((project) => {
                const isExpanded = expandedProjectId === project.projectId;
                const isFavorite = favoriteProjectIds.includes(project.projectId);
                const detailId = getProjectDetailId(project.projectId);
                return <article key={project.projectId} className={viewMode === 'grid' ? 'studio-project-card' : 'studio-project-row'}>
                  <div className={viewMode === 'grid' ? 'relative' : 'flex items-center gap-2'}>
                    <button type="button" onClick={() => handleProjectCardClick(project)}
                      className={viewMode === 'grid' ? 'block w-full rounded-xl p-3 text-left' : 'flex min-w-0 flex-1 items-center gap-4 rounded-lg py-4 text-left'}
                      aria-label={`${t('dashboard.actionOpenProject')}: ${project.projectName}. ${formatDiagramCount(project.diagramCount)}. ${getDiagramTypeLabel(project.latestDiagramType, t)}.`}>
                      <div className={viewMode === 'grid' ? 'mb-3 h-32 overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-950/40' : 'hidden h-16 w-24 shrink-0 overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-950/40 sm:block'}>
                        <RecentProjectPreview project={project.diagrams[0]} title={project.projectName} unavailableLabel={t('home.previewUnavailable')} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h2 className="truncate text-[13px] font-semibold text-slate-800 dark:text-slate-100">{project.projectName}</h2>
                        <p className="mt-1.5 flex flex-wrap gap-x-2 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                          <span>{getDiagramTypeLabel(project.latestDiagramType, t)}</span><span aria-hidden="true">·</span><span>{formatDiagramCount(project.diagramCount)}</span>
                        </p>
                        <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500"><time dateTime={project.latestEditedAt}>{formatTime(project.latestEditedAt)}</time></p>
                      </div>
                    </button>
                    <div className={viewMode === 'grid' ? 'flex items-center justify-end gap-1 border-t border-slate-200/60 px-2 py-1 dark:border-white/[0.06]' : 'flex shrink-0 items-center gap-1'}>
                      <button type="button" onClick={() => toggleFavoriteProject(project.projectId)}
                        className={`studio-icon-button ${isFavorite ? 'text-violet-600 dark:text-violet-300' : ''}`}
                        aria-label={isFavorite ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')} aria-pressed={isFavorite}
                        title={isFavorite ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')}>
                        <Star size={15} className={isFavorite ? 'fill-current' : ''} />
                      </button>
                      <button type="button" onClick={() => handleProjectDetailsClick(project.projectId)} aria-expanded={isExpanded}
                        aria-controls={isExpanded ? detailId : undefined} aria-label={`${t('dashboard.actionReviewProject')}: ${project.projectName}`}
                        className="studio-secondary gap-1 px-2 text-xs">
                        <span className="hidden sm:inline">{t('dashboard.actionReviewProject')}</span><ChevronDown size={15} className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                      </button>
                    </div>
                  </div>
                  {isExpanded && <div id={detailId} className="border-t border-slate-200/70 px-3 py-3 dark:border-white/[0.07]">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{t('dashboard.mobileProjectDetailTitle')}</p>
                      <button type="button" onClick={() => handleCopyProjectId(project.projectId)} className="studio-secondary text-xs"><Copy size={13} />{t('dashboard.actionCopyProjectId')}</button>
                    </div>
                    {project.diagrams.map((item) => <button key={item.snapshot_id || item.diagram_id || item.request_id} type="button" onClick={() => handleOpenProject(item)} className="flex min-h-11 w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition hover:bg-indigo-50/60 dark:hover:bg-white/[0.03]">
                      <div className="min-w-0 flex-1"><p className="truncate text-xs font-medium text-slate-700 dark:text-slate-200">{getFileTitle(item)}</p><p className="mt-1 text-[11px] text-slate-500">{formatTime(getActivityTime(item))}</p></div><ArrowRight size={14} className="shrink-0 text-indigo-400" />
                    </button>)}
                    {project.diagramCount > project.diagrams.length && <p className="mt-2 text-xs leading-relaxed text-slate-500 dark:text-slate-400">{t('dashboard.projectHistoryHint')}</p>}
                  </div>}
                </article>;
              })}
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
              <p role="status">{isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : loadedProjectsStatus}</p>
              {loadMoreError && <p role="alert" className="text-red-600 dark:text-red-300">{loadMoreError}</p>}
              {hasMoreProjects && <button type="button" onClick={handleLoadMoreProjects} disabled={!canLoadMoreProjects} className="studio-secondary">
                {isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : t('dashboard.loadMoreProjects')}
              </button>}
            </div>
          </section>
        )}
      </div></main>
    </div>
  );
};
