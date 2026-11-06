// Ported from backend/app/services/workflow_runtime/events.py — keep in sync
// (PHASE3_PLAN.md WP29). SSE event payload helpers for workflow streaming.
//
// ``format_workflow_sse`` returns the wire text like Python; the TS adapter
// yields ``WorkflowEvent`` objects instead (``{event, data}``) and callers
// that need the wire format use ``format_workflow_sse``.

import { ValueError } from '../py/errors.ts';
import {
  REFINE_COMPLETE_STATUSES,
  RefineCompletePayload,
  RefinerSkippedPayload,
  StageCompletePayload,
  StageStartPayload,
  format_sse_event,
  type RefineCompleteStatus,
} from './event_payloads.ts';
import {
  PUBLIC_REFINER_DEGRADED_MESSAGE,
  PUBLIC_REFINER_DISABLED_MESSAGE,
  PUBLIC_REFINER_NOT_NEEDED_MESSAGE,
  PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE,
} from './errors.ts';

/** One event of the generation stream (the parsed form of an SSE chunk). */
export interface WorkflowEvent {
  event: string;
  data: Record<string, unknown>;
}

export const STREAMING_STAGES: ReadonlyArray<readonly [string, string]> = [
  ['structure', 'Analyzing document structure...'],
  ['styling', 'Designing visual styles...'],
  ['layout', 'Computing layout positions...'],
  ['render', 'Rendering final diagram...'],
];

/** Stable public completion state for the optional refiner stream event. */
export class RefineCompletion {
  constructor(readonly fixes_applied: number, readonly status: RefineCompleteStatus, readonly message: string) {}

  public_payload(): Record<string, unknown> {
    return refine_complete_payload({ fixes_applied: this.fixes_applied, status: this.status, message: this.message });
  }
}

export function format_workflow_sse(event: string, payload: Record<string, unknown>): string {
  return format_sse_event(event, payload);
}

/** The TS adapter's equivalent of ``format_workflow_sse``: an event object. */
export function workflow_event(event: string, payload: object): WorkflowEvent {
  return { event, data: payload as Record<string, unknown> };
}

/** Python ``str.capitalize()``: first character upper-cased, the rest lower-cased. */
export function pyCapitalize(text: string): string {
  const chars = Array.from(text);
  if (!chars.length) return text;
  return chars[0].toUpperCase() + chars.slice(1).join('').toLowerCase();
}

export function stage_start_payload(
  { stage, stage_index, total_stages, message }: { stage: string; stage_index: number; total_stages: number; message: string },
): Record<string, unknown> {
  return { ...StageStartPayload({ stage, stage_index, total_stages, message }) };
}

export function stage_complete_payload(
  { stage, stage_index, total_stages, duration_ms, message = null }:
  { stage: string; stage_index: number; total_stages: number; duration_ms: number; message?: string | null },
): Record<string, unknown> {
  return {
    ...StageCompletePayload({
      stage,
      stage_index,
      total_stages,
      message: message || `${pyCapitalize(stage)} complete`,
      duration_ms,
    }),
  };
}

export function refine_complete_payload(
  { fixes_applied, status, message }: { fixes_applied: number; status: string; message: string },
): Record<string, unknown> {
  if (!(REFINE_COMPLETE_STATUSES as readonly string[]).includes(status)) {
    throw new ValueError(`Unknown refiner completion status: ${status}`);
  }
  return { ...RefineCompletePayload({ fixes_applied, status, message }) };
}

export function refine_completed_completion(fixes_applied: number): RefineCompletion {
  return new RefineCompletion(fixes_applied, 'completed', `Auto-fixed ${fixes_applied} visual issue(s)`);
}

export function refine_unresolved_completion(
  { fixes_applied, termination_reason }: { fixes_applied: number; termination_reason: string | null },
): RefineCompletion {
  const reason = termination_reason || 'not_converged';
  return new RefineCompletion(fixes_applied, 'unresolved', `Refiner did not converge (${reason}); keeping the base diagram.`);
}

export function refine_failed_completion(): RefineCompletion {
  return new RefineCompletion(0, 'failed', PUBLIC_REFINER_DEGRADED_MESSAGE);
}

export function refine_skipped_completion(message: string = PUBLIC_REFINER_NOT_NEEDED_MESSAGE): RefineCompletion {
  return new RefineCompletion(0, 'skipped', message);
}

export function refine_unsupported_canvas_completion(): RefineCompletion {
  return refine_skipped_completion(PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE);
}

export function refiner_skipped_payload(): Record<string, unknown> {
  return { ...RefinerSkippedPayload({ message: PUBLIC_REFINER_DISABLED_MESSAGE }) };
}
