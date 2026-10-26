import type { DiagramType } from '../types/api';
import type { CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import { isCanvasLibrary } from '../contracts/canvas';

const STORAGE_KEY = 'evodiagram_startup_generation_draft_v1';
const MAX_DRAFT_AGE_MS = 12 * 60 * 60 * 1000;

const VALID_DIAGRAM_TYPES = new Set<DiagramType>([
  'flow',
  'architecture',
  'sequence',
  'er',
  'mindmap',
  'network',
  'automated',
]);

export type StartupGenerationDraftStatus = 'pending' | 'failed';
export type StartupGenerationDraftSource = 'landing' | 'home' | 'dashboard' | 'gallery' | 'workspace';

export type StartupGenerationDraft = {
  promptText: string;
  diagramType: DiagramType;
  llmConfigId: string;
  canvasMode: CanvasMode;
  metadata?: Record<string, string>;
  status: StartupGenerationDraftStatus;
  source: StartupGenerationDraftSource;
  createdAt: number;
  updatedAt: number;
};

type StartupGenerationDraftInput = Omit<StartupGenerationDraft, 'createdAt' | 'updatedAt'> & {
  createdAt?: number;
  updatedAt?: number;
};

const canUseSessionStorage = () => {
  try {
    return typeof window !== 'undefined' && Boolean(window.sessionStorage);
  } catch {
    return false;
  }
};

const isDiagramType = (value: unknown): value is DiagramType => (
  typeof value === 'string' && VALID_DIAGRAM_TYPES.has(value as DiagramType)
);

const normalizeMetadata = (metadata: unknown): Record<string, string> | undefined => {
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
    return undefined;
  }

  const entries = Object.entries(metadata)
    .filter((entry): entry is [string, string] => (
      typeof entry[0] === 'string' && typeof entry[1] === 'string'
    ));

  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
};

const normalizeDraft = (value: unknown): StartupGenerationDraft | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }

  const raw = value as Partial<StartupGenerationDraft>;
  const promptText = typeof raw.promptText === 'string' ? raw.promptText.trim() : '';
  const llmConfigId = typeof raw.llmConfigId === 'string' ? raw.llmConfigId.trim() : '';
  if (!promptText || !llmConfigId || !isDiagramType(raw.diagramType) || !isCanvasLibrary(raw.canvasMode)) {
    return null;
  }

  const now = Date.now();
  const createdAt = typeof raw.createdAt === 'number' && Number.isFinite(raw.createdAt)
    ? raw.createdAt
    : now;
  const updatedAt = typeof raw.updatedAt === 'number' && Number.isFinite(raw.updatedAt)
    ? raw.updatedAt
    : createdAt;

  if (now - updatedAt > MAX_DRAFT_AGE_MS) {
    return null;
  }

  return {
    promptText,
    diagramType: raw.diagramType,
    llmConfigId,
    canvasMode: raw.canvasMode,
    metadata: normalizeMetadata(raw.metadata),
    status: raw.status === 'failed' ? 'failed' : 'pending',
    source: raw.source === 'landing'
      || raw.source === 'home'
      || raw.source === 'dashboard'
      || raw.source === 'gallery'
      ? raw.source
      : 'workspace',
    createdAt,
    updatedAt,
  };
};

export const saveStartupGenerationDraft = (
  input: StartupGenerationDraftInput,
): StartupGenerationDraft | null => {
  if (!canUseSessionStorage()) return null;

  const now = Date.now();
  const draft = normalizeDraft({
    ...input,
    createdAt: input.createdAt ?? now,
    updatedAt: input.updatedAt ?? now,
  });
  if (!draft) return null;

  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
    return draft;
  } catch {
    return null;
  }
};

export const loadStartupGenerationDraft = (): StartupGenerationDraft | null => {
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

/**
 * Downgrade a still-pending draft to `failed`.
 *
 * Called on `beforeunload`: a generation that was in flight when the page went
 * away must not silently restart itself on the next load. Leaving it `pending`
 * made the workspace re-fire the same request with no user action, which could
 * loop indefinitely across refreshes and burn the backend rate limit.
 * `createdAt` / `updatedAt` are preserved so the 12h TTL keeps its original
 * anchor.
 */
export const markStartupGenerationDraftFailed = (): void => {
  const draft = loadStartupGenerationDraft();
  if (!draft || draft.status !== 'pending') return;

  saveStartupGenerationDraft({ ...draft, status: 'failed' });
};

export const clearStartupGenerationDraft = (): void => {
  if (!canUseSessionStorage()) return;

  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage cleanup failures
  }
};
