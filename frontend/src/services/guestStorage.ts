import { BROWSER_MODE } from './browser/runtime';
import type { DiagramRequest, DiagramResponse, SchemaSyncPayload, SchemaSyncResult, ProjectSnapshotResponse, ProjectSnapshotItem } from '../types/api';
import type { RecentDiagram } from '../types/app';
import type { CabinId, Rule } from '../types/dna';
import { normalizeCanvasLibraryOrNull } from '../contracts/canvas';
import { splitCanvasPayload } from '../utils/app';
import { readLocalStorage } from '../utils/safeLocalStorage';

export type { CabinId, Rule };

const GUEST_DIAGRAMS_KEY = 'evodiagram_guest_diagrams';
const GUEST_DNA_KEY = 'evodiagram_guest_dna';

export function isGuest(): boolean {
  return BROWSER_MODE || !readLocalStorage('auth_token');
}

function guestId(): string {
  return `guest_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

// ---- Diagrams ----

export interface GuestDiagram {
  id: number;
  request_id: string;
  diagram_id: string;
  project_id: string;
  snapshot_id: string;
  prompt: string;
  diagram_type: string;
  style?: string;
  canvas_library?: string;
  summary: string | null;
  excalidraw_payload: Record<string, unknown> | null;
  tldraw_snapshot: Record<string, unknown> | null;
  created_at: string;
  updated_at?: string;
  // Snapshot history for this project
  snapshots: GuestSnapshot[];
}

export interface GuestSnapshot {
  generation_report?: import('../utils/generationReport').GenerationReport;
  snapshot_id: string;
  parent_id: string | null;
  schema_blob: Record<string, unknown>;
  edit_source: string;
  thought_trace: string | null;
  timestamp: string;
}

export interface GuestSaveResult {
  projectId: string;
  snapshotId: string;
  diagramId: string;
  latestSchema: Record<string, unknown>;
}

export class GuestProjectNotFoundError extends Error {
  constructor(projectId: string) {
    super(`Guest project not found: ${projectId}`);
    this.name = 'GuestProjectNotFoundError';
  }
}

function readGuestDiagrams(): GuestDiagram[] {
  try {
    const raw = localStorage.getItem(GUEST_DIAGRAMS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeGuestDiagrams(diagrams: GuestDiagram[]): void {
  localStorage.setItem(GUEST_DIAGRAMS_KEY, JSON.stringify(diagrams));
}

export function guestExportProjects(): GuestDiagram[] {
  return JSON.parse(JSON.stringify(readGuestDiagrams())) as GuestDiagram[];
}

export function guestSaveDiagram(request: DiagramRequest, response: DiagramResponse): GuestSaveResult {
  const diagrams = readGuestDiagrams();

  let excalidrawPayload: Record<string, unknown> | null = null;
  if (response.excalidrawPayload) {
    try {
      const parsed = JSON.parse(response.excalidrawPayload) as unknown;
      excalidrawPayload = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? parsed as Record<string, unknown>
        : null;
    } catch {
      excalidrawPayload = null;
    }
  }

  const canvasLibrary = normalizeCanvasLibraryOrNull(request.metadata?.canvasLibrary)
    ?? (response.tldrawSnapshot ? 'tldraw' : 'excalidraw');
  const projectId = response.projectId || guestId();
  const snapshotId = response.snapshotId || guestId();
  const schemaBlob: Record<string, unknown> = response.rawSchemaBlob ?? response.tldrawSnapshot ?? excalidrawPayload ?? {};
  const splitPayload = splitCanvasPayload(schemaBlob);
  const normalizedExcalidrawPayload = splitPayload.excalidrawPayload
    ? JSON.parse(splitPayload.excalidrawPayload)
    : null;

  const newSnapshot: GuestSnapshot = {
    snapshot_id: snapshotId,
    parent_id: null,
    schema_blob: schemaBlob,
    edit_source: 'AI_GEN',
    generation_report: response.generationReport,
    thought_trace: null,
    timestamp: new Date().toISOString(),
  };

  // Check if this project already exists in storage
  const existingIdx = diagrams.findIndex((d) => d.project_id === projectId);

  if (existingIdx !== -1) {
    // Append snapshot to existing project instead of creating a duplicate
    const existing = diagrams[existingIdx];
    newSnapshot.parent_id = existing.snapshot_id;
    existing.snapshots.push(newSnapshot);
    existing.snapshot_id = snapshotId;
    existing.diagram_id = snapshotId;
    existing.tldraw_snapshot = splitPayload.tldrawSnapshot ?? null;
    existing.excalidraw_payload = normalizedExcalidrawPayload;
    existing.canvas_library = canvasLibrary;
    existing.summary = response.summary ?? existing.summary;
    existing.updated_at = newSnapshot.timestamp;

    // Move project to the top (most recent)
    diagrams.splice(existingIdx, 1);
    diagrams.unshift(existing);
  } else {
    // New project
    const entry: GuestDiagram = {
      id: Date.now(),
      request_id: request.id,
      diagram_id: snapshotId,
      project_id: projectId,
      snapshot_id: snapshotId,
      prompt: request.prompt,
      diagram_type: request.diagramType,
      style: request.style,
      canvas_library: canvasLibrary,
      summary: response.summary ?? null,
      excalidraw_payload: normalizedExcalidrawPayload,
      tldraw_snapshot: splitPayload.tldrawSnapshot ?? null,
      created_at: new Date().toISOString(),
      updated_at: newSnapshot.timestamp,
      snapshots: [newSnapshot],
    };
    diagrams.unshift(entry);
  }

  // Storage failures surface to the caller. Never silently evict saved projects.
  writeGuestDiagrams(diagrams);

  return {
    projectId,
    snapshotId,
    diagramId: snapshotId,
    latestSchema: schemaBlob,
  };
}

export function guestFetchRecentDiagrams(): RecentDiagram[] {
  const diagrams = readGuestDiagrams();
  const getUpdatedAt = (diagram: GuestDiagram) => (
    diagram.updated_at
    || diagram.snapshots?.[diagram.snapshots.length - 1]?.timestamp
    || diagram.created_at
  );
  return diagrams
    .sort((a, b) => new Date(getUpdatedAt(b)).getTime() - new Date(getUpdatedAt(a)).getTime())
    .map((d) => ({
      id: d.id,
      request_id: d.request_id,
      diagram_id: d.diagram_id,
      project_id: d.project_id,
      snapshot_id: d.snapshot_id,
      prompt: d.prompt,
      diagram_type: d.diagram_type as RecentDiagram['diagram_type'],
      summary: d.summary,
      excalidraw_payload: d.excalidraw_payload,
      tldraw_snapshot: d.tldraw_snapshot,
      canvas_library: normalizeCanvasLibraryOrNull(d.canvas_library),
      created_at: d.created_at,
      updated_at: getUpdatedAt(d),
      snapshot_count: d.snapshots?.length ?? 0,
      generation_report: d.snapshots?.find(snapshot => snapshot.snapshot_id === d.snapshot_id)?.generation_report,
    }));
}

export function guestDeleteDiagram(diagramId: string): void {
  const diagrams = readGuestDiagrams();
  writeGuestDiagrams(
    diagrams.filter((d) => d.diagram_id !== diagramId && d.project_id !== diagramId),
  );
}

// ---- Projects / Snapshots ----

export function guestFetchProjectSnapshots(projectId: string): ProjectSnapshotResponse {
  const diagrams = readGuestDiagrams();
  const project = diagrams.find(
    (d) => d.project_id === projectId || d.diagram_id === projectId,
  );

  if (!project || !project.snapshots?.length) {
    return { snapshots: [], page: 1, page_size: 20, total: 0 };
  }

  const items: ProjectSnapshotItem[] = project.snapshots.map((s) => ({
    snapshot_id: s.snapshot_id,
    project_id: project.project_id,
    parent_id: s.parent_id,
    schema_blob: s.schema_blob,
    edit_source: s.edit_source,
    thought_trace: s.thought_trace,
    metrics_scores: null,
    generation_report: s.generation_report,
    timestamp: s.timestamp,
  }));

  return {
    snapshots: items,
    page: 1,
    page_size: 20,
    total: items.length,
  };
}

export function guestSyncProjectSchema(payload: SchemaSyncPayload): SchemaSyncResult {
  const diagrams = readGuestDiagrams();
  const idx = diagrams.findIndex(
    (d) => d.project_id === payload.project_id || d.diagram_id === payload.project_id,
  );

  const newSnapshotId = guestId();

  if (idx !== -1) {
    const project = diagrams[idx];

    // Update the latest schema on the project
    const splitPayload = splitCanvasPayload(payload.schema_patch);
    project.tldraw_snapshot = splitPayload.tldrawSnapshot ?? null;
    project.excalidraw_payload = splitPayload.excalidrawPayload
      ? JSON.parse(splitPayload.excalidrawPayload)
      : null;

    if (!project.snapshots) {
      project.snapshots = [];
    }

    if (payload.create_snapshot) {
      // Create new snapshot
      const parentId = project.snapshots.length > 0
        ? project.snapshots[project.snapshots.length - 1].snapshot_id
        : null;

      project.snapshot_id = newSnapshotId;
      project.snapshots.push({
        snapshot_id: newSnapshotId,
        parent_id: parentId,
        schema_blob: payload.schema_patch,
        edit_source: payload.editor ?? 'tldraw',
        thought_trace: null,
        timestamp: new Date().toISOString(),
      });
    } else {
      // Overwrite mode: update the target snapshot in-place instead of creating a new one
      const targetSnapshot = payload.base_snapshot_id
        ? project.snapshots.find((s) => s.snapshot_id === payload.base_snapshot_id)
        : project.snapshots[project.snapshots.length - 1];

      if (targetSnapshot) {
        if (targetSnapshot.generation_report) {
          targetSnapshot.generation_report = { ...targetSnapshot.generation_report, qualityStatus: 'edited' };
        }
        targetSnapshot.schema_blob = payload.schema_patch;
        targetSnapshot.edit_source = payload.editor ?? 'tldraw';
        targetSnapshot.timestamp = new Date().toISOString();
        project.snapshot_id = targetSnapshot.snapshot_id;
      } else {
        // No snapshots yet — create the first one
        project.snapshot_id = newSnapshotId;
        project.snapshots.push({
          snapshot_id: newSnapshotId,
          parent_id: null,
          schema_blob: payload.schema_patch,
          edit_source: payload.editor ?? 'tldraw',
          thought_trace: null,
          timestamp: new Date().toISOString(),
        });
      }
    }

    project.diagram_id = project.snapshot_id;

    writeGuestDiagrams(diagrams);

    const effectiveSnapshotId = project.snapshot_id ?? newSnapshotId;
    return {
      project_id: project.project_id,
      snapshot_id: effectiveSnapshotId,
      latest_schema: payload.schema_patch,
      edit_source: payload.editor ?? 'tldraw',
      version: 1,
    };
  }

  throw new GuestProjectNotFoundError(payload.project_id);
}

// ---- DNA Rules ----

type DnaRuleLocale = 'en' | 'zh';
type SeedRuleCopy = {
  title: string;
  preview: string;
};
type SeedRule = Rule & {
  copy: Record<DnaRuleLocale, SeedRuleCopy>;
};

const DEFAULT_DNA_LOCALE: DnaRuleLocale = 'en';
const DNA_RULE_LOCALES = new Set<string>(['en', 'zh']);

const seedRules: Record<CabinId, SeedRule[]> = {
  structure: [
    {
      id: 1,
      title: 'Naming preference: User over Client',
      preview: 'Prefer User as the primary actor name in system diagrams.',
      source: 'ai',
      enabled: true,
      pinned: true,
      usageCount: 39,
      updatedAt: '2h',
      copy: {
        en: {
          title: 'Naming preference: User over Client',
          preview: 'Prefer User as the primary actor name in system diagrams.',
        },
        zh: {
          title: '命名偏好：User > Client',
          preview: '在系统设计图中优先使用 User 作为用户实体命名。',
        },
      },
    },
    {
      id: 2,
      title: 'Connection style: bidirectional request/response',
      preview: 'Use bidirectional semantics for request-response relationships to reduce ambiguity.',
      source: 'manual',
      enabled: true,
      pinned: false,
      usageCount: 27,
      updatedAt: '6h',
      copy: {
        en: {
          title: 'Connection style: bidirectional request/response',
          preview: 'Use bidirectional semantics for request-response relationships to reduce ambiguity.',
        },
        zh: {
          title: '连结偏好：请求响应双向表达',
          preview: '对请求-响应关系优先使用双向语义，减少歧义。',
        },
      },
    },
    {
      id: 3,
      title: 'Hierarchy depth: default to three layers',
      preview: 'Use presentation, logic, and data layers as the preferred architecture skeleton.',
      source: 'ai',
      enabled: true,
      pinned: false,
      usageCount: 21,
      updatedAt: '1d',
      copy: {
        en: {
          title: 'Hierarchy depth: default to three layers',
          preview: 'Use presentation, logic, and data layers as the preferred architecture skeleton.',
        },
        zh: {
          title: '层级深度：默认 3 层架构',
          preview: '展示层 / 逻辑层 / 数据层作为首选骨架。',
        },
      },
    },
    {
      id: 4,
      title: 'Boundary naming: make domain edges explicit',
      preview: 'Label module boundaries in complex systems to keep responsibilities clear.',
      source: 'manual',
      enabled: false,
      pinned: false,
      usageCount: 9,
      updatedAt: '3d',
      copy: {
        en: {
          title: 'Boundary naming: make domain edges explicit',
          preview: 'Label module boundaries in complex systems to keep responsibilities clear.',
        },
        zh: {
          title: '边界命名：域边界优先显式',
          preview: '在复杂系统中强制标注模块边界，避免责任漂移。',
        },
      },
    },
  ],
  style: [
    {
      id: 11,
      title: 'Primary palette: blue-violet gradient',
      preview: 'Use brand blue-violet on core nodes and avoid high-saturation red unless needed.',
      source: 'ai',
      enabled: true,
      pinned: true,
      usageCount: 33,
      updatedAt: '4h',
      copy: {
        en: {
          title: 'Primary palette: blue-violet gradient',
          preview: 'Use brand blue-violet on core nodes and avoid high-saturation red unless needed.',
        },
        zh: {
          title: '主品牌色：蓝紫渐变',
          preview: '核心节点优先使用品牌蓝紫，降低高饱和红使用频次。',
        },
      },
    },
    {
      id: 12,
      title: 'Geometry: 12px corner radius',
      preview: 'Keep cards and nodes on a consistent radius for a calmer visual system.',
      source: 'manual',
      enabled: true,
      pinned: false,
      usageCount: 26,
      updatedAt: '8h',
      copy: {
        en: {
          title: 'Geometry: 12px corner radius',
          preview: 'Keep cards and nodes on a consistent radius for a calmer visual system.',
        },
        zh: {
          title: '几何特征：12px 圆角',
          preview: '统一卡片与节点圆角，保持视觉一致性。',
        },
      },
    },
    {
      id: 13,
      title: 'Line baseline: 1.5px',
      preview: 'Use 1.5px strokes in dense diagrams to balance sharpness and readability.',
      source: 'ai',
      enabled: true,
      pinned: false,
      usageCount: 18,
      updatedAt: '1d',
      copy: {
        en: {
          title: 'Line baseline: 1.5px',
          preview: 'Use 1.5px strokes in dense diagrams to balance sharpness and readability.',
        },
        zh: {
          title: '线条基准：1.5px',
          preview: '信息密集图中采用 1.5px 线宽，平衡锐度与清晰度。',
        },
      },
    },
    {
      id: 14,
      title: 'Annotation placement: quiet bottom-right notes',
      preview: 'Keep notes below the main flow hierarchy so they do not steal focus.',
      source: 'manual',
      enabled: false,
      pinned: false,
      usageCount: 7,
      updatedAt: '2d',
      copy: {
        en: {
          title: 'Annotation placement: quiet bottom-right notes',
          preview: 'Keep notes below the main flow hierarchy so they do not steal focus.',
        },
        zh: {
          title: '注释排版：右下角弱化',
          preview: '备注信息视觉层级低于主流程，不抢主路径焦点。',
        },
      },
    },
  ],
  layout: [],
};

const normalizeDnaRuleLocale = (locale?: string | null): DnaRuleLocale => (
  locale && DNA_RULE_LOCALES.has(locale) ? locale as DnaRuleLocale : DEFAULT_DNA_LOCALE
);

// New scopes start with the user's own preferences, never fabricated activity.
// The legacy seed copy below is retained only to localize already-saved rules.
const buildInitialRules = (): Record<CabinId, Rule[]> => ({
  structure: [],
  style: [],
  layout: [],
});

const matchesSeedCopy = (rule: Rule, seed: SeedRule): boolean => (
  Object.values(seed.copy).some((copy) => (
    rule.title === copy.title && rule.preview === copy.preview
  ))
);

const localizeSeedRules = (
  rules: Record<CabinId, Rule[]>,
  locale?: string | null,
): Record<CabinId, Rule[]> => {
  const normalizedLocale = normalizeDnaRuleLocale(locale);
  return {
    structure: rules.structure.map((rule) => {
      const seed = seedRules.structure.find((candidate) => candidate.id === rule.id);
      return seed && matchesSeedCopy(rule, seed)
        ? { ...rule, ...seed.copy[normalizedLocale] }
        : rule;
    }),
    style: rules.style.map((rule) => {
      const seed = seedRules.style.find((candidate) => candidate.id === rule.id);
      return seed && matchesSeedCopy(rule, seed)
        ? { ...rule, ...seed.copy[normalizedLocale] }
        : rule;
    }),
    layout: rules.layout,
  };
};

export function guestLoadDnaRules(scopeId?: string | null, locale?: string | null): Record<CabinId, Rule[]> {
  return loadDnaRulesForScope(scopeId, locale);
}

function dnaRulesKey(scopeId?: string | null): string {
  return scopeId ? `evodiagram_user_dna_${scopeId}` : GUEST_DNA_KEY;
}

export function hasDnaRulesForScope(scopeId?: string | null): boolean {
  return localStorage.getItem(dnaRulesKey(scopeId)) !== null;
}

export function loadDnaRulesForScope(scopeId?: string | null, locale?: string | null): Record<CabinId, Rule[]> {
  try {
    const raw = localStorage.getItem(dnaRulesKey(scopeId));
    if (!raw) return buildInitialRules();
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && ('structure' in parsed)) {
      return localizeSeedRules(parsed as Record<CabinId, Rule[]>, locale);
    }
    return buildInitialRules();
  } catch {
    return buildInitialRules();
  }
}

export function guestSaveDnaRules(rules: Record<CabinId, Rule[]>, scopeId?: string | null): void {
  localStorage.setItem(dnaRulesKey(scopeId), JSON.stringify(rules));
}

// ---- Project-Specific DNA Rules ----

const projectDnaKey = (projectId: string) => `evodiagram_project_dna_${projectId}`;
const scopedProjectDnaKey = (projectId: string, scopeId?: string | null) => (
  scopeId ? `evodiagram_user_${scopeId}_project_dna_${projectId}` : projectDnaKey(projectId)
);

export function guestLoadProjectDnaRules(
  projectId: string,
  scopeId?: string | null,
  locale?: string | null,
): Record<CabinId, Rule[]> | null {
  try {
    const raw = localStorage.getItem(scopedProjectDnaKey(projectId, scopeId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && 'structure' in parsed
      ? localizeSeedRules(parsed as Record<CabinId, Rule[]>, locale)
      : null;
  } catch {
    return null;
  }
}

export function guestSaveProjectDnaRules(projectId: string, rules: Record<CabinId, Rule[]>, scopeId?: string | null): void {
  localStorage.setItem(scopedProjectDnaKey(projectId, scopeId), JSON.stringify(rules));
}

export function guestDeleteProjectDnaRules(projectId: string, scopeId?: string | null): void {
  localStorage.removeItem(scopedProjectDnaKey(projectId, scopeId));
}

export function guestHasProjectDna(projectId: string, scopeId?: string | null): boolean {
  return localStorage.getItem(scopedProjectDnaKey(projectId, scopeId)) !== null;
}
