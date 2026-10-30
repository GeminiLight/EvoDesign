import { ApiError, apiV1Url, getStoredAuthToken, notifyIfUnauthorized } from './httpClient';

export type AgentConnection = {
  connection_id: string; project_id: string | null; name: string; status: string;
  can_commit: boolean; expires_at: number; context_version: number;
};
export type AgentConstraints = {
  dna: Array<{ cabin: string; title: string; description: string }>;
  locked_ids: string[]; constraints_hash: string; source: string;
};
export type AgentDocument = {
  project_id: string; title: string | null; version: number; snapshot_id: string | null;
  canvas_library: 'excalidraw' | 'tldraw'; schema: Record<string, unknown>;
  constraints: AgentConstraints; web_url: string; metrics_scores?: Record<string, unknown> | null;
  capabilities: { semantic_edit: boolean; operations: string[] };
};
export type AgentProposal = {
  proposal_id: string; project_id: string; base_version: number; status: string; changed_ids: string[];
  report: { message?: string; code?: string; warnings?: string[]; issues?: Array<{ message: string; severity: string }> };
  committed_version: number | null; committed_snapshot_id: string | null; expires_at: number; author_kind: string;
};
export type AgentCheckpoint = { snapshot_id: string; is_checkpoint: boolean; edit_source: string; created_at: string };

function requestSignal(parent: AbortSignal | null | undefined, milliseconds: number) {
  const controller = new AbortController();
  const abort = () => controller.abort(parent?.reason);
  if (parent?.aborted) abort(); else parent?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => controller.abort(new DOMException('Request timed out', 'TimeoutError')), milliseconds);
  return { signal: controller.signal, close: () => { clearTimeout(timer); parent?.removeEventListener('abort', abort); } };
}

export async function agentRequest<T>(path: string, init: RequestInit = {}, timeout = 15000): Promise<T> {
  const token = getStoredAuthToken();
  if (!token) throw new ApiError('Sign in to connect an Agent', 401, undefined, 'authentication_required');
  const request = requestSignal(init.signal, timeout);
  try {
  const response = await fetch(apiV1Url(path), { ...init, headers: {
    'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init.headers,
  }, signal: request.signal });
  if (getStoredAuthToken() !== token) throw new DOMException('Account changed', 'AbortError');
  const payload = await response.json();
  if (!response.ok) {
    notifyIfUnauthorized(response);
    const error = payload.error ?? payload.detail;
    throw new ApiError(error?.message ?? (typeof error === 'string' ? error : 'Request failed'), response.status,
      undefined, error?.code);
  }
  if (payload.protocol_version !== 1 || payload.ok !== true) throw new ApiError('Update the backend to use Agent collaboration', 502);
  return payload.data as T;
  } finally { request.close(); }
}

export const projectAgentPath = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;
export const proposalPath = (projectId: string, id: string) => `${projectAgentPath(projectId)}/agent-proposals/${encodeURIComponent(id)}`;

export async function readAgentDocument(projectId: string, signal?: AbortSignal): Promise<AgentDocument> {
  const doc = await agentRequest<AgentDocument>(`${projectAgentPath(projectId)}/document`, { signal });
  if (doc.project_id !== projectId || !Number.isInteger(doc.version) || doc.version < 1
    || !doc.schema || typeof doc.schema !== 'object' || !['excalidraw', 'tldraw'].includes(doc.canvas_library)) {
    throw new ApiError('Saved document is unavailable', 502);
  }
  return doc;
}

export async function agentPreviewUrl(projectId: string, proposalId: string, signal?: AbortSignal): Promise<string> {
  return privateImageUrl(`${proposalPath(projectId, proposalId)}/preview`, signal);
}

export async function savedDocumentPreviewUrl(projectId: string, version: number, signal?: AbortSignal): Promise<string> {
  return privateImageUrl(`${projectAgentPath(projectId)}/document/preview?version=${version}`, signal);
}

async function privateImageUrl(path: string, signal?: AbortSignal): Promise<string> {
  const token = getStoredAuthToken();
  const request = requestSignal(signal, 50000);
  try {
  const response = await fetch(apiV1Url(path), {
    headers: { Authorization: `Bearer ${token}` }, signal: request.signal,
  });
  if (getStoredAuthToken() !== token) throw new DOMException('Account changed', 'AbortError');
  if (!response.ok || !response.headers.get('content-type')?.startsWith('image/png')) throw new ApiError('Preview is unavailable', response.status, undefined, 'render_failed');
  return URL.createObjectURL(await response.blob());
  } finally { request.close(); }
}

export function agentErrorMessage(error: unknown, t: (key: string) => string): string {
  if (error instanceof ApiError && error.code) {
    const key = `agent.errors.${error.code}`;
    const translated = t(key);
    if (translated !== key) return translated;
  }
  return t('agent.requestFailed');
}
