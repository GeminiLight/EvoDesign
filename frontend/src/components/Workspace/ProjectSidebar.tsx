import { shouldSubmitOnEnter } from '../../utils/keyboard';
import { snapshotSourceKey } from '../../utils/projectHistory';
import { AlertTriangle, Check, PanelLeftClose, Dna, FolderKanban, History, List, Loader2, LogIn, Pencil, Plus, RefreshCcw, Save } from 'lucide-react';
import type { DiagramResponse, ProjectSnapshotItem } from '../../types/api';
import type { RecentCanvasLibrary, RecentDiagram } from '../../types/app';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { WorkspaceSaveStatus } from '../../hooks/useDiagramSync';
import { detectCanvasPayloadKind } from '../../utils/app';

type WorkspaceLoadStatus = 'idle' | 'loading' | 'ready' | 'failed';

export interface ProjectSidebarProps {
  onToggleCollapse: () => void;
  projectName: string;
  isEditingProjectName: boolean;
  projectNameDraft: string;
  onProjectNameDraftChange: (value: string) => void;
  onStartEdit: () => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  projectNameInputRef: React.RefObject<HTMLInputElement | null>;
  visibleItemsCount: number;
  isViewingProjectHistory: boolean;
  canViewProjectHistory: boolean;
  displayedProjectSnapshots: ProjectSnapshotItem[];
  displayedRecentDiagrams: RecentDiagram[];
  preview: DiagramResponse | null;
  onSelectSnapshot: (snapshot: ProjectSnapshotItem) => void;
  onSelectRecentDiagram: (item: RecentDiagram) => void;
  onShowProjectHistory: () => void;
  onShowRecentDiagrams: () => void;
  onOpenCreateDialog: () => void;
  onSaveSnapshot?: () => void;
  onResolveSaveConflict?: () => void;
  onRecoverMissingProject?: () => void;
  onReauth?: () => void;
  manualSaveStatus?: WorkspaceSaveStatus;
  hasUnsavedChanges?: boolean;
  recentLoadStatus?: WorkspaceLoadStatus;
  projectHistoryLoadStatus?: WorkspaceLoadStatus;
  onRetryRecentLoad?: () => void;
  onRetryProjectHistoryLoad?: () => void;
  isInteractionDisabled?: boolean;
  interactionDisabledReason?: string;
  generatingDiagramId?: string | null;
  hasProjectDna?: boolean;
  onOpenProjectDna?: () => void;
}

export function ProjectSidebar({
  onToggleCollapse,
  projectName,
  isEditingProjectName,
  projectNameDraft,
  onProjectNameDraftChange,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  projectNameInputRef,
  visibleItemsCount,
  isViewingProjectHistory,
  canViewProjectHistory,
  displayedProjectSnapshots,
  displayedRecentDiagrams,
  preview,
  onSelectSnapshot,
  onSelectRecentDiagram,
  onShowProjectHistory,
  onShowRecentDiagrams,
  onOpenCreateDialog,
  onSaveSnapshot,
  onResolveSaveConflict,
  onRecoverMissingProject,
  onReauth,
  manualSaveStatus = 'idle',
  hasUnsavedChanges = false,
  recentLoadStatus = 'idle',
  projectHistoryLoadStatus = 'idle',
  onRetryRecentLoad,
  onRetryProjectHistoryLoad,
  isInteractionDisabled = false,
  interactionDisabledReason,
  generatingDiagramId,
  hasProjectDna,
  onOpenProjectDna,
}: ProjectSidebarProps) {
  const { t } = useLanguage();
  const panelId = 'workspace-project-sidebar-panel';
  const listId = 'workspace-project-sidebar-list';
  const focusRingClass = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-950';
  const getCurrentSuffix = (isCurrent: boolean) => (isCurrent ? `, ${t('app.current')}` : '');
  const projectDnaScope = hasProjectDna ? t('workspace.dnaProject') : t('workspace.dnaGlobal');
  const canSaveSnapshot = Boolean(preview?.projectId && onSaveSnapshot);
  const isSavingSnapshot = manualSaveStatus === 'saving';
  const isSaveFailed = manualSaveStatus === 'failed';
  const isSaveSaved = manualSaveStatus === 'saved';
  const isSaveConflict = manualSaveStatus === 'conflict';
  const isSaveAuthExpired = manualSaveStatus === 'authExpired';
  const isSaveMissingProject = manualSaveStatus === 'missingProject';
  const canRequestReauth = Boolean(isSaveAuthExpired && onReauth);
  const canResolveConflict = Boolean(isSaveConflict && onResolveSaveConflict);
  const canRecoverMissingProject = Boolean(isSaveMissingProject && onRecoverMissingProject);
  const isSaveUnavailable = !canSaveSnapshot && !canRequestReauth && !canResolveConflict && !canRecoverMissingProject;
  const isSaveBlocked = (isSaveConflict && !canResolveConflict) || (isSaveMissingProject && !canRecoverMissingProject);
  const isSaveClean = canSaveSnapshot
    && !hasUnsavedChanges
    && !isSavingSnapshot
    && !isSaveFailed
    && !isSaveConflict
    && !isSaveAuthExpired
    && !isSaveMissingProject
    && !isSaveSaved;
  const isSaveReadonly = isSaveClean || (canSaveSnapshot && !hasUnsavedChanges && isSaveSaved);
  const saveButtonLabel = isSavingSnapshot
    ? t('workspace.savingChanges')
    : isSaveConflict
      ? t('workspace.saveConflictAction')
      : isSaveAuthExpired
        ? t('workspace.saveAuthExpiredAction')
        : isSaveMissingProject
          ? t('workspace.saveProjectMissingAction')
    : isSaveUnavailable
      ? t('workspace.noDiagramToSave')
    : isSaveFailed
      ? t('workspace.retrySave')
    : isSaveSaved
      ? t('workspace.changesSaved')
      : isSaveClean
        ? t('workspace.noChangesToSave')
        : t('workspace.saveChanges');
  const saveButtonToneClass = isSaveConflict || isSaveAuthExpired || isSaveMissingProject
    ? 'border-amber-200 bg-amber-50/80 text-amber-800 hover:border-amber-300 hover:bg-amber-50 dark:border-amber-500/35 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:border-amber-400/50 dark:hover:bg-amber-500/15'
    : isSaveFailed
    ? 'border-red-200 bg-red-50/80 text-red-700 hover:border-red-300 hover:bg-red-50 dark:border-red-500/35 dark:bg-red-500/10 dark:text-red-200 dark:hover:border-red-400/50 dark:hover:bg-red-500/15'
    : isSaveSaved
      ? 'border-emerald-200 bg-emerald-50/80 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-50 dark:border-emerald-500/35 dark:bg-emerald-500/10 dark:text-emerald-200 dark:hover:border-emerald-400/50 dark:hover:bg-emerald-500/15'
      : 'border-slate-200 bg-white/65 text-slate-600 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400 dark:hover:border-brand-500/50 dark:hover:text-brand-300';
  const SaveStatusIcon = isSavingSnapshot
    ? Loader2
    : isSaveAuthExpired
      ? LogIn
      : isSaveConflict || isSaveMissingProject
        ? AlertTriangle
        : isSaveFailed
          ? RefreshCcw
          : isSaveSaved
            ? Check
            : isSaveClean
              ? Check
            : Save;
  const handleSaveButtonClick = () => {
    if (isInteractionDisabled) {
      return;
    }

    if (isSaveConflict && onResolveSaveConflict) {
      onResolveSaveConflict();
      return;
    }
    if (isSaveMissingProject && onRecoverMissingProject) {
      onRecoverMissingProject();
      return;
    }
    if (isSaveAuthExpired && onReauth) {
      onReauth();
      return;
    }
    onSaveSnapshot?.();
  };
  const saveButtonDisabled = isInteractionDisabled || isSavingSnapshot || isSaveBlocked || isSaveReadonly || isSaveUnavailable;
  const currentListStatus = isViewingProjectHistory ? projectHistoryLoadStatus : recentLoadStatus;
  const currentRetryHandler = isViewingProjectHistory ? onRetryProjectHistoryLoad : onRetryRecentLoad;
  const currentListLabel = isViewingProjectHistory
    ? t('workspace.projectHistoryTab')
    : t('workspace.recentDiagramsTab');
  const isListLoading = currentListStatus === 'loading';
  const isListLoadFailed = currentListStatus === 'failed';
  const listFailureTitle = isViewingProjectHistory
    ? t('workspace.projectHistoryUnavailable')
    : t('workspace.recentDiagramsUnavailable');
  const listFailureHint = isViewingProjectHistory
    ? t('workspace.projectHistoryUnavailableHint')
    : t('workspace.recentDiagramsUnavailableHint');
  const getCanvasBadgeLabel = (mode: RecentCanvasLibrary | null) => {
    if (mode === 'tldraw') return 'TLDraw';
    if (mode === 'excalidraw') return 'Excalidraw';
    return null;
  };
  const canvasBadgeClass = 'ml-auto shrink-0 rounded-md border border-slate-200 bg-white/70 px-1.5 py-0.5 text-[11px] font-semibold text-slate-500 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400';
  const disabledInteractionClass = 'disabled:cursor-not-allowed disabled:opacity-55';
  const interactionTitle = isInteractionDisabled ? interactionDisabledReason : undefined;
  const getSnapshotCanvasMode = (snapshot: ProjectSnapshotItem): RecentCanvasLibrary | null => {
    const mode = detectCanvasPayloadKind(snapshot.schema_blob);
    return mode === 'tldraw' || mode === 'excalidraw' ? mode : null;
  };
  const getSnapshotSourceLabel = (editSource?: string | null) => {
    return t(snapshotSourceKey(editSource));
  };
  const getSnapshotTitle = (index: number, isCurrent: boolean) => {
    if (isCurrent) return t('workspace.currentSnapshot');
    if (index === 0) return t('workspace.latestSnapshot');
    return t('workspace.snapshotNumber').replace('{number}', String(index + 1));
  };
  const getSnapshotTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString();
  };
  const getRecentCanvasMode = (item: RecentDiagram): RecentCanvasLibrary | null => {
    if (item.canvas_library === 'tldraw' || item.canvas_library === 'excalidraw') {
      return item.canvas_library;
    }

    const mode = detectCanvasPayloadKind(item.tldraw_snapshot ?? item.excalidraw_payload ?? null);
    return mode === 'tldraw' || mode === 'excalidraw' ? mode : null;
  };

  return (
    <aside
      id={panelId}
      aria-label={t('workspace.projectPanelLabel')}
      aria-busy={Boolean(generatingDiagramId)}
      className="workspace-project-sidebar p-3"
    >
      <div className="mb-3 flex min-h-8 items-center justify-between gap-2 px-1">
        <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400">{t('workspace.projectNavigation')}</h2>
        <button type="button" onClick={onToggleCollapse}
          className={`hidden h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200 lg:inline-flex ${focusRingClass}`}
          title={t('workspace.collapsePanel')} aria-label={t('workspace.collapsePanel')}
          aria-expanded={true} aria-controls={panelId}>
          <PanelLeftClose size={16} />
        </button>
      </div>
      <div className="mb-3 border-b border-slate-200 px-1 pb-3 dark:border-slate-700">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-1 items-start gap-2">
                {isEditingProjectName ? (
                  <input
                    ref={projectNameInputRef}
                    value={projectNameDraft}
                    onChange={(event) => onProjectNameDraftChange(event.target.value)}
                    onBlur={onSaveEdit}
                    disabled={isInteractionDisabled}
                    title={interactionTitle}
                    onKeyDown={(event) => {
                      if (shouldSubmitOnEnter(event)) {
                        event.preventDefault();
                        onSaveEdit();
                      }
                      if (event.key === 'Escape') {
                        event.preventDefault();
                        onCancelEdit();
                      }
                    }}
                    className={`h-11 min-w-0 flex-1 rounded-lg border border-brand-200 bg-white px-2 text-sm font-semibold text-slate-800 outline-none transition focus:border-brand-300 dark:border-brand-500/60 dark:bg-slate-900 dark:text-slate-100 ${focusRingClass}`}
                    aria-label={t('workspace.projectName')}
                  />
                ) : (
                  <p className="min-w-0 flex-1 break-words text-sm font-semibold leading-6 text-slate-800 dark:text-slate-100">{projectName}</p>
                )}
                <button
                  type="button"
                  onClick={() => {
                    if (isInteractionDisabled) {
                      return;
                    }

                    if (isEditingProjectName) {
                      onSaveEdit();
                      return;
                    }
                    onStartEdit();
                  }}
                  disabled={isInteractionDisabled}
                  className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-transparent text-slate-400 transition hover:border-slate-200 hover:bg-slate-50 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-55 dark:text-slate-500 dark:hover:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-brand-300 ${focusRingClass}`}
                  title={interactionTitle ?? (isEditingProjectName ? t('workspace.saveProjectName') : t('workspace.editProjectName'))}
                  aria-label={isEditingProjectName ? t('workspace.saveProjectName') : t('workspace.editProjectName')}
                >
                  {isEditingProjectName ? <Check className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
                </button>
          </div>
        </div>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{currentListLabel}</p>
      </div>

      <>
          <button
            type="button"
            onClick={onOpenCreateDialog}
            disabled={isInteractionDisabled}
            title={interactionTitle}
            className={`mb-2 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-3 py-2.5 text-sm font-semibold text-brand-700 transition hover:bg-brand-100 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-300 dark:hover:bg-brand-500/20 ${disabledInteractionClass} ${focusRingClass}`}
          >
            <Plus className="h-4 w-4" />
            {t('workspace.newDiagram')}
          </button>

          {onSaveSnapshot && (
            <button
              type="button"
              onClick={handleSaveButtonClick}
              disabled={saveButtonDisabled}
              title={interactionTitle ?? saveButtonLabel}
              aria-busy={isSavingSnapshot}
              aria-live="polite"
              className={`mb-2 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold backdrop-blur-md transition disabled:cursor-not-allowed disabled:opacity-45 ${saveButtonToneClass} ${focusRingClass}`}
            >
              <SaveStatusIcon className={`h-3.5 w-3.5 ${isSavingSnapshot ? 'animate-spin' : ''}`} />
              {saveButtonLabel}
            </button>
          )}

          {onOpenProjectDna && (
            <button
              type="button"
              onClick={onOpenProjectDna}
              disabled={isInteractionDisabled}
              title={interactionTitle}
              aria-label={`${t('workspace.projectDnaLabel')}: ${projectDnaScope}`}
              className={`mb-3 inline-flex min-h-11 w-full items-center gap-2 rounded-xl border border-slate-200 bg-white/65 px-3 py-2 text-xs font-medium text-slate-600 backdrop-blur-md transition hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400 dark:hover:border-brand-500/50 dark:hover:text-brand-300 ${disabledInteractionClass} ${focusRingClass}`}
            >
              <Dna className="h-3.5 w-3.5 shrink-0" />
              {t('nav.dna')}
              <span
                className={`ml-auto rounded-full px-2 py-0.5 text-xs font-semibold ${
                  hasProjectDna
                    ? 'bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300'
                    : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                }`}
              >
                {projectDnaScope}
              </span>
            </button>
          )}

          {canViewProjectHistory && (
            <div
              role="tablist"
              aria-label={t('workspace.historyViewLabel')}
              className="mb-3 grid grid-cols-2 gap-1 rounded-xl border border-slate-200 bg-white/55 p-1 text-xs font-semibold text-slate-500 backdrop-blur-md dark:border-slate-700 dark:bg-slate-900/65 dark:text-slate-400"
            >
              <button
                type="button"
                role="tab"
                aria-selected={isViewingProjectHistory}
                onClick={onShowProjectHistory}
                disabled={isInteractionDisabled}
                title={interactionTitle}
                className={`inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg px-2 transition ${disabledInteractionClass} ${focusRingClass} ${
                  isViewingProjectHistory
                    ? 'bg-brand-50 text-brand-700 shadow-sm dark:bg-brand-500/15 dark:text-brand-300'
                    : 'hover:bg-slate-50 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200'
                }`}
              >
                <History className="h-3.5 w-3.5" />
                <span className="truncate">{t('workspace.projectHistoryTab')}</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={!isViewingProjectHistory}
                onClick={onShowRecentDiagrams}
                disabled={isInteractionDisabled}
                title={interactionTitle}
                className={`inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg px-2 transition ${disabledInteractionClass} ${focusRingClass} ${
                  !isViewingProjectHistory
                    ? 'bg-brand-50 text-brand-700 shadow-sm dark:bg-brand-500/15 dark:text-brand-300'
                    : 'hover:bg-slate-50 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200'
                }`}
              >
                <List className="h-3.5 w-3.5" />
                <span className="truncate">{t('workspace.recentDiagramsTab')}</span>
              </button>
            </div>
          )}

          {isInteractionDisabled && interactionDisabledReason && (
            <div className="mb-3 flex items-start gap-2 rounded-xl border border-brand-200/70 bg-brand-50/65 px-3 py-2 text-[11px] font-medium leading-relaxed text-brand-800 backdrop-blur-md dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200" role="status">
              <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
              <span>{interactionDisabledReason}</span>
            </div>
          )}

          <div
            id={listId}
            className="custom-scrollbar flex-1 space-y-2 overflow-y-auto pr-1"
            aria-label={t('workspace.projectListLabel')}
            aria-busy={isListLoading}
            aria-live="polite"
          >
            {visibleItemsCount > 0 && isListLoading && (
              <div
                role="status"
                className="rounded-xl border border-brand-200/80 bg-brand-50/65 px-3 py-2 text-left text-[11px] font-medium text-brand-800 backdrop-blur-md dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200"
              >
                <div className="flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  <span>{t('common.loading')}</span>
                </div>
              </div>
            )}
            {visibleItemsCount > 0 && isListLoadFailed && (
              <div role="alert" className="rounded-xl border border-amber-200/80 bg-amber-50/70 px-3 py-2 text-left text-[11px] text-amber-800 backdrop-blur-md dark:border-amber-500/35 dark:bg-amber-500/10 dark:text-amber-200">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">{listFailureTitle}</p>
                    <p className="mt-0.5 leading-relaxed opacity-85">{listFailureHint}</p>
                  </div>
                  {currentRetryHandler && (
                    <button
                      type="button"
                      onClick={currentRetryHandler}
                      disabled={isInteractionDisabled}
                      title={interactionTitle}
                      className={`shrink-0 rounded-lg border border-amber-200 bg-white/75 px-2 py-1 text-xs font-semibold text-amber-800 transition hover:border-amber-300 hover:bg-white dark:border-amber-500/35 dark:bg-slate-900/55 dark:text-amber-200 dark:hover:border-amber-400/50 ${disabledInteractionClass} ${focusRingClass}`}
                    >
                      {t('common.retry')}
                    </button>
                  )}
                </div>
              </div>
            )}
            {visibleItemsCount === 0 && isListLoading ? (
              <div role="status" className="flex h-full min-h-40 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300/80 bg-white/55 px-3 text-center backdrop-blur-md dark:border-slate-700 dark:bg-slate-900/55">
                <Loader2 className="h-5 w-5 animate-spin text-brand-500" />
                <p className="mt-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
                  {t('common.loading')}
                </p>
              </div>
            ) : visibleItemsCount === 0 && isListLoadFailed ? (
              <div role="alert" className="flex h-full min-h-40 flex-col items-center justify-center rounded-xl border border-amber-200/80 bg-amber-50/70 px-3 text-center backdrop-blur-md dark:border-amber-500/35 dark:bg-amber-500/10">
                <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-300" />
                <p className="mt-2 text-xs font-semibold text-amber-800 dark:text-amber-200">
                  {listFailureTitle}
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-amber-700/80 dark:text-amber-200/80">
                  {listFailureHint}
                </p>
                {currentRetryHandler && (
                  <button
                    type="button"
                    onClick={currentRetryHandler}
                    disabled={isInteractionDisabled}
                    title={interactionTitle}
                    className={`mt-3 inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-amber-200 bg-white/75 px-3 py-2 text-xs font-semibold text-amber-800 transition hover:border-amber-300 hover:bg-white dark:border-amber-500/35 dark:bg-slate-900/55 dark:text-amber-200 dark:hover:border-amber-400/50 ${disabledInteractionClass} ${focusRingClass}`}
                  >
                    <RefreshCcw className="h-3.5 w-3.5" />
                    {t('common.retry')}
                  </button>
                )}
              </div>
            ) : visibleItemsCount === 0 ? (
              <div className="flex h-full min-h-40 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300/80 bg-white/55 px-3 text-center backdrop-blur-md dark:border-slate-700 dark:bg-slate-900/55">
                <FolderKanban className="h-5 w-5 text-slate-500 dark:text-slate-400" />
                <p className="mt-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
                  {t('workspace.noDiagramsYet')}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {t('workspace.noDiagramsHint')}
                </p>
              </div>
            ) : isViewingProjectHistory
              ? displayedProjectSnapshots.map((snapshot, index) => {
                  const isCurrent = preview?.snapshotId === snapshot.snapshot_id;
                  const title = getSnapshotTitle(index, isCurrent);
                  const sourceLabel = getSnapshotSourceLabel(snapshot.edit_source);
                  const timestamp = getSnapshotTimestamp(snapshot.timestamp);
                  const canvasLabel = getCanvasBadgeLabel(getSnapshotCanvasMode(snapshot));
                  return (
                  <button
                    key={snapshot.snapshot_id}
                    type="button"
                    onClick={() => { onSelectSnapshot(snapshot); }}
                    disabled={isInteractionDisabled}
                    title={interactionTitle}
                    aria-label={`${title}, ${sourceLabel}, ${canvasLabel ? `${canvasLabel}, ` : ''}${timestamp}${getCurrentSuffix(isCurrent)}`}
                    aria-current={isCurrent ? 'true' : undefined}
                    className={`min-h-14 w-full rounded-xl border p-3 text-left transition ${disabledInteractionClass} ${focusRingClass} ${isCurrent ? 'border-brand-300 border-l-[3px] border-l-brand-500 bg-brand-50/60 shadow-sm dark:border-brand-500/60 dark:border-l-brand-400 dark:bg-brand-500/15' : 'border-white/70 bg-white/65 backdrop-blur-md hover:border-brand-200 hover:bg-brand-50/40 dark:border-slate-700 dark:bg-slate-900/80 dark:hover:border-brand-500/50 dark:hover:bg-brand-500/10'}`}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <p className="min-w-0 flex-1 text-xs font-semibold text-slate-700 dark:text-slate-200">{sourceLabel}</p>
                      {isCurrent && (
                        <span className="shrink-0 rounded-md bg-brand-100 px-1.5 py-0.5 text-[11px] font-semibold text-brand-700 dark:bg-brand-500/20 dark:text-brand-200">
                          {t('workspace.currentSnapshotBadge')}
                        </span>
                      )}
                      {!isCurrent && index === 0 && (
                        <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                          {t('workspace.latestSnapshotBadge')}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-1 text-xs text-slate-500 dark:text-slate-400">
                      {timestamp}
                    </p>
                  </button>
                  );
                })
              : displayedRecentDiagrams.map((item, index) => {
                  const isItemGenerating = item.diagram_id === generatingDiagramId;
                  const title = isItemGenerating
                    ? t('workspace.generating')
                    : (item.summary || item.prompt || `${t('workspace.diagramPrefix')} ${index + 1}`);
                  const timestamp = isItemGenerating ? t('workspace.generatingHint') : new Date(item.created_at).toLocaleString();
                  const isCurrent = preview?.diagramId === item.diagram_id;
                  const canvasLabel = getCanvasBadgeLabel(getRecentCanvasMode(item));
                  return (
                  <button
                    key={item.id || item.diagram_id || `recent-${index}`}
                    type="button"
                    onClick={() => { onSelectRecentDiagram(item); }}
                    disabled={isInteractionDisabled || isItemGenerating}
                    title={isItemGenerating ? t('workspace.generatingHint') : interactionTitle ?? title}
                    aria-label={`${title}, ${canvasLabel ? `${canvasLabel}, ` : ''}${timestamp}${getCurrentSuffix(isCurrent)}`}
                    aria-current={isCurrent ? 'true' : undefined}
                    aria-busy={isItemGenerating}
                    className={`min-h-14 w-full rounded-xl border p-3 text-left transition ${disabledInteractionClass} ${focusRingClass} ${isCurrent ? 'border-brand-300 border-l-[3px] border-l-brand-500 bg-brand-50/60 shadow-sm dark:border-brand-500/60 dark:border-l-brand-400 dark:bg-brand-500/15' : 'border-white/70 bg-white/65 backdrop-blur-md hover:border-brand-200 hover:bg-brand-50/40 dark:border-slate-700 dark:bg-slate-900/80 dark:hover:border-brand-500/50 dark:hover:bg-brand-500/10'}`}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      {isItemGenerating && (
                        <svg className="h-3.5 w-3.5 shrink-0 animate-spin text-brand-500" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>
                      )}
                      <p className="line-clamp-1 text-xs font-semibold text-slate-700 dark:text-slate-200">{title}</p>
                      {canvasLabel && <span className={canvasBadgeClass}>{canvasLabel}</span>}
                    </div>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{timestamp}</p>
                  </button>
                  );
                })}
          </div>
      </>
    </aside>
  );
}
