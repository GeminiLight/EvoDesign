import type {
  StreamErrorEvent,
  StreamRefineCompleteEvent,
  StreamRefineErrorEvent,
  StreamRefineStatus,
  StreamResultEvent,
  StreamStage,
  StreamStageCompleteEvent,
  StreamStageEvent,
  StreamStageStartEvent,
} from '../types/api';
import {
  STREAM_ERROR_STAGES,
  STREAM_REFINE_STATUSES,
  STREAM_STAGES,
} from '../contracts/streamEvents';

const STREAM_STAGE_VALUES = new Set<string>(STREAM_STAGES);
const STREAM_ERROR_STAGE_VALUES = new Set<string>(STREAM_ERROR_STAGES);
const STREAM_REFINE_STATUS_VALUES = new Set<string>(STREAM_REFINE_STATUSES);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isOptionalNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || isNullableString(value);
}

function isOptionalNullableRecord(value: unknown): value is Record<string, unknown> | null | undefined {
  return value === undefined || value === null || isRecord(value);
}

function isOptionalBoolean(value: unknown): value is boolean | undefined {
  return value === undefined || typeof value === 'boolean';
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string';
}

function isStreamStage(value: unknown): value is StreamStage {
  return typeof value === 'string' && STREAM_STAGE_VALUES.has(value);
}

function isStreamErrorStage(value: unknown): value is StreamErrorEvent['stage'] {
  return typeof value === 'string' && STREAM_ERROR_STAGE_VALUES.has(value);
}

function isStreamRefineStatus(value: unknown): value is StreamRefineStatus {
  return typeof value === 'string' && STREAM_REFINE_STATUS_VALUES.has(value);
}

function isBaseStreamStageEvent(value: unknown): value is StreamStageStartEvent {
  return isRecord(value)
    && isStreamStage(value.stage)
    && isFiniteNumber(value.stage_index)
    && isFiniteNumber(value.total_stages)
    && typeof value.message === 'string';
}

export function isStreamStageStartEvent(value: unknown): value is StreamStageStartEvent {
  return isBaseStreamStageEvent(value)
    && !('duration_ms' in value);
}

export function isStreamStageCompleteEvent(value: unknown): value is StreamStageCompleteEvent {
  return isBaseStreamStageEvent(value)
    && isFiniteNumber((value as unknown as Record<string, unknown>).duration_ms);
}

export function isStreamStageEvent(value: unknown): value is StreamStageEvent {
  return isStreamStageStartEvent(value) || isStreamStageCompleteEvent(value);
}

export function isStreamRefineCompleteEvent(value: unknown): value is StreamRefineCompleteEvent {
  return isRecord(value)
    && isFiniteNumber(value.fixes_applied)
    && isStreamRefineStatus(value.status)
    && typeof value.message === 'string';
}

export function isStreamRefineErrorEvent(value: unknown): value is StreamRefineErrorEvent {
  return isRecord(value)
    && typeof value.message === 'string'
    && typeof value.detail === 'string';
}

export function isRefinerSkippedEvent(value: unknown): value is { message: string } {
  return isRecord(value) && typeof value.message === 'string';
}

export function isStreamResultEvent(value: unknown): value is StreamResultEvent {
  return isRecord(value)
    && typeof value.request_id === 'string'
    && isNullableString(value.project_id)
    && isNullableString(value.snapshot_id)
    && isRecord(value.schema_blob)
    && isOptionalNullableRecord(value.thought_trace)
    && isOptionalNullableRecord(value.metrics_scores)
    && typeof value.summary === 'string'
    && isOptionalNullableString(value.thumbnail_url)
    && isOptionalBoolean(value.persist_error)
    && isOptionalString(value.persist_error_message);
}

export function isStreamErrorEvent(value: unknown): value is StreamErrorEvent {
  return isRecord(value)
    && isStreamErrorStage(value.stage)
    && typeof value.message === 'string'
    && typeof value.detail === 'string';
}

export function assertStreamPayload<T>(
  value: unknown,
  predicate: (payload: unknown) => payload is T,
  eventType: string,
): T {
  if (predicate(value)) {
    return value;
  }
  throw new Error(`Malformed ${eventType} stream event`);
}
