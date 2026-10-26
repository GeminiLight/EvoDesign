import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef, useState } from 'react';
import type { CanvasLibrary, DiagramResponse } from '../types/api';
import type { TLEditorSnapshot } from '@tldraw/tldraw';
import type { CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import { isApiError, syncProjectSchema } from '../services/backendApi';
import { ApiError } from '../services/httpClient';
import { getSnapshotDocSignature, parseJsonObject, splitCanvasPayload, updateDiagramProjectSnapshotMap } from '../utils/app';

const AUTO_SYNC_DEBOUNCE_MS = 700;
const SNAPSHOT_CHANGE_THROTTLE_MS = 100;
const SAVE_STATUS_RESET_MS = 2400;
const CANCELLED_SYNC_SUPPRESS_MS = 1500;

export type WorkspaceSaveStatus = 'idle' | 'saving' | 'saved' | 'failed' | 'conflict' | 'authExpired' | 'missingProject';

type RestoreRecoveryDraftInput = {
  latestSnapshot: Record<string, unknown>;
  activeEditingSnapshotId?: string | null;
  lastSyncedDocSignature?: string | null;
  projectVersion?: number | null;
  hasUnsavedChanges?: boolean;
};

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export function useDiagramSync(
  preview: DiagramResponse | null,
  setPreview: Dispatch<SetStateAction<DiagramResponse | null>>,
  canvasMode: CanvasMode,
  setError: (error: string | null) => void,
  t: (key: string) => string
) {
  const [manualSaveStatus, setManualSaveStatus] = useState<WorkspaceSaveStatus>('idle');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  const hasUnsavedChangesRef = useRef(false);
  const syncInFlightRef = useRef(false);
  const manualSaveInFlightRef = useRef(false);
  const flushAfterExplicitSaveRef = useRef<() => void>(() => {});
  const autoSyncAbortControllerRef = useRef<AbortController | null>(null);
  const suppressSyncUntilRef = useRef<number>(0);
  const lastSyncedDocSignatureRef = useRef<string | null>(null);
  const hydrationSourceRef = useRef<string | null>(null);
  const latestSnapshotRef = useRef<Record<string, unknown> | null>(null);
  const activeEditingSnapshotIdRef = useRef<string | null>(null);
  const projectVersionRef = useRef<number | null>(null);
  useEffect(() => {
    projectVersionRef.current = preview?.projectVersion ?? null;
  }, [preview?.projectId, preview?.projectVersion]);
  const syncContextVersionRef = useRef(0);
  const lastSaveFailureStatusRef = useRef<WorkspaceSaveStatus | null>(null);
  const autoSyncPausedUntilManualSaveRef = useRef(false);
  const autoSyncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveStatusTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const snapshotChangeThrottleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSnapshotChangeRef = useRef<{ editor: CanvasLibrary } | null>(null);
  const lastSnapshotChangeRunAtRef = useRef(0);
  const pendingAutoSyncRef = useRef<{
    snapshotPayload: Record<string, unknown>;
    signature: string;
    editor: CanvasLibrary;
    projectId: string;
    baseSnapshotId: string | null;
    syncVersion: number;
  } | null>(null);

  const clearAutoSyncTimer = useCallback(() => {
    if (autoSyncTimerRef.current) {
      clearTimeout(autoSyncTimerRef.current);
      autoSyncTimerRef.current = null;
    }
  }, []);

  const clearSaveStatusTimer = useCallback(() => {
    if (saveStatusTimerRef.current) {
      clearTimeout(saveStatusTimerRef.current);
      saveStatusTimerRef.current = null;
    }
  }, []);

  const clearSnapshotChangeThrottle = useCallback(() => {
    if (snapshotChangeThrottleTimerRef.current) {
      clearTimeout(snapshotChangeThrottleTimerRef.current);
      snapshotChangeThrottleTimerRef.current = null;
    }
    pendingSnapshotChangeRef.current = null;
  }, []);

  const setSaveStatus = useCallback((status: WorkspaceSaveStatus) => {
    clearSaveStatusTimer();
    lastSaveFailureStatusRef.current = ['failed', 'conflict', 'authExpired', 'missingProject'].includes(status)
      ? status
      : null;
    setManualSaveStatus(status);
    if (status === 'saved') {
      saveStatusTimerRef.current = setTimeout(() => {
        saveStatusTimerRef.current = null;
        setManualSaveStatus('idle');
      }, SAVE_STATUS_RESET_MS);
    }
  }, [clearSaveStatusTimer]);

  const setUnsavedChanges = useCallback((dirty: boolean) => {
    hasUnsavedChangesRef.current = dirty;
    setHasUnsavedChanges(dirty);
  }, []);

  const getSaveFailure = useCallback((error: unknown): { status: WorkspaceSaveStatus; messageKey: string } => {
    if (isApiError(error)) {
      if (error.status === 409) {
        return { status: 'conflict', messageKey: 'workspace.saveConflict' };
      }
      if (error.status === 401) {
        return { status: 'authExpired', messageKey: 'workspace.saveAuthExpired' };
      }
      if (error.status === 404) {
        return { status: 'missingProject', messageKey: 'workspace.saveProjectMissing' };
      }
    }

    return { status: 'failed', messageKey: 'workspace.saveChangesFailed' };
  }, []);

  const applySaveFailure = useCallback((error: unknown) => {
    const failure = getSaveFailure(error);
    if (['conflict', 'authExpired', 'missingProject'].includes(failure.status)) {
      autoSyncPausedUntilManualSaveRef.current = true;
      clearAutoSyncTimer();
      pendingAutoSyncRef.current = null;
    }
    setSaveStatus(failure.status);
    setError(t(failure.messageKey));
  }, [clearAutoSyncTimer, getSaveFailure, setError, setSaveStatus, t]);

  const beginHistorySwitch = useCallback((signature: string | null, version: number | null = null) => {
    syncContextVersionRef.current += 1;
    suppressSyncUntilRef.current = Date.now() + 1200;
    autoSyncPausedUntilManualSaveRef.current = false;
    clearAutoSyncTimer();
    clearSnapshotChangeThrottle();
    pendingAutoSyncRef.current = null;
    lastSyncedDocSignatureRef.current = signature;
    projectVersionRef.current = version;
    setUnsavedChanges(false);
    setSaveStatus('idle');
  }, [clearAutoSyncTimer, clearSnapshotChangeThrottle, setSaveStatus, setUnsavedChanges]);

  const resetSyncState = useCallback(() => {
    syncContextVersionRef.current += 1;
    suppressSyncUntilRef.current = Date.now() + 1200;
    autoSyncPausedUntilManualSaveRef.current = false;
    clearAutoSyncTimer();
    clearSnapshotChangeThrottle();
    pendingAutoSyncRef.current = null;
    latestSnapshotRef.current = null;
    activeEditingSnapshotIdRef.current = null;
    lastSyncedDocSignatureRef.current = null;
    projectVersionRef.current = null;
    setUnsavedChanges(false);
    setSaveStatus('idle');
  }, [clearAutoSyncTimer, clearSnapshotChangeThrottle, setSaveStatus, setUnsavedChanges]);

  const prepareSaveConflictRetry = useCallback(() => {
    clearAutoSyncTimer();
    pendingAutoSyncRef.current = null;
    autoSyncPausedUntilManualSaveRef.current = true;
    projectVersionRef.current = null;
    setUnsavedChanges(true);
    setSaveStatus('idle');
  }, [clearAutoSyncTimer, setSaveStatus, setUnsavedChanges]);

  const markAuthExpiredPreservingDirtyState = useCallback(() => {
    syncContextVersionRef.current += 1;
    suppressSyncUntilRef.current = Date.now() + 1200;
    autoSyncPausedUntilManualSaveRef.current = true;
    clearAutoSyncTimer();
    clearSnapshotChangeThrottle();
    pendingAutoSyncRef.current = null;

    const fallbackPayload =
      parseJsonObject(preview?.tldrawSnapshot) ?? parseJsonObject(preview?.excalidrawPayload);
    const latestSignature = getSnapshotDocSignature(latestSnapshotRef.current ?? fallbackPayload);
    const hasLocalChanges = Boolean(
      hasUnsavedChangesRef.current
      || (
        latestSignature
        && latestSignature !== lastSyncedDocSignatureRef.current
      ),
    );

    setUnsavedChanges(hasLocalChanges);
    setSaveStatus('authExpired');
    setError(t('workspace.saveAuthExpired'));
  }, [clearAutoSyncTimer, clearSnapshotChangeThrottle, preview?.excalidrawPayload, preview?.tldrawSnapshot, setError, setSaveStatus, setUnsavedChanges, t]);

  const restoreRecoveryDraftSyncState = useCallback((input: RestoreRecoveryDraftInput) => {
    syncContextVersionRef.current += 1;
    suppressSyncUntilRef.current = Date.now() + 1200;
    autoSyncPausedUntilManualSaveRef.current = false;
    clearAutoSyncTimer();
    clearSnapshotChangeThrottle();
    pendingAutoSyncRef.current = null;

    latestSnapshotRef.current = input.latestSnapshot;
    activeEditingSnapshotIdRef.current = input.activeEditingSnapshotId ?? null;
    lastSyncedDocSignatureRef.current = input.lastSyncedDocSignature ?? null;
    projectVersionRef.current = input.projectVersion ?? null;

    const latestSignature = getSnapshotDocSignature(input.latestSnapshot);
    const hasLocalChanges = Boolean(
      input.hasUnsavedChanges
      || (
        latestSignature
        && latestSignature !== lastSyncedDocSignatureRef.current
      ),
    );

    setUnsavedChanges(hasLocalChanges);
    setSaveStatus('idle');
    setError(null);
  }, [clearAutoSyncTimer, clearSnapshotChangeThrottle, setError, setSaveStatus, setUnsavedChanges]);

  const waitForAutoSyncIdle = useCallback(async (
    timeoutMs = 3000,
    signal?: AbortSignal,
  ) => {
    const abortActiveAutoSync = () => {
      autoSyncAbortControllerRef.current?.abort();
    };

    if (signal?.aborted) {
      abortActiveAutoSync();
      return false;
    }

    const deadline = Date.now() + timeoutMs;
    signal?.addEventListener('abort', abortActiveAutoSync, { once: true });
    try {
      while (syncInFlightRef.current && Date.now() < deadline) {
        if (signal?.aborted) {
          return false;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 50));
      }
      return !syncInFlightRef.current;
    } finally {
      signal?.removeEventListener('abort', abortActiveAutoSync);
    }
  }, []);

  const persistLatestSnapshot = useCallback(async (options?: {
    createSnapshot?: boolean;
    showError?: boolean;
    waitForInFlight?: boolean;
    requireProject?: boolean;
    signal?: AbortSignal;
  }): Promise<boolean> => {
    const createSnapshot = Boolean(options?.createSnapshot);
    const showError = Boolean(options?.showError);
    const waitForInFlight = options?.waitForInFlight ?? true;
    const requireProject = Boolean(options?.requireProject);
    const signal = options?.signal;

    if (!preview?.projectId) {
      if (requireProject) {
        setUnsavedChanges(true);
        if (showError) {
          setSaveStatus('missingProject');
          setError(t('workspace.saveProjectMissing'));
        }
        return false;
      }
      setUnsavedChanges(false);
      return true;
    }

    const fallbackPayload =
      parseJsonObject(preview.tldrawSnapshot) ?? parseJsonObject(preview.excalidrawPayload);
    let payload = latestSnapshotRef.current ?? fallbackPayload;
    if (!payload || typeof payload !== 'object') {
      return true;
    }

    let signature = getSnapshotDocSignature(payload);
    if (!signature) {
      return true;
    }

    const projectId = preview.projectId;
    let baseSnapshotId = activeEditingSnapshotIdRef.current ?? preview.snapshotId ?? null;
    const editor = canvasMode === 'excalidraw' ? 'excalidraw' : 'tldraw';
    const syncVersion = syncContextVersionRef.current;

    clearAutoSyncTimer();
    if (signal?.aborted) {
      return false;
    }

    if (syncInFlightRef.current) {
      pendingAutoSyncRef.current = {
        snapshotPayload: payload,
        signature,
        editor,
        projectId,
        baseSnapshotId,
        syncVersion: syncContextVersionRef.current,
      };

      if (!waitForInFlight) {
        return false;
      }

      const idle = await waitForAutoSyncIdle(3000, signal);

      if (!idle || signal?.aborted) {
        return false;
      }

      if (syncVersion !== syncContextVersionRef.current) {
        return false;
      }

      const queuedSync = pendingAutoSyncRef.current;
      pendingAutoSyncRef.current = null;
      if (
        queuedSync
        && queuedSync.syncVersion === syncContextVersionRef.current
        && queuedSync.projectId === projectId
      ) {
        payload = queuedSync.snapshotPayload;
        signature = queuedSync.signature;
        baseSnapshotId = activeEditingSnapshotIdRef.current ?? queuedSync.baseSnapshotId;
      } else {
        const refreshedPayload = latestSnapshotRef.current ?? payload;
        const refreshedSignature = getSnapshotDocSignature(refreshedPayload);
        if (refreshedSignature && refreshedSignature !== signature) {
          payload = refreshedPayload;
          signature = refreshedSignature;
          baseSnapshotId = activeEditingSnapshotIdRef.current ?? baseSnapshotId;
        }
      }

      if (signature === lastSyncedDocSignatureRef.current) {
        setUnsavedChanges(false);
        return true;
      }
    }

    if (signature === lastSyncedDocSignatureRef.current) {
      setUnsavedChanges(false);
      return true;
    }

    syncInFlightRef.current = true;
    try {
      if (!projectId.startsWith('guest_') && (projectVersionRef.current ?? preview?.projectVersion) == null) {
        throw new ApiError('Project revision must be refreshed before saving', 409);
      }
      const result = await syncProjectSchema(
        {
          project_id: projectId,
          schema_patch: payload,
          editor,
          base_snapshot_id: baseSnapshotId,
          create_snapshot: createSnapshot,
          version: projectVersionRef.current ?? preview?.projectVersion,
        },
        { signal },
      );

      if (syncVersion !== syncContextVersionRef.current) {
        return false;
      }

      const serverSignature = getSnapshotDocSignature(result.latest_schema) ?? signature;
      const syncedSignature = hydrationSourceRef.current === serverSignature
        ? getSnapshotDocSignature(latestSnapshotRef.current) ?? serverSignature : serverSignature;
      const localSignatureAfterSync = getSnapshotDocSignature(latestSnapshotRef.current);
      const hasLocalChangesAfterSync = Boolean(
        localSignatureAfterSync && localSignatureAfterSync !== syncedSignature,
      );

      lastSyncedDocSignatureRef.current = syncedSignature;
      autoSyncPausedUntilManualSaveRef.current = false;
      if (!hasLocalChangesAfterSync) {
        latestSnapshotRef.current = result.latest_schema;
      }
      projectVersionRef.current = result.version;
      const splitPayload = splitCanvasPayload(result.latest_schema);

      setPreview((prev) => {
        if (!prev || prev.projectId !== projectId) {
          return prev;
        }

        updateDiagramProjectSnapshotMap(String(prev.diagramId), result.project_id, result.snapshot_id);

        return {
          ...prev,
          snapshotId: result.snapshot_id,
          projectVersion: result.version,
          ...(hasLocalChangesAfterSync
            ? {}
            : {
                tldrawSnapshot: splitPayload.tldrawSnapshot,
                excalidrawPayload: splitPayload.excalidrawPayload,
                rawSchemaBlob: result.latest_schema,
              }),
        };
      });

      activeEditingSnapshotIdRef.current = result.snapshot_id;
      setUnsavedChanges(hasLocalChangesAfterSync);
      setError(null);
      return true;
    } catch (err) {
      if (isAbortError(err)) {
        return false;
      }
      if (!isApiError(err)) {
        console.error('Schema sync failed:', err);
      }
      if (showError && syncVersion === syncContextVersionRef.current) {
        applySaveFailure(err);
      }
      return false;
    } finally {
      syncInFlightRef.current = false;
      if (syncVersion === syncContextVersionRef.current && !manualSaveInFlightRef.current) {
        flushAfterExplicitSaveRef.current();
      }
    }
  }, [applySaveFailure, canvasMode, clearAutoSyncTimer, preview, setError, setPreview, setSaveStatus, setUnsavedChanges, t, waitForAutoSyncIdle]);

  const persistCurrentChangesBeforeSwitch = useCallback(async () => {
    lastSaveFailureStatusRef.current = null;
    const didPersist = await persistLatestSnapshot({
      waitForInFlight: true,
      showError: true,
    });
    // A 401 means the session is already gone, so saving can never succeed
    // again. Reporting failure here would trap the user in the workspace with
    // every navigation cancelled, so let the navigation through; the
    // authExpired banner set by applySaveFailure still warns them.
    return didPersist || lastSaveFailureStatusRef.current === 'authExpired';
  }, [persistLatestSnapshot]);

  const persistCurrentChangesBeforeGeneration = useCallback(async (options?: { signal?: AbortSignal }) => {
    return persistLatestSnapshot({
      waitForInFlight: true,
      showError: true,
      signal: options?.signal,
    });
  }, [persistLatestSnapshot]);

  const runAutoOverwriteSync = useCallback((
    snapshotPayload: Record<string, unknown>,
    signature: string,
    editor: CanvasLibrary,
    projectId: string,
    baseSnapshotId: string | null,
    syncVersion: number,
  ) => {
    const autoSyncAbortController = new AbortController();
    autoSyncAbortControllerRef.current = autoSyncAbortController;
    syncInFlightRef.current = true;
    setSaveStatus('saving');

    void (async () => {
      let syncWasAborted = false;
      try {
        const result = await syncProjectSchema(
          {
            project_id: projectId,
            schema_patch: snapshotPayload,
            editor,
            base_snapshot_id: baseSnapshotId,
            create_snapshot: false,
            version: projectVersionRef.current ?? preview?.projectVersion,
          },
          { signal: autoSyncAbortController.signal },
        );

        if (syncVersion !== syncContextVersionRef.current) {
          return;
        }

        projectVersionRef.current = result.version;
        autoSyncPausedUntilManualSaveRef.current = false;

        setPreview((prev) => {
          if (!prev) return prev;
          if (prev.projectId !== projectId) return prev;
          if (baseSnapshotId && prev.snapshotId && prev.snapshotId !== baseSnapshotId && prev.snapshotId !== result.snapshot_id) {
            return prev;
          }

          updateDiagramProjectSnapshotMap(String(prev.diagramId), result.project_id, result.snapshot_id);

          if (prev.snapshotId === result.snapshot_id && prev.projectVersion === result.version) {
            return prev;
          }

          return {
            ...prev,
            snapshotId: result.snapshot_id,
            projectVersion: result.version,
          };
        });

        const serverSignature = getSnapshotDocSignature(result.latest_schema) ?? signature;
        const syncedSignature = hydrationSourceRef.current === serverSignature
          ? getSnapshotDocSignature(latestSnapshotRef.current) ?? serverSignature : serverSignature;
        const localSignatureAfterSync = getSnapshotDocSignature(latestSnapshotRef.current);
        const hasLocalChangesAfterSync = Boolean(
          localSignatureAfterSync && localSignatureAfterSync !== syncedSignature,
        );

        activeEditingSnapshotIdRef.current = result.snapshot_id;
        lastSyncedDocSignatureRef.current = syncedSignature;
        setUnsavedChanges(hasLocalChangesAfterSync);
        setSaveStatus(hasLocalChangesAfterSync ? 'saving' : 'saved');
        setError(null);
      } catch (err) {
        if (isAbortError(err)) {
          syncWasAborted = true;
          if (syncVersion === syncContextVersionRef.current) {
            suppressSyncUntilRef.current = Date.now() + CANCELLED_SYNC_SUPPRESS_MS;
            pendingAutoSyncRef.current = null;
            setSaveStatus('idle');
          }
          return;
        }
        if (!isApiError(err)) {
          console.error('Auto schema sync failed:', err);
        }
        if (syncVersion === syncContextVersionRef.current) {
          applySaveFailure(err);
        }
      } finally {
        if (autoSyncAbortControllerRef.current === autoSyncAbortController) {
          autoSyncAbortControllerRef.current = null;
        }
        syncInFlightRef.current = false;

        const nextSync = pendingAutoSyncRef.current;
        if (!manualSaveInFlightRef.current && !syncWasAborted) {
          pendingAutoSyncRef.current = null;

          if (
            nextSync
            && nextSync.syncVersion === syncContextVersionRef.current
            && nextSync.signature !== lastSyncedDocSignatureRef.current
          ) {
            runAutoOverwriteSync(
              nextSync.snapshotPayload,
              nextSync.signature,
              nextSync.editor,
              nextSync.projectId,
              nextSync.baseSnapshotId,
              nextSync.syncVersion,
            );
          }
        }
      }
    })();
  }, [applySaveFailure, preview?.projectVersion, setError, setPreview, setSaveStatus, setUnsavedChanges]);

  const scheduleAutoOverwriteSync = useCallback((
    snapshotPayload: Record<string, unknown>,
    signature: string,
    editor: CanvasLibrary,
    projectId: string,
    baseSnapshotId: string | null,
    syncVersion: number,
  ) => {
    clearAutoSyncTimer();
    autoSyncTimerRef.current = setTimeout(() => {
      autoSyncTimerRef.current = null;
      if (syncVersion !== syncContextVersionRef.current || signature === lastSyncedDocSignatureRef.current) return;

      if (syncInFlightRef.current || manualSaveInFlightRef.current) {
        pendingAutoSyncRef.current = {
          snapshotPayload,
          signature,
          editor,
          projectId,
          baseSnapshotId,
          syncVersion,
        };
        return;
      }

      runAutoOverwriteSync(
        snapshotPayload,
        signature,
        editor,
        projectId,
        baseSnapshotId,
        syncVersion,
      );
    }, AUTO_SYNC_DEBOUNCE_MS);
  }, [clearAutoSyncTimer, runAutoOverwriteSync]);

  const applySnapshotChange = useCallback((
    editor: CanvasLibrary,
    snapshot: Record<string, unknown>,
  ) => {
    if (Date.now() < suppressSyncUntilRef.current) {
      return;
    }

    const currentDocSignature = getSnapshotDocSignature(snapshot);
    if (!currentDocSignature) {
      return;
    }

    if (currentDocSignature === lastSyncedDocSignatureRef.current) {
      clearAutoSyncTimer();
      pendingAutoSyncRef.current = null;
      setUnsavedChanges(false);
      setSaveStatus('idle');
      return;
    }

    if (!preview?.projectId) {
      setUnsavedChanges(false);
      return;
    }

    const projectId = preview.projectId;
    const baseSnapshotId = activeEditingSnapshotIdRef.current ?? preview.snapshotId ?? null;
    if (!baseSnapshotId) {
      return;
    }
    const syncVersion = syncContextVersionRef.current;
    setUnsavedChanges(true);
    setPreview(prev => !prev?.generationReport || prev.generationReport.qualityStatus === 'edited'
      ? prev : { ...prev, generationReport: { ...prev.generationReport, qualityStatus: 'edited' } });

    if (autoSyncPausedUntilManualSaveRef.current) {
      clearAutoSyncTimer();
      pendingAutoSyncRef.current = null;
      return;
    }

    if (syncInFlightRef.current || manualSaveInFlightRef.current) {
      pendingAutoSyncRef.current = {
        snapshotPayload: snapshot,
        signature: currentDocSignature,
        editor,
        projectId,
        baseSnapshotId,
        syncVersion,
      };
      return;
    }

    scheduleAutoOverwriteSync(snapshot, currentDocSignature, editor, projectId, baseSnapshotId, syncVersion);
  }, [clearAutoSyncTimer, preview?.projectId, preview?.snapshotId, scheduleAutoOverwriteSync, setPreview, setSaveStatus, setUnsavedChanges]);

  // Deferred throttle runs must see the current project/snapshot context, not
  // the one captured when the timer was scheduled.
  const applySnapshotChangeRef = useRef(applySnapshotChange);
  useEffect(() => {
    applySnapshotChangeRef.current = applySnapshotChange;
  }, [applySnapshotChange]);

  const runSnapshotChange = useCallback((editor: CanvasLibrary) => {
    lastSnapshotChangeRunAtRef.current = Date.now();
    pendingSnapshotChangeRef.current = null;
    // Always read the newest content rather than a snapshot captured when the
    // throttle timer was armed.
    const snapshot = latestSnapshotRef.current;
    if (!snapshot) {
      return;
    }
    applySnapshotChangeRef.current(editor, snapshot);
  }, []);

  const handleSnapshotChange = useCallback((
    editor: CanvasLibrary,
    snapshot: Record<string, unknown>,
  ) => {
    // Stays immediate and unthrottled: other code reads this ref synchronously.
    latestSnapshotRef.current = snapshot;

    // Throttle only the signature computation (a full JSON.stringify of the
    // document) and the auto-sync scheduling. Leading edge keeps the first
    // change responsive; the timer below is the guaranteed trailing edge, so
    // the last change after the user stops interacting always gets through.
    const elapsed = Date.now() - lastSnapshotChangeRunAtRef.current;
    if (snapshotChangeThrottleTimerRef.current === null && elapsed >= SNAPSHOT_CHANGE_THROTTLE_MS) {
      runSnapshotChange(editor);
      return;
    }

    pendingSnapshotChangeRef.current = { editor };
    if (snapshotChangeThrottleTimerRef.current === null) {
      snapshotChangeThrottleTimerRef.current = setTimeout(() => {
        snapshotChangeThrottleTimerRef.current = null;
        const pending = pendingSnapshotChangeRef.current;
        if (!pending) {
          return;
        }
        runSnapshotChange(pending.editor);
      }, Math.max(SNAPSHOT_CHANGE_THROTTLE_MS - elapsed, 0));
    }
  }, [runSnapshotChange]);

  const flushPendingAutoSync = useCallback((options?: { rebaseToActiveSnapshot?: boolean }) => {
    const nextSync = pendingAutoSyncRef.current;
    pendingAutoSyncRef.current = null;

    if (
      !nextSync
      || nextSync.syncVersion !== syncContextVersionRef.current
      || nextSync.signature === lastSyncedDocSignatureRef.current
    ) {
      return;
    }

    runAutoOverwriteSync(
      nextSync.snapshotPayload,
      nextSync.signature,
      nextSync.editor,
      nextSync.projectId,
      options?.rebaseToActiveSnapshot
        ? activeEditingSnapshotIdRef.current ?? nextSync.baseSnapshotId
        : nextSync.baseSnapshotId,
      nextSync.syncVersion,
    );
  }, [runAutoOverwriteSync]);

  const handleTldrawSnapshotChange = useCallback((snapshot: TLEditorSnapshot) => {
    handleSnapshotChange('tldraw', snapshot as unknown as Record<string, unknown>);
  }, [handleSnapshotChange]);

  const handleExcalidrawSceneChange = useCallback((scene: Record<string, unknown>, loadedScene?: Record<string, unknown>) => {
    const sourceSignature = getSnapshotDocSignature(loadedScene);
    if (sourceSignature && (sourceSignature === lastSyncedDocSignatureRef.current
      || sourceSignature === hydrationSourceRef.current)) {
      // Native restoration normalizes versions, order keys and text metrics.
      // Only normalize a known saved baseline; never acknowledge an unsaved AI edit.
      hydrationSourceRef.current = sourceSignature;
      latestSnapshotRef.current = scene;
      lastSyncedDocSignatureRef.current = getSnapshotDocSignature(scene);
      clearAutoSyncTimer();
      pendingAutoSyncRef.current = null;
      setUnsavedChanges(false);
      if (!syncInFlightRef.current && !manualSaveInFlightRef.current) setSaveStatus('idle');
      return;
    }
    hydrationSourceRef.current = null;
    handleSnapshotChange('excalidraw', scene);
  }, [clearAutoSyncTimer, handleSnapshotChange, setSaveStatus, setUnsavedChanges]);

  useEffect(() => {
    flushAfterExplicitSaveRef.current = () => flushPendingAutoSync({ rebaseToActiveSnapshot: true });
  }, [flushPendingAutoSync]);

  const handleManualSaveSnapshot = useCallback(async () => {
    if (!preview?.projectId || manualSaveStatus === 'saving') {
      return;
    }

    if (!hasUnsavedChangesRef.current) {
      setSaveStatus('saved');
      return;
    }

    autoSyncPausedUntilManualSaveRef.current = false;
    setSaveStatus('saving');
    manualSaveInFlightRef.current = true;
    let didSave = false;
    try {
      didSave = await persistLatestSnapshot({
        createSnapshot: true,
        waitForInFlight: true,
        showError: true,
      });
      if (didSave) {
        setSaveStatus(hasUnsavedChangesRef.current ? 'idle' : 'saved');
      }
      if (!didSave) {
        if (!lastSaveFailureStatusRef.current) {
          setSaveStatus('failed');
          setError(t('workspace.saveChangesFailed'));
        }
      }
    } catch (err) {
      console.error('Manual snapshot save failed:', err);
      applySaveFailure(err);
    } finally {
      manualSaveInFlightRef.current = false;
      if (didSave) {
        flushPendingAutoSync({ rebaseToActiveSnapshot: true });
      }
    }
  }, [applySaveFailure, flushPendingAutoSync, manualSaveStatus, persistLatestSnapshot, preview?.projectId, setError, setSaveStatus, t]);

  useEffect(() => () => {
    clearAutoSyncTimer();
    clearSaveStatusTimer();
    // Not flushed on purpose: the deferred body can only touch state and refs
    // that die with this hook, and its only lasting effect would be arming the
    // auto-sync timer that clearAutoSyncTimer() above tears down again.
    clearSnapshotChangeThrottle();
  }, [clearAutoSyncTimer, clearSaveStatusTimer, clearSnapshotChangeThrottle]);

  return {
    manualSaveStatus,
    hasUnsavedChanges,
    latestSnapshotRef,
    activeEditingSnapshotIdRef,
    lastSyncedDocSignatureRef,
    syncInFlightRef,
    projectVersionRef,
    resetSyncState,
    beginHistorySwitch,
    markAuthExpiredPreservingDirtyState,
    restoreRecoveryDraftSyncState,
    prepareSaveConflictRetry,
    persistLatestSnapshot,
    persistCurrentChangesBeforeSwitch,
    persistCurrentChangesBeforeGeneration,
    handleTldrawSnapshotChange,
    handleExcalidrawSceneChange,
    handleManualSaveSnapshot,
  };
}
