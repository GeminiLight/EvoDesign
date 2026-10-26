import type { DiagramRequest, DiagramResponse } from '../types/api';
import type { CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import { isCanvasLibrary } from '../contracts/canvas';

const STORAGE_KEY = 'evodiagram_workspace_recovery_draft_v1';
const MAX_DRAFT_AGE_MS = 12 * 60 * 60 * 1000;

export type WorkspaceRecoveryDraft = {
  version: 1;
  savedAt: number;
  sourceAuthIdentity: string | null;
  preview: DiagramResponse;
  request: DiagramRequest;
  canvasMode: CanvasMode;
  projectName: string;
  latestSnapshot: Record<string, unknown>;
  activeEditingSnapshotId: string | null;
  lastSyncedDocSignature: string | null;
  projectVersion: number | null;
  hasUnsavedChanges: boolean;
};

type WorkspaceRecoveryDraftInput = Omit<WorkspaceRecoveryDraft, 'version' | 'savedAt' | 'sourceAuthIdentity'> & {
  savedAt?: number;
  sourceAuthIdentity?: string | null;
};

const canUseSessionStorage = () => {
  try {
    return typeof window !== 'undefined' && Boolean(window.sessionStorage);
  } catch {
    return false;
  }
};

const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const normalizeStringOrNull = (value: unknown): string | null => (
  typeof value === 'string' && value.trim() ? value : null
);

const normalizePreview = (value: unknown): DiagramResponse | null => {
  if (!isRecord(value)) return null;

  const diagramId = typeof value.diagramId === 'string' ? value.diagramId : '';
  const requestId = typeof value.requestId === 'string' ? value.requestId : '';
  const generatedAt = typeof value.generatedAt === 'string'
    ? value.generatedAt
    : new Date().toISOString();
  const excalidrawPayload = typeof value.excalidrawPayload === 'string'
    ? value.excalidrawPayload
    : '';

  if (!diagramId || !requestId) {
    return null;
  }

  return {
    diagramId,
    requestId,
    projectId: typeof value.projectId === 'string' ? value.projectId : undefined,
    snapshotId: typeof value.snapshotId === 'string' ? value.snapshotId : undefined,
    projectVersion: typeof value.projectVersion === 'number' ? value.projectVersion : undefined,
    excalidrawPayload,
    tldrawSnapshot: isRecord(value.tldrawSnapshot) ? value.tldrawSnapshot : undefined,
    rawSchemaBlob: isRecord(value.rawSchemaBlob) ? value.rawSchemaBlob : undefined,
    summary: typeof value.summary === 'string' ? value.summary : '',
    previewImage: typeof value.previewImage === 'string' ? value.previewImage : '',
    thumbnailUrl: typeof value.thumbnailUrl === 'string' ? value.thumbnailUrl : undefined,
    warnings: Array.isArray(value.warnings)
      ? value.warnings.filter((item): item is string => typeof item === 'string')
      : undefined,
    generatedAt,
    persistError: Boolean(value.persistError),
  };
};

const normalizeRequest = (value: unknown): DiagramRequest | null => {
  if (!isRecord(value)) return null;

  const id = typeof value.id === 'string' ? value.id : '';
  const prompt = typeof value.prompt === 'string' ? value.prompt : '';
  const diagramType = typeof value.diagramType === 'string' ? value.diagramType : '';
  const style = typeof value.style === 'string' ? value.style : '';
  const refinementLevel = typeof value.refinementLevel === 'string' ? value.refinementLevel : '';
  const llmConfigId = typeof value.llmConfigId === 'string' ? value.llmConfigId : '';

  if (!id || !diagramType || !style || !refinementLevel || !llmConfigId) {
    return null;
  }

  return {
    id,
    prompt,
    diagramType: value.diagramType as DiagramRequest['diagramType'],
    style: value.style as DiagramRequest['style'],
    refinementLevel: value.refinementLevel as DiagramRequest['refinementLevel'],
    constraints: isRecord(value.constraints)
      ? value.constraints as DiagramRequest['constraints']
      : {},
    llmConfigId,
    assets: Array.isArray(value.assets) ? value.assets as DiagramRequest['assets'] : undefined,
    lockedNodes: Array.isArray(value.lockedNodes)
      ? value.lockedNodes.filter((item): item is string => typeof item === 'string')
      : undefined,
    metadata: isRecord(value.metadata)
      ? Object.fromEntries(
          Object.entries(value.metadata).filter(
            (entry): entry is [string, string] => (
              typeof entry[0] === 'string' && typeof entry[1] === 'string'
            ),
          ),
        )
      : undefined,
  };
};

const normalizeDraft = (value: unknown): WorkspaceRecoveryDraft | null => {
  if (!isRecord(value)) return null;

  const savedAt = typeof value.savedAt === 'number' && Number.isFinite(value.savedAt)
    ? value.savedAt
    : 0;
  if (!savedAt || Date.now() - savedAt > MAX_DRAFT_AGE_MS) {
    return null;
  }

  const preview = normalizePreview(value.preview);
  const request = normalizeRequest(value.request);
  const latestSnapshot = isRecord(value.latestSnapshot) ? value.latestSnapshot : null;

  if (!preview || !request || !latestSnapshot || !isCanvasLibrary(value.canvasMode)) {
    return null;
  }

  return {
    version: 1,
    savedAt,
    sourceAuthIdentity: normalizeStringOrNull(value.sourceAuthIdentity),
    preview,
    request,
    canvasMode: value.canvasMode,
    projectName: typeof value.projectName === 'string' ? value.projectName : '',
    latestSnapshot,
    activeEditingSnapshotId: normalizeStringOrNull(value.activeEditingSnapshotId),
    lastSyncedDocSignature: normalizeStringOrNull(value.lastSyncedDocSignature),
    projectVersion: typeof value.projectVersion === 'number' && Number.isFinite(value.projectVersion)
      ? value.projectVersion
      : null,
    hasUnsavedChanges: Boolean(value.hasUnsavedChanges),
  };
};

export const saveWorkspaceRecoveryDraft = (
  input: WorkspaceRecoveryDraftInput,
): boolean => {
  if (!canUseSessionStorage()) return false;

  const draft: WorkspaceRecoveryDraft = {
    ...input,
    version: 1,
    savedAt: input.savedAt ?? Date.now(),
    sourceAuthIdentity: normalizeStringOrNull(input.sourceAuthIdentity),
  };

  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
};

export const loadWorkspaceRecoveryDraft = (): WorkspaceRecoveryDraft | null => {
  if (!canUseSessionStorage()) return null;

  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const draft = normalizeDraft(JSON.parse(raw));
    if (!draft) {
      window.sessionStorage.removeItem(STORAGE_KEY);
    }
    return draft;
  } catch {
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore storage cleanup failures
    }
    return null;
  }
};

export const clearWorkspaceRecoveryDraft = (): void => {
  if (!canUseSessionStorage()) return;

  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage cleanup failures
  }
};
