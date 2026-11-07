// Ported from backend/app/services/workflow_runtime/event_payloads.py and
// backend/app/core/sse.py — keep in sync (PHASE3_PLAN.md WP29).
//
// Typed public payloads for the generation SSE events. The pydantic models are
// ``extra="forbid", strict=True``; here each payload is built by a function
// that validates the same constraints and returns a plain object whose key
// order equals ``model_dump()`` (field declaration order) — the frontend parses
// the JSON text, so key order is part of the contract.

import { ValueError } from '../py/errors.ts';
import { pyJsonDumps } from '../py/json.ts';

export const STREAM_STAGE_VALUES = [
  'memory', 'structure', 'styling', 'layout', 'render', 'verification', 'refining', 'final_verification', 'learning',
] as const;
export const STREAM_ERROR_STAGE_VALUES = [...STREAM_STAGE_VALUES, 'init', 'generation', 'rewrite'] as const;
export const REFINE_COMPLETE_STATUSES = ['completed', 'skipped', 'failed', 'unresolved'] as const;
export const STREAM_EVENT_TYPES = [
  'stage_start', 'stage_complete', 'refine_complete', 'refine_error', 'refiner_skipped', 'result', 'error',
] as const;

export type StreamStage = (typeof STREAM_STAGE_VALUES)[number];
export type StreamErrorStage = (typeof STREAM_ERROR_STAGE_VALUES)[number];
export type RefineCompleteStatus = (typeof REFINE_COMPLETE_STATUSES)[number];
export type StreamEventType = (typeof STREAM_EVENT_TYPES)[number];

/** ``pydantic.ValidationError`` raised by a strict public payload model. */
export class PayloadValidationError extends ValueError {}

function fail(model: string, field: string, message: string): never {
  throw new PayloadValidationError(`1 validation error for ${model}\n${field}\n  ${message}`);
}

function strictStr(model: string, field: string, value: unknown): string {
  if (typeof value !== 'string') fail(model, field, 'Input should be a valid string');
  return value;
}

function strictInt(model: string, field: string, value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) fail(model, field, 'Input should be a valid integer');
  return value;
}

function literal<T extends string>(model: string, field: string, value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    fail(model, field, `Input should be ${allowed.map((v) => `'${v}'`).join(', ')}`);
  }
  return value as T;
}

function optionalStr(model: string, field: string, value: unknown): string | null {
  return value === null || value === undefined ? null : strictStr(model, field, value);
}

function dict(model: string, field: string, value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(model, field, 'Input should be a valid dictionary');
  return value as Record<string, unknown>;
}

export interface StageStartPayload { stage: StreamStage; stage_index: number; total_stages: number; message: string }
export interface StageCompletePayload extends StageStartPayload { duration_ms: number }
export interface RefineCompletePayload { fixes_applied: number; status: RefineCompleteStatus; message: string }
export interface RefineErrorPayload { message: string; detail: string }
export interface RefinerSkippedPayload { message: string }
export interface StreamErrorPayload { stage: StreamErrorStage; message: string; detail: string }

export function StageStartPayload(fields: { stage: string; stage_index: number; total_stages: number; message: string }): StageStartPayload {
  const m = 'StageStartPayload';
  return {
    stage: literal(m, 'stage', fields.stage, STREAM_STAGE_VALUES),
    stage_index: strictInt(m, 'stage_index', fields.stage_index),
    total_stages: strictInt(m, 'total_stages', fields.total_stages),
    message: strictStr(m, 'message', fields.message),
  };
}

export function StageCompletePayload(
  fields: { stage: string; stage_index: number; total_stages: number; message: string; duration_ms: number },
): StageCompletePayload {
  const m = 'StageCompletePayload';
  return {
    stage: literal(m, 'stage', fields.stage, STREAM_STAGE_VALUES),
    stage_index: strictInt(m, 'stage_index', fields.stage_index),
    total_stages: strictInt(m, 'total_stages', fields.total_stages),
    message: strictStr(m, 'message', fields.message),
    duration_ms: strictInt(m, 'duration_ms', fields.duration_ms),
  };
}

/**
 * Refiner outcome reported to the client. ``fixes_applied`` counts edits that
 * actually landed on the manifest, not edits the refiner proposed.
 */
export function RefineCompletePayload(fields: { fixes_applied: number; status: string; message: string }): RefineCompletePayload {
  const m = 'RefineCompletePayload';
  return {
    fixes_applied: strictInt(m, 'fixes_applied', fields.fixes_applied),
    status: literal(m, 'status', fields.status, REFINE_COMPLETE_STATUSES),
    message: strictStr(m, 'message', fields.message),
  };
}

export function RefineErrorPayload(fields: { message: string; detail: string }): RefineErrorPayload {
  const m = 'RefineErrorPayload';
  return { message: strictStr(m, 'message', fields.message), detail: strictStr(m, 'detail', fields.detail) };
}

export function RefinerSkippedPayload(fields: { message: string }): RefinerSkippedPayload {
  return { message: strictStr('RefinerSkippedPayload', 'message', fields.message) };
}

export function StreamErrorPayload(fields: { stage: string; message: string; detail: string }): StreamErrorPayload {
  const m = 'StreamErrorPayload';
  return {
    stage: literal(m, 'stage', fields.stage, STREAM_ERROR_STAGE_VALUES),
    message: strictStr(m, 'message', fields.message),
    detail: strictStr(m, 'detail', fields.detail),
  };
}

export interface StreamResultFields {
  request_id: string;
  project_id: string | null;
  snapshot_id: string | null;
  schema_blob: Record<string, unknown>;
  thought_trace?: Record<string, unknown> | null;
  metrics_scores?: Record<string, unknown> | null;
  summary: string;
  thumbnail_url?: string | null;
  persist_error?: boolean | null;
  persist_error_message?: string | null;
}

/** ``StreamResultPayload(...).to_public_dict()``: absent persistence fields are dropped. */
export function StreamResultPayload(fields: StreamResultFields): Record<string, unknown> {
  const m = 'StreamResultPayload';
  const optionalDict = (field: string, value: unknown) => (value === null || value === undefined ? null : dict(m, field, value));
  const payload: Record<string, unknown> = {
    request_id: strictStr(m, 'request_id', fields.request_id),
    project_id: optionalStr(m, 'project_id', fields.project_id),
    snapshot_id: optionalStr(m, 'snapshot_id', fields.snapshot_id),
    schema_blob: dict(m, 'schema_blob', fields.schema_blob),
    thought_trace: optionalDict('thought_trace', fields.thought_trace),
    metrics_scores: optionalDict('metrics_scores', fields.metrics_scores),
    summary: strictStr(m, 'summary', fields.summary),
    thumbnail_url: optionalStr(m, 'thumbnail_url', fields.thumbnail_url),
    persist_error: fields.persist_error ?? null,
    persist_error_message: optionalStr(m, 'persist_error_message', fields.persist_error_message),
  };
  if (payload.persist_error !== null && typeof payload.persist_error !== 'boolean') fail(m, 'persist_error', 'Input should be a valid boolean');
  for (const key of ['thumbnail_url', 'persist_error', 'persist_error_message']) {
    if (payload[key] === null) delete payload[key];
  }
  return payload;
}

// ── app/core/sse.py ──────────────────────────────────────────────────────

/** One parsed backend SSE event (``SseEvent``). */
export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

/** ``format_sse_event``: the backend SSE wire format (``json.dumps(..., ensure_ascii=False)``). */
export function format_sse_event(event_name: string, data: Record<string, unknown>): string {
  return `event: ${event_name}\ndata: ${pyJsonText(data)}\n\n`;
}

/** ``parse_sse_event``: null when the chunk has no JSON object data. */
export function parse_sse_event(chunk: string): SseEvent | null {
  let event_name: string | null = null;
  const data_lines: string[] = [];
  for (const line of chunk.trim().split(/\r\n|\r|\n/)) {
    if (line.startsWith('event: ')) event_name = line.slice('event: '.length);
    else if (line.startsWith('data: ')) data_lines.push(line.slice('data: '.length));
  }
  if (!event_name || !data_lines.length) return null;
  let data: unknown;
  try {
    data = JSON.parse(data_lines.join('\n'));
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  return { event: event_name, data: data as Record<string, unknown> };
}

/** ``json.dumps(data, ensure_ascii=False)`` (default separators ``", "`` / ``": "``). */
function pyJsonText(data: unknown): string {
  return pyJsonDumps(data, { ensureAscii: false });
}
