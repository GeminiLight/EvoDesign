import type { CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import type { DiagramType } from '../types/api';
import type { CabinId } from '../types/dna';
import { isCanvasLibrary } from '../contracts/canvas';

const STORAGE_KEY = 'evodiagram_workspace_preflight_draft_v1';
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

export type WorkspacePreflightKind = 'gallery' | 'dna' | 'startup';
export type WorkspacePreflightSource = 'landing' | 'home' | 'dashboard' | 'gallery' | 'workspace' | 'dna';

export type WorkspacePreflightRule = {
  cabinId: CabinId;
  title: string;
  preview: string;
};

export type WorkspacePreflightGeneration = {
  kind: WorkspacePreflightKind;
  promptText: string;
  diagramType: DiagramType;
  llmConfigId: string;
  canvasMode: CanvasMode;
  useIcons?: boolean;
  source: WorkspacePreflightSource;
  sourceName?: string;
  sourceDescription?: string;
  rules: WorkspacePreflightRule[];
  ruleCount: number;
  createdAt: number;
  updatedAt: number;
};

type WorkspacePreflightDraftInput = Omit<WorkspacePreflightGeneration, 'createdAt' | 'updatedAt'> & {
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

const isCabinId = (value: unknown): value is CabinId => (
  value === 'structure' || value === 'style' || value === 'layout'
);

const isPreflightKind = (value: unknown): value is WorkspacePreflightKind => (
  value === 'gallery' || value === 'dna' || value === 'startup'
);

const normalizeSource = (value: unknown): WorkspacePreflightSource => (
  value === 'landing'
    || value === 'home'
    || value === 'dashboard'
    || value === 'gallery'
    || value === 'dna'
    || value === 'workspace'
    ? value
    : 'workspace'
);

const normalizeOptionalText = (value: unknown): string | undefined => {
  const text = typeof value === 'string' ? value.trim() : '';
  return text || undefined;
};

const normalizeRules = (value: unknown): WorkspacePreflightRule[] => {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      return [];
    }

    const rule = item as Partial<WorkspacePreflightRule>;
    const title = typeof rule.title === 'string' ? rule.title.trim() : '';
    const preview = typeof rule.preview === 'string' ? rule.preview.trim() : '';
    if (!title || !preview || !isCabinId(rule.cabinId)) {
      return [];
    }

    return [{
      cabinId: rule.cabinId,
      title,
      preview,
    }];
  });
};

const normalizeDraft = (value: unknown): WorkspacePreflightGeneration | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }

  const raw = value as Partial<WorkspacePreflightGeneration>;
  const llmConfigId = typeof raw.llmConfigId === 'string' ? raw.llmConfigId.trim() : '';
  if (!isPreflightKind(raw.kind) || !llmConfigId || !isDiagramType(raw.diagramType) || !isCanvasLibrary(raw.canvasMode)) {
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

  const rules = normalizeRules(raw.rules);
  const rawRuleCount = typeof raw.ruleCount === 'number' && Number.isFinite(raw.ruleCount)
    ? Math.max(0, Math.floor(raw.ruleCount))
    : rules.length;

  return {
    kind: raw.kind,
    promptText: typeof raw.promptText === 'string' ? raw.promptText.trim() : '',
    diagramType: raw.diagramType,
    llmConfigId,
    canvasMode: raw.canvasMode,
    useIcons: raw.useIcons === true && raw.canvasMode === 'excalidraw',
    source: normalizeSource(raw.source),
    sourceName: normalizeOptionalText(raw.sourceName),
    sourceDescription: normalizeOptionalText(raw.sourceDescription),
    rules,
    ruleCount: Math.max(rawRuleCount, rules.length),
    createdAt,
    updatedAt,
  };
};

export const saveWorkspacePreflightDraft = (
  input: WorkspacePreflightDraftInput,
): WorkspacePreflightGeneration | null => {
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

export const loadWorkspacePreflightDraft = (): WorkspacePreflightGeneration | null => {
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

export const clearWorkspacePreflightDraft = (): void => {
  if (!canUseSessionStorage()) return;

  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage cleanup failures
  }
};
