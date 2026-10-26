import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  ArrowUpDown,
  CircleAlert,
  Copy,
  FolderKanban,
  GitBranch,
  Grid3X3,
  List,
  Plus,
  Search,
  Sparkles,
  Star,
} from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { RecentProjectPreview } from '../components/Home/RecentProjectPreview';
import { Header } from '../components/Header';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { fetchRecentDiagrams } from '../services/backendApi';
import { GUEST_IMPORT_COMPLETED_EVENT } from '../services/guestImportService';
import { loadFavoriteProjectIds, saveFavoriteProjectIds } from '../services/projectPreferences';
import { defaultConfigs, getDiagramTypeLabel } from '../constants/app';
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

const DIAGRAM_TYPE_ACCENT: Record<string, string> = {
  flowchart: 'from-emerald-400/20 to-teal-400/10 dark:from-emerald-500/15 dark:to-teal-500/10',
  sequence: 'from-violet-400/20 to-purple-400/10 dark:from-violet-500/15 dark:to-purple-500/10',
  architecture: 'from-brand-400/20 to-cyan-400/10 dark:from-brand-500/15 dark:to-cyan-500/10',
  mindmap: 'from-amber-400/20 to-orange-400/10 dark:from-amber-500/15 dark:to-orange-500/10',
  er: 'from-rose-400/20 to-pink-400/10 dark:from-rose-500/15 dark:to-pink-500/10',
  class: 'from-indigo-400/20 to-blue-400/10 dark:from-indigo-500/15 dark:to-blue-500/10',
};
const DEFAULT_ACCENT = 'from-slate-400/15 to-slate-300/10 dark:from-slate-500/15 dark:to-slate-600/10';

const getCardAccent = (type: string) => DIAGRAM_TYPE_ACCENT[type] || DEFAULT_ACCENT;

const normalizeProjectScope = (value: string | null): ProjectScope => (
  value === 'favorites' ? 'favorites' : 'all'
);

const getProjectKeyFromDiagram = (item: RecentDiagram) => item.project_id || item.request_id;

const getRecentDiagramIdentity = (item: RecentDiagram) => (
  `${getProjectKeyFromDiagram(item)}:${item.snapshot_id || item.diagram_id || item.request_id}`
);

const getProjectDomId = (projectId: string) => projectId.replace(/[^A-Za-z0-9_-]/g, '-') || 'project';
const getDesktopProjectDetailId = (projectId: string) => `project-detail-${getProjectDomId(projectId)}`;
const getMobileProjectDetailId = (projectId: string) => `mobile-project-detail-${getProjectDomId(projectId)}`;

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
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [projectScope, setProjectScope] = useState<ProjectScope>(() => requestedProjectScope);
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [mobileExpandedProjectId, setMobileExpandedProjectId] = useState<string | null>(null);
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
      setSelectedProjectId(null);
      setMobileExpandedProjectId(null);
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

  const projectNameMap = useMemo(
    () => new Map(projectCards.map((project) => [project.projectId, project.projectName])),
    [projectCards],
  );

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
      setSelectedProjectId(null);
      setMobileExpandedProjectId(null);
      return;
    }

    const exists = filteredProjectCards.some((item) => item.projectId === selectedProjectId);
    if (!exists) {
      setSelectedProjectId(filteredProjectCards[0].projectId);
    }

    const mobileExpandedExists = mobileExpandedProjectId === null
      || filteredProjectCards.some((item) => item.projectId === mobileExpandedProjectId);
    if (!mobileExpandedExists) {
      setMobileExpandedProjectId(null);
    }
  }, [filteredProjectCards, mobileExpandedProjectId, selectedProjectId]);

  const selectedProject = useMemo(
    () => filteredProjectCards.find((item) => item.projectId === selectedProjectId) ?? null,
    [filteredProjectCards, selectedProjectId],
  );
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
    const recent = recentEvolutions.slice(0, 4).map((item) => getFileTitle(item));
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

  const handleProjectDetailsClick = useCallback((project: ProjectCard) => {
    setSelectedProjectId(project.projectId);
    setMobileExpandedProjectId(project.projectId);
  }, []);

  const handleMobileProjectDetailsClick = useCallback((projectId: string) => {
    setSelectedProjectId(projectId);
    setMobileExpandedProjectId((current) => (current === projectId ? null : projectId));
  }, []);

  const formatProjectCount = useCallback((count: number) => (
    `${count} ${t(count === 1 ? 'dashboard.projectCountSingular' : 'dashboard.projectCountPlural')}`
  ), [t]);

  const loadedProjectsStatus = useMemo(() => {
    const visible = formatProjectCount(filteredProjectCards.length);
    const loaded = formatProjectCount(projectCards.length);
    const availability = hasMoreProjects
      ? t('dashboard.moreProjectsAvailable')
      : t('dashboard.allProjectsLoaded');
    return `${t('dashboard.loadedProjectsVisible')} ${visible} · ${t('dashboard.loadedProjectsStatus')} ${loaded} · ${availability}`;
  }, [
    filteredProjectCards.length,
    formatProjectCount,
    hasMoreProjects,
    projectCards.length,
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
    <div className="bg-soft-mesh dark:bg-soft-mesh-dark min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      <Header />

      <main id="main-content" className="mx-auto w-full max-w-[1400px] px-4 py-7 sm:px-6 lg:px-8">
        {/* ── Page Header ── */}
        <section className="mb-8 hero-fade-up">
          <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100 sm:text-3xl">
            {t('nav.projects')}
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {isInitialLoading
              ? '\u00A0'
              : projectCards.length > 0
                ? formatProjectCount(projectCards.length)
                : loadStatus === 'failed'
                  ? t('dashboard.loadFailedTitle')
                  : t('dashboard.subtitleEmpty')}
          </p>
        </section>

        {/* ── Toolbar ── */}
        <section className="relative z-30 mb-6 hero-fade-up hero-delay-1">{/* hero-fade-up keeps a transform after it finishes, so this section is
            its own stacking context and the search-suggestion panel's z-30 only
            applies inside it. Without an explicit order here, later sections
            painted over the open panel. */}
          <div className="flex flex-wrap items-center gap-3">
            {/* Scope tabs */}
            <div
              role="tablist"
              aria-label={t('dashboard.projectSpaces')}
              className="custom-scrollbar flex w-full max-w-full items-center gap-1 overflow-x-auto rounded-xl border border-slate-200/70 bg-white/70 p-1 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 sm:w-auto sm:gap-1.5"
            >
              {projectScopeTabs.map((tab) => {
                const Icon = tab.icon;
                const isActive = projectScope === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => handleProjectScopeChange(tab.id)}
                    className={`tap-target inline-flex min-h-9 flex-1 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-all sm:flex-none sm:px-3.5 ${
                      isActive
                        ? 'bg-white text-brand-700 shadow-e1 dark:bg-slate-800 dark:text-brand-300'
                        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
                  >
                    <Icon className={`h-3.5 w-3.5 ${isActive && tab.id === 'favorites' ? 'fill-current' : ''}`} />
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {/* Search */}
            <div className="relative min-w-0 w-full sm:min-w-[240px] sm:w-auto sm:flex-1 max-w-md">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" />
              <input
                value={searchKeyword}
                onChange={(event) => handleSearchKeywordChange(event.target.value)}
                onFocus={() => setIsSearchFocused(true)}
                onBlur={() => window.setTimeout(() => setIsSearchFocused(false), 120)}
                placeholder={t('dashboard.searchPlaceholder')}
                aria-label={t('dashboard.searchPlaceholder')}
                className="h-11 w-full rounded-xl border border-slate-200/70 bg-white/70 pl-9 pr-3 text-sm text-slate-700 outline-none backdrop-blur-xl transition focus:border-brand-300 focus:bg-white/80 focus-visible:ring-2 focus-visible:ring-brand-200 dark:border-white/10 dark:bg-slate-900/60 dark:text-slate-200 dark:placeholder:text-slate-500 dark:focus:border-brand-400 dark:focus:bg-slate-900/80"
              />

              {isSearchFocused && (
                <div className="absolute left-0 right-0 top-12 z-30 surface-overlay rounded-2xl p-4 shadow-e4 dark:shadow-e4-dark">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dashboard.searchSuggestionsRecent')}</p>
                  <div className="mb-3 flex flex-wrap gap-2">
                    {searchSuggestions.recent.length > 0 ? searchSuggestions.recent.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => handleSearchKeywordChange(item)}
                        className="rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs text-slate-600 backdrop-blur-sm transition hover:border-brand-300 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                      >
                        {item}
                      </button>
                    )) : (
                      <span className="text-xs text-slate-500 dark:text-slate-400">-</span>
                    )}
                  </div>

                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dashboard.searchSuggestionsHot')}</p>
                  <div className="flex flex-wrap gap-2">
                    {searchSuggestions.hot.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => handleSearchKeywordChange(item)}
                        className="rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs text-slate-600 backdrop-blur-sm transition hover:border-brand-300 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Primary action + Sort + View controls */}
            <div className="ml-0 grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:ml-auto sm:flex sm:w-auto sm:flex-wrap">
              <button
                type="button"
                onClick={() => navigate('/workspace')}
                className={`${
                  // While the list is empty the empty state below owns the
                  // primary action, so this one steps down to secondary rather
                  // than putting two identical blue buttons on the same screen.
                  hasLoadedProjects
                    ? 'btn-primary'
                    : 'btn-muted dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300'
                } min-h-11 justify-center gap-1.5 text-xs sm:order-none sm:w-auto`}
              >
                <Plus className="h-3.5 w-3.5" />
                {t('dashboard.newProject')}
              </button>

              <div
                className="custom-scrollbar col-span-2 row-start-2 flex min-w-0 max-w-full items-center gap-1 overflow-x-auto rounded-xl border border-slate-200/70 bg-white/70 p-1 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 sm:col-span-1 sm:row-start-auto"
                role="group"
                aria-label={t('dashboard.sortByLabel')}
              >
                <ArrowUpDown className="ml-1.5 h-3.5 w-3.5 shrink-0 text-slate-500 dark:text-slate-400 sm:ml-2" />
                {sortOptions.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setSortMode(option.id)}
                    aria-pressed={sortMode === option.id}
                    className={`tap-target min-h-9 flex-1 shrink-0 rounded-lg px-2.5 text-xs font-medium transition-all sm:flex-none ${
                      sortMode === option.id
                        ? 'bg-white text-brand-700 shadow-e1 dark:bg-slate-800 dark:text-brand-300'
                        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
                  >
                    <span className="sm:hidden">{option.shortLabel}</span>
                    <span className="hidden sm:inline">{option.label}</span>
                  </button>
                ))}
              </div>

              <div
                className="flex items-center justify-self-end gap-0.5 rounded-xl border border-slate-200/70 bg-white/70 p-1 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60"
                role="group"
                aria-label={t('dashboard.viewModeLabel')}
              >
                <button
                  type="button"
                  onClick={() => setViewMode('grid')}
                  className={`tap-target flex h-9 w-9 items-center justify-center rounded-lg transition-all ${viewMode === 'grid' ? 'bg-white text-slate-700 shadow-e1 dark:bg-slate-800 dark:text-slate-100' : 'text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300'}`}
                  aria-label={t('dashboard.viewGrid')}
                  aria-pressed={viewMode === 'grid'}
                >
                  <Grid3X3 className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('list')}
                  className={`tap-target flex h-9 w-9 items-center justify-center rounded-lg transition-all ${viewMode === 'list' ? 'bg-white text-slate-700 shadow-e1 dark:bg-slate-800 dark:text-slate-100' : 'text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300'}`}
                  aria-label={t('dashboard.viewList')}
                  aria-pressed={viewMode === 'list'}
                >
                  <List className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
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
                className="btn-muted dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
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
          <section role="alert" className="py-12 hero-fade-up hero-delay-2">
            <div className="mx-auto flex max-w-xl flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-red-200/80 bg-red-50 text-red-600 shadow-sm dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                <CircleAlert className="h-7 w-7" />
              </div>
              <h2 className="mt-5 font-display text-xl font-bold text-slate-900 dark:text-slate-100">{t('dashboard.loadFailedTitle')}</h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500 dark:text-slate-400">{t('dashboard.loadFailedEmptyHint')}</p>
              <div className="mt-5 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={() => { void loadRecent(); }}
                  className="btn-primary min-h-11 gap-2"
                >
                  {t('common.retry')}
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/workspace')}
                  className="btn-muted min-h-11 gap-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                >
                  <Plus className="h-4 w-4" />
                  {t('dashboard.newProject')}
                </button>
              </div>
            </div>
          </section>
        ) : isFavoritesEmptyState ? (
          <section className="py-12 hero-fade-up hero-delay-2">
            <div className="mx-auto flex max-w-xl flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-amber-200/80 bg-amber-50 text-amber-600 shadow-sm dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
                <Star className="h-7 w-7" />
              </div>
              <h2 className="mt-5 font-display text-xl font-bold text-slate-900 dark:text-slate-100">{t('dashboard.noFavoriteProjects')}</h2>
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
                    className="btn-primary min-h-11 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : t('dashboard.loadMoreProjects')}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleProjectScopeChange('all')}
                  className={`${hasMoreProjects ? 'btn-muted dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300' : 'btn-primary'} min-h-11`}
                >
                  {t('dashboard.tabAllProjects')}
                </button>
              </div>
            </div>
          </section>
        ) : showFilteredEmptyState ? (
          <section className="py-12 hero-fade-up hero-delay-2">
            <div className="mx-auto flex max-w-xl flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-slate-200/80 bg-gradient-to-br from-slate-50 via-white to-brand-50 text-slate-500 shadow-sm dark:border-slate-700 dark:from-slate-800 dark:via-slate-900 dark:to-brand-500/10 dark:text-slate-300">
                <Search className="h-7 w-7" />
              </div>
              <h2 className="mt-5 font-display text-xl font-bold text-slate-900 dark:text-slate-100">{t('dashboard.noSearchResults')}</h2>
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
                  className="btn-primary min-h-11 gap-2"
                >
                  {t('dashboard.clearSearch')}
                </button>
                {projectScope !== 'all' && (
                  <button
                    type="button"
                    onClick={handleClearFilters}
                    className="btn-muted min-h-11 gap-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                  >
                    {t('dashboard.showAllProjects')}
                  </button>
                )}
                {hasMoreProjects ? (
                  <button
                    type="button"
                    onClick={handleLoadMoreProjects}
                    disabled={!canLoadMoreProjects}
                    className="btn-muted min-h-11 gap-2 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                  >
                    {isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : t('dashboard.loadMoreProjects')}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => navigate('/workspace')}
                    className="btn-muted min-h-11 gap-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                  >
                    <Plus className="h-4 w-4" />
                    {t('dashboard.newProject')}
                  </button>
                )}
              </div>
            </div>
          </section>
        ) : filteredProjectCards.length === 0 ? (
          <section className="py-10 hero-fade-up hero-delay-2">
            <div className="mx-auto flex max-w-lg flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-brand-200/80 bg-gradient-to-br from-brand-50 via-white to-indigo-50 text-brand-500 shadow-e1 dark:border-brand-500/30 dark:from-brand-500/20 dark:via-slate-900 dark:to-indigo-500/15 dark:text-brand-400">
                <FolderKanban className="h-7 w-7" />
              </div>
              <h2 className="mt-5 font-display text-xl font-bold text-slate-900 dark:text-slate-100">{t('dashboard.emptyEmotionalTitle')}</h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-500 dark:text-slate-400">{t('dashboard.emptyEmotionalHint')}</p>
              <button
                type="button"
                onClick={() => navigate('/workspace')}
                className="btn-primary mt-5 min-h-11 gap-2"
              >
                <Plus className="h-4 w-4" />
                {t('dashboard.emptyPrimaryAction')}
              </button>
            </div>

            {/* Template quick-starts */}
            <div className="mt-10">
              <p className="mb-4 text-center text-sm font-semibold text-slate-600 dark:text-slate-300">{t('dashboard.emptyGuide')}</p>
              <div className="grid gap-4 sm:grid-cols-3">
                {[
                  {
                    title: t('dashboard.templateAutomatedDesc'),
                    prompt: t('dashboard.templateAutomatedPrompt'),
                    diagramType: 'automated' as DiagramType,
                    Icon: Sparkles,
                    color: 'from-brand-400/15 via-white/60 to-white/50 dark:from-brand-500/10 dark:via-slate-900/50 dark:to-slate-900/40',
                    border: 'border-brand-200/60 dark:border-brand-500/25',
                    iconTone: 'text-brand-600 dark:text-brand-300',
                  },
                  {
                    title: t('dashboard.templateFlowDesc'),
                    prompt: t('dashboard.templateFlowPrompt'),
                    diagramType: 'flow' as DiagramType,
                    Icon: GitBranch,
                    color: 'from-emerald-400/15 via-white/60 to-white/50 dark:from-emerald-500/10 dark:via-slate-900/50 dark:to-slate-900/40',
                    border: 'border-emerald-200/60 dark:border-emerald-500/25',
                    iconTone: 'text-emerald-600 dark:text-emerald-300',
                  },
                  {
                    title: t('dashboard.templateSequenceDesc'),
                    prompt: t('dashboard.templateSequencePrompt'),
                    diagramType: 'sequence' as DiagramType,
                    Icon: List,
                    color: 'from-violet-400/15 via-white/60 to-white/50 dark:from-violet-500/10 dark:via-slate-900/50 dark:to-slate-900/40',
                    border: 'border-violet-200/60 dark:border-violet-500/25',
                    iconTone: 'text-violet-600 dark:text-violet-300',
                  },
                ].map((tpl) => {
                  const TemplateIcon = tpl.Icon;
                  const tag = getDiagramTypeLabel(tpl.diagramType, t);
                  return (
                    <button
                      key={tpl.diagramType}
                      type="button"
                      onClick={() => {
                        const llmConfigId = defaultConfigs[0]?.id ?? 'default';
                        navigate('/workspace', {
                          state: {
                            initialPrompt: tpl.prompt,
                            initialDiagramType: tpl.diagramType,
                            initialLlmConfigId: llmConfigId,
                            initialCanvasMode: 'excalidraw',
                            initialSource: 'dashboard',
                            preflightGeneration: true,
                            preflightKind: 'startup',
                          },
                        });
                      }}
                      className={`group relative overflow-hidden rounded-2xl border ${tpl.border} bg-gradient-to-br ${tpl.color} p-5 text-left backdrop-blur-xl transition-all hover:shadow-lg hover:-translate-y-0.5`}
                    >
                      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-white/70 bg-white/70 shadow-sm backdrop-blur-sm dark:border-white/10 dark:bg-slate-950/35 ${tpl.iconTone}`}>
                        <TemplateIcon className="h-5 w-5" />
                      </div>
                      <span className="mb-1 block text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{tag}</span>
                      <p className="text-sm font-medium text-slate-700 dark:text-slate-200 line-clamp-2">{tpl.title}</p>
                      <span className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-brand-600 dark:text-brand-400 group-hover:underline">
                        {t('dashboard.startFromTemplate')}
                        <ArrowRight className="h-3 w-3" />
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>
        ) : (
          <div className="hero-fade-up hero-delay-2">
            {/* ── Project Cards ── */}
            <section className="mb-8">
              <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
                {t('dashboard.projectSpaces')}
              </h2>

              <div className={viewMode === 'grid' ? 'grid gap-5 sm:grid-cols-2 lg:grid-cols-3' : 'space-y-3'}>
                {filteredProjectCards.map((project, index) => {
                  const isSelected = selectedProjectId === project.projectId;
                  const isMobileExpanded = mobileExpandedProjectId === project.projectId;
                  const isFavorite = favoriteProjectIds.includes(project.projectId);
                  const accent = getCardAccent(project.latestDiagramType);
                  const desktopDetailId = getDesktopProjectDetailId(project.projectId);
                  const mobileDetailId = getMobileProjectDetailId(project.projectId);
                  const mobileVisibleDiagrams = project.diagrams.slice(0, 3);
                  const hiddenDiagramCount = Math.max(0, project.diagramCount - mobileVisibleDiagrams.length);

                  return (
                    <article
                      key={project.projectId}
                      style={{ animationDelay: `${Math.min(index * 40, 200)}ms` }}
                      className={`group relative overflow-hidden rounded-2xl border bg-white dark:bg-slate-900 transition-all duration-200 hero-fade-up ${
                        isSelected
                          ? 'border-brand-300/80 bg-white/70 shadow-[0_8px_30px_rgba(49,141,255,0.12)] dark:border-brand-500/50 dark:bg-slate-900/70 dark:shadow-[0_8px_30px_rgba(49,141,255,0.08)]'
                          : 'border-slate-200 hover:border-brand-300 hover:shadow-e2 dark:border-slate-700 dark:hover:border-brand-500'
                      }`}
                    >
                      {/* Gradient accent bar */}
                      <div className={`h-1.5 bg-gradient-to-r ${accent}`} />

                      <button
                        type="button"
                        onClick={() => handleProjectCardClick(project)}
                        className="block w-full cursor-pointer px-4 pb-4 pt-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-300 dark:focus-visible:ring-brand-500"
                        aria-label={`${t('dashboard.actionOpenProject')}: ${project.projectName}. ${formatDiagramCount(project.diagramCount)}. ${getDiagramTypeLabel(project.latestDiagramType, t)}.`}
                      >
                        {viewMode === 'grid' && <div className="mb-4 h-36 overflow-hidden rounded-lg border border-slate-100 bg-white">
                          <RecentProjectPreview project={project.diagrams[0]} title={project.projectName} unavailableLabel={t('home.previewUnavailable')} />
                        </div>}
                        <div className="flex items-start gap-3 pr-12">
                          <div className="min-w-0 flex-1">
                            <p className="line-clamp-1 text-sm font-semibold text-slate-800 dark:text-slate-100">{project.projectName}</p>
                          </div>
                        </div>

                        <div className="mt-3 flex flex-wrap items-center gap-1.5">
                          <span className="rounded-md bg-brand-500/10 px-2 py-0.5 text-xs font-semibold text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
                            {formatDiagramCount(project.diagramCount)}
                          </span>
                          <span className="min-w-0 max-w-[9rem] truncate rounded-md bg-slate-500/10 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-500/15 dark:text-slate-400">
                            {getDiagramTypeLabel(project.latestDiagramType, t)}
                          </span>
                        </div>

                        <span className="mt-3 hidden items-center gap-1 text-xs font-semibold text-brand-600 transition group-hover:underline dark:text-brand-300 sm:inline-flex">
                          {t('dashboard.actionOpenProject')}
                          <ArrowRight className="h-3.5 w-3.5" />
                        </span>
                        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400 sm:hidden">{formatTime(project.latestEditedAt)}</p>
                      </button>

                      <button
                        type="button"
                        onClick={() => toggleFavoriteProject(project.projectId)}
                        className={`absolute right-3 top-4 z-10 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-amber-500 dark:focus-visible:ring-offset-slate-950 ${
                          isFavorite
                            ? 'text-amber-500 hover:text-amber-600 dark:text-amber-400 dark:hover:text-amber-300'
                            : 'text-slate-300 opacity-100 hover:text-amber-500 dark:text-slate-600 dark:hover:text-amber-400 bg-white/90 dark:bg-slate-900/90'
                        }`}
                        aria-label={isFavorite ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')}
                        aria-pressed={isFavorite}
                        title={isFavorite ? t('dashboard.unmarkFavorite') : t('dashboard.markFavorite')}
                      >
                        <Star className={`h-4 w-4 ${isFavorite ? 'fill-current' : ''}`} />
                      </button>

                      <div className="hidden border-t border-slate-200/60 px-4 pb-4 pt-3 dark:border-slate-700/50 sm:flex sm:items-center sm:justify-between">
                        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                          {formatTime(project.latestEditedAt)}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleProjectDetailsClick(project)}
                          aria-expanded={isSelected}
                          aria-controls={isSelected ? desktopDetailId : undefined}
                          aria-label={`${t('dashboard.actionReviewProject')}: ${project.projectName}`}
                          className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-brand-200 hover:bg-brand-50/70 hover:text-brand-700 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-brand-500/45 dark:hover:bg-brand-500/10 dark:hover:text-brand-200 dark:focus-visible:ring-offset-slate-950"
                        >
                          <List className="h-3.5 w-3.5" />
                          {t('dashboard.actionReviewProject')}
                        </button>
                      </div>

                      <div className="border-t border-slate-200/60 px-4 pb-4 pt-3 dark:border-slate-700/50 sm:hidden">
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            onClick={() => handleMobileProjectDetailsClick(project.projectId)}
                            aria-expanded={isMobileExpanded}
                            aria-controls={isMobileExpanded ? mobileDetailId : undefined}
                            aria-label={`${t('dashboard.actionReviewProject')}: ${project.projectName}`}
                            className="inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-brand-200 hover:bg-brand-50/70 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-brand-500/45 dark:hover:bg-brand-500/10 dark:hover:text-brand-200 dark:focus-visible:ring-offset-slate-950"
                          >
                            <List className="mr-1.5 h-3.5 w-3.5" />
                            {t('dashboard.actionReviewProject')}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenProject(project.diagrams[0])}
                            aria-label={`${t('dashboard.actionOpenProject')}: ${project.projectName}`}
                            className="btn-primary min-h-11 gap-1.5 text-xs"
                          >
                            {t('dashboard.actionOpenProject')}
                          </button>
                        </div>

                        {isMobileExpanded && (
                          <div
                            id={mobileDetailId}
                            data-testid="mobile-project-detail"
                            className="mt-3 border-t border-slate-200/70 pt-3 text-slate-700 dark:border-slate-700/50 dark:text-slate-200"
                          >
                            <div className="mb-2 flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="text-xs font-semibold text-slate-800 dark:text-slate-100">
                                  {t('dashboard.mobileProjectDetailTitle')}
                                </p>
                                <p className="mt-1 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
                                  {t('dashboard.mobileProjectDetailHint')}
                                </p>
                              </div>
                              <button
                                type="button"
                                onClick={() => handleCopyProjectId(project.projectId)}
                                aria-label={t('dashboard.actionCopyProjectId')}
                                className="inline-flex min-h-10 shrink-0 items-center justify-center rounded-lg border border-slate-200/80 bg-white/70 px-2.5 py-1.5 text-xs font-semibold text-slate-500 transition hover:border-brand-200 hover:text-brand-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:border-slate-700 dark:bg-slate-950/30 dark:text-slate-300 dark:hover:border-brand-500/45 dark:hover:text-brand-200"
                              >
                                <Copy className="h-3.5 w-3.5" />
                              </button>
                            </div>

                            <div className="divide-y divide-slate-200/60 dark:divide-slate-700/50">
                              {mobileVisibleDiagrams.map((item) => (
                                <button
                                  key={item.snapshot_id || item.diagram_id}
                                  type="button"
                                  onClick={() => handleOpenProject(item)}
                                  className="flex min-h-11 w-full items-center gap-3 rounded-lg px-1 py-2 text-left transition hover:bg-white/65 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:hover:bg-slate-950/35"
                                >
                                  <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${getCardAccent(item.diagram_type)}`}>
                                    <FolderKanban className="h-4 w-4 text-slate-500 dark:text-slate-300" />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <p className="line-clamp-1 text-xs font-semibold text-slate-700 dark:text-slate-100">
                                      {getFileTitle(item)}
                                    </p>
                                    <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                                      {getDiagramTypeLabel(item.diagram_type, t)} · {formatTime(getActivityTime(item))}
                                    </p>
                                  </div>
                                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-500 dark:text-slate-400" />
                                </button>
                              ))}
                            </div>

                            {hiddenDiagramCount > 0 && (
                              <p className="mt-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                                {t('dashboard.mobileProjectMoreSnapshots').replace('{count}', String(hiddenDiagramCount))}
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>

              <div className="mt-5 rounded-2xl border border-white/60 bg-white/45 px-4 py-3 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/45">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                      {isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : loadedProjectsStatus}
                    </p>
                    {loadMoreError && (
                      <p role="alert" className="mt-1 text-xs font-medium text-red-600 dark:text-red-300">
                        {loadMoreError}
                      </p>
                    )}
                  </div>

                  {hasMoreProjects && (
                    <button
                      type="button"
                      onClick={handleLoadMoreProjects}
                      disabled={!canLoadMoreProjects}
                      className="btn-muted min-h-11 shrink-0 justify-center disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                    >
                      {isLoadingMoreProjects ? t('dashboard.loadingMoreProjects') : t('dashboard.loadMoreProjects')}
                    </button>
                  )}
                </div>
              </div>
            </section>

            {/* ── Selected Project Detail ── */}
            {selectedProject && (
              <section
                id={getDesktopProjectDetailId(selectedProject.projectId)}
                className="mb-8 hidden overflow-hidden rounded-2xl border border-white/60 bg-white/55 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/55 sm:block"
              >
                <div className="flex flex-col gap-3 border-b border-slate-200/60 px-4 py-4 dark:border-slate-700/50 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                      {selectedProject.projectName}
                    </h3>
                    <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                      {formatDiagramCount(selectedProject.diagramCount)} · /{selectedProject.projectId.slice(0, 12)}
                    </p>
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <button
                      type="button"
                      onClick={() => handleCopyProjectId(selectedProject.projectId)}
                      aria-label={t('dashboard.actionCopyProjectId')}
                      className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-white/60 bg-white/60 px-3 py-2 text-xs font-medium text-slate-600 backdrop-blur-sm transition hover:bg-white hover:text-brand-600 dark:border-white/10 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-brand-300"
                    >
                      <Copy className="h-3.5 w-3.5" />
                      {t('dashboard.actionCopyProjectId')}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleOpenProject(selectedProject.diagrams[0])}
                      className="btn-primary min-h-11 gap-1.5 text-xs"
                    >
                      {t('dashboard.actionOpenProject')}
                    </button>
                  </div>
                </div>

                {selectedProject.diagramCount > selectedProject.diagrams.length && (
                  <div className="border-b border-slate-200/60 bg-brand-50/35 px-5 py-3 text-xs leading-relaxed text-slate-500 dark:border-slate-700/50 dark:bg-brand-500/5 dark:text-slate-400">
                    {t('dashboard.projectHistoryHint')}
                  </div>
                )}

                <div className="divide-y divide-slate-200/50 dark:divide-slate-700/40">
                  {selectedProject.diagrams.map((item) => (
                    <button
                      key={item.snapshot_id || item.diagram_id}
                      type="button"
                      onClick={() => handleOpenProject(item)}
                      className="flex w-full items-center gap-4 px-5 py-3 text-left transition hover:bg-brand-50/30 dark:hover:bg-brand-500/5"
                    >
                      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${getCardAccent(item.diagram_type)}`}>
                        <FolderKanban className="h-4 w-4 text-slate-500 dark:text-slate-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-1 text-sm font-medium text-slate-700 dark:text-slate-200">{getFileTitle(item)}</p>
                        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                          {getDiagramTypeLabel(item.diagram_type, t)} · {formatTime(getActivityTime(item))}
                        </p>
                      </div>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-300 dark:text-slate-600" />
                    </button>
                  ))}
                </div>
              </section>
            )}

            {/* ── Recent Evolutions ── */}
            <section className="overflow-hidden rounded-2xl border border-white/60 bg-white/55 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/55">
              <div className="border-b border-slate-200/60 px-5 py-4 dark:border-slate-700/50">
                <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('dashboard.recentEvolutions')}</h3>
              </div>
              <div className="divide-y divide-slate-200/50 dark:divide-slate-700/40">
                {recentEvolutions.map((item) => {
                  const projectId = getProjectKeyFromDiagram(item);
                  const projectTitle = projectNameMap.get(projectId) || `${t('dashboard.untitledProject')} ${projectId.slice(0, 8)}`;

                  return (
                    <button
                      key={item.snapshot_id || item.diagram_id}
                      type="button"
                      onClick={() => navigate('/workspace', { state: { pendingLoadProject: item } })}
                      className="flex w-full items-center gap-4 px-5 py-3 text-left transition hover:bg-brand-50/30 dark:hover:bg-brand-500/5"
                    >
                      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${getCardAccent(item.diagram_type)}`}>
                        <FolderKanban className="h-4 w-4 text-slate-500 dark:text-slate-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-1 text-sm font-medium text-slate-700 dark:text-slate-200">{getFileTitle(item)}</p>
                        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                          {t('dashboard.belongsToProject')} {projectTitle}
                        </p>
                      </div>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-300 dark:text-slate-600" />
                    </button>
                  );
                })}
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
};
