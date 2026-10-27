import type { UploadedAsset } from '../types/api';

export const classifyAssetType = (file: File): UploadedAsset['type'] => {
  if (file.type.startsWith('image/')) return 'image';
  if (/\.(csv|xlsx?|json|txt)$/i.test(file.name)) return 'dataset';
  return 'sketch';
};

export const parseJsonObject = (raw: unknown): Record<string, unknown> | null => {
  if (!raw) return null;
  if (typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw !== 'string') return null;

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === 'object') {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch {
    return null;
  }
};

export type CanvasPayloadKind = 'excalidraw' | 'tldraw';
export type CanvasPayloadInspectionStatus = 'valid' | 'empty' | 'invalid' | 'mismatch' | 'missing';

export type CanvasPayloadInspection = {
  status: CanvasPayloadInspectionStatus;
  kind: CanvasPayloadKind | null;
  expectedKind?: CanvasPayloadKind;
  payload: Record<string, unknown> | null;
  nodeCount: number;
};

const isObjectRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

export const isExcalidrawPayload = (payloadLike: unknown): payloadLike is Record<string, unknown> => {
  return isObjectRecord(payloadLike) && Array.isArray(payloadLike.elements);
};

export const isTldrawPayload = (payloadLike: unknown): payloadLike is Record<string, unknown> => {
  if (!isObjectRecord(payloadLike)) {
    return false;
  }

  const document = payloadLike.document;

  return (
    (isObjectRecord(document) && isObjectRecord(payloadLike.session))
    || isObjectRecord(payloadLike.records)
    || isObjectRecord(payloadLike.store)
  );
};

export const detectCanvasPayloadKind = (payloadLike: unknown): CanvasPayloadKind | null => {
  if (isExcalidrawPayload(payloadLike)) {
    return 'excalidraw';
  }

  if (isTldrawPayload(payloadLike)) {
    return 'tldraw';
  }

  return null;
};

const countExcalidrawNodes = (payload: Record<string, unknown>): number => {
  if (!Array.isArray(payload.elements)) {
    return 0;
  }

  return payload.elements.filter((element) => isObjectRecord(element)).length;
};

type TldrawRecordContainerKind =
  | 'documentStore'
  | 'rootStore'
  | 'documentRecords'
  | 'rootRecords'
  | 'missing';

const getTldrawRecordContainer = (
  schema: Record<string, unknown>,
): { records: Record<string, unknown>; kind: TldrawRecordContainerKind } => {
  const document = isObjectRecord(schema.document) ? schema.document : null;

  if (document && isObjectRecord(document.store)) {
    return { records: document.store, kind: 'documentStore' };
  }

  if (isObjectRecord(schema.store)) {
    return { records: schema.store, kind: 'rootStore' };
  }

  if (document && isObjectRecord(document.records)) {
    return { records: document.records, kind: 'documentRecords' };
  }

  if (isObjectRecord(schema.records)) {
    return { records: schema.records, kind: 'rootRecords' };
  }

  return { records: {}, kind: 'missing' };
};

const countTldrawShapeNodes = (payload: Record<string, unknown>): number => {
  const records = getTldrawRecordContainer(payload).records;
  return Object.values(records)
    .filter(isObjectRecord)
    .filter((record) => record.typeName === 'shape')
    .length;
};

export const inspectCanvasPayload = (
  payloadLike: unknown,
  expectedKind?: CanvasPayloadKind,
): CanvasPayloadInspection => {
  const payload = parseJsonObject(payloadLike);

  if (!payload) {
    return {
      status: 'missing',
      kind: null,
      expectedKind,
      payload: null,
      nodeCount: 0,
    };
  }

  const kind = detectCanvasPayloadKind(payload);
  if (!kind) {
    return {
      status: 'invalid',
      kind: null,
      expectedKind,
      payload,
      nodeCount: 0,
    };
  }

  const nodeCount = kind === 'excalidraw'
    ? countExcalidrawNodes(payload)
    : countTldrawShapeNodes(payload);

  if (expectedKind && kind !== expectedKind) {
    return {
      status: 'mismatch',
      kind,
      expectedKind,
      payload,
      nodeCount,
    };
  }

  return {
    status: nodeCount > 0 ? 'valid' : 'empty',
    kind,
    expectedKind,
    payload,
    nodeCount,
  };
};

const withTldrawRecordContainer = (
  schema: Record<string, unknown>,
  records: Record<string, unknown>,
  kind: TldrawRecordContainerKind,
): Record<string, unknown> => {
  const document = isObjectRecord(schema.document) ? schema.document : null;

  if (kind === 'documentStore' || (kind === 'missing' && document && isObjectRecord(schema.session))) {
    return {
      ...schema,
      document: {
        ...(document ?? {}),
        store: records,
      },
    };
  }

  if (kind === 'rootStore') {
    return {
      ...schema,
      store: records,
    };
  }

  if (kind === 'documentRecords') {
    return {
      ...schema,
      document: {
        ...(document ?? {}),
        records,
      },
    };
  }

  return {
    ...schema,
    records,
  };
};

export const normalizeTldrawSchemaForLocalEdit = (
  schema: Record<string, unknown>,
): Record<string, unknown> => ({
  records: getTldrawRecordContainer(schema).records,
});

export const splitCanvasPayload = (
  payloadLike: unknown,
): { tldrawSnapshot: Record<string, unknown> | undefined; excalidrawPayload: string } => {
  const payload = parseJsonObject(payloadLike);
  const kind = detectCanvasPayloadKind(payload);

  if (kind === 'tldraw') {
    return {
      tldrawSnapshot: payload ?? undefined,
      excalidrawPayload: '',
    };
  }

  if (kind === 'excalidraw') {
    return {
      tldrawSnapshot: undefined,
      excalidrawPayload: JSON.stringify(payload ?? {}),
    };
  }

  return {
    tldrawSnapshot: undefined,
    excalidrawPayload: '',
  };
};

/**
 * Extract all node/shape IDs from a canvas schema blob.
 * Works for both Excalidraw (elements[].id) and tldraw (records{}.id where typeName==='shape').
 */
export const getAllNodeIds = (schema: Record<string, unknown>): string[] => {
  // Excalidraw: { elements: [{id, ...}] }
  if (Array.isArray(schema.elements)) {
    return (schema.elements as Array<{ id?: string }>)
      .map((el) => el.id)
      .filter((id): id is string => typeof id === 'string');
  }

  const records = getTldrawRecordContainer(schema).records;
  if (Object.keys(records).length > 0) {
    return Object.values(records)
      .filter(isObjectRecord)
      .filter((r) => r.typeName === 'shape')
      .map((r) => r.id)
      .filter((id): id is string => typeof id === 'string');
  }

  return [];
};

// --- Snapshot document signatures -------------------------------------------
//
// Signatures are ONLY ever compared for equality (dirty checks, auto-sync
// dedupe, history switches); no call site parses them as content. They must
// never be displayed, stored as data, or diffed.
//
// COMPATIBILITY: the excalidraw signature format changed from a full
// JSON.stringify of the document to the folded digest below (see
// foldExcalidrawDocumentSignature). Signatures persisted before this change -
// the server-side last synced state, recovery drafts in sessionStorage - can
// never equal a freshly computed one, so the first load after the upgrade
// detects "changed" once and performs a single re-sync. That is an accepted
// one-time cost of the algorithm switch.

const SIGNATURE_FNV_PRIME = 16777619;
const SIGNATURE_SEED_A = 0x811c9dc5;
const SIGNATURE_SEED_B = 0x01000193;

/** 32-bit FNV-1a string hash. Only stability matters, not range. */
const hashString32 = (input: string, seed: number): number => {
  let hash = seed;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, SIGNATURE_FNV_PRIME);
  }
  return hash | 0;
};

const hex36 = (value: number): string => (value >>> 0).toString(36);

/** Legacy signature: full serialization of the document part. Kept as the
 * fallback for payloads whose elements lack reliable version metadata. */
const stringifyExcalidrawSignature = (payload: Record<string, unknown>): string | null => {
  const appState = isObjectRecord(payload.appState) ? payload.appState : {};
  const files = isObjectRecord(payload.files) ? payload.files : {};
  const documentPart = {
    elements: payload.elements,
    files,
    appState: {
      viewBackgroundColor: appState.viewBackgroundColor ?? null,
    },
  };

  try {
    return JSON.stringify(documentPart);
  } catch {
    return null;
  }
};

/**
 * Cheap order-sensitive fold over an excalidraw scene, replacing the full
 * JSON.stringify that used to run on every throttled snapshot change.
 *
 * Excalidraw guarantees `version` (incremented) and `versionNonce`
 * (regenerated) change on every element mutation, so folding
 * id-hash + version + versionNonce per element detects every content edit
 * without serializing anything. The element fold is order-dependent (FNV-style
 * xor-then-multiply) because array order carries z-order; the file fold is a
 * commutative sum because file map key order is not guaranteed to survive a
 * JSON round-trip through the backend. Two independent 32-bit lanes give a
 * 64-bit digest, keeping accidental collisions out of practical range for a
 * change-detection gate.
 *
 * Returns null when any element lacks finite numeric version/versionNonce
 * (hand-built or LLM-merged payloads), so the caller can fall back to the
 * exact full-serialization signature instead of risking a blind spot.
 */
const foldExcalidrawSignature = (payload: Record<string, unknown>): string | null => {
  const elements = payload.elements as unknown[];
  let laneA = SIGNATURE_SEED_A;
  let laneB = SIGNATURE_SEED_B;

  for (const element of elements) {
    if (!isObjectRecord(element)) {
      return null;
    }
    const version = element.version;
    const versionNonce = element.versionNonce;
    if (
      typeof version !== 'number' || !Number.isFinite(version)
      || typeof versionNonce !== 'number' || !Number.isFinite(versionNonce)
    ) {
      return null;
    }
    const id = typeof element.id === 'string' ? element.id : String(element.id ?? '');
    const deleted = element.isDeleted === true ? 1 : 0;
    const foldA = (hashString32(id, SIGNATURE_SEED_A) + Math.imul(version, 0x9e3779b1) + versionNonce + deleted) | 0;
    const foldB = (hashString32(id, SIGNATURE_SEED_B) + Math.imul(versionNonce, 0x85ebca6b) + Math.imul(version, 31) + deleted) | 0;
    laneA = Math.imul(laneA ^ foldA, SIGNATURE_FNV_PRIME);
    laneB = Math.imul(laneB ^ foldB, SIGNATURE_FNV_PRIME);
  }

  const files = isObjectRecord(payload.files) ? payload.files : {};
  let fileLaneA = 0;
  let fileLaneB = 0;
  let fileCount = 0;
  for (const [fileId, file] of Object.entries(files)) {
    if (!isObjectRecord(file)) {
      return null;
    }
    const dataUrlLength = typeof file.dataURL === 'string' ? file.dataURL.length : 0;
    fileLaneA = (fileLaneA + hashString32(fileId, SIGNATURE_SEED_A) + dataUrlLength) | 0;
    fileLaneB = (fileLaneB + hashString32(fileId, SIGNATURE_SEED_B) + Math.imul(dataUrlLength, SIGNATURE_FNV_PRIME)) | 0;
    fileCount += 1;
  }

  const appState = isObjectRecord(payload.appState) ? payload.appState : {};
  const background = String(appState.viewBackgroundColor ?? '');

  return `exd2:${elements.length}:${fileCount}:${hex36(laneA)}${hex36(laneB)}:${hex36(fileLaneA)}${hex36(fileLaneB)}:${hex36(hashString32(background, SIGNATURE_SEED_A))}${hex36(hashString32(background, SIGNATURE_SEED_B))}`;
};

type SnapshotSignatureStats = {
  computeCount: number;
  lastDurationMs: number;
  lastElementCount: number;
  lastAlgorithm: 'fold' | 'stringify' | 'none';
};

declare global {
  interface Window {
    /** DEV-only instrumentation; read by frontend/browser-regression.mjs to
     * verify the snapshot-change throttle on the real hot path. */
    __evoSnapshotSignatureStats?: SnapshotSignatureStats;
  }
}

export const getSnapshotDocSignature = (snapshotLike: unknown): string | null => {
  if (!snapshotLike || typeof snapshotLike !== 'object') {
    return null;
  }

  const instrument = import.meta.env.DEV && typeof window !== 'undefined';
  const startedAt = instrument ? performance.now() : 0;

  const payload = snapshotLike as Record<string, unknown>;
  let signature: string | null;
  let elementCount = 0;
  let algorithm: SnapshotSignatureStats['lastAlgorithm'] = 'none';

  if (Array.isArray(payload.elements)) {
    elementCount = payload.elements.length;
    signature = foldExcalidrawSignature(payload);
    if (signature !== null) {
      algorithm = 'fold';
    } else {
      signature = stringifyExcalidrawSignature(payload);
      algorithm = signature !== null ? 'stringify' : 'none';
    }
  } else {
    // tldraw branch: TLRecord carries no per-record version/nonce field
    // (BaseRecord is just { id, typeName }), so there is no cheap equivalent
    // fold. Keep the full serialization; like the excalidraw path it only runs
    // at the throttled snapshot-change boundary in useDiagramSync (~100ms),
    // not per store mutation.
    const document = isObjectRecord(payload.document) ? payload.document : null;
    const documentPart = (
      document && isObjectRecord(document.store)
        ? document.store
        : isObjectRecord(payload.store)
          ? payload.store
          : document && isObjectRecord(document.records)
            ? document.records
            : isObjectRecord(payload.records)
              ? payload.records
              : payload.document ?? payload
    ) as unknown;

    try {
      signature = JSON.stringify(documentPart);
      algorithm = signature !== null ? 'stringify' : 'none';
    } catch {
      signature = null;
    }
  }

  if (instrument) {
    const stats = (window.__evoSnapshotSignatureStats ??= {
      computeCount: 0,
      lastDurationMs: 0,
      lastElementCount: 0,
      lastAlgorithm: 'none',
    });
    stats.computeCount += 1;
    stats.lastDurationMs = performance.now() - startedAt;
    stats.lastElementCount = elementCount;
    stats.lastAlgorithm = algorithm;
  }

  return signature;
};

const DIAGRAM_MAP_KEY = 'diagram_project_snapshot_map';

/**
 * Update the localStorage mapping from diagramId to project/snapshot IDs.
 * Silently ignores localStorage failures.
 */
export const updateDiagramProjectSnapshotMap = (
  diagramId: string,
  projectId: string,
  snapshotId: string,
): void => {
  try {
    const raw = localStorage.getItem(DIAGRAM_MAP_KEY);
    const map = raw ? JSON.parse(raw) : {};
    map[String(diagramId)] = { project_id: projectId, snapshot_id: snapshotId };
    localStorage.setItem(DIAGRAM_MAP_KEY, JSON.stringify(map));
  } catch {
    // ignore localStorage failures
  }
};

/**
 * Merge modified nodes delta into current canvas schema.
 * Supports both excalidraw and tldraw formats.
 *
 * Handles three operations:
 * - Update: Replace existing nodes with modified versions
 * - Add: Append new nodes to the schema
 * - Delete: Remove only explicitly named selected nodes
 *
 * @param currentSchema - Full current canvas schema
 * @param modifiedNodes - Modified nodes returned by LLM (only selected nodes)
 * @param canvasLibrary - Canvas type
 * @param selectedNodeIds - IDs of nodes that are allowed to be changed
 */
export const mergeDeltaIntoSchema = (
  currentSchema: Record<string, unknown>,
  modifiedNodes: Record<string, unknown>,
  canvasLibrary: 'excalidraw' | 'tldraw',
  selectedNodeIds?: string[],
): Record<string, unknown> => {
  const selected = new Set(selectedNodeIds || []);
  const deleted = new Set(Array.isArray(modifiedNodes.deleted_ids)
    ? modifiedNodes.deleted_ids.filter((id): id is string => typeof id === 'string' && selected.has(id))
    : []);
  if (canvasLibrary === 'excalidraw') {
    const current = (currentSchema.elements as Array<Record<string, unknown>>) || [];
    // A selected container owns its bound label; AI text edits may update it.
    for (const element of current) {
      if (typeof element.containerId === 'string' && selected.has(element.containerId)) selected.add(String(element.id));
    }
    const updates = (modifiedNodes.elements as Array<Record<string, unknown>>) || [];
    const existing = new Set(current.map(element => element.id));
    const changes = new Map(updates.filter(element => element && typeof element.id === 'string'
      && (!existing.has(element.id) || selected.has(element.id))).map(element => [element.id, element]));
    // Bound text follows deletion of its container. Node icons are reconciled by the canvas.
    for (const element of current) {
      if (typeof element.containerId === 'string' && deleted.has(element.containerId)) deleted.add(element.id as string);
    }
    const elements = current.map(element => {
      const id = element.id as string;
      const change = changes.get(id);
      if (!change && !deleted.has(id)) return element;
      return { ...element, ...change, ...(deleted.has(id) ? { isDeleted: true } : {}),
        version: Number(element.version || 0) + 1,
        versionNonce: Math.floor(Math.random() * 2147483647), updated: Date.now() };
    });
    for (const [id, change] of changes) {
      if (!existing.has(id)) elements.push(change);
    }
    return { ...currentSchema, elements };
  }
  const { records, kind } = getTldrawRecordContainer(currentSchema);
  const merged = { ...records };
  for (const id of deleted) delete merged[id];
  for (const [id, record] of Object.entries(merged)) {
    if (isObjectRecord(record) && record.typeName === 'binding'
      && (deleted.has(String(record.fromId)) || deleted.has(String(record.toId)))) delete merged[id];
  }
  for (const [id, change] of Object.entries(modifiedNodes.records || {})) {
    if (!(id in records) || selected.has(id)) merged[id] = change;
  }
  return withTldrawRecordContainer(currentSchema, merged, kind);
};
