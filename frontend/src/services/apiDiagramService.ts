import { BROWSER_MODE } from './browser/runtime';
import { readAgentDocument } from './agentApi';
import { loadDnaRules } from './backendApi';
import { flushDnaDraft } from '../utils/dnaSyncDraft';
import { parseGenerationReport } from '../utils/generationReport';
import type {
  DiagramRequest,
  DiagramResponse,
  DiagramService,
  StreamStageCompleteEvent,
  StreamStageStartEvent,
  StreamRefineCompleteEvent,
  StreamRefineErrorEvent,
  StreamResultEvent,
  StreamErrorEvent,
  DiagramLocalEditRequest,
  DiagramLocalEditResponse,
  CanvasLibrary,
  BackendDiagramGenerateRequest,
  BackendDiagramGenerateResponse,
} from '../types/api';
import {
  ApiError,
  apiV1Url,
  getStoredAuthToken,
  readResponseDetail,
} from './httpClient';
import { guestLoadDnaRules, guestLoadProjectDnaRules } from './guestStorage';
import { getSnapshotDocSignature, inspectCanvasPayload, splitCanvasPayload } from '../utils/app';
import { AUTH_USER_ID_STORAGE_KEY, notifyAuthInvalidated } from '../features/auth/authEvents';
import { normalizeCanvasLibraryOrDefault } from '../contracts/canvas';
import {
  assertStreamPayload,
  isRefinerSkippedEvent,
  isStreamErrorEvent,
  isStreamRefineCompleteEvent,
  isStreamRefineErrorEvent,
  isStreamResultEvent,
  isStreamStageCompleteEvent,
  isStreamStageStartEvent,
} from './streamEventGuards';

const GENERATE_TIMEOUT_MS = 600_000; // 10 minutes
const GENERATION_CANCELLED_MESSAGE = 'Generation cancelled by user.';
const GENERATION_TIMEOUT_MESSAGE = 'Generation timeout: the request took too long. Please try again or simplify your prompt.';
const GENERATION_FAILED_MESSAGE = 'Diagram generation failed';
const LOCAL_EDIT_FAILED_MESSAGE = 'Local edit failed';

const DNA_CABIN_LABELS = {
  structure: 'Structure DNA',
  style: 'Style DNA',
  layout: 'Layout DNA',
} as const;
const LANGUAGE_STORAGE_KEY = 'smartdiagram_language';

function getStoredDnaRuleLocale(): 'en' | 'zh' {
  const storedLanguage = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  return storedLanguage === 'zh' ? 'zh' : 'en';
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function getGenerationAbortMessage(reason: 'timeout' | 'external' | null): string {
  return reason === 'external' ? GENERATION_CANCELLED_MESSAGE : GENERATION_TIMEOUT_MESSAGE;
}

async function buildGenerationHttpError(response: Response, isGuest: boolean): Promise<ApiError> {
  const detail = await readResponseDetail(response, GENERATION_FAILED_MESSAGE);

  if (response.status === 401) {
    notifyAuthInvalidated();
    return new ApiError(
      isGuest
        ? 'Guest access is unavailable. Please sign in to generate diagrams.'
        : 'Your session has expired. Please sign in again.',
      response.status,
      detail,
      isGuest ? 'generation_guest_unavailable' : 'generation_auth_expired',
    );
  }

  if (response.status === 429) {
    return new ApiError(
      "You've reached the generation limit. Please wait a minute before trying again.",
      response.status,
      detail,
      'generation_rate_limited',
    );
  }

  if (response.status === 400 || response.status === 422) {
    return new ApiError(
      'Generation request is invalid.',
      response.status,
      detail,
      'generation_invalid_request',
    );
  }

  return new ApiError(
    GENERATION_FAILED_MESSAGE,
    response.status,
    detail,
    response.status >= 500 ? 'generation_service_failed' : 'generation_failed',
  );
}

function getLocalEditErrorCode(response: Response, detail: string): string {
  if (response.status === 401) return 'local_edit_auth_expired';
  if (response.status === 429) return 'local_edit_rate_limited';
  if (response.status === 400 && /selected nodes were not found/i.test(detail)) {
    return 'local_edit_selection_missing';
  }
  if (response.status === 400 && /unsupported canvas library/i.test(detail)) {
    return 'local_edit_unsupported_canvas';
  }
  return 'local_edit_failed';
}

function buildDiagramRequirements(request: DiagramRequest): string {
  const baseRequirement = `Create a ${request.diagramType} diagram that visualizes the provided text.`;
  const projectId = request.metadata?.projectId;
  const userScopeId = BROWSER_MODE ? null : localStorage.getItem(AUTH_USER_ID_STORAGE_KEY);
  const dnaRuleLocale = getStoredDnaRuleLocale();
  const dnaRules = (
    projectId && guestLoadProjectDnaRules(projectId, userScopeId, dnaRuleLocale)
  ) || guestLoadDnaRules(userScopeId, dnaRuleLocale);
  const dnaSections = (Object.keys(DNA_CABIN_LABELS) as Array<keyof typeof DNA_CABIN_LABELS>)
    .map((cabinId) => {
      const cabinRules = dnaRules[cabinId];
      const rules = Array.isArray(cabinRules) ? cabinRules : [];
      const enabledRules = rules.filter((rule) => rule.enabled);
      if (enabledRules.length === 0) return null;

      return [
        `${DNA_CABIN_LABELS[cabinId]}:`,
        ...enabledRules.map((rule) => `- ${rule.title}: ${rule.preview}`),
      ].join('\n');
    })
    .filter((section): section is string => Boolean(section));

  if (dnaSections.length === 0) {
    return baseRequirement;
  }

  return [
    baseRequirement,
    '',
    'Apply these enabled user Design DNA rules when relevant. Treat them as preferences, not diagram content to render verbatim:',
    ...dnaSections,
  ].join('\n');
}

function parseCurrentSchema(value: string | undefined): Record<string, unknown> | null {
  return value ? JSON.parse(value) as Record<string, unknown> : null;
}

async function buildGenerateDiagramPayload(
  request: DiagramRequest,
  canvasLibrary: CanvasLibrary,
): Promise<BackendDiagramGenerateRequest> {
  const payload: BackendDiagramGenerateRequest = {
    context: request.prompt,
    diagram_type: request.diagramType === 'automated' ? null : request.diagramType,
    use_icons: request.useIcons ?? request.metadata?.useIcons === 'true',
    requirements: buildDiagramRequirements(request),
    locked_nodes: request.lockedNodes ?? [],
    project_id: request.metadata?.projectId ?? null,
    current_schema: parseCurrentSchema(request.metadata?.currentSchema),
    canvas_library: canvasLibrary,
  };
  const projectId = request.metadata?.projectId;
  if (projectId && getStoredAuthToken()) {
    const owner = localStorage.getItem(AUTH_USER_ID_STORAGE_KEY);
    if (owner) {
      flushDnaDraft(`evodesign:dna-pending:${owner}:global`);
      flushDnaDraft(`evodesign:dna-pending:${owner}:${projectId}`);
      const rules = await Promise.all([loadDnaRules(undefined, undefined, owner), loadDnaRules(projectId, undefined, owner)]);
      if (rules.some(value => !value)) throw new ApiError('Design preferences are unavailable', 503);
    }
    const expectedVersion = Number(request.metadata?.projectVersion);
    const doc = await readAgentDocument(projectId);
    const localSchema = parseCurrentSchema(request.metadata?.currentSchema);
    const sameContent = Boolean(localSchema && getSnapshotDocSignature(localSchema) === getSnapshotDocSignature(doc.schema));
    if (!Number.isInteger(expectedVersion) || doc.canvas_library !== canvasLibrary
      || (expectedVersion !== doc.version && !sameContent)) {
      throw new ApiError('The design changed. Review the saved version before generating.', 409, undefined, 'version_conflict');
    }
    payload.base_version = doc.version;
    payload.current_schema = doc.schema;
    payload.locked_nodes = [...new Set([...(request.lockedNodes ?? []), ...doc.constraints.locked_ids])];
    payload.requirements = [
      `Create a ${request.diagramType} diagram that visualizes the provided text.`,
      ...doc.constraints.dna.map(rule => `${rule.cabin}: ${rule.title}: ${rule.description}`),
    ].join('\n');
  }
  return payload;
}

export const apiDiagramService: DiagramService = {
  async generateDiagram(request: DiagramRequest): Promise<DiagramResponse> {
    if (BROWSER_MODE) {
      const { generateBrowserDiagram } = await import('./browser/diagramService');
      return generateBrowserDiagram(request, buildDiagramRequirements(request));
    }
    const authToken = getStoredAuthToken();
    const token = authToken || import.meta.env.VITE_GUEST_TOKEN || '';
    const isGuest = !authToken;
    const canvasLibrary = normalizeCanvasLibraryOrDefault(request.metadata?.canvasLibrary);
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), GENERATE_TIMEOUT_MS);

    let response: Response;
    try {
      const payload = await buildGenerateDiagramPayload(request, canvasLibrary);
      response = await fetch(apiV1Url('/diagram/generate'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new Error(GENERATION_TIMEOUT_MESSAGE);
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }

    if (!response.ok) {
      throw await buildGenerationHttpError(response, isGuest);
    }

    const data = await response.json() as BackendDiagramGenerateResponse;
    const splitPayload = splitCanvasPayload(data.schema_blob ?? {});
    const payloadInspection = inspectCanvasPayload(data.schema_blob ?? {}, canvasLibrary);
    const warnings = payloadInspection.status === 'valid'
      ? undefined
      : [`canvas_payload_${payloadInspection.status}`];

    return {
      generationReport: parseGenerationReport(data.metrics_scores),
      requestId: data.request_id || request.id,
      projectId: data.project_id ?? undefined,
      proposalId: data.proposal_id ?? undefined,
      persistError: data.persist_error,
      snapshotId: data.snapshot_id ?? undefined,
      projectVersion: data.version ?? undefined,
      diagramId: data.snapshot_id || `diagram_${Math.random().toString(36).slice(2, 8)}`,
      excalidrawPayload: splitPayload.excalidrawPayload,
      tldrawSnapshot: splitPayload.tldrawSnapshot,
      rawSchemaBlob: data.schema_blob ?? {},
      summary: data.summary || 'Generated successfully',
      previewImage: '',
      generatedAt: new Date().toISOString(),
      warnings,
    };
  },

  async editDiagramLocal(request: DiagramLocalEditRequest): Promise<DiagramLocalEditResponse> {
    if (BROWSER_MODE) {
      const { editBrowserDiagram } = await import('./browser/diagramService');
      return editBrowserDiagram(request);
    }
    const authToken = getStoredAuthToken();
    const token = authToken || import.meta.env.VITE_GUEST_TOKEN || '';

    const response = await fetch(apiV1Url('/diagram/edit-local'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      if (response.status === 401) {
        notifyAuthInvalidated();
      }
      const detail = await readResponseDetail(response, LOCAL_EDIT_FAILED_MESSAGE);
      throw new ApiError(
        LOCAL_EDIT_FAILED_MESSAGE,
        response.status,
        detail,
        getLocalEditErrorCode(response, detail),
      );
    }

    const result: DiagramLocalEditResponse = await response.json();
    return result;
  },
};

export interface StreamCallbacks {
  onProviderWait?: (seconds: number) => void;
  onStageStart?: (event: StreamStageStartEvent) => void;
  onStageComplete?: (event: StreamStageCompleteEvent) => void;
  onRefineComplete?: (event: StreamRefineCompleteEvent) => void;
  onRefineError?: (event: StreamRefineErrorEvent) => void;
  onRefinerSkipped?: (event: { message: string }) => void;
  onResult?: (event: StreamResultEvent) => void;
  onError?: (event: StreamErrorEvent) => void;
}

export interface StreamOptions {
  signal?: AbortSignal;
}

export async function generateDiagramStream(
  request: DiagramRequest,
  callbacks: StreamCallbacks,
  options: StreamOptions = {},
): Promise<DiagramResponse> {
  if (BROWSER_MODE) {
    const { generateBrowserDiagram } = await import('./browser/diagramService');
    return generateBrowserDiagram(request, buildDiagramRequirements(request), callbacks, options);
  }
  const authToken = getStoredAuthToken();
  const token = authToken || import.meta.env.VITE_GUEST_TOKEN || '';
  const isGuest = !authToken;
  const canvasLibrary = normalizeCanvasLibraryOrDefault(request.metadata?.canvasLibrary);
  const controller = new AbortController();
  let abortReason: 'timeout' | 'external' | null = null;
  const abortFromExternal = () => {
    abortReason = abortReason ?? 'external';
    controller.abort();
  };
  const abortOnTimeout = () => {
    abortReason = abortReason ?? 'timeout';
    controller.abort();
  };
  // A slow model may take several minutes per stage. Keep active streams
  // alive while retaining both an inactivity limit and a total upper bound.
  let timeoutId = window.setTimeout(abortOnTimeout, GENERATE_TIMEOUT_MS);
  const overallTimeoutId = window.setTimeout(abortOnTimeout, 3 * GENERATE_TIMEOUT_MS);
  const recordStageProgress = () => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(abortOnTimeout, GENERATE_TIMEOUT_MS);
  };

  if (options.signal?.aborted) {
    abortFromExternal();
  } else {
    options.signal?.addEventListener('abort', abortFromExternal, { once: true });
  }

  const cleanupAbortHandlers = () => {
    window.clearTimeout(timeoutId);
    window.clearTimeout(overallTimeoutId);
    options.signal?.removeEventListener('abort', abortFromExternal);
  };

  let response: Response;
  try {
    const payload = await buildGenerateDiagramPayload(request, canvasLibrary);
    response = await fetch(apiV1Url('/diagram/generate/stream'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (error) {
    cleanupAbortHandlers();
    if (isAbortError(error)) {
      throw new Error(getGenerationAbortMessage(abortReason));
    }
    throw error;
  }

  if (!response.ok) {
    cleanupAbortHandlers();
    throw await buildGenerationHttpError(response, isGuest);
  }

  // Parse SSE stream
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let resultData: StreamResultEvent | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on double newline (SSE event boundary)
      const parts = buffer.split('\n\n');
      // Keep the last incomplete part in the buffer
      buffer = parts.pop() || '';

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;
        if (trimmed === ': keepalive') {
          // Connection is alive during a model call; the overall deadline stays.
          recordStageProgress();
          continue;
        }

        let eventType = '';
        const dataLines: string[] = [];

        for (const line of trimmed.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            // One event may carry several `data:` lines; the backend encoder
            // joins them with "\n" (backend/app/core/sse.py), so collect every
            // line instead of overwriting and truncating the JSON.
            dataLines.push(line.slice(6));
          }
        }

        const dataStr = dataLines.join('\n');
        if (!eventType || !dataStr) continue;

        try {
          const parsed = JSON.parse(dataStr);

          switch (eventType) {
            case 'stage_start': {
              const event = assertStreamPayload(parsed, isStreamStageStartEvent, eventType);
              recordStageProgress();
              callbacks.onStageStart?.(event);
              break;
            }
            case 'stage_complete': {
              const event = assertStreamPayload(parsed, isStreamStageCompleteEvent, eventType);
              recordStageProgress();
              callbacks.onStageComplete?.(event);
              break;
            }
            case 'refine_complete': {
              const event = assertStreamPayload(parsed, isStreamRefineCompleteEvent, eventType);
              callbacks.onRefineComplete?.(event);
              break;
            }
            case 'refine_error': {
              const event = assertStreamPayload(parsed, isStreamRefineErrorEvent, eventType);
              callbacks.onRefineError?.(event);
              break;
            }
            case 'refiner_skipped': {
              const event = assertStreamPayload(parsed, isRefinerSkippedEvent, eventType);
              callbacks.onRefinerSkipped?.(event);
              break;
            }
            case 'result': {
              resultData = assertStreamPayload(parsed, isStreamResultEvent, eventType);
              callbacks.onResult?.(resultData);
              break;
            }
            case 'error': {
              const event = assertStreamPayload(parsed, isStreamErrorEvent, eventType);
              callbacks.onError?.(event);
              throw new ApiError(
                'Generation stage failed',
                500,
                event.detail || event.message,
                'generation_stage_failed',
              );
            }
          }
        } catch (e) {
          if (e instanceof SyntaxError) {
            // Dropping one malformed event must not kill the stream, but it
            // must not be invisible either: a dropped `result` event only
            // surfaces much later as "stream ended without a result event".
            const snippet = dataStr.length > 200 ? `${dataStr.slice(0, 200)}...` : dataStr;
            console.warn(`[diagram stream] dropped "${eventType}" event (SyntaxError): ${snippet}`, e);
            continue;
          }
          throw e;
        }
      }
    }
  } catch (error) {
    if (isAbortError(error)) {
      throw new Error(getGenerationAbortMessage(abortReason));
    }
    throw error;
  } finally {
    cleanupAbortHandlers();
  }

  if (!resultData) {
    throw new Error('Stream ended without a result event');
  }

  const splitPayload = splitCanvasPayload(resultData.schema_blob ?? {});
  const payloadInspection = inspectCanvasPayload(resultData.schema_blob ?? {}, canvasLibrary);
  const warnings = payloadInspection.status === 'valid'
    ? undefined
    : [`canvas_payload_${payloadInspection.status}`];

  return {
    generationReport: parseGenerationReport(resultData.metrics_scores),
    requestId: resultData.request_id || request.id,
    projectId: resultData.project_id ?? undefined,
    proposalId: resultData.proposal_id,
    snapshotId: resultData.snapshot_id ?? undefined,
    projectVersion: resultData.version ?? undefined,
    diagramId: resultData.snapshot_id || `diagram_${Math.random().toString(36).slice(2, 8)}`,
    excalidrawPayload: splitPayload.excalidrawPayload,
    tldrawSnapshot: splitPayload.tldrawSnapshot,
    rawSchemaBlob: resultData.schema_blob ?? {},
    summary: resultData.summary || 'Generated successfully',
    previewImage: '',
    thumbnailUrl: resultData.thumbnail_url ?? undefined,
    generatedAt: new Date().toISOString(),
    warnings,
    persistError: resultData.persist_error ?? false,
  };
}
