import { type MutableRefObject, type Dispatch, type SetStateAction, useState, useCallback, useRef } from 'react';
import type { DiagramRequest, DiagramResponse, DiagramType } from '../types/api';
import type { GenerationProgress, HistoryViewMode, RecentDiagram } from '../types/app';
import type { CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import { generateDiagramStream } from '../services/apiDiagramService';
import { fetchRecentDiagrams, isApiError, saveDiagram } from '../services/backendApi';
import { isGuest } from '../services/guestStorage';
import { saveProjectName } from '../services/projectPreferences';
import { generatedProjectTitle } from '../utils/projectHistory';
import { createId } from '../constants/app';
import { getSnapshotDocSignature, parseJsonObject } from '../utils/app';

export interface GenerateDiagramDeps {
  setPreview: Dispatch<SetStateAction<DiagramResponse | null>>;
  setRecentDiagrams: Dispatch<SetStateAction<RecentDiagram[]>>;
  setHistoryViewMode: Dispatch<SetStateAction<HistoryViewMode>>;
  latestSnapshotRef: MutableRefObject<Record<string, unknown> | null>;
  activeEditingSnapshotIdRef: MutableRefObject<string | null>;
  lastSyncedDocSignatureRef: MutableRefObject<string | null>;
  setRequest: Dispatch<SetStateAction<DiagramRequest>>;
  setCanvasMode: Dispatch<SetStateAction<CanvasMode>>;
  setError?: Dispatch<SetStateAction<string | null>>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  t: (key: string) => string;
  userId: string;
  authIdentity: string | null;
  projectName: string;
  getRunGuard?: () => string | null;
}

export interface GenerateDiagramParams {
  request: DiagramRequest;
  promptText: string;
  diagramType: DiagramType;
  llmConfigId: string;
  canvasMode: CanvasMode;
  metadata?: Record<string, string>;
  recoverPreviewOnFailure?: DiagramResponse | null;
}

function getGenerationErrorMessage(error: unknown, t: (key: string) => string): string {
  if (isApiError(error)) {
    switch (error.code) {
      case 'generation_guest_unavailable':
        return t('workspace.generationGuestUnavailable');
      case 'generation_auth_expired':
        return t('workspace.generationAuthExpired');
      case 'generation_rate_limited':
        return t('workspace.generationRateLimited');
      case 'generation_invalid_request':
        return t('workspace.generationInvalidRequest');
      case 'generation_stage_failed':
        return t('workspace.generationStageFailed');
      case 'generation_service_failed':
      case 'generation_failed':
      default:
        return t('workspace.generationServiceFailed');
    }
  }

  if (!(error instanceof Error)) {
    return t('app.generationFailed');
  }

  const message = error.message.trim();
  const normalizedMessage = message.toLowerCase();

  if (
    normalizedMessage.includes('failed to fetch')
    || normalizedMessage.includes('networkerror')
    || normalizedMessage.includes('network request failed')
    || normalizedMessage.includes('load failed')
  ) {
    return t('workspace.generationConnectionFailed');
  }

  if (normalizedMessage.includes('generation timeout')) {
    return t('workspace.generationTimedOut');
  }

  if (normalizedMessage.includes('generation cancelled')) {
    return t('workspace.generationCancelled');
  }

  if (normalizedMessage.includes('stream ended without a result event')) {
    return t('workspace.generationStreamIncomplete');
  }

  if (message) {
    return message;
  }

  return t('app.generationFailed');
}

function getBlockingCanvasWarning(response: DiagramResponse): string | null {
  return response.warnings?.find((warning) => (
    warning === 'canvas_payload_empty'
    || warning === 'canvas_payload_invalid'
    || warning === 'canvas_payload_mismatch'
    || warning === 'canvas_payload_missing'
  )) ?? null;
}

function getCanvasPayloadWarningMessage(warning: string, t: (key: string) => string): string {
  switch (warning) {
    case 'canvas_payload_empty':
      return t('workspace.generationCanvasEmpty');
    case 'canvas_payload_invalid':
      return t('workspace.generationCanvasInvalid');
    case 'canvas_payload_mismatch':
      return t('workspace.generationCanvasMismatch');
    case 'canvas_payload_missing':
      return t('workspace.generationCanvasMissing');
    default:
      return t('workspace.generationReturnedUnusableCanvas');
  }
}

function isGenerationCancelledError(error: unknown): boolean {
  return error instanceof Error && error.message.toLowerCase().includes('generation cancelled');
}

export function useGenerateDiagram(deps: GenerateDiagramDeps) {
  const {
    setPreview, setRecentDiagrams, setHistoryViewMode,
    latestSnapshotRef, activeEditingSnapshotIdRef, lastSyncedDocSignatureRef,
    setRequest, setCanvasMode, setError,
    showToast, t, userId, authIdentity, projectName, getRunGuard,
  } = deps;

  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [generatingDiagramId, setGeneratingDiagramId] = useState<string | null>(null);
  const isGeneratingRef = useRef(false);
  const generationAbortControllerRef = useRef<AbortController | null>(null);
  const lastGenerationCancelledRef = useRef(false);

  const cancelGeneration = useCallback(() => {
    generationAbortControllerRef.current?.abort();
  }, []);

  const wasLastGenerationCancelled = useCallback(() => lastGenerationCancelledRef.current, []);

  const generateDiagram = useCallback(async (params: GenerateDiagramParams): Promise<boolean> => {
    const { request, promptText, diagramType, llmConfigId, canvasMode: selectedCanvasMode, metadata } = params;

    if (!promptText || isGeneratingRef.current) return false;

    const runGuard = getRunGuard?.() ?? null;
    const isCurrentRun = () => !getRunGuard || getRunGuard() === runGuard;

    isGeneratingRef.current = true;
    lastGenerationCancelledRef.current = false;
    setIsGenerating(true);
    setProgress(null);
    setError?.(null);
    const abortController = new AbortController();
    generationAbortControllerRef.current = abortController;

    const nextRequest: DiagramRequest = {
      ...request,
      id: createId('request'),
      prompt: promptText,
      useIcons: metadata?.useIcons !== undefined ? metadata.useIcons === 'true' : request.useIcons ?? false,
      diagramType,
      llmConfigId,
      metadata: {
        ...(request.metadata ?? {}),
        ...metadata,
      },
    };

    // When adding a new diagram to an existing project, keep the current canvas
    // visible and stay in project view. Only use the placeholder card + recent
    // view when creating a brand-new project (no projectId in context).
    const isAddingToProject = Boolean(metadata?.projectId);
    const placeholderDiagramId = `generating_${Date.now().toString(36)}`;

    if (!isAddingToProject) {
      const placeholderItem: RecentDiagram = {
        id: Date.now(),
        request_id: nextRequest.id,
        diagram_id: placeholderDiagramId,
        project_id: null,
        snapshot_id: null,
        prompt: promptText,
        diagram_type: diagramType,
        summary: null,
        excalidraw_payload: null,
        tldraw_snapshot: null,
        canvas_library: selectedCanvasMode,
        created_at: new Date().toISOString(),
      };
      setRecentDiagrams((prev) => [placeholderItem, ...prev]);
      setGeneratingDiagramId(placeholderDiagramId);
      setHistoryViewMode('recent');
      const placeholderPreview =
        selectedCanvasMode === 'excalidraw'
          ? { tldrawSnapshot: undefined, excalidrawPayload: JSON.stringify({ elements: [], appState: {}, files: {} }) }
          : { tldrawSnapshot: undefined, excalidrawPayload: '' };
      setPreview({
        requestId: nextRequest.id,
        diagramId: placeholderDiagramId,
        ...placeholderPreview,
        rawSchemaBlob: selectedCanvasMode === 'excalidraw'
          ? { elements: [], appState: {}, files: {} }
          : undefined,
        summary: promptText,
        previewImage: '',
        generatedAt: new Date().toISOString(),
      });
    }

    try {
      const response = await generateDiagramStream(
        nextRequest,
        {
          onStageStart(event) {
            if (!isCurrentRun()) return;
            setProgress((prev) => ({
              ...prev,
              startedAt: prev?.startedAt ?? Date.now(),
              stageStartedAt: Date.now(),
              currentStage: event.stage,
              stageIndex: event.stage_index,
              totalStages: event.total_stages,
              message: t(`workspace.stage_${event.stage}`),
              completedStages: prev?.completedStages ?? [],
            }));
          },
          onStageComplete(event) {
            if (!isCurrentRun()) return;
            setProgress((prev) => prev ? {
              ...prev,
              completedStages: [...prev.completedStages, event.stage],
            } : prev);
          },
          onRefineComplete(event) {
            if (!isCurrentRun()) return;
            if (event.status === 'skipped') {
              setProgress((prev) => prev ? {
                ...prev,
                refinerSkipped: true,
                refinerSkippedMessage: event.message,
              } : prev);
              return;
            }
            const refineStatus = event.status;
            setProgress((prev) => prev ? {
              ...prev,
              refineComplete: {
                fixes_applied: event.fixes_applied,
                status: refineStatus,
                message: event.message,
              },
            } : prev);
            if (event.status === 'completed' && event.fixes_applied > 0) {
              showToast(
                t('workspace.autoFixedIssues').replace('{count}', String(event.fixes_applied)),
                'success',
              );
            }
          },
          onRefineError(event) {
            if (!isCurrentRun()) return;
            setProgress((prev) => prev ? {
              ...prev,
              refinerError: {
                message: event.message,
                detail: event.detail,
              },
            } : prev);
            console.warn(`Refiner degraded: ${event.detail || event.message}`);
          },
          onRefinerSkipped(event) {
            if (!isCurrentRun()) return;
            setProgress((prev) => prev ? {
              ...prev,
              refinerSkipped: true,
              refinerSkippedMessage: event.message,
            } : prev);
          },
          onError(event) {
            if (!isCurrentRun()) return;
            console.warn(`Generation stage "${event.stage}" failed.`);
          },
        },
        { signal: abortController.signal },
      );

      if (!isCurrentRun()) {
        return false;
      }

      const unusableCanvasWarning = getBlockingCanvasWarning(response);
      if (unusableCanvasWarning) {
        const payloadMessage = getCanvasPayloadWarningMessage(unusableCanvasWarning, t);
        setError?.(payloadMessage);
        showToast(payloadMessage, 'error');
        if (!isAddingToProject) {
          setRecentDiagrams((prev) => prev.filter((d) => d.diagram_id !== placeholderDiagramId));
          setPreview((prev) =>
            prev?.diagramId === placeholderDiagramId
              ? params.recoverPreviewOnFailure ?? null
              : prev,
          );
        }
        return false;
      }

      let effectiveResponse = response;
      let guestPersistenceOk = true;

      if (isGuest()) {
        try {
          const saved = await saveDiagram(nextRequest, response, userId);
          effectiveResponse = {
            ...response,
            projectId: saved.projectId ?? response.projectId,
            snapshotId: saved.snapshotId ?? response.snapshotId,
            diagramId: saved.diagramId ?? response.diagramId,
          };
        } catch (saveErr) {
          guestPersistenceOk = false;
          console.error('Failed to save guest diagram locally:', saveErr);
          showToast(t('workspace.guestSaveFailed'), 'error');
        }
      }

      setHistoryViewMode(effectiveResponse.projectId ? 'project' : 'recent');
      const initialSnapshotPayload =
        parseJsonObject(effectiveResponse.tldrawSnapshot) ?? parseJsonObject(effectiveResponse.excalidrawPayload);
      latestSnapshotRef.current = initialSnapshotPayload;
      lastSyncedDocSignatureRef.current = getSnapshotDocSignature(initialSnapshotPayload);
      activeEditingSnapshotIdRef.current = effectiveResponse.snapshotId ?? null;
      if (effectiveResponse.projectId) {
        const title = generatedProjectTitle(projectName, promptText, isAddingToProject);
        saveProjectName(authIdentity, effectiveResponse.projectId, title);
      }
      setPreview(effectiveResponse);

      if (effectiveResponse.persistError) {
        const persistMessage = t('workspace.generationPersistFailed');
        setError?.(persistMessage);
        showToast(persistMessage, 'error');
      }
      // Update the placeholder card with real thumbnail if available
      if (effectiveResponse.thumbnailUrl) {
        setRecentDiagrams((prev) =>
          prev.map((d) =>
            d.diagram_id === placeholderDiagramId
              ? { ...d, thumbnail_url: effectiveResponse.thumbnailUrl }
              : d,
          ),
        );
      }
      setRequest((prev) => ({
        ...prev,
        prompt: promptText,
        diagramType,
        llmConfigId,
      }));
      setCanvasMode(selectedCanvasMode);

      try {
        if (!isGuest() || guestPersistenceOk) {
          const latest = await fetchRecentDiagrams(userId);
          if (!isCurrentRun()) {
            return false;
          }
          setRecentDiagrams(latest as RecentDiagram[]);
        }
      } catch (refreshErr) {
        if (!isCurrentRun()) {
          return false;
        }
        console.warn('Failed to refresh sidebar after generation:', refreshErr);
        showToast(t('workspace.sidebarRefreshAfterGenerationFailed'), 'info');
      }

      return true;
    } catch (err) {
      if (!isCurrentRun()) {
        return false;
      }
      if (!isApiError(err)) {
        console.error('Generation failed:', err);
      }
      const wasCancelled = isGenerationCancelledError(err);
      lastGenerationCancelledRef.current = wasCancelled;
      const errorMessage = getGenerationErrorMessage(err, t);
      if (wasCancelled) {
        showToast(errorMessage, 'info');
      } else {
        setError?.(errorMessage);
        showToast(errorMessage, 'error');
      }
      if (!isAddingToProject) {
        setRecentDiagrams((prev) => prev.filter((d) => d.diagram_id !== placeholderDiagramId));
        setPreview((prev) =>
          prev?.diagramId === placeholderDiagramId
            ? params.recoverPreviewOnFailure ?? null
            : prev,
        );
      }
      return false;
    } finally {
      isGeneratingRef.current = false;
      if (generationAbortControllerRef.current === abortController) {
        generationAbortControllerRef.current = null;
      }
      setIsGenerating(false);
      if (!isAddingToProject) {
        setGeneratingDiagramId(null);
      }
      setProgress(null);
    }
  }, [
    setPreview, setRecentDiagrams, setHistoryViewMode,
    latestSnapshotRef, activeEditingSnapshotIdRef, lastSyncedDocSignatureRef,
    setRequest, setCanvasMode, setError,
    showToast, t, userId, authIdentity, projectName, getRunGuard,
  ]);

  return {
    isGenerating,
    setIsGenerating,
    progress,
    setProgress,
    generatingDiagramId,
    setGeneratingDiagramId,
    cancelGeneration,
    wasLastGenerationCancelled,
    generateDiagram,
  };
}
