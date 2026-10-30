import { BROWSER_MODE } from './browser/runtime';
import { parseGenerationReport } from '../utils/generationReport';
import type {
  BackendDnaAnalyzeResponse,
  BackendDnaRuleSchema,
  BackendDnaRulesPayload,
  BackendProjectCreateRequest,
  BackendProjectCreateResponse,
  BackendProjectListItem,
  BackendProjectListResponse,
  DiagramType,
  DiagramRequest,
  DiagramResponse,
  ProjectSnapshotResponse,
  SchemaSyncPayload,
  SchemaSyncResult,
} from '../types/api';
import type { RecentCanvasLibrary, RecentDiagram } from '../types/app';
import type { BackendProjectDetailResponse } from '../contracts/backendApi.generated';
import { normalizeBackendTimestamp } from '../utils/projectHistory';
import type { CabinId, Rule } from '../types/dna';
import { AUTH_USER_ID_STORAGE_KEY } from '../features/auth/authEvents';
import { readLocalStorage } from '../utils/safeLocalStorage';
import { createBlankExcalidrawScene } from '../utils/blankCanvas';
import { normalizeCanvasLibraryOrNull } from '../contracts/canvas';
import {
  isGuest,
  guestSaveDiagram,
  guestFetchRecentDiagrams,
  guestDeleteDiagram,
  guestFetchProjectSnapshots,
  guestSyncProjectSchema,
  GuestProjectNotFoundError,
  type GuestSaveResult,
} from './guestStorage';
import {
  ApiError,
  apiV1Url,
  getStoredAuthToken,
  notifyIfUnauthorized,
  readResponseDetail,
  requireStoredAuthToken,
} from './httpClient';

export { ApiError, getStoredAuthToken, isApiError } from './httpClient';

const BACKEND_DIAGRAM_TYPE_ALIASES: Record<string, DiagramType> = {
  automated: 'automated',
  architecture: 'architecture',
  class: 'architecture',
  class_diagram: 'architecture',
  flow: 'flow',
  flowchart: 'flow',
  data_flow_diagram: 'flow',
  swimlane: 'flow',
  swimlane_diagram: 'flow',
  sequence: 'sequence',
  sequence_diagram: 'sequence',
  state_diagram: 'sequence',
  er: 'er',
  er_diagram: 'er',
  entity_relationship: 'er',
  mindmap: 'mindmap',
  mind_map: 'mindmap',
  network: 'network',
  network_topology: 'network',
};

const normalizeBackendDiagramType = (value: string | null | undefined): DiagramType => {
  if (!value) return 'automated';
  const normalized = value.trim().toLowerCase().replace(/[-\s]+/g, '_');
  return BACKEND_DIAGRAM_TYPE_ALIASES[normalized] ?? 'automated';
};

/**
 * Guest-only: save the generated diagram to localStorage.
 * For logged-in users, the backend auto-persists via _persist_result during streaming.
 */
type SaveDiagramResult = {
  ok: true;
  source: 'guest' | 'backend_noop';
} & Partial<GuestSaveResult>;

export async function saveDiagram(
  request: DiagramRequest,
  response: DiagramResponse,
  _userId: string | number,
): Promise<SaveDiagramResult> {
  void _userId;
  if (isGuest()) {
    const saved = guestSaveDiagram(request, response);
    return { ok: true, source: 'guest', ...saved };
  }

  // For logged-in users, generate stream already persists data.
  // No-op to avoid duplicate writes to the old diagrams table.
  return { ok: true, source: 'backend_noop' };
}

type FetchRecentDiagramsOptions = {
  limit?: number;
  offset?: number;
};

type ProjectCreatePayload = Omit<BackendProjectCreateRequest, 'canvas_engine'> & {
  canvas_library?: RecentCanvasLibrary | null;
  canvas_engine?: RecentCanvasLibrary | null;
};

const normalizeProjectListLimit = (value: number | undefined): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 20;
  return Math.min(100, Math.max(1, Math.trunc(value ?? 20)));
};

export async function fetchRecentDiagrams(
  _userId: string | number,
  options: FetchRecentDiagramsOptions = {},
): Promise<RecentDiagram[]> {
  void _userId;
  const limit = normalizeProjectListLimit(options.limit);
  const offset = Math.max(0, Math.trunc(options.offset ?? 0));

  if (isGuest()) {
    return guestFetchRecentDiagrams().slice(offset, offset + limit);
  }

  const token = requireStoredAuthToken();
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });

  const res = await fetch(apiV1Url(`/projects?${query.toString()}`), {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
    const detail = await readResponseDetail(res, '获取项目列表失败');
    throw new ApiError(detail, res.status, detail);
  }

  const data = await res.json() as BackendProjectListResponse;
  const projects: BackendProjectListItem[] = Array.isArray(data.projects) ? data.projects : [];

  return projects.map((p) => {
    const projectId = p.project_id ?? '';
    const latestSnapshotId = p.latest_snapshot_id ?? null;
    const latestSchema = p.latest_schema ?? null;
    const canvasLibrary = normalizeCanvasLibraryOrNull(p.canvas_library ?? p.canvas_engine);
    const fallbackTimestamp = new Date().toISOString();
    const createdAt = normalizeBackendTimestamp(p.created_at || fallbackTimestamp);
    const updatedAt = normalizeBackendTimestamp(p.updated_at || createdAt);

    return {
      id: projectId,
      request_id: projectId,
      diagram_id: latestSnapshotId || projectId,
      project_id: projectId,
      snapshot_id: p.latest_snapshot_id || null,
      project_version: p.version,
      prompt: p.source_text || p.title || '',
      diagram_type: normalizeBackendDiagramType(p.diagram_type),
      summary: p.title,
      excalidraw_payload: canvasLibrary === 'excalidraw' ? latestSchema : null,
      tldraw_snapshot: canvasLibrary === 'tldraw' ? latestSchema : null,
      canvas_library: canvasLibrary,
      thumbnail_url: p.thumbnail_url || null,
      created_at: createdAt,
      updated_at: updatedAt,
      snapshot_count: typeof p.snapshot_count === 'number' ? p.snapshot_count : 0,
    };
  });
}

/** Load one saved workspace directly, including projects outside the recent page. */
export async function fetchProjectDiagram(projectId: string): Promise<RecentDiagram> {
  if (isGuest()) {
    const project = guestFetchRecentDiagrams().find(item => item.project_id === projectId);
    if (!project) throw new ApiError('Project not found', 404);
    return project;
  }
  const token = requireStoredAuthToken();
  const [response, history] = await Promise.all([
    fetch(apiV1Url(`/projects/${encodeURIComponent(projectId)}`), { headers: { Authorization: `Bearer ${token}` } }),
    fetchProjectSnapshots({ projectId, pageSize: 1 }),
  ]);
  if (!response.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(response);
    const detail = await readResponseDetail(response, 'Project could not be loaded');
    throw new ApiError(detail, response.status, detail);
  }
  const project = await response.json() as BackendProjectDetailResponse;
  const snapshot = history.snapshots[0];
  const currentSnapshot = snapshot?.snapshot_id === project.current_snapshot_id ? snapshot : undefined;
  const canvas = normalizeCanvasLibraryOrNull(project.canvas_library ?? project.canvas_engine);
  const schema = project.latest_schema ?? (canvas === 'excalidraw' ? createBlankExcalidrawScene() : null);
  return {
    id: projectId, project_id: projectId, request_id: projectId,
    diagram_id: project.current_snapshot_id ?? projectId, snapshot_id: project.current_snapshot_id ?? undefined,
    project_version: project.version,
    generation_report: currentSnapshot?.generation_report ?? parseGenerationReport(currentSnapshot?.metrics_scores),
    prompt: project.source_text ?? '', summary: project.title,
    diagram_type: normalizeBackendDiagramType(project.diagram_type), canvas_library: canvas,
    excalidraw_payload: canvas === 'excalidraw' ? schema : null,
    tldraw_snapshot: canvas === 'tldraw' ? schema : null,
    thumbnail_url: project.thumbnail_url,
    created_at: normalizeBackendTimestamp(project.created_at),
    updated_at: normalizeBackendTimestamp(project.updated_at), snapshot_count: history.total,
  };
}

export async function createProject(payload: ProjectCreatePayload): Promise<BackendProjectCreateResponse> {
  const token = requireStoredAuthToken();
  const canvasLibrary = payload.canvas_library ?? payload.canvas_engine ?? 'excalidraw';

  const res = await fetch(apiV1Url('/projects'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      title: payload.title ?? null,
      diagram_type: payload.diagram_type ?? 'automated',
      canvas_library: canvasLibrary,
      source_text: payload.source_text ?? null,
    }),
  });

  if (!res.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
    const detail = await readResponseDetail(res, '创建项目失败');
    throw new ApiError(detail, res.status, detail);
  }

  return await res.json() as BackendProjectCreateResponse;
}

export async function createBlankCanvasProject(request: DiagramRequest, title: string): Promise<RecentDiagram> {
  const schema = createBlankExcalidrawScene();
  const createdAt = new Date().toISOString();
  if (isGuest()) {
    const saved = guestSaveDiagram({ ...request, prompt: '', diagramType: 'automated',
      metadata: { canvasLibrary: 'excalidraw' } }, {
      requestId: request.id, diagramId: request.id, generatedAt: createdAt, summary: title,
      previewImage: '', excalidrawPayload: JSON.stringify(schema), rawSchemaBlob: schema,
    }, { editSource: 'MANUAL_CREATE' });
    return fetchProjectDiagram(saved.projectId);
  }
  const project = await createProject({ title, diagram_type: 'automated', canvas_library: 'excalidraw', source_text: '' });
  const synced = await syncProjectSchema({ project_id: project.project_id, schema_patch: schema,
    editor: 'excalidraw', base_snapshot_id: null, create_snapshot: true, version: project.version ?? 1 });
  return { id: project.project_id, project_id: project.project_id, request_id: request.id,
    diagram_id: synced.snapshot_id, snapshot_id: synced.snapshot_id, project_version: synced.version,
    prompt: '', diagram_type: 'automated', summary: title, canvas_library: 'excalidraw',
    excalidraw_payload: synced.latest_schema, created_at: normalizeBackendTimestamp(project.created_at), updated_at: createdAt };
}

export async function updateProjectTitle(projectId: string, title: string): Promise<void> {
  if (isGuest()) {
    return;
  }

  const token = requireStoredAuthToken();

  const res = await fetch(apiV1Url(`/projects/${encodeURIComponent(projectId)}`), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ title }),
  });

  if (!res.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
    const detail = await readResponseDetail(res, '更新项目名称失败');
    throw new Error(detail);
  }
}

export async function deleteProject(projectId: string): Promise<void> {
  if (isGuest()) {
    guestDeleteDiagram(projectId);
    return;
  }

  const token = requireStoredAuthToken();

  const res = await fetch(apiV1Url(`/projects/${encodeURIComponent(projectId)}`), {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
    const detail = await readResponseDetail(res, '删除项目失败');
    throw new Error(detail);
  }
}

export async function updateUserProfile(payload: { username?: string; name?: string; avatar_url?: string }) {
  const token = requireStoredAuthToken();

  const res = await fetch(apiV1Url('/users/profile'), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      username: payload.username ?? payload.name,
      avatar_url: payload.avatar_url,
    }),
  });

  if (!res.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
    const detail = await readResponseDetail(res, '更新个人信息失败');
    throw new Error(detail);
  }

  return res.json();
}

export async function fetchProjectSnapshots(params: {
  projectId: string;
  withTrace?: boolean;
  page?: number;
  pageSize?: number;
}): Promise<ProjectSnapshotResponse> {
  if (isGuest()) {
    return guestFetchProjectSnapshots(params.projectId);
  }

  const token = requireStoredAuthToken();

  const query = new URLSearchParams({
    with_trace: String(Boolean(params.withTrace)),
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 20),
  });

  const res = await fetch(apiV1Url(`/projects/${encodeURIComponent(params.projectId)}/snapshots?${query.toString()}`), {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
    const detail = await readResponseDetail(res, '获取项目快照失败');
    throw new ApiError(detail, res.status, detail);
  }

  const data = await res.json() as ProjectSnapshotResponse;
  return { ...data, snapshots: data.snapshots.map(snapshot => ({ ...snapshot, timestamp: normalizeBackendTimestamp(snapshot.timestamp), project_version: data.project_version })) };
}

// ---------------------------------------------------------------------------
// DNA API
// ---------------------------------------------------------------------------

/** Extract DNA rule candidates from a design image (works for guests too). */
export async function analyzeDnaImage(
  file: File,
): Promise<Array<{ tempId: number; cabinId: CabinId; title: string; preview: string }>> {
  if (BROWSER_MODE) throw new Error('Image-based preference extraction requires the full local edition.');
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(apiV1Url('/dna/analyze'), {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) return [];
    const data = await res.json() as BackendDnaAnalyzeResponse;
    const candidates = data.candidates ?? [];
    return candidates
      .filter((c) => ['structure', 'style', 'layout'].includes(c.cabin_id))
      .map((c) => ({
        tempId: c.temp_id,
        cabinId: c.cabin_id as CabinId,
        title: c.title,
        preview: c.preview,
      }));
  } catch {
    // DNA extraction is optional; the UI stays usable without candidates.
    return [];
  }
}

/** Load user's DNA rules from the backend. Returns null for guests / on error. */
export async function loadDnaRules(
  projectId?: string,
  capturedToken?: string,
  ownerId?: string,
): Promise<Record<CabinId, Rule[]> | null> {
  const token = capturedToken ?? getStoredAuthToken();
  if (!token) return null;

  try {
    await dnaSaveQueues.get(dnaQueueKey(token, projectId, ownerId));
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    const res = await fetch(apiV1Url(`/dna/rules${query}`), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
      return null;
    }
    const data = await res.json() as BackendDnaRulesPayload;
    return _parseBackendRules(data);
  } catch {
    // Treat network or parse errors as "no backend DNA available".
    return null;
  }
}

// Serialize replacements for a given identity and project. An earlier slow save
// must never arrive after a newer edit, including across page remounts.
const dnaSaveQueues = new Map<string, Promise<boolean>>();
function dnaQueueKey(token: string, projectId?: string, ownerId?: string): string {
  return JSON.stringify([ownerId ? 'user' : 'token', ownerId ?? token, projectId ?? null]);
}

/** Capture the originating identity before queuing; never read a new login later. */
export function saveDnaRules(
  rules: Record<CabinId, Rule[]>,
  projectId?: string,
  options?: { token?: string; keepalive?: boolean; ownerId?: string },
): Promise<boolean> {
  const token = options?.token ?? getStoredAuthToken();
  if (!token) return Promise.resolve(false);
  const body = JSON.stringify({
    structure: rules.structure.map((r) => _ruleToBackend(r, 'structure', projectId)),
    style: rules.style.map((r) => _ruleToBackend(r, 'style', projectId)),
    layout: rules.layout.map((r) => _ruleToBackend(r, 'layout', projectId)),
    project_id: projectId ?? null,
  });
  const key = dnaQueueKey(token, projectId, options?.ownerId);
  const previous = dnaSaveQueues.get(key) ?? Promise.resolve(true);
  const request = previous.then(async () => {
    try {
      const res = await fetch(apiV1Url('/dna/rules'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body,
        // Only small payloads are eligible for keepalive (browser limit is 64 KiB).
        keepalive: options?.keepalive === true && new Blob([body]).size < 60000,
      });
      if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
      return res.ok;
    } catch {
      return false;
    }
  });
  dnaSaveQueues.set(key, request);
  void request.finally(() => { if (dnaSaveQueues.get(key) === request) dnaSaveQueues.delete(key); });
  return request;
}

function _parseBackendRules(
  data: BackendDnaRulesPayload,
): Record<CabinId, Rule[]> {
  let idCounter = 1;

  const parseList = (list: BackendDnaRuleSchema[] | undefined): Rule[] =>
    (list ?? []).map((item) => {
      // The backend is starting to return its stored primary key. Preserve it
      // so a later save can update the row in place; tolerate its absence
      // (older backends) by leaving ruleId unset and deriving one on save.
      const backendRuleId = typeof item.rule_id === 'string' && item.rule_id.trim()
        ? item.rule_id
        : undefined;
      return {
        id: idCounter++,
        ruleId: backendRuleId,
        title: item.title ?? '',
        preview: item.preview ?? '',
        source: (item.source === 'manual' ? 'manual' : 'ai') as Rule['source'],
        enabled: Boolean(item.enabled ?? true),
        pinned: Boolean(item.pinned ?? false),
        usageCount: Number(item.usage_count ?? 0),
        updatedAt: item.updated_at ?? new Date().toISOString(),
      };
    });

  return {
    structure: parseList(data.structure),
    style: parseList(data.style),
    layout: parseList(data.layout),
  };
}

/** Deterministic 32-bit FNV-1a hash, rendered as base36. */
function _hash36(input: string, seed: number): string {
  let hash = seed;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

/**
 * Build a stable `rule_id` for the backend primary key.
 *
 * Fallback for rules that carry no backend-assigned `ruleId` (locally seeded
 * rules, guest rules, or responses from backends predating the field): the
 * numeric `id` is renumbered from 1 on every load, so identity is derived from
 * the values that survive the round trip: the owning scope plus the cabin and
 * the title. `dna_rules.rule_id` is a globally unique primary key, so the
 * user/project scope is part of the input - without it two users sharing a
 * rule title (the seeded starter rules do) would derive the same id and
 * collide on insert.
 */
function _dnaRuleId(rule: Rule, cabinId: CabinId, projectId?: string): string {
  // The cached user id is the stable scope; the token only backs up sessions
  // stored before that key existed (unique per user, just less stable).
  const userScope = readLocalStorage(AUTH_USER_ID_STORAGE_KEY) ?? getStoredAuthToken() ?? 'anonymous';
  const key = `${userScope}|${projectId ?? 'global'}|${cabinId}|${rule.title}`;
  // Two seeds => ~64 bits, still far below the 36-char column limit.
  return `dna_${_hash36(key, 0x811c9dc5)}${_hash36(key, 0x01000193)}`;
}

function _ruleToBackend(rule: Rule, cabinId: CabinId, projectId?: string): BackendDnaRuleSchema {
  return {
    // Reuse the backend-assigned id when we have one so an edit (e.g. a title
    // change) updates the same row instead of deleting and re-creating it.
    // Fall back to the deterministic hash for rules that never came from the
    // backend (locally seeded, guest, or pre-`rule_id` responses), which keeps
    // today's behaviour byte-for-byte when the field is absent.
    rule_id: rule.ruleId ?? _dnaRuleId(rule, cabinId, projectId),
    cabin_id: cabinId,
    title: rule.title,
    preview: rule.preview,
    source: rule.source,
    enabled: rule.enabled,
    pinned: rule.pinned,
    usage_count: rule.usageCount,
    updated_at: rule.updatedAt ?? new Date().toISOString(),
  };
}

export async function syncProjectSchema(
  payload: SchemaSyncPayload,
  options: { signal?: AbortSignal } = {},
): Promise<SchemaSyncResult> {
  if (isGuest()) {
    if (!payload.project_id.startsWith('guest_')) {
      throw new ApiError('Authentication required to sync this project', 401);
    }

    try {
      return guestSyncProjectSchema(payload);
    } catch (error) {
      if (error instanceof GuestProjectNotFoundError) {
        throw new ApiError('Guest project is no longer available', 404);
      }
      throw error;
    }
  }

  // Every formal write, including snapshot imports, carries its expected version.
  if (payload.version == null) {
    throw new ApiError('Reload project history before saving an unversioned document', 409);
  }

  const token = requireStoredAuthToken();

  const res = await fetch(apiV1Url('/schema/sync'), {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      project_id: payload.project_id,
      schema_patch: payload.schema_patch,
      editor: payload.editor ?? 'excalidraw',
      base_snapshot_id: payload.base_snapshot_id ?? null,
      create_snapshot: Boolean(payload.create_snapshot),
      version: payload.version ?? null,
    }),
    signal: options.signal,
  });

  if (!res.ok) {
    if (getStoredAuthToken() === token) notifyIfUnauthorized(res);
    const detail = await readResponseDetail(res, '同步 schema 失败');
    throw new ApiError(detail, res.status, detail);
  }

  return res.json();
}
