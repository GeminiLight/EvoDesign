import '../styles/workspace-documents.css';
import { useBrowserModelLabel } from '../hooks/useBrowserModelLabel';
import { BROWSER_MODE } from '../services/browser/runtime';
import { parseGenerationReport } from '../utils/generationReport';
import { GenerationReport } from '../components/GenerationReport';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Columns3, History, Loader2, MessageSquare, PencilLine, RefreshCcw, Save, X } from 'lucide-react';
import type {
  DiagramRequest,
  DiagramResponse,
  DiagramType,
  ProjectSnapshotItem,
} from '../types/api';
import type { HistoryViewMode, RecentDiagram } from '../types/app';
import { createBlankCanvasProject, createProject, fetchProjectDiagram, fetchProjectSnapshots, fetchRecentDiagrams, isApiError, syncProjectSchema } from '../services/backendApi';
import { workspaceAuthTransition, canRestoreWorkspaceDraft } from '../utils/workspaceAuth';
import { apiDiagramService } from '../services/apiDiagramService';
import { GUEST_IMPORT_COMPLETED_EVENT, type GuestImportCompletedDetail } from '../services/guestImportService';
import { type CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import { DiagramCanvasPanel } from '../components/DiagramCanvas/DiagramCanvasPanel';
import type { PromptPill } from '../components/DiagramPromptComposer';
import { Header } from '../components/Header';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { WorkspaceSettingsDialog } from '../components/Workspace/WorkspaceSettingsDialog';
import { ProjectSidebar } from '../components/Workspace/ProjectSidebar';
import { WorkspaceHistoryPopover } from '../components/Workspace/WorkspaceHistoryPopover';
import { CanvasFullscreenControls } from '../components/Workspace/CanvasFullscreenControls';
import { WorkspaceSaveIndicator } from '../components/Workspace/WorkspaceSaveIndicator';
import { WorkspaceTabs } from '../components/Workspace/WorkspaceTabs';
import { useWorkspaceDocuments } from '../hooks/useWorkspaceDocuments';
import { useCanvasFullscreen } from '../hooks/useCanvasFullscreen';
import { closeWorkspaceDocument, workspaceDocumentKey, type WorkspaceDocument, type CanvasViewState } from '../utils/workspaceDocuments';
import { AgentChatPanel } from '../components/Workspace/AgentChatPanel';
import { ProjectDnaDrawer } from '../components/Workspace/ProjectDnaDrawer';
import { CreateDiagramDialog } from '../components/Workspace/CreateDiagramDialog';
import { WorkspaceOnboarding } from '../components/Workspace/WorkspaceOnboarding';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { useToast } from '../components/toastContext';
import { AUTH_INVALIDATED_EVENT, AUTH_USER_ID_STORAGE_KEY } from '../features/auth/authEvents';
import { useDiagramSync, type WorkspaceSaveStatus } from '../hooks/useDiagramSync';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { useProjectName } from '../hooks/useProjectName';
import { useCreateDialog } from '../hooks/useCreateDialog';
import { useGenerateDiagram } from '../hooks/useGenerateDiagram';
import { createId, defaultConfigs, initialRequest, getDiagramTypeLabel, diagramTypeToPillId, pillIdToDiagramType } from '../constants/app';
import {
  detectCanvasPayloadKind,
  parseJsonObject,
  getSnapshotDocSignature,
  getAllNodeIds,
  inspectCanvasPayload,
  splitCanvasPayload,
  mergeDeltaIntoSchema,
  normalizeTldrawSchemaForLocalEdit,
} from '../utils/app';
import { guestHasProjectDna } from '../services/guestStorage';
import { removeLocalStorage } from '../utils/safeLocalStorage';
import { loadProjectName, saveProjectName } from '../services/projectPreferences';
import { useLocation, useNavigate } from 'react-router-dom';
import { StageProgress } from '../components/StageProgress';
import {
  clearStartupGenerationDraft,
  markStartupGenerationDraftFailed,
  saveStartupGenerationDraft,
  type StartupGenerationDraft,
  type StartupGenerationDraftSource,
} from '../services/startupGenerationDraft';
import {
  clearWorkspaceRecoveryDraft,
  loadWorkspaceRecoveryDraft,
  saveWorkspaceRecoveryDraft,
} from '../services/workspaceRecoveryDraft';
import {
  clearWorkspacePreflightDraft,
  saveWorkspacePreflightDraft,
  type WorkspacePreflightGeneration,
} from '../services/workspacePreflightDraft';
import {
  buildCreateHandoff,
  getInitialPreflightGeneration,
  getInitialStartupGenerationDraft,
  isWorkspaceDiagramType,
} from '../services/workspaceRouteHandoff';

type WorkspaceLoadStatus = 'idle' | 'loading' | 'ready' | 'failed';

type ActiveGenerationSummary = {
  prompt: string;
  diagramTypeLabel: string;
  modelLabel: string;
  canvasLabel: string;
};

type FailedGenerationDraft = {
  promptText: string;
  diagramType: DiagramType;
  llmConfigId: string;
  canvasMode: CanvasMode;
  metadata?: Record<string, string>;
  recoverPreviewOnFailure?: DiagramResponse | null;
};

type GenerationPreparationResult = 'ready' | 'failed' | 'cancelled';

type CreatePreflightDraftOverrides = {
  useIcons?: boolean;
  promptText?: string;
  diagramType?: DiagramType;
  modelIndex?: number;
  canvasIndex?: number;
};

const buildFailedDraftFromStartupDraft = (
  draft: StartupGenerationDraft,
): FailedGenerationDraft => ({
  promptText: draft.promptText,
  diagramType: draft.diagramType,
  llmConfigId: draft.llmConfigId,
  canvasMode: draft.canvasMode,
  metadata: draft.metadata,
  recoverPreviewOnFailure: null,
});

const buildPromptAfterPillSelection = (
  currentPrompt: string,
  nextPill: PromptPill,
  allPills: PromptPill[],
) => {
  const trimmedCurrent = currentPrompt.trimStart();
  const nextPrefix = nextPill.prefix.trim();

  if (!trimmedCurrent) {
    return nextPrefix ? `${nextPrefix} ` : '';
  }

  const currentPrefix = allPills
    .map((pill) => pill.prefix.trim())
    .filter(Boolean)
    .find((prefix) => trimmedCurrent.toLocaleLowerCase().startsWith(prefix.toLocaleLowerCase()));

  if (!currentPrefix) {
    return currentPrompt;
  }

  const remainingPrompt = trimmedCurrent.slice(currentPrefix.length).trimStart();
  return remainingPrompt ? `${nextPrefix} ${remainingPrompt}` : `${nextPrefix} `;
};

export function WorkspacePage() {
  const { t, language } = useLanguage();
  const modelLabel = useBrowserModelLabel(t);
  const { showToast } = useToast();
  const { user, loading: authLoading } = useBackendAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const authIdentity = user?.user_id ?? null;
  const [canvasOwnerIdentity, setCanvasOwnerIdentity] = useState(authIdentity);
  const expiredAuthIdentityRef = useRef<string | null>(null);
  const [initialPreflightGeneration] = useState<WorkspacePreflightGeneration | null>(() => (
    getInitialPreflightGeneration(location.state)
  ));
  const [initialStartupDraft] = useState<StartupGenerationDraft | null>(() => (
    getInitialStartupGenerationDraft(location.state)
  ));
  const [initialResumeProjectId] = useState(() => (
    !initialPreflightGeneration && !initialStartupDraft && !location.state?.pendingLoadProject
      ? new URLSearchParams(location.search).get('project') : null
  ));

  const initialCanvasModeFromLocation = initialStartupDraft?.canvasMode ?? location.state?.initialCanvasMode;
  const initialCanvasMode: CanvasMode = initialCanvasModeFromLocation === 'tldraw' ? 'tldraw' : 'excalidraw';

  const [request, setRequest] = useState<DiagramRequest>(() => {
    const initialPrompt = initialStartupDraft?.promptText ?? location.state?.initialPrompt;
    const initialLlmConfigId = initialStartupDraft?.llmConfigId ?? location.state?.initialLlmConfigId;
    const initialDiagramType = initialStartupDraft?.diagramType ?? location.state?.initialDiagramType;

    const hasValidLlmConfig = typeof initialLlmConfigId === 'string'
      && defaultConfigs.some((config) => config.id === initialLlmConfigId);
    const normalizedInitialDiagramType: DiagramType | null = isWorkspaceDiagramType(initialDiagramType)
      ? initialDiagramType as DiagramType
      : null;
    const hasValidDiagramType = normalizedInitialDiagramType !== null;

    if (initialPrompt) {
      return {
        ...initialRequest,
        prompt: initialPrompt,
        diagramType: hasValidDiagramType ? normalizedInitialDiagramType : initialRequest.diagramType,
        llmConfigId: hasValidLlmConfig ? initialLlmConfigId : initialRequest.llmConfigId,
      };
    }

    if (hasValidDiagramType && hasValidLlmConfig) {
      return {
        ...initialRequest,
        diagramType: normalizedInitialDiagramType,
        llmConfigId: initialLlmConfigId,
      };
    }

    if (hasValidDiagramType) {
      return {
        ...initialRequest,
        diagramType: normalizedInitialDiagramType,
      };
    }

    if (hasValidLlmConfig) {
      return {
        ...initialRequest,
        llmConfigId: initialLlmConfigId,
      };
    }

    return initialRequest;
  });
  const [canvasMode, setCanvasMode] = useState<CanvasMode>(initialCanvasMode);
  const [preview, setPreview] = useState<DiagramResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recentDiagrams, setRecentDiagrams] = useState<RecentDiagram[]>([]);
  const [projectSnapshots, setProjectSnapshots] = useState<ProjectSnapshotItem[]>([]);
  const [recentLoadStatus, setRecentLoadStatus] = useState<WorkspaceLoadStatus>('idle');
  const [projectHistoryLoadStatus, setProjectHistoryLoadStatus] = useState<WorkspaceLoadStatus>('idle');
  const [recentReloadNonce, setRecentReloadNonce] = useState(0);
  const [projectHistoryReloadNonce, setProjectHistoryReloadNonce] = useState(0);
  const [historyViewMode, setHistoryViewMode] = useState<HistoryViewMode>('recent');
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const mobileHistoryRef = useRef<HTMLButtonElement | null>(null);
  const [isAssistantFloating, setIsAssistantFloating] = useState(true);
  const fullscreenRootRef = useRef<HTMLDivElement>(null);
  const fullscreenAssistantButtonRef = useRef<HTMLButtonElement>(null);
  const { isFullscreen: isCanvasFullscreen, toggleFullscreen } = useCanvasFullscreen(fullscreenRootRef);
  const [showWorkspaceSettings, setShowWorkspaceSettings] = useState(false);
  const [mobilePane, setMobilePane] = useState<'canvas' | 'chat' | 'projects'>('canvas');
  const isCompactWorkspace = useMediaQuery('(max-width: 1023px)');
  const [isChatPanelCollapsed, setIsChatPanelCollapsed] = useState(true);
  const handleToggleCanvasFullscreen = useCallback(() => {
    setIsHistoryOpen(false);
    setMobilePane('canvas');
    void toggleFullscreen().catch(() => showToast(t('workspace.fullscreenFailed'), 'error'));
  }, [toggleFullscreen, showToast, t]);
  // Lifted out of WorkspaceOnboarding so the chat panel can tell whether the
  // onboarding card is currently the one offering starter prompts.
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);
  const {
    projectName, setProjectName, projectNameDraft, setProjectNameDraft,
    isEditingProjectName, isSavingProjectName, projectNameInputRef,
    handleStartProjectNameEdit, handleCancelProjectNameEdit, handleSaveProjectNameEdit,
  } = useProjectName(preview?.projectId, canvasOwnerIdentity, t, {
    readOnly: Boolean(canvasOwnerIdentity && canvasOwnerIdentity !== authIdentity),
    onRenamed: (projectId, title) => {
      commitRecentDiagrams(items => items.map(item => item.project_id === projectId ? { ...item, summary: title } : item));
      setPreview(current => current?.projectId === projectId ? { ...current, summary: title } : current);
    },
    onError: () => showToast(t('workspace.projectRenameFailed'), 'error'),
  });

  const {
    showCreateDialog, setShowCreateDialog, createPrompt, setCreatePrompt,
    createSelectedPillId, setCreateSelectedPillId,
    createModelIndex, setCreateModelIndex, createCanvasIndex, setCreateCanvasIndex,
    createPills, createMorePills, createModelOptions, createCanvasOptions,
    selectedCreateDiagramType,
    handleOpenCreateDialog,
  } = useCreateDialog(request, canvasMode, t);
  const [createUseIcons, setCreateUseIcons] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<Array<{ id: string; role: 'user' | 'agent'; content: string }>>([
    { id: 'agent-init', role: 'agent', content: t('workspace.agentReady') },
  ]);
  const { documents: openDocuments, open: openDocument, close: closeDocument,
    remember: rememberDocumentContext, recall: recallDocumentContext } = useWorkspaceDocuments(authIdentity);
  const activeDocumentKey = workspaceDocumentKey(preview?.projectId, preview?.diagramId);
  const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(null);
  const viewReaderRef = useRef<(() => CanvasViewState) | null>(null);
  const createNewDocumentRef = useRef(false);
  const handleViewReader = useCallback((reader: (() => CanvasViewState) | null) => { viewReaderRef.current = reader; }, []);
  const rememberCurrentDocument = useCallback(() => {
    if (!preview || canvasOwnerIdentity !== authIdentity) return;
    rememberDocumentContext(activeDocumentKey, { messages: chatMessages, input: chatInput, view: viewReaderRef.current?.() ?? null });
  }, [activeDocumentKey, authIdentity, canvasOwnerIdentity, chatInput, chatMessages, preview, rememberDocumentContext]);
  const restoreDocumentContext = useCallback((key: string) => {
    const context = recallDocumentContext(key);
    setChatMessages(context?.messages.map(message => message.id === 'agent-init' ? { ...message, content: t('workspace.agentReady') } : message)
      ?? [{ id: 'agent-init', role: 'agent', content: t('workspace.agentReady') }]);
    setChatInput(context?.input ?? '');
  }, [recallDocumentContext, t]);
  useEffect(() => {
    if (!preview || canvasOwnerIdentity !== authIdentity) return;
    openDocument({ key: activeDocumentKey, projectId: preview.projectId, diagramId: preview.diagramId,
      title: projectName || preview.summary || t('workspace.untitledProject') });
  }, [activeDocumentKey, authIdentity, canvasOwnerIdentity, openDocument, preview, projectName, t]);
  useEffect(() => {
    setChatMessages(messages => messages.map(message => message.id === 'agent-init' ? { ...message, content: t('workspace.agentReady') } : message));
  }, [t]);
  const [activeCreatePreflight, setActiveCreatePreflight] = useState<WorkspacePreflightGeneration | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [showProjectDna, setShowProjectDna] = useState(false);
  const [hasProjectDna, setHasProjectDna] = useState(false);
  const [isLocalEditing, setIsLocalEditing] = useState(false);
  const [isGenerationStarting, setIsGenerationStarting] = useState(false);
  const [isSaveRecoveryActive, setIsSaveRecoveryActive] = useState(false);
  const [isHistorySwitching, setIsHistorySwitching] = useState(false);
  const [showWorkspaceRecoveryNotice, setShowWorkspaceRecoveryNotice] = useState(false);
  const [showReauthConfirm, setShowReauthConfirm] = useState(false);
  const [activeGenerationSummary, setActiveGenerationSummary] = useState<ActiveGenerationSummary | null>(null);
  const [failedGenerationDraft, setFailedGenerationDraft] = useState<FailedGenerationDraft | null>(() => (
    initialStartupDraft?.status === 'failed'
      ? buildFailedDraftFromStartupDraft(initialStartupDraft)
      : null
  ));
  const [startupGenerationActive, setStartupGenerationActive] = useState(
    () => initialStartupDraft?.status === 'pending',
  );
  const previewIdentityRef = useRef<{ projectId?: string; snapshotId?: string }>({});
  const pendingGuestPreviewIdentityRef = useRef<{ projectId?: string; snapshotId?: string } | null>(null);
  const activeAuthIdentityRef = useRef<string | null>(authIdentity);
  const previousAuthIdentityRef = useRef<string | null | undefined>(undefined);
  const authInvalidatedRef = useRef(false);
  const workspaceCanvasSectionRef = useRef<HTMLElement | null>(null);
  activeAuthIdentityRef.current = authIdentity;
  // Canvas context counter: each user-driven canvas switch increments this. A
  // generation run also captures it, so stale async results cannot replace a
  // canvas the user moved away from.
  const switchGenRef = useRef(0);
  const generationStartInFlightRef = useRef(false);
  const historySwitchInFlightRef = useRef(false);
  const generationPreparationAbortControllerRef = useRef<AbortController | null>(null);
  // Guard: ensure pendingLoadProject from location.state is processed at most once.
  const pendingLoadHandledRef = useRef(false);
  // Guard: ensure pendingGeneration from location.state is processed at most once.
  const pendingGenerationHandledRef = useRef(false);
  const preflightGenerationHandledRef = useRef(false);
  const preserveCanvasDuringHistoryReloadRef = useRef<false | 'preserve' | 'rebase'>(false);
  const workspaceRecoveryDraftAppliedRef = useRef(false);

  const clearActiveCreatePreflight = useCallback(() => {
    setActiveCreatePreflight(null);
    clearWorkspacePreflightDraft();
  }, []);

  const {
    latestSnapshotRef,
    activeEditingSnapshotIdRef,
    beginHistorySwitch,
    persistLatestSnapshot,
    persistCurrentChangesBeforeSwitch,
    persistCurrentChangesBeforeGeneration,
    prepareSaveConflictRetry,
    handleTldrawSnapshotChange,
    handleExcalidrawSceneChange,
    handleManualSaveSnapshot,
    manualSaveStatus,
    hasUnsavedChanges,
    lastSyncedDocSignatureRef,
    projectVersionRef,
    resetSyncState,
    markAuthExpiredPreservingDirtyState,
    restoreRecoveryDraftSyncState,
  } = useDiagramSync(preview, setPreview, canvasMode, setError, t);

  const getGenerationRunGuard = useCallback(() => (
    `${activeAuthIdentityRef.current ?? 'guest'}:${switchGenRef.current}`
  ), []);

  useEffect(() => {
    previewIdentityRef.current = {
      projectId: preview?.projectId,
      snapshotId: preview?.snapshotId,
    };
  }, [preview?.projectId, preview?.snapshotId]);

  // Monotonic write counter for `recentDiagrams`. The sidebar loader below and
  // the post-generation refresh inside useGenerateDiagram both publish this
  // list, so a slow loader response must not roll back a newer write.
  const recentDiagramsWriteSeqRef = useRef(0);
  const commitRecentDiagrams: typeof setRecentDiagrams = useCallback((value) => {
    recentDiagramsWriteSeqRef.current += 1;
    setRecentDiagrams(value);
  }, []);

  const {
    isGenerating, progress, generatingDiagramId,
    cancelGeneration, wasLastGenerationCancelled,
    generateDiagram,
  } = useGenerateDiagram({
    setPreview, setRecentDiagrams: commitRecentDiagrams, setHistoryViewMode,
    latestSnapshotRef, activeEditingSnapshotIdRef, lastSyncedDocSignatureRef,
    setRequest, setCanvasMode, setError,
    showToast, t,
    userId: user?.user_id ?? '',
    authIdentity,
    projectName,
    getRunGuard: getGenerationRunGuard,
  });

  const clearSelection = useCallback(() => {
    setSelectedNodeIds([]);
  }, []);

  const getValidSelectedNodeIds = useCallback((schema: Record<string, unknown> | null) => {
    if (!schema || selectedNodeIds.length === 0) {
      return [];
    }

    const currentNodeIds = new Set(getAllNodeIds(schema));
    return selectedNodeIds.filter((id) => currentNodeIds.has(id));
  }, [selectedNodeIds]);
  const validSelectedNodeIdsForChat = getValidSelectedNodeIds(latestSnapshotRef.current);
  const sceneElementsForChat = Array.isArray(latestSnapshotRef.current?.elements)
    ? latestSnapshotRef.current.elements as Array<{ id: string; type?: string; text?: string; originalText?: string; containerId?: string }> : [];
  const selectedElementForChat = validSelectedNodeIdsForChat.length === 1
    ? sceneElementsForChat.find(element => element.id === validSelectedNodeIdsForChat[0]) : undefined;
  const selectedTextForChat = selectedElementForChat?.type === 'text' ? selectedElementForChat
    : sceneElementsForChat.find(element => element.type === 'text' && element.containerId === selectedElementForChat?.id);
  const selectedLabelForChat = (selectedTextForChat?.originalText || selectedTextForChat?.text || '').replace(/\s+/g, ' ').slice(0, 120);
  const selectionLabelForChat = selectedElementForChat
    ? ['arrow', 'line'].includes(selectedElementForChat.type || '')
      ? `${t('workspace.selectedConnection')}${selectedLabelForChat ? `: ${selectedLabelForChat}` : ''}`
      : selectedLabelForChat ? t('workspace.selectedLabel').replace('{label}', selectedLabelForChat) : undefined
    : undefined;
  const staleSelectedCountForChat = Math.max(
    0,
    selectedNodeIds.length - validSelectedNodeIdsForChat.length,
  );

  const isGenerationBusy = isGenerationStarting || isGenerating || startupGenerationActive;
  const workspaceInteractionBlocked = isGenerationBusy || isLocalEditing || isSaveRecoveryActive || isHistorySwitching || isSavingProjectName;
  const canvasBusyKind = isLocalEditing
    ? 'local-edit'
    : isSaveRecoveryActive || isSavingProjectName
      ? 'save-recovery'
      : isHistorySwitching
        ? 'history-switch'
        : isGenerationBusy
          ? 'generation'
          : null;
  const authTransitionBlocked = workspaceInteractionBlocked;


  const activeCreateHandoff = useMemo(
    () => buildCreateHandoff(activeCreatePreflight, t),
    [activeCreatePreflight, t],
  );
  const preflightReviewActive = showCreateDialog && Boolean(activeCreatePreflight) && !preview;
  const onboardingVisible = !preview && !isGenerationBusy && !preflightReviewActive;
  const persistCreatePreflightDraft = useCallback((overrides: CreatePreflightDraftOverrides = {}) => {
    if (!activeCreatePreflight) {
      return;
    }

    const nextModelIndex = overrides.modelIndex ?? createModelIndex;
    const nextCanvasIndex = overrides.canvasIndex ?? createCanvasIndex;
    const selectedLlmConfigId = createModelOptions[nextModelIndex]?.id ?? activeCreatePreflight.llmConfigId;
    const selectedCanvasMode = createCanvasOptions[nextCanvasIndex]?.id === 'tldraw' ? 'tldraw' : 'excalidraw';

    saveWorkspacePreflightDraft({
      ...activeCreatePreflight,
      promptText: (overrides.promptText ?? createPrompt).trim(),
      diagramType: overrides.diagramType ?? selectedCreateDiagramType,
      llmConfigId: selectedLlmConfigId,
      canvasMode: selectedCanvasMode,
      useIcons: (overrides.useIcons ?? createUseIcons) && selectedCanvasMode === 'excalidraw',
      updatedAt: Date.now(),
    });
  }, [
    activeCreatePreflight,
    createCanvasIndex,
    createCanvasOptions,
    createModelIndex,
    createModelOptions,
    createPrompt,
    createUseIcons,
    selectedCreateDiagramType,
  ]);
  const shouldOfferGenerationRecovery = Boolean(preview?.persistError && !preview.projectId);
  const sidebarSaveStatus: WorkspaceSaveStatus = isSaveRecoveryActive || isHistorySwitching
    ? 'saving'
    : shouldOfferGenerationRecovery
      ? 'missingProject'
      : manualSaveStatus;
  const workspaceInteractionBlockedReason = canvasBusyKind === 'local-edit'
    ? t('workspace.localEditNavigationBlocked')
    : canvasBusyKind === 'save-recovery'
      ? t('workspace.saveRecoveryNavigationBlocked')
      : canvasBusyKind === 'history-switch'
        ? t('workspace.historySwitchNavigationBlocked')
        : t('workspace.generationNavigationBlocked');
  const handleAuthTransitionBlocked = useCallback(() => {
    showToast(t('workspace.authTransitionBlocked'), 'info');
  }, [showToast, t]);
  const handleWorkspaceInteractionBlocked = useCallback(() => {
    showToast(workspaceInteractionBlockedReason, 'info');
  }, [showToast, workspaceInteractionBlockedReason]);
  const getCanvasModeLabel = useCallback((mode: CanvasMode) => (
    mode === 'tldraw' ? t('home.canvasTldraw') : t('home.canvasExcalidraw')
  ), [t]);
  const setGenerationSummary = useCallback((
    promptText: string,
    diagramType: DiagramType,
    selectedCanvasMode: CanvasMode,
  ) => {
    setActiveGenerationSummary({
      prompt: promptText.trim(),
      diagramTypeLabel: getDiagramTypeLabel(diagramType, t),
      modelLabel,
      canvasLabel: getCanvasModeLabel(selectedCanvasMode),
    });
  }, [getCanvasModeLabel, modelLabel, t]);
  const buildFailedGenerationDraft = useCallback((
    promptText: string,
    diagramType: DiagramType,
    llmConfigId: string,
    selectedCanvasMode: CanvasMode,
    metadata?: Record<string, string>,
    recoverPreviewOnFailure?: DiagramResponse | null,
  ): FailedGenerationDraft => ({
    promptText,
    diagramType,
    llmConfigId,
    canvasMode: selectedCanvasMode,
    metadata,
    recoverPreviewOnFailure,
  }), []);
  const savePendingGenerationDraft = useCallback((
    draft: FailedGenerationDraft,
    source: StartupGenerationDraftSource = 'workspace',
  ) => {
    clearWorkspacePreflightDraft();
    saveStartupGenerationDraft({
      promptText: draft.promptText,
      diagramType: draft.diagramType,
      llmConfigId: draft.llmConfigId,
      canvasMode: draft.canvasMode,
      metadata: draft.metadata,
      status: 'pending',
      source,
    });
  }, []);
  const saveFailedGenerationDraft = useCallback((
    draft: FailedGenerationDraft,
    source: StartupGenerationDraftSource = 'workspace',
  ) => {
    setFailedGenerationDraft(draft);
    saveStartupGenerationDraft({
      promptText: draft.promptText,
      diagramType: draft.diagramType,
      llmConfigId: draft.llmConfigId,
      canvasMode: draft.canvasMode,
      metadata: draft.metadata,
      status: 'failed',
      source,
    });
  }, []);
  const clearGenerationFailure = useCallback(() => {
    setFailedGenerationDraft(null);
    clearStartupGenerationDraft();
  }, []);
  const handleCancelActiveGeneration = useCallback(() => {
    generationPreparationAbortControllerRef.current?.abort();
    cancelGeneration();
  }, [cancelGeneration]);
  const getGenerationIncompleteMessage = useCallback(() => (
    wasLastGenerationCancelled()
      ? t('workspace.generationCancelledChat')
      : t('workspace.diagramUpdateFailed')
  ), [t, wasLastGenerationCancelled]);
  const scrollCanvasIntoViewOnMobile = useCallback(() => {
    if (!window.matchMedia('(max-width: 1023px)').matches) {
      return;
    }

    setMobilePane('canvas');
    const target = workspaceCanvasSectionRef.current;
    if (!target) {
      return;
    }

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        target.scrollIntoView({
          block: 'start',
          behavior: prefersReducedMotion ? 'auto' : 'smooth',
        });
      });
    });
  }, []);
  const beginGenerationStart = useCallback(() => {
    if (expiredAuthIdentityRef.current) {
      showToast(t('workspace.saveAuthExpired'), 'error');
      return false;
    }
    if (generationStartInFlightRef.current || isGenerating || startupGenerationActive) {
      return false;
    }

    generationStartInFlightRef.current = true;
    setIsGenerationStarting(true);
    return true;
  }, [isGenerating, startupGenerationActive, showToast, t]);
  const finishGenerationStart = useCallback(() => {
    generationStartInFlightRef.current = false;
    setIsGenerationStarting(false);
  }, []);
  const buildGlobalGenerationMetadata = useCallback((
    selectedCanvasMode: CanvasMode,
    extras: Record<string, string> = {},
  ): Record<string, string> => {
    const schemaForGeneration = selectedCanvasMode === canvasMode
      ? latestSnapshotRef.current
      : null;
    const savedElements = schemaForGeneration?.elements;
    const savedIconsEnabled = Array.isArray(savedElements) && savedElements.some(element => (
      element?.type === 'image' && !element.isDeleted && element.customData?.evoDesignIcon
    ));

    return {
      canvasLibrary: selectedCanvasMode,
      // After reopening/switching projects, preserve this scene's icon choice
      // instead of borrowing the previous request's setting.
      useIcons: String(schemaForGeneration ? savedIconsEnabled : request.useIcons ?? false),
      ...(preview?.projectId ? { projectId: preview.projectId } : {}),
      ...(schemaForGeneration ? { currentSchema: JSON.stringify(schemaForGeneration) } : {}),
      ...extras,
    };
  }, [canvasMode, latestSnapshotRef, preview?.projectId, request.useIcons]);

  const getLocalEditFailureMessage = useCallback((err: unknown) => {
    // The browser adapter sanitizes provider failures; show its actionable reason.
    if (BROWSER_MODE && err instanceof Error) return err.message;
    if (isApiError(err)) {
      switch (err.code) {
        case 'local_edit_auth_expired':
          return t('workspace.localEditAuthExpired');
        case 'local_edit_rate_limited':
          return t('workspace.localEditRateLimited');
        case 'local_edit_selection_missing':
          return t('workspace.localEditSelectionMissing');
        case 'local_edit_unsupported_canvas':
          return t('workspace.localEditUnsupportedCanvas');
        default:
          break;
      }
    }

    return t('workspace.localEditFailed');
  }, [t]);

  const saveWorkspaceRecoveryState = useCallback((owner?: string | null) => {
    if (!preview) {
      return false;
    }

    const snapshotPayload = latestSnapshotRef.current
      ?? parseJsonObject(preview.tldrawSnapshot)
      ?? parseJsonObject(preview.excalidrawPayload);
    if (!snapshotPayload) {
      return false;
    }

    // The restore path rebuilds tldrawSnapshot / excalidrawPayload /
    // rawSchemaBlob from `latestSnapshot`, so keeping copies here only
    // serialized the same canvas three times and blew the sessionStorage quota
    // on large diagrams.
    return saveWorkspaceRecoveryDraft({
      preview: {
        ...preview,
        tldrawSnapshot: undefined,
        excalidrawPayload: '',
        rawSchemaBlob: undefined,
      },
      request,
      canvasMode,
      projectName,
      latestSnapshot: snapshotPayload,
      activeEditingSnapshotId: activeEditingSnapshotIdRef.current ?? preview.snapshotId ?? null,
      lastSyncedDocSignature: lastSyncedDocSignatureRef.current,
      projectVersion: projectVersionRef.current,
      hasUnsavedChanges,
      sourceAuthIdentity: owner ?? activeAuthIdentityRef.current ?? expiredAuthIdentityRef.current,
    });
  }, [
    activeEditingSnapshotIdRef,
    canvasMode,
    hasUnsavedChanges,
    lastSyncedDocSignatureRef,
    latestSnapshotRef,
    preview,
    projectName,
    projectVersionRef,
    request,
  ]);

  const proceedToReauth = useCallback(() => {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    removeLocalStorage('auth_token');
    removeLocalStorage(AUTH_USER_ID_STORAGE_KEY);
    window.dispatchEvent(new Event(AUTH_INVALIDATED_EVENT));
    navigate('/auth/email', { state: { returnTo } });
  }, [location.hash, location.pathname, location.search, navigate]);

  const handleReauthFromWorkspace = useCallback(() => {
    // The draft save also fails when sessionStorage is unavailable or over
    // quota. Cancelling the redirect there left the user stuck in an expired
    // workspace with no way back to sign-in, so degrade to a confirmation.
    // The native window.confirm was the last one in the app; route it through
    // the shared ConfirmDialog so styling, focus trapping and i18n match.
    if (preview && !saveWorkspaceRecoveryState()) {
      setShowReauthConfirm(true);
      return;
    }

    proceedToReauth();
  }, [preview, proceedToReauth, saveWorkspaceRecoveryState]);

  useEffect(() => {
    const handleAuthInvalidated = (event: Event) => {
      authInvalidatedRef.current = (event as CustomEvent<{ reason?: string }>).detail?.reason !== 'signed-out';
    };

    window.addEventListener(AUTH_INVALIDATED_EVENT, handleAuthInvalidated);
    return () => {
      window.removeEventListener(AUTH_INVALIDATED_EVENT, handleAuthInvalidated);
    };
  }, []);

  useEffect(() => {
    if (authLoading) return;
    const previousAuthIdentity = previousAuthIdentityRef.current;
    if (previousAuthIdentity === undefined) setCanvasOwnerIdentity(authIdentity);
    if (previousAuthIdentity !== undefined && previousAuthIdentity !== authIdentity) {
      const transition = workspaceAuthTransition(previousAuthIdentity, authIdentity, expiredAuthIdentityRef.current);
      const isGuestAccountUpgrade = transition === 'guest-upgrade';
      const isSessionInvalidation = previousAuthIdentity !== null
        && authIdentity === null
        && authInvalidatedRef.current;
      authInvalidatedRef.current = false;

      if (isSessionInvalidation) {
        expiredAuthIdentityRef.current = previousAuthIdentity;
        switchGenRef.current += 1;
        if (preview && !saveWorkspaceRecoveryState(previousAuthIdentity)) {
          showToast(t('workspace.workspaceRecoverySaveFailed'), 'error');
        }
        markAuthExpiredPreservingDirtyState();
        clearSelection();
        setRecentDiagrams([]);
        setProjectSnapshots([]);
        setRecentLoadStatus('idle');
        setProjectHistoryLoadStatus('idle');
        setIsLocalEditing(false);
        setStartupGenerationActive(false);
        setShowCreateDialog(false);
        clearActiveCreatePreflight();
        setShowProjectDna(false);
        setHasProjectDna(false);
        setShowWorkspaceRecoveryNotice(false);
        setError((current) => current ?? t('workspace.saveAuthExpired'));
        previousAuthIdentityRef.current = authIdentity;
        return;
      }

      expiredAuthIdentityRef.current = null;
      setCanvasOwnerIdentity(authIdentity);
      if (transition === 'resume' && preview && latestSnapshotRef.current) {
        // The live canvas can be newer than the disk draft after an expiry.
        restoreRecoveryDraftSyncState({
          latestSnapshot: latestSnapshotRef.current,
          activeEditingSnapshotId: activeEditingSnapshotIdRef.current,
          lastSyncedDocSignature: lastSyncedDocSignatureRef.current,
          projectVersion: projectVersionRef.current,
          hasUnsavedChanges,
        });
        workspaceRecoveryDraftAppliedRef.current = true;
        preserveCanvasDuringHistoryReloadRef.current = 'preserve';
        if (!hasUnsavedChanges) clearWorkspaceRecoveryDraft();
        setRecentReloadNonce(value => value + 1);
        setProjectHistoryReloadNonce(value => value + 1);
        setError(null);
        previousAuthIdentityRef.current = authIdentity;
        return;
      }
      pendingLoadHandledRef.current = true;
      workspaceRecoveryDraftAppliedRef.current = false;
      const search = new URLSearchParams(location.search);
      search.delete('project');
      navigate({ pathname: location.pathname, search: search.toString() }, { replace: true, state: {} });
      switchGenRef.current += 1;
      resetSyncState();
      if (isGuestAccountUpgrade) {
        pendingGuestPreviewIdentityRef.current = { ...previewIdentityRef.current };
        setPreview((prev) => prev ? {
          ...prev,
          projectId: undefined,
          snapshotId: undefined,
        } : null);
        activeEditingSnapshotIdRef.current = null;
        showToast(t('workspace.guestCanvasKeptAfterLogin'), 'info');
      } else {
        pendingGuestPreviewIdentityRef.current = null;
        setPreview(null);
      }
      setRecentDiagrams([]);
      setProjectSnapshots([]);
      setRecentLoadStatus('idle');
      setProjectHistoryLoadStatus('idle');
      setHistoryViewMode('recent');
      if (!isGuestAccountUpgrade) {
        setRequest(initialRequest);
        setCanvasMode(initialCanvasMode);
      }
      clearSelection();
      setShowProjectDna(false);
      setHasProjectDna(false);
      setShowWorkspaceRecoveryNotice(false);
      setIsLocalEditing(false);
      setStartupGenerationActive(false);
      setShowCreateDialog(false);
      clearActiveCreatePreflight();
      setCreatePrompt('');
      setCreateSelectedPillId('adaptive');
      setCreateModelIndex(0);
      if (!isGuestAccountUpgrade) {
        setCreateCanvasIndex(initialCanvasMode === 'tldraw' ? 1 : 0);
        setChatInput('');
        setChatMessages([{ id: 'agent-init', role: 'agent', content: t('workspace.agentReady') }]);
      }
      setError(null);
    }
    previousAuthIdentityRef.current = authIdentity;
  }, [
    authIdentity, authLoading, hasUnsavedChanges, latestSnapshotRef, projectVersionRef,
    restoreRecoveryDraftSyncState, location.pathname, location.search, navigate,
    activeEditingSnapshotIdRef,
    clearActiveCreatePreflight,
    clearSelection,
    initialCanvasMode,
    lastSyncedDocSignatureRef,
    markAuthExpiredPreservingDirtyState,
    preview,
    resetSyncState,
    saveWorkspaceRecoveryState,
    setCreateCanvasIndex,
    setCreateModelIndex,
    setCreatePrompt,
    setCreateSelectedPillId,
    setShowCreateDialog,
    showToast,
    t,
  ]);

  useEffect(() => {
    if (workspaceRecoveryDraftAppliedRef.current || !authIdentity) {
      return;
    }

    const draft = loadWorkspaceRecoveryDraft();
    if (!draft) {
      return;
    }
    if (!canRestoreWorkspaceDraft(draft.sourceAuthIdentity, draft.preview.projectId, authIdentity)) {
      return;
    }

    const draftDirty = draft.hasUnsavedChanges
      || getSnapshotDocSignature(draft.latestSnapshot) !== draft.lastSyncedDocSignature;
    if (!draftDirty && initialResumeProjectId) {
      clearWorkspaceRecoveryDraft();
      return;
    }
    workspaceRecoveryDraftAppliedRef.current = true;
    pendingGuestPreviewIdentityRef.current = null;
    if (!draftDirty) clearWorkspaceRecoveryDraft();
    const splitPayload = splitCanvasPayload(draft.latestSnapshot);

    setCanvasMode(draft.canvasMode);
    setRequest(draft.request);
    setProjectName(draft.projectName);
    clearSelection();
    clearGenerationFailure();
    preserveCanvasDuringHistoryReloadRef.current = 'preserve';
    setHistoryViewMode(draft.preview.projectId ? 'project' : 'recent');
    setPreview({
      ...draft.preview,
      tldrawSnapshot: splitPayload.tldrawSnapshot,
      excalidrawPayload: splitPayload.excalidrawPayload,
      rawSchemaBlob: draft.latestSnapshot,
    });
    restoreRecoveryDraftSyncState({
      latestSnapshot: draft.latestSnapshot,
      activeEditingSnapshotId: draft.activeEditingSnapshotId ?? draft.preview.snapshotId ?? null,
      lastSyncedDocSignature: draft.lastSyncedDocSignature,
      projectVersion: draft.projectVersion,
      hasUnsavedChanges: draftDirty,
    });
    setShowWorkspaceRecoveryNotice(draftDirty);
    if (draftDirty) showToast(t('workspace.workspaceRecoveryRestored'), 'info');
  }, [
    authIdentity,
    clearGenerationFailure,
    clearSelection,
    restoreRecoveryDraftSyncState,
    initialResumeProjectId,
    setProjectName,
    showToast,
    t,
  ]);

  useEffect(() => {
    if (manualSaveStatus === 'saved' && !hasUnsavedChanges) {
      const draft = loadWorkspaceRecoveryDraft();
      if (draft && authIdentity && canRestoreWorkspaceDraft(draft.sourceAuthIdentity, draft.preview.projectId, authIdentity)) {
        clearWorkspaceRecoveryDraft();
      }
      setShowWorkspaceRecoveryNotice(false);
    }
  }, [authIdentity, hasUnsavedChanges, manualSaveStatus]);

  // Keep hasProjectDna in sync when project changes or the drawer closes
  useEffect(() => {
    setHasProjectDna(preview?.projectId ? guestHasProjectDna(preview.projectId, authIdentity) : false);
  }, [authIdentity, preview?.projectId, showProjectDna]);

  const detectCanvasModeFromPayload = useCallback((payloadLike: unknown): CanvasMode | null => {
    return detectCanvasPayloadKind(payloadLike);
  }, []);

  const detectCanvasModeFromSnapshot = useCallback((snapshot: ProjectSnapshotItem): CanvasMode | null => {
    if (snapshot.thought_trace) {
      try {
        const parsed = JSON.parse(snapshot.thought_trace) as Record<string, unknown>;
        const editor = String(parsed.editor ?? '').toLowerCase();
        if (editor === 'tldraw') return 'tldraw';
        if (editor === 'excalidraw') return 'excalidraw';
      } catch {
        // ignore invalid trace format
      }
    }

    return detectCanvasModeFromPayload(snapshot.schema_blob);
  }, [detectCanvasModeFromPayload]);

  const detectCanvasModeFromRecent = useCallback((item: RecentDiagram): CanvasMode | null => {
    if (item.canvas_library === 'tldraw' || item.canvas_library === 'excalidraw') {
      return item.canvas_library;
    }

    const tldrawMode = detectCanvasModeFromPayload(item.tldraw_snapshot ?? null);
    if (tldrawMode) {
      return tldrawMode;
    }

    return detectCanvasModeFromPayload(item.excalidraw_payload ?? null);
  }, [detectCanvasModeFromPayload]);

  const previewSupportsCanvasMode = useCallback((mode: CanvasMode): boolean => {
    if (!preview) return true;
    if (mode === 'tldraw') {
      return detectCanvasModeFromPayload(preview.tldrawSnapshot ?? null) === 'tldraw';
    }

    return detectCanvasModeFromPayload(parseJsonObject(preview.excalidrawPayload)) === 'excalidraw';
  }, [detectCanvasModeFromPayload, preview]);

  const getCanvasModeUnavailableReason = useCallback((mode: CanvasMode): string | null => {
    if (BROWSER_MODE && mode === 'tldraw') return t('browser.excalidrawOnly');
    if (mode === canvasMode) return null;
    if (workspaceInteractionBlocked) {
      return t('workspace.canvasModeBusy');
    }
    if (preview && !previewSupportsCanvasMode(mode)) {
      return t('workspace.canvasModeLocked');
    }
    return null;
  }, [
    canvasMode,
    preview,
    previewSupportsCanvasMode,
    t,
    workspaceInteractionBlocked,
  ]);

  const handleCanvasModeChange = useCallback((mode: CanvasMode) => {
    const unavailableReason = getCanvasModeUnavailableReason(mode);
    if (unavailableReason) {
      showToast(unavailableReason, 'info');
      return;
    }
    if (mode === canvasMode) return;
    clearSelection();
    setCanvasMode(mode);
  }, [canvasMode, clearSelection, getCanvasModeUnavailableReason, showToast]);

  const prepareForGlobalGeneration = useCallback(async (
    signal?: AbortSignal,
  ): Promise<GenerationPreparationResult> => {
    const didPersist = await persistCurrentChangesBeforeGeneration({ signal });
    if (signal?.aborted) {
      showToast(t('workspace.generationCancelled'), 'info');
      return 'cancelled';
    }

    if (!didPersist) {
      showToast(t('workspace.saveBeforeGenerationFailed'), 'error');
      return 'failed';
    }

    clearSelection();
    return 'ready';
  }, [clearSelection, persistCurrentChangesBeforeGeneration, showToast, t]);

  const handleBeforeWorkspaceNavigate = useCallback(async () => {
    if (workspaceInteractionBlocked) {
      handleWorkspaceInteractionBlocked();
      return false;
    }

    if (expiredAuthIdentityRef.current) return saveWorkspaceRecoveryState();
    const didPersist = await persistCurrentChangesBeforeSwitch();
    if (!didPersist) {
      showToast(t('workspace.saveBeforeNavigationFailed'), 'error');
      return false;
    }

    const draft = loadWorkspaceRecoveryDraft();
    if (draft?.sourceAuthIdentity === activeAuthIdentityRef.current) clearWorkspaceRecoveryDraft();
    return true;
  }, [
    handleWorkspaceInteractionBlocked,
    saveWorkspaceRecoveryState,
    persistCurrentChangesBeforeSwitch,
    showToast,
    t,
    workspaceInteractionBlocked,
  ]);

  const runSavedHistorySwitch = useCallback(async (
    applySwitch: () => void | boolean | Promise<void | boolean>,
  ): Promise<boolean> => {
    if (expiredAuthIdentityRef.current) {
      showToast(t('workspace.saveAuthExpired'), 'error');
      return false;
    }
    if (historySwitchInFlightRef.current) {
      showToast(t('workspace.historySwitchNavigationBlocked'), 'info');
      return false;
    }

    if (workspaceInteractionBlocked) {
      handleWorkspaceInteractionBlocked();
      return false;
    }

    historySwitchInFlightRef.current = true;
    setIsHistorySwitching(true);
    const myGen = ++switchGenRef.current;
    const requestAuthIdentity = activeAuthIdentityRef.current;

    try {
      const didPersist = await persistLatestSnapshot({ waitForInFlight: true, showError: true });
      if (!didPersist) {
        showToast(t('workspace.saveBeforeHistorySwitchFailed'), 'error');
        return false;
      }
      if (requestAuthIdentity !== activeAuthIdentityRef.current) return false;
      if (myGen !== switchGenRef.current) return false;

      const draft = loadWorkspaceRecoveryDraft();
      if (draft && requestAuthIdentity && draft.sourceAuthIdentity === requestAuthIdentity) clearWorkspaceRecoveryDraft();
      const applied = await applySwitch();
      return applied !== false && requestAuthIdentity === activeAuthIdentityRef.current && myGen === switchGenRef.current;
    } finally {
      historySwitchInFlightRef.current = false;
      setIsHistorySwitching(false);
    }
  }, [
    handleWorkspaceInteractionBlocked,
    persistLatestSnapshot,
    showToast,
    t,
    workspaceInteractionBlocked,
  ]);

  useEffect(() => {
    if (!hasUnsavedChanges || !preview?.projectId) return undefined;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges, preview?.projectId]);

  const handleResolveSaveConflict = useCallback(() => {
    if (!preview?.projectId) return;

    preserveCanvasDuringHistoryReloadRef.current = 'rebase';
    prepareSaveConflictRetry();
    setHistoryViewMode('project');
    setRecentReloadNonce((prev) => prev + 1);
    setProjectHistoryReloadNonce((prev) => prev + 1);
    setError(null);
    showToast(t('workspace.saveConflictRefreshed'), 'info');
  }, [prepareSaveConflictRetry, preview?.projectId, showToast, t]);

  const handleRecoverMissingProject = useCallback(async () => {
    if (workspaceInteractionBlocked) {
      handleWorkspaceInteractionBlocked();
      return;
    }
    if (isSaveRecoveryActive) return;

    const payload = latestSnapshotRef.current
      ?? parseJsonObject(preview?.tldrawSnapshot)
      ?? parseJsonObject(preview?.excalidrawPayload);

    if (!payload) {
      const message = t('workspace.saveRecoveryNoCanvas');
      setError(message);
      showToast(message, 'error');
      return;
    }

    const recoveredTitle = `${projectName.trim() || t('workspace.untitledProject')} ${t('workspace.recoveredCopySuffix')}`;
    const requestAuthIdentity = activeAuthIdentityRef.current;
    setIsSaveRecoveryActive(true);
    setError(null);

    try {
      const created = await createProject({
        title: recoveredTitle,
        diagram_type: request.diagramType,
        canvas_library: canvasMode,
        source_text: request.prompt || preview?.summary || recoveredTitle,
      });
      if (requestAuthIdentity !== activeAuthIdentityRef.current) return;

      const synced = await syncProjectSchema({
        project_id: created.project_id,
        schema_patch: payload,
        editor: canvasMode,
        base_snapshot_id: null,
        create_snapshot: true,
        version: null,
      });
      if (requestAuthIdentity !== activeAuthIdentityRef.current) return;

      const syncedSignature = getSnapshotDocSignature(synced.latest_schema);
      const splitPayload = splitCanvasPayload(synced.latest_schema);
      beginHistorySwitch(syncedSignature);
      latestSnapshotRef.current = synced.latest_schema;
      activeEditingSnapshotIdRef.current = synced.snapshot_id;
      projectVersionRef.current = synced.version;
      saveProjectName(authIdentity, synced.project_id, recoveredTitle);
      setProjectName(recoveredTitle);
      setPreview((prev) => ({
        requestId: prev?.requestId ?? createId('request'),
        projectId: synced.project_id,
        snapshotId: synced.snapshot_id,
        projectVersion: synced.version,
        diagramId: synced.snapshot_id,
        tldrawSnapshot: splitPayload.tldrawSnapshot,
        excalidrawPayload: splitPayload.excalidrawPayload,
        rawSchemaBlob: synced.latest_schema,
        summary: prev?.summary ?? recoveredTitle,
        previewImage: prev?.previewImage ?? '',
        thumbnailUrl: prev?.thumbnailUrl,
        warnings: prev?.warnings,
        generatedAt: prev?.generatedAt ?? new Date().toISOString(),
      }));
      setHistoryViewMode('project');
      setRecentReloadNonce((prev) => prev + 1);
      setProjectHistoryReloadNonce((prev) => prev + 1);
      showToast(t('workspace.saveRecoveryCopySaved'), 'success');
    } catch (err) {
      console.error('Failed to save recovery copy', err);
      const message = isApiError(err) && err.status === 401
        ? t('workspace.saveAuthExpired')
        : t('workspace.saveRecoveryCopyFailed');
      setError(message);
      showToast(message, 'error');
    } finally {
      setIsSaveRecoveryActive(false);
    }
  }, [
    activeEditingSnapshotIdRef,
    authIdentity,
    beginHistorySwitch,
    canvasMode,
    handleWorkspaceInteractionBlocked,
    isSaveRecoveryActive,
    latestSnapshotRef,
    preview?.excalidrawPayload,
    preview?.summary,
    preview?.tldrawSnapshot,
    projectName,
    projectVersionRef,
    request.diagramType,
    request.prompt,
    setProjectName,
    showToast,
    t,
    workspaceInteractionBlocked,
  ]);

  const handleOpenCreateDiagram = useCallback(() => {
    if (workspaceInteractionBlocked) {
      handleWorkspaceInteractionBlocked();
      return;
    }
    clearActiveCreatePreflight();
    handleOpenCreateDialog();
  }, [clearActiveCreatePreflight, handleOpenCreateDialog, handleWorkspaceInteractionBlocked, workspaceInteractionBlocked]);

  const handleSaveAction = useCallback(() => {
    if (workspaceInteractionBlocked) return;
    if (manualSaveStatus === 'conflict') handleResolveSaveConflict();
    else if (manualSaveStatus === 'missingProject') void handleRecoverMissingProject();
    else if (manualSaveStatus === 'authExpired') handleReauthFromWorkspace();
    else void handleManualSaveSnapshot();
  }, [handleManualSaveSnapshot, handleReauthFromWorkspace, handleRecoverMissingProject, handleResolveSaveConflict, manualSaveStatus, workspaceInteractionBlocked]);

  useEffect(() => {
    const saveShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        event.stopPropagation();
        if (!event.repeat) handleSaveAction();
      }
    };
    window.addEventListener('keydown', saveShortcut, true);
    return () => window.removeEventListener('keydown', saveShortcut, true);
  }, [handleSaveAction]);

  const openCreateDialogFromPrompt = useCallback((promptText: string) => {
    const trimmedPrompt = promptText.trim();
    if (!trimmedPrompt) return;

    setError(null);
    clearActiveCreatePreflight();
    setCreatePrompt(trimmedPrompt);
    setCreateSelectedPillId(diagramTypeToPillId[request.diagramType] ?? 'adaptive');
    setCreateModelIndex(Math.max(0, defaultConfigs.findIndex((config) => config.id === request.llmConfigId)));
    setCreateCanvasIndex(canvasMode === 'tldraw' ? 1 : 0);
    setShowCreateDialog(true);
  }, [
    canvasMode,
    clearActiveCreatePreflight,
    request.diagramType,
    request.llmConfigId,
    setCreateCanvasIndex,
    setCreateModelIndex,
    setCreatePrompt,
    setCreateSelectedPillId,
    setShowCreateDialog,
  ]);

  const handleRetryFailedGeneration = useCallback(async () => {
    if (!failedGenerationDraft || workspaceInteractionBlocked || !beginGenerationStart()) return;

    const preparationAbortController = new AbortController();
    generationPreparationAbortControllerRef.current = preparationAbortController;
    setError(null);
    setGenerationSummary(
      failedGenerationDraft.promptText,
      failedGenerationDraft.diagramType,
      failedGenerationDraft.canvasMode,
    );
    savePendingGenerationDraft(failedGenerationDraft);

    try {
      const preparationResult = await prepareForGlobalGeneration(preparationAbortController.signal);
      if (preparationResult !== 'ready') {
        saveFailedGenerationDraft(failedGenerationDraft);
        return;
      }
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }

      const didGenerate = await generateDiagram({
        request,
        promptText: failedGenerationDraft.promptText,
        diagramType: failedGenerationDraft.diagramType,
        llmConfigId: failedGenerationDraft.llmConfigId,
        canvasMode: failedGenerationDraft.canvasMode,
        recoverPreviewOnFailure: failedGenerationDraft.recoverPreviewOnFailure,
        metadata: failedGenerationDraft.metadata,
      });

      if (didGenerate) {
        clearGenerationFailure();
        scrollCanvasIntoViewOnMobile();
      } else {
        saveFailedGenerationDraft(failedGenerationDraft);
      }
    } finally {
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }
      finishGenerationStart();
    }
  }, [
    beginGenerationStart,
    clearGenerationFailure,
    failedGenerationDraft,
    finishGenerationStart,
    generateDiagram,
    prepareForGlobalGeneration,
    request,
    saveFailedGenerationDraft,
    savePendingGenerationDraft,
    scrollCanvasIntoViewOnMobile,
    setGenerationSummary,
    workspaceInteractionBlocked,
  ]);

  const handleEditFailedGenerationPrompt = useCallback(() => {
    if (!failedGenerationDraft || workspaceInteractionBlocked) return;

    const pillId = diagramTypeToPillId[failedGenerationDraft.diagramType] ?? 'adaptive';
    const modelIndex = Math.max(0, defaultConfigs.findIndex((config) => config.id === failedGenerationDraft.llmConfigId));

    setCreatePrompt(failedGenerationDraft.promptText);
    setCreateSelectedPillId(pillId);
    setCreateModelIndex(modelIndex);
    setCreateCanvasIndex(failedGenerationDraft.canvasMode === 'tldraw' ? 1 : 0);
    clearActiveCreatePreflight();
    setShowCreateDialog(true);
  }, [
    clearActiveCreatePreflight,
    failedGenerationDraft,
    setCreateCanvasIndex,
    setCreateModelIndex,
    setCreatePrompt,
    setCreateSelectedPillId,
    setShowCreateDialog,
    workspaceInteractionBlocked,
  ]);

  const handleGenerateFromDialog = async () => {
    const promptText = createPrompt.trim();
    if (!promptText || workspaceInteractionBlocked || !beginGenerationStart()) return;

    const preparationAbortController = new AbortController();
    generationPreparationAbortControllerRef.current = preparationAbortController;
    try {
      setError(null);
      const selectedLabel = getDiagramTypeLabel(selectedCreateDiagramType, t);
      const selectedLlmConfigId = createModelOptions[createModelIndex]?.id ?? request.llmConfigId;
      const selectedCanvasMode = createCanvasOptions[createCanvasIndex]?.id === 'tldraw' ? 'tldraw' : 'excalidraw';
      const metadata = buildGlobalGenerationMetadata(selectedCanvasMode, {
        selectedDiagramOption: selectedLabel,
        useIcons: String(createUseIcons && selectedCanvasMode === 'excalidraw'),
        projectName: projectName.trim() || '',
        ...(activeCreatePreflight ? { handoffSource: activeCreatePreflight.kind } : {}),
      });
      const creatingNewDocument = createNewDocumentRef.current;
      if (creatingNewDocument) {
        delete metadata.projectId;
        delete metadata.currentSchema;
        delete metadata.projectName;
      }

      clearGenerationFailure();
      setGenerationSummary(promptText, selectedCreateDiagramType, selectedCanvasMode);
      const nextFailedDraft = buildFailedGenerationDraft(
        promptText,
        selectedCreateDiagramType,
        selectedLlmConfigId,
        selectedCanvasMode,
        metadata,
        preview,
      );
      savePendingGenerationDraft(nextFailedDraft);

      const preparationResult = await prepareForGlobalGeneration(preparationAbortController.signal);
      if (preparationResult !== 'ready') {
        saveFailedGenerationDraft(nextFailedDraft);
        return;
      }
      if (creatingNewDocument) {
        rememberCurrentDocument();
        setChatMessages([{ id: 'agent-init', role: 'agent', content: t('workspace.agentReady') },
          { id: createId('msg'), role: 'user', content: promptText }]);
        setChatInput('');
      }
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }

      setShowCreateDialog(false);
      const didGenerate = await generateDiagram({
        request,
        promptText,
        diagramType: selectedCreateDiagramType,
        llmConfigId: selectedLlmConfigId,
        canvasMode: selectedCanvasMode,
        recoverPreviewOnFailure: preview,
        metadata,
      });
      if (didGenerate) {
        createNewDocumentRef.current = false;
        clearStartupGenerationDraft();
        clearActiveCreatePreflight();
        scrollCanvasIntoViewOnMobile();
      } else {
        if (creatingNewDocument) restoreDocumentContext(activeDocumentKey);
        saveFailedGenerationDraft(nextFailedDraft);
      }
    } finally {
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }
      finishGenerationStart();
    }
  };

  const handleLoadDiagram = useCallback(async (source: RecentDiagram | (() => Promise<RecentDiagram>)) => {
    return runSavedHistorySwitch(async () => {
      const loadGuard = getGenerationRunGuard();
      const diagram = typeof source === 'function' ? await source() : source;
      if (getGenerationRunGuard() !== loadGuard) return false;
      const isCurrentDiagram =
        preview?.diagramId === diagram.diagram_id
        || Boolean(diagram.snapshot_id && preview?.snapshotId === diagram.snapshot_id);
      if (isCurrentDiagram) {
        scrollCanvasIntoViewOnMobile();
        return;
      }

      rememberCurrentDocument();
      restoreDocumentContext(workspaceDocumentKey(diagram.project_id, diagram.diagram_id));
      clearSelection();
      setHistoryViewMode(diagram.project_id ? 'project' : 'recent');
      const payload = parseJsonObject(diagram.tldraw_snapshot) ?? parseJsonObject(diagram.excalidraw_payload);
      const itemCanvasMode = detectCanvasModeFromRecent(diagram);
      if (itemCanvasMode) {
        setCanvasMode(itemCanvasMode);
      }
      beginHistorySwitch(getSnapshotDocSignature(payload), diagram.project_version ?? null);
      activeEditingSnapshotIdRef.current = diagram.snapshot_id ?? null;
      latestSnapshotRef.current = payload;
      const splitPayload = splitCanvasPayload(payload);
      const restoredProjectTitle = diagram.summary?.trim();
      if (authIdentity && diagram.project_id && restoredProjectTitle) {
        saveProjectName(authIdentity, diagram.project_id, restoredProjectTitle);
        setProjectName(restoredProjectTitle);
      }

      clearGenerationFailure();
      setPreview({
        diagramId: diagram.diagram_id,
        requestId: diagram.request_id || createId('request'),
        projectId: diagram.project_id ?? undefined,
        snapshotId: diagram.snapshot_id ?? undefined,
        projectVersion: diagram.project_version,
        tldrawSnapshot: splitPayload.tldrawSnapshot,
        excalidrawPayload: splitPayload.excalidrawPayload,
        rawSchemaBlob: payload ?? undefined,
        summary: diagram.summary ?? '',
        previewImage: '',
        generatedAt: diagram.created_at,
        generationReport: diagram.generation_report,
      });
      setRequest((prev) => ({
        ...prev,
        prompt: diagram.prompt,
        diagramType: diagram.diagram_type,
      }));
      setError(null);
      scrollCanvasIntoViewOnMobile();
    });
  }, [activeEditingSnapshotIdRef, authIdentity, beginHistorySwitch, clearGenerationFailure, clearSelection, detectCanvasModeFromRecent, getGenerationRunGuard, latestSnapshotRef, preview?.diagramId, preview?.snapshotId, rememberCurrentDocument, restoreDocumentContext, runSavedHistorySwitch, scrollCanvasIntoViewOnMobile, setProjectName]);

  useEffect(() => {
    // Guard: only process once. window.history.replaceState does NOT update
    // React Router's useLocation(), so location.state.pendingLoadProject would
    // persist across re-runs caused by handleLoadDiagram identity changes.
    if (pendingLoadHandledRef.current) return;
    if (authLoading) return;
    const pendingLoadProject = location.state?.pendingLoadProject;
    if (!pendingLoadProject && !initialResumeProjectId) return;
    pendingLoadHandledRef.current = true;
    // Unsaved recovery data takes precedence over the last server version.
    if (!pendingLoadProject && workspaceRecoveryDraftAppliedRef.current) return;
    const owner = activeAuthIdentityRef.current;
    void handleLoadDiagram(pendingLoadProject ?? (() => fetchProjectDiagram(initialResumeProjectId!)))
      .catch(() => {
        if (owner === activeAuthIdentityRef.current) setError(t('workspace.resumeProjectFailed'));
      });
    // Use React Router navigate so useLocation() sees the cleared state.
    if (pendingLoadProject) navigate(location.pathname, { replace: true, state: {} });
  }, [authLoading, initialResumeProjectId, location.state, handleLoadDiagram, navigate, location.pathname, t]);

  useEffect(() => {
    if (!preview?.projectId || isHistorySwitching || authLoading || canvasOwnerIdentity !== authIdentity) return;
    const search = new URLSearchParams(location.search);
    if (search.get('project') === preview.projectId) return;
    search.set('project', preview.projectId);
    navigate({ pathname: location.pathname, search: search.toString() }, { replace: true, state: location.state });
  }, [authIdentity, canvasOwnerIdentity, authLoading, isHistorySwitching, location.pathname, location.search, location.state, navigate, preview?.projectId]);

  // Handle explicit preflight handoffs from Insights/DNA without auto-generating.
  useEffect(() => {
    if (preflightGenerationHandledRef.current) return;
    if (!initialPreflightGeneration) return;
    preflightGenerationHandledRef.current = true;

    clearStartupGenerationDraft();
    const activePreflight = saveWorkspacePreflightDraft(initialPreflightGeneration)
      ?? initialPreflightGeneration;

    const promptText = activePreflight.promptText;
    const diagramType = activePreflight.diagramType;
    const llmConfigId = activePreflight.llmConfigId;
    const selectedCanvasMode = activePreflight.canvasMode;
    const modelIndex = Math.max(0, defaultConfigs.findIndex((config) => config.id === llmConfigId));

    setRequest((prev) => ({ ...prev, prompt: promptText, diagramType, llmConfigId }));
    setCanvasMode(selectedCanvasMode);
    setCreatePrompt(promptText);
    setCreateSelectedPillId(diagramTypeToPillId[diagramType] ?? 'adaptive');
    setCreateModelIndex(modelIndex);
    setCreateCanvasIndex(selectedCanvasMode === 'tldraw' ? 1 : 0);
    setCreateUseIcons(activePreflight.useIcons === true);
    setActiveCreatePreflight(activePreflight);
    setShowCreateDialog(true);
    navigate(location.pathname, { replace: true, state: {} });
  }, [
    initialPreflightGeneration,
    location.pathname,
    navigate,
    setCreateCanvasIndex,
    setCreateModelIndex,
    setCreatePrompt,
    setCreateSelectedPillId,
    setShowCreateDialog,
  ]);

  // A generation still marked `pending` when the page unloads is downgraded to
  // `failed`, so the next load offers the retry card instead of re-firing the
  // same request unattended.
  useEffect(() => {
    const handleBeforeUnload = () => {
      markStartupGenerationDraftFailed();
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, []);

  // Handle a pending startup draft handed over from Landing/Home/Dashboard.
  useEffect(() => {
    if (pendingGenerationHandledRef.current) return;
    if (!initialStartupDraft || initialStartupDraft.status !== 'pending') return;
    pendingGenerationHandledRef.current = true;
    setStartupGenerationActive(true);
    clearWorkspacePreflightDraft();

    // The draft is already stored; rewriting it here only pushed `updatedAt`
    // forward, which meant the 12h TTL could never expire a stuck draft.
    navigate(location.pathname, { replace: true, state: {} });

    const promptText = initialStartupDraft.promptText;
    const diagramType = initialStartupDraft.diagramType;
    const llmConfigId = initialStartupDraft.llmConfigId;
    const selectedCanvasMode = initialStartupDraft.canvasMode;
    const metadata = initialStartupDraft.metadata ?? { canvasLibrary: selectedCanvasMode };

    setRequest((prev) => ({ ...prev, prompt: promptText, diagramType, llmConfigId }));
    setCanvasMode(selectedCanvasMode);
    setGenerationSummary(promptText, diagramType, selectedCanvasMode);
    setFailedGenerationDraft(null);
    setChatMessages((prev) => {
      const alreadyLogged = prev.some((message) => message.role === 'user' && message.content === promptText);
      return alreadyLogged ? prev : [...prev, { id: createId('msg'), role: 'user', content: promptText }];
    });
    clearSelection();
    setError(null);

    void (async () => {
      try {
        const didGenerate = await generateDiagram({
          request,
          promptText,
          diagramType,
          llmConfigId,
          canvasMode: selectedCanvasMode,
          recoverPreviewOnFailure: preview,
          metadata,
        });
        const failedDraft = buildFailedGenerationDraft(
          promptText,
          diagramType,
          llmConfigId,
          selectedCanvasMode,
          metadata,
          preview,
        );
        if (didGenerate) {
          clearStartupGenerationDraft();
          scrollCanvasIntoViewOnMobile();
        } else {
          saveFailedGenerationDraft(failedDraft, initialStartupDraft.source);
        }
      } finally {
        setStartupGenerationActive(false);
      }
    })();
  }, [
    buildFailedGenerationDraft,
    clearSelection,
    generateDiagram,
    initialStartupDraft,
    location.pathname,
    navigate,
    preview,
    request,
    saveFailedGenerationDraft,
    scrollCanvasIntoViewOnMobile,
    setGenerationSummary,
  ]);

  const handleSelectSnapshot = useCallback(async (snapshot: ProjectSnapshotItem) => {
    await runSavedHistorySwitch(() => {
      if (preview?.snapshotId === snapshot.snapshot_id) {
        scrollCanvasIntoViewOnMobile();
        return;
      }

      clearSelection();
      setHistoryViewMode('project');
      const snapshotCanvasMode = detectCanvasModeFromSnapshot(snapshot);
      if (snapshotCanvasMode) {
        setCanvasMode(snapshotCanvasMode);
      }
      beginHistorySwitch(getSnapshotDocSignature(snapshot.schema_blob), projectVersionRef.current ?? snapshot.project_version ?? null);
      activeEditingSnapshotIdRef.current = snapshot.snapshot_id;
      latestSnapshotRef.current = (snapshot.schema_blob ?? null) as Record<string, unknown> | null;
      const splitPayload = splitCanvasPayload(snapshot.schema_blob);

      clearGenerationFailure();
      setError(null);
      setPreview((prev) => {
        if (prev) {
          return {
            ...prev,
            // Explicit history navigation resets the viewport; saving a new
            // snapshot of the live document must keep selection and zoom.
            requestId: createId('request'),
            projectId: snapshot.project_id,
            snapshotId: snapshot.snapshot_id,
            projectVersion: projectVersionRef.current ?? snapshot.project_version,
            tldrawSnapshot: splitPayload.tldrawSnapshot,
            excalidrawPayload: splitPayload.excalidrawPayload,
            rawSchemaBlob: snapshot.schema_blob,
            generationReport: snapshot.generation_report ?? parseGenerationReport(snapshot.metrics_scores),
          };
        }

        return {
          requestId: createId('request'),
          projectId: snapshot.project_id,
          snapshotId: snapshot.snapshot_id,
          projectVersion: projectVersionRef.current ?? snapshot.project_version,
          diagramId: snapshot.snapshot_id,
          tldrawSnapshot: splitPayload.tldrawSnapshot,
          excalidrawPayload: splitPayload.excalidrawPayload,
          rawSchemaBlob: snapshot.schema_blob,
          generationReport: snapshot.generation_report ?? parseGenerationReport(snapshot.metrics_scores),
          summary: t('workspace.loadedFromSnapshotHistory'),
          previewImage: '',
          generatedAt: snapshot.timestamp,
        };
      });
      scrollCanvasIntoViewOnMobile();
    });
  }, [activeEditingSnapshotIdRef, beginHistorySwitch, clearGenerationFailure, clearSelection, detectCanvasModeFromSnapshot, latestSnapshotRef, preview?.snapshotId, projectVersionRef, runSavedHistorySwitch, scrollCanvasIntoViewOnMobile, t]);

  const handleActivateDocument = useCallback(async (document: WorkspaceDocument) => {
    if (document.key === activeDocumentKey) { scrollCanvasIntoViewOnMobile(); return true; }
    if (!document.projectId) {
      const recent = recentDiagrams.find(item => item.diagram_id === document.diagramId);
      return recent ? handleLoadDiagram(recent) : false;
    }
    try {
      return await handleLoadDiagram(() => fetchProjectDiagram(document.projectId!));
    } catch {
      showToast(t('workspace.resumeProjectFailed'), 'error');
      return false;
    }
  }, [activeDocumentKey, handleLoadDiagram, recentDiagrams, scrollCanvasIntoViewOnMobile, showToast, t]);

  const handleSelectRecentDiagram = useCallback(async (item: RecentDiagram) => {
    if (item.project_id) {
      await handleActivateDocument({ key: workspaceDocumentKey(item.project_id), projectId: item.project_id,
        diagramId: item.diagram_id, title: item.summary || item.prompt });
    } else await handleLoadDiagram(item);
  }, [handleActivateDocument, handleLoadDiagram]);

  const handleCloseDocument = useCallback(async (document: WorkspaceDocument) => {
    if (workspaceInteractionBlocked) return;
    if (document.key !== activeDocumentKey) { closeDocument(document.key); return; }
    const result = closeWorkspaceDocument(openDocuments, document.key, activeDocumentKey);
    const next = result.documents.find(item => item.key === result.activeKey);
    if (next) {
      if (await handleActivateDocument(next)) closeDocument(document.key);
      return;
    }
    await runSavedHistorySwitch(() => {
      closeDocument(document.key);
      clearSelection();
      beginHistorySwitch(getSnapshotDocSignature(null), null);
      latestSnapshotRef.current = null;
      activeEditingSnapshotIdRef.current = null;
      setPreview(null);
      setProjectName(t('workspace.untitledProject'));
      setRequest(initialRequest);
      restoreDocumentContext('draft');
      setHistoryViewMode('recent');
      setOnboardingDismissed(false);
      clearGenerationFailure();
      navigate('/workspace', { replace: true, state: {} });
    });
  }, [activeDocumentKey, activeEditingSnapshotIdRef, beginHistorySwitch, clearGenerationFailure, clearSelection,
    closeDocument, handleActivateDocument, latestSnapshotRef, navigate, openDocuments, restoreDocumentContext,
    runSavedHistorySwitch, setProjectName, t, workspaceInteractionBlocked]);

  const handleNewDocument = useCallback(() => {
    if (workspaceInteractionBlocked) return;
    createNewDocumentRef.current = true;
    handleOpenCreateDiagram();
  }, [handleOpenCreateDiagram, workspaceInteractionBlocked]);

  const handleCreateBlankDocument = useCallback(async () => {
    const titleBase = language === 'zh' ? '未命名画布' : 'Untitled canvas';
    const titles = new Set([...recentDiagrams.map(item => item.summary), ...openDocuments.map(item => item.title)]);
    let title = titleBase;
    let suffix = 2;
    while (titles.has(title)) title = `${titleBase} ${suffix++}`;
    const owner = activeAuthIdentityRef.current;
    try {
      const opened = await handleLoadDiagram(async () => {
        const document = await createBlankCanvasProject({ ...request, id: createId('manual') }, title);
        if (activeAuthIdentityRef.current === owner && document.project_id) saveProjectName(owner, document.project_id, title);
        return document;
      });
      if (opened) { setRecentReloadNonce(value => value + 1); setOnboardingDismissed(true); }
    } catch (error) {
      console.error('Blank canvas creation failed:', error);
      showToast(language === 'zh' ? '无法创建画布，请重试。当前画布已保留。' : 'Could not create a canvas. Your current canvas is kept.', 'error');
    }
  }, [handleLoadDiagram, language, openDocuments, recentDiagrams, request, showToast]);

  const displayedProjectSnapshots = useMemo(
    () => projectSnapshots,
    [projectSnapshots],
  );

  const displayedRecentDiagrams = useMemo(
    () => recentDiagrams,
    [recentDiagrams],
  );

  const isViewingProjectHistory = historyViewMode === 'project' && Boolean(preview?.projectId);
  const visibleItemsCount = isViewingProjectHistory ? displayedProjectSnapshots.length : displayedRecentDiagrams.length;
  const handleShowProjectHistory = useCallback(() => {
    if (workspaceInteractionBlocked) {
      handleWorkspaceInteractionBlocked();
      return;
    }
    if (!preview?.projectId) return;
    setHistoryViewMode('project');
  }, [handleWorkspaceInteractionBlocked, preview?.projectId, workspaceInteractionBlocked]);

  const handleShowRecentDiagrams = useCallback(() => {
    if (workspaceInteractionBlocked) {
      handleWorkspaceInteractionBlocked();
      return;
    }
    setHistoryViewMode('recent');
  }, [handleWorkspaceInteractionBlocked, workspaceInteractionBlocked]);

  useEffect(() => {
    if (!authIdentity && expiredAuthIdentityRef.current) return;
    let stale = false;
    const requestAuthIdentity = authIdentity;

    const load = async () => {
      // Reserve this request's slot in the write order.
      const requestSeq = recentDiagramsWriteSeqRef.current + 1;
      setRecentLoadStatus('loading');
      try {
        const data = await fetchRecentDiagrams(requestAuthIdentity ?? '');
        if (stale || activeAuthIdentityRef.current !== requestAuthIdentity) return;
        // Someone newer (e.g. the post-generation refresh) already published a
        // list while this was in flight, so this response is stale.
        if (recentDiagramsWriteSeqRef.current < requestSeq) {
          commitRecentDiagrams(data as RecentDiagram[]);
        }
        setRecentLoadStatus('ready');
      } catch (err) {
        if (stale || activeAuthIdentityRef.current !== requestAuthIdentity) return;
        console.error('Failed to fetch recent diagrams', err);
        setRecentLoadStatus('failed');
      }
    };

    load();
    return () => {
      stale = true;
    };
    // `location.state` and `t` were in here but unused by the loader: the
    // former changes when this page clears its own route state, the latter on
    // every language switch, and each fired a pointless /projects request.
  }, [authIdentity, commitRecentDiagrams, recentReloadNonce]);

  useEffect(() => {
    const handleGuestImportCompleted = (event: Event) => {
      const importedProjects = (event as CustomEvent<GuestImportCompletedDetail>).detail?.projects ?? {};
      const pendingIdentity = pendingGuestPreviewIdentityRef.current;

      if (pendingIdentity?.projectId) {
        const imported = importedProjects[pendingIdentity.projectId];
        if (imported?.projectId) {
          const importedSnapshotId = pendingIdentity.snapshotId
            ? imported.snapshots[pendingIdentity.snapshotId]
            : undefined;

          setPreview((prev) => prev ? {
            ...prev,
            projectId: imported.projectId,
            // Falling back to the guest snapshot id here while the editing ref
            // was cleared sent `guest_xxx` back as the new account's
            // base_snapshot_id. Drop it instead, so both stay unset.
            snapshotId: importedSnapshotId,
          } : prev);
          activeEditingSnapshotIdRef.current = importedSnapshotId ?? null;
          setHistoryViewMode('project');
          pendingGuestPreviewIdentityRef.current = null;
        }
      }

      setRecentReloadNonce((prev) => prev + 1);
      setProjectHistoryReloadNonce((prev) => prev + 1);
    };

    window.addEventListener(GUEST_IMPORT_COMPLETED_EVENT, handleGuestImportCompleted);
    return () => {
      window.removeEventListener(GUEST_IMPORT_COMPLETED_EVENT, handleGuestImportCompleted);
    };
  }, [activeEditingSnapshotIdRef]);

  useEffect(() => {
    if (!authIdentity && expiredAuthIdentityRef.current) return;
    if (historyViewMode !== 'project' || !preview?.projectId) {
      setProjectSnapshots([]);
      setProjectHistoryLoadStatus('idle');
      return;
    }

    let stale = false;
    const requestProjectId = preview.projectId;
    const requestSnapshotId = preview.snapshotId;
    const requestAuthIdentity = authIdentity;

    const loadProjectSnapshots = async () => {
      setProjectHistoryLoadStatus('loading');
      setProjectSnapshots((currentSnapshots) => {
        if (!currentSnapshots.length) return currentSnapshots;
        return currentSnapshots.every((snapshot) => snapshot.project_id === requestProjectId)
          ? currentSnapshots
          : [];
      });
      try {
        const data = await fetchProjectSnapshots({
          projectId: requestProjectId,
          withTrace: true,
          page: 1,
          pageSize: 20,
        });

        if (stale || activeAuthIdentityRef.current !== requestAuthIdentity) return;

        const snapshots = data.snapshots || [];
        setProjectSnapshots(snapshots);
        setProjectHistoryLoadStatus('ready');

        if (preserveCanvasDuringHistoryReloadRef.current) {
          const allowRebase = preserveCanvasDuringHistoryReloadRef.current === 'rebase';
          preserveCanvasDuringHistoryReloadRef.current = false;
          // Only explicit conflict recovery adopts the newer server revision.
          // Session recovery must keep its original revision to detect conflicts.
          if (allowRebase) {
            projectVersionRef.current = data.project_version ?? null;
            setPreview(prev => prev?.projectId === requestProjectId
              ? { ...prev, projectVersion: data.project_version } : prev);
          }
          return;
        }
        const localSignature = getSnapshotDocSignature(latestSnapshotRef.current);
        if (localSignature && localSignature !== lastSyncedDocSignatureRef.current) return;

        if (!snapshots.length) {
          return;
        }

        // When no snapshot is explicitly selected, auto-pick the newest one.
        // When one IS selected but not found in the list, leave the selection alone
        // rather than silently resetting to snapshots[0].
        const targetSnapshot = requestSnapshotId
          ? (snapshots.find((item) => item.snapshot_id === requestSnapshotId) ?? null)
          : snapshots[0];

        if (!targetSnapshot) {
          return;
        }

        const currentIdentity = previewIdentityRef.current;
        if (
          currentIdentity.projectId !== requestProjectId
          || currentIdentity.snapshotId !== requestSnapshotId
        ) {
          return;
        }

        const savedReport = targetSnapshot.generation_report ?? parseGenerationReport(targetSnapshot.metrics_scores);
        setPreview((prev) => {
          if (!prev || activeAuthIdentityRef.current !== requestAuthIdentity
            || prev.projectId !== requestProjectId || prev.snapshotId !== requestSnapshotId) return prev;
          return { ...prev, generationReport: savedReport, projectVersion: data.project_version };
        });

        projectVersionRef.current = data.project_version ?? null;
        const currentCanvasPayload =
          parseJsonObject(preview?.tldrawSnapshot) ?? parseJsonObject(preview?.excalidrawPayload);
        const currentSignature = getSnapshotDocSignature(currentCanvasPayload);
        const targetSignature = getSnapshotDocSignature(targetSnapshot.schema_blob);

        if (
          targetSnapshot.snapshot_id !== requestSnapshotId
          || currentSignature !== targetSignature
        ) {
          clearSelection();
          // Capture the expected snapshotId from the closure so the functional
          // updater can guard against a concurrent selection change (race condition:
          // the initial-load fetch may resolve after the user clicks a different
          // snapshot, but before React has run this effect's cleanup).
          setPreview((prev) => {
            if (!prev) return prev;
            if (activeAuthIdentityRef.current !== requestAuthIdentity) return prev;
            if (prev.projectId !== requestProjectId || prev.snapshotId !== requestSnapshotId) return prev;
            beginHistorySwitch(targetSignature, data.project_version ?? null);
            latestSnapshotRef.current = (targetSnapshot.schema_blob ?? null) as Record<string, unknown> | null;
            activeEditingSnapshotIdRef.current = targetSnapshot.snapshot_id;
            return {
              ...prev,
              projectId: targetSnapshot.project_id,
              snapshotId: targetSnapshot.snapshot_id,
              projectVersion: data.project_version,
              generationReport: savedReport,
              ...splitCanvasPayload(targetSnapshot.schema_blob),
            };
          });
        }
      } catch (err) {
        if (stale || activeAuthIdentityRef.current !== requestAuthIdentity) return;
        preserveCanvasDuringHistoryReloadRef.current = false;
        console.error('Failed to fetch project snapshots', err);
        setProjectHistoryLoadStatus('failed');
      }
    };

    loadProjectSnapshots();

    return () => {
      stale = true;
    };
    // Intentionally do not depend on preview canvas payload. Local edits update
    // preview in-place; reloading snapshots on every payload change can replace
    // fresh unsaved edits with the older server copy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    beginHistorySwitch,
    authIdentity,
    clearSelection,
    historyViewMode,
    projectHistoryReloadNonce,
    preview?.projectId,
    preview?.snapshotId,
    t,
  ]);

  const handleSendChatMessage = useCallback(async (contentOverride?: string) => {
    const content = (contentOverride ?? chatInput).trim();
    if (!content || workspaceInteractionBlocked) return;

    if (!preview) {
      setChatInput('');
      openCreateDialogFromPrompt(content);
      return;
    }

    const currentSchema = latestSnapshotRef.current;
    const validSelectedNodeIds = getValidSelectedNodeIds(currentSchema);
    const hadSelection = selectedNodeIds.length > 0;
    const hasSelection = validSelectedNodeIds.length > 0;

    if (hadSelection && !hasSelection) {
      const selectionExpiredMessage = t('workspace.selectionExpired');
      clearSelection();
      setError(selectionExpiredMessage);
      setChatMessages((prev) => [...prev, {
        id: createId('msg'),
        role: 'agent',
        content: selectionExpiredMessage,
      }]);
      return;
    }

    const isGlobalGeneration = !hasSelection;
    if (isGlobalGeneration && !beginGenerationStart()) return;

    setChatMessages((prev) => [...prev, { id: createId('msg'), role: 'user', content }]);
    if (contentOverride === undefined) {
      setChatInput('');
    }
    setError(null);

    if (hadSelection && validSelectedNodeIds.length !== selectedNodeIds.length) {
      setSelectedNodeIds(validSelectedNodeIds);
    }

    // Use local edit API when nodes are selected
    if (hasSelection && currentSchema) {
      if (expiredAuthIdentityRef.current) {
        showToast(t('workspace.saveAuthExpired'), 'error');
        return;
      }
      const runGuard = getGenerationRunGuard();
      setIsLocalEditing(true);
      try {
        const localEditSchema = canvasMode === 'tldraw'
          ? normalizeTldrawSchemaForLocalEdit(currentSchema)
          : currentSchema;
        const result = await apiDiagramService.editDiagramLocal({
          current_schema: localEditSchema,
          selected_node_ids: validSelectedNodeIds,
          instruction: content,
          canvas_library: canvasMode,
          project_id: preview?.projectId,
        });
        if (getGenerationRunGuard() !== runGuard) return;

        // Merge delta into current schema
        const mergedSchema = mergeDeltaIntoSchema(
          currentSchema,
          result.modified_nodes,
          canvasMode,
          validSelectedNodeIds,
        );
        const mergedNodeIds = new Set(getAllNodeIds(mergedSchema));
        setSelectedNodeIds(validSelectedNodeIds.filter((id) => mergedNodeIds.has(id)));

        // Update preview with merged schema (in-place update, no new snapshot)
        latestSnapshotRef.current = mergedSchema;
        const splitPayload = splitCanvasPayload(mergedSchema);
        setPreview((prev) => prev ? {
          ...prev,
          tldrawSnapshot: splitPayload.tldrawSnapshot,
          excalidrawPayload: splitPayload.excalidrawPayload,
          rawSchemaBlob: mergedSchema,
          generationReport: prev.generationReport ? { ...prev.generationReport, qualityStatus: 'edited' } : undefined,
        } : null);

        const didSaveLocalEdit = await persistLatestSnapshot({
          waitForInFlight: true,
          showError: true,
          requireProject: true,
        });
        if (getGenerationRunGuard() !== runGuard) return;

        const localEditSaveFailureMessage = preview?.projectId
          ? t('workspace.localEditSaveFailed')
          : t('workspace.localEditSaveCopyNeeded');
        setChatMessages((prev) => [...prev, {
          id: createId('msg'),
          role: 'agent',
          content: didSaveLocalEdit
            ? t('workspace.localEditSaved').replace('{count}', String(validSelectedNodeIds.length))
            : localEditSaveFailureMessage,
        }]);
        if (!didSaveLocalEdit) {
          showToast(localEditSaveFailureMessage, 'error');
        } else {
          scrollCanvasIntoViewOnMobile();
        }
      } catch (err) {
        const isAuthExpiredLocalEdit = isApiError(err) && err.status === 401;
        if (getGenerationRunGuard() !== runGuard
          && !(isAuthExpiredLocalEdit && activeAuthIdentityRef.current === null)) return;
        const failureMessage = getLocalEditFailureMessage(err);
        // Preserve a failed instruction without overwriting a newer draft.
        setChatInput(draft => draft || content);
        setError(failureMessage);
        showToast(failureMessage, 'error');
        setChatMessages((prev) => [...prev, {
          id: createId('msg'),
          role: 'agent',
          content: failureMessage,
        }]);
      } finally {
        if (getGenerationRunGuard() === runGuard) setIsLocalEditing(false);
      }
      return;
    }

    // Fall back to global regeneration when no selection
    const lockedNodes: string[] | undefined = undefined;
    const metadata = buildGlobalGenerationMetadata(canvasMode);
    clearGenerationFailure();
    setGenerationSummary(content, request.diagramType, canvasMode);
    const nextFailedDraft = buildFailedGenerationDraft(
      content,
      request.diagramType,
      request.llmConfigId,
      canvasMode,
      metadata,
      preview,
    );
    savePendingGenerationDraft(nextFailedDraft);
    const preparationAbortController = new AbortController();
    generationPreparationAbortControllerRef.current = preparationAbortController;
    try {
      const preparationResult = await prepareForGlobalGeneration(preparationAbortController.signal);
      if (preparationResult !== 'ready') {
        saveFailedGenerationDraft(nextFailedDraft);
        setChatMessages((prev) => [...prev, {
          id: createId('msg'),
          role: 'agent',
          content: preparationResult === 'cancelled'
            ? t('workspace.generationCancelledChat')
            : t('workspace.saveBeforeGenerationFailed'),
        }]);
        return;
      }
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }

      const didGenerate = await generateDiagram({
        request: {
          ...request,
          ...(lockedNodes ? { lockedNodes } : {}),
        },
        promptText: content,
        diagramType: request.diagramType,
        llmConfigId: request.llmConfigId,
        canvasMode,
        recoverPreviewOnFailure: preview,
        metadata,
      });
      setChatMessages((prev) => [...prev, {
        id: createId('msg'),
        role: 'agent',
        content: didGenerate ? t('workspace.diagramUpdated') : getGenerationIncompleteMessage(),
      }]);
      if (didGenerate) {
        clearStartupGenerationDraft();
        scrollCanvasIntoViewOnMobile();
      } else {
        saveFailedGenerationDraft(nextFailedDraft);
      }
    } finally {
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }
      finishGenerationStart();
    }
  }, [getGenerationRunGuard, beginGenerationStart, buildGlobalGenerationMetadata, buildFailedGenerationDraft, chatInput, workspaceInteractionBlocked, request, canvasMode, preview, openCreateDialogFromPrompt, latestSnapshotRef, selectedNodeIds, clearSelection, clearGenerationFailure, getGenerationIncompleteMessage, getLocalEditFailureMessage, getValidSelectedNodeIds, persistLatestSnapshot, prepareForGlobalGeneration, generateDiagram, showToast, t, setPreview, finishGenerationStart, scrollCanvasIntoViewOnMobile, setGenerationSummary, saveFailedGenerationDraft, savePendingGenerationDraft]);

  const handleQuickPrompt = useCallback(async (text: string) => {
    const promptText = text.trim();
    if (!promptText || workspaceInteractionBlocked) return;

    if (!preview) {
      openCreateDialogFromPrompt(promptText);
      return;
    }

    const currentSchema = latestSnapshotRef.current;
    const validSelectedNodeIds = getValidSelectedNodeIds(currentSchema);
    const hadSelection = selectedNodeIds.length > 0;

    if (hadSelection && validSelectedNodeIds.length === 0) {
      const selectionExpiredMessage = t('workspace.selectionExpired');
      clearSelection();
      setError(selectionExpiredMessage);
      setChatMessages((prev) => [...prev, {
        id: createId('msg'),
        role: 'agent',
        content: selectionExpiredMessage,
      }]);
      return;
    }

    if (validSelectedNodeIds.length > 0) {
      await handleSendChatMessage(promptText);
      return;
    }

    if (!beginGenerationStart()) return;

    setChatMessages((prev) => [...prev, { id: createId('msg'), role: 'user', content: promptText }]);
    setError(null);
    const metadata = buildGlobalGenerationMetadata(canvasMode);
    clearGenerationFailure();
    setGenerationSummary(promptText, request.diagramType, canvasMode);
    const nextFailedDraft = buildFailedGenerationDraft(
      promptText,
      request.diagramType,
      request.llmConfigId,
      canvasMode,
      metadata,
      preview,
    );
    savePendingGenerationDraft(nextFailedDraft);
    const preparationAbortController = new AbortController();
    generationPreparationAbortControllerRef.current = preparationAbortController;
    try {
      const preparationResult = await prepareForGlobalGeneration(preparationAbortController.signal);
      if (preparationResult !== 'ready') {
        saveFailedGenerationDraft(nextFailedDraft);
        setChatMessages((prev) => [...prev, {
          id: createId('msg'),
          role: 'agent',
          content: preparationResult === 'cancelled'
            ? t('workspace.generationCancelledChat')
            : t('workspace.saveBeforeGenerationFailed'),
        }]);
        return;
      }
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }

      const didGenerate = await generateDiagram({
        request,
        promptText,
        diagramType: request.diagramType,
        llmConfigId: request.llmConfigId,
        canvasMode,
        recoverPreviewOnFailure: preview,
        metadata,
      });
      setChatMessages((prev) => [...prev, {
        id: createId('msg'),
        role: 'agent',
        content: didGenerate ? t('workspace.diagramUpdated') : getGenerationIncompleteMessage(),
      }]);
      if (didGenerate) {
        clearStartupGenerationDraft();
        scrollCanvasIntoViewOnMobile();
      } else {
        saveFailedGenerationDraft(nextFailedDraft);
      }
    } finally {
      if (generationPreparationAbortControllerRef.current === preparationAbortController) {
        generationPreparationAbortControllerRef.current = null;
      }
      finishGenerationStart();
    }
  }, [beginGenerationStart, buildGlobalGenerationMetadata, buildFailedGenerationDraft, workspaceInteractionBlocked, request, canvasMode, preview, openCreateDialogFromPrompt, getValidSelectedNodeIds, handleSendChatMessage, selectedNodeIds, clearSelection, latestSnapshotRef, prepareForGlobalGeneration, generateDiagram, t, finishGenerationStart, scrollCanvasIntoViewOnMobile, setGenerationSummary, clearGenerationFailure, getGenerationIncompleteMessage, saveFailedGenerationDraft, savePendingGenerationDraft]);

  return (
    <div data-canvas-fullscreen={isCanvasFullscreen} className="studio-shell studio-workspace workspace-shell min-h-screen overflow-x-hidden bg-canvas text-slate-900 font-sans selection:bg-brand-100 selection:text-brand-900 dark:bg-slate-950 dark:text-slate-100 dark:selection:bg-brand-500/40 dark:selection:text-white">
      <Header
        variant="studio"
        workspaceTabs={<WorkspaceTabs documents={authLoading ? [] : openDocuments}
          recent={recentDiagrams.map(item => ({ key: workspaceDocumentKey(item.project_id, item.diagram_id),
            projectId: item.project_id ?? undefined, diagramId: item.diagram_id,
            title: (item.project_id ? loadProjectName(authIdentity, item.project_id) : null)
              || item.summary || item.prompt || t('workspace.untitledProject') }))}
          activeKey={activeDocumentKey} title={projectName || t('workspace.untitledProject')}
          dirty={hasUnsavedChanges} saving={manualSaveStatus === 'saving'} busy={workspaceInteractionBlocked || authLoading}
          editingName={isEditingProjectName} nameDraft={projectNameDraft} nameInputRef={projectNameInputRef}
          onNameChange={setProjectNameDraft} onRename={() => { if (preview?.projectId) handleStartProjectNameEdit(); }}
          onSaveName={handleSaveProjectNameEdit} onCancelName={handleCancelProjectNameEdit}
          onActivate={document => { void handleActivateDocument(document); }}
          onClose={document => { void handleCloseDocument(document); }} onNew={handleNewDocument}
          onCreateBlank={() => { void handleCreateBlankDocument(); }} />}
        authTransitionBlocked={authTransitionBlocked}
        onAuthTransitionBlocked={handleAuthTransitionBlocked}
        onBeforeNavigate={handleBeforeWorkspaceNavigate}
        onOpenSettings={() => setShowWorkspaceSettings(true)}
      ><div className="workspace-header-tools" ref={setToolbarTarget} /></Header>
      <WorkspaceSettingsDialog open={showWorkspaceSettings} onClose={() => setShowWorkspaceSettings(false)}
        canvasMode={canvasMode} onCanvasChange={handleCanvasModeChange} getModeUnavailableReason={getCanvasModeUnavailableReason} />

      <main id="main-content" className="workspace-main">
        {/* The canvas is the page content, so there is no room for a visible
            title, but the document still needs one: without it the heading
            outline started at h2 and screen-reader users got no page name. */}
        <h1 className="sr-only">{t('nav.workspace')}</h1>

        {error && (
          <div role="alert" className="mb-4 flex items-center gap-3 rounded-2xl border border-red-200/80 bg-red-50/80 px-4 py-3 text-sm text-red-600 backdrop-blur-xl shrink-0 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300 lg:mb-6">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
            {error}
          </div>
        )}

        {failedGenerationDraft && !isGenerationBusy && (
          <section className="mb-4 rounded-2xl border border-amber-200/80 bg-amber-50/85 px-4 py-3 text-amber-900 shadow-[0_14px_34px_rgba(217,119,6,0.12)] backdrop-blur-xl dark:border-amber-500/35 dark:bg-amber-500/10 dark:text-amber-100 lg:mb-6" aria-label={t('workspace.generationRecoveryTitle')}>
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-300" />
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold">{t('workspace.generationRecoveryTitle')}</h2>
                    <p className="mt-1 text-xs leading-relaxed text-amber-800/85 dark:text-amber-100/80">
                      {t('workspace.generationRecoveryHint')}
                    </p>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 text-[11px] md:grid-cols-[minmax(0,1fr),auto]">
                  <p className="line-clamp-2 min-w-0 break-words rounded-lg border border-amber-200/80 bg-white/65 px-2 py-1.5 font-semibold leading-relaxed dark:border-amber-500/30 dark:bg-slate-950/30">
                    {failedGenerationDraft.promptText}
                  </p>
                  <div className="flex flex-wrap gap-1.5 md:justify-end">
                    <span className="rounded-lg border border-amber-200/80 bg-white/65 px-2 py-1.5 font-medium dark:border-amber-500/30 dark:bg-slate-950/30">
                      {getDiagramTypeLabel(failedGenerationDraft.diagramType, t)}
                    </span>
                    <span className="rounded-lg border border-amber-200/80 bg-white/65 px-2 py-1.5 font-medium dark:border-amber-500/30 dark:bg-slate-950/30">
                      {modelLabel}
                    </span>
                    <span className="rounded-lg border border-amber-200/80 bg-white/65 px-2 py-1.5 font-medium dark:border-amber-500/30 dark:bg-slate-950/30">
                      {getCanvasModeLabel(failedGenerationDraft.canvasMode)}
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2 md:justify-end">
                <button
                  type="button"
                  onClick={() => { void handleRetryFailedGeneration(); }}
                  disabled={workspaceInteractionBlocked}
                  title={workspaceInteractionBlocked ? t('workspace.generationNavigationBlocked') : undefined}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-amber-600 px-3 py-2 text-xs font-semibold text-white shadow-[0_10px_22px_rgba(217,119,6,0.24)] transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
                >
                  <RefreshCcw className="h-3.5 w-3.5" />
                  {t('workspace.generationRetryAction')}
                </button>
                <button
                  type="button"
                  onClick={handleEditFailedGenerationPrompt}
                  disabled={workspaceInteractionBlocked}
                  title={workspaceInteractionBlocked ? t('workspace.generationNavigationBlocked') : undefined}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-amber-200 bg-white/75 px-3 py-2 text-xs font-semibold text-amber-900 transition hover:border-amber-300 hover:bg-white disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 focus-visible:ring-offset-2 dark:border-amber-500/35 dark:bg-slate-950/30 dark:text-amber-100 dark:hover:border-amber-400/50 dark:focus-visible:ring-offset-slate-950"
                >
                  <PencilLine className="h-3.5 w-3.5" />
                  {t('workspace.generationEditPromptAction')}
                </button>
                <button
                  type="button"
                  onClick={clearGenerationFailure}
                  aria-label={t('workspace.generationDismissRecovery')}
                  disabled={workspaceInteractionBlocked}
                  title={workspaceInteractionBlocked ? t('workspace.generationNavigationBlocked') : undefined}
                  className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-amber-200 bg-white/65 text-amber-700 transition hover:border-amber-300 hover:bg-white disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 focus-visible:ring-offset-2 dark:border-amber-500/35 dark:bg-slate-950/30 dark:text-amber-200 dark:hover:border-amber-400/50 dark:focus-visible:ring-offset-slate-950"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </section>
        )}

        <nav className="workspace-mobile-nav" aria-label={t('workspace.panes')}>
          {([
            ['canvas', Columns3, t('workspace.canvasPane')],
            ['chat', MessageSquare, t('workspace.agentName')],
            ['projects', History, t('studio.documentVersions')],
          ] as const).map(([pane, Icon, label]) => (
            <button key={pane} type="button" aria-pressed={pane === 'projects' ? isHistoryOpen : mobilePane === pane}
              ref={pane === 'projects' ? mobileHistoryRef : undefined}
              disabled={pane === 'projects' && (!preview?.projectId || workspaceInteractionBlocked)}
              aria-controls={pane === 'projects' ? 'workspace-history-popover' : `workspace-pane-${pane}`} onClick={() => {
                if (pane === 'projects') { setIsHistoryOpen(value => !value); handleShowProjectHistory(); }
                else { setIsHistoryOpen(false); setMobilePane(pane); }
              }}>
              <Icon size={16} aria-hidden="true" />{label}
              {pane === 'chat' && selectedNodeIds.length > 0 && <span className="workspace-selection-dot" />}
            </button>
          ))}
        </nav>

        <div ref={fullscreenRootRef} className="workspace-grid" data-fullscreen={isCanvasFullscreen} data-project-collapsed="true"
          data-chat-collapsed={isCanvasFullscreen || isChatPanelCollapsed || isAssistantFloating} data-mobile-pane={mobilePane}>
          {isCanvasFullscreen && <CanvasFullscreenControls assistantVisible={!isChatPanelCollapsed}
            assistantButtonRef={fullscreenAssistantButtonRef} onToggleAssistant={() => setIsChatPanelCollapsed(value => !value)}
            onExit={handleToggleCanvasFullscreen} />}

          <section id="workspace-pane-canvas" role="tabpanel" aria-label={projectName} ref={workspaceCanvasSectionRef} className="workspace-canvas-pane">
            {isGenerationBusy && (progress || isGenerationStarting || startupGenerationActive) && (
              <div className="mb-2 rounded-2xl border border-brand-200/80 bg-brand-50/70 px-4 py-3 backdrop-blur-xl dark:border-brand-500/30 dark:bg-brand-500/10">
                <div className="flex items-start gap-3">
                  <svg className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-brand-500" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>
                  <div className="min-w-0 flex-1">
                    {progress ? (
                      <>
                        <StageProgress progress={progress} t={t} />
                        {progress.message && (
                          <p className="mt-1 text-xs font-medium leading-relaxed text-brand-700 dark:text-brand-200">
                            {progress.message}
                          </p>
                        )}
                      </>
                    ) : (
                      <span className="text-xs font-semibold text-brand-700 dark:text-brand-300">
                        {t('workspace.generationPreparing')}
                      </span>
                    )}
                  </div>
                  {isGenerating && (
                    <button
                      type="button"
                      onClick={handleCancelActiveGeneration}
                      className="inline-flex min-h-9 shrink-0 items-center justify-center rounded-xl border border-brand-200 bg-white/75 px-3 py-1.5 text-xs font-semibold text-brand-700 transition hover:border-brand-300 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-brand-500/35 dark:bg-slate-950/30 dark:text-brand-200 dark:hover:border-brand-400/55 dark:focus-visible:ring-offset-slate-950"
                    >
                      {t('workspace.stopGeneration')}
                    </button>
                  )}
                </div>

                {activeGenerationSummary && (
                  <div className="mt-3 grid gap-2 border-t border-brand-200/70 pt-3 text-[11px] text-brand-800 dark:border-brand-500/20 dark:text-brand-200 sm:grid-cols-[minmax(0,1fr),auto]">
                    <p className="min-w-0 truncate font-semibold">
                      {activeGenerationSummary.prompt}
                    </p>
                    <div className="flex min-w-0 flex-wrap gap-1.5 sm:justify-end">
                      <span className="rounded-lg border border-brand-200/70 bg-white/65 px-2 py-1 font-medium dark:border-brand-500/30 dark:bg-slate-950/30">
                        {activeGenerationSummary.diagramTypeLabel}
                      </span>
                      <span className="rounded-lg border border-brand-200/70 bg-white/65 px-2 py-1 font-medium dark:border-brand-500/30 dark:bg-slate-950/30">
                        {activeGenerationSummary.modelLabel}
                      </span>
                      <span className="rounded-lg border border-brand-200/70 bg-white/65 px-2 py-1 font-medium dark:border-brand-500/30 dark:bg-slate-950/30">
                        {activeGenerationSummary.canvasLabel}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}
            {canvasMode !== 'excalidraw' && !isGenerationBusy && preview?.generationReport && (
              <GenerationReport report={preview.generationReport} t={t} />
            )}
            {showWorkspaceRecoveryNotice && preview && (
              <section
                role="status"
                aria-live="polite"
                aria-label={t('workspace.workspaceRecoveryNoticeTitle')}
                className="mb-2 rounded-2xl border border-emerald-200/85 bg-emerald-50/85 px-4 py-3 text-emerald-950 shadow-[0_14px_34px_rgba(16,185,129,0.12)] backdrop-blur-xl dark:border-emerald-500/35 dark:bg-emerald-500/10 dark:text-emerald-100"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 items-start gap-3">
                    <Save className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-300" />
                    <div className="min-w-0">
                      <h2 className="text-sm font-semibold">{t('workspace.workspaceRecoveryNoticeTitle')}</h2>
                      <p className="mt-1 text-xs leading-relaxed text-emerald-800/85 dark:text-emerald-100/80">
                        {t('workspace.workspaceRecoveryNoticeHint')}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        if (preview.projectId) {
                          void handleManualSaveSnapshot();
                          return;
                        }
                        void handleRecoverMissingProject();
                      }}
                      disabled={workspaceInteractionBlocked || manualSaveStatus === 'saving' || isSaveRecoveryActive}
                      title={workspaceInteractionBlocked ? workspaceInteractionBlockedReason : undefined}
                      className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white shadow-[0_10px_22px_rgba(16,185,129,0.24)] transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
                    >
                      {manualSaveStatus === 'saving' || isSaveRecoveryActive ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Save className="h-3.5 w-3.5" />
                      )}
                      {manualSaveStatus === 'saving' || isSaveRecoveryActive
                        ? t('workspace.workspaceRecoveryNoticeSaving')
                        : preview.projectId
                          ? t('workspace.workspaceRecoveryNoticeSaveAction')
                          : t('workspace.saveRecoveryBannerAction')}
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowWorkspaceRecoveryNotice(false)}
                      aria-label={t('workspace.workspaceRecoveryNoticeDismiss')}
                      disabled={workspaceInteractionBlocked}
                      title={workspaceInteractionBlocked ? workspaceInteractionBlockedReason : undefined}
                      className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-emerald-200 bg-white/65 text-emerald-700 transition hover:border-emerald-300 hover:bg-white disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:ring-offset-2 dark:border-emerald-500/35 dark:bg-slate-950/30 dark:text-emerald-200 dark:hover:border-emerald-400/50 dark:focus-visible:ring-offset-slate-950"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </section>
            )}
            {shouldOfferGenerationRecovery && (
              <section
                role="alert"
                aria-label={t('workspace.saveRecoveryBannerTitle')}
                className="mb-2 rounded-2xl border border-amber-200/85 bg-amber-50/85 px-4 py-3 text-amber-950 shadow-[0_14px_34px_rgba(217,119,6,0.12)] backdrop-blur-xl dark:border-amber-500/35 dark:bg-amber-500/10 dark:text-amber-100"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 items-start gap-3">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-300" />
                    <div className="min-w-0">
                      <h2 className="text-sm font-semibold">{t('workspace.saveRecoveryBannerTitle')}</h2>
                      <p className="mt-1 text-xs leading-relaxed text-amber-800/85 dark:text-amber-100/80">
                        {t('workspace.saveRecoveryBannerHint')}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => { void handleRecoverMissingProject(); }}
                    disabled={workspaceInteractionBlocked}
                    title={workspaceInteractionBlocked ? workspaceInteractionBlockedReason : undefined}
                    className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-amber-600 px-4 py-2 text-xs font-semibold text-white shadow-[0_10px_22px_rgba(217,119,6,0.24)] transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
                  >
                    {isSaveRecoveryActive ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="h-3.5 w-3.5" />
                    )}
                    {isSaveRecoveryActive
                      ? t('workspace.saveRecoveryBannerSaving')
                      : t('workspace.saveRecoveryBannerAction')}
                  </button>
                </div>
              </section>
            )}
            <div className="relative min-h-[28rem] flex-1 lg:min-h-0">
              {!preview && preflightReviewActive && (
                <div className="absolute inset-0 z-10 flex items-start justify-center overflow-y-auto overscroll-contain p-3 pointer-events-none sm:items-center sm:p-6">
                  <div
                    data-testid="workspace-preflight-review"
                    role="status"
                    className="pointer-events-none w-full max-w-xl rounded-2xl border border-brand-200/70 bg-white/90 p-4 text-left shadow-[0_24px_70px_rgba(82,112,148,0.22)] ring-1 ring-white/80 backdrop-blur-2xl dark:border-brand-500/25 dark:bg-slate-950/88 dark:shadow-[0_26px_80px_rgba(2,6,23,0.58)] dark:ring-white/10 sm:p-5"
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-50 text-brand-500 dark:bg-brand-500/20 dark:text-brand-300">
                        <PencilLine className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <h2 className="text-lg font-bold leading-tight text-slate-900 dark:text-slate-100">
                          {t('workspace.preflightReviewTitle')}
                        </h2>
                        <p className="mt-1 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
                          {t('workspace.preflightReviewHint')}
                        </p>
                      </div>
                    </div>
                    {createPrompt.trim() && (
                      <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50/85 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-900/80">
                        <p className="text-[10px] font-semibold text-brand-600 dark:text-brand-300">
                          {t('workspace.preflightReviewPromptLabel')}
                        </p>
                        <p className="mt-1 line-clamp-3 text-sm leading-relaxed text-slate-700 dark:text-slate-200">
                          {createPrompt.trim()}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}
              {onboardingVisible && (
                <WorkspaceOnboarding
                  onGeneratePrompt={handleQuickPrompt}
                  isGenerating={workspaceInteractionBlocked}
                  initialPrompt={request.prompt}
                  dismissed={onboardingDismissed}
                  onDismissedChange={setOnboardingDismissed}
                />
              )}
              <DiagramCanvasPanel
                toolbarTarget={toolbarTarget}
                initialView={recallDocumentContext(activeDocumentKey)?.view}
                onViewReader={handleViewReader}
                canvasMode={canvasMode}
                preview={preview}
                projectName={projectName}
                saveIndicator={preview?.projectId && !isGenerationBusy ? <WorkspaceSaveIndicator status={sidebarSaveStatus}
                  dirty={hasUnsavedChanges} disabled={workspaceInteractionBlocked} onSave={handleSaveAction} /> : undefined}
                projectNavigation={<WorkspaceHistoryPopover open={isHistoryOpen}
                  disabled={workspaceInteractionBlocked || !preview?.projectId}
                  mobileAnchorRef={isCompactWorkspace ? mobileHistoryRef : undefined}
                  onOpenChange={open => { setIsHistoryOpen(open); if (open) handleShowProjectHistory(); }}>
                  <ProjectSidebar
              historyOnly
              onToggleCollapse={() => setIsHistoryOpen(false)}
              projectName={projectName}
              isEditingProjectName={false}
              projectNameDraft={projectNameDraft}
              onProjectNameDraftChange={setProjectNameDraft}
              onStartEdit={() => {
                if (workspaceInteractionBlocked) {
                  handleWorkspaceInteractionBlocked();
                  return;
                }
                handleStartProjectNameEdit();
              }}
              onSaveEdit={() => {
                if (workspaceInteractionBlocked) {
                  handleWorkspaceInteractionBlocked();
                  return;
                }
                handleSaveProjectNameEdit();
              }}
              onCancelEdit={handleCancelProjectNameEdit}
              projectNameInputRef={projectNameInputRef}
              visibleItemsCount={visibleItemsCount}
              isViewingProjectHistory={isViewingProjectHistory}
              canViewProjectHistory={Boolean(preview?.projectId)}
              displayedProjectSnapshots={displayedProjectSnapshots}
              displayedRecentDiagrams={displayedRecentDiagrams}
              preview={preview}
              onSelectSnapshot={(snapshot) => { void handleSelectSnapshot(snapshot); }}
              onSelectRecentDiagram={(item) => { void handleSelectRecentDiagram(item); }}
              onShowProjectHistory={handleShowProjectHistory}
              onShowRecentDiagrams={handleShowRecentDiagrams}
              onOpenCreateDialog={handleNewDocument}
              isInteractionDisabled={workspaceInteractionBlocked}
              interactionDisabledReason={workspaceInteractionBlockedReason}
              onSaveSnapshot={() => { void handleManualSaveSnapshot(); }}
              onResolveSaveConflict={handleResolveSaveConflict}
              onRecoverMissingProject={() => { void handleRecoverMissingProject(); }}
              onReauth={handleReauthFromWorkspace}
              manualSaveStatus={sidebarSaveStatus}
              hasUnsavedChanges={hasUnsavedChanges}
              recentLoadStatus={recentLoadStatus}
              projectHistoryLoadStatus={projectHistoryLoadStatus}
              onRetryRecentLoad={() => setRecentReloadNonce((prev) => prev + 1)}
              onRetryProjectHistoryLoad={() => setProjectHistoryReloadNonce((prev) => prev + 1)}
              generatingDiagramId={generatingDiagramId}
              hasProjectDna={hasProjectDna}
              onOpenProjectDna={preview?.projectId ? () => setShowProjectDna(true) : undefined}
            />
                </WorkspaceHistoryPopover>}
                onToggleFullscreen={handleToggleCanvasFullscreen}
                isGenerating={isGenerationBusy}
                canvasBusyKind={canvasBusyKind}
                generationMessage={progress?.message ?? null}
                onTldrawSnapshotChange={handleTldrawSnapshotChange}
                onExcalidrawSceneChange={handleExcalidrawSceneChange}
                onSelectionChange={setSelectedNodeIds}
              />
            </div>
          </section>

          <div id="workspace-pane-chat" className="workspace-chat-pane" data-overlay={isCanvasFullscreen || (!isCompactWorkspace && (isChatPanelCollapsed || isAssistantFloating))}>
            <AgentChatPanel
              chatMessages={chatMessages}
              chatInput={chatInput}
              onChatInputChange={setChatInput}
              onSendMessage={handleSendChatMessage}
              onQuickPrompt={handleQuickPrompt}
              hasContent={Boolean(preview && latestSnapshotRef.current && inspectCanvasPayload(latestSnapshotRef.current, canvasMode).status === 'valid')}
              isCollapsed={(isCanvasFullscreen || !isCompactWorkspace) && isChatPanelCollapsed}
              isFloating={isCanvasFullscreen || (!isCompactWorkspace && isAssistantFloating)}
              showLauncher={!isCanvasFullscreen}
              onToggleDock={isCanvasFullscreen ? undefined : () => setIsAssistantFloating(value => !value)}
              onToggleCollapse={() => {
                setIsChatPanelCollapsed(prev => !prev);
                if (isCanvasFullscreen) requestAnimationFrame(() => fullscreenAssistantButtonRef.current?.focus({ preventScroll: true }));
              }}
              isGenerating={workspaceInteractionBlocked}
              busyKind={canvasBusyKind}
              selectedCount={validSelectedNodeIdsForChat.length}
              selectionLabel={selectionLabelForChat}
              staleSelectedCount={staleSelectedCountForChat}
              preflightReviewActive={preflightReviewActive}
              startPromptsHandledElsewhere={onboardingVisible && !onboardingDismissed && !isCompactWorkspace && !chatInput.trim()}
            />
          </div>
        </div>
      </main>

      {showProjectDna && preview?.projectId && (
        <ProjectDnaDrawer
          projectId={preview.projectId}
          onClose={() => setShowProjectDna(false)}
        />
      )}

      <CreateDiagramDialog
        useIcons={createUseIcons}
        onUseIconsChange={(value) => {
          setCreateUseIcons(value);
          persistCreatePreflightDraft({ useIcons: value });
        }}
        open={showCreateDialog}
        onClose={() => {
          createNewDocumentRef.current = false;
          setShowCreateDialog(false);
          if (activeCreatePreflight?.source === 'home' && !preview) {
            navigate('/home', { replace: true, state: { initialPrompt: createPrompt,
              initialDiagramType: selectedCreateDiagramType, initialUseIcons: createUseIcons } });
          }
          clearActiveCreatePreflight();
        }}
        prompt={createPrompt}
        onPromptChange={(value) => {
          setCreatePrompt(value);
          persistCreatePreflightDraft({ promptText: value });
        }}
        onGenerate={() => { void handleGenerateFromDialog(); }}
        onCancelGeneration={handleCancelActiveGeneration}
        onEnhance={() => {
          const value = createPrompt.trim();
          if (!value) return;
          const enhancedPrompt = `${value}\n\n${t('home.enhancePromptInstruction')}`;
          setCreatePrompt(enhancedPrompt);
          persistCreatePreflightDraft({ promptText: enhancedPrompt });
        }}
        onSelectPill={(pill) => {
          setCreateSelectedPillId(pill.id);
          // React may run a state updater more than once (StrictMode always
          // does), so the sessionStorage write has to stay outside of it.
          const nextPrompt = buildPromptAfterPillSelection(
            createPrompt,
            pill,
            [...createPills, ...createMorePills],
          );
          setCreatePrompt(nextPrompt);
          persistCreatePreflightDraft({
            promptText: nextPrompt,
            diagramType: pillIdToDiagramType[pill.id] ?? 'automated',
          });
        }}
        selectedPillId={createSelectedPillId}
        pills={createPills}
        morePills={createMorePills}
        modelOptions={createModelOptions}
        modelIndex={createModelIndex}
        onModelChange={(index) => {
          setCreateModelIndex(index);
          persistCreatePreflightDraft({ modelIndex: index });
        }}
        canvasOptions={createCanvasOptions}
        canvasIndex={createCanvasIndex}
        onCanvasChange={(index) => {
          setCreateCanvasIndex(index);
          persistCreatePreflightDraft({ canvasIndex: index });
        }}
        isGenerating={isGenerationBusy}
        isWorkspaceLocked={workspaceInteractionBlocked && !isGenerationBusy}
        workspaceLockedReason={workspaceInteractionBlockedReason}
        progress={progress}
        handoff={activeCreateHandoff}
      />

      <ConfirmDialog
        open={showReauthConfirm}
        title={t('workspace.workspaceRecoverySaveFailedConfirmTitle')}
        description={t('workspace.workspaceRecoverySaveFailedConfirm')}
        confirmLabel={t('workspace.workspaceRecoverySaveFailedConfirmAction')}
        cancelLabel={t('common.cancel')}
        tone="danger"
        onCancel={() => setShowReauthConfirm(false)}
        onConfirm={() => {
          setShowReauthConfirm(false);
          proceedToReauth();
        }}
      />

    </div>
  );
}

export default WorkspacePage;
